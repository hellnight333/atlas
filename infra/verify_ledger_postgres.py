"""The mission ledger, reachable from a process that shares no filesystem.

The milestone this proves: work Qevik has to do is visible to a machine other
than the one that recorded it. Nothing else — no node registry, no capability
matching, no dispatch changes.

    python3 infra/verify_ledger_postgres.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal, init_db  # noqa: E402
from atlas_kernel.mission import service  # noqa: E402
from atlas_kernel.mission.models import MissionStatus  # noqa: E402
from atlas_kernel.mission.service import FACTORY, KIND  # noqa: E402
from atlas_kernel.mission.timeline import (  # noqa: E402
    BACKENDS,
    LedgerUnavailable,
    Timeline,
)

TENANT = "tenant-ledger-proof"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


init_db()
work = Path(tempfile.mkdtemp(prefix="qevik-ledger-"))


def wipe():
    """Everything this harness writes, including the other-factory probe.

    Run at the start as well as the end: a crashed run leaves its rows behind,
    and a fixture that collides with them fails for a reason that has nothing to
    do with what is being tested.
    """
    with SessionLocal() as session:
        session.execute(text(
            "DELETE FROM atlas_business_events "
            "WHERE factory = :f AND business_id = :t"),
            {"f": FACTORY, "t": TENANT})
        session.execute(text(
            "DELETE FROM atlas_business_events WHERE id = 'evt-ledgerproof-x'"))
        session.commit()


wipe()

print("\n-- the backend is chosen, never guessed -------------------------------")
check("the default is still the file", Timeline(work / "a.jsonl").backend == "file",
      "a deployment moves deliberately")
check("...and says it is not networked",
      Timeline(work / "a.jsonl").networked is False)
check("postgres reports that it is",
      Timeline(work / "a.jsonl", backend="postgres").networked is True)
try:
    Timeline(work / "a.jsonl", backend="n8n")
    check("an unknown backend is refused", False, "it was accepted")
except ValueError as refused:
    check("an unknown backend is refused", True, str(refused)[:52])
check("there are exactly two", BACKENDS == {"file", "postgres"},
      str(sorted(BACKENDS)))

print("\n-- the same events, in both stores ------------------------------------")
# Built once, written to both, folded from each. The comparison is the point:
# a store that folds differently is a different ledger wearing the same name.
on_disk = Timeline(work / "both.jsonl", backend="file")
in_pg = Timeline(work / "unused.jsonl", backend="postgres")

made = []
for n in range(3):
    mission, event = service.create(
        tenant=TENANT, title=f"ledger proof {n}", requested_by="harness",
        origin_name="none", recipe="execution-canary")
    made.append(mission)
    for sink in (on_disk, in_pg):
        sink.append(event)
    mission, event = service.transition(mission, MissionStatus.PLANNING,
                                        tenant=TENANT, actor="harness")
    for sink in (on_disk, in_pg):
        sink.append(event)

from_file = service.fold(on_disk.read(), tenant=TENANT)
from_pg = service.fold(in_pg.read(), tenant=TENANT)
check("both stores hold the same number of events",
      len(on_disk.read()) == len(in_pg.read()) == 6,
      f"file {len(on_disk.read())}, postgres {len(in_pg.read())}")
check("fold returns the same missions",
      {m["mission_id"] for m in from_file} == {m["mission_id"] for m in from_pg},
      f"{len(from_pg)} mission(s)")
check("BYTE FOR BYTE: every field of every mission is identical",
      json.dumps(sorted(from_file, key=lambda m: m["mission_id"]),
                 sort_keys=True, default=str)
      == json.dumps(sorted(from_pg, key=lambda m: m["mission_id"]),
                    sort_keys=True, default=str),
      "the same fold, from a file and from a database")

print("\n-- it does not read another factory's decisions -----------------------")
with SessionLocal() as session:
    session.execute(text("""
        INSERT INTO atlas_business_events
            (id, business_id, factory, kind, actor, detail, at)
        VALUES ('evt-ledgerproof-x', :t, 'opportunity', 'artefact_reviewed',
                'probe', '{"mission_id": "mission-not-a-mission"}', now())
        ON CONFLICT (id) DO NOTHING
    """), {"t": TENANT})
    session.commit()
check("a decision from another factory is not in the ledger",
      not any(e["kind"] == "artefact_reviewed" for e in in_pg.read()),
      "atlas_business_events is shared; the ledger is one factory of it")
check("...and does not appear as a mission",
      "mission-not-a-mission" not in {m["mission_id"] for m in
                                      service.fold(in_pg.read(), tenant=TENANT)})

print("\n-- no hidden fallback ------------------------------------------------")
# The store is made unreachable directly, rather than through a bad DSN: what is
# being tested is what happens when the session fails, and routing that through
# a driver makes the test about the driver.
import atlas_kernel.db as db  # noqa: E402


class _Unreachable:
    def __enter__(self):
        raise OSError("the database is not there")

    def __exit__(self, *_):
        return False


working = db.SessionLocal
db.SessionLocal = lambda: _Unreachable()
try:
    broken = Timeline(work / "b.jsonl", backend="postgres")
    try:
        broken.read()
        check("an unreachable ledger raises rather than falling back", False,
              "it returned something")
    except LedgerUnavailable as refused:
        check("an unreachable ledger raises rather than falling back", True,
              str(refused)[:52])
    try:
        broken.append({"kind": KIND, "factory": FACTORY, "actor": "x",
                       "business_id": TENANT, "detail": {}})
        check("...and an append does too", False, "it wrote somewhere")
    except LedgerUnavailable:
        check("...and an append does too", True,
              "a silent revert to the file is a split-brain queue")
    check("nothing was written to the file it is not using",
          not (work / "b.jsonl").exists(),
          "a fallback would have left a private history here")
finally:
    db.SessionLocal = working

check("NEGATIVE CONTROL: with the store back, it reads again",
      len(Timeline(work / "c.jsonl", backend="postgres").read()) >= 6,
      "so the refusals above were the outage, not a broken reader")

print("\n-- a second process, sharing no filesystem ----------------------------")
# The whole point of the milestone. The child is given a timeline path that
# **does not exist and never will**; if it can see the work, it saw it through
# the database.
reader = ROOT / ".ledger-reader.py"
reader.write_text(
    "import json, sys\n"
    f"sys.path.insert(0, {str(ROOT / 'packages' / 'kernel')!r})\n"
    "from atlas_kernel.mission import service\n"
    "from atlas_kernel.mission.timeline import Timeline\n"
    "t = Timeline('/nonexistent/never/created.jsonl', backend='postgres')\n"
    f"folded = service.fold(t.read(), tenant={TENANT!r})\n"
    "print(json.dumps(sorted(m['mission_id'] for m in folded)))\n",
    encoding="utf-8")
done = subprocess.run([sys.executable, str(reader)], capture_output=True,
                      text=True, check=False)
reader.unlink(missing_ok=True)
seen = json.loads(done.stdout or "[]") if done.returncode == 0 else []
check("another process sees the work", done.returncode == 0,
      done.stderr.strip()[-120:] if done.returncode else "")
check("...all of it", seen == sorted(m.id for m in made), str(seen))
check("...with no file to read", not Path("/nonexistent/never/created.jsonl").exists(),
      "it came from the database or it did not come at all")

print("\n-- the file is untouched ---------------------------------------------")
before = (work / "both.jsonl").read_bytes()
Timeline(work / "unused.jsonl", backend="postgres").read()
check("reading postgres does not write the file",
      (work / "both.jsonl").read_bytes() == before)
check("...and the postgres timeline created no file",
      not (work / "unused.jsonl").exists(),
      "rollback is pointing back at a file nothing has altered")

wipe()

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
for n in FAILED:
    print(f"  FAILED  {n}")
sys.exit(1 if FAILED else 0)
