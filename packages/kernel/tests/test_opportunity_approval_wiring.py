"""The Opportunity Factory against the real approval service (M014).

Everywhere else, approvals are hand-built objects — fast, and fine for proving
the guards. This file uses the actual ``ApprovalService`` the Media Factory
publishes through, because the thing most worth checking is that outreach
reuses that machinery rather than having grown a second approval system beside
it, and a hand-built ``ApprovalRequest`` would prove nothing about the wiring.

Also covers the two paths that only appear when something goes wrong: a refused
send must leave a trace, and a rejection must not leave a sendable message.

And it covers the wiring in both directions, which is the part that decays
quietly. Asking has to *claim* the message before the question exists, or two
workers each create one and whichever loses the write is a live approval nothing
points at. Answering has to reach the row through the path production takes —
the customer endpoint calls `ApprovalService.reject` and nothing else — and has
to land only while the message is still open, or a send recorded in between is
replaced by a refusal that was decided against a state which no longer exists.

Both races are exercised with a worker that read the row before somebody else
wrote it, because that is what the race *is*. A test that re-reads at the moment
of writing proves the check and says nothing about the guard.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from atlas_kernel import db
from atlas_kernel.approval.models import ApprovalContext, ApprovalScope, ApprovalState
from atlas_kernel.composition_root import create_runtime
from atlas_kernel.opportunity.detectors.base import DetectorRegistry
from atlas_kernel.opportunity.detectors.website import WebsiteDetector
from atlas_kernel.opportunity.gate import (
    BOUND_MESSAGE,
    FORECLOSED,
    OUTREACH_ACTION,
    PROPOSAL_FINGERPRINT,
    OutreachGate,
    OutreachNotApproved,
)
from atlas_kernel.opportunity.models import (
    Business,
    OutreachMessage,
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
from atlas_kernel.opportunity.repository import OpportunityRepository, StaleMessage
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


def _durable(approvals, channel: RecordingChannel | None = None, **kwargs):
    """A service whose messages survive the call, which is what a race needs.

    Without a repository there is no row for two workers to contend over, so
    every property below would pass on a service that stored nothing.
    """
    repository = OpportunityRepository()
    service = _service(channel or RecordingChannel(), approvals, **kwargs)
    service.repository = repository
    return service, repository


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


def _stored(repository: OpportunityRepository, message) -> OutreachMessage | None:
    """The row itself, found by id.

    By id and never by "the newest for this business": the seed list resolves to
    one permanent `Business`, so every run of this module adds another message to
    the same company and a positional read would assert about somebody else's.
    """
    for row in repository.messages_for(message.business_id):
        if row.id == message.id:
            return row
    return None


def _questions_about(approvals, message_id: str) -> list:
    return [
        request
        for request in approvals.list_pending()
        if request.metadata.get(BOUND_MESSAGE) == message_id
    ]


class _AsksFromAStaleRead(OpportunityService):
    """A second worker whose read of the message predates the first one's claim.

    Overriding the read is how an interleaving is written down. Both workers pass
    the same checks against the same draft — which is the situation — and what
    has to hold is that only one of them ever creates a question.
    """

    def _as_persisted(self, message):
        return self.snapshot


class _ClosesFromAStaleRead(OpportunityService):
    """A worker whose read of the message predates a send recorded elsewhere.

    Same shape, the other direction: the refusal was decided against a row that
    was still open, and by the time it is written the message has gone out.
    """

    def _message_asked_about(self, approval):
        return self.snapshot


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


class TestAskingClaimsTheMessage:
    """One draft, one question, and the row says so.

    `request_approval` used to create the request and leave the message at
    `DRAFT`, which `outreach.unreviewed` reports as a draft nobody has been asked
    about — and the obvious response to that listing is to ask a second person.
    """

    def test_asking_moves_the_row_and_names_the_request_on_it(self) -> None:
        runtime = create_runtime()
        service, repository = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)
        assert _stored(repository, prepared.message).status is OutreachStatus.DRAFT

        request = service.request_approval(prepared)

        row = _stored(repository, prepared.message)
        assert row.status is OutreachStatus.AWAITING_APPROVAL
        assert row.approval_id == request.id
        assert request.metadata[BOUND_MESSAGE] == row.id, (
            "the approval must name the row it was raised about, or a refusal "
            "arriving later has nothing to bind to"
        )

    def test_two_workers_on_one_draft_raise_exactly_one_question(self) -> None:
        """The claim is taken before the approval exists, so the loser never
        creates one.

        Asking first and claiming afterwards lets both workers pass their checks
        and both call the approval service; whichever loses the write is then a
        pending request with nothing pointing at it, which no later pass can find
        and no person can clear.
        """
        runtime = create_runtime()
        service, repository = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)
        draft = _stored(repository, prepared.message)

        first = service.request_approval(prepared)

        second = _AsksFromAStaleRead(
            detectors=service.detectors, gate=service.gate, outreach=service.outreach
        )
        second.repository = repository
        second.snapshot = draft

        with pytest.raises(OutreachNotApproved, match="no longer the draft"):
            second.request_approval(replace(prepared, message=draft))

        assert [q.id for q in _questions_about(runtime.approval_service, draft.id)] == [
            first.id
        ], "the second worker created a question nobody can reach from the message"
        assert _stored(repository, draft).approval_id == first.id

    def test_a_message_that_already_records_a_decision_is_not_asked_about_again(
        self,
    ) -> None:
        """`infra/approve_send.py` writes these rows too, and an operator runs it
        out of this process. Asking again would move a decision they took back to
        awaiting a question they already answered."""
        runtime = create_runtime()
        service, repository = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)
        repository.save_message(
            prepared.message.model_copy(
                update={
                    "status": OutreachStatus.APPROVED_FOR_MANUAL_SEND,
                    "approved_fingerprint": prepared.proposal.fingerprint,
                }
            )
        )

        with pytest.raises(OutreachNotApproved, match="already records"):
            service.request_approval(prepared)

        assert not _questions_about(runtime.approval_service, prepared.message.id)
        row = _stored(repository, prepared.message)
        assert row.status is OutreachStatus.APPROVED_FOR_MANUAL_SEND
        assert row.approved_fingerprint == prepared.proposal.fingerprint

    def test_a_message_already_under_a_request_is_not_put_to_a_second_person(
        self,
    ) -> None:
        runtime = create_runtime()
        service, repository = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)
        first = service.request_approval(prepared)

        with pytest.raises(OutreachNotApproved, match="already raised under approval"):
            service.request_approval(prepared)

        assert [q.id for q in _questions_about(runtime.approval_service, prepared.message.id)] == [
            first.id
        ]


class TestTheAnswerReachesTheMessage:
    """The other half, and the one that decays quietly.

    Nothing decides an outreach approval by calling into this package: the
    customer endpoint calls `ApprovalService.reject` directly and stops there. So
    the write-back is exercised here the same way — through the approval service
    — and never by calling `record_decision`, which would prove only that the
    method works.
    """

    def test_the_service_watches_the_approvals_it_asks_through(self) -> None:
        runtime = create_runtime()
        service, _ = _durable(runtime.approval_service)
        assert service.watching

    def test_an_approval_service_with_no_bus_is_reported_as_unwatched(self) -> None:
        """Honest rather than optimistic. Most doubles in these tests have no
        bus, and a service that claimed to be watching one would make every
        write-back look wired."""
        assert not _service(RecordingChannel(), None).watching

    def test_a_refusal_through_the_approval_service_closes_the_message(self) -> None:
        runtime = create_runtime()
        service, repository = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)

        runtime.approval_service.reject(request.id, actor="ayoub", comment="not this one")

        row = _stored(repository, prepared.message)
        assert row.status is OutreachStatus.REJECTED
        assert row.approval_id == request.id
        assert row.detail == FORECLOSED[ApprovalState.REJECTED]

    def test_a_cancelled_request_is_not_recorded_as_a_person_refusing(self) -> None:
        """A cancellation and a refusal both stop the send and only one is a
        decision somebody took. "rejected by approver" on a cancellation puts
        words in the mouth of a person who never spoke."""
        runtime = create_runtime()
        service, repository = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)

        runtime.approval_service.cancel(request.id, actor="ayoub", comment="withdrawn")

        row = _stored(repository, prepared.message)
        assert row.status is OutreachStatus.REJECTED
        assert row.detail == FORECLOSED[ApprovalState.CANCELLED]
        assert row.detail != FORECLOSED[ApprovalState.REJECTED]

    def test_an_approval_elsewhere_in_atlas_does_not_reach_an_outreach_message(
        self,
    ) -> None:
        """The bus carries every approval in Atlas. A media publication being
        refused must not arrive at a write-back that would go looking for a
        message it never named."""
        runtime = create_runtime()
        service, repository = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)

        unrelated = runtime.approval_service.create_request(
            title="Publish a video",
            context=ApprovalContext(action="media.publish", requested_by="atlas"),
            metadata={"business_id": prepared.message.business_id},
        )
        runtime.approval_service.reject(unrelated.id, actor="ayoub")

        row = _stored(repository, prepared.message)
        assert row.status is OutreachStatus.AWAITING_APPROVAL
        assert row.approval_id == request.id

    def test_a_refusal_never_overwrites_a_send_recorded_in_between(self) -> None:
        """The whole point of the guard. The refusal was decided against a row
        that was open; by the time it is written the message has gone out, and an
        unconditional save would leave Qevik with no record that it contacted a
        stranger."""
        runtime = create_runtime()
        service, repository = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        asked = _stored(repository, prepared.message)

        moment = datetime.now(UTC)
        repository.save_message(
            asked.model_copy(
                update={
                    "status": OutreachStatus.SENT,
                    "sent_at": moment,
                    "provider_message_id": "provider-1",
                }
            )
        )
        rejected = runtime.approval_service.reject(request.id, actor="ayoub")

        stale = _ClosesFromAStaleRead(
            detectors=service.detectors, gate=service.gate, outreach=service.outreach
        )
        stale.repository = repository
        stale.snapshot = asked

        assert stale.record_decision(rejected) is None

        row = _stored(repository, prepared.message)
        assert row.status is OutreachStatus.SENT
        assert row.provider_message_id == "provider-1"
        assert row.sent_at is not None
        assert PipelineEventKind.REJECTED not in [event.kind for event in stale.events], (
            "a refusal that landed nowhere must not be reported on the timeline as "
            "though it had"
        )

    def test_a_decision_taken_before_the_row_names_its_request_still_reaches_it(
        self,
    ) -> None:
        """The window between creating the question and linking it to the row.

        `request_approval` claims the row first and writes `approval_id` onto it
        second, because the id does not exist until the request does. Inside that
        gap the question is live and the row does not name it — and an approver
        looking at the pending list can answer it there. Found by `approval_id`
        alone, that answer is discarded, the linkage write then lands, and the row
        is left at `AWAITING_APPROVAL` for ever under an approval nobody can
        re-decide.

        Written as the two halves of `request_approval` with the rejection
        interleaved, because that is what the race is.
        """
        runtime = create_runtime()
        service, repository = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)

        claimed = prepared.message.model_copy(
            update={"status": OutreachStatus.AWAITING_APPROVAL}
        )
        repository.save_message(claimed, expecting=OutreachStatus.DRAFT)
        request = service.gate.request(prepared.outcome, requested_by="atlas")
        assert not _stored(repository, prepared.message).approval_id, (
            "the row must still be unlinked, or this is not the window under test"
        )

        runtime.approval_service.reject(request.id, actor="ayoub", comment="not this one")

        row = _stored(repository, prepared.message)
        assert row.status is OutreachStatus.REJECTED
        assert row.approval_id == request.id
        assert row.detail == FORECLOSED[ApprovalState.REJECTED]

        # And the linkage write that was on its way cannot undo it: it was
        # decided against a row that was open, and the row no longer is.
        with pytest.raises(StaleMessage):
            repository.save_message(
                claimed.model_copy(update={"approval_id": request.id}),
                expecting=OutreachStatus.AWAITING_APPROVAL,
            )

    def test_that_window_does_not_let_a_refusal_close_somebody_elses_question(
        self,
    ) -> None:
        """The fallback binds on the approval's own record of which row it named,
        and that is weaker than the row naming the approval back — so it applies
        only to a row that names *no* approval. A row already raised under one
        request is not closed by a decision about another."""
        runtime = create_runtime()
        service, repository = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)
        first = service.request_approval(prepared)

        # Nothing in the pipeline creates a second question about a linked row —
        # `request_approval` refuses — so this is built by hand, which is exactly
        # the case a binding has to survive.
        other = runtime.approval_service.create_request(
            title="Contact Al Noor Dental Clinic",
            context=ApprovalContext(action=OUTREACH_ACTION, requested_by="atlas"),
            metadata={
                "business_id": prepared.message.business_id,
                BOUND_MESSAGE: prepared.message.id,
            },
        )
        runtime.approval_service.reject(other.id, actor="ayoub")

        row = _stored(repository, prepared.message)
        assert row.status is OutreachStatus.AWAITING_APPROVAL
        assert row.approval_id == first.id

    def test_a_suppression_that_landed_nowhere_is_not_written_to_the_timeline(
        self,
    ) -> None:
        """A `SUPPRESSED` entry beside the `SENT` that beat it is worse than no
        entry at all.

        The timeline is where the no-spam guarantee is read back from, and an
        entry saying a guard stopped a message that in fact went out reads as a
        recipient who was protected and was not. Same rule as `record_decision`:
        a write that landed nowhere is not reported as though it had.
        """
        runtime = create_runtime()
        service, repository = _durable(
            runtime.approval_service,
            suppression=SuppressionList(["hello@alnoor.test"]),
        )
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")

        # Somebody else records the send while this worker is between the
        # approval it read and the refusal it is about to write.
        asked = _stored(repository, prepared.message)
        repository.save_message(
            asked.model_copy(
                update={
                    "status": OutreachStatus.SENT,
                    "sent_at": datetime.now(UTC),
                    "provider_message_id": "provider-1",
                }
            )
        )

        with pytest.raises(OutreachRefused, match="suppression list"):
            service.send(prepared, approved, EXAMPLE_PROFILE)

        row = _stored(repository, prepared.message)
        assert row.status is OutreachStatus.SENT
        assert row.provider_message_id == "provider-1"
        assert PipelineEventKind.SUPPRESSED not in [event.kind for event in service.events], (
            "a suppression that landed nowhere must not be reported on the timeline "
            "beside the send that beat it"
        )
        assert prepared.message.status is not OutreachStatus.SUPPRESSED

    def test_a_message_that_already_went_out_is_passed_over(self) -> None:
        """The same protection one step earlier, through the ordinary path: a row
        recording a send is not a row with an open question on it."""
        runtime = create_runtime()
        service, repository = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        asked = _stored(repository, prepared.message)
        repository.save_message(
            asked.model_copy(
                update={"status": OutreachStatus.SENT, "sent_at": datetime.now(UTC)}
            )
        )

        rejected = runtime.approval_service.reject(request.id, actor="ayoub")

        assert service.record_decision(rejected) is None
        assert _stored(repository, prepared.message).status is OutreachStatus.SENT

    def test_a_suppressed_send_closes_the_row_rather_than_leaving_it_awaiting(
        self,
    ) -> None:
        """A person said yes and a guard said no anyway. The question is answered
        either way, and a row left at `AWAITING_APPROVAL` goes on telling the
        review queue that somebody still owes a decision they have given."""
        runtime = create_runtime()
        service, repository = _durable(
            runtime.approval_service,
            suppression=SuppressionList(["hello@alnoor.test"]),
        )
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")

        with pytest.raises(OutreachRefused, match="suppression list"):
            service.send(prepared, approved, EXAMPLE_PROFILE)

        row = _stored(repository, prepared.message)
        assert row.status is OutreachStatus.SUPPRESSED
        assert row.approval_id == request.id
        assert row.approved_fingerprint == prepared.proposal.fingerprint, (
            "the refusal must keep what the approval established, or it reads as a "
            "row nobody ever decided"
        )


class TestTheDecidingProcessIsWired:
    """Where the write-back actually has to be subscribed.

    Every test above builds an `OpportunityService`, and building one is what
    subscribes the handler — which is why they all pass and none of them says
    anything about production. The process that decides approvals is
    `atlas_kernel.api`, which constructs a runtime and no pipeline: nothing there
    ever built an `OpportunityService`, so `/approvals/{id}/reject` moved the
    approval and left the outreach row saying `AWAITING_APPROVAL` for ever.

    So these build no watching service at all. If the composition root stops
    wiring it, they fail.
    """

    def test_the_runtime_watches_outreach_approvals(self) -> None:
        runtime = create_runtime()

        assert runtime.outreach_decisions.watching

    def test_the_wired_service_has_no_way_to_send(self) -> None:
        """It exists to write answers back, and is on no path that should reach a
        channel. A recording channel would capture the message and hand back a
        provider id, which is how an accidental send comes to look like it
        worked."""
        runtime = create_runtime()

        assert runtime.outreach_decisions.outreach.channel_name == "unwired"
        with pytest.raises(OutreachRefused, match="no sending identity"):
            runtime.outreach_decisions.outreach._channel.deliver(  # noqa: SLF001
                OutreachMessage(
                    proposal_id="p", business_id="b", channel="unwired",
                    recipient="nobody@example.test", subject="s", body="b",
                )
            )

    def test_a_rejection_closes_the_row_with_no_pipeline_in_the_process(self) -> None:
        """The pipeline here is built against an approval service with no bus, so
        it subscribes to nothing. The only subscriber on the runtime's bus is the
        one the composition root made — and it is the one that has to do the
        work."""
        runtime = create_runtime()
        pipeline, repository = _durable(None)
        assert not pipeline.watching, "this pipeline must not be the thing under test"
        _, _, prepared = _prepared(pipeline)

        # Asking, done the way `request_approval` does it, but through a bare
        # gate so that nothing in this test subscribes to the runtime's bus.
        asking = OutreachGate(approvals=runtime.approval_service)
        request = asking.request(prepared.outcome, requested_by="atlas")
        repository.save_message(
            prepared.message.model_copy(
                update={
                    "status": OutreachStatus.AWAITING_APPROVAL,
                    "approval_id": request.id,
                }
            ),
            expecting=OutreachStatus.DRAFT,
        )

        runtime.approval_service.reject(request.id, actor="ayoub", comment="not this one")

        row = _stored(repository, prepared.message)
        assert row.status is OutreachStatus.REJECTED, (
            "nothing in the deciding process wrote the answer back onto the row"
        )
        assert row.detail == FORECLOSED[ApprovalState.REJECTED]


class TestARefusalMustBeAboutTheseWords:
    """`authorise` proves the approval describes the message by re-deriving the
    fingerprint. A refusal has no fingerprint, so it has to bind on an identifier
    — and on nothing weaker."""

    def test_matching_business_proposal_recipient_and_channel_do_not_bind(self) -> None:
        """The four together look like they pick out one message and they do not:
        `infra/outreach_drafts.py` writes a WhatsApp draft and an email draft from
        one proposal, and a draft rewritten after a typo keeps all four. Accepting
        them would close the wrong row and leave the refused one in the queue."""
        runtime = create_runtime()
        service, _ = _durable(runtime.approval_service)
        business, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        rejected = runtime.approval_service.reject(request.id, actor="ayoub")

        twin = OutreachMessage(
            proposal_id=prepared.proposal.id,
            business_id=business.id,
            channel=prepared.message.channel,
            recipient=prepared.message.recipient,
            subject=prepared.proposal.subject,
            body=prepared.proposal.body,
        )

        with pytest.raises(OutreachNotApproved, match="was raised about message"):
            service.gate.reject(twin, rejected)

    def test_a_question_nobody_has_answered_cannot_close_a_message(self) -> None:
        runtime = create_runtime()
        service, _ = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)

        with pytest.raises(OutreachNotApproved, match="nobody has decided"):
            service.gate.reject(prepared.message, request)

    def test_an_approved_request_is_not_recorded_as_a_refusal(self) -> None:
        """The only door onto `APPROVED` is `authorise`, because it is the only
        one that re-derives the fingerprint first."""
        runtime = create_runtime()
        service, _ = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")

        with pytest.raises(OutreachNotApproved, match="record that with authorise"):
            service.gate.reject(prepared.message, approved)

    def test_an_unforeclosed_approval_writes_nothing_back(self) -> None:
        runtime = create_runtime()
        service, repository = _durable(runtime.approval_service)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)

        with pytest.raises(OutreachNotApproved, match="has not foreclosed"):
            service.record_decision(request)

        assert _stored(repository, prepared.message).status is OutreachStatus.AWAITING_APPROVAL


class TestDurableRun:
    def test_a_run_with_a_repository_survives_the_process(self) -> None:
        """Without persistence the funnel resets and the cooldown forgets who
        has been contacted — which is a no-spam guarantee, not a nicety."""
        runtime = create_runtime()
        service, _ = _durable(runtime.approval_service)

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
