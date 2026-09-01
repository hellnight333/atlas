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
from atlas_kernel.outreach import unreviewed

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

    def test_requesting_approval_records_the_ask_on_the_message(self) -> None:
        """A pending request has to be visible in the message record.

        The review queue answers "has anybody been asked about this draft?" from
        the row and nothing else — `AWAITING_APPROVAL` is the only status that
        records the question having been put. A request that left the row at
        `DRAFT` would be reported as a draft nobody has looked at, and the
        obvious response to that report is a second request for the same
        decision.

        The `approval_requested` event is not a substitute. It names an approval
        and an opportunity, never a message, so a business holding two drafts
        cannot be told from it which one was asked about.
        """
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)

        assert prepared.message.status is OutreachStatus.AWAITING_APPROVAL
        # The row names the request it is waiting on, which is what makes the
        # claim it makes checkable rather than something a reader must trust.
        assert prepared.message.approval_id == request.id
        # Naming the question is not answering it. A pending request stays in
        # the queue, or the drafts somebody is waiting on are exactly the ones
        # the list of drafts somebody is waiting on leaves out.
        assert unreviewed.undecided(prepared.message)
        row = unreviewed.classify(prepared.message)
        assert row.state == unreviewed.ASKED
        assert request.id in row.traces[unreviewed.ASKED]

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


class TestTheAnswerReachesTheMessage:
    """`AWAITING_APPROVAL` is a claim that expires, and nothing expires it.

    `ApprovalService` decides against its own request record and has never heard
    of an outreach message. So every way an approval ends other than a completed
    `send` — a refusal through the approvals API, a cancellation, `expire_due`
    sweeping a request nobody answered — leaves the message asserting an open
    question after the question was answered. The review queue reads that row
    and asks somebody to decide a thing that was already decided.
    """

    @pytest.mark.parametrize(
        "answer, expected_detail",
        [
            (lambda approvals, ident: approvals.reject(ident, actor="ayoub"),
             "rejected by approver"),
            (lambda approvals, ident: approvals.cancel(ident, actor="ayoub"),
             "cancelled"),
            (lambda approvals, ident: approvals.expire(ident), "expired"),
        ],
        ids=["rejected", "cancelled", "expired"],
    )
    def test_a_foreclosed_approval_closes_the_message(
        self, answer, expected_detail
    ) -> None:
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)
        assert unreviewed.classify(prepared.message).state == unreviewed.ASKED

        service.record_decision(prepared, answer(runtime.approval_service, request.id))

        assert prepared.message.status is OutreachStatus.REJECTED
        assert prepared.message.approval_id == request.id
        # Which of the three, said out loud. A request that expired unanswered
        # and one a person refused both stop the send, and recording the first
        # as "rejected by approver" invents a decision nobody made.
        assert expected_detail in (prepared.message.detail or "")
        # And the queue stops listing it. This is the whole point: an answered
        # request that goes on being reported as unanswered is an invitation to
        # ask the same person the same question again.
        assert not unreviewed.undecided(prepared.message)

    def test_the_answer_is_recorded_on_the_timeline(self) -> None:
        """A decision only the message row knows about is one the funnel cannot
        count. `metrics.py` derives from events, not from current state."""
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)
        service.record_decision(
            prepared, runtime.approval_service.reject(request.id, actor="ayoub")
        )

        # Compared by value, like every other timeline assertion here.
        # `BusinessEvent.kind` is a plain string on purpose — each factory adds
        # kinds without editing the opportunity package — and the validator
        # returns `value.strip()`, which is a new `str` and never the enum
        # member. An `is` filter against `PipelineEventKind` therefore matches
        # nothing at all, which is the direction that hides rather than fails:
        # `assert not [...]` written that way would pass on any timeline.
        recorded = [e for e in service.events if e.kind == PipelineEventKind.REJECTED]
        assert len(recorded) == 1
        assert recorded[0].detail["approval_id"] == request.id
        assert recorded[0].detail["approval_state"] == "rejected"

    def test_the_funnel_counts_that_rejection(self) -> None:
        """The event exists so that a number moves, and the number is the test.

        `build_report` groups the timeline by `kind` and reads
        `PipelineEventKind.REJECTED` out of it, so an answer recorded under any
        other name is one the funnel silently does not count — a refusal that
        leaves the message closed and the report claiming nobody said no. This
        asserts the whole path rather than the spelling of a constant.
        """
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)
        assert service.report().rejected == 0

        service.record_decision(
            prepared, runtime.approval_service.reject(request.id, actor="ayoub")
        )

        assert service.report().rejected == 1

    def test_a_pending_request_cannot_be_closed(self) -> None:
        """Closing an undecided request would answer for the approver, which is
        the one thing this gate exists to make impossible."""
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)

        with pytest.raises(OutreachNotApproved, match="nobody has decided"):
            service.record_decision(prepared, request)
        assert prepared.message.status is OutreachStatus.AWAITING_APPROVAL

    def test_an_approval_is_not_recorded_here(self) -> None:
        """A yes goes through `authorise`, which re-derives the fingerprint.

        A second door onto `APPROVED` that skipped that check would be a way to
        authorise delivery of words that moved after a person read them — and it
        would arrive by way of a method whose stated job is bookkeeping.
        """
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")

        with pytest.raises(OutreachNotApproved, match="authorise"):
            service.record_decision(prepared, approved)
        assert prepared.message.approved_fingerprint is None
        assert prepared.message.authorized_automated_at is None

    def test_a_sent_message_never_reopens(self) -> None:
        """The whole flow, ending where it should: nothing that completed is
        offered back to the queue for a second decision."""
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)

        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")
        sent = service.send(prepared, approved, EXAMPLE_PROFILE)

        assert sent.status is OutreachStatus.SENT
        assert not unreviewed.undecided(sent)


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

    def test_a_pending_request_is_stored_as_awaiting_approval(self) -> None:
        """The queue reads the database, not the object the request was made
        from. A status that moved only in memory would still show a pending
        request as an untouched draft to everybody who asks the records."""
        from atlas_kernel.opportunity.repository import OpportunityRepository

        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        service.repository = OpportunityRepository()

        business, _, prepared = _prepared(service)
        service.request_approval(prepared)

        stored = OpportunityRepository().messages_for(business.id)
        row = next(m for m in stored if m.id == prepared.message.id)
        assert row.status is OutreachStatus.AWAITING_APPROVAL
        assert unreviewed.classify(row).state == unreviewed.ASKED
