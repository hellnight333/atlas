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

**The message record follows the decision, in both directions.** Asking claims
the row and writes the request id onto it; every way the question is then
answered writes the outcome back — ``send`` on its exits, and
``record_decision`` for answers that arrive through the approvals API long after
this service has forgotten the run. None of it *takes* a decision: the approval's
own state says what happened, and this only stops the message record from going
on claiming an open question after somebody closed it. A queue of questions
nobody can clear is how the same stranger gets asked about twice.

**Every one of those writes reads a status and then writes against it**, which is
a check-then-write and races unless the check travels with the write. It does:
``save_message(..., expecting=...)`` carries the status this service read into
the statement that updates, so a save whose premise expired lands nowhere and
raises ``StaleMessage`` instead of overwriting whatever replaced it. The one
deliberate exception is recording a send that already went out, and ``send``
says why.
"""

from __future__ import annotations

import logging
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
from .repository import OpportunityRepository, StaleMessage

log = logging.getLogger(__name__)

#: Statuses that leave the question open, and the only ones a decision may be
#: written onto. Writing a refusal over a message that was already sent would
#: rewrite what happened, and a decision a person took is not Atlas's to
#: reinterpret.
#:
#: The same two ``outreach.unreviewed`` calls undecided, and for the same reason.
#: Spelled here rather than imported because that module deliberately has no
#: dependency in either direction — it takes records as arguments — and importing
#: it to read two strings would create one.
OPEN_STATUSES: frozenset[OutreachStatus] = frozenset(
    {OutreachStatus.DRAFT, OutreachStatus.AWAITING_APPROVAL}
)

#: Columns whose presence is itself a decision, whatever the status column says.
#:
#: Read alongside the status rather than instead of it, because a status is one
#: edit away from lying and the direction that matters here destroys history: an
#: approved or sent message must never be closed as a refusal.
#: ``outreach.unreviewed.DECISION_COLUMNS`` reads the same three.
DECIDED_COLUMNS: tuple[str, ...] = (
    "approved_fingerprint",
    "sent_at",
    "authorized_automated_at",
)


def _undecided(message: OutreachMessage) -> bool:
    """Whether the row still records an open question and nothing more.

    The same four signals ``outreach.unreviewed.undecided`` reads, for the same
    reason: a status is a single edit away from lying, and the direction that
    destroys history is the one where a message somebody acted on is treated as
    one nobody has touched.

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

    def __post_init__(self) -> None:
        """Start watching for the answers to the questions this service asks.

        The subscription is made here rather than left to whoever builds the
        service, because forgetting it is invisible: the pipeline would go on
        asking people about strangers and quietly stop recording what they said,
        and the only symptom is a review queue that never empties. Constructing
        the service is the wiring.

        ``watching`` is ``False`` against an approval service with no event bus —
        every hand-built double in the tests — and that is the honest value, not
        a failure. Nothing else in this class depends on it; it exists so a caller
        can tell "watching" from "silently not watching".
        """
        self.watching = self.gate.on_foreclosed(self._foreclosed)

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
        """Claim the message, then ask a person about it.

        The status move is not bookkeeping. ``AWAITING_APPROVAL`` is the only
        thing in the message record saying the question was put about *these*
        words, and the review queue in ``outreach.unreviewed`` reads exactly
        that: a row still at ``DRAFT`` is reported as one nobody has been asked
        about. Creating the request and leaving the row alone shows a pending
        question as an untouched draft, and the obvious response to that listing
        is to ask somebody the same thing a second time.

        **The claim comes first, and it is what makes the question single.** The
        move out of ``DRAFT`` is a guarded write, so of two workers holding the
        same draft exactly one takes the transition and the other is refused with
        the status it actually found. Asking first and claiming afterwards would
        let both pass their checks, create two pending requests about one set of
        words, and leave whichever lost the write orphaned — a live question with
        nothing pointing at it, which no later pass can find or settle. Claiming
        first means the loser never reaches ``gate.request`` at all.

        ``approval_id`` is written in a second guarded write, after the request
        exists, because the id does not exist before it. That leaves one window,
        and it is the safe one: a crash between the two leaves the row claimed
        and unlinked, where it blocks a second question rather than inviting one.
        A failure of the write itself is repaired rather than left — the request
        is withdrawn, because a question nobody can reach is worse than no
        question.

        Both guards read the **stored** row, and the write is built from it. The
        caller's copy is a snapshot from whenever it last looked, and
        ``infra/approve_send.py`` is a second writer of exactly these rows that an
        operator runs out of this process — a copy taken before that ran still
        says ``DRAFT`` and would carry a settled decision back to
        ``AWAITING_APPROVAL``.

        Refuses a message that already records a decision, and one that already
        names a request. Neither is repaired by asking again: the first would
        move a sent, refused or suppressed row back to awaiting a question
        somebody already answered, and the second abandons a live request and
        puts the same words to a second person. New words are a new question, and
        ``prepare`` is what makes one.
        """
        stored = self._as_persisted(prepared.message)
        if not _undecided(stored):
            raise OutreachNotApproved(
                f"message {stored.id} is {stored.status.value} and already records "
                "what was decided about it; asking again would move it back to "
                "awaiting a question somebody already answered. Prepare the words "
                "afresh — a new question is a new message"
            )
        if stored.approval_id:
            raise OutreachNotApproved(
                f"message {stored.id} was already raised under approval "
                f"{stored.approval_id}; a second request would leave that one open "
                "with nothing pointing at it and put the same words to two people. "
                "Settle it first — record_decision closes it"
            )

        claimed = self._claim(stored)
        try:
            request = self.gate.request(prepared.outcome, requested_by=requested_by)
        except Exception:
            # The claim was taken for a question that never got asked. Releasing
            # it is what stops the row sitting at AWAITING_APPROVAL for ever with
            # no request behind it, refusing every future ask.
            self._release(claimed, stored.status)
            raise

        asked = claimed.model_copy(update={"approval_id": request.id})
        if self.repository is not None:
            try:
                self.repository.save_message(asked, expecting=OutreachStatus.AWAITING_APPROVAL)
            except Exception:
                # The question is live and the row cannot say so. Withdrawing is
                # the only thing that stops a retry from being a second person
                # asked about the same words. A withdrawal that fails too
                # surfaces with this failure chained behind it — an unreachable
                # pending request deserves an error nobody can miss.
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

    def record_decision(
        self, approval, *, actor: str = "operator"
    ) -> OutreachMessage | None:
        """Write a terminal approval outcome back onto the persisted message.

        The counterpart to ``request_approval``, and what makes that method's
        claim on the row safe to leave there. Every way an approval ends happens
        somewhere else and later — a refusal through the customer endpoint or the
        kernel API, a cancellation, ``expire_due`` sweeping a request nobody
        answered — and each moves ``ApprovalService``'s own record and nothing
        more. Without this the message goes on saying ``AWAITING_APPROVAL`` after
        a person answered, and somebody is asked to decide again about words
        already refused.

        It takes the approval and *finds* the message rather than taking both,
        because that is the shape the caller is in: the answer arrives with an
        approval id and no ``PreparedOutreach`` in hand. ``gate.on_foreclosed``
        is what delivers those answers here, so this is not a method a surface has
        to remember to call.

        Returns the message it closed, or ``None`` when there is nothing to close
        — no repository, no row raised under this approval, a row that already
        records an outcome, or a row that acquired one between the read and the
        write. ``None`` is an ordinary answer and not a failure: most approvals in
        Atlas have no outreach message behind them.

        **The refusal is persisted only while the message is still open.** The
        write carries the status this method read, so a send or a manual approval
        landing in between refuses it rather than being replaced by it. That is
        the whole difference between recording a decision and reinterpreting one:
        a message that went out stays sent, and a later cancellation cannot
        un-send it.

        ``APPROVED`` is refused rather than written. Marking a message approved is
        ``gate.authorise``'s act, because only ``authorise`` re-derives the
        fingerprint and refuses words that moved since a person read them.
        """
        if approval.state not in FORECLOSED:
            raise OutreachNotApproved(
                f"approval {approval.id} is {approval.state.value} and has not "
                "foreclosed the send; there is no decision here to write onto a "
                "message, and inventing one would answer for the approver"
            )

        repository = self.repository
        message = self._message_asked_about(approval)
        if message is None or repository is None:
            return None

        marked = self.gate.reject(message, approval)
        try:
            # `message.status` and not a constant: the row is claimed at
            # AWAITING_APPROVAL by `request_approval`, and older rows raised
            # before that existed are still at DRAFT. The expectation is whatever
            # was actually read a moment ago.
            repository.save_message(marked, expecting=message.status)
        except StaleMessage:
            return None

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

    def _foreclosed(self, approval, actor: str) -> None:
        """What ``gate.on_foreclosed`` delivers a closed outreach approval to.

        Deliberately total. This runs inside whichever endpoint recorded the
        decision, and an exception here would turn a refusal a person has already
        made into a failed request they would retry — only to be told the
        approval is already rejected. The decision is the durable thing; the
        message record catching up is not worth losing it over.

        Swallowing it silently would be worse than the race, so it goes to the
        log. A row that misses its write-back stays at ``AWAITING_APPROVAL``,
        which ``outreach.unreviewed`` already reports as asked-and-unanswered
        pointing at the request record — visible, and recoverable by calling this
        again.
        """
        try:
            self.record_decision(approval, actor=actor or "system")
        except Exception:  # noqa: BLE001 — see the docstring; the decision outranks the record
            log.exception(
                "could not write approval %s back onto its outreach message", approval.id
            )

    def _message_asked_about(self, approval) -> OutreachMessage | None:
        """The persisted message raised under this approval, if it is still open.

        Found through ``approval_id`` alone. The timeline entry cannot serve: it
        names an approval and an opportunity, never a message, and a business
        holding a WhatsApp draft beside an email draft is exactly the case that
        decides it — attributing the answer to rows would close both when at most
        one was ever asked about.

        Rows that already record an outcome are passed over rather than closed.
        A message sent before its request was cancelled stays sent.
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

        A guard that reads its argument guards the caller's memory rather than the
        record, and the two disagree the moment anything else writes the row.

        Found by id through ``messages_for``, the same way ``_message_asked_about``
        finds its row, because the repository has no read of a single message and
        adding one is a change to a file this one does not own.

        Falls back to the argument, which is not a weakened check: with no
        repository nothing is stored at all, and a message that was never saved
        has no row that could contradict it. In both cases the copy is the only
        account there is.
        """
        if self.repository is None:
            return message
        for row in self.repository.messages_for(message.business_id):
            if row.id == message.id:
                return row
        return message

    def _claim(self, stored: OutreachMessage) -> OutreachMessage:
        """Take the row out of ``DRAFT`` so exactly one caller may ask about it.

        ``expecting=DRAFT`` and not the status that was read, deliberately.
        ``DRAFT`` is the only state in which no question has demonstrably been
        put; a row already at ``AWAITING_APPROVAL`` either names its request or is
        a claim some earlier run crashed halfway through, and asking again is the
        wrong answer to both.
        """
        claimed = stored.model_copy(update={"status": OutreachStatus.AWAITING_APPROVAL})
        if self.repository is None:
            return claimed
        try:
            self.repository.save_message(claimed, expecting=OutreachStatus.DRAFT)
        except StaleMessage as lost:
            raise OutreachNotApproved(
                f"message {stored.id} is {lost.found!r} and no longer the draft this "
                "read it as; somebody else claimed it or decided it between the read "
                "and the write, and asking now would be the second question about "
                "these words"
            ) from lost
        return claimed

    def _release(self, claimed: OutreachMessage, previous: OutreachStatus) -> None:
        """Give back a claim whose question was never asked.

        Guarded on the claim itself, so a row somebody else has since moved on is
        left where they put it. ``StaleMessage`` is therefore the ordinary
        outcome of losing that race and not an error — the claim is gone, which
        is what this was trying to achieve.
        """
        if self.repository is None:
            return
        try:
            self.repository.save_message(
                claimed.model_copy(update={"status": previous}),
                expecting=OutreachStatus.AWAITING_APPROVAL,
            )
        except StaleMessage:
            return

    def _opportunity_behind(self, message: OutreachMessage) -> str | None:
        """Which opportunity a persisted message belongs to, when that is knowable.

        Read through the proposal rather than carried on the message, because the
        message does not have it and inventing a column for one event kind would
        be the wrong place to keep it. ``None`` is a real answer: a
        mission-originated message has no proposal at all, and the timeline entry
        is still worth writing against the business.
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

        The refusal exit writes the outcome onto the message too. The question
        was answered the moment ``authorise`` returned, and a row left at
        ``AWAITING_APPROVAL`` after a guard closed the send goes on telling the
        review queue that a person still owes a decision they have already given.
        """
        open_at_entry = prepared.message.status
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
            # A person said yes and a guard said no anyway — a suppression added
            # after the approval, or a cooldown this business is still inside.
            # Written from `authorised`, so the row keeps what the approval
            # established: which request settled it, the fingerprint a person
            # read, and when automated delivery was authorised. Losing those
            # would make the refusal look like a row nobody ever decided.
            #
            # Guarded, and nothing was delivered, so losing the race is the right
            # outcome: whatever the other writer recorded is a decision about a
            # message this call never sent.
            refused = authorised.model_copy(
                update={"status": OutreachStatus.SUPPRESSED, "detail": str(refusal)}
            )
            landed = True
            if self.repository is not None:
                try:
                    self.repository.save_message(refused, expecting=open_at_entry)
                except StaleMessage:
                    landed = False
                    log.warning(
                        "message %s moved before its suppression could be recorded", refused.id
                    )
            if landed:
                # Only when the record agrees. A caller left holding a copy that
                # says `suppressed` over a row somebody else decided would carry
                # that disagreement into whatever it does next.
                prepared.message = refused
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
            # The one write here that is deliberately **not** guarded. By this
            # line the channel has either delivered or failed, and that is a fact
            # about the world; refusing to record it because another writer got
            # to the row first would leave Qevik with no record that it contacted
            # a stranger. Recording what happened outranks protecting what the
            # row said before it did.
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
