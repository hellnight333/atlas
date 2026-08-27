"""Mission reports, readable by a process that shares no filesystem.

The milestone this proves: a report written by one machine can be read by
another. Nothing else — no node registration, no capability matching.

    python3 infra/verify_reports_postgres.py
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal, init_db  # noqa: E402
from atlas_kernel.mission import reports  # noqa: E402
from atlas_kernel.mission.models import Mission  # noqa: E402

TENANT = "tenant-reports-proof"
OTHER = "tenant-somebody-else"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


init_db()
work = Path(tempfile.mkdtemp(prefix="qevik-reports-"))


def wipe():
    with SessionLocal() as session:
        session.execute(text(
            "DELETE FROM atlas_mission_reports WHERE tenant_id IN (:a, :b)"),
            {"a": TENANT, "b": OTHER})
        session.commit()


wipe()
mission = Mission(id="mission-reportproof01", tenant_id=TENANT,
                  title="report proof")

print("\n-- the store is chosen, never guessed ---------------------------------")
# With the variable *absent*, not merely as the environment happens to be. On
# production the variable is deliberately set, and a check that read the ambient
# value would report the deployment's choice as a broken default.
_ambient = os.environ.pop(reports.ENVIRONMENT, None)
check("the default, with nothing configured, is the file",
      reports.store() == "file", "a deployment moves deliberately")
if _ambient is not None:
    os.environ[reports.ENVIRONMENT] = _ambient
check("...and this deployment has chosen",
      _ambient in (None, "file", "postgres"),
      f"{reports.ENVIRONMENT}={_ambient or '(unset, so file)'}")
os.environ[reports.ENVIRONMENT] = "sqlite-maybe"
try:
    reports.store()
    check("an unknown store is refused", False, "it was accepted")
except ValueError as refused:
    check("an unknown store is refused", True, str(refused)[:52])
os.environ.pop(reports.ENVIRONMENT)
check("there are exactly two", reports.STORES == {"file", "postgres"},
      str(sorted(reports.STORES)))

print("\n-- the file store is untouched ---------------------------------------")
written = reports.write(mission, root=work, attempts=1, detail="on disk")
check("a file is still written when the store is the file", written.is_file(),
      written.name)
on_disk = written.read_text(encoding="utf-8")
check("...and it renders as it always did", on_disk.startswith("# report proof"))

print("\n-- the postgres store writes no file ----------------------------------")
os.environ[reports.ENVIRONMENT] = "postgres"
try:
    fresh = Path(tempfile.mkdtemp(prefix="qevik-nofile-"))
    path = reports.write(mission, root=fresh, attempts=1, detail="on disk")
    check("nothing was written to disk", not any(fresh.rglob("*.md")),
          str(sorted(p.name for p in fresh.rglob('*'))[:3]))
    check("...and the caller still gets a path back", str(path).endswith(".md"),
          str(path))
    stored = reports.latest(mission.id, tenant=TENANT)
    check("the body is byte-for-byte what the file store produced",
          stored["report"] == on_disk,
          f"{len(stored['report'])} vs {len(on_disk)} chars")
    check("...and the recorded byte count is the encoded length",
          stored["bytes"] == len(on_disk.encode("utf-8")), str(stored["bytes"]))

    print("\n-- a large report, because 6.3 MB is the real case -------------------")
    big = Mission(id="mission-reportproof02", tenant_id=TENANT, title="big")
    evidence = "\n".join("x" * 250_000 for _ in range(26))     # ~6.5 MB
    reports.write(big, root=fresh, evidence=evidence, detail="large")
    back = reports.latest(big.id, tenant=TENANT)
    check("a multi-megabyte report round-trips", back["bytes"] > 6_000_000,
          f"{back['bytes']:,} bytes")
    check("...byte for byte",
          hashlib.sha256(back["report"].encode()).hexdigest()
          == hashlib.sha256(reports.render(big, evidence=evidence,
                                           detail="large").encode()).hexdigest())

    print("\n-- insert-only: a re-run appends -------------------------------------")
    before = _count = None
    with SessionLocal() as session:
        before = session.execute(text(
            "SELECT count(*) FROM atlas_mission_reports WHERE mission_id = :m"),
            {"m": mission.id}).scalar()
    reports.write(mission, root=fresh, attempts=2, detail="second attempt")
    with SessionLocal() as session:
        after = session.execute(text(
            "SELECT count(*) FROM atlas_mission_reports WHERE mission_id = :m"),
            {"m": mission.id}).scalar()
    check("a second write appends rather than overwriting", after == before + 1,
          f"{before} then {after}")
    check("the reader returns the latest",
          "second attempt" in reports.latest(mission.id, tenant=TENANT)["report"])
    check("...and the earlier attempt is still there",
          after >= 2, "a filename lost it; a row does not")

    print("\n-- tenants ------------------------------------------------------------")
    theirs = Mission(id="mission-reportproof03", tenant_id=OTHER, title="theirs")
    reports.write(theirs, root=fresh, detail="another tenant")
    check("another tenant's report is not returned",
          reports.latest(theirs.id, tenant=TENANT) is None)
    check("NEGATIVE CONTROL: it is returned to its own tenant",
          reports.latest(theirs.id, tenant=OTHER) is not None)
    check("...and the operator console, unscoped, sees it",
          reports.latest(theirs.id) is not None)

    print("\n-- no hidden fallback -------------------------------------------------")
    import atlas_kernel.db as db  # noqa: E402

    class _Down:
        def __enter__(self):
            raise OSError("the database is not there")

        def __exit__(self, *_):
            return False

    working = db.SessionLocal
    db.SessionLocal = lambda: _Down()
    try:
        try:
            reports.write(mission, root=fresh, detail="during an outage")
            check("an unreachable store raises rather than writing a file",
                  False, "it wrote somewhere")
        except reports.ReportStoreUnavailable:
            check("an unreachable store raises rather than writing a file", True,
                  "a report on a disk nobody can read is worse than none")
        check("...and no file appeared", not any(fresh.rglob("*.md")))
    finally:
        db.SessionLocal = working

    print("\n-- two processes, sharing no filesystem --------------------------------")
    # In a temp dir, not the repository. Writing it into ROOT failed on the
    # server with EACCES — which is the source checkout being read-only to the
    # worker user, exactly as `verify_scratch_isolation` requires. The guard was
    # right and the harness was wrong.
    probe = work / "report-reader.py"
    probe.write_text(
        "import hashlib, json, os, sys\n"
        f"sys.path.insert(0, {str(ROOT / 'packages' / 'kernel')!r})\n"
        "os.environ['QEVIK_REPORTS_STORE'] = 'postgres'\n"
        "from atlas_kernel.mission import reports\n"
        f"r = reports.latest({big.id!r}, tenant={TENANT!r})\n"
        "print(json.dumps({'bytes': r['bytes'],"
        " 'sha': hashlib.sha256(r['report'].encode()).hexdigest(),"
        " 'path': r['path']}))\n", encoding="utf-8")
    done = subprocess.run([sys.executable, str(probe)], capture_output=True,
                          text=True, check=False)
    probe.unlink(missing_ok=True)
    import json as _json  # noqa: E402

    seen = _json.loads(done.stdout) if done.returncode == 0 else {}
    check("a second process reads the report", done.returncode == 0,
          done.stderr.strip()[-140:] if done.returncode else "")
    check("...with no file anywhere to read", not any(fresh.rglob("*.md")))
    check("...and the bytes are identical",
          seen.get("sha") == hashlib.sha256(back["report"].encode()).hexdigest(),
          f"{seen.get('bytes', 0):,} bytes")
finally:
    os.environ.pop(reports.ENVIRONMENT, None)

print("\n-- the ledger never carries a body ------------------------------------")
from atlas_kernel.mission import service  # noqa: E402

event = service._event(mission, actor="worker", note="report written")
check("a mission event carries the path and not the report",
      "report_path" in event.detail and "content" not in event.detail)
check("...and is small enough to fold every ten seconds",
      len(str(event.detail)) < 4_000, f"{len(str(event.detail))} chars")
# Asserted against the real ledger, not asserted as `True`. This is the
# property the separate table exists for: every worker folds these rows every
# ten seconds, and one 6 MB detail among them would cross the wire constantly.
with SessionLocal() as session:
    events = session.execute(text(
        "SELECT count(*) FROM atlas_business_events "
        "WHERE factory = 'mission'")).scalar() or 0
    widest = session.execute(text(
        "SELECT coalesce(max(length(detail::text)), 0) "
        "FROM atlas_business_events WHERE factory = 'mission'")).scalar() or 0
if not events:
    # A maximum over nothing is zero, which would pass without measuring
    # anything. Reported rather than counted as proof.
    check("no mission event in the ledger holds a body", False,
          "NOT MEASURED: this database holds no mission events. Run where the "
          "ledger is — the production gate does.")
else:
    check("no mission event in the ledger holds a body", int(widest) < 16_000,
          f"{events} event(s), widest detail {int(widest):,} chars; bodies live "
          "in atlas_mission_reports, which fold never reads")

wipe()
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
for n in FAILED:
    print(f"  FAILED  {n}")
sys.exit(1 if FAILED else 0)
