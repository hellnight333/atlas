"""The one place a person is asked before Atlas contacts a stranger.

Same shape as the Media Factory's publish gate, and deliberately so — it reuses
``atlas_kernel.approval`` rather than growing a second approval system beside it.

**The approval is on the outcome:** this business, these words, this channel. The
approver is not asked to authorise detector runs, scoring, or proposal
generation. Those are Atlas's problem, and asking would be asking someone to
audit an internal plan they have no way to evaluate.

**The approval binds to a fingerprint.** What is recorded is not "someone
approved this message" but "someone approved *these exact words resting on these
exact facts*". Re-run a detector, edit a paragraph, change the offer, and the
fingerprint moves — at which point the send is refused rather than quietly
delivering something no human read. That is the difference between consent to a
particular thing and a standing permission to contact someone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..approval.models import ApprovalContext, ApprovalRequest, ApprovalScope, ApprovalState
from ..approval.service import ApprovalService
from .models import (
    Finding,
    OutreachMessage,
    OutreachStatus,
    Proposal,
    Prospect,
)

#: Stored on the approval so the check at send time compares like with like.
PROPOSAL_FINGERPRINT = "proposal_fingerprint"

#: What the policy engine sees. Named so a policy can require a second approver
#: for outreach specifically, without this file knowing such a policy exists.
OUTREACH_ACTION = "opportunity.outreach.send"


class OutreachNotApproved(RuntimeError):
    """The message was not cleared to send."""


@dataclass
class OutreachOutcome:
    """Exactly what a person is being asked to approve.

    Carries the findings as well as the message. An approver who cannot see what
    the claims rest on is being asked to trust the generator, and the entire
    point of the evidence invariant is that they should not have to.
    """

    prospect: Prospect
    proposal: Proposal
    findings: list[Finding]
    channel: str
    recipient: str

    @property
    def fingerprint(self) -> str:
        return self.proposal.fingerprint

    def summary(self) -> dict[str, Any]:
        return {
            "prospect": self.prospect.name,
            "recipient": self.recipient,
            "channel": self.channel,
            "subject": self.proposal.subject,
            "claims": len(self.proposal.claims),
            "evidence": [
                {
                    "statement": finding.statement,
                    "observed": [item.summary for item in finding.evidence],
                }
                for finding in self.findings
            ],
        }


class OutreachGate:
    """Requests approval, and converts an approval into a sendable message."""

    def __init__(self, approvals: ApprovalService) -> None:
        self._approvals = approvals

    def request(self, outcome: OutreachOutcome, *, requested_by: str = "atlas") -> ApprovalRequest:
        """Ask a human. Nothing is sent by this call.

        The evidence goes in the payload rather than only the summary line: an
        approver who cannot see what the claims rest on is being asked to trust
        the generator, and the evidence invariant exists so they do not have to.
        """
        context = ApprovalContext(
            action=OUTREACH_ACTION,
            scopes=[ApprovalScope.EXTERNAL_API, ApprovalScope.NETWORK],
            requested_by=requested_by,
            payload=outcome.summary(),
        )
        return self._approvals.create_request(
            title=f"Contact {outcome.prospect.name}",
            context=context,
            metadata={
                PROPOSAL_FINGERPRINT: outcome.fingerprint,
                "prospect_id": outcome.prospect.id,
                "proposal_id": outcome.proposal.id,
                "recipient": outcome.recipient,
                "channel": outcome.channel,
            },
        )

    def authorise(
        self,
        message: OutreachMessage,
        approval: ApprovalRequest,
        proposal: Proposal,
    ) -> OutreachMessage:
        """Turn an approved request into a message that may be sent.

        Re-derives the fingerprint from the proposal as it stands *now* and
        compares it against the one recorded when approval was requested. A
        mismatch means the thing approved is not the thing that would be sent,
        and the only safe answer is no.
        """
        if approval.state is not ApprovalState.APPROVED:
            raise OutreachNotApproved(
                f"approval {approval.id} is {approval.state.value}; nothing sends without a yes"
            )

        recorded = approval.metadata.get(PROPOSAL_FINGERPRINT)
        if not recorded:
            raise OutreachNotApproved(
                f"approval {approval.id} records no proposal fingerprint, so it cannot "
                "be shown to describe this message"
            )

        current = proposal.fingerprint
        if recorded != current:
            raise OutreachNotApproved(
                f"the proposal changed after approval (approved {recorded}, now {current}); "
                "re-request approval for the new version"
            )

        return message.model_copy(
            update={
                "status": OutreachStatus.APPROVED,
                "approval_id": approval.id,
                "approved_fingerprint": current,
            }
        )

    def reject(self, message: OutreachMessage, approval: ApprovalRequest) -> OutreachMessage:
        return message.model_copy(
            update={
                "status": OutreachStatus.REJECTED,
                "approval_id": approval.id,
                "detail": "rejected by approver",
            }
        )
