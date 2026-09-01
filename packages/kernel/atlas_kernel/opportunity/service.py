"""The pipeline, start to finish.

Discovery → inspection → qualification → proposal → approval → send, with an
event recorded at every transition so the funnel in ``metrics.py`` is derived
from what happened rather than from what the current state implies.

The service holds the sequence and nothing else. Scoring lives in
``qualification``, prose in ``proposals``, the human decision in ``gate``, and
the guards in ``outreach``. Anything that starts to look like business logic in
here belongs in one of those.

Note what this deliberately does **not** do: there is no ``run_everything``
method that discovers, qualifies, writes and sends. The gap between
``prepare`` and ``send`` is where a person goes, and closing it with a
convenience method would make the safe path the longer one.

**The message record follows the decision, in both directions.** Asking writes
``AWAITING_APPROVAL`` and the request id; every way the question is then
answered writes the outcome back — ``send`` on its three exits, and
``record_decision`` for the answers that arrive through the approvals API long
after this service has forgotten the run. None of it *takes* a decision: the
approval's own state says what happened, and this only stops the message record
from going on claiming an open question after somebody closed it. A queue of
questions nobody can clear is how the same stranger gets asked about twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .detectors.base import DetectorRegistry, DiscoveryResult
from .gate import FORECLOSED, OutreachGate, OutreachNotApproved, OutreachOutcome
from .metrics import FunnelReport, build_report
from .models import (
    Business,
    BusinessEvent,
    Finding,
    NicheProfile,
    Opportunity,
    OpportunityStage,
    OutreachMessage,
    OutreachStatus,
    PipelineEventKind,
    Proposal,
)
from .outreach import OutreachRefused, OutreachService
from .proposals import EvidenceProposalGenerator, ProposalGenerator
from .qualification import qualify, rank
from .repository import OpportunityRepository


#: Statuses that leave the question open. A row in one of these records that
#: nobody has decided about it, and it is the only kind ``record_decision`` may
#: close: writing a refusal onto a message that was already sent would rewrite
#: what happened, and a decision a person took is not Atlas's to reinterpret.
#:
#: The same two ``outreach.unreviewed`` calls undecided, and for the same
#: reason. Spelled here rather than imported because that module deliberately
#: has no dependency in either direction — it takes records as arguments — and
#: importing it to read two strings would create one.
OPEN_STATUSES: frozenset[OutreachStatus] = frozenset(
    {OutreachStatus.DRAFT, OutreachStatus.AWAITING_APPROVAL}
)

#: Columns whose presence is itself a decision, whatever the status column says.
#:
#: Checked alongside the status rather than instead of it, because a status is
#: one edit away from lying and the direction that matters here is the one that
#: destroys history: an approved or sent message must never be closed as a
#: refusal. ``outreach.unreviewed.DECISION_COLUMNS`` reads the same three.
DECIDED_COLUMNS: tuple[str, ...] = (
    "approved_fingerprint",
    "sent_at",
    "authorized_automated_at",
)


def _undecided(message: OutreachMessage) -> bool:
    """Whether the row still records an open question and nothing more.

    The same four signals ``outreach.unreviewed.undecided`` reads, and the same
    reason for reading four rather than one: a status is a single edit away from
    lying, and the direction that destroys history is the one where a message
    somebody acted on is treated as one nobody has touched.

    Read in both directions here. ``record_decision`` may only close a row that
    is still open; ``request_approval`` may only ask about one.
    """
    return message.status in OPEN_STATUSES and not any(
        getattr(message, column) for column in DECIDED_COLUMNS
    )


@dataclass
class PreparedOutreach:
    """Everything needed for a human to decide, and nothing sent yet."""

    business: Business
    opportunity: Opportunity
    proposal: Proposal
    message: OutreachMessage
    outcome: OutreachOutcome


@dataclass
class OpportunityService:
    detectors: DetectorRegistry
    gate: OutreachGate
    outreach: OutreachService
    generator: ProposalGenerator = field(default_factory=EvidenceProposalGenerator)
    #: Optional. Without it the service still runs -- useful in tests and for a
    #: dry scan -- but nothing survives the process, which means the funnel
    #: resets and the cooldown forgets who has already been contacted. Supply
    #: one for any run that actually sends.
    repository: OpportunityRepository | None = None
    #: In-memory event log, mirrored to the repository when there is one.
    events: list[BusinessEvent] = field(default_factory=list)

    # -- discovery and qualification -------------------------------------

    def discover(self, profile: NicheProfile, limit: int = 50) -> DiscoveryResult:
        """Ask every registered source and resolve the answers.

        Businesses are resolved against what is already stored before anything
        is recorded, so a company found last week and found again today is the
        same record with a second source attached — not a second row that
        escapes the cooldown protecting the first.
        """
        result = self.detectors.discover(profile, limit)
        resolved: list[Business] = []
        for business in result.businesses:
            if self.repository is not None:
                business, is_new = self.repository.resolve_business(business)
            else:
                is_new = True
            resolved.append(business)
            if is_new:
                self._record(business.id, PipelineEventKind.DISCOVERED)
        return DiscoveryResult(
            businesses=resolved,
            duplicates_merged=result.duplicates_merged,
            possible_duplicates=result.possible_duplicates,
            source_failures=result.source_failures,
        )

    def inspect(self, business: Business, profile: NicheProfile) -> list[Finding]:
        return self.detectors.inspect(business, profile)

    def qualify(
        self, business: Business, findings: list[Finding], profile: NicheProfile
    ) -> Opportunity:
        opportunity = qualify(business, findings, profile)
        if self.repository is not None:
            self.repository.save_opportunity(opportunity)
        kind = (
            PipelineEventKind.QUALIFIED
            if opportunity.stage is OpportunityStage.QUALIFIED
            else PipelineEventKind.DISQUALIFIED
        )
        self._record(
            business.id,
            kind,
            {"score": opportunity.score, "findings": len(opportunity.findings)},
            opportunity_id=opportunity.id,
        )
        return opportunity

    def scan(self, profile: NicheProfile, limit: int = 50) -> list[Opportunity]:
        """Discover and qualify in one pass. Contacts nobody."""
        opportunities: list[Opportunity] = []
        for business in self.discover(profile, limit).businesses:
            findings = self.inspect(business, profile)
            opportunities.append(self.qualify(business, findings, profile))
        return rank(opportunities)

    # -- proposal and approval -------------------------------------------

    def prepare(
        self, business: Business, opportunity: Opportunity, profile: NicheProfile
    ) -> PreparedOutreach:
        """Write the proposal and ask for approval. Sends nothing."""
        if opportunity.stage is not OpportunityStage.QUALIFIED:
            raise ValueError(
                f"{business.name} did not qualify (score {opportunity.score} < "
                f"{profile.qualify_threshold}); Atlas does not write to businesses "
                "it has nothing substantiated to say to"
            )
        if not business.email:
            raise ValueError(f"{business.name} has no email address to contact")

        proposal = self.generator.generate(business, opportunity, profile)
        if self.repository is not None:
            self.repository.save_proposal(proposal)
        self._record(
            business.id,
            PipelineEventKind.PROPOSAL_GENERATED,
            {"generator": proposal.generator, "claims": len(proposal.claims)},
            opportunity_id=opportunity.id,
        )

        message = OutreachMessage(
            proposal_id=proposal.id,
            business_id=business.id,
            channel=self.outreach.channel_name,
            recipient=business.email,
            subject=proposal.subject,
            body=proposal.body,
        )
        if self.repository is not None:
            self.repository.save_message(message)
        outcome = OutreachOutcome(
            business=business,
            proposal=proposal,
            findings=opportunity.findings,
            channel=message.channel,
            recipient=message.recipient,
            message_id=message.id,
        )
        return PreparedOutreach(
            business=business,
            opportunity=opportunity,
            proposal=proposal,
            message=message,
            outcome=outcome,
        )

    def request_approval(self, prepared: PreparedOutreach, *, requested_by: str = "atlas"):
        """Ask a person, and record on the message that they were asked.

        The status move is not bookkeeping. ``AWAITING_APPROVAL`` is the only
        thing in the message record that says the question was put about *these*
        words, and the review queue in ``outreach.unreviewed`` reads exactly
        that: a row still at ``DRAFT`` is reported as one nobody has been asked
        about. Creating the request and leaving the row alone shows a pending
        question as an untouched draft, and the obvious response to that listing
        is to ask somebody the same thing a second time.

        ``approval_id`` names the question and never an answer. Without it there
        is no way back from a message to the request that settles it, which is
        precisely what ``record_decision`` needs in order to write the answer
        where the question was asked; the timeline entry cannot supply it,
        because it names an approval and an opportunity and a business holding
        two drafts has two candidate rows. Nothing infers a decision from the
        column — ``send`` re-derives the fingerprint, ``record_decision`` reads
        the approval's own state, and ``unreviewed.DECISION_COLUMNS`` leaves it
        out on purpose so a pending request is not mistaken for an act.

        The answer arrives by its own path. ``ApprovalService`` decides against
        its own records and knows nothing about outreach messages, so a request
        that is refused, cancelled or left to expire has to come back through
        ``record_decision`` or this row goes on claiming an open question after
        that stopped being true.

        Asked about **once**, and the two guards below are what hold that. A
        ``PreparedOutreach`` is reusable and mutable, so a second call is one
        stray loop away, and the write is unconditional: it would move a sent,
        suppressed, failed or refused row back to ``AWAITING_APPROVAL``, and
        ``save_message`` writes every mutable column from the object it is
        handed — so ``sent_at``, ``approved_fingerprint`` and
        ``authorized_automated_at`` are not merely left behind by the move, they
        are overwritten with whatever the caller happens to be holding. Asking
        again about a row that already names a *pending* request is the other
        half: it abandons that request, still open and now unreachable from any
        message, and puts the same words to a second person. Neither is repaired
        by re-asking, so neither is allowed. New words are a new question, and
        ``prepare`` is what makes one.

        **Both guards read the stored row, and the write is built from it.** The
        caller's copy is the wrong thing to ask, because it is a snapshot of the
        row as it stood when whoever holds it last looked — and ``gate``'s
        ``_must_describe`` already names that case out loud: a caller holding a
        copy taken before the question was put. Such a copy still says ``DRAFT``
        and still names no approval, so both guards pass on it however far the
        row itself has moved, and the write then puts a settled decision back to
        ``AWAITING_APPROVAL`` and clears the columns that recorded it. This is
        not a thought experiment: ``infra/approve_send.py`` is a second writer of
        exactly these rows, an operator runs it out of this process, and it moves
        a draft to ``APPROVED_FOR_MANUAL_SEND`` with the fingerprint of the words
        they read.

        Reloading settles what the record says; it does not make the check and
        the write one act. The row can still move between them, because
        ``save_message`` is an unconditional upsert — closing that last gap needs
        a conditional update in ``OpportunityRepository``, which is a change to a
        file this one does not own. What reloading removes is the half that needs
        no race at all.

        The request and the row's record of it have to arrive together. Two
        stores, two writes, and the second can fail: ``gate.withdraw`` takes the
        question back rather than leaving it live with nothing pointing at it.
        """
        stored = self._as_persisted(prepared.message)
        if not _undecided(stored):
            raise OutreachNotApproved(
                f"message {stored.id} is {stored.status.value} "
                "and already records what was decided about it; asking again would "
                "move it back to awaiting a question somebody already answered. "
                "Prepare the words afresh — a new question is a new message"
            )
        if stored.approval_id:
            raise OutreachNotApproved(
                f"message {stored.id} was already raised under approval "
                f"{stored.approval_id}; a second request would leave that "
                "one open with nothing pointing at it and put the same words to two "
                "people. Settle it first — record_decision closes it"
            )

        request = self.gate.request(prepared.outcome, requested_by=requested_by)
        asked = stored.model_copy(
            update={
                "status": OutreachStatus.AWAITING_APPROVAL,
                "approval_id": request.id,
            }
        )
        if self.repository is not None:
            try:
                self.repository.save_message(asked)
            except Exception:
                # The question is live and the row does not say so. Withdrawing
                # is the only thing that stops the retry from being a second
                # person asked about the same words. If the withdrawal fails too
                # it surfaces with this failure chained behind it — an
                # unreachable pending request deserves an error nobody can miss,
                # not a quieter one.
                self.gate.withdraw(request)
                raise
        prepared.message = asked
        self._record(
            prepared.business.id,
            PipelineEventKind.APPROVAL_REQUESTED,
            {"approval_id": request.id, "message_id": asked.id},
            opportunity_id=prepared.opportunity.id,
        )
        return request

    def record_decision(self, approval, *, actor: str = "operator") -> OutreachMessage | None:
        """Write a terminal approval outcome back onto the persisted message.

        The counterpart to ``request_approval``, and what makes that method's
        claim on the row safe to leave there. Every way an approval ends happens
        somewhere else and later — a refusal through the approvals API, a
        cancellation, ``expire_due`` sweeping a request nobody answered — and
        each one moves ``ApprovalService``'s own record and nothing more. The
        message goes on saying ``AWAITING_APPROVAL`` after a person answered,
        the review queue lists a settled question as one still waiting, and
        somebody is asked to decide again about words already refused.

        It takes the approval and *finds* the message rather than taking both,
        because that is the shape the caller is in: the answer arrives with an
        approval id and no ``PreparedOutreach`` in hand. The link is the
        ``approval_id`` written when the question was put.

        Returns the message it closed, or ``None`` when there is nothing to
        close — no repository, no row raised under this approval, or a row that
        already records an outcome. ``None`` is an ordinary answer and not a
        failure: most approvals in Atlas have no outreach message behind them.

        ``APPROVED`` is refused rather than written, and that is not an
        omission. Marking a message approved is ``gate.authorise``'s act,
        because only ``authorise`` re-derives the fingerprint and refuses words
        that moved since a person read them. A method whose job is keeping a row
        honest must not become a second door onto sending.

        **The check and the write are not one act, and cannot be made one from
        here.** ``_message_asked_about`` reads the row, this writes it, and
        ``save_message`` is an unconditional upsert — so a send or a manual
        approval that another writer records in between is overwritten by the
        refusal rather than protected by the check that just passed.
        ``infra/approve_send.py`` is that other writer, and an operator runs it
        whenever they like. The fix is a conditional update in
        ``OpportunityRepository`` — write the refusal only where the row is still
        open and still carries none of ``DECIDED_COLUMNS`` — and it belongs in
        that file. Reading the row a second time just before the write would move
        the window rather than close it, and a guard that looks sound and is not
        is worse than a gap somebody can see.

        **Nothing in production calls this yet, and nothing can.** The refusal
        endpoints — ``POST /approvals/{id}/reject`` and ``/cancel`` in
        ``api.py``, ``/approvals/{id}/decide`` in ``customer/api.py`` — settle
        the request and stop there. That is not a hole under this method, it is
        the same hole under ``request_approval``: no production module builds an
        ``OpportunityService``, so no outreach approval is ever created, no row
        ever reaches ``AWAITING_APPROVAL``, and there is no stranded row for a
        refusal to leave behind. (The customer endpoint could not decide one in
        any case — it demands a ``tenant_id`` in the approval's metadata and
        ``gate.request`` writes none.)

        The two halves have to be wired in the same change, and neither can be
        wired from this file. Whoever gives the pipeline a production entry point
        owns both: the surface that calls ``request_approval`` to put the
        question, and the approval transition — an ``ApprovalRejected`` /
        ``ApprovalCancelled`` / ``ApprovalExpired`` subscriber is the seam,
        though the event bus has no production subscriber today — that calls this
        to write the answer back. Wiring only this half would put the opportunity
        factory behind the kernel's approval service to close rows nothing
        produces, which inverts the dependency and buys nothing.
        """
        if approval.state not in FORECLOSED:
            raise OutreachNotApproved(
                f"approval {approval.id} is {approval.state.value} and has not "
                "foreclosed the send; there is no decision here to write onto a "
                "message, and inventing one would answer for the approver"
            )

        message = self._message_asked_about(approval)
        if message is None:
            return None

        marked = self.gate.reject(message, approval)
        if self.repository is not None:
            self.repository.save_message(marked)
        self._record(
            marked.business_id,
            PipelineEventKind.REJECTED,
            {
                "approval_id": approval.id,
                "approval_state": approval.state.value,
                "message_id": marked.id,
                "detail": marked.detail,
            },
            opportunity_id=self._opportunity_behind(marked),
            actor=actor,
        )
        return marked

    def _message_asked_about(self, approval) -> OutreachMessage | None:
        """The persisted message raised under this approval, if it is still open.

        Found through ``approval_id`` alone. The timeline entry cannot serve:
        it names an approval and an opportunity, never a message, and a business
        holding a WhatsApp draft beside an email draft is exactly the case that
        decides it — attributing the answer to rows would close both when at
        most one was ever asked about.

        Rows that already record an outcome are passed over rather than closed.
        Four independent signals, the same four ``outreach.unreviewed`` reads:
        the status, and the three columns whose presence is an act somebody
        took. A message sent before its request was cancelled stays sent — a
        later cancellation cannot un-send it, and rewriting the row to say
        otherwise would be Atlas reinterpreting a decision a person made.
        """
        if self.repository is None:
            return None
        business_id = str(approval.metadata.get("business_id") or "")
        if not business_id:
            return None
        for message in self.repository.messages_for(business_id):
            if message.approval_id == approval.id and _undecided(message):
                return message
        return None

    def _as_persisted(self, message: OutreachMessage) -> OutreachMessage:
        """The stored row this message is a copy of, or the copy when there is none.

        A guard that reads its argument guards the caller's memory rather than
        the record, and those two disagree the moment anything else writes the
        row — another process, an operator running ``infra/approve_send.py``, or
        this service itself on a run whose ``PreparedOutreach`` somebody kept.

        Found by id through ``messages_for``, the same way ``_message_asked_about``
        finds its row, and for the same reason: the repository has no read of a
        single message, and adding one is a change to a file this one does not own.

        Falls back to the argument, which is not a weakened check. With no
        repository nothing is stored at all, and a message that was never saved
        has no row that could contradict it — in both cases the record says
        nothing about this message, and the copy is the only account there is.
        """
        if self.repository is None:
            return message
        for row in self.repository.messages_for(message.business_id):
            if row.id == message.id:
                return row
        return message

    def _opportunity_behind(self, message: OutreachMessage) -> str | None:
        """Which opportunity a persisted message belongs to, when that is knowable.

        Read through the proposal rather than carried on the message, because
        the message does not have it and inventing a column for one event kind
        would be the wrong place to keep it. ``None`` is a real answer: a
        mission-originated message has no proposal at all, and the timeline
        entry is still worth writing against the business.
        """
        if self.repository is None or not message.proposal_id:
            return None
        proposal = self.repository.get_proposal(message.proposal_id)
        return proposal.opportunity_id if proposal else None

    # -- sending ----------------------------------------------------------

    def send(
        self,
        prepared: PreparedOutreach,
        approval,
        profile: NicheProfile,
        *,
        now: datetime | None = None,
    ) -> OutreachMessage:
        """Authorise against the approval, then send. Refusals are recorded.

        Every exit writes the outcome onto the message, including the refusals.
        The question was answered the moment ``authorise`` returned, and a row
        left at ``AWAITING_APPROVAL`` after a guard closed the send goes on
        telling the review queue that a person still owes a decision they have
        already given.
        """
        authorised = self.gate.authorise(prepared.message, approval, prepared.proposal)
        prepared.message = authorised
        self._record(
            prepared.business.id,
            PipelineEventKind.APPROVED,
            {"approval_id": approval.id, "message_id": authorised.id},
            opportunity_id=prepared.opportunity.id,
        )

        try:
            sent = self.outreach.send(authorised, prepared.proposal, profile, now=now)
        except OutreachRefused as refusal:
            # A person said yes and a guard said no anyway — suppression added
            # after the approval, or a cooldown this business is still inside.
            # `SUPPRESSED` is what the timeline already records for it, and the
            # message now agrees rather than claiming an unanswered question.
            #
            # Written from `authorised`, so the row keeps what the approval
            # established: which request settled it, the fingerprint a person
            # read, and when automated delivery was authorised. Losing those
            # would make the refusal look like a row nobody ever decided.
            refused = authorised.model_copy(
                update={"status": OutreachStatus.SUPPRESSED, "detail": str(refusal)}
            )
            prepared.message = refused
            if self.repository is not None:
                self.repository.save_message(refused)
            self._record(
                prepared.business.id,
                PipelineEventKind.SUPPRESSED,
                {"reason": str(refusal), "message_id": refused.id},
                opportunity_id=prepared.opportunity.id,
            )
            raise

        kind = (
            PipelineEventKind.SENT if sent.status.value == "sent" else PipelineEventKind.SEND_FAILED
        )
        prepared.message = sent
        if self.repository is not None:
            self.repository.save_message(sent)
        self._record(
            prepared.business.id,
            kind,
            {"detail": sent.detail, "message_id": sent.provider_message_id},
            opportunity_id=prepared.opportunity.id,
        )
        return sent

    # -- outcomes ---------------------------------------------------------

    def record_reply(
        self, opportunity_id: str, business_id: str, *, actor: str = "operator"
    ) -> None:
        self._record(
            business_id,
            PipelineEventKind.REPLIED,
            {},
            opportunity_id=opportunity_id,
            actor=actor,
        )

    def record_meeting(
        self, opportunity_id: str, business_id: str, *, actor: str = "operator"
    ) -> None:
        self._record(
            business_id,
            PipelineEventKind.MEETING_BOOKED,
            {},
            opportunity_id=opportunity_id,
            actor=actor,
        )

    def record_won(
        self,
        opportunity_id: str,
        business_id: str,
        *,
        value: float | None = None,
        actor: str = "operator",
    ) -> None:
        self._record(
            business_id,
            PipelineEventKind.WON,
            {"value": value},
            opportunity_id=opportunity_id,
            actor=actor,
        )

    def record_lost(
        self, opportunity_id: str, business_id: str, *, reason: str = "", actor: str = "operator"
    ) -> None:
        self._record(
            business_id,
            PipelineEventKind.LOST,
            {"reason": reason},
            opportunity_id=opportunity_id,
            actor=actor,
        )

    # -- measurement ------------------------------------------------------

    def report(self) -> FunnelReport:
        return build_report(self.events)

    # -- internals --------------------------------------------------------

    def _record(
        self,
        business_id: str,
        kind: PipelineEventKind,
        detail: dict | None = None,
        *,
        opportunity_id: str | None = None,
        actor: str = "system",
    ) -> BusinessEvent:
        """Append to the timeline.

        The business is required and the opportunity is optional, which is the
        right way round: a company is discovered before it has an opportunity,
        and everything that ever happens to it — proposals now, conversations,
        websites and support history later — belongs on one timeline keyed by
        the permanent record rather than scattered across whichever pipeline
        happened to be running.
        """
        event = BusinessEvent(
            opportunity_id=opportunity_id,
            business_id=business_id,
            kind=kind,
            detail=detail or {},
            actor=actor,
            at=datetime.now(UTC),
        )
        self.events.append(event)
        if self.repository is not None:
            self.repository.record_event(event)
        return event
