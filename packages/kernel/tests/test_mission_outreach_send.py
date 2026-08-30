"""The explicit mission SEND action, and everything that stands in front of it.

Approval and sending are separate decisions here. These tests hold that apart —
approval must persist an artefact and reach nothing, and sending must refuse
anything the approval does not still cover.

Nothing sends. The SMTP layer is replaced wherever the transport is reached.
"""

from __future__ import annotations

import hashlib

import pytest

from atlas_kernel.opportunity.models import OutreachMessage, OutreachStatus
from atlas_kernel.outreach import channels
from atlas_kernel.outreach.preparation import Prepared


def _prepared(**over) -> Prepared:
    base = dict(
        business_id="b1", business_name="Al Noor Dental", signal_id="s1",
        mission_id="mission-000000000001", commit="abc123def456",
        site_id="site-1", url="https://sites.qevik.ai/site-1/",
        approved_scope="website", evidence_fingerprints=("ev-2", "ev-1"),
        answers=("no title", "no phone"), subject="A website for Al Noor Dental",
        body="Hello,\n\nI built one.\n", recipient="hello@alnoor.test",
        channel="email")
    base.update(over)
    return Prepared(**base)


# ============================================ the canonical fingerprint

class TestTheCanonicalFingerprint:
    def test_it_is_stable_for_the_same_records(self) -> None:
        assert _prepared().fingerprint == _prepared().fingerprint

    def test_evidence_order_does_not_change_it(self) -> None:
        """Read the list back the other way round and the approval survives."""
        assert (_prepared(evidence_fingerprints=("ev-1", "ev-2")).fingerprint
                == _prepared(evidence_fingerprints=("ev-2", "ev-1")).fingerprint)

    @pytest.mark.parametrize("field,value", [
        ("subject", "Something else"),
        ("body", "Different words entirely"),
        ("recipient", "someone@else.test"),
        ("commit", "999999999999"),
        ("evidence_fingerprints", ("ev-1", "ev-3")),
    ])
    def test_every_component_invalidates_it(self, field, value) -> None:
        assert _prepared(**{field: value}).fingerprint != _prepared().fingerprint

    def test_it_is_not_a_digest_of_the_body_alone(self) -> None:
        """The failure this replaced: an approval over the words only, which
        said nothing about the evidence or the publication they rest on."""
        body_only = hashlib.sha256(_prepared().body.encode()).hexdigest()
        assert _prepared().fingerprint != body_only

    def test_answers_are_covered_through_the_body_not_separately(self) -> None:
        """`answers` are already inside the composed body. Including them twice
        would say nothing new — but changing them must still invalidate."""
        from atlas_kernel.outreach.preparation import compose

        subject_a, body_a = compose(business_name="X", url="https://u/",
                                    answers=("one",), site_id="s")
        subject_b, body_b = compose(business_name="X", url="https://u/",
                                    answers=("two",), site_id="s")
        assert body_a != body_b
        assert (_prepared(subject=subject_a, body=body_a).fingerprint
                != _prepared(subject=subject_b, body=body_b).fingerprint)


# ============================================ provenance durability

class TestProvenanceIsReadAtTheCommit:
    def test_missing_provenance_raises_rather_than_becoming_empty(self) -> None:
        """The defect this closes.

        `provenance()` returns `{}` when it cannot read, which would silently
        compose a shorter message — a different message — with no error. For an
        approval that is unacceptable, so `provenance_at` refuses instead.
        """
        from atlas_kernel.mission import artefact

        with pytest.raises(artefact.Unreadable):
            artefact.provenance_at("abc123", "/nonexistent/workspace")

    def test_the_lenient_reader_still_exists_for_display(self) -> None:
        """Unchanged, because a reviewer looking at a mission wants what is
        there now and an absent file is not an error on that path."""
        from atlas_kernel.mission import artefact

        assert artefact.provenance("m", "/nonexistent/workspace") == {}

    def test_it_reads_by_commit_not_by_branch(self) -> None:
        """A branch is a name somebody can move; an approval that read through
        one would authorise whatever it later pointed at."""
        import inspect

        from atlas_kernel.mission import artefact

        source = inspect.getsource(artefact.provenance_at)
        assert "read_at" in source, "must be commit-addressed"
        assert "branch_of" not in source


# ============================================ the send guards

class TestSendGuards:
    """`OutreachService` is the only path to a channel, and these are its gates
    seen from the mission side. The service's own tests cover them in full."""

    def _service(self, channel, **kwargs):
        from atlas_kernel.opportunity.outreach import OutreachService

        return OutreachService(channel, **kwargs)

    def _message(self, **over) -> OutreachMessage:
        from datetime import UTC, datetime

        payload = {
            "proposal_id": "", "mission_id": "mission-000000000001",
            "business_id": "b1", "channel": "email",
            "recipient": "hello@alnoor.test",
            "subject": _prepared().subject, "body": _prepared().body,
            "status": OutreachStatus.APPROVED,
            "approved_fingerprint": _prepared().fingerprint,
            "authorized_automated_at": datetime.now(UTC),
        }
        payload.update(over)
        return OutreachMessage(**payload)

    def test_a_manual_whatsapp_approval_cannot_be_sent_automatically(self) -> None:
        """The five real drafts are approved for a person to send. They must
        never be picked up by an automated path."""
        from atlas_kernel.opportunity.outreach import OutreachRefused
        from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE

        class Exploding:
            name = "exploding"

            def deliver(self, message):
                raise AssertionError("a manual approval reached a channel")

        message = self._message(
            status=OutreachStatus.APPROVED_FOR_MANUAL_SEND,
            authorized_automated_at=None, channel="whatsapp")
        with pytest.raises(OutreachRefused, match="by hand"):
            self._service(Exploding()).send(message, _prepared(), EXAMPLE_PROFILE)

    def test_approval_without_automated_authorisation_is_refused(self) -> None:
        from atlas_kernel.opportunity.outreach import OutreachRefused
        from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE

        class Exploding:
            name = "exploding"

            def deliver(self, message):
                raise AssertionError("an unauthorised message reached a channel")

        message = self._message(authorized_automated_at=None)
        with pytest.raises(OutreachRefused, match="automated"):
            self._service(Exploding()).send(message, _prepared(), EXAMPLE_PROFILE)

    def test_a_changed_artefact_invalidates_the_authorisation(self) -> None:
        """Evidence, publication or wording moved after approval."""
        from atlas_kernel.opportunity.outreach import OutreachRefused
        from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE

        class Exploding:
            name = "exploding"

            def deliver(self, message):
                raise AssertionError("a stale approval reached a channel")

        for moved in (_prepared(body="Rewritten"),
                      _prepared(commit="ffffffffffff"),
                      _prepared(evidence_fingerprints=("ev-9",))):
            with pytest.raises(OutreachRefused, match="changed after approval"):
                self._service(Exploding()).send(self._message(), moved,
                                                EXAMPLE_PROFILE)


# ============================================ the surface itself

class TestTheSendSurface:
    def test_the_route_accepts_no_message_content(self) -> None:
        """The request says *which* artefact to send, never *what* to send.

        Structural, because the way this rule dies is a convenience field added
        later so a caller can 'just tweak the subject'.
        """
        import inspect

        from atlas_kernel.mission import api

        source = inspect.getsource(api.build_router)
        start = source.index("def send_outreach")
        end = source.index("def publish", start)
        route = source[start:end]

        assert "body:" not in route, "the send route takes no request body"
        for forbidden in ("recipient=", "subject=", "body=", "offer", "price"):
            assert f"{forbidden}request" not in route

    def test_approval_and_sending_are_different_routes(self) -> None:
        import inspect

        from atlas_kernel.mission import api

        source = inspect.getsource(api.build_router)
        assert '"/{mission_id}/outreach/approve"' in source
        assert '"/{mission_id}/outreach/send"' in source

    def test_approval_never_sends(self) -> None:
        """The approve route may persist and record. It may not deliver."""
        import inspect

        from atlas_kernel.mission import api

        source = inspect.getsource(api.build_router)
        start = source.index("def approve_outreach")
        end = source.index("def send_outreach", start)
        approve = source[start:end]

        for forbidden in ("OutreachService", "SmtpOutreachChannel",
                          "EmailChannel", ".deliver(", ".send("):
            assert forbidden not in approve, (
                f"the approve route references {forbidden!r}; approval records "
                "permission and must not create the ability")

    def test_the_send_route_loads_durable_guards(self) -> None:
        """An empty `SuppressionList()` suppresses nothing and an empty
        `ContactHistory()` has nobody in a cooldown. Both must come from the
        database, or the guards pass in production while stopping nothing."""
        import inspect

        from atlas_kernel.mission import api

        source = inspect.getsource(api.build_router)
        start = source.index("def send_outreach")
        end = source.index("def publish", start)
        route = source[start:end]

        assert "load_suppression()" in route
        assert "load_contact_history(" in route

    def test_the_cooldown_is_declared_not_written_into_the_route(self) -> None:
        """A cooldown is a commercial term. It lives in data with its date and
        its source, so it can be found and argued with."""
        import inspect

        from atlas_kernel.mission import api

        source = inspect.getsource(api.build_router)
        start = source.index("def send_outreach")
        end = source.index("def publish", start)
        route = source[start:end]

        assert "contact_policy_for()" in route
        assert "EXAMPLE_PROFILE" not in route
        for number in ("7", "14", "30", "90"):
            assert f"contact_cooldown_days = {number}" not in route
            assert f"cooldown_days={number}" not in route

    def test_the_declared_policy_is_the_owners_decision_with_provenance(self) -> None:
        """Fourteen days, decided 2026-08-30. Recorded where a reader finds it."""
        import inspect

        from atlas_kernel.opportunity import profiles

        assert profiles.INITIAL_CONTACT_POLICY.contact_cooldown_days == 14
        # Whitespace-normalised: the declaration is a wrapped comment block, and
        # a test that breaks when a line is re-wrapped teaches people to delete
        # the test rather than keep the provenance.
        raw = inspect.getsource(profiles).replace("#:", " ")
        declaration = " ".join(raw.split())
        assert "2026-08-30" in declaration, "a policy without a date has no author"
        assert "not a technical default" in declaration

    def test_the_placeholder_profile_never_supplies_a_cooldown(self) -> None:
        """`EXAMPLE_PROFILE` says of itself that it is not a recommendation.
        Inheriting a commercial term from it because it is the only one
        registered is exactly the silent invention this guards against."""
        from atlas_kernel.opportunity.profiles import (
            EXAMPLE_PROFILE,
            INITIAL_CONTACT_POLICY,
            contact_policy_for,
        )

        assert contact_policy_for(EXAMPLE_PROFILE.id) is INITIAL_CONTACT_POLICY
        assert contact_policy_for("") is INITIAL_CONTACT_POLICY
        assert contact_policy_for("no-such-niche") is INITIAL_CONTACT_POLICY

    def test_a_real_niche_profile_still_overrides_it(self) -> None:
        """A niche that states its own cadence has stated it deliberately."""
        from atlas_kernel.opportunity.models import NicheProfile
        from atlas_kernel.opportunity.profiles import (
            PROFILES,
            contact_policy_for,
            register_profile,
        )

        own = NicheProfile(id="probe-niche", name="Probe", geography="UAE",
                           offer="a website", contact_cooldown_days=45)
        register_profile(own)
        try:
            assert contact_policy_for("probe-niche").contact_cooldown_days == 45
        finally:
            PROFILES.pop("probe-niche", None)

    def test_signal_scope_is_not_a_niche_key(self) -> None:
        """The defect this replaced.

        Production signals carry an audited URL in `scope` for
        `weak_web_presence`, and the source name for `missing_service`. Looking
        a niche up by scope could never have matched.
        """
        from atlas_kernel.opportunity.profiles import PROFILES

        for scope in ("http://www.thesalondubai.com/", "openstreetmap"):
            assert scope not in PROFILES


# ============================================ nothing else gained a send path

class TestNoWideningHappened:
    def test_smtp_is_still_not_dispatchable(self) -> None:
        from atlas_kernel.mission.toolrunner import DISPATCHABLE

        assert "smtp" not in DISPATCHABLE
        assert {"site-publish", "http-fetch"} <= set(DISPATCHABLE)

    def test_the_transport_is_still_reached_only_through_the_adapter(self) -> None:
        from pathlib import Path

        import atlas_kernel

        root = Path(atlas_kernel.__file__).parent
        allowed = {"channels.py", "smtp_channel.py", "preparation.py"}
        callers = [
            str(path.relative_to(root))
            for path in root.rglob("*.py")
            if path.name not in allowed
            and "EmailChannel(" in path.read_text(encoding="utf-8", errors="ignore")
        ]
        assert callers == [], callers

    def test_the_transport_still_refuses_without_a_credential(self, monkeypatch) -> None:
        from atlas_kernel.outreach.channels import ChannelNotConnected, EmailChannel

        for name in channels.SMTP_SETTINGS:
            monkeypatch.delenv(name, raising=False)

        class Approved:
            approved = True

        with pytest.raises(ChannelNotConnected):
            EmailChannel().send(recipient="a@b.co", subject="s", body="b",
                                approval=Approved())


class TestWhatAReaderIsGivenToApproveWith:
    """`approve_outreach` re-composes the message server-side and refuses (409)
    when the client's fingerprint differs. A read that returns no fingerprint
    therefore cannot be approved by any client — the endpoint works and is
    unreachable, which is how a shipped feature has no user."""

    def test_the_summary_carries_the_fingerprint_an_approval_must_echo(self) -> None:
        prepared = _prepared()

        assert prepared.summary()["fingerprint"] == prepared.fingerprint
        assert len(prepared.summary()["fingerprint"]) == 64

    def test_it_covers_the_words_the_reader_actually_read(self) -> None:
        """A fingerprint that ignored the body would approve a message the
        operator never saw."""
        import dataclasses

        first = _prepared()
        edited = dataclasses.replace(first, body=first.body + " and one more thing")

        assert edited.summary()["fingerprint"] != first.summary()["fingerprint"]

    def test_it_covers_the_recipient(self) -> None:
        """The same words to a different stranger is a different act."""
        import dataclasses

        first = _prepared()
        elsewhere = dataclasses.replace(first, recipient="someone-else@example.test")

        assert elsewhere.summary()["fingerprint"] != first.summary()["fingerprint"]
