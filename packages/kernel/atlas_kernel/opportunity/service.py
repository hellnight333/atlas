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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .detectors.base import DetectorRegistry, DiscoveryResult
from .gate import OutreachGate, OutreachOutcome
from .metrics import FunnelReport, build_report
from .models import (
    Business,
    Finding,
    NicheProfile,
    Opportunity,
    OpportunityStage,
    OutreachMessage,
    PipelineEvent,
    PipelineEventKind,
    Proposal,
)
from .outreach import OutreachRefused, OutreachService
from .proposals import EvidenceProposalGenerator, ProposalGenerator
from .qualification import qualify, rank
from .repository import OpportunityRepository


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
    events: list[PipelineEvent] = field(default_factory=list)

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
        )
        return PreparedOutreach(
            business=business,
            opportunity=opportunity,
            proposal=proposal,
            message=message,
            outcome=outcome,
        )

    def request_approval(self, prepared: PreparedOutreach, *, requested_by: str = "atlas"):
        request = self.gate.request(prepared.outcome, requested_by=requested_by)
        self._record(
            prepared.business.id,
            PipelineEventKind.APPROVAL_REQUESTED,
            {"approval_id": request.id},
            opportunity_id=prepared.opportunity.id,
        )
        return request

    # -- sending ----------------------------------------------------------

    def send(
        self,
        prepared: PreparedOutreach,
        approval,
        profile: NicheProfile,
        *,
        now: datetime | None = None,
    ) -> OutreachMessage:
        """Authorise against the approval, then send. Refusals are recorded."""
        authorised = self.gate.authorise(prepared.message, approval, prepared.proposal)
        self._record(
            prepared.business.id,
            PipelineEventKind.APPROVED,
            {"approval_id": approval.id},
            opportunity_id=prepared.opportunity.id,
        )

        try:
            sent = self.outreach.send(authorised, prepared.proposal, profile, now=now)
        except OutreachRefused as refusal:
            self._record(
                prepared.business.id,
                PipelineEventKind.SUPPRESSED,
                {"reason": str(refusal)},
                opportunity_id=prepared.opportunity.id,
            )
            raise

        kind = (
            PipelineEventKind.SENT if sent.status.value == "sent" else PipelineEventKind.SEND_FAILED
        )
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
    ) -> PipelineEvent:
        """Append to the timeline.

        The business is required and the opportunity is optional, which is the
        right way round: a company is discovered before it has an opportunity,
        and everything that ever happens to it — proposals now, conversations,
        websites and support history later — belongs on one timeline keyed by
        the permanent record rather than scattered across whichever pipeline
        happened to be running.
        """
        event = PipelineEvent(
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
