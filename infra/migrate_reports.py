"""Copy mission reports from disk into Postgres. Reversible, read-only on files.

The files are **never modified, renamed or deleted**. Rollback is unsetting
`QEVIK_REPORTS_STORE`, and the originals are exactly where they were.

Idempotent on `(mission_id, path, bytes)`: a report already stored with the same
name and the same length is not copied again. Length rather than a hash of the
whole body because one real report is 6.3 MB and re-hashing every file on every
run to discover there is nothing to do is a cost with no reader — the harness
verifies content byte for byte, which is where that check belongs.

    migrate_reports.py --reports /var/lib/qevik/control/reports
    migrate_reports.py --reports … --check
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal, init_db  # noqa: E402
from atlas_kernel.mission.reports import REPORTS  # noqa: E402
from atlas_kernel.mission.timeline import Timeline  # noqa: E402

MISSION_ID = "_mission-"


def mission_of(name: str) -> str:
    """The mission a report belongs to, from the name the writer gave it.

    `filename()` ends every report with `_<mission id>.md`, which is the only
    link between a file and a mission that exists on disk.
    """
    stem = Path(name).stem
    _, _, tail = stem.rpartition("_")
    return tail if tail.startswith("mission-") else ""


def stored() -> set[tuple[str, str, int]]:
    with SessionLocal() as session:
        rows = session.execute(text(
            "SELECT mission_id, path, bytes FROM atlas_mission_reports")).all()
    return {(r[0], r[1], int(r[2])) for r in rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", required=True)
    parser.add_argument("--timeline", default="",
                        help="ledger, to attribute a tenant to each report")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    init_db()
    directory = Path(args.reports) / REPORTS
    files = sorted(p for p in directory.glob("*.md") if p.is_file())
    total = sum(p.stat().st_size for p in files)
    print(f"files:    {len(files)} report(s), {total} bytes")

    # The tenant each mission belongs to, from the ledger. A report inherits its
    # mission's tenant; guessing one would put a customer's report where another
    # tenant could read it.
    tenants: dict[str, str] = {}
    if args.timeline:
        for event in Timeline(Path(args.timeline), backend="file").read():
            detail = event.get("detail") or {}
            if detail.get("mission_id"):
                tenants[detail["mission_id"]] = detail.get("tenant_id", "")

    have = stored()
    print(f"postgres: {len(have)} report(s) already there")

    missing = [p for p in files
               if (mission_of(p.name), str(REPORTS / p.name),
                   p.stat().st_size) not in have]
    print(f"to copy:  {len(missing)}")
    if args.check:
        return 0

    copied = copied_bytes = 0
    with SessionLocal() as session:
        for path in missing:
            mission_id = mission_of(path.name)
            if not mission_id:
                print(f"  skipped (no mission in the name): {path.name}")
                continue
            body = path.read_text(encoding="utf-8")
            session.execute(
                text("""
                INSERT INTO atlas_mission_reports
                    (id, mission_id, tenant_id, path, content, bytes,
                     written_by, written_at)
                VALUES (:id, :mission_id, :tenant_id, :path, :content, :bytes,
                        :written_by, :written_at)
                """),
                {"id": f"rep-mig-{mission_id[-12:]}-{path.stat().st_size}",
                 "mission_id": mission_id,
                 "tenant_id": tenants.get(mission_id, ""),
                 "path": str(REPORTS / path.name), "content": body,
                 "bytes": len(body.encode("utf-8")),
                 "written_by": "migration",
                 # When the file was written, not when it was copied.
                 "written_at": datetime.fromtimestamp(path.stat().st_mtime,
                                                      tz=UTC)})
            copied += 1
            copied_bytes += len(body.encode("utf-8"))
        session.commit()

    print(f"copied:   {copied} report(s), {copied_bytes} bytes")
    print(f"postgres: {len(stored())} report(s) now")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
