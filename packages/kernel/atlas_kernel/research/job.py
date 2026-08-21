"""A research run: what it looked at, what it found, and what it could not tell.

The engine's whole job is to produce evidence. Interpreting that evidence into
something to sell belongs to `outreach.opportunity`, and saying it out loud
belongs to `outreach.consistency`. Research must not do either, because a
component that both gathers the facts and decides what they mean will
eventually find what it went looking for.

Two structures carry everything:

* `StageResult` — one stage, its findings, and whether it actually ran.
* `ResearchResult` — the run, folded from its stages.

The distinction that matters most in this file is between a stage that looked
and found nothing, and a stage that could not look. The first is evidence. The
second is a fact about us, and turning it into a claim about a customer's
website is the single most damaging thing this system could do.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..opportunity.website_audit import Finding, Status

#: A research job's life. Deliberately not the ten build states — research never
#: designs, builds or produces media, and a lifecycle carrying states a job can
#: never reach tells an operator nothing.
class JobState(StrEnum):
    QUEUED = "QUEUED"
    RESEARCHING = "RESEARCHING"
    #: Every stage ran.
    READY = "READY"
    #: Some stages ran. The common outcome, and an honest one.
    PARTIAL = "PARTIAL"
    #: Nothing usable. Discovery failed, or the site never answered.
    FAILED = "FAILED"
    #: Stopped on purpose.
    CANCELLED = "CANCELLED"


TERMINAL = frozenset({JobState.READY, JobState.PARTIAL, JobState.FAILED,
                      JobState.CANCELLED})


class StageState(StrEnum):
    OK = "ok"
    #: Ran, and correctly declined to look — no CMS to read, no blog to analyse.
    SKIPPED = "skipped"
    #: Tried and could not. Everything it would have established is UNVERIFIED.
    FAILED = "failed"


def _now() -> datetime:
    return datetime.now(UTC)


class StageResult(BaseModel):
    """One stage of one run."""

    model_config = ConfigDict(frozen=True)

    stage: str
    state: StageState = StageState.OK
    findings: tuple[Finding, ...] = ()
    #: Facts worth keeping that are not findings — counts, routes, timings.
    facts: dict = Field(default_factory=dict)
    #: Why it skipped or failed. Never empty when it did.
    reason: str = ""
    duration_ms: int = 0

    @property
    def counted(self) -> bool:
        return self.state is StageState.OK


class ResearchResult(BaseModel):
    """A whole run, and the only thing downstream is allowed to read."""

    model_config = ConfigDict(frozen=True)

    business_id: str
    website: str
    state: JobState
    stages: tuple[StageResult, ...] = ()
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime = Field(default_factory=_now)

    @property
    def findings(self) -> tuple[Finding, ...]:
        return tuple(f for stage in self.stages for f in stage.findings)

    @property
    def facts(self) -> dict:
        return {stage.stage: stage.facts for stage in self.stages if stage.facts}

    @property
    def failed_stages(self) -> tuple[str, ...]:
        return tuple(s.stage for s in self.stages if s.state is StageState.FAILED)

    @property
    def ran(self) -> tuple[str, ...]:
        return tuple(s.stage for s in self.stages if s.state is StageState.OK)

    def observations(self) -> list[dict]:
        """The shape the audit already emits, so nothing downstream changes.

        `scoring.score()` and the opportunity rules both read
        `{"feature": ..., "status": ...}` lists today. Research produces the
        same thing, which is why adding an entire engine underneath them
        requires no change to either.
        """
        merged: dict[str, dict] = {}
        for finding in self.findings:
            existing = merged.get(finding.feature)
            # A confirmed reading beats an unverified one whichever arrived
            # first: one stage failing to see Arabic must not bury another
            # stage having found it.
            if existing is not None and existing["status"] != Status.UNVERIFIED.value:
                if finding.status is Status.UNVERIFIED:
                    continue
            merged[finding.feature] = {
                "feature": finding.feature,
                "status": finding.status.value,
                "category": finding.category.value,
                "evidence": finding.evidence,
            }
        return list(merged.values())


def fold(business_id: str, website: str, stages: list[StageResult], *,
         started: datetime, essential: str = "discovery") -> ResearchResult:
    """Decide what a run amounts to.

    A run is FAILED when the stage everything else depends on failed — without
    discovery there are no routes, so every later stage is guessing. Otherwise
    it is READY when every stage ran and PARTIAL when some did not, which is
    the ordinary outcome and is reported as such rather than as success.
    """
    by_name = {s.stage: s for s in stages}
    root = by_name.get(essential)
    if root is not None and root.state is StageState.FAILED:
        state = JobState.FAILED
    elif not stages:
        state = JobState.FAILED
    elif any(s.state is StageState.FAILED for s in stages):
        state = JobState.PARTIAL
    else:
        state = JobState.READY
    return ResearchResult(business_id=business_id, website=website, state=state,
                          stages=tuple(stages), started_at=started, finished_at=_now())
