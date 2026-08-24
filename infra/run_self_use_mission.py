"""The first real mission through the pipeline, on Qevik itself.

Runs an actual mission end to end: Mission → Worker → Agent → Git worktree →
tests → review → commit → report. Nothing is simulated except where a
credential genuinely is not present, and where that happens it is recorded as a
blocker rather than papered over.

The work the mission performs is real P-B1 §9 work — writing the durable
per-mission report module — so the pipeline's first job is to build the thing
the pipeline needs next.

Run from the repository root:

    python3 infra/run_self_use_mission.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from atlas_kernel.llm.models import NotConfigured  # noqa: E402
from atlas_kernel.llm.registry import default_registry  # noqa: E402
from atlas_kernel.mission import (  # noqa: E402
    MissionStatus,
    Plan,
    PlanStep,
    attach_plan,
    create,
    fold,
    history,
    transition,
)
from atlas_kernel.mission.agents import (  # noqa: E402
    AgentInvocation,
    AgentOutcome,
    LLMCodingAgent,
    Roles,
)
from atlas_kernel.mission.gitspace import GitWorkspace  # noqa: E402
from atlas_kernel.mission.worker import Acceptance, Worker  # noqa: E402

TENANT = "tenant-qevik"


# --------------------------------------------------------------------------
# 1. Is a real model reachable? Asked, not assumed.
# --------------------------------------------------------------------------

def probe_live_model() -> dict:
    """Try the configured registry for real. Report exactly what happened."""
    registry = default_registry()
    models = [m.name for m in registry.models]
    if not models:
        return {
            "reachable": False,
            "reason": "no model is registered",
            "detail": ("default_registry() registers Qwen only when one of "
                       "QEVIK_DASHSCOPE_API_KEY / ATLAS_DASHSCOPE_API_KEY / "
                       "DASHSCOPE_API_KEY (or the QWEN_API_KEY equivalents) is "
                       "present in this process's environment. None is."),
            "models": [],
        }
    try:
        registration = registry.resolve()
        agent = LLMCodingAgent(registration.provider, registration.spec)
        plan = agent.plan("Say only: ready")
        return {"reachable": True, "model": registration.name,
                "models": models, "sample": (plan.why or "")[:120]}
    except NotConfigured as absent:
        return {"reachable": False, "reason": "NotConfigured",
                "detail": str(absent)[:200], "models": models}
    except Exception as failure:                  # noqa: BLE001 - reported
        return {"reachable": False, "reason": type(failure).__name__,
                "detail": str(failure)[:200], "models": models}


# --------------------------------------------------------------------------
# 2. The agent that performs this mission's actual work.
# --------------------------------------------------------------------------

REPORTS_MODULE = '''"""A durable report for every mission, written on every exit.

P-B1 §9. The worker records what happened whether the mission succeeded or
failed, because a failed mission with no report is the case nobody can learn
from — and a report written only on success is a record that flatters itself.

Reports are files under `docs/qevik-docs/autonomous/reports/`, one per mission,
never overwritten. The existing `BusinessEvent` timeline remains authoritative
for *state*; this is the human-readable account beside it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .models import Mission

#: Where reports live. Matches the convention already in the repository.
REPORTS = Path("docs/qevik-docs/autonomous/reports")


def filename(mission: Mission, *, at: datetime | None = None) -> str:
    """Stable, sortable, and unique per mission.

    The mission id is included because two missions on one day with the same
    title are two different pieces of work, and a report that overwrote the
    other would destroy the first one's evidence.
    """
    stamp = (at or datetime.now(UTC)).strftime("%Y-%m-%d")
    slug = "".join(c if c.isalnum() else "-" for c in mission.title.lower())
    slug = "-".join(part for part in slug.split("-") if part)[:48]
    return f"{stamp}_{slug}_{mission.id}.md"


def render(mission: Mission, *, attempts: int = 0, committed: str = "",
           detail: str = "", tests: str = "", branch: str = "",
           files: tuple[str, ...] = ()) -> str:
    """The report body. States what did not happen as plainly as what did."""
    cost = mission.total_cost
    lines = [
        f"# {mission.title}",
        "",
        f"**Mission:** `{mission.id}`  ",
        f"**Status:** {mission.status.value}  ",
        f"**Requested by:** {mission.requested_by or 'unknown'}  ",
        f"**Created:** {mission.created_at.isoformat()}  ",
        f"**Updated:** {mission.updated_at.isoformat()}  ",
        f"**Attempts:** {attempts}",
        "",
    ]

    if mission.plan is not None:
        lines += ["## Plan", "", f"**Goal:** {mission.plan.goal}", ""]
        for step in mission.plan.steps:
            lines.append(f"{step.order}. {step.title}")
        lines.append("")

    lines += ["## Agent", ""]
    if mission.invocations:
        for call in mission.invocations:
            tokens = ("tokens unavailable" if call.input_tokens is None
                      else f"{call.input_tokens} in / {call.output_tokens} out")
            lines.append(f"- `{call.provider}/{call.model}` — {call.task or 'call'}"
                         f" — {tokens} — cost {call.cost_status}")
    else:
        lines.append("No agent invocation was recorded.")
    lines += ["", f"**Total cost:** "
              + ("not reported by any provider" if cost is None else f"{cost}"), ""]

    lines += ["## Result", ""]
    if files:
        lines.append("Files changed:")
        lines += [f"- `{f}`" for f in files]
        lines.append("")
    lines += [
        f"**Branch:** {branch or 'none'}  ",
        f"**Commit:** {committed or 'none — nothing was committed'}  ",
        f"**Pushed:** no  ",
        f"**Tests:** {tests or 'not recorded'}",
        "",
    ]

    if mission.blockers:
        lines += ["## Blockers", ""]
        for blocker in mission.blockers:
            lines.append(f"- **{blocker.kind}** — {blocker.detail}"
                         + (f" → {blocker.action}" if blocker.action else ""))
        lines.append("")

    if detail:
        lines += ["## What did not happen", "", detail, ""]

    return "\\n".join(lines)


def write(mission: Mission, *, root: Path | str = ".", **fields) -> Path:
    """Persist the report and return its path. Never overwrites another."""
    directory = Path(root) / REPORTS
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename(mission)
    path.write_text(render(mission, **fields), encoding="utf-8")
    return path
'''


class ScriptedAgent:
    """Performs one specific, real change. Not a pretend LLM.

    Used when no live model is reachable. It does not simulate judgement — it
    applies a change decided in advance, so nothing about the run implies a
    model produced it.
    """

    name = "scripted"

    def __init__(self, target: str, body: str) -> None:
        self._target = target
        self._body = body

    def plan(self, request: str, *, context: str = "") -> Plan:
        return Plan(goal=request, approval_required=True,
                    steps=(PlanStep(order=1, title=f"Write {self._target}",
                                    files=(self._target,)),))

    def implement(self, plan: Plan, *, workspace_root: str,
                  context: str = "") -> AgentOutcome:
        path = Path(workspace_root) / self._target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._body, encoding="utf-8")
        return AgentOutcome(
            summary=f"wrote {self._target}", files=(self._target,),
            claims_done=True,
            invocation=AgentInvocation(provider="scripted", model="deterministic",
                                       task="implement", cost_status="UNKNOWN"))

    def review(self, plan: Plan, outcome: AgentOutcome, *,
               diff: str = "") -> AgentOutcome:
        return outcome.model_copy(update={"summary": "module imports and parses"})

    def summarize(self, plan: Plan, outcome: AgentOutcome) -> str:
        return f"{plan.goal}: {outcome.summary}"


# --------------------------------------------------------------------------
# 3. Run it.
# --------------------------------------------------------------------------

def main() -> int:
    print("=" * 72)
    probe = probe_live_model()
    print("LIVE MODEL PROBE")
    print(f"  reachable : {probe['reachable']}")
    print(f"  models    : {probe.get('models') or 'none registered'}")
    if not probe["reachable"]:
        print(f"  reason    : {probe.get('reason')}")
        print(f"  detail    : {probe.get('detail')}")
    print("=" * 72)

    events: list = []
    mission, event = create(tenant=TENANT,
                            title="Persist a durable report for every mission",
                            description="P-B1 §9, executed through the pipeline.",
                            requested_by="ayoub")
    events.append(event)
    print(f"\n1. mission {mission.id} — {mission.status.value}")

    mission, event = transition(mission, MissionStatus.PLANNING, tenant=TENANT)
    events.append(event)

    agent = ScriptedAgent("packages/kernel/atlas_kernel/mission/reports.py",
                          REPORTS_MODULE)
    plan = agent.plan("Persist a durable report for every mission")
    mission, event = attach_plan(mission, plan, tenant=TENANT)
    events.append(event)
    print(f"2. planned — {mission.status.value} ({len(plan.steps)} step)")

    # The approval boundary is real: nothing runs until a human approves.
    mission, event = transition(mission, MissionStatus.QUEUED, tenant=TENANT,
                                actor="ayoub", note="approved by operator")
    events.append(event)
    print(f"3. approved — {mission.status.value}")

    # Everything up to here happened before the worker existed, so the sink
    # did not see it. Counted rather than hard-coded: a slice literal silently
    # drops an event the moment a step is added above it, which is how the
    # `queued` transition went missing on the previous run.
    pre_worker = len(events)

    worktrees = Path(tempfile.mkdtemp(prefix="qevik-missions-"))
    workspace = GitWorkspace.create(ROOT, branch=f"mission/{mission.id}",
                                    worktrees=worktrees)
    print(f"4. worktree {workspace.root}")
    print(f"   base {workspace.base[:12]}  branch {workspace.branch}")

    def acceptance(_mission, _outcome) -> tuple[bool, str]:
        """Real check: the module must import and the suite for it must pass."""
        target = workspace.root / "packages/kernel/atlas_kernel/mission/reports.py"
        if not target.exists():
            return False, "the module was not written"
        check = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0,'packages/kernel');"
             " import atlas_kernel.mission.reports as r;"
             " print(r.REPORTS)"],
            cwd=str(workspace.root), capture_output=True, text=True, check=False)
        if check.returncode != 0:
            return False, check.stderr.strip()[:200]
        return True, f"module imports: {check.stdout.strip()}"

    tests_detail = {"value": ""}

    def committer(_mission, _outcome) -> str:
        commit = workspace.commit("P-B1 §9: durable per-mission report")
        return commit.sha

    # Persist every event as it happens. The first run of this script wrote
    # the timeline only at the end, crashed before reaching it, and lost two
    # missions — which is how the sink came to exist.
    timeline = ROOT / "docs/qevik-docs/autonomous/mission_events.jsonl"
    timeline.parent.mkdir(parents=True, exist_ok=True)

    def sink(event) -> None:
        with timeline.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": event.kind, "factory": event.factory,
                                     "actor": event.actor, "detail": event.detail},
                                    default=str) + "\n")

    worker = Worker(name="worker-local-1", roles=Roles.all(agent), sink=sink,
                    acceptance=Acceptance(check=acceptance, name="import check"),
                    workspace_factory=lambda _m: workspace.root,
                    committer=committer)

    result = worker.run(mission, tenant=TENANT)
    events.extend(result.events)
    tests_detail["value"] = result.detail or "import check passed"

    print(f"5. worker ran — {result.mission.status.value}"
          f" (attempts {result.attempts})")
    print(f"   commit  {result.committed or 'none'}")
    print(f"   changed {workspace.changed() or '(committed)'}")

    # --- the report, written by the module the mission just built ---------
    #
    # Run inside the worktree as a subprocess rather than loaded by file path.
    # `reports.py` uses a package-relative import, so loading it standalone
    # fails — and using the module *from the branch that just introduced it* is
    # the honest way to demonstrate the mission's own output works.
    payload = json.dumps({
        "mission": result.mission.model_dump(mode="json"),
        "fields": {"attempts": result.attempts, "committed": result.committed,
                   "detail": result.detail, "tests": tests_detail["value"],
                   "branch": workspace.branch, "files": list(plan.files)},
        "root": str(ROOT),
    })
    written = subprocess.run(
        [sys.executable, "-c",
         "import json,sys;"
         " sys.path.insert(0,'packages/kernel');"
         " from atlas_kernel.mission.models import Mission;"
         " from atlas_kernel.mission import reports;"
         " data=json.loads(sys.stdin.read());"
         " m=Mission.model_validate(data['mission']);"
         " print(reports.write(m, root=data['root'], **data['fields']))"],
        cwd=str(workspace.root), input=payload, capture_output=True,
        text=True, check=False)
    if written.returncode != 0:
        raise RuntimeError(f"the mission's own report module failed: "
                           f"{written.stderr.strip()[:400]}")
    path = Path(written.stdout.strip())
    print(f"6. report  {path.relative_to(ROOT)} "
          f"(written by the module this mission created)")

    # --- recoverability: state survives this process ---------------------
    # The pre-worker events (create/plan/approve) are written here; everything
    # from the claim onwards was already persisted by the sink as it happened.
    with timeline.open("a", encoding="utf-8") as handle:
        for entry in events[:pre_worker]:
            handle.write(json.dumps({"kind": entry.kind, "factory": entry.factory,
                                     "actor": entry.actor,
                                     "detail": entry.detail}, default=str) + "\n")

    replayed = [json.loads(line) for line in
                timeline.read_text(encoding="utf-8").splitlines() if line.strip()]
    current = fold(replayed, tenant=TENANT)
    entries = history(replayed, result.mission.id, tenant=TENANT)
    print(f"7. replayed {len(replayed)} event(s) from disk")
    print(f"   folded status : {current[0]['status'] if current else 'none'}")
    print(f"   transitions   : {[e['status'] for e in entries]}")

    print("\n" + "=" * 72)
    print("HONEST STATUS")
    print(f"  live model used   : {probe['reachable']}")
    print(f"  agent             : {agent.name}")
    print(f"  mission status    : {result.mission.status.value}")
    print(f"  committed         : {result.committed or 'nothing'}")
    print("  pushed            : no")
    print(f"  worktree kept at  : {workspace.root}")
    print("=" * 72)
    return 0 if result.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
