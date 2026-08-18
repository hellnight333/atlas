#!/usr/bin/env python3
"""Run one natural-language objective to completion, as a durable job.

Invoked by the control API, never by a person directly. It lives on disk and is
version-controlled rather than being generated per request: a control plane that
writes fresh scripts and executes them is a shell with extra steps.

    run_objective.py "<objective>" "<slug>" publish|no-publish

Everything it learns is written into the job's artifacts directory so the UI can
show it after the fact — the plan, the provenance, the outcome and any
screenshots. The browser tab is a viewer; this is what actually happened.
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
    default_planner,
)
from atlas_kernel.actions.approval_gate import ApprovalGate, init_approvals  # noqa: E402
from atlas_kernel.browser import PlaywrightSession  # noqa: E402
from atlas_kernel.research import BraveSearch  # noqa: E402
from atlas_kernel.website.targets.public_host import PublicHostTarget  # noqa: E402
from atlas_kernel.workspace import Workspace  # noqa: E402

#: Where a job builds. Durable on purpose: the first version used
#: tempfile.mkdtemp(), and systemd's PrivateTmp gives each service invocation
#: its own /tmp — so restarting the API between a pause and an approval deleted
#: the generated files while the plan state survived. The approval was intact,
#: the site it referred to was gone, and the resume failed on a missing
#: directory. Work that a human is being asked to approve has to outlive the
#: process that made it.
WORKSPACES = Path(os.environ.get("QEVIK_WORKSPACES", "/var/lib/qevik/workspaces"))
SITES_ROOT = os.environ.get("QEVIK_SITES_ROOT", "/srv/sites")
PUBLIC_BASE = os.environ.get("QEVIK_SITES_BASE_URL", "http://2.28.62.83")


class Authorised:
    """Carries the operator's decision into the deploy handler.

    Constructed here from an argument the API set after checking the submitting
    user's scope. A plan cannot make one of these for itself, which is the point.
    """

    def __init__(self, approved: bool) -> None:
        self.approved = approved


def main() -> int:
    objective = sys.argv[1] if len(sys.argv) > 1 else ""
    slug = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
    publish = len(sys.argv) > 3 and sys.argv[3] == "publish"
    if not objective:
        print("no objective given", file=sys.stderr)
        return 2

    artifacts = Path(os.environ.get("QEVIK_JOB_ARTIFACTS", "."))
    artifacts.mkdir(parents=True, exist_ok=True)

    print("OBJECTIVE:", objective)
    print("PUBLISH AUTHORISED:", publish)

    actions = default_action_runner()
    planner = default_planner(actions=actions)
    plan = planner.plan(objective, slug=slug or None, python=sys.executable)

    snapshot = plan.context_snapshot
    print("PLANNER  :", snapshot.get("planner"), "| MODEL:", snapshot.get("model"))
    if planner.last_fallback_reason:
        print("FALLBACK :", planner.last_fallback_reason)
    for correction in snapshot.get("corrections") or []:
        print("CORRECTED:", correction[:160])

    print("PLAN     :")
    for step in plan.steps:
        payload = json.dumps(step.payload, default=str)
        refs = sorted(set(__import__("re").findall(r"\$\{([A-Za-z0-9_.\-\[\]]+)\}", payload)))
        print(f"  {step.id:<22} {step.action:<16} {('<- ' + ', '.join(refs)) if refs else ''}")
    (artifacts / "plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    WORKSPACES.mkdir(parents=True, exist_ok=True)
    job_name = os.environ.get("QEVIK_JOB_ID", "objective")
    workspace = Workspace.create(WORKSPACES, job_name)
    target = PublicHostTarget(SITES_ROOT, base_url=PUBLIC_BASE)
    ctx = ExecutionContext(
        workspace=workspace,
        browser_factory=lambda: PlaywrightSession(headless=True),
        search_factory=BraveSearch,
        deploy_target=target,
        # Kept for the deploy handler's own check. The gate above is the real
        # boundary now; this remains so a plan cannot publish when the operator
        # did not even ask to.
        approvals=Authorised(publish),
    )

    # The gate is always present on the server. Outward-facing steps stop here
    # for a human rather than inheriting a blanket permission granted before
    # anyone knew what would be published.
    init_approvals()
    job_id = os.environ.get("QEVIK_JOB_ID", "")
    gate = ApprovalGate(requested_by="qevik")
    report = PlanRunner(
        actions, repairer=RegenerateRepairer(), gate=gate, job_id=job_id
    ).run(plan, ctx)

    if report.waiting_approval:
        print()
        print(f"PAUSED: {report.error}")
        print(f"APPROVAL: {report.approval_id}  (step {report.paused_at_step})")
        (artifacts / "outcome.json").write_text(
            json.dumps(
                {
                    "ok": False,
                    "waiting_approval": True,
                    "approval_id": report.approval_id,
                    "paused_at_step": report.paused_at_step,
                    "objective": objective,
                    "planner": snapshot.get("planner"),
                    "model": snapshot.get("model"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        # Exit 0: pausing for a decision is not a failure, and marking it one
        # would put every waiting job in the failed list.
        return 0
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
        (r.output for r in reversed(report.records) if r.action == "browser.operate" and r.ok),
        {},
    )
    print("DEPLOYED_URL:", deployed or "-")
    print("VERIFIED    :", verified.get("status"), verified.get("extracted"))
    print("REPAIRS     :", report.repairs)

    for shot in report.evidence:
        try:
            shutil.copy(shot, artifacts / Path(shot).name)
        except OSError:
            pass
    (artifacts / "provenance.json").write_text(
        json.dumps(report.provenance(), indent=2, default=str), encoding="utf-8"
    )
    (artifacts / "outcome.json").write_text(
        json.dumps(
            {
                "ok": report.ok,
                "objective": objective,
                "planner": snapshot.get("planner"),
                "model": snapshot.get("model"),
                "deployed_url": deployed,
                "verified_status": verified.get("status"),
                "repairs": report.repairs,
                "refused": report.refused,
                "timed_out": report.timed_out,
                "error": report.error,
                "publish_authorised": publish,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    (artifacts / "report.txt").write_text(
        report.summary() + "\n\n" + report.render_provenance(), encoding="utf-8"
    )
    print("OK" if report.ok else "FAILED")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
