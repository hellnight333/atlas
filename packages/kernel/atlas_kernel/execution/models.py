"""What an execution produced, and whether anyone may act on it.

The distinction this module exists to hold: **READY_TO_PUBLISH is not
PUBLISHED.** One means an artefact passed its gates and is waiting for a human;
the other means it is live in the world. Collapsing them is how a system reports
success for work nobody ever saw, and it is the single most damaging confusion
available here — so they are separate states, the transition between them
happens nowhere in this package, and a test asserts that.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class NotApproved(Exception):
    """Execution was attempted without the consent that authorises it."""


class UnsupportedCapability(Exception):
    """No executor exists for the capability a recommendation names."""


class PublicationState(StrEnum):
    #: Produced, gates not yet run.
    DRAFT = "DRAFT"
    #: Gates passed. A human may now decide. **Nobody outside has seen it.**
    READY_TO_PUBLISH = "READY_TO_PUBLISH"
    #: A gate failed. Never publishable, whatever else succeeded.
    REJECTED = "REJECTED"
    #: Live. Not reachable from this package — P1.4 and a separate approval own
    #: the step, and the value exists here only so the enum is honest about
    #: what comes next.
    PUBLISHED = "PUBLISHED"


class QAVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    #: The gate could not run. Never a pass — an unrun check has established
    #: nothing, exactly as an unverified observation establishes nothing.
    NOT_RUN = "not_run"


class QAResult(BaseModel):
    """One gate's finding."""

    model_config = ConfigDict(frozen=True)

    gate: str
    verdict: QAVerdict
    detail: str = ""

    @property
    def blocks(self) -> bool:
        """Only a pass lets an artefact through. NOT_RUN blocks."""
        return self.verdict is not QAVerdict.PASS


class ExecutionOutcome(BaseModel):
    """A job's whole result, and the only thing downstream should read."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    run_id: str
    recommendation_id: str
    business_id: str
    tenant_id: str | None = None
    capability_id: str = ""

    succeeded: bool = False
    error: str = ""
    asset_ids: tuple[str, ...] = ()
    qa: tuple[QAResult, ...] = ()
    state: PublicationState = PublicationState.DRAFT

    #: Enough to measure later without re-deriving anything: what the numbers
    #: were before, and what would be watched afterwards. P1.4 reads these.
    baseline: dict = Field(default_factory=dict)
    measures: tuple[str, ...] = ()

    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def failed_gates(self) -> tuple[QAResult, ...]:
        return tuple(r for r in self.qa if r.blocks)

    @property
    def publishable(self) -> bool:
        """Never true because generation succeeded — only because QA passed."""
        return (self.succeeded and bool(self.asset_ids) and not self.failed_gates
                and self.state is PublicationState.READY_TO_PUBLISH)
