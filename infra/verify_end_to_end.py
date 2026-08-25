#!/usr/bin/env python3
"""One mission, all the way through, with real processes.

    control plane -> mission -> scheduler -> atomic claim -> worker
    -> agent registry -> adapter -> tool contract -> sandbox
    -> evidence -> report -> complete

Every link is exercised by the thing that actually implements it. The HTTP
surface is a running server, the worker is a separate OS process started with
`subprocess`, the claim is taken against a real PostgreSQL when a DSN is given,
and the restart is a genuine process death rather than a fixture teardown.

The mission is harmless by construction: the `self-check` agent runs three
declared commands inside a discardable git worktree. It calls no provider,
spends nothing, and touches no customer or public site. Its third step *asserts*
the confinement rather than assuming it — it tries to read `/etc/shadow` and the
step passes only if it could not.

    python3 infra/verify_end_to_end.py [--claims-dsn postgresql://...]

Exits non-zero on any failure. Nothing here is skipped quietly.
"""

from __future__ import annotations

import argparse
import json
import os
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

TENANT = "tenant-e2e"
USER = "e2e-operator"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "", *, why_not: str = "") -> bool:
    """`detail` is shown either way; `why_not` only on failure.

    Two parameters because one kept producing lines like
    "PASS  … — the sentence that started the work is gone", where the
    explanation of the failure was printed next to a pass. A reader skimming for
    problems stops trusting the output after seeing that once.
    """
    (PASSED if ok else FAILED).append(name)
    shown = detail if ok else (why_not or detail)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {shown}" if shown else ""))
    return ok


def call(base: str, path: str, method: str = "GET", body: object = None,
         token: str = "") -> tuple[int, dict]:
    req = urllib.request.Request(base + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data, timeout=30) as answer:
            return answer.status, json.loads(answer.read() or b"{}")
    except urllib.error.HTTPError as failed:
        try:
            return failed.code, json.loads(failed.read() or b"{}")
        except Exception:
            return failed.code, {}
    except Exception as failed:
        return 0, {"error": type(failed).__name__}


def serve(state: Path, port: int) -> subprocess.Popen:
    """A real HTTP server in its own process, as the deployment runs it."""
    environment = {
        **os.environ,
        "QEVIK_STATE": str(state),
        "QEVIK_REPOSITORY": str(ROOT),
        "QEVIK_VAULT_MASTER_KEY": "end-to-end-verification-key-not-a-secret",
        "PYTHONPATH": str(ROOT / "packages" / "kernel"),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--factory",
         "atlas_kernel.qevik.app:from_environment",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        time.sleep(0.5)
        if call(base, "/api/health")[0] in (200, 401, 403):
            return process
        if process.poll() is not None:
            raise RuntimeError("the server exited during start-up")
    raise RuntimeError("the server never answered")


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
    parser.add_argument("--claims-dsn", default=os.environ.get("QEVIK_CLAIMS_DSN", ""))
    parser.add_argument("--port", type=int, default=8477)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    workspace = Path(tempfile.mkdtemp(prefix="qevik-e2e-"))
    state = workspace / "state"
    state.mkdir(parents=True)
    # The same directory the server derives from QEVIK_STATE. Passing the
    # worker a different one is exactly the disagreement this found.
    reports = state / "reports"
    reports.mkdir()
    base = f"http://127.0.0.1:{args.port}"
    server: subprocess.Popen | None = None

    from atlas_kernel.auth.models import Scope
    from atlas_kernel.auth.store import AuthStore, init_auth

    init_auth()
    store = AuthStore()
    import secrets

    password = secrets.token_urlsafe(32)      # generated here; never printed
    scopes = frozenset({Scope.READ, Scope.EXECUTE, Scope.ADMIN})
    # Idempotent: a previous run that was interrupted before its cleanup must
    # not stop this one. Re-using the account is fine — the password is new
    # every time and the account is removed at the end either way.
    if store.get_user(USER) is None:
        store.create_user(USER, password, scopes=scopes)
    else:
        store.set_password(USER, password)
        store.set_scopes(USER, scopes)
    store.set_tenant(USER, TENANT)

    try:
        print("1. The control plane, as its own process")
        server = serve(state, args.port)
        code, body = call(base, "/auth/login", "POST",
                          {"username": USER, "password": password})
        token = body.get("token", "")
        check("the control plane is serving and an operator can sign in",
              code == 200 and bool(token), f"HTTP {code}")
        if not token:
            return 1

        code, body = call(base, "/api/health", token=token)
        claiming = body.get("components", {}).get("claiming", {})
        sandbox = body.get("components", {}).get("sandbox", {})
        check("it reports what claiming it has", bool(claiming.get("status")),
              claiming.get("status"))
        check("and whether it can contain a coding agent",
              "confinement" in sandbox, sandbox.get("confinement"))

        print("\n2. Submit a mission through the real API")
        code, mission = call(base, "/api/missions", "POST", {
            "title": "Self-check: prove the execution path end to end",
            "description": "Runs declared verification commands in a "
                           "discardable worktree. No provider, no spend, no "
                           "customer or public site touched.",
        }, token)
        mission_id = mission.get("mission_id", "")
        check("the mission is created", code == 201 and bool(mission_id),
              f"HTTP {code}")
        check("it lands in DRAFT, not queued", mission.get("status") == "draft",
              mission.get("status"))
        if not mission_id:
            return 1

        print("\n3. A registered agent proposes a plan — it does not authorise it")
        code, planned = call(base, f"/api/missions/{mission_id}/plan", "POST",
                             {"agent": "self-check"}, token)
        check("the agent proposed a plan", code == 200, f"HTTP {code}")
        check("proposing does NOT queue it",
              planned.get("status") == "awaiting_approval", planned.get("status"))
        check("the plan names what will run",
              len((planned.get("plan") or {}).get("steps") or []) == 3,
              str(len((planned.get("plan") or {}).get("steps") or [])) + " steps")
        check("and says who proposed it", planned.get("proposed_by") == "self-check")

        code, refused = call(base, f"/api/missions/{mission_id}/plan", "POST",
                             {"agent": "planner"}, token)
        check("a model-backed agent is refused here rather than half-implemented",
              refused.get("detail", "").startswith("planner is"), f"HTTP {code}")

        print("\n4. The scheduler will not dispatch it until a person approves")
        code, plan_view = call(base, "/api/missions/schedule", token=token)
        waiting = [r["mission_id"] for r in plan_view["queues"]["WAITING"]]
        check("it is WAITING on a person, not runnable", mission_id in waiting,
              f"dispatchable={plan_view['dispatchable']}")

        print("\n5. Approve it — the authority is the operator, not the agent")
        code, approved = call(base, f"/api/missions/{mission_id}/approve", "POST",
                              {"note": "approved by the verification operator"},
                              token)
        check("approval queues it", approved.get("status") == "queued",
              approved.get("status"))

        code, plan_view = call(base, "/api/missions/schedule", token=token)
        check("and now the scheduler says it may run",
              plan_view["dispatchable"] == [mission_id],
              str(plan_view["dispatchable"]))
        row = next((r for r in plan_view["queues"]["NOW"]
                    if r["mission_id"] == mission_id), {})
        check("with a reason a person can read", bool(row.get("why")),
              row.get("why"))

        print("\n6. The worker runs it — a separate OS process, with the "
              "control plane killed")
        stop(server)
        server = None
        check("nothing is serving HTTP", call(base, "/api/health")[0] == 0)

        command = [sys.executable, str(ROOT / "infra" / "mission_worker.py"),
                   "--timeline", str(state / "missions.jsonl"),
                   "--tenant", TENANT, "--name", "worker-e2e",
                   "--repository", str(ROOT),
                   "--worktrees", str(workspace / "worktrees"),
                   "--reports", str(reports),
                   "--agent", "self-check", "--once"]
        if args.claims_dsn:
            command += ["--claims-dsn", args.claims_dsn,
                        "--require-atomic-claims"]
        finished = subprocess.run(command, capture_output=True, text=True,
                                  timeout=600, check=False)
        logs = finished.stdout + finished.stderr
        check("the worker ran to completion", finished.returncode == 0,
              f"exit {finished.returncode}")
        atomic = "multi-worker safe" in logs
        if args.claims_dsn:
            check("it used Postgres-backed atomic claims", atomic,
                  "reported" if atomic else "the worker did NOT report atomic "
                  "claiming — it may have fallen back")
        check("it went through the agent registry", "self-check" in logs)
        if "complete" not in logs and "finished as" in logs:
            # The worker's own account of what went wrong. Hiding it and
            # reporting only "not complete" is exactly the unactionable report
            # this project keeps refusing to write.
            print("\n    --- what the worker said ---")
            for line in logs.strip().splitlines()[-14:]:
                print("    " + line)
            print("    ---")

        print("\n7. A new control plane reads the mission back")
        server = serve(state, args.port)
        code, body = call(base, "/auth/login", "POST",
                          {"username": USER, "password": password})
        token = body.get("token", "")
        code, done = call(base, f"/api/missions/{mission_id}", token=token)
        check("THE MISSION IS COMPLETE AFTER A FULL RESTART",
              done.get("status") == "complete", f"status={done.get('status')}")
        check("it recorded a commit", bool(done.get("commits")),
              str(done.get("commits"))[:60])

        code, history = call(base, f"/api/missions/{mission_id}/history",
                             token=token)
        steps = [h.get("status") for h in history.get("history", [])]
        check("the whole lifecycle is on the record",
              {"draft", "planning", "awaiting_approval", "queued", "processing",
               "complete"} <= set(steps), " → ".join(steps))

        print("\n8. The evidence and the report are durable")
        code, report = call(base, f"/api/missions/{mission_id}/report",
                            token=token)
        check("a durable report exists", code == 200, f"HTTP {code}")
        text = report.get("report", "")
        step_by_step = "workspace is writable" in text and "Evidence" in text
        check("it names what was proven, step by step", step_by_step,
              "" if step_by_step else "the report does not carry the agent's "
              "own account of what ran")
        contained = "nothing outside the workspace is reachable" in text
        check("nothing outside the workspace was reachable", contained,
              "" if contained else "the containment assertion is missing")
        check("the report is a real file on disk",
              any(reports.rglob("*.md")), str(list(reports.rglob("*.md"))[:1]))

        print("\n9. The cost is accounted for, or its absence is")
        code, history = call(base, f"/api/missions/{mission_id}/history",
                             token=token)
        notes = " ".join(h.get("note", "") for h in history.get("history", []))
        accounted = "charged" in notes or "cost UNKNOWN" in notes
        check("the mission's cost reached the ledger, or said why it could not",
              accounted,
              "" if accounted else "a mission finished with nothing said about "
              "what it cost")
        check("an unknown cost is never recorded as zero",
              "This is not a zero" in notes or "charged" in notes,
              "" if accounted else "silence reads as free")
        check("the quota timeline is beside the mission timeline",
              (state / "quota.jsonl").exists() or "cost UNKNOWN" in notes,
              why_not="the worker and the control plane must share one balance")

        print("\n10. The conversation that started it survives too")
        code, listing = call(base, "/api/chat", token=token)
        check("the control plane can list conversations", code == 200,
              f"HTTP {code}")
        code, opened = call(base, "/api/chat", "POST",
                            {"text": "Check that this deployment is sound."},
                            token)
        conversation_id = opened.get("conversation_id", "")
        check("a person's message starts a conversation",
              code in (200, 201) and bool(conversation_id), f"HTTP {code}")

        stop(server)
        server = serve(state, args.port)
        code, body = call(base, "/auth/login", "POST",
                          {"username": USER, "password": password})
        token = body.get("token", "")
        code, after = call(base, f"/api/chat/{conversation_id}", token=token)
        check("THE CONVERSATION SURVIVED A RESTART", code == 200,
              f"HTTP {code}")
        said = json.dumps(after)
        check("and still carries what the person typed",
              "Check that this deployment is sound." in said,
              why_not="the sentence that started the work is gone")
        check("the chat timeline is beside the mission timeline",
              (state / "chat.jsonl").exists(),
              why_not="conversations must be as durable as the missions they "
                      "produce")

        print("\n11. Restart again — durability is not a one-off")
        stop(server)
        server = serve(state, args.port)
        code, body = call(base, "/auth/login", "POST",
                          {"username": USER, "password": password})
        code, again = call(base, f"/api/missions/{mission_id}",
                           token=body.get("token", ""))
        check("still complete after a second restart",
              again.get("status") == "complete", again.get("status"))
        check("and still points at its report",
              bool(again.get("report_path")), again.get("report_path"))
    finally:
        stop(server)
        try:
            store.delete_user(USER, requested_by="verification")
        except Exception:
            pass
        if not args.keep:
            shutil.rmtree(workspace, ignore_errors=True)
        else:
            print(f"\nkept: {workspace}")

    print("\n" + "=" * 66)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    print("=" * 66)
    if FAILED:
        print("\nNOT VERIFIED. " + "; ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
