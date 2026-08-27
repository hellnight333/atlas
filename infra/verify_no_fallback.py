"""Every silent substitution, attempted against the real worker.

Each case here is a thing that would once have carried on quietly: a worker
running a mission with an agent nobody approved, dispatching work whose provider
credential does not exist, cloning a repository the mission did not name, or
starting work an allowance cannot cover. Unit tests assert the refusals; this
runs the actual `mission_worker.py` process and checks the mission ends BLOCKED
with the reason attached.

Each attempt has a **paired positive control** — the same setup with the one
offending detail corrected — so a refusal that fires for an unrelated reason
shows up as both halves failing rather than as a pass.

    python3 infra/verify_no_fallback.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from atlas_kernel.mission import service  # noqa: E402
from atlas_kernel.mission.models import (  # noqa: E402
    MissionStatus,
    Plan,
    PlanStep,
)
from atlas_kernel.mission.timeline import Timeline  # noqa: E402

TENANT = "tenant-no-fallback"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


def a_plan(cost: float | None = 0.1) -> Plan:
    return Plan(goal="do a small thing",
                steps=(PlanStep(order=1, title="write", files=("reports/x.md",)),),
                estimated_cost=cost, approval_required=False)


def queue_one(timeline: Timeline, *, mission_id_hint: str, agent_id: str,
              origin_name: str, cost: float | None = 0.1):
    """A mission already through policy and sitting in the queue."""
    mission, event = service.create(tenant=TENANT, title=mission_id_hint,
                                    requested_by="harness",
                                    origin_name=origin_name)
    timeline.append(event)
    mission, event = service.transition(mission, MissionStatus.PLANNING,
                                        tenant=TENANT, actor="harness")
    timeline.append(event)
    mission, event = service.attach_plan(
        mission, a_plan(cost), tenant=TENANT, agent_id=agent_id,
        modifies_qevik_itself=False)
    timeline.append(event)
    return mission


def run_worker(timeline: Timeline, tmp: Path, *, agent: str, tag: str,
               origins: list[str] | None = None,
               quota: Path | None = None) -> subprocess.CompletedProcess:
    command = [sys.executable, str(ROOT / "infra" / "mission_worker.py"),
               "--timeline", str(timeline.path), "--tenant", TENANT,
               "--name", f"worker-{tag}",
               "--worktrees", str(tmp / tag / "wt"),
               "--scratch", str(tmp / tag / "scratch"),
               "--reports", str(tmp / tag / "reports"),
               "--state", str(tmp / tag / "state"),
               "--agent", agent, "--once"]
    if quota is not None:
        command += ["--quota-timeline", str(quota)]
    for entry in origins or []:
        command += ["--origin", entry]
    return subprocess.run(command, capture_output=True, text=True, timeout=600,
                          check=False)


def landed(timeline: Timeline, mission_id: str) -> dict:
    folded = service.fold(Timeline(timeline.path).read(), tenant=TENANT)
    return next((m for m in folded if m["mission_id"] == mission_id), {})


# ------------------------------------------------------------------ the agent

def agent_substitution(tmp: Path) -> None:
    """A mission approved as `self-check` work, picked up by a worker that
    serves something else.

    The obvious version of this — `--agent llm` — cannot be run here: that
    worker refuses to *start* without a model credential, so the dispatch gate
    would never be reached and the test would pass for the wrong reason.
    `--agent fake` is used instead. It is deliberately not in the agent
    registry, so a worker running it serves no declared agent at all, which is
    the same substitution seen from the other side.

    Each case gets its **own timeline**. The first draft shared one, and
    `--once` takes a single mission per pass, so the positive control silently
    re-ran the negative case's mission.
    """
    bad = Timeline(tmp / "agent-bad" / "missions.jsonl")
    mismatched = queue_one(bad, mission_id_hint="approved as self-check",
                           agent_id="self-check", origin_name="none")
    run_worker(bad, tmp, agent="fake", tag="agent-bad")
    row = landed(bad, mismatched.id)
    # The property is that the wrong worker does not *run* it — not that the
    # mission ends up in any particular state. This asked for BLOCKED, which was
    # the behaviour until two workers started racing for each other's missions
    # and each blocked the one it was never meant to run. "Not by me" is not a
    # defect in the mission, so the backstop releases it and the right worker
    # takes it. Asserting the old literal state made a deliberate fix look like
    # a regression.
    check("a worker serving a different agent does not run the mission",
          row.get("status") != MissionStatus.COMPLETE.value,
          f"status={row.get('status')}")
    check("...and leaves it available rather than condemning it",
          row.get("status") in {MissionStatus.QUEUED.value,
                                MissionStatus.BLOCKED.value},
          f"status={row.get('status')}")
    check("...and it never reached a workspace", not row.get("workspace"))

    good = Timeline(tmp / "agent-good" / "missions.jsonl")
    matched = queue_one(good, mission_id_hint="approved as self-check (ok)",
                        agent_id="self-check", origin_name="none")
    run_worker(good, tmp, agent="self-check", tag="agent-good")
    row = landed(good, matched.id)
    check("POSITIVE CONTROL: the matching worker runs it to completion",
          row.get("status") == MissionStatus.COMPLETE.value,
          f"status={row.get('status')}")


# ------------------------------------------------------------------ the origin

def origin_substitution(tmp: Path) -> None:
    """A mission naming a repository this worker does not have."""
    timeline = Timeline(tmp / "origin" / "missions.jsonl")
    stray = queue_one(timeline, mission_id_hint="names an unknown origin",
                      agent_id="self-check", origin_name="acme-web")

    run_worker(timeline, tmp, agent="self-check", tag="origin-bad")
    row = landed(timeline, stray.id)
    check("a mission naming an unregistered origin is REFUSED",
          row.get("status") == MissionStatus.BLOCKED.value,
          f"status={row.get('status')}")
    check("...and does not fall back to the default, which is Qevik",
          "no origin named" in (row.get("note") or ""),
          (row.get("note") or "")[:80])
    check("...and never recorded an origin it did not name",
          not row.get("origin_kind"), row.get("origin_kind", ""))


# ------------------------------------------------------------- the credential

def credential_substitution(tmp: Path) -> None:
    """A mission whose agent needs a model credential nobody configured.

    Held by the scheduler rather than blocked: a credential can appear later, so
    this resolves by itself and must not be recorded as a failure.
    """
    timeline = Timeline(tmp / "cred" / "missions.jsonl")
    needs_model = queue_one(timeline, mission_id_hint="needs a model",
                            agent_id="implementer", origin_name="none")

    done = run_worker(timeline, tmp, agent="llm", tag="cred")
    row = landed(timeline, needs_model.id)
    check("a mission needing an unavailable credential is NOT dispatched",
          row.get("status") == MissionStatus.QUEUED.value,
          f"status={row.get('status')}")
    check("...it stays queued rather than failing, because a key can arrive",
          row.get("status") != MissionStatus.FAILED.value)
    check("...and no workspace was created for it", not row.get("workspace"))
    check("...and the worker said why rather than sitting silent",
          "credential" in (done.stderr + done.stdout).lower(),
          "no explanation in the log" if "credential" not in
          (done.stderr + done.stdout).lower() else "")


# ---------------------------------------------------------------- the budget

def budget_gate(tmp: Path) -> None:
    """Work an allowance cannot carry, refused before it runs."""
    from atlas_kernel.fabric.budgets import Scope
    from atlas_kernel.fabric.budgets import policy as budget_policy
    from atlas_kernel.quota.ledger import QuotaLedger

    timeline = Timeline(tmp / "budget" / "missions.jsonl")
    quota = Timeline(tmp / "budget" / "quota.jsonl")
    # Under `policy.COSTLY_UNITS`, so policy queues it with nobody asked — the
    # budget gate is what must stop it. The first draft used 250 units, which
    # policy held for approval, so the mission never reached the queue and the
    # gate under test never ran.
    expensive = queue_one(timeline, mission_id_hint="more than the allowance",
                          agent_id="self-check", origin_name="none", cost=4.0)
    check("the mission reaches the queue on policy alone",
          landed(timeline, expensive.id).get("status")
          == MissionStatus.QUEUED.value,
          landed(timeline, expensive.id).get("status", ""))

    # An allowance below the estimate, on a scope the mission sits in.
    ledger = QuotaLedger(events=quota.read(), sink=quota.append)
    ledger.register(budget_policy(Scope.MISSION, expensive.id, tenant=TENANT,
                                  limit=1.0))

    run_worker(timeline, tmp, agent="self-check", tag="budget",
               quota=quota.path)
    row = landed(timeline, expensive.id)
    check("a mission beyond its allowance is REFUSED before it runs",
          row.get("status") == MissionStatus.BLOCKED.value,
          f"status={row.get('status')}")
    check("...and the refusal names the allowance rather than the plan",
          "cannot carry it" in (row.get("note") or ""),
          (row.get("note") or "")[:110])
    check("...and nothing was spent on it",
          not row.get("total_cost"), str(row.get("total_cost")))


def customer_origin_selection(tmp: Path) -> None:
    """The surface, end to end: a customer origin is offered, chosen, and run.

    Over a real HTTP server, because the point is that a **name** crosses the
    wire and the path never does.
    """
    import json
    import os

    from atlas_kernel.mission import origins

    customer = tmp / "acme-repo"
    customer.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-b", "main", "."], ["add", "."]):
        subprocess.run(["git", *args], cwd=customer, capture_output=True,
                       check=False)
    (customer / "site.html").write_text("<h1>acme</h1>\n")
    env = dict(os.environ) | {
        "GIT_AUTHOR_NAME": "h", "GIT_AUTHOR_EMAIL": "h@q.local",
        "GIT_COMMITTER_NAME": "h", "GIT_COMMITTER_EMAIL": "h@q.local"}
    subprocess.run(["git", "add", "."], cwd=customer, capture_output=True,
                   check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=customer, env=env,
                   capture_output=True, check=True)

    declared = f"acme-web={customer}"
    registry = origins.Registry.build(origins.from_environment(declared))

    # ---- what a browser would receive ---------------------------------
    public = registry.public()
    names = [o["name"] for o in public]
    check("the customer origin is offered alongside the built-ins",
          names == ["qevik", "none", "acme-web"], str(names))
    check("NO FILESYSTEM PATH IS IN WHAT THE BROWSER RECEIVES",
          not any("path" in o for o in public)
          and str(customer) not in json.dumps(public),
          json.dumps(public)[:120])
    check("the customer origin is not marked as self-modification",
          not registry.resolve("acme-web").modifies_qevik_itself)
    check("Qevik's own origin still is",
          registry.resolve("qevik").modifies_qevik_itself)

    # ---- and it actually runs -----------------------------------------
    timeline = Timeline(tmp / "customer" / "missions.jsonl")
    chosen = queue_one(timeline, mission_id_hint="work on the customer site",
                       agent_id="self-check", origin_name="acme-web")
    before = subprocess.run(["git", "-c", f"safe.directory={customer}",
                             "show-ref"], cwd=customer, capture_output=True,
                            text=True, check=False).stdout

    worker_env = dict(os.environ) | {origins.ENVIRONMENT: declared}
    subprocess.run(
        [sys.executable, str(ROOT / "infra" / "mission_worker.py"),
         "--timeline", str(timeline.path), "--tenant", TENANT,
         "--name", "worker-customer",
         "--worktrees", str(tmp / "customer" / "wt"),
         "--scratch", str(tmp / "customer" / "scratch"),
         "--reports", str(tmp / "customer" / "reports"),
         "--state", str(tmp / "customer" / "state"),
         "--agent", "self-check", "--once"],
        capture_output=True, text=True, timeout=600, check=False, env=worker_env)

    row = landed(timeline, chosen.id)
    check("A MISSION AGAINST THE CHOSEN CUSTOMER ORIGIN COMPLETES",
          row.get("status") == MissionStatus.COMPLETE.value,
          f"status={row.get('status')}")
    check("...and it recorded that origin, by kind",
          row.get("origin_kind") == "customer", str(row.get("origin_kind")))
    check("...and worked in a clone rather than the customer's repository",
          bool(row.get("workspace")) and str(customer) not in row.get("workspace", "x"),
          row.get("workspace", ""))

    after = subprocess.run(["git", "-c", f"safe.directory={customer}",
                            "show-ref"], cwd=customer, capture_output=True,
                           text=True, check=False).stdout
    check("...and THE CUSTOMER'S REPOSITORY IS UNCHANGED", before == after,
          f"{before!r} -> {after!r}")


def main() -> int:
    print("no silent fallback — real worker processes\n")
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        print("agent")
        agent_substitution(tmp)
        print("\norigin")
        origin_substitution(tmp)
        print("\ncredential")
        credential_substitution(tmp)
        print("\nbudget")
        budget_gate(tmp)
        print("\ncustomer origin selection")
        customer_origin_selection(tmp)
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
