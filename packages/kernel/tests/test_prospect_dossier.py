"""The thirteen facts a person needs before writing to a stranger.

Every test here builds a real prospect through the real writers and reads the
dossier back, because the two failures this module can have are both invisible
to a unit test with a stubbed repository:

* **A fact answered from the wrong owner.** The first version read the reason
  for selection out of `open_signals`, which is right until somebody approves
  the opportunity — at which point the signal stops being open and the prospect
  who got furthest is the one the dossier says there is no reason to approach.
  `test_an_approved_opportunity_still_explains_itself` is that bug.

* **A fact composed instead of read.** What will be sent must be the stored
  draft's own words. A dossier that re-composed the message would show one
  thing and send another, and the approval fingerprint would faithfully certify
  the difference.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from atlas_kernel import db
from atlas_kernel.opportunity import ranking
from atlas_kernel.opportunity.dossier import OWNERS, assemble
from atlas_kernel.opportunity.models import (
    Business,
    BusinessEvent,
    Evidence,
    EvidenceKind,
    OutreachMessage,
    OutreachStatus,
)
from atlas_kernel.opportunity.repository import OpportunityRepository
from atlas_kernel.opportunity.signals import (
    Inference,
    Observation,
    Reach,
    Signal,
    SignalKind,
    SuggestedAction,
)

TENANT = "tenant-dossier"
OTHER = "tenant-someone-else"


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


@pytest.fixture
def repo() -> OpportunityRepository:
    return OpportunityRepository()


def _business(repo: OpportunityRepository, *, tenant: str = TENANT,
              email: str = "") -> Business:
    saved = repo.save_business(Business(
        name="Al Waha Dental", geography="United Arab Emirates",
        website="https://alwaha.test", email=email, phone="",
        sources=["seed"], tenant_id=tenant))
    return saved


def _signal(repo: OpportunityRepository, business_id: str) -> Signal:
    evidence = [Evidence(kind=EvidenceKind.HTTP_RESPONSE,
                         source="https://alwaha.test/", observed={"status": 200},
                         detector="website")]
    observation = Observation(statement="the homepage has no phone link",
                              scope="website", evidence=evidence,
                              observed_at=datetime.now(UTC))
    signal = Signal(
        kind=SignalKind.NEW_BUSINESS, business_id=business_id,
        observations=[observation],
        inferences=[Inference(statement="they may be losing calls",
                              rests_on=tuple(observation.fingerprints),
                              confidence=0.5)],
        actions=[SuggestedAction(statement="offer a health check",
                                 reach=Reach.OUTWARD, needs_approval=True,
                                 capability="health-check")])
    assert repo.save_signal(signal, ranking.rank(signal), tenant=TENANT)
    return signal


def _audit(repo: OpportunityRepository, business_id: str) -> None:
    repo.record_event(BusinessEvent(
        business_id=business_id, factory="opportunity", kind="website_audited",
        actor="audit", detail={
            "url": "https://alwaha.test", "audited_at": "2026-08-30T02:00:00Z",
            "observations": [
                {"capability": "tel-link", "status": "not_found",
                 "evidence": "no tel: link in the homepage HTML"},
                {"capability": "https", "status": "present",
                 "evidence": "served over TLS"},
                # Neither present nor absent. It must stay its own count.
                {"capability": "opening-hours", "status": "not_verified",
                 "evidence": "the page did not finish loading"},
            ]}))


def _publish(repo: OpportunityRepository, business_id: str, signal_id: str,
             *, mission: str) -> None:
    repo.record_publication(
        mission_id=mission, business_id=business_id, signal_id=signal_id,
        commit="abc123", site_id="alwaha", url="https://sites.test/alwaha",
        files=["index.html"], actor="worker", offer="offer-health-check",
        tenant=TENANT)


def _draft(repo: OpportunityRepository, business_id: str, *,
           status: OutreachStatus = OutreachStatus.DRAFT,
           recipient: str = "hello@alwaha.test",
           approved: str = "", sent_at: datetime | None = None,
           subject: str = "What I found on Al Waha Dental's website",
           created_at: datetime | None = None,
           ) -> OutreachMessage:
    message = OutreachMessage(
        proposal_id="", mission_id="m-1", business_id=business_id,
        channel="email", recipient=recipient,
        subject=subject,
        body="I looked at your site and put what I found here: ...",
        status=status, approved_fingerprint=approved or None,
        sent_at=sent_at,
        **({"created_at": created_at} if created_at else {}),
        provider_message_id="<abc@qevik.ai>" if sent_at else None)
    return repo.save_message(message)


def _ready_to_write(repo: OpportunityRepository, business_id: str, *,
                    mission: str = "m-1") -> None:
    """Everything before the draft, so `next` reaches the approval step."""
    signal = _signal(repo, business_id)
    _audit(repo, business_id)
    _publish(repo, business_id, signal.id, mission=mission)
    repo.record_review(mission_id=mission, business_id=business_id,
                       signal_id=signal.id, decision="accepted",
                       actor="ayoub", commit="abc123", tenant=TENANT)


def _clean(repo: OpportunityRepository, business_id: str) -> None:
    from sqlalchemy import text

    from atlas_kernel.db import SessionLocal

    with SessionLocal() as session:
        for table, column in (("atlas_outreach_messages", "business_id"),
                              ("atlas_business_events", "business_id"),
                              ("atlas_signals", "business_id"),
                              ("atlas_businesses", "id")):
            session.execute(text(f"DELETE FROM {table} WHERE {column} = :b"),
                            {"b": business_id})
        session.commit()


# --------------------------------------------------------------- the absences


def test_an_unknown_business_is_not_an_empty_dossier(repo):
    found = assemble(f"nobody-{uuid4().hex}", memory=repo, tenant=TENANT)
    assert found["known"] is False
    assert "no business" in found["detail"]
    assert "answers" not in found, "a dossier for nobody is not thirteen unknowns"


def test_the_reason_for_selection_is_scoped_to_whoever_raised_it(repo):
    """A company is shared. The opportunity about it is not.

    Businesses carry no tenant — `save_business` writes none — so the gate
    cannot sit on the company record without hiding every prospect from
    everybody. It sits on the signal, which is the row that has one.
    """
    business = _business(repo)
    try:
        _signal(repo, business.id)                       # raised by TENANT

        mine = assemble(business.id, memory=repo, tenant=TENANT)["answers"]
        assert mine["why"]["known"] is True

        theirs = assemble(business.id, memory=repo, tenant=OTHER)["answers"]
        assert theirs["who"]["known"] is True, "the company itself is shared"
        assert theirs["why"]["known"] is False, \
            "another tenant's reason for selection is not this one's to read"
    finally:
        _clean(repo, business.id)


def test_a_business_with_nothing_says_so_thirteen_times(repo):
    """Every gap named, none filled."""
    business = _business(repo)
    try:
        answers = assemble(business.id, memory=repo, tenant=TENANT)["answers"]
        assert set(answers) == set(OWNERS)
        assert answers["who"]["known"] is True
        unknown = {name for name, a in answers.items() if not a["known"]}
        assert unknown == set(OWNERS) - {"who", "next"}
        for name in unknown:
            assert answers[name]["detail"], f"{name} is missing with no reason"
        assert answers["next"]["action"] == "Nothing to do"
    finally:
        _clean(repo, business.id)


def test_no_audit_is_not_a_finding_about_their_website(repo):
    business = _business(repo)
    try:
        observed = assemble(business.id, memory=repo,
                            tenant=TENANT)["answers"]["observed"]
        assert observed["known"] is False
        assert "not a finding about their site" in observed["detail"]
        assert "confirmed_absent" not in observed
    finally:
        _clean(repo, business.id)


def test_an_unfinished_observation_is_neither_present_nor_absent(repo):
    """Our own failure must never be counted as a fact about them."""
    business = _business(repo)
    try:
        _audit(repo, business.id)
        observed = assemble(business.id, memory=repo,
                            tenant=TENANT)["answers"]["observed"]
        assert observed["checked"] == 3
        assert observed["confirmed_absent"] == 1
        assert observed["confirmed_present"] == 1
        assert observed["not_verified"] == 1
    finally:
        _clean(repo, business.id)


# ------------------------------------------------------------ the wrong owner


def test_an_approved_opportunity_still_explains_itself(repo):
    """The bug this file exists for.

    `open_signals` stops returning a signal the moment somebody approves it. A
    dossier built on that read reports "no reason to approach them" for exactly
    the prospects a person already said yes to.
    """
    business = _business(repo)
    try:
        signal = _signal(repo, business.id)
        before = assemble(business.id, memory=repo, tenant=TENANT)["answers"]
        assert before["why"]["known"] is True
        assert before["why"]["state"] == "open"

        repo.approve_signal(signal.id, actor="ayoub", tenant=TENANT)
        assert not [s for s in repo.open_signals(limit=200, tenant=TENANT)
                    if s["business_id"] == business.id], "fixture did not approve"

        after = assemble(business.id, memory=repo, tenant=TENANT)["answers"]
        assert after["why"]["known"] is True, \
            "an approved opportunity is still the reason they were selected"
        assert after["why"]["state"] == "approved"
        assert after["why"]["statement"] == "offer a health check"
    finally:
        _clean(repo, business.id)


# ------------------------------------------------- the message is not composed


def test_what_will_be_sent_is_the_stored_draft_word_for_word(repo):
    business = _business(repo, email="hello@alwaha.test")
    try:
        signal = _signal(repo, business.id)
        _audit(repo, business.id)
        _publish(repo, business.id, signal.id, mission="m-1")
        draft = _draft(repo, business.id)

        answers = assemble(business.id, memory=repo, tenant=TENANT)["answers"]
        assert answers["message"]["subject"] == draft.subject
        assert answers["message"]["body"] == draft.body
        assert answers["message"]["status"] == "draft"
        assert answers["recipient"]["address"] == draft.recipient
        assert answers["recipient"]["is_the_drafted_recipient"] is True
        assert answers["recipient"]["still_matches_the_record"] is True
    finally:
        _clean(repo, business.id)


def test_a_draft_addressed_somewhere_the_record_no_longer_agrees_with(repo):
    """Shown, not silently reconciled — the draft is what would go out."""
    business = _business(repo, email="new@alwaha.test")
    try:
        _draft(repo, business.id, recipient="old@alwaha.test")
        recipient = assemble(business.id, memory=repo,
                             tenant=TENANT)["answers"]["recipient"]
        assert recipient["address"] == "old@alwaha.test"
        assert recipient["still_matches_the_record"] is False
    finally:
        _clean(repo, business.id)


def test_an_undrafted_prospect_is_not_given_a_guessed_message(repo):
    business = _business(repo, email="hello@alwaha.test")
    try:
        message = assemble(business.id, memory=repo,
                           tenant=TENANT)["answers"]["message"]
        assert message["known"] is False
        assert "subject" not in message and "body" not in message
        assert "not guessed here" in message["detail"]
    finally:
        _clean(repo, business.id)


def test_the_dossier_composes_nothing():
    """Structural. It may read a recipient; it may not write a message.

    Checked by parsing, not by grepping text, so this test cannot pass on the
    strength of its own docstring.
    """
    source = Path(
        "packages/kernel/atlas_kernel/opportunity/dossier.py").read_text()
    tree = ast.parse(source)
    # Only what it pulls from the kernel. `__future__` and `typing` are not
    # capabilities and excluding them by module keeps this from passing
    # because somebody added an unrelated import.
    imported = {
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.level > 0 or (node.module or "").startswith("atlas_kernel"))
        for alias in node.names}
    # `COMPOSABLE` is a tuple of offer names — data owned elsewhere, read so
    # this module does not keep a second opinion about which publications can
    # be described. Reading a constant is not composing a message.
    assert imported == {"verified_recipient", "ALL_TENANTS", "COMPOSABLE"}, (
        "the dossier imports something that is not a read: composing, "
        "preparing or sending here creates a second answer to a question that "
        f"already has one. Imported: {sorted(imported)}")

    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    forbidden = {"prepare", "compose", "compose_health_check", "send",
                 "deliver", "dispatch", "approve", "save_message",
                 "record_event", "save_business", "save_signal"}
    assert not (called & forbidden), \
        f"the dossier writes or composes: {sorted(called & forbidden)}"


# ------------------------------------------------------------- the afterwards


def test_a_timeline_before_the_send_is_not_what_happened_afterwards(repo):
    business = _business(repo)
    try:
        _audit(repo, business.id)          # an event, but it precedes any send
        after = assemble(business.id, memory=repo,
                         tenant=TENANT)["answers"]["after"]
        assert after["known"] is False
        assert after["events"] == []
        assert "before Qevik spoke to them" in after["detail"]
    finally:
        _clean(repo, business.id)


def test_what_happened_afterwards_is_the_timeline_after_the_send(repo):
    business = _business(repo)
    try:
        _audit(repo, business.id)                    # happens before the send
        sent_at = datetime.now(UTC)
        _draft(repo, business.id, status=OutreachStatus.SENT,
               approved="fp-1", sent_at=sent_at)
        repo.record_event(BusinessEvent(
            business_id=business.id, factory="customer", kind="lead_captured",
            actor="website", detail={"asked_about": "the report"}))

        after = assemble(business.id, memory=repo,
                         tenant=TENANT)["answers"]["after"]
        assert after["known"] is True
        kinds = [e["kind"] for e in after["events"]]
        assert kinds == ["lead_captured"], \
            "the audit predates the send and is not an afterwards"
        assert after["delivery"][0]["status"] == "sent"
    finally:
        _clean(repo, business.id)


def test_a_reply_of_a_kind_nothing_knows_about_still_appears(repo):
    """The dossier must not enumerate event kinds.

    A proposal, a customer or a payment appears the moment whichever factory
    owns it writes one — no edit here.
    """
    business = _business(repo)
    try:
        _draft(repo, business.id, status=OutreachStatus.SENT, approved="fp-1",
               sent_at=datetime.now(UTC))
        repo.record_event(BusinessEvent(
            business_id=business.id, factory="billing",
            kind="payment_received_kind_invented_by_this_test",
            actor="stripe", detail={"amount": 1200}))
        after = assemble(business.id, memory=repo,
                         tenant=TENANT)["answers"]["after"]
        assert "payment_received_kind_invented_by_this_test" in \
               [e["kind"] for e in after["events"]]
    finally:
        _clean(repo, business.id)


# --------------------------------------------------------------- what is next


def test_the_next_action_walks_the_chain_one_step_at_a_time(repo):
    business = _business(repo)
    try:
        def nxt() -> str:
            return assemble(business.id, memory=repo,
                            tenant=TENANT)["answers"]["next"]["action"]

        assert nxt() == "Nothing to do"
        signal = _signal(repo, business.id)
        assert nxt() == "Wait for the audit"
        _audit(repo, business.id)
        assert nxt() == "Approve the opportunity"
        _publish(repo, business.id, signal.id, mission="m-1")
        assert nxt() == "Review the artefact"
        repo.record_review(mission_id="m-1", business_id=business.id,
                           signal_id=signal.id, decision="accepted",
                           actor="ayoub", commit="abc123", tenant=TENANT)
        assert nxt() == "Find a way to reach them"

        repo.record_contactability(business.id, address="hello@alwaha.test",
                                   source_url="https://alwaha.test/contact")
        assert nxt() == "Prepare the message"
        _draft(repo, business.id)
        assert nxt() == "Review the draft"
    finally:
        _clean(repo, business.id)


def test_the_next_action_never_offers_to_send(repo):
    """Approved and unsent is a state, not a button."""
    business = _business(repo, email="hello@alwaha.test")
    try:
        _draft(repo, business.id, status=OutreachStatus.APPROVED,
               approved="fp-1")
        signal = _signal(repo, business.id)
        _audit(repo, business.id)
        _publish(repo, business.id, signal.id, mission="m-1")
        repo.record_review(mission_id="m-1", business_id=business.id,
                           signal_id=signal.id, decision="accepted",
                           actor="ayoub", commit="abc123", tenant=TENANT)

        nxt = assemble(business.id, memory=repo,
                       tenant=TENANT)["answers"]["next"]
        assert nxt["action"] == "Approved, not sent"
        assert "approval boundary" in nxt["because"]
    finally:
        _clean(repo, business.id)


# --------------------------------------------------------------- why usable


def test_an_address_read_from_their_own_page_says_where(repo):
    business = _business(repo)
    try:
        repo.record_contactability(business.id, address="hello@alwaha.test",
                                   source_url="https://alwaha.test/contact")
        why = assemble(business.id, memory=repo,
                       tenant=TENANT)["answers"]["why_usable"]
        assert why["known"] is True
        assert why["observations"][0]["source_url"] == \
               "https://alwaha.test/contact"
    finally:
        _clean(repo, business.id)


def test_an_address_from_nowhere_in_particular_says_that_too(repo):
    business = _business(repo, email="hello@alwaha.test")
    try:
        answers = assemble(business.id, memory=repo, tenant=TENANT)["answers"]
        assert answers["recipient"]["known"] is True
        why = answers["why_usable"]
        assert why["known"] is False
        assert "not the same evidence" in why["detail"]
    finally:
        _clean(repo, business.id)


def test_provenance_for_another_address_does_not_vouch_for_this_one(repo):
    """The one fact that justifies writing to a stranger, matched to the address.

    A page published `info@alwaha.test`; the draft goes to a hand-entered
    address nobody read anywhere. `bool(provenance)` made the second look
    evidence-backed because the first exists.
    """
    business = _business(repo)
    try:
        repo.record_contactability(business.id, address="info@alwaha.test",
                                   source_url="https://alwaha.test/contact")
        _draft(repo, business.id, recipient="owner@personal.test")

        answers = assemble(business.id, memory=repo, tenant=TENANT)["answers"]
        assert answers["recipient"]["address"] == "owner@personal.test"
        why = answers["why_usable"]
        assert why["known"] is False, \
            "a page that published a different address is not evidence for this one"
        assert why["observations"] == []
        assert why["other_addresses_observed"] == 1
        assert "not this one" in why["detail"]
    finally:
        _clean(repo, business.id)


def test_an_address_the_page_did_publish_is_still_vouched_for(repo):
    """Negative control for the match: the same fixture, addressed correctly."""
    business = _business(repo)
    try:
        repo.record_contactability(business.id, address="info@alwaha.test",
                                   source_url="https://alwaha.test/contact")
        _draft(repo, business.id, recipient="info@alwaha.test")

        why = assemble(business.id, memory=repo,
                       tenant=TENANT)["answers"]["why_usable"]
        assert why["known"] is True
        assert why["address"] == "info@alwaha.test"
        assert why["observations"][0]["source_url"] == \
               "https://alwaha.test/contact"
        assert why["other_addresses_observed"] == 0
    finally:
        _clean(repo, business.id)


# ------------------------------------------------- the approval is of the draft


def test_an_older_approval_does_not_approve_the_newer_draft(repo):
    """The approval answer is about the words the dossier is showing.

    A message approved last week and a draft written this morning are two
    different sets of words. `bool(approved)` over every message the business
    ever had put "Approved, not sent" beside the new draft, and an operator
    reads `approved` next to a sentence nobody approved.
    """
    business = _business(repo, email="hello@alwaha.test")
    try:
        _ready_to_write(repo, business.id)
        old = _draft(repo, business.id, status=OutreachStatus.APPROVED,
                     approved="fp-1", subject="the words somebody approved",
                     created_at=datetime.now(UTC) - timedelta(days=7))
        new = _draft(repo, business.id, subject="the words nobody has read",
                     created_at=datetime.now(UTC))

        answers = assemble(business.id, memory=repo, tenant=TENANT)["answers"]
        assert answers["message"]["id"] == new.id, "fixture: the newer draft shows"
        approval = answers["approval"]
        assert approval["known"] is False, \
            "an older approval is not an approval of the draft on screen"
        assert approval["message_id"] == new.id
        assert "not approved" in approval["detail"]
        # The earlier approval is not hidden — it happened — but it says which
        # message it is about.
        assert [a["message_id"] for a in approval["approvals"]] == [old.id]
        assert approval["approvals"][0]["is_the_drafted_message"] is False
        assert approval["superseded_approvals"] == 1
        assert answers["next"]["action"] == "Review the draft"
    finally:
        _clean(repo, business.id)


def test_an_approval_of_the_shown_draft_still_reads_as_approved(repo):
    """Negative control: the same chain, with the newest draft approved."""
    business = _business(repo, email="hello@alwaha.test")
    try:
        _ready_to_write(repo, business.id)
        _draft(repo, business.id, status=OutreachStatus.APPROVED,
               approved="fp-1", subject="an older approved message",
               created_at=datetime.now(UTC) - timedelta(days=7))
        new = _draft(repo, business.id, status=OutreachStatus.APPROVED,
                     approved="fp-2", subject="the newest words, approved",
                     created_at=datetime.now(UTC))

        answers = assemble(business.id, memory=repo, tenant=TENANT)["answers"]
        approval = answers["approval"]
        assert approval["known"] is True
        assert approval["message_id"] == new.id
        assert [a["message_id"] for a in approval["approvals"]
                if a["is_the_drafted_message"]] == [new.id]
        assert answers["next"]["action"] == "Approved, not sent"
    finally:
        _clean(repo, business.id)


def test_evidence_moved_since_is_measured_from_the_shown_approval(repo):
    """The window belongs to the words on screen, not to the oldest approval.

    A re-reading between an old approval and today's approved draft did not
    move the ground under the draft — it happened before it was written.
    """
    business = _business(repo, email="hello@alwaha.test")
    try:
        _draft(repo, business.id, status=OutreachStatus.APPROVED,
               approved="fp-1", subject="approved a week ago",
               created_at=datetime.now(UTC) - timedelta(days=7))
        repo.record_event(BusinessEvent(
            business_id=business.id, factory="reevaluation",
            kind="business_reevaluated", actor="recipe:verify-recorded-websites",
            detail={"changes": [{"feature": "click_to_call",
                                 "was": "not_found", "now": "present",
                                 "change": "contradicted"}]}))
        _draft(repo, business.id, status=OutreachStatus.APPROVED,
               approved="fp-2", subject="approved just now",
               created_at=datetime.now(UTC))

        approval = assemble(business.id, memory=repo,
                            tenant=TENANT)["answers"]["approval"]
        assert approval["known"] is True
        assert approval["evidence_moved_since"] == [], \
            "the re-reading predates the draft this answer is about"
    finally:
        _clean(repo, business.id)


def test_an_unapproved_draft_reports_no_moved_evidence_at_all(repo):
    """No approval, no window — not the window of somebody else's approval.

    The draft on screen is unapproved and an older message was approved, so
    falling back to the oldest approval measures from a moment before these
    words existed. The answer would then carry changes that cannot have moved
    the ground under a draft written after them, under a `known=False` claim
    about that draft.
    """
    business = _business(repo, email="hello@alwaha.test")
    try:
        _ready_to_write(repo, business.id)
        old = _draft(repo, business.id, status=OutreachStatus.APPROVED,
                     approved="fp-1", subject="approved a week ago",
                     created_at=datetime.now(UTC) - timedelta(days=7))
        repo.record_event(BusinessEvent(
            business_id=business.id, factory="reevaluation",
            kind="business_reevaluated", actor="recipe:verify-recorded-websites",
            detail={"changes": [{"feature": "click_to_call",
                                 "was": "not_found", "now": "present",
                                 "change": "contradicted"}]}))
        new = _draft(repo, business.id, subject="written after all of that",
                     created_at=datetime.now(UTC))

        # The change is real and is visible from the older approval's moment —
        # so an empty answer below is the fix, not an empty fixture.
        assert [c["feature"] for c in
                repo.evidence_changes_since(business.id, old.created_at)] == \
               ["click_to_call"]

        approval = assemble(business.id, memory=repo,
                            tenant=TENANT)["answers"]["approval"]
        assert approval["known"] is False
        assert approval["message_id"] == new.id
        assert approval["evidence_moved_since"] == [], \
            "nothing approves these words, so nothing has moved since one did"

        # Negative control: once these words *are* approved, a change after
        # that approval is reported — the window exists and is this draft's.
        approved_now = _draft(repo, business.id,
                              status=OutreachStatus.APPROVED, approved="fp-2",
                              subject="and then approved",
                              created_at=datetime.now(UTC))
        repo.record_event(BusinessEvent(
            business_id=business.id, factory="reevaluation",
            kind="business_reevaluated", actor="recipe:verify-recorded-websites",
            detail={"changes": [{"feature": "whatsapp", "was": "present",
                                 "now": "not_found",
                                 "change": "contradicted"}]}))
        after = assemble(business.id, memory=repo,
                         tenant=TENANT)["answers"]["approval"]
        assert after["known"] is True and after["message_id"] == approved_now.id
        assert [c["feature"] for c in after["evidence_moved_since"]] == \
               ["whatsapp"], "only what moved after the approval on screen"
    finally:
        _clean(repo, business.id)


def test_every_answer_names_the_model_it_came_from(repo):
    business = _business(repo)
    try:
        answers = assemble(business.id, memory=repo, tenant=TENANT)["answers"]
        for name, answer in answers.items():
            assert answer["from"] == OWNERS[name]
            assert answer["from"].strip(), f"{name} cites no owner"
    finally:
        _clean(repo, business.id)


# ------------------------------------------------------------- through the API


def test_the_dossier_is_served_through_the_composed_app(tmp_path, monkeypatch,
                                                        repo):
    """Serialisable, routed, and behind the same auth as everything else.

    Through the real app because the two things that break here break nowhere
    else: a `Finding` that will not encode, and a path that loses the race to
    `/{business_id}/sightings`.
    """
    from fastapi.testclient import TestClient

    from atlas_kernel.auth.models import Scope, User, hash_password
    from atlas_kernel.auth.store import AuthStore
    from atlas_kernel.qevik.app import Wiring, create_app

    business = _business(repo, email="hello@alwaha.test")
    try:
        signal = _signal(repo, business.id)
        _audit(repo, business.id)
        _publish(repo, business.id, signal.id, mission="m-1")
        _draft(repo, business.id)

        app = create_app(Wiring(repository_root=tmp_path,
                                mission_timeline=tmp_path / "m.jsonl"))
        who = User(username="t", password_hash=hash_password("test-only-pw"),
                   tenant_id=TENANT, scopes=frozenset(Scope))
        monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: who)
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer t"
            got = client.get(f"/api/discovery/{business.id}/dossier")
            assert got.status_code == 200, got.text
            body = got.json()
            assert body["known"] is True
            assert set(body["answers"]) == set(OWNERS)
            assert body["answers"]["message"]["subject"]
            # Negative control on the route order: the neighbouring path still
            # belongs to the handler that declares it.
            assert client.get("/api/discovery/opportunities").status_code == 200
    finally:
        _clean(repo, business.id)


def test_a_publication_that_does_not_say_what_it_is_blocks_the_message(repo):
    """Found in production: four of five publications record no offer.

    `prepare` refuses them, permanently — the field did not exist when they
    were written. The dossier said "Prepare the message", which sends an
    operator at a door the system holds shut.
    """
    business = _business(repo, email="hello@alwaha.test")
    try:
        signal = _signal(repo, business.id)
        _audit(repo, business.id)
        repo.record_publication(
            mission_id="m-1", business_id=business.id, signal_id=signal.id,
            commit="abc123", site_id="alwaha", url="https://sites.test/alwaha",
            files=["index.html"], actor="worker", offer="", tenant=TENANT)
        repo.record_review(mission_id="m-1", business_id=business.id,
                           signal_id=signal.id, decision="accepted",
                           actor="ayoub", commit="abc123", tenant=TENANT)

        answers = assemble(business.id, memory=repo, tenant=TENANT)["answers"]
        assert answers["produced"]["describable"] is False
        assert answers["next"]["action"] == "Record what was published"

        # Negative control: the same chain with a composable offer asks for the
        # message, so the refusal above is the offer and not the fixture.
        _clean(repo, business.id)
        business2 = _business(repo, email="hello@alwaha.test")
        signal2 = _signal(repo, business2.id)
        _audit(repo, business2.id)
        _publish(repo, business2.id, signal2.id, mission="m-2")
        repo.record_review(mission_id="m-2", business_id=business2.id,
                           signal_id=signal2.id, decision="accepted",
                           actor="ayoub", commit="abc123", tenant=TENANT)
        try:
            second = assemble(business2.id, memory=repo, tenant=TENANT)["answers"]
            assert second["produced"]["describable"] is True
            assert second["next"]["action"] == "Prepare the message"
        finally:
            _clean(repo, business2.id)
    finally:
        _clean(repo, business.id)


def test_an_approval_says_whether_its_evidence_has_since_moved(repo):
    """A fact for the operator, never a verdict from the system.

    The two approved messages in production were drafted at 13:35 on
    2026-08-19 against an audit from 12:05 the same day, and nothing has
    re-read those sites since. The nightly pass will reach them, and when it
    does the words stay exactly what a person approved while the ground under
    them moves. Those are two different facts and the screen must show both.
    """
    from atlas_kernel.opportunity.models import BusinessEvent, OutreachStatus

    business = _business(repo, email="hello@alwaha.test")
    try:
        _draft(repo, business.id, status=OutreachStatus.APPROVED,
               approved="fp-1")
        before = assemble(business.id, memory=repo,
                          tenant=TENANT)["answers"]["approval"]
        assert before["known"] is True
        assert before["evidence_moved_since"] == []

        repo.record_event(BusinessEvent(
            business_id=business.id, factory="reevaluation",
            kind="business_reevaluated", actor="recipe:verify-recorded-websites",
            detail={"changes": [
                {"feature": "click_to_call", "was": "not_found",
                 "now": "present", "change": "contradicted"},
                # About our checking, not their site. It must not appear: an
                # operator trained to ignore the flag ignores the real one too.
                {"feature": "arabic", "was": "present", "now": "unverified",
                 "change": "now_unverified"}]}))

        after = assemble(business.id, memory=repo,
                         tenant=TENANT)["answers"]["approval"]
        moved = after["evidence_moved_since"]
        assert [c["feature"] for c in moved] == ["click_to_call"]
        # The approval itself is untouched. Nothing withdrew it.
        assert after["approvals"][0]["fingerprint"] == "fp-1"
        assert repo.messages_for(business.id)[-1].status is OutreachStatus.APPROVED
        assert after["known"] is True
    finally:
        _clean(repo, business.id)
