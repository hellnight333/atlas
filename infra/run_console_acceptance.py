"""The control panel, exercised against a real server over real HTTP.

Not a TestClient. `uvicorn` is started in a separate process, requests go over a
socket, and the server is killed and restarted in the middle — because the claim
being tested is that a mission survives the browser going away, and a TestClient
shares a process with the thing it is testing, so it cannot distinguish "the
mission persisted" from "the object was still in memory".

What this does, in order:

    1. start the server
    2. fetch the console shell unauthenticated (the login page must load)
    3. confirm every API path refuses without a session
    4. sign in
    5. read the roadmap, credentials, models, actions surfaces
    6. start a conversation, propose a plan, approve it
    7. kill the server            <- the browser going away
    8. run the worker as its own process
    9. start a *new* server
   10. confirm the mission, its history and its report are all still there

Step 7 is the point. Everything before it is setup.

    python3 infra/run_console_acceptance.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

PORT = int(os.environ.get("QEVIK_ACCEPTANCE_PORT", "8977"))
BASE = f"http://127.0.0.1:{PORT}"
TENANT = "tenant-acceptance"
OPERATOR, PASSWORD = "acceptance", "acceptance-only-not-a-real-password"

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{f'  — {detail}' if detail else ''}")
    return ok


def call(path: str, *, token: str = "", method: str = "GET",
         body: dict | None = None) -> tuple[int, dict | str]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8", "replace")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, raw
    except urllib.error.URLError as unreachable:
        return 0, str(unreachable)


def serve(workspace: Path) -> subprocess.Popen:  # noqa: D401
    """A real uvicorn, in its own process."""
    environment = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "packages" / "kernel"),
        "QEVIK_ACCEPTANCE_STATE": str(workspace),
        # A master key so the vault is unsealed for the credential surface. Test
        # only, and it never leaves this process tree.
        "QEVIK_VAULT_MASTER_KEY": "acceptance-only-master-key",
        # Its own database, in the workspace. Without this `AuthStore()` reaches
        # for a local Postgres, and an acceptance run must not depend on — or
        # write to — whatever database happens to be on the machine.
        "ATLAS_DATABASE_URL": f"sqlite+pysqlite:///{workspace / 'acceptance.db'}",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--host", "127.0.0.1", "--port",
         str(PORT), "--log-level", "warning",
         "--factory", "acceptance_app:build"],
        cwd=str(ROOT / "infra"), env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    for _ in range(60):
        # `/health`, not `/api/health`: liveness is public, deployment
        # posture is not.
        status, _body = call("/health")
        if status == 200:
            return process
        if process.poll() is not None:
            raise RuntimeError(
                "the server exited: "
                + (process.stderr.read().decode() if process.stderr else ""))
        time.sleep(0.5)
    raise RuntimeError("the server never became ready")


def stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:        # pragma: no cover - defensive
        process.kill()


def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="qevik-acceptance-"))
    repository = workspace / "repo"
    repository.mkdir()
    for command in (["git", "init", "-q", "-b", "main"],
                    ["git", "config", "user.email", "a@b.c"],
                    ["git", "config", "user.name", "acceptance"]):
        subprocess.run(command, cwd=repository, capture_output=True, check=True)
    (repository / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repository, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repository,
                   capture_output=True, check=True)

    print("=" * 74)
    print("CONTROL PANEL ACCEPTANCE — real server, real HTTP, real restart")
    print("=" * 74)
    print(f"  workspace {workspace}")

    server = serve(workspace)
    token = ""
    conversation = mission = ""
    try:
        # -------------------------------------------------- 1. the shell loads
        print("\n1. The console loads before anybody signs in")
        status, shell = call("/")
        check("the shell is served", status == 200 and "Qevik Control" in str(shell))
        check("a deep link serves the shell too", call("/missions")[0] == 200)

        # -------------------------------------------- 2. the API refuses first
        print("\n2. Every API surface refuses without a session")
        for path in ("/api/missions", "/api/chat", "/api/credentials",
                     "/api/models", "/api/customer/actions"):
            code, _ = call(path)
            check(f"{path} refuses", code == 401, f"got {code}")

        # ------------------------------------------------------- 3. signing in
        print("\n3. Sign in")
        status, body = call("/auth/login", method="POST",
                            body={"username": OPERATOR, "password": PASSWORD})
        token = (body or {}).get("token", "") if isinstance(body, dict) else ""
        check("a session token is issued", status == 200 and bool(token),
              f"status {status}")
        if not token:
            raise RuntimeError(f"cannot continue without a session: {body}")

        # ---------------------------------------------------- 4. the surfaces
        print("\n4. The surfaces answer")
        for label, path in (("credentials", "/api/credentials"),
                            ("models", "/api/models"),
                            ("model selection", "/api/models/selection"),
                            ("human actions", "/api/missions/actions"),
                            ("blockers", "/api/missions/blockers"),
                            ("costs", "/api/missions/costs"),
                            ("missions", "/api/missions"),
                            ("chat", "/api/chat")):
            code, _ = call(path, token=token)
            check(f"{label} answers", code == 200, f"got {code}")

        status, credentials = call("/api/credentials", token=token)
        rows = credentials.get("credentials", []) if isinstance(credentials, dict) else []
        check("every integration is listed", len(rows) >= 16, f"{len(rows)} listed")
        check("no credential value is returned",
              all("secret" not in json.dumps(row).lower() or not row.get("secret")
                  for row in rows))

        # ------------------------------------------- 5. chat produces a plan
        print("\n5. Chat → plan → approval")
        status, made = call("/api/chat", token=token, method="POST",
                            body={"text": "Improve the Qevik website."})
        conversation = made.get("conversation_id", "") if isinstance(made, dict) else ""
        check("a conversation is created", status == 201 and bool(conversation))

        status, proposed = call(f"/api/chat/{conversation}/plan", token=token,
                                method="POST")
        blocked = proposed.get("blocked") if isinstance(proposed, dict) else None
        check("a plan is proposed", status == 200)
        # With no model credential the planner refuses and names it, which is
        # the correct behaviour and not a failure of the console.
        check("with no model, the plan is a blocker rather than an invention",
              blocked is True,
              "a template plan here would be the dangerous answer")

        status, refused = call(f"/api/chat/{conversation}/decide", token=token,
                               method="POST", body={"approved": True})
        check("a blocked plan cannot be approved into a mission", status == 409,
              f"got {status}")

        # A plan the console can approve, attached the way a configured planner
        # would attach it. The link under test is approval -> mission -> worker.
        from atlas_kernel.chat import service as chat_service
        from atlas_kernel.mission.models import Plan, PlanStep

        events = json.loads((workspace / "chat.json").read_text(encoding="utf-8")) \
            if (workspace / "chat.json").exists() else []
        current = chat_service.rehydrate(
            next(c for c in chat_service.fold(events, tenant=TENANT)
                 if c["conversation_id"] == conversation), tenant=TENANT)
        _updated, event = chat_service.plan_for(
            current, Plan(goal="Improve the Qevik website",
                          approval_required=True,
                          steps=(PlanStep(order=1, title="Write the page",
                                          files=("improvement.md",)),)),
            tenant=TENANT, provider="acceptance", model="acceptance-model")
        events.append(json.loads(json.dumps({
            "kind": event.kind, "factory": event.factory, "actor": event.actor,
            "detail": event.detail}, default=str)))
        (workspace / "chat.json").write_text(json.dumps(events, default=str),
                                             encoding="utf-8")

        status, approved = call(f"/api/chat/{conversation}/decide", token=token,
                                method="POST", body={"approved": True})
        mission = approved.get("mission_id", "") if isinstance(approved, dict) else ""
        check("approving queues a mission", status == 200 and bool(mission),
              f"status {status}")
        check("the mission is queued, not running",
              isinstance(approved, dict) and approved.get("mission_status") == "queued")

        # ------------------------------------------------ 6. the browser leaves
        print("\n6. The server is killed — the browser going away")
        stop(server)
        server = None
        code, _ = call("/health")
        check("nothing is serving", code == 0, f"got {code}")

        # -------------------------------------- 7. the worker runs regardless
        print("\n7. The worker runs in its own process, with nothing serving")
        finished = subprocess.run(
            [sys.executable, str(ROOT / "infra" / "mission_worker.py"),
             "--timeline", str(workspace / "missions.jsonl"),
             "--tenant", TENANT, "--name", "worker-acceptance",
             "--repository", str(repository),
             "--worktrees", str(workspace / "worktrees"),
             "--vault", str(workspace / "worker-vault"),
             "--agent", "fake", "--once"],
            capture_output=True, text=True, timeout=180, check=False)
        check("the worker completed", finished.returncode == 0,
              finished.stderr[-200:] if finished.returncode else "")

        # ------------------------------------------- 8. a new server sees it
        print("\n8. A new server — reopening the console")
        server = serve(workspace)
        status, body = call("/auth/login", method="POST",
                            body={"username": OPERATOR, "password": PASSWORD})
        token = (body or {}).get("token", "") if isinstance(body, dict) else ""

        status, found = call(f"/api/missions/{mission}", token=token)
        state = found.get("status") if isinstance(found, dict) else None
        check("the mission survived the restart", status == 200)
        check("it ran to completion while nothing served HTTP",
              state == "complete", f"status is {state}")
        check("it committed", bool(found.get("commits")) if isinstance(found, dict) else False)

        status, history = call(f"/api/missions/{mission}/history", token=token)
        statuses = [h["status"] for h in history.get("history", [])] \
            if isinstance(history, dict) else []
        check("the whole lifecycle is on the record",
              statuses[:1] == ["draft"] and statuses[-1:] == ["complete"]
              and "processing" in statuses and "committing" in statuses,
              " → ".join(statuses))

        status, report = call(f"/api/missions/{mission}/report", token=token)
        check("a durable report exists", status == 200 and
              isinstance(report, dict) and bool(report.get("report")),
              f"status {status}")

        status, conversation_now = call(f"/api/chat/{conversation}", token=token)
        check("the conversation still references the mission",
              isinstance(conversation_now, dict)
              and conversation_now.get("mission_id") == mission)
        check("what the person typed is unchanged",
              isinstance(conversation_now, dict) and any(
                  "Improve the Qevik website." in m["text"]
                  for m in conversation_now.get("messages", [])))
    finally:
        if server is not None:
            stop(server)

    print()
    print("=" * 74)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for name in FAILED:
            print(f"    FAILED: {name}")
    print("=" * 74)

    (ROOT / "docs/qevik-docs/autonomous/reports/console_acceptance.json").write_text(
        json.dumps({"passed": PASSED, "failed": FAILED,
                    "mission_id": mission, "conversation_id": conversation},
                   indent=2) + "\n", encoding="utf-8")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
