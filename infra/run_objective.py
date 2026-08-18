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
import tempfile
from pathlib import Path

sys.path.insert(0, "/opt/qevik/atlas/packages/kernel")

from atlas_kernel.actions import (  # noqa: E402
    ExecutionContext,
    PlanRunner,
    RegenerateRepairer,
    default_action_runner,
    default_planner,
)
from atlas_kernel.browser import PlaywrightSession  # noqa: E402
from atlas_kernel.research import BraveSearch  # noqa: E402
from atlas_kernel.website.targets.public_host import PublicHostTarget  # noqa: E402
from atlas_kernel.workspace import Workspace  # noqa: E402

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

    artifacts = Path(os.environ.get("QEVIK_JOB_ARTIFACTS", tempfile.mkdtemp()))
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

    workspace = Workspace.create(Path(tempfile.mkdtemp()), slug or "objective")
    target = PublicHostTarget(SITES_ROOT, base_url=PUBLIC_BASE)
    ctx = ExecutionContext(
        workspace=workspace,
        browser_factory=lambda: PlaywrightSession(headless=True),
        search_factory=BraveSearch,
        deploy_target=target,
        # Absent authorisation is not "no object" but an object saying no, so
        # the refusal message names the boundary rather than a missing argument.
        approvals=Authorised(publish),
    )

    report = PlanRunner(actions, repairer=RegenerateRepairer()).run(plan, ctx)
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
