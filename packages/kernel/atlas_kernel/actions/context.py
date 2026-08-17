"""What an action is given, and what it leaves behind.

One context travels through a whole plan. It carries the workspace the plan
builds in, the deployment target it publishes to, the factories for a browser
and a search client, and — the part that makes a plan a plan rather than a list
— the outputs of every step that has already run.

Factories rather than instances, deliberately. A browser costs ~400 MB resident
and the canonical box has 8 GB shared with PostgreSQL, so a plan whose steps
never browse must not pay for one; and a plan that browses twice should not hold
two open across the unrelated steps in between.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..workspace import Workspace


def _now() -> datetime:
    return datetime.now(UTC)


class ActionRecord(BaseModel):
    """One executed action. The unit of the plan's audit trail.

    Recorded whether it succeeded or failed, and it keeps the payload it was
    given: a plan that only records its successes cannot be diagnosed, and one
    that records outcomes without inputs cannot be reproduced.
    """

    model_config = ConfigDict(frozen=True)

    step_id: str
    action: str
    capability: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    error: str = ""
    duration_seconds: float = 0.0
    #: Screenshots, deployed files, captured logs. Paths, not blobs.
    evidence: list[str] = Field(default_factory=list)
    at: datetime = Field(default_factory=_now)
    attempt: int = 1

    def __str__(self) -> str:
        state = "ok" if self.ok else f"FAILED ({self.error[:60]})"
        retry = f" [attempt {self.attempt}]" if self.attempt > 1 else ""
        return f"{self.action}{retry} — {state} in {self.duration_seconds:.2f}s"


class ExecutionContext:
    """Everything a plan's steps share."""

    def __init__(
        self,
        *,
        workspace: Workspace,
        evidence_dir: Path | None = None,
        browser_factory: Callable[[], Any] | None = None,
        search_factory: Callable[[], Any] | None = None,
        deploy_target: Any | None = None,
        approvals: Any | None = None,
    ) -> None:
        self.workspace = workspace
        self.evidence_dir = Path(evidence_dir or workspace.root / "_evidence")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._browser_factory = browser_factory
        self._search_factory = search_factory
        self.deploy_target = deploy_target
        #: Authorisation boundary for outward-facing actions. Absent means
        #: nothing outward-facing may run — the safe default, not an oversight.
        self.approvals = approvals
        #: step id -> that step's output. What later steps read.
        self.outputs: dict[str, dict[str, Any]] = {}
        #: Every action attempted, in order.
        self.records: list[ActionRecord] = []

    def browser(self):
        if self._browser_factory is None:
            raise RuntimeError(
                "this plan needs a browser but none was provided. Pass "
                "browser_factory=... — an action never constructs its own runtime."
            )
        return self._browser_factory()

    def search(self):
        if self._search_factory is None:
            raise RuntimeError(
                "this plan needs web search but none was provided. Pass search_factory=..."
            )
        return self._search_factory()

    def evidence_path(self, name: str) -> Path:
        return self.evidence_dir / name

    def record(self, record: ActionRecord) -> ActionRecord:
        self.records.append(record)
        if record.ok:
            self.outputs[record.step_id] = record.output
        return record

    @property
    def evidence(self) -> list[str]:
        return [path for record in self.records for path in record.evidence]

    def lineage(self) -> str:
        """Every action taken, in order, as a person would read it."""
        lines = [f"plan lineage — {len(self.records)} action(s)"]
        lines.extend(f"  {index}. {record}" for index, record in enumerate(self.records, 1))
        if self.evidence:
            lines.append(f"  evidence: {len(self.evidence)} artifact(s) in {self.evidence_dir}")
        return "\n".join(lines)
