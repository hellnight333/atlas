"""The funnel. The success metric is not "emails sent".

Computed from ``PipelineEvent`` rather than from each opportunity's current
stage, and the difference is not academic: a funnel derived from current state
cannot tell you that forty businesses reached "sent" and came back to nothing,
because those forty now sit in whatever stage they ended in. Append-only events
keep the history that makes a rate meaningful.

Rates are ``None`` rather than ``0.0`` when the denominator is zero. A close
rate of "0%" from three businesses reads like failure; "not enough data yet" is
the truth, and the two should not be rendered the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import PipelineEvent, PipelineEventKind

#: The funnel, in order. Each entry maps a reported stage to the events that
#: count as reaching it.
FUNNEL: list[tuple[str, tuple[PipelineEventKind, ...]]] = [
    ("discovered", (PipelineEventKind.DISCOVERED,)),
    ("qualified", (PipelineEventKind.QUALIFIED,)),
    ("proposed", (PipelineEventKind.PROPOSAL_GENERATED,)),
    ("approved", (PipelineEventKind.APPROVED,)),
    ("sent", (PipelineEventKind.SENT,)),
    ("replied", (PipelineEventKind.REPLIED,)),
    ("meetings", (PipelineEventKind.MEETING_BOOKED,)),
    ("won", (PipelineEventKind.WON,)),
]


def _rate(numerator: int, denominator: int) -> float | None:
    """A proportion, or ``None`` when there is nothing to divide by."""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


@dataclass
class FunnelReport:
    """Counts of distinct businesses reaching each stage, and the rates between.

    Distinct businesses, not events: three follow-ups to one business is one
    business contacted, and counting it as three would flatter every rate
    downstream of it.
    """

    counts: dict[str, int] = field(default_factory=dict)
    #: Businesses looked at and deliberately rejected. Not a failure —
    #: knowing the qualification bar is doing work is the point of measuring it.
    disqualified: int = 0
    rejected: int = 0
    suppressed: int = 0
    send_failed: int = 0
    lost: int = 0

    @property
    def qualification_rate(self) -> float | None:
        return _rate(self.counts.get("qualified", 0), self.counts.get("discovered", 0))

    @property
    def approval_rate(self) -> float | None:
        """How often a human said yes to what Atlas wrote.

        The most direct measure of proposal quality available before anyone
        replies, and the one that moves first when the generator gets worse.
        """
        return _rate(self.counts.get("approved", 0), self.counts.get("proposed", 0))

    @property
    def reply_rate(self) -> float | None:
        return _rate(self.counts.get("replied", 0), self.counts.get("sent", 0))

    @property
    def meeting_rate(self) -> float | None:
        return _rate(self.counts.get("meetings", 0), self.counts.get("sent", 0))

    @property
    def close_rate(self) -> float | None:
        """Won over contacted.

        The number this whole factory rests on, and unproven until real
        outreach happens. Deliberately measured against ``sent`` rather than
        against meetings, because a close rate computed on the few who already
        agreed to talk flatters itself.
        """
        return _rate(self.counts.get("won", 0), self.counts.get("sent", 0))

    def as_dict(self) -> dict[str, object]:
        return {
            "counts": dict(self.counts),
            "disqualified": self.disqualified,
            "rejected": self.rejected,
            "suppressed": self.suppressed,
            "send_failed": self.send_failed,
            "lost": self.lost,
            "rates": {
                "qualification": self.qualification_rate,
                "approval": self.approval_rate,
                "reply": self.reply_rate,
                "meeting": self.meeting_rate,
                "close": self.close_rate,
            },
        }


def build_report(events: list[PipelineEvent]) -> FunnelReport:
    """Reduce an event log to a funnel."""
    report = FunnelReport()
    by_kind: dict[PipelineEventKind, set[str]] = {}
    for event in events:
        by_kind.setdefault(event.kind, set()).add(event.business_id)

    for stage, kinds in FUNNEL:
        reached: set[str] = set()
        for kind in kinds:
            reached |= by_kind.get(kind, set())
        report.counts[stage] = len(reached)

    report.disqualified = len(by_kind.get(PipelineEventKind.DISQUALIFIED, set()))
    report.rejected = len(by_kind.get(PipelineEventKind.REJECTED, set()))
    report.suppressed = len(by_kind.get(PipelineEventKind.SUPPRESSED, set()))
    report.send_failed = len(by_kind.get(PipelineEventKind.SEND_FAILED, set()))
    report.lost = len(by_kind.get(PipelineEventKind.LOST, set()))
    return report
