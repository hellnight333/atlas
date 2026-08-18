"""Pausing a plan for a human, durably.

The previous boundary was a flag on submission: consent given before any plan
existed, to a category rather than to an act. These tests defend the replacement
— consent to a specific proposal, bound to it, spent once, and surviving a
restart.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from atlas_kernel.actions.approval_gate import (
    GATED_ACTIONS,
    INTERNAL_ACTIONS,
    ApprovalGate,
    ApprovalOutcome,
    ApprovalProposal,
    ApprovalStore,
    Risk,
    classify,
    describe,
    fingerprint,
    init_approvals,
    material,
)
from atlas_kernel.auth import Scope

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def _schema():
    init_approvals()


@pytest.fixture
def store() -> ApprovalStore:
    return ApprovalStore()


@pytest.fixture
def job() -> str:
    """A unique job per test, so runs never inherit each other's approvals."""
    return f"job_test_{uuid.uuid4().hex[:10]}"


def _proposal(job: str, **kwargs) -> ApprovalProposal:
    payload = kwargs.pop("payload", {"slug": "clinic", "promote": True})
    return ApprovalProposal(
        job_id=job,
        step_id=kwargs.pop("step_id", "deploy"),
        action=kwargs.pop("action", "site.deploy"),
        scope=Scope.PUBLISH,
        risk=Risk.PUBLIC,
        fingerprint=fingerprint("site.deploy", payload),
        payload=payload,
        summary="Publish the site",
        target="/clinic/",
        **kwargs,
    )


class TestWhatNeedsApproval:
    def test_internal_work_does_not(self) -> None:
        """Requiring a decision for writing a file in a scratch directory trains
        people to click approve without reading."""
        for action in INTERNAL_ACTIONS:
            assert classify(action) is None

    def test_publishing_sending_spending_and_deleting_do(self) -> None:
        for action in ("site.deploy", "email.send", "payment.create", "site.remove"):
            assert classify(action) is not None

    def test_an_unknown_action_is_gated_rather_than_allowed(self) -> None:
        """A new capability should have to argue that it is harmless. Failing
        open is how something outward-facing ships ungated because nobody
        remembered to list it."""
        scope, risk = classify("some.future.capability")
        assert scope is Scope.ADMIN and risk is Risk.DESTRUCTIVE

    def test_each_gated_action_names_a_scope_and_a_risk(self) -> None:
        for action, (scope, risk) in GATED_ACTIONS.items():
            assert isinstance(scope, Scope) and isinstance(risk, Risk), action


class TestTheApprovalIsBoundToTheAct:
    def test_a_cosmetic_change_does_not_need_a_new_decision(self) -> None:
        base = {"slug": "clinic", "promote": True, "screenshot": "a.png"}
        other = {**base, "screenshot": "b.png"}
        assert fingerprint("site.deploy", base) == fingerprint("site.deploy", other)

    def test_changing_the_target_does(self) -> None:
        """Approving a deploy of this content to this slug must not approve a
        different one."""
        a = fingerprint("site.deploy", {"slug": "clinic"})
        b = fingerprint("site.deploy", {"slug": "somewhere-else"})
        assert a != b

    def test_changing_the_recipient_does(self) -> None:
        a = fingerprint("email.send", {"to": "them@example.com", "body": "hello"})
        b = fingerprint("email.send", {"to": "someone-else@example.com", "body": "hello"})
        assert a != b

    def test_changing_the_message_does(self) -> None:
        a = fingerprint("email.send", {"to": "t@example.com", "body": "hello"})
        b = fingerprint("email.send", {"to": "t@example.com", "body": "wire me money"})
        assert a != b

    def test_changing_the_amount_does(self) -> None:
        a = fingerprint("payment.create", {"amount": 10, "currency": "AED", "vendor": "v"})
        b = fingerprint("payment.create", {"amount": 10000, "currency": "AED", "vendor": "v"})
        assert a != b

    def test_only_material_parameters_are_bound(self) -> None:
        assert set(material("site.deploy", {"slug": "x", "screenshot": "y"})) == {"slug"}

    def test_the_reviewer_is_told_the_exact_target(self) -> None:
        """The single fact most needed and most easily lost in a payload dump."""
        summary, target = describe("email.send", {"to": "owner@clinic.ae", "body": "hi"})
        assert "owner@clinic.ae" in target
        assert "Send a message" in summary


class TestTheGate:
    def test_an_internal_step_runs_without_asking(self, job: str) -> None:
        gate = ApprovalGate()
        verdict = gate.check(job_id=job, step_id="s", action="code.write", payload={})
        assert verdict.outcome is ApprovalOutcome.ALLOWED

    def test_a_publish_waits_and_records_what_it_proposes(self, job: str) -> None:
        gate = ApprovalGate()
        verdict = gate.check(
            job_id=job,
            step_id="deploy",
            action="site.deploy",
            payload={"slug": "clinic", "url": "http://host/clinic/"},
        )
        assert verdict.outcome is ApprovalOutcome.WAITING
        assert verdict.approval_id

        stored = ApprovalStore().get(verdict.approval_id)
        assert stored["status"] == "pending"
        assert stored["action"] == "site.deploy"
        assert stored["target"] == "http://host/clinic/"
        assert stored["required_scope"] == "publish"

    def test_asking_twice_presents_one_decision_not_two(self, job: str) -> None:
        """A job that pauses, is restarted and pauses again on the same step must
        not stack duplicate requests in the queue."""
        gate = ApprovalGate()
        payload = {"slug": "clinic"}
        first = gate.check(job_id=job, step_id="d", action="site.deploy", payload=payload)
        second = gate.check(job_id=job, step_id="d", action="site.deploy", payload=payload)
        assert first.approval_id == second.approval_id
        assert len(ApprovalStore().for_job(job)) == 1

    def test_an_approved_act_is_allowed(self, job: str, store: ApprovalStore) -> None:
        gate = ApprovalGate()
        payload = {"slug": "clinic"}
        waiting = gate.check(job_id=job, step_id="d", action="site.deploy", payload=payload)
        store.decide(waiting.approval_id, approve=True, decided_by="ayoub")

        allowed = gate.check(job_id=job, step_id="d", action="site.deploy", payload=payload)
        assert allowed.outcome is ApprovalOutcome.ALLOWED
        assert "ayoub" in allowed.reason

    def test_an_approval_does_not_carry_to_a_different_act(
        self, job: str, store: ApprovalStore
    ) -> None:
        """The property that stops consent being obtained for something harmless
        and spent on something else."""
        gate = ApprovalGate()
        approved = gate.check(
            job_id=job, step_id="d", action="site.deploy", payload={"slug": "harmless"}
        )
        store.decide(approved.approval_id, approve=True, decided_by="ayoub")

        different = gate.check(
            job_id=job, step_id="d", action="site.deploy", payload={"slug": "something-else"}
        )
        assert different.outcome is ApprovalOutcome.WAITING
        assert different.approval_id != approved.approval_id

    def test_a_rejection_stops_the_step(self, job: str, store: ApprovalStore) -> None:
        gate = ApprovalGate()
        waiting = gate.check(job_id=job, step_id="d", action="site.deploy", payload={"slug": "x"})
        store.decide(waiting.approval_id, approve=False, decided_by="ayoub", reason="wrong copy")

        verdict = gate.check(job_id=job, step_id="d", action="site.deploy", payload={"slug": "x"})
        assert verdict.outcome is ApprovalOutcome.REJECTED
        assert "wrong copy" in verdict.reason

    def test_a_rejected_request_cannot_be_flipped_to_approved(
        self, job: str, store: ApprovalStore
    ) -> None:
        """Decisions are final. Re-deciding would let a rejection be laundered
        into an approval without anyone re-reading the proposal."""
        gate = ApprovalGate()
        waiting = gate.check(job_id=job, step_id="d", action="site.deploy", payload={"slug": "x"})
        store.decide(waiting.approval_id, approve=False, decided_by="ayoub")
        with pytest.raises(ValueError, match="already rejected"):
            store.decide(waiting.approval_id, approve=True, decided_by="ayoub")

    def test_a_spent_approval_cannot_authorise_a_second_execution(
        self, job: str, store: ApprovalStore
    ) -> None:
        gate = ApprovalGate()
        payload = {"slug": "once"}
        waiting = gate.check(job_id=job, step_id="d", action="site.deploy", payload=payload)
        store.decide(waiting.approval_id, approve=True, decided_by="ayoub")
        assert (
            gate.check(job_id=job, step_id="d", action="site.deploy", payload=payload).outcome
            is ApprovalOutcome.ALLOWED
        )

        gate.consume(waiting.approval_id)
        again = gate.check(job_id=job, step_id="d", action="site.deploy", payload=payload)
        assert again.outcome is ApprovalOutcome.WAITING, "a spent approval ran twice"


class TestExpiry:
    def test_an_expired_request_is_not_spendable(self, job: str, store: ApprovalStore) -> None:
        """Enforced on read, so a stale approval is not usable merely because no
        sweeper has run."""
        proposal = _proposal(job, expires_at=datetime.now(UTC) - timedelta(seconds=1))
        approval_id = store.request(proposal)

        assert store.get(approval_id)["status"] == "expired"
        verdict = ApprovalGate().check(
            job_id=job,
            step_id="deploy",
            action="site.deploy",
            payload={"slug": "clinic", "promote": True},
        )
        assert verdict.outcome is ApprovalOutcome.EXPIRED

    def test_an_expired_request_cannot_be_decided(self, job: str, store: ApprovalStore) -> None:
        approval_id = store.request(
            _proposal(job, expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        with pytest.raises(ValueError, match="already expired"):
            store.decide(approval_id, approve=True, decided_by="ayoub")


class TestConcurrency:
    def test_approving_one_job_does_not_unblock_another(self, store: ApprovalStore) -> None:
        """Two jobs proposing the identical act still need separate decisions —
        the fingerprint is scoped to the job, not global."""
        gate = ApprovalGate()
        job_a = f"job_a_{uuid.uuid4().hex[:8]}"
        job_b = f"job_b_{uuid.uuid4().hex[:8]}"
        payload = {"slug": "same-slug"}

        a = gate.check(job_id=job_a, step_id="d", action="site.deploy", payload=payload)
        b = gate.check(job_id=job_b, step_id="d", action="site.deploy", payload=payload)
        assert a.approval_id != b.approval_id

        store.decide(a.approval_id, approve=True, decided_by="ayoub")

        assert (
            gate.check(job_id=job_a, step_id="d", action="site.deploy", payload=payload).outcome
            is ApprovalOutcome.ALLOWED
        )
        assert (
            gate.check(job_id=job_b, step_id="d", action="site.deploy", payload=payload).outcome
            is ApprovalOutcome.WAITING
        ), "approving A unblocked B"

    def test_two_reviewers_racing_produce_one_decision(
        self, job: str, store: ApprovalStore
    ) -> None:
        """The second writer is refused rather than silently overwriting the
        first, so the audit trail names who actually decided."""
        approval_id = store.request(_proposal(job))
        store.decide(approval_id, approve=True, decided_by="first")
        with pytest.raises(ValueError, match="already approved"):
            store.decide(approval_id, approve=False, decided_by="second")
        assert store.get(approval_id)["decided_by"] == "first"


class TestTheAuditTrail:
    def test_a_decided_request_records_who_when_and_why(
        self, job: str, store: ApprovalStore
    ) -> None:
        approval_id = store.request(_proposal(job))
        store.decide(approval_id, approve=True, decided_by="ayoub", reason="checked the copy")
        row = store.get(approval_id)
        assert row["decided_by"] == "ayoub"
        assert row["decided_at"] is not None
        assert row["decision_reason"] == "checked the copy"
        assert row["requested_by"] == "qevik"

    def test_the_proposal_keeps_the_evidence_that_led_to_it(
        self, job: str, store: ApprovalStore
    ) -> None:
        """A reviewer allowing a publish should be able to see what research
        produced the copy they are approving."""
        proposal = _proposal(
            job,
            provenance={"researched": [{"query": "clinics", "sources": ["https://e.test"]}]},
            evidence=["/tmp/shot.png"],
        )
        row = store.get(store.request(proposal))
        assert row["provenance"]["researched"][0]["sources"] == ["https://e.test"]
        assert row["evidence"] == ["/tmp/shot.png"]

    def test_the_whole_chain_is_reconstructable_from_the_row(
        self, job: str, store: ApprovalStore
    ) -> None:
        approval_id = store.request(_proposal(job))
        store.decide(approval_id, approve=True, decided_by="ayoub")
        row = store.get(approval_id)
        for field in (
            "job_id",
            "step_id",
            "action",
            "required_scope",
            "risk",
            "fingerprint",
            "payload",
            "summary",
            "target",
            "status",
            "requested_by",
            "created_at",
            "decided_by",
            "decided_at",
        ):
            assert field in row, field
