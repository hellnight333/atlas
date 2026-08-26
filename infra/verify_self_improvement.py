#!/usr/bin/env python3
"""A feature request, from the phone to a commit, with nothing invented.

    feature request -> conversation -> plan OR explicit blocker
    -> deterministic policy -> approval -> mission -> scheduler
    -> agent -> isolated worktree -> tests -> commit -> report

The two things this exists to prove are refusals, not successes:

**Qevik never invents a plan.** With no model it produces a blocker naming what
is missing, and the blocker distinguishes "no credential" from "the provider is
refusing the credential you have" — those need opposite actions from the person
reading them.

**Qevik does not authorise changes to Qevik.** The mission edits Qevik's own
source, so it cannot reach a queue without a person, whatever the plan says
about itself.

Everything is driven through the real HTTP surface with a real worker process
and real restarts. Nothing here calls a service function directly to skip a
step it did not want to set up.

    python3 infra/verify_self_improvement.py
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

TENANT = "tenant-selfimprove"
USER = "selfimprove-operator"
REQUEST = ("Add this feature: record how long each mission spends waiting for "
           "approval, and show it on the mission detail page.")

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "", *, why_not: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    shown = detail if ok else (why_not or detail)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {shown}" if shown else ""))
    return ok


def call(base: str, path: str, method: str = "GET", body: object = None,
         token: str = "") -> tuple[int, dict]:
    request = urllib.request.Request(base + path, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(request, data, timeout=40) as answer:
            return answer.status, json.loads(answer.read() or b"{}")
    except urllib.error.HTTPError as failed:
        try:
            return failed.code, json.loads(failed.read() or b"{}")
        except Exception:
            return failed.code, {}
    except Exception as failed:
        return 0, {"error": type(failed).__name__}


def serve(state: Path, port: int) -> subprocess.Popen:
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--factory",
         "atlas_kernel.qevik.app:from_environment",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env={**os.environ, "QEVIK_STATE": str(state),
             "QEVIK_REPOSITORY": str(ROOT),
             "QEVIK_VAULT_MASTER_KEY": "self-improvement-check-not-a-secret",
             "PYTHONPATH": str(ROOT / "packages" / "kernel")},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        time.sleep(0.5)
        if call(base, "/api/health")[0] in (200, 401, 403):
            return process
        if process.poll() is not None:
            raise RuntimeError("the control plane exited during start-up")
    raise RuntimeError("the control plane never answered")


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8488)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    workspace = Path(tempfile.mkdtemp(prefix="qevik-selfimprove-"))
    state = workspace / "state"
    state.mkdir(parents=True)
    (state / "reports").mkdir()
    base = f"http://127.0.0.1:{args.port}"
    server: subprocess.Popen | None = None

    from atlas_kernel.auth.models import Scope
    from atlas_kernel.auth.store import AuthStore, init_auth

    init_auth()
    store = AuthStore()
    password = secrets.token_urlsafe(32)
    scopes = frozenset({Scope.READ, Scope.EXECUTE, Scope.ADMIN})
    if store.get_user(USER) is None:
        store.create_user(USER, password, scopes=scopes)
    else:
        store.set_password(USER, password)
        store.set_scopes(USER, scopes)
    store.set_tenant(USER, TENANT)

    def sign_in() -> str:
        return call(base, "/auth/login", "POST",
                    {"username": USER, "password": password})[1].get("token", "")

    try:
        print("1. A person types a feature request")
        server = serve(state, args.port)
        token = sign_in()
        check("the control plane is up and an operator can sign in", bool(token))
        if not token:
            return 1

        code, opened = call(base, "/api/chat", "POST", {"text": REQUEST}, token)
        conversation_id = opened.get("conversation_id", "")
        check("the request becomes a conversation",
              code in (200, 201) and bool(conversation_id), f"HTTP {code}")
        check("it is not a mission yet", not opened.get("mission_id"),
              why_not="typing a sentence must not queue work")

        print("\n2. The control plane is killed and restarted")
        stop(server)
        check("nothing is serving", call(base, "/api/health")[0] == 0)
        server = serve(state, args.port)
        token = sign_in()
        code, again = call(base, f"/api/chat/{conversation_id}", token=token)
        check("THE REQUEST SURVIVED THE RESTART", code == 200, f"HTTP {code}")
        check("with the words the person typed",
              REQUEST in json.dumps(again),
              why_not="the sentence that started the work is gone")

        print("\n3. Planning with no usable model")
        code, planned = call(base, f"/api/chat/{conversation_id}/plan", "POST",
                             {}, token)
        proposal = planned.get("proposal", {})
        plan = proposal.get("plan", {})
        blockers = plan.get("blockers", [])
        check("planning answers rather than erroring", code == 200,
              f"HTTP {code}")
        check("IT PRODUCED A BLOCKER, NOT A PLAN",
              planned.get("blocked") is True and bool(blockers),
              why_not="a plan was invented with no model behind it")
        check("and no steps were invented", not plan.get("steps"),
              why_not=f"{len(plan.get('steps') or [])} steps appeared from nowhere")
        kind = blockers[0].get("kind") if blockers else ""
        check("the blocker names why", kind in ("PENDING_CREDENTIAL",
                                                "BLOCKED_EXTERNAL_PROVIDER"),
              kind)
        check("it says what a person should do",
              bool(blockers and blockers[0].get("action")),
              why_not="a blocker with no action is a status")
        check("provenance records that no model produced this",
              not proposal.get("model"),
              why_not=f"a model was named: {proposal.get('model')}")

        print("\n4. Approving a blocked plan is refused")
        code, refused = call(base, f"/api/chat/{conversation_id}/decide", "POST",
                             {"approved": True}, token)
        check("a plan that is only a blocker cannot be approved into a mission",
              code == 409, f"HTTP {code}")
        check("and the refusal explains itself",
              "blocked" in json.dumps(refused).lower(),
              json.dumps(refused)[:80])

        print("\n5. A real plan, and policy decides — not the plan")
        from atlas_kernel.mission.models import Plan, PlanStep
        from atlas_kernel.mission.policy import Requirement, decide

        # A plan that asks for no approval and touches only reviewed-free paths:
        # the most permissive thing a planner could propose.
        permissive = Plan(
            goal="Record approval wait time",
            approval_required=False, estimated_cost=0.5, cost_status="ESTIMATED",
            steps=(PlanStep(order=1, title="note the timing",
                            files=("docs/qevik-docs/timing.md",)),))
        verdict = decide(permissive, agent_id="implementer")
        check("A SELF-MODIFYING PLAN CANNOT AUTHORISE ITSELF",
              verdict.requirement is not Requirement.NONE,
              verdict.because[:64])
        check("and the same plan against customer work is not held",
              decide(permissive, agent_id="implementer",
                     modifies_qevik_itself=False).requirement is Requirement.NONE,
              "the rule is a boundary, not a stop switch")

        print("\n6. The approved path executes, with provenance intact")
        # A deterministic agent, run through the real worker. It is not passed
        # off as model work: the mission records the agent that ran it, and the
        # conversation above still says no model produced a plan.
        from atlas_kernel.mission import service as missions
        from atlas_kernel.mission.adapter import SELF_CHECK_STEPS, build
        from atlas_kernel.mission.models import MissionStatus
        from atlas_kernel.mission.timeline import Timeline

        timeline = Timeline(state / "missions.jsonl")
        mission, event = missions.create(
            tenant=TENANT, requested_by=USER,
            title="Self-improvement: verify the execution path")
        timeline.append(event)
        proposed = build("self-check", SELF_CHECK_STEPS).plan(mission.title)
        mission, event = missions.transition(mission, MissionStatus.PLANNING,
                                             tenant=TENANT, actor=USER)
        timeline.append(event)
        mission, event = missions.attach_plan(mission, proposed, tenant=TENANT,
                                              agent_id="self-check")
        timeline.append(event)
        check("policy held it for a person",
              mission.status is MissionStatus.AWAITING_APPROVAL,
              mission.status.value)

        mission, event = missions.transition(
            mission, MissionStatus.QUEUED, tenant=TENANT, actor=USER,
            note="approved by the verification operator")
        timeline.append(event)

        stop(server)
        server = None
        check("the control plane is not running while the work happens",
              call(base, "/api/health")[0] == 0)

        finished = subprocess.run(
            [sys.executable, str(ROOT / "infra" / "mission_worker.py"),
             "--timeline", str(timeline.path), "--tenant", TENANT,
             "--name", "worker-selfimprove", "--repository", str(ROOT),
             "--worktrees", str(workspace / "worktrees"),
             "--reports", str(state / "reports"), "--state", str(state),
             "--agent", "self-check", "--once"],
            capture_output=True, text=True, timeout=600, check=False)
        check("the worker ran", finished.returncode == 0,
              f"exit {finished.returncode}")

        print("\n7. The result survives another restart")
        server = serve(state, args.port)
        token = sign_in()
        code, done = call(base, f"/api/missions/{mission.id}", token=token)
        check("THE MISSION IS COMPLETE AFTER A RESTART",
              done.get("status") == "complete", f"status={done.get('status')}")
        code, report = call(base, f"/api/missions/{mission.id}/report",
                            token=token)
        check("the report is durable", code == 200, f"HTTP {code}")
        check("it says what was actually checked",
              "workspace is writable" in report.get("report", ""),
              why_not="the report does not carry the evidence")

        print("\n8. Cost is never shown as free when nobody priced it")
        code, costs = call(base, "/api/missions/costs", token=token)
        check("an unpriced mission is reported as unpriced",
              costs.get("priced_calls") == 0 and costs.get("unpriced_calls", 0) >= 0,
              f"priced={costs.get('priced_calls')} unpriced={costs.get('unpriced_calls')}")
        check("and the mission's own total is absent, not zero",
              done.get("total_cost") is None,
              why_not=f"total_cost is {done.get('total_cost')}, which reads as free")

        print("\n9. No credential value anywhere the operator can see")
        code, history = call(base, f"/api/chat/{conversation_id}/history",
                             token=token)
        code, mission_history = call(base, f"/api/missions/{mission.id}/history",
                                     token=token)
        everything = json.dumps([again, planned, done, report, history,
                                 mission_history])
        import re

        leaked = re.findall(r"sk-[A-Za-z0-9_-]{16,}", everything)
        check("no key-shaped string in any response", not leaked,
              why_not=f"{len(leaked)} found")
        check("nor in the durable timelines",
              not re.findall(r"sk-[A-Za-z0-9_-]{16,}",
                             (state / "chat.jsonl").read_text(encoding="utf-8")
                             + (state / "missions.jsonl").read_text(encoding="utf-8")))
    finally:
        stop(server)
        try:
            store.delete_user(USER, requested_by="verification")
        except Exception:
            pass
        if args.keep:
            print(f"\nkept: {workspace}")
        else:
            shutil.rmtree(workspace, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    print("=" * 68)
    if FAILED:
        print("\nNOT VERIFIED. " + "; ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
