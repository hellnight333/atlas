#!/usr/bin/env python3
"""Continue a plan that paused for a human decision.

    resume_objective.py <original_job_id>

Started by the control API when an approval is granted. It reads the state the
paused run left behind, rebuilds the outputs earlier steps produced, and
continues from the blocked step.

The steps that already ran are **not** re-run. Their effects have happened —
files written, tests executed, sites built — and repeating them would at best
waste the work and at worst duplicate something outward-facing. That is why the
paused run wrote its outputs down rather than trusting a fresh process to
reproduce them.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "/opt/qevik/atlas/packages/kernel")

from atlas_kernel.actions import (  # noqa: E402
    ExecutionContext,
    PlanRunner,
    RegenerateRepairer,
    default_action_runner,
)
from atlas_kernel.actions.approval_gate import ApprovalGate, init_approvals  # noqa: E402
from atlas_kernel.actions.context import ActionRecord  # noqa: E402
from atlas_kernel.actions.runner import state_path  # noqa: E402
from atlas_kernel.agents.plan_models import ExecutionPlan  # noqa: E402
from atlas_kernel.browser import PlaywrightSession  # noqa: E402
from atlas_kernel.jobs import JobRunner  # noqa: E402
from atlas_kernel.research import BraveSearch  # noqa: E402
from atlas_kernel.website.targets.public_host import PublicHostTarget  # noqa: E402
from atlas_kernel.workspace import Workspace  # noqa: E402

SITES_ROOT = os.environ.get("QEVIK_SITES_ROOT", "/srv/sites")
# The public base for published sites. The old-host IP used to be the default
# here; a second production host makes a hard-coded origin a way to publish a
# URL that points at the wrong machine, so the public name is the default and
# QEVIK_SITES_BASE_URL (as set in atlas.env on the hosts) overrides it.
PUBLIC_BASE = os.environ.get("QEVIK_SITES_BASE_URL", "https://sites.qevik.ai")


class Authorised:
    approved = True


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: resume_objective.py <job_id>", file=sys.stderr)
        return 2
    original_job = sys.argv[1]
    artifacts = Path(os.environ.get("QEVIK_JOB_ARTIFACTS", "."))

    runner = JobRunner()
    try:
        paused = runner.get(original_job)
    except Exception as error:  # noqa: BLE001
        print(f"cannot read the paused job: {error}", file=sys.stderr)
        return 1

    state_file = state_path(paused.artifacts_dir)
    if not state_file.is_file():
        print(f"no resume state at {state_file}; nothing to continue", file=sys.stderr)
        return 1

    state = json.loads(state_file.read_text(encoding="utf-8"))
    plan = ExecutionPlan.model_validate(state["plan"])
    completed = set(state.get("completed") or [])

    print("RESUMING  :", original_job)
    print("PAUSED AT :", state.get("paused_at_step"))
    print("APPROVAL  :", state.get("approval_id"))
    print("ALREADY DONE:", ", ".join(sorted(completed)) or "nothing")

    # The workspace the paused run built in. Reusing it is the whole point —
    # the generated files and the dist/ directory are already there.
    workspace = Workspace.open(state["workspace_root"])
    target = PublicHostTarget(SITES_ROOT, base_url=PUBLIC_BASE)
    ctx = ExecutionContext(
        workspace=workspace,
        browser_factory=lambda: PlaywrightSession(headless=True),
        search_factory=BraveSearch,
        deploy_target=target,
        approvals=Authorised(),
    )
    ctx.outputs.update(state.get("outputs") or {})
    for raw in state.get("records") or []:
        try:
            ctx.records.append(ActionRecord.model_validate(raw))
        except Exception:  # noqa: BLE001 - a record that will not parse is not worth failing over
            pass

    # Drop the steps that already ran. The gate still guards what remains, so a
    # plan with two publishes needs two decisions rather than one.
    remaining = [s for s in plan.steps if s.id not in completed]
    plan = plan.model_copy(update={"steps": remaining})
    print("REMAINING :", ", ".join(s.id for s in remaining) or "nothing")

    init_approvals()
    report = PlanRunner(
        default_action_runner(),
        repairer=RegenerateRepairer(),
        gate=ApprovalGate(requested_by="qevik"),
        job_id=original_job,  # the same job, so approvals stay attached to it
    ).run(plan, ctx)

    print()
    print(report.summary())
    print()
    print(report.render_provenance())

    deployed = next(
        (r.output.get("url", "") for r in reversed(report.records)
         if r.action == "site.deploy" and r.ok),
        "",
    )
    verified = next(
        (r.output for r in reversed(report.records) if r.action == "browser.operate" and r.ok), {}
    )
    print("DEPLOYED_URL:", deployed or "-")
    print("VERIFIED    :", verified.get("status"), verified.get("extracted"))

    for shot in report.evidence:
        try:
            shutil.copy(shot, artifacts / Path(shot).name)
        except OSError:
            pass
    (artifacts / "outcome.json").write_text(
        json.dumps(
            {
                "ok": report.ok,
                "resumed_from": original_job,
                "deployed_url": deployed,
                "verified_status": verified.get("status"),
                "waiting_approval": report.waiting_approval,
                "approval_id": report.approval_id,
                "error": report.error,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    (artifacts / "provenance.json").write_text(
        json.dumps(report.provenance(), indent=2, default=str), encoding="utf-8"
    )
    print("OK" if report.ok else ("PAUSED" if report.waiting_approval else "FAILED"))
    return 0 if (report.ok or report.waiting_approval) else 1


if __name__ == "__main__":
    raise SystemExit(main())
