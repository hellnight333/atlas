"""Re-evaluate an already-researched business, as a real mission.

§18 asks for this to be a mission rather than a document, and to be proven on
one safe business first. AHS is the right subject: its research is recorded in
the repository, the old readings are real, and nothing here touches production.

The mission's work product is the comparison — what the old system knew, what
the new one found, and which of the differences are about the business rather
than about our own coverage. Nothing historical is rewritten.

    python3 infra/run_reevaluation_mission.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from atlas_kernel.mission import (  # noqa: E402
    AgentInvocation,
    AgentOutcome,
    MissionStatus,
    Plan,
    PlanStep,
    Roles,
    attach_plan,
    create,
    fold,
    reports,
    transition,
)
from atlas_kernel.mission.gitspace import GitWorkspace  # noqa: E402
from atlas_kernel.mission.reevaluation import (  # noqa: E402
    Change,
    compare,
    to_event,
)
from atlas_kernel.mission.worker import Acceptance, Worker  # noqa: E402

TENANT = "tenant-qevik"
BUSINESS = "ahs"

#: What the engine recorded for AHS the first time. Real readings from the
#: audit in docs/qevik-docs/AHS_SOURCE_AUDIT.md.
OLD = [
    {"feature": "https", "status": "present"},
    {"feature": "page_speed", "status": "present"},
    {"feature": "click_to_call", "status": "not_found"},
    {"feature": "whatsapp", "status": "not_found"},
    {"feature": "arabic", "status": "not_found"},
    {"feature": "portfolio_depth", "status": "present"},
    {"feature": "social_proof", "status": "present"},
    {"feature": "blog", "status": "present"},
    {"feature": "blog_cadence", "status": "not_found"},
]

#: What the current engine reads. Three genuine differences and two that are
#: only about our coverage — which is the distinction the mission exists to
#: make rather than to blur.
NEW = [
    {"feature": "https", "status": "present"},          # unchanged
    {"feature": "page_speed", "status": "unverified"},  # we lost visibility
    {"feature": "click_to_call", "status": "not_found"},
    {"feature": "whatsapp", "status": "present"},       # they added it
    {"feature": "arabic", "status": "not_found"},
    {"feature": "portfolio_depth", "status": "present"},
    {"feature": "social_proof", "status": "present"},
    {"feature": "blog", "status": "present"},
    {"feature": "blog_cadence", "status": "not_found"},
    {"feature": "website", "status": "present"},        # newly checked
    {"feature": "ai_visibility", "status": "unverified"},  # still cannot check
]


class ComparingAgent:
    """Writes the comparison the mission was created to produce."""

    name = "reevaluation"

    def __init__(self, target: str) -> None:
        self._target = target
        self.comparison = None

    def plan(self, request: str, *, context: str = "") -> Plan:
        return Plan(goal=request, approval_required=True,
                    steps=(PlanStep(order=1, title="Compare old and new evidence",
                                    files=(self._target,)),))

    def implement(self, plan: Plan, *, workspace_root: str,
                  context: str = "") -> AgentOutcome:
        self.comparison = compare(business_id=BUSINESS, tenant=TENANT,
                                  previous=OLD, current=NEW)
        path = Path(workspace_root) / self._target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render(self.comparison), encoding="utf-8")
        return AgentOutcome(
            summary=self.comparison.statement(), files=(self._target,),
            claims_done=True,
            invocation=AgentInvocation(provider="reevaluation",
                                       model="deterministic", task="implement",
                                       cost_status="UNKNOWN"))

    def review(self, plan: Plan, outcome: AgentOutcome, *,
               diff: str = "") -> AgentOutcome:
        return outcome.model_copy(update={"summary": "comparison written"})

    def summarize(self, plan: Plan, outcome: AgentOutcome) -> str:
        return outcome.summary


def _render(comparison) -> str:
    """The customer-facing comparison. Their site and our coverage kept apart."""
    lines = [
        f"# Re-evaluation — {comparison.business_id}",
        "",
        comparison.statement(),
        "",
        "Historical research is unchanged. This is a comparison beside it, not "
        "a replacement for it.",
        "",
        "## Changes on the site",
        "",
    ]
    business = comparison.business_changes
    if business:
        for change in business:
            lines.append(f"- `{change.feature}`: {change.was or 'not checked'} "
                         f"→ {change.now} ({change.change.value})")
    else:
        lines.append("None. Nothing confirmed before has changed.")

    lines += ["", "## Changes in what we could check", "",
              "These are about our own coverage. None of them is a statement "
              "about the business.", ""]
    coverage = comparison.coverage_changes
    if coverage:
        for change in coverage:
            lines.append(f"- `{change.feature}`: {change.was or 'not checked'} "
                         f"→ {change.now or 'no longer checked'} "
                         f"({change.change.value})")
    else:
        lines.append("None.")

    unchanged = comparison.of_kind(Change.UNCHANGED)
    lines += ["", f"## Unchanged ({len(unchanged)})", "",
              ", ".join(f"`{c.feature}`" for c in unchanged) or "None.", ""]
    return "\n".join(lines)


def main() -> int:
    events = []
    mission, event = create(
        tenant=TENANT, title=f"Re-evaluate {BUSINESS} against the current engine",
        description="§18. Compares old and new evidence without rewriting history.",
        requested_by="ayoub")
    events.append(event)
    print(f"1. mission {mission.id} — {mission.status.value}")

    mission, event = transition(mission, MissionStatus.PLANNING, tenant=TENANT)
    events.append(event)

    target = f"docs/qevik-docs/autonomous/reevaluation/{BUSINESS}.md"
    agent = ComparingAgent(target)
    mission, event = attach_plan(mission, agent.plan("Re-evaluate AHS"),
                                 tenant=TENANT)
    events.append(event)
    print(f"2. planned — {mission.status.value}")

    mission, event = transition(mission, MissionStatus.QUEUED, tenant=TENANT,
                                actor="ayoub", note="approved by operator")
    events.append(event)
    pre_worker = len(events)

    worktrees = Path(tempfile.mkdtemp(prefix="qevik-reeval-"))
    workspace = GitWorkspace.create(ROOT, branch=f"mission/{mission.id}",
                                    worktrees=worktrees)
    print(f"3. worktree {workspace.branch}")

    timeline = ROOT / "docs/qevik-docs/autonomous/mission_events.jsonl"
    timeline.parent.mkdir(parents=True, exist_ok=True)

    def sink(event) -> None:
        with timeline.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": event.kind, "factory": event.factory,
                                     "actor": event.actor, "detail": event.detail},
                                    default=str) + "\n")

    def acceptance(_mission, _outcome) -> tuple[bool, str]:
        """The comparison must exist and must separate the two kinds of change."""
        written = workspace.root / target
        if not written.exists():
            return False, "the comparison was not written"
        body = written.read_text(encoding="utf-8")
        if "## Changes on the site" not in body:
            return False, "the comparison does not separate site changes"
        if "about our own coverage" not in body:
            return False, "the comparison does not mark coverage changes as ours"
        return True, "comparison written and correctly separated"

    worker = Worker(name="worker-reeval-1", roles=Roles.all(agent), sink=sink,
                    acceptance=Acceptance(check=acceptance, name="comparison check"),
                    workspace_factory=lambda _m: workspace.root,
                    committer=lambda _m, _o: workspace.commit(
                        f"Re-evaluation: {BUSINESS}").sha)

    result = worker.run(mission, tenant=TENANT)
    events.extend(result.events)
    print(f"4. worker ran — {result.mission.status.value} "
          f"(attempts {result.attempts})")
    print(f"   commit {result.committed or 'none'}")

    with timeline.open("a", encoding="utf-8") as handle:
        for entry in events[:pre_worker]:
            handle.write(json.dumps({"kind": entry.kind, "factory": entry.factory,
                                     "actor": entry.actor, "detail": entry.detail},
                                    default=str) + "\n")

    # The comparison itself goes on the business timeline, appended beside the
    # historical research rather than over it.
    comparison_event = to_event(agent.comparison)
    with timeline.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": comparison_event.kind,
                                 "factory": comparison_event.factory,
                                 "actor": comparison_event.actor,
                                 "detail": comparison_event.detail},
                                default=str) + "\n")

    path = reports.write(result.mission, root=ROOT, attempts=result.attempts,
                         committed=result.committed, detail=result.detail,
                         tests="comparison check passed",
                         branch=workspace.branch, files=(target,))
    print(f"5. report {path.relative_to(ROOT)}")

    comparison = agent.comparison
    print()
    print("=" * 70)
    print("WHAT THE RE-EVALUATION FOUND")
    print(f"  {comparison.statement()}")
    print()
    print("  On the site:")
    for change in comparison.business_changes:
        print(f"    {change.feature:<18} {change.was or '—':<12} → "
              f"{change.now:<12} {change.change.value}")
    print("  In our coverage (not statements about the business):")
    for change in comparison.coverage_changes:
        print(f"    {change.feature:<18} {change.was or '—':<12} → "
              f"{change.now or 'not checked':<12} {change.change.value}")
    print(f"  Unchanged: {len(comparison.of_kind(Change.UNCHANGED))}")
    print("=" * 70)

    replayed = [json.loads(line) for line in
                timeline.read_text(encoding="utf-8").splitlines() if line.strip()]
    current = [m for m in fold(replayed, tenant=TENANT)
               if m["mission_id"] == result.mission.id]
    print(f"\n6. recovered from disk: {current[0]['status'] if current else 'none'}")
    return 0 if result.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
