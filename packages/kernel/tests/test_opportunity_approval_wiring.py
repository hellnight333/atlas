"""The Opportunity Factory against the real approval service (M014).

Everywhere else, approvals are hand-built objects — fast, and fine for proving
the guards. This file uses the actual ``ApprovalService`` the Media Factory
publishes through, because the thing most worth checking is that outreach
reuses that machinery rather than having grown a second approval system beside
it, and a hand-built ``ApprovalRequest`` would prove nothing about the wiring.

Also covers the two paths that only appear when something goes wrong: a refused
send must leave a trace, and a rejection must not leave a sendable message.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_kernel import db
from atlas_kernel.approval.models import ApprovalScope, ApprovalState
from atlas_kernel.composition_root import create_runtime
from atlas_kernel.opportunity.detectors.base import DetectorRegistry
from atlas_kernel.opportunity.detectors.website import WebsiteDetector
from atlas_kernel.opportunity.gate import (
    OUTREACH_ACTION,
    PROPOSAL_FINGERPRINT,
    OutreachGate,
    OutreachNotApproved,
)
from atlas_kernel.opportunity.models import (
    Business,
    OutreachStatus,
    PipelineEventKind,
)
from atlas_kernel.opportunity.outreach import (
    OutreachRefused,
    OutreachService,
    RecordingChannel,
    SuppressionList,
)
from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE
from atlas_kernel.opportunity.service import OpportunityService
from atlas_kernel.opportunity.tenancy import ALL_TENANTS

BARE_PAGE = "<html><body><p>Coming soon</p></body></html>"
SEED_CSV = "name,website,email\nAl Noor Dental Clinic,https://alnoor.test,hello@alnoor.test\n"


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


def _service(channel: RecordingChannel, approvals, **kwargs) -> OpportunityService:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=BARE_PAGE)

    from atlas_kernel.opportunity.sources import SeedListSource

    registry = DetectorRegistry()
    registry.register_source(SeedListSource.from_csv(SEED_CSV))
    registry.register_detector(
        WebsiteDetector(
            client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
        )
    )
    return OpportunityService(
        detectors=registry,
        gate=OutreachGate(approvals=approvals),
        outreach=OutreachService(channel, **kwargs),
    )


def _prepared(service: OpportunityService):
    opportunity = service.scan(EXAMPLE_PROFILE, limit=1)[0]
    business = Business(
        id=opportunity.business_id,
        name="Al Noor Dental Clinic",
        geography="United Arab Emirates",
        website="https://alnoor.test",
        email="hello@alnoor.test",
    )
    return business, opportunity, service.prepare(business, opportunity, EXAMPLE_PROFILE)


class TestRealApprovalService:
    def test_requesting_approval_creates_a_pending_request_and_sends_nothing(self) -> None:
        runtime = create_runtime()
        channel = RecordingChannel()
        service = _service(channel, runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared, requested_by="atlas")

        assert request.state is ApprovalState.PENDING
        assert channel.delivered == []
        assert runtime.approval_service.get(request.id) is not None

    def test_the_request_carries_the_scopes_a_policy_can_act_on(self) -> None:
        """Named scopes and a named action, so a policy can demand a second
        approver for outreach without the gate knowing such a policy exists."""
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)

        assert request.action == OUTREACH_ACTION
        assert ApprovalScope.EXTERNAL_API in request.scopes
        assert ApprovalScope.NETWORK in request.scopes

    def test_the_approver_can_see_the_evidence_behind_every_claim(self) -> None:
        """An approver who cannot check what the claims rest on is being asked
        to trust the generator, which is what the evidence rule exists to avoid."""
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)
        evidence = request.payload["evidence"]

        assert evidence, "the approval carries no evidence"
        assert all(item["observed"] for item in evidence)
        assert request.metadata[PROPOSAL_FINGERPRINT] == prepared.proposal.fingerprint

    def test_a_human_approving_makes_the_message_sendable(self) -> None:
        runtime = create_runtime()
        channel = RecordingChannel()
        service = _service(channel, runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")
        sent = service.send(prepared, approved, EXAMPLE_PROFILE)

        assert sent.status is OutreachStatus.SENT
        assert len(channel.delivered) == 1

    def test_a_pending_request_cannot_be_sent(self) -> None:
        runtime = create_runtime()
        channel = RecordingChannel()
        service = _service(channel, runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)

        with pytest.raises(OutreachNotApproved, match="pending"):
            service.send(prepared, request, EXAMPLE_PROFILE)
        assert channel.delivered == []

    def test_a_rejected_request_cannot_be_sent(self) -> None:
        runtime = create_runtime()
        channel = RecordingChannel()
        service = _service(channel, runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)
        rejected = runtime.approval_service.reject(
            request.id, actor="ayoub", comment="not this one"
        )

        with pytest.raises(OutreachNotApproved, match="rejected"):
            service.send(prepared, rejected, EXAMPLE_PROFILE)
        assert channel.delivered == []

    def test_rejecting_marks_the_message_rather_than_leaving_it_draft(self) -> None:
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)
        rejected = runtime.approval_service.reject(request.id, actor="ayoub")
        marked = service.gate.reject(prepared.message, rejected)

        assert marked.status is OutreachStatus.REJECTED
        assert marked.approval_id == request.id


class TestRefusalsLeaveATrace:
    def test_a_suppressed_send_records_an_event(self) -> None:
        """A refusal that vanishes is a refusal nobody can audit — and the
        funnel would report it as if the message had simply never existed."""
        runtime = create_runtime()
        channel = RecordingChannel()
        service = _service(
            channel,
            runtime.approval_service,
            suppression=SuppressionList(["hello@alnoor.test"]),
        )
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")

        with pytest.raises(OutreachRefused, match="suppression list"):
            service.send(prepared, approved, EXAMPLE_PROFILE)

        assert channel.delivered == []
        kinds = [event.kind for event in service.events]
        assert PipelineEventKind.SUPPRESSED in kinds
        assert PipelineEventKind.SENT not in kinds

    def test_a_channel_failure_is_reported_as_a_failed_send(self) -> None:
        runtime = create_runtime()

        class Failing:
            name = "failing"

            def deliver(self, message):
                raise RuntimeError("smtp refused connection")

        service = _service(RecordingChannel(), runtime.approval_service)
        service.outreach = OutreachService(Failing())
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")
        result = service.send(prepared, approved, EXAMPLE_PROFILE)

        assert result.status is OutreachStatus.FAILED
        assert PipelineEventKind.SEND_FAILED in [event.kind for event in service.events]


class TestDurableRun:
    def test_a_run_with_a_repository_survives_the_process(self) -> None:
        """Without persistence the funnel resets and the cooldown forgets who
        has been contacted — which is a no-spam guarantee, not a nicety."""
        from atlas_kernel.opportunity.repository import OpportunityRepository

        runtime = create_runtime()
        repository = OpportunityRepository()
        service = _service(RecordingChannel(), runtime.approval_service)
        service.repository = repository

        business, opportunity, prepared = _prepared(service)
        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")
        service.send(prepared, approved, EXAMPLE_PROFILE)

        # A fresh repository stands in for a restarted process.
        reloaded = OpportunityRepository()
        assert reloaded.get_business(business.id, tenant=ALL_TENANTS) is not None
        assert reloaded.list_findings(business.id)
        assert reloaded.load_contact_history(tenant=ALL_TENANTS).within_cooldown(
            business.id, EXAMPLE_PROFILE.contact_cooldown_days
        )
        stored = [e for e in reloaded.list_events(tenant=ALL_TENANTS) if e.opportunity_id == opportunity.id]
        assert PipelineEventKind.SENT in [e.kind for e in stored]
