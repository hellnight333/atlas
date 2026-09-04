"""A pipeline that cannot lie about where a relationship stands.

Every stage here is derived from evidence, so these tests are mostly about the
lies a stored-stage CRM tells and this one cannot:

* `contacted` when nothing was sent — here it requires a message row that says
  `sent`;
* a stage that stays optimistic after a company goes quiet — here silence
  becomes `dormant` on its own;
* a next action with no reason, which nobody can check or disagree with;
* an action that looks available when a credential is missing — here the
  blocker is named, in the same vocabulary the agent floor uses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from atlas_kernel.crm import ActionKind, Stage, board, relationship
from atlas_kernel.opportunity.models import (
    Business,
    BusinessEvent,
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    Opportunity,
    OpportunityStage,
    OutreachMessage,
    OutreachStatus,
    Severity,
)
from atlas_kernel.qevik import Wiring, create_app

NOW = datetime(2026, 9, 4, tzinfo=UTC)


@pytest.fixture
def client(tmp_path):
    app = create_app(Wiring(repository_root=tmp_path, vault_path=tmp_path / "vault.json"))
    with TestClient(app) as test_client:
        yield test_client


def a_business(**kwargs) -> Business:
    return Business(id=kwargs.pop("id", "biz-1"), name=kwargs.pop("name", "Al Noor Dental"),
                    geography=kwargs.pop("geography", "dubai"), **kwargs)


def a_finding(**kwargs) -> Finding:
    return Finding(
        id=kwargs.pop("id", "find-1"),
        business_id=kwargs.pop("business_id", "biz-1"),
        kind=kwargs.pop("kind", FindingKind.NO_HTTPS),
        severity=kwargs.pop("severity", Severity.HIGH),
        statement=kwargs.pop("statement", "the site is served over http"),
        evidence=kwargs.pop("evidence", [Evidence(kind=EvidenceKind.HTTP_RESPONSE,
                                                  source="http://alnoor.example",
                                                  summary="served over http on port 80")]),
        detected_at=kwargs.pop("detected_at", NOW - timedelta(days=1)),
        **kwargs)


def an_opportunity(**kwargs) -> Opportunity:
    return Opportunity(
        id=kwargs.pop("id", "opp-1"), business_id=kwargs.pop("business_id", "biz-1"),
        niche=kwargs.pop("niche", "dental"), findings=kwargs.pop("findings", []),
        stage=kwargs.pop("stage", OpportunityStage.QUALIFIED),
        score=kwargs.pop("score", 72.0), **kwargs)


def a_message(status: OutreachStatus, **kwargs) -> OutreachMessage:
    return OutreachMessage(
        id=kwargs.pop("id", "msg-1"), proposal_id=kwargs.pop("proposal_id", "prop-1"),
        business_id=kwargs.pop("business_id", "biz-1"),
        channel=kwargs.pop("channel", "email"),
        recipient=kwargs.pop("recipient", "hello@alnoor.example"),
        subject=kwargs.pop("subject", "Your website"), body=kwargs.pop("body", "..."),
        status=status, created_at=kwargs.pop("created_at", NOW - timedelta(days=2)),
        **kwargs)


def an_event(kind: str, days_ago: int = 1, **kwargs) -> BusinessEvent:
    return BusinessEvent(id=kwargs.pop("id", f"ev-{kind}"),
                         business_id=kwargs.pop("business_id", "biz-1"),
                         factory=kwargs.pop("factory", "opportunity"), kind=kind,
                         at=NOW - timedelta(days=days_ago), **kwargs)


# --- the stage is what happened, not what somebody typed ------------------------

def test_a_company_nobody_looked_at_is_discovered() -> None:
    r = relationship(a_business(), now=NOW)
    assert r.stage is Stage.DISCOVERED
    assert r.next_action.kind is ActionKind.AUDIT
    assert r.next_action.because


def test_an_audit_moves_it_to_researched() -> None:
    r = relationship(a_business(), findings=[a_finding()], now=NOW)
    assert r.stage is Stage.RESEARCHED
    assert "1 issue" in r.because
    assert r.next_action.kind is ActionKind.SCORE


def test_a_score_moves_it_to_qualified() -> None:
    r = relationship(a_business(), findings=[a_finding()],
                     opportunity=an_opportunity(), now=NOW)
    assert r.stage is Stage.QUALIFIED
    assert r.score == 72.0
    assert "72" in r.because


def test_contacted_requires_a_message_that_actually_left() -> None:
    """The lie a stored-stage CRM tells most often.

    An approved draft is not contact. Only a row that says `sent`, with a date,
    moves a company to `contacted`.
    """
    approved = relationship(a_business(email="a@b.example"),
                            messages=[a_message(OutreachStatus.APPROVED)], now=NOW)
    assert approved.stage is Stage.APPROVED

    sent = relationship(a_business(email="a@b.example"),
                        messages=[a_message(OutreachStatus.SENT,
                                            sent_at=NOW - timedelta(days=1))], now=NOW)
    assert sent.stage is Stage.CONTACTED
    assert "sent on 2026-09-03" in sent.because


def test_a_draft_is_proposed_not_approved() -> None:
    r = relationship(a_business(), messages=[a_message(OutreachStatus.AWAITING_APPROVAL)],
                     now=NOW)
    assert r.stage is Stage.PROPOSED
    assert r.next_action.kind is ActionKind.REVIEW


def test_a_reply_beats_a_send() -> None:
    r = relationship(a_business(),
                     messages=[a_message(OutreachStatus.SENT, sent_at=NOW - timedelta(days=3))],
                     events=[an_event("outreach.replied", days_ago=1)], now=NOW)
    assert r.stage is Stage.REPLIED
    assert r.next_action.kind is ActionKind.RESPOND


def test_delivery_makes_them_a_customer() -> None:
    r = relationship(a_business(), events=[an_event("website.published", days_ago=2)], now=NOW)
    assert r.stage is Stage.CUSTOMER
    assert r.next_action.kind is ActionKind.SERVE


def test_a_closed_opportunity_is_closed_whatever_else_happened() -> None:
    r = relationship(a_business(), findings=[a_finding()],
                     opportunity=an_opportunity(stage=OpportunityStage.DISQUALIFIED),
                     messages=[a_message(OutreachStatus.SENT, sent_at=NOW)], now=NOW)
    assert r.stage is Stage.CLOSED
    assert r.next_action.kind is ActionKind.NOTHING


def test_silence_becomes_dormant_on_its_own() -> None:
    """No human marks a company stale; the absence of events does.

    A stored-stage CRM shows a two-year-old `qualified` and looks busy.
    """
    old = relationship(a_business(), findings=[a_finding(detected_at=NOW - timedelta(days=90))],
                       now=NOW)
    assert old.stage is Stage.DORMANT
    assert "nothing has happened since" in old.because
    assert old.next_action.kind is ActionKind.AUDIT


# --- the next action, and the two things that make it useful --------------------

def test_every_action_carries_a_reason_naming_a_fact() -> None:
    """A reason that does not name a fact is a reason nobody can disagree with."""
    cases = [
        relationship(a_business(), now=NOW),
        relationship(a_business(), findings=[a_finding()], now=NOW),
        relationship(a_business(email="a@b.example"), findings=[a_finding()],
                     opportunity=an_opportunity(), now=NOW),
        relationship(a_business(), messages=[a_message(OutreachStatus.SENT, sent_at=NOW)],
                     now=NOW),
    ]
    for r in cases:
        assert len(r.next_action.because) > 12, r.next_action
        assert r.next_action.summary


def test_an_unreachable_company_is_told_to_find_a_contact_not_to_send() -> None:
    """412 businesses were discovered and 0 had an email address. A pipeline
    that says "send" to a company with nobody to send to is the shape of that
    failure."""
    r = relationship(a_business(), findings=[a_finding()], opportunity=an_opportunity(),
                     now=NOW)
    assert r.contactable is False
    assert r.next_action.kind is ActionKind.FIND_CONTACT
    assert "no address on file" in r.next_action.because


def test_a_missing_channel_blocks_the_send_and_names_the_blocker() -> None:
    """The same vocabulary the agent floor uses, so one unlock clears both."""
    r = relationship(a_business(email="a@b.example"),
                     messages=[a_message(OutreachStatus.APPROVED)],
                     channels_ready=frozenset(), now=NOW)
    assert r.next_action.kind is ActionKind.SEND
    assert r.next_action.blocked is True
    assert r.next_action.blocked_by == "PENDING_CREDENTIAL"


def test_a_configured_channel_unblocks_the_send() -> None:
    r = relationship(a_business(email="a@b.example"),
                     messages=[a_message(OutreachStatus.APPROVED)],
                     channels_ready=frozenset({"email"}), now=NOW)
    assert r.next_action.kind is ActionKind.SEND
    assert r.next_action.blocked is False


def test_nothing_in_the_pipeline_performs_an_action() -> None:
    """A derivation that could also send is one nobody can safely run twice."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "atlas_kernel" / "crm" /
              "pipeline.py").read_text(encoding="utf-8")
    for forbidden in ("requests.", "urllib", "smtplib", "def send(", "commit(", "INSERT"):
        assert forbidden not in source, f"the pipeline reaches out: {forbidden}"


# --- the board -----------------------------------------------------------------

def test_the_board_separates_what_can_start_from_what_cannot() -> None:
    relationships = [
        relationship(a_business(id="a"), findings=[a_finding(business_id="a")], now=NOW),
        relationship(a_business(id="b", email="b@x.example"),
                     messages=[a_message(OutreachStatus.APPROVED, business_id="b")],
                     channels_ready=frozenset(), now=NOW),
        relationship(a_business(id="c", email="c@x.example"),
                     messages=[a_message(OutreachStatus.APPROVED, business_id="c")],
                     channels_ready=frozenset(), now=NOW),
    ]
    result = board(relationships)
    assert result["total"] == 3
    assert result["actionable"] == 1
    assert result["blocked_on"][0]["blocker"] == "PENDING_CREDENTIAL"
    assert result["blocked_on"][0]["companies"] == 2
    assert result["stages"]["researched"] == 1


def test_the_board_counts_every_stage_even_the_empty_ones() -> None:
    """A stage missing from the board reads as a stage nothing is in, which is
    true — but a stage that is simply absent reads as a bug."""
    result = board([relationship(a_business(), now=NOW)])
    assert set(result["stages"]) == {s.value for s in Stage}


def test_a_closed_company_is_not_counted_as_actionable() -> None:
    closed = relationship(a_business(), opportunity=an_opportunity(stage=OpportunityStage.LOST),
                          now=NOW)
    assert board([closed])["actionable"] == 0


# --- the route -----------------------------------------------------------------

def test_the_pipeline_route_is_mounted(client) -> None:
    body = client.get("/api/crm/pipeline").json()
    assert set(body) >= {"known", "relationships", "board"}


def test_an_unreadable_store_is_not_an_empty_pipeline(client, monkeypatch) -> None:
    """"no companies" and "the store did not answer" are different facts, and
    only one of them means there is no work to do."""
    class Broken:
        def list_businesses(self, **_):
            raise RuntimeError("connection refused")

    client.app.state.opportunity_repository = Broken()
    body = client.get("/api/crm/pipeline").json()
    assert body["known"] is False
    assert "not the same as having no companies" in body["detail"]


def test_a_missing_company_is_a_404_not_an_empty_relationship(client) -> None:
    assert client.get("/api/crm/does-not-exist").status_code == 404
