"""The Opportunity Factory against the real approval service (M014).

Everywhere else, approvals are hand-built objects — fast, and fine for proving
the guards. This file uses the actual ``ApprovalService`` the Media Factory
publishes through, because the thing most worth checking is that outreach
reuses that machinery rather than having grown a second approval system beside
it, and a hand-built ``ApprovalRequest`` would prove nothing about the wiring.

Also covers the two paths that only appear when something goes wrong: a refused
send must leave a trace, and a rejection must not leave a sendable message.

And it covers what happens to the *message record* as the decision moves, which
is a separate question from what happens to the approval. `ApprovalService`
settles requests against its own records and knows nothing about outreach
messages, so every one of those transitions has to be written back or the row
goes on saying a person still owes an answer they have already given —
`TestTheMessageFollowsTheDecision`. The review queue in `outreach.unreviewed`
reads exactly that row, and is used here as the reader whose account of the
message has to stay true.
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
from atlas_kernel.opportunity.repository import OpportunityRepository
from atlas_kernel.opportunity.service import OpportunityService
from atlas_kernel.opportunity.tenancy import ALL_TENANTS
from atlas_kernel.outreach import unreviewed

BARE_PAGE = "<html><body><p>Coming soon</p></body></html>"
SEED_CSV = "name,website,email\nAl Noor Dental Clinic,https://alnoor.test,hello@alnoor.test\n"
OTHER_CSV = "name,website,email\nBright Smile Dental,https://bright.test,hi@bright.test\n"


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


def _service(
    channel: RecordingChannel, approvals, *, seed: str = SEED_CSV, **kwargs
) -> OpportunityService:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=BARE_PAGE)

    from atlas_kernel.opportunity.sources import SeedListSource

    registry = DetectorRegistry()
    registry.register_source(SeedListSource.from_csv(seed))
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


def _prepared(
    service: OpportunityService,
    *,
    name: str = "Al Noor Dental Clinic",
    website: str = "https://alnoor.test",
    email: str = "hello@alnoor.test",
):
    opportunity = service.scan(EXAMPLE_PROFILE, limit=1)[0]
    business = Business(
        id=opportunity.business_id,
        name=name,
        geography="United Arab Emirates",
        website=website,
        email=email,
    )
    return business, opportunity, service.prepare(business, opportunity, EXAMPLE_PROFILE)


def _durable(runtime, channel: RecordingChannel | None = None, **kwargs) -> OpportunityService:
    """A service that persists, which is the only way a decision can arrive late.

    `record_decision` is handed an approval and has to find the row it was
    raised about. Without a repository there is no row to find — which is the
    honest answer for a dry scan, and useless for testing the wiring.
    """
    service = _service(channel or RecordingChannel(), runtime.approval_service, **kwargs)
    service.repository = OpportunityRepository()
    return service


def _stored(message_id: str, business_id: str):
    """The row as a restarted process would read it back."""
    rows = [m for m in OpportunityRepository().messages_for(business_id) if m.id == message_id]
    assert rows, f"message {message_id} was never persisted"
    return rows[-1]


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


class TestTheMessageFollowsTheDecision:
    """The row says what the records say, at every point the decision moves.

    One property: **the message never claims an open question that has been
    answered, and never claims an answer nobody gave.** A row stuck at
    `AWAITING_APPROVAL` after a person decided puts the same stranger back in
    the review queue, and the obvious response to that listing is to ask
    somebody a second time about words they already refused.

    The same property read backwards is why asking is guarded too: a second
    `request_approval` on a row that has already been answered would put the
    claim back on a message that carries an answer, which is the same lie
    written from the other end.
    """

    def test_asking_is_recorded_on_the_message_and_not_only_on_the_timeline(self) -> None:
        """`AWAITING_APPROVAL` is the only thing in the message record that says
        the question was put about *these* words. The timeline entry names an
        approval and an opportunity, and a business holding two drafts has two
        candidate rows, so it cannot stand in."""
        runtime = create_runtime()
        service = _durable(runtime)
        business, _, prepared = _prepared(service)

        request = service.request_approval(prepared)

        assert prepared.message.status is OutreachStatus.AWAITING_APPROVAL
        assert prepared.message.approval_id == request.id
        stored = _stored(prepared.message.id, business.id)
        assert stored.status is OutreachStatus.AWAITING_APPROVAL
        assert stored.approval_id == request.id

    def test_a_pending_request_still_reads_as_undecided_to_the_review_queue(self) -> None:
        """The ask must not read as an act. `approval_id` names a question, and
        a queue that took it for a decision would hide every row somebody is
        actually waiting on."""
        runtime = create_runtime()
        service = _durable(runtime)
        business, _, prepared = _prepared(service)

        service.request_approval(prepared)

        assert unreviewed.undecided(_stored(prepared.message.id, business.id))

    def test_a_refusal_taken_elsewhere_is_written_back_onto_the_persisted_row(self) -> None:
        """The blocking case. The refusal happens through the approvals API,
        long after this service forgot the run, and nothing but this call ties
        it back to the message the question was raised about."""
        runtime = create_runtime()
        service = _durable(runtime)
        business, _, prepared = _prepared(service)
        request = service.request_approval(prepared)

        refused = runtime.approval_service.reject(request.id, actor="ayoub", comment="not this one")
        marked = service.record_decision(refused)

        assert marked is not None
        assert marked.id == prepared.message.id
        stored = _stored(prepared.message.id, business.id)
        assert stored.status is OutreachStatus.REJECTED
        assert stored.detail == "rejected by approver"
        assert not unreviewed.undecided(stored)
        assert PipelineEventKind.REJECTED in [event.kind for event in service.events]

    def test_a_cancelled_request_is_not_reported_as_somebody_refusing(self) -> None:
        """A cancellation and a refusal both stop the send and are not the same
        event. Writing "rejected by approver" onto a request nobody answered
        puts words in the mouth of a person who never spoke."""
        runtime = create_runtime()
        service = _durable(runtime)
        business, _, prepared = _prepared(service)
        request = service.request_approval(prepared)

        cancelled = runtime.approval_service.cancel(request.id, actor="ayoub")
        service.record_decision(cancelled)

        stored = _stored(prepared.message.id, business.id)
        assert stored.status is OutreachStatus.REJECTED
        assert "cancelled" in (stored.detail or "")
        assert "rejected by approver" != stored.detail

    def test_an_expiry_is_written_back_as_an_expiry(self) -> None:
        """`expire_due` sweeps requests nobody answered. The row it leaves
        behind is the one that decays quietly: still awaiting a person who was
        never going to answer."""
        runtime = create_runtime()
        service = _durable(runtime)
        business, _, prepared = _prepared(service)
        request = service.request_approval(prepared)

        expired = runtime.approval_service.expire(request.id)
        service.record_decision(expired)

        stored = _stored(prepared.message.id, business.id)
        assert stored.status is OutreachStatus.REJECTED
        assert "expired" in (stored.detail or "")

    def test_the_recorded_state_says_which_of_the_three_it_was(self) -> None:
        runtime = create_runtime()
        service = _durable(runtime)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)

        service.record_decision(runtime.approval_service.cancel(request.id, actor="ayoub"))

        decided = [e for e in service.events if e.kind == PipelineEventKind.REJECTED]
        assert decided[-1].detail["approval_state"] == ApprovalState.CANCELLED.value
        assert decided[-1].detail["message_id"] == prepared.message.id

    def test_a_message_that_already_records_an_outcome_is_left_alone(self) -> None:
        """A send that happened is not undone by a later refusal of the request.

        Atlas may keep a row honest; it may not reinterpret what a person did.
        The row here was sent while the request was still open — records that
        disagree, which is exactly when a sweeper is dangerous.
        """
        runtime = create_runtime()
        service = _durable(runtime)
        business, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        sent = prepared.message.model_copy(
            update={
                "status": OutreachStatus.SENT,
                "sent_at": prepared.message.created_at,
                "provider_message_id": "recorded-1",
            }
        )
        service.repository.save_message(sent)

        refused = runtime.approval_service.reject(request.id, actor="ayoub")

        assert service.record_decision(refused) is None
        assert _stored(sent.id, business.id).status is OutreachStatus.SENT
        assert PipelineEventKind.REJECTED not in [event.kind for event in service.events]

    def test_an_approval_with_no_message_behind_it_is_an_ordinary_none(self) -> None:
        """Most approvals in Atlas are not about outreach at all. Being handed
        one is not a failure and must not raise."""
        runtime = create_runtime()
        service = _durable(runtime)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        elsewhere = runtime.approval_service.reject(request.id, actor="ayoub").model_copy(
            update={"id": "approval-nothing-points-here"}
        )

        assert service.record_decision(elsewhere) is None

    def test_an_undecided_request_cannot_be_written_onto_a_message(self) -> None:
        """Closing a row while the question is open would answer for the
        approver, which is the one thing this whole path exists to prevent."""
        runtime = create_runtime()
        service = _durable(runtime)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)

        with pytest.raises(OutreachNotApproved, match="has not foreclosed"):
            service.record_decision(request)

    def test_an_approved_request_is_not_a_second_door_onto_sending(self) -> None:
        """A yes is recorded by `gate.authorise`, which re-derives the
        fingerprint. A method for keeping a row honest must not become another
        way to mark a message sendable."""
        runtime = create_runtime()
        service = _durable(runtime)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")

        with pytest.raises(OutreachNotApproved, match="has not foreclosed"):
            service.record_decision(approved)

    def test_an_approved_send_that_is_refused_leaves_no_open_question(self) -> None:
        """A person said yes and a guard said no anyway. Both are true, and the
        row has to stop claiming somebody still owes an answer — otherwise the
        review queue offers the same decision again."""
        runtime = create_runtime()
        channel = RecordingChannel()
        service = _durable(
            runtime, channel, suppression=SuppressionList(["hello@alnoor.test"])
        )
        business, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")

        with pytest.raises(OutreachRefused, match="suppression list"):
            service.send(prepared, approved, EXAMPLE_PROFILE)

        assert channel.delivered == []
        assert prepared.message.status is OutreachStatus.SUPPRESSED
        stored = _stored(prepared.message.id, business.id)
        assert stored.status is OutreachStatus.SUPPRESSED
        assert "suppression list" in (stored.detail or "")
        assert not unreviewed.undecided(stored)

    def test_the_refused_row_keeps_what_the_approval_established(self) -> None:
        """Written from the authorised message, so the refusal is recognisably a
        decision somebody took rather than a row nobody ever answered."""
        runtime = create_runtime()
        service = _durable(
            runtime, suppression=SuppressionList(["hello@alnoor.test"])
        )
        business, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")

        with pytest.raises(OutreachRefused):
            service.send(prepared, approved, EXAMPLE_PROFILE)

        stored = _stored(prepared.message.id, business.id)
        assert stored.approval_id == request.id
        assert stored.approved_fingerprint == prepared.proposal.fingerprint

    def test_a_sent_message_cannot_be_put_back_to_awaiting_by_asking_again(self) -> None:
        """The write in `request_approval` is unconditional, and a
        `PreparedOutreach` is reusable — so a second call would move a delivered
        row back to `AWAITING_APPROVAL` while `sent_at` stayed where it was: a
        row reporting an open question and a completed send at once."""
        runtime = create_runtime()
        service = _durable(runtime)
        business, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")
        service.send(prepared, approved, EXAMPLE_PROFILE)

        with pytest.raises(OutreachNotApproved, match="already records what was decided"):
            service.request_approval(prepared)

        stored = _stored(prepared.message.id, business.id)
        assert stored.status is OutreachStatus.SENT
        assert stored.sent_at is not None
        assert stored.approval_id == request.id

    def test_a_refused_send_is_not_reopened_by_asking_again(self) -> None:
        """Same guard, from the exit that leaves the row `SUPPRESSED`. A person
        said yes, a guard said no, and neither of those is an open question."""
        runtime = create_runtime()
        service = _durable(runtime, suppression=SuppressionList(["hello@alnoor.test"]))
        business, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")
        with pytest.raises(OutreachRefused):
            service.send(prepared, approved, EXAMPLE_PROFILE)

        with pytest.raises(OutreachNotApproved, match="already records what was decided"):
            service.request_approval(prepared)

        assert _stored(prepared.message.id, business.id).status is OutreachStatus.SUPPRESSED

    def test_a_rejected_message_is_not_reopened_by_asking_again(self) -> None:
        """A refusal written back by `record_decision` is an answer. Re-asking
        would offer the same stranger's words to a second person as though the
        first had never spoken."""
        runtime = create_runtime()
        service = _durable(runtime)
        business, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        service.record_decision(runtime.approval_service.reject(request.id, actor="ayoub"))
        prepared.message = _stored(prepared.message.id, business.id)

        with pytest.raises(OutreachNotApproved, match="already records what was decided"):
            service.request_approval(prepared)

        assert _stored(prepared.message.id, business.id).status is OutreachStatus.REJECTED

    def test_a_message_already_awaiting_an_answer_is_not_asked_about_twice(self) -> None:
        """The other half: re-asking a row that names a pending request abandons
        that request — still open, and now with nothing pointing at it — and
        puts the same words to a second person."""
        runtime = create_runtime()
        service = _durable(runtime)
        business, _, prepared = _prepared(service)
        first = service.request_approval(prepared)
        before = len(runtime.approval_service.list_pending())

        with pytest.raises(OutreachNotApproved, match="already raised under approval"):
            service.request_approval(prepared)

        assert len(runtime.approval_service.list_pending()) == before
        assert _stored(prepared.message.id, business.id).approval_id == first.id

    def test_settling_the_question_is_what_makes_asking_again_possible(self) -> None:
        """The guard must not be a dead end. A cancelled request is closed by
        `record_decision`, and the next question is asked about fresh words —
        which is what `prepare` produces."""
        runtime = create_runtime()
        service = _durable(runtime)
        business, opportunity, prepared = _prepared(service)
        first = service.request_approval(prepared)
        service.record_decision(runtime.approval_service.cancel(first.id, actor="ayoub"))

        again = service.prepare(business, opportunity, EXAMPLE_PROFILE)
        second = service.request_approval(again)

        assert second.id != first.id
        assert again.message.id != prepared.message.id
        assert _stored(again.message.id, business.id).status is OutreachStatus.AWAITING_APPROVAL
        assert _stored(prepared.message.id, business.id).status is OutreachStatus.REJECTED

    def test_a_delivered_message_is_persisted_as_sent_rather_than_awaiting(self) -> None:
        runtime = create_runtime()
        service = _durable(runtime)
        business, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")

        sent = service.send(prepared, approved, EXAMPLE_PROFILE)

        assert prepared.message.status is OutreachStatus.SENT
        assert _stored(sent.id, business.id).status is OutreachStatus.SENT


class TestARejectionBelongsToOneMessage:
    """`authorise` proves the approval describes the message with the
    fingerprint. A refusal has no fingerprint — nothing about a refused request
    describes a body of text — so `reject` has to establish the binding itself,
    or it closes whichever row it is handed with a decision nobody took about
    it, while the message somebody actually refused stays in the queue."""

    def test_refusing_one_request_does_not_close_a_message_raised_under_another(self) -> None:
        """Two requests exist about the same words — the second raised straight
        through the gate, because `request_approval` will not put a message that
        already names one to a second person. The row stays bound to the first,
        and the second one's refusal is not an answer about it."""
        runtime = create_runtime()
        service = _durable(runtime)
        _, _, prepared = _prepared(service)
        first = service.request_approval(prepared)
        bound_to_first = prepared.message
        second = service.gate.request(prepared.outcome)
        assert bound_to_first.approval_id == first.id != second.id

        refused_second = runtime.approval_service.reject(second.id, actor="ayoub")

        with pytest.raises(OutreachNotApproved, match="raised under approval"):
            service.gate.reject(bound_to_first, refused_second)

    def test_another_businesss_refusal_does_not_close_this_draft(self) -> None:
        """The row names no request — every draft written before the question is
        put — so the only link available is the message the approval names."""
        runtime = create_runtime()
        mine = _service(RecordingChannel(), runtime.approval_service)
        theirs = _service(RecordingChannel(), runtime.approval_service, seed=OTHER_CSV)
        _, _, ours = _prepared(mine)
        _, _, other = _prepared(
            theirs,
            name="Bright Smile Dental",
            website="https://bright.test",
            email="hi@bright.test",
        )
        request = theirs.request_approval(other)
        refused = runtime.approval_service.reject(request.id, actor="ayoub")

        assert ours.message.approval_id is None
        with pytest.raises(OutreachNotApproved, match="was raised about message"):
            mine.gate.reject(ours.message, refused)

    def test_a_refusal_about_another_channel_does_not_close_this_one(self) -> None:
        """A business holds a WhatsApp draft beside an email draft. They are two
        rows, and the request names the one it was raised about."""
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)
        sibling = prepared.message.model_copy(
            update={"id": "whatsapp-draft", "channel": "whatsapp", "approval_id": None}
        )
        request = service.request_approval(prepared)
        refused = runtime.approval_service.reject(request.id, actor="ayoub")

        with pytest.raises(OutreachNotApproved, match="was raised about message"):
            service.gate.reject(sibling, refused)

    def test_a_second_draft_of_the_same_words_is_not_closed_by_the_first_refusal(self) -> None:
        """The case four descriptive fields cannot separate.

        A draft rewritten after a typo keeps its business, its proposal, its
        recipient *and* its channel — all four equal, two live rows, different
        ids and different words. Binding on the description would accept a
        refusal raised about one of them for the other, which is the wrong-row
        closure the guard exists to prevent.
        """
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)
        rewritten = prepared.message.model_copy(
            update={
                "id": "rewritten-after-a-typo",
                "body": prepared.message.body + "\n\nP.S. corrected.",
                "approval_id": None,
            }
        )
        request = service.request_approval(prepared)
        refused = runtime.approval_service.reject(request.id, actor="ayoub")

        assert rewritten.business_id == prepared.message.business_id
        assert rewritten.proposal_id == prepared.message.proposal_id
        assert rewritten.recipient == prepared.message.recipient
        assert rewritten.channel == prepared.message.channel

        with pytest.raises(OutreachNotApproved, match="was raised about message"):
            service.gate.reject(rewritten, refused)

    def test_an_approval_naming_no_message_is_refused(self) -> None:
        """Silence is not agreement. An approval that names no message cannot be
        shown to be about this row, and stamping it on anyway is how the wrong
        row gets closed."""
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        bare = runtime.approval_service.reject(request.id, actor="ayoub").model_copy(
            update={"metadata": {}}
        )
        draft = prepared.message.model_copy(update={"approval_id": None})

        with pytest.raises(OutreachNotApproved, match="nothing ties the two together"):
            service.gate.reject(draft, bare)

    def test_the_request_it_was_raised_under_closes_it(self) -> None:
        """The other direction, so the guard is not simply refusing everything."""
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        refused = runtime.approval_service.reject(request.id, actor="ayoub")

        marked = service.gate.reject(prepared.message, refused)

        assert marked.status is OutreachStatus.REJECTED
        assert marked.approval_id == request.id

    def test_a_draft_naming_no_request_is_closed_by_the_approval_that_names_it(self) -> None:
        """The second binding has to work, not only refuse. A copy of the row
        taken before the question was put carries no `approval_id`, and the
        request still knows which row it was raised about."""
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        refused = runtime.approval_service.reject(request.id, actor="ayoub")
        draft = prepared.message.model_copy(update={"approval_id": None})

        assert service.gate.reject(draft, refused).status is OutreachStatus.REJECTED

    def test_a_pending_request_cannot_close_a_message(self) -> None:
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)

        with pytest.raises(OutreachNotApproved, match="nobody has decided"):
            service.gate.reject(prepared.message, request)

    def test_an_approved_request_is_sent_to_authorise_instead(self) -> None:
        runtime = create_runtime()
        service = _service(RecordingChannel(), runtime.approval_service)
        _, _, prepared = _prepared(service)
        request = service.request_approval(prepared)
        approved = runtime.approval_service.approve(request.id, actor="ayoub")

        with pytest.raises(OutreachNotApproved, match="record that with authorise"):
            service.gate.reject(prepared.message, approved)


class TestDurableRun:
    def test_a_run_with_a_repository_survives_the_process(self) -> None:
        """Without persistence the funnel resets and the cooldown forgets who
        has been contacted — which is a no-spam guarantee, not a nicety."""
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
