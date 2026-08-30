"""A Qevik mission worker announcing the machine it runs on. Nothing more.

The milestone this proves: the existing `atlas_kernel/cluster` registry and
heartbeat become Qevik's node substrate, and mission behaviour is untouched.

    python3 infra/verify_node_registration.py
"""

from __future__ import annotations

import ast
import importlib.util
import socket
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.cluster.models import HeartbeatReport, WorkerState  # noqa: E402
from atlas_kernel.db import SessionLocal, init_db  # noqa: E402
from atlas_kernel.fabric.agents import Registry as AgentRegistry  # noqa: E402
from atlas_kernel.fabric.tools import for_agent  # noqa: E402

spec = importlib.util.spec_from_file_location("mw", ROOT / "infra" / "mission_worker.py")
mw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mw)

PASSED: list[str] = []
FAILED: list[str] = []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


init_db()

print("\n-- nothing was duplicated --------------------------------------------")
source = (ROOT / "infra" / "mission_worker.py").read_text()
tree = ast.parse(source)
names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
for forbidden, why in (("WorkerRegistry", "a second registry"),
                       ("HeartbeatService", "a second heartbeat"),
                       ("LeaseManager", "a second lease manager"),
                       ("Dispatcher", "a second dispatcher")):
    check(f"the worker defines no {why}", forbidden not in names,
          "" if forbidden not in names else f"class {forbidden} is defined here")

check("NEGATIVE CONTROL: cluster's dispatcher is not used",
      "dispatcher" not in source and "Dispatcher" not in source,
      "dispatch stays with fabric.scheduler")
check("NEGATIVE CONTROL: ExecutionLease is not used",
      "ExecutionLease" not in source and "LeaseManager" not in source,
      "claims are ownership; leases are capacity")
check("it imports the registry that already exists",
      "from atlas_kernel.cluster.worker_registry import WorkerRegistry" in source)
check("...and the heartbeat that already exists",
      "from atlas_kernel.cluster.heartbeat_service import HeartbeatService" in source)

print("\n-- capabilities are derived, not listed -------------------------------")
derived = mw._capabilities_for("research")
expected = sorted(t.id for t in for_agent(AgentRegistry().get("researcher")))
check("research capabilities equal its agent's declared tools",
      derived == expected, str(derived))
for role in ("delivery", "publish", "self-check"):
    agent = AgentRegistry().get(mw.REGISTERED_AS[role])
    check(f"...and {role}'s do too",
          mw._capabilities_for(role) == sorted(t.id for t in for_agent(agent)),
          str(mw._capabilities_for(role)))
check("an unknown role advertises nothing rather than guessing",
      mw._capabilities_for("not-a-role") == [])

body = ast.unparse(next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef)
                        and n.name == "_capabilities_for"))
for tool in ("http-fetch", "site-publish", "website-generator", "filesystem"):
    check(f"NEGATIVE CONTROL: {tool!r} is not hard-coded in the derivation",
          f"'{tool}'" not in body and f'"{tool}"' not in body,
          "a second list is the drift this exists to avoid")

print("\n-- the probe reports what is there, and nothing else -------------------")
resources = mw._probe_resources()
check("cpu cores are real", resources.cpu_cores > 0, str(resources.cpu_cores))
check("ram is real", resources.ram_gb > 0, f"{resources.ram_gb} GB")
import shutil  # noqa: E402

if shutil.which("nvidia-smi"):
    check("a machine with nvidia-smi reports a gpu", resources.gpu is not None,
          str(resources.gpu))
else:
    check("a machine with no nvidia-smi reports gpu=None",
          resources.gpu is None and resources.vram_gb == 0,
          "absent, never guessed")

print("\n-- one identity per worker process ------------------------------------")
ROLES = (("worker", "llm"), ("worker-research", "research"),
         ("worker-delivery", "delivery"), ("worker-publish", "publish"))
ids = {name: mw._register_node(name, role) for name, role in ROLES}
for name, worker_id in ids.items():
    check(f"{name} registered", bool(worker_id), worker_id)
check("four processes on one host are four identities",
      len(set(ids.values())) == 4, str(len(set(ids.values()))))
check("...and none of them is worker-local",
      "worker-local" not in ids.values(),
      "the in-process id is excluded from stale detection")
check("...each named <hostname>:<worker-name>",
      all(v == f"{socket.gethostname()}:{k}" for k, v in ids.items()))

repeat = {name: mw._register_node(name, role) for name, role in ROLES}
check("RESTART: every identity is stable", repeat == ids,
      "idempotent on the composite, so a restart keeps its history")

print("\n-- each advertises only its own capabilities ---------------------------")
with SessionLocal() as session:
    rows = {r["id"]: r for r in session.execute(text(
        "SELECT id, capabilities, resources, tags FROM atlas_workers "
        "WHERE id = ANY(:ids)"), {"ids": list(ids.values())}).mappings()}
for name, role in ROLES:
    agent = AgentRegistry().get(mw.REGISTERED_AS[role])
    expected = sorted(t.id for t in for_agent(agent))
    got = sorted(rows[ids[name]]["capabilities"])
    check(f"{name} advertises exactly {expected}", got == expected, str(got))
everything = {c for r in rows.values() for c in r["capabilities"]}
check("NEGATIVE CONTROL: no single worker claims them all",
      not any(sorted(r["capabilities"]) == sorted(everything)
              for r in rows.values()),
      f"the union is {sorted(everything)} and nobody advertises it")
check("each row records the machine it is on",
      all(f"machine:{socket.gethostname()}" in r["tags"] for r in rows.values()))
check("...and real resources", all('"cpu_cores": 0' not in str(r["resources"])
                                   for r in rows.values()))

node_id = ids["worker-research"]

print("\n-- heartbeat is independent of mission activity ------------------------")
registry, heartbeats = mw._node_services()
before = registry.get(node_id).last_heartbeat_at
time.sleep(1.1)
mw._heartbeat(node_id)
after = registry.get(node_id).last_heartbeat_at
check("a heartbeat with no mission running still advances it", after > before,
      f"{before} -> {after}")
check("...and the timeout is the machine's, not the mission's",
      heartbeats.timeout_seconds == 90,
      "90s liveness vs claim staleness — different questions")

from atlas_kernel.mission.service import CLAIM_TIMEOUT  # noqa: E402

check("NEGATIVE CONTROL: the two timeouts are different numbers",
      int(CLAIM_TIMEOUT.total_seconds()) != heartbeats.timeout_seconds,
      f"claim {int(CLAIM_TIMEOUT.total_seconds())}s vs heartbeat "
      f"{heartbeats.timeout_seconds}s")

print("\n-- killing one worker makes only that one stale ------------------------")
from atlas_kernel.mission.claims import LocalClaims  # noqa: E402

claims = LocalClaims()
claims.acquire("mission-regproof", worker="worker-research")
held = claims.holder("mission-regproof")

for other in ids.values():                    # everyone is alive right now
    mw._heartbeat(other)
with SessionLocal() as session:               # one of them stops reporting
    session.execute(text(
        "UPDATE atlas_workers SET last_heartbeat_at = :old WHERE id = :i"),
        {"old": datetime.now(UTC).replace(year=2020), "i": node_id})
    session.commit()

stale = {w.id for w in heartbeats.stale_workers()}
check("the killed worker is reported stale", node_id in stale, node_id)
check("...and the other three on the same host are not",
      not (set(ids.values()) - {node_id}) & stale,
      f"{sorted(set(ids.values()) & stale)} stale of {len(ids)}")
check("...its mission claim is untouched",
      claims.holder("mission-regproof") == held == "worker-research",
      "liveness of a process is not ownership of work")
heartbeats.detect_timeouts()
check("...and marking it offline still does not touch the claim",
      claims.holder("mission-regproof") == "worker-research"
      and registry.get(node_id).status is WorkerState.OFFLINE)
check("...while the others stay online",
      all(registry.get(i).status is WorkerState.ONLINE
          for i in ids.values() if i != node_id))

print("\n-- registration failure does not stop the work --------------------------")
saved = mw._node_services
mw._node_services = lambda: (_ for _ in ()).throw(OSError("registry is away"))
try:
    check("a failed registration returns nothing and raises nothing",
          mw._register_node("worker-regproof", "research") == "")
    mw._heartbeat("worker-regproof")
    check("...and a failed heartbeat is survivable too", True,
          "the ledger, claims and missions do not depend on it")
finally:
    mw._node_services = saved

# Only the identities this harness made, and never `worker-local`. An earlier
# version of this file registered as the in-process local worker and deleted it
# on the way out, which broke `test_cluster` — its `_reset_cluster` pauses that
# row and expects it to exist. Identity model (b) means this cannot recur; the
# guard says so rather than relying on it.
mine = [i for i in ids.values() if i != "worker-local" and ":" in i]
assert len(mine) == len(ids), "refusing to remove a row this harness did not make"
with SessionLocal() as session:
    session.execute(text("DELETE FROM atlas_worker_heartbeats "
                         "WHERE worker_id = ANY(:ids)"), {"ids": mine})
    session.execute(text("DELETE FROM atlas_workers WHERE id = ANY(:ids)"),
                    {"ids": mine})
    session.commit()

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
for n in FAILED:
    print(f"  FAILED  {n}")
sys.exit(1 if FAILED else 0)
