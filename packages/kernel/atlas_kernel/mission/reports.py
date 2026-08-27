"""A durable report for every mission, written on every exit.

P-B1 §9. The worker records what happened whether the mission succeeded or
failed, because a failed mission with no report is the case nobody can learn
from — and a report written only on success is a record that flatters itself.

Reports are files under `docs/qevik-docs/autonomous/reports/`, one per mission,
never overwritten. The existing `BusinessEvent` timeline remains authoritative
for *state*; this is the human-readable account beside it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .models import Mission

#: Where reports live. Matches the convention already in the repository.
REPORTS = Path("docs/qevik-docs/autonomous/reports")

#: Which store holds report bodies. Read once, from the environment, never
#: guessed — and `file` remains the default so a deployment moves deliberately.
ENVIRONMENT = "QEVIK_REPORTS_STORE"
FILE = "file"
POSTGRES = "postgres"
STORES = frozenset({FILE, POSTGRES})


class ReportStoreUnavailable(RuntimeError):
    """The configured store could not be reached.

    Its own type for the reason the ledger has one: a fallback here would write
    a report to a disk an off-host control plane cannot read, and report it as
    written. A mission would look complete with a report nobody can open.
    """


def store() -> str:
    chosen = os.environ.get(ENVIRONMENT, FILE)
    if chosen not in STORES:
        raise ValueError(
            f"{chosen!r} is not a report store. Known: {', '.join(sorted(STORES))}.")
    return chosen


def save(mission: Mission, body: str, *, path: str, written_by: str = "",
         at: datetime | None = None) -> str:
    """Record one report body. Insert-only; a re-run appends.

    Returns the path, unchanged, so `report_path` keeps meaning what it meant.
    In this store the path is a **name**, not a location — nothing resolves it
    against a filesystem.
    """
    from sqlalchemy import text

    from ..db import SessionLocal

    try:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_mission_reports
                    (id, mission_id, tenant_id, path, content, bytes,
                     written_by, written_at)
                VALUES (:id, :mission_id, :tenant_id, :path, :content, :bytes,
                        :written_by, :written_at)
                """),
                {"id": f"rep-{uuid4().hex[:12]}", "mission_id": mission.id,
                 "tenant_id": mission.tenant_id, "path": path, "content": body,
                 "bytes": len(body.encode("utf-8")), "written_by": written_by,
                 "written_at": at or datetime.now(UTC)})
            session.commit()
    except Exception as unreachable:               # noqa: BLE001 - re-raised
        raise ReportStoreUnavailable(
            f"could not store the report: {unreachable}"[:300]) from unreachable
    return path


def latest(mission_id: str, *, tenant: str | None = None) -> dict | None:
    """The most recent report for a mission, or nothing.

    Latest rather than only: a retried mission has more than one, and the
    earlier attempts stay readable instead of being overwritten as they were
    when a filename was the identity.
    """
    from sqlalchemy import text

    from ..db import SessionLocal

    try:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                SELECT path, content, bytes, written_by, written_at
                FROM atlas_mission_reports
                WHERE mission_id = :m
                  AND (:tenant = '' OR tenant_id = :tenant)
                ORDER BY written_at DESC, id DESC
                LIMIT 1
                """),
                {"m": mission_id, "tenant": str(tenant or "")}).mappings().first()
    except Exception as unreachable:               # noqa: BLE001 - re-raised
        raise ReportStoreUnavailable(
            f"could not read the report: {unreachable}"[:300]) from unreachable
    if row is None:
        return None
    return {"path": row["path"], "report": row["content"],
            "bytes": row["bytes"], "written_by": row["written_by"],
            "written_at": row["written_at"].isoformat()
            if row["written_at"] else ""}


def filename(mission: Mission, *, at: datetime | None = None) -> str:
    """Stable, sortable, and unique per mission.

    The mission id is included because two missions on one day with the same
    title are two different pieces of work, and a report that overwrote the
    other would destroy the first one's evidence.
    """
    stamp = (at or datetime.now(UTC)).strftime("%Y-%m-%d")
    slug = "".join(c if c.isalnum() else "-" for c in mission.title.lower())
    slug = "-".join(part for part in slug.split("-") if part)[:48]
    return f"{stamp}_{slug}_{mission.id}.md"


def render(mission: Mission, *, attempts: int = 0, committed: str = "",
           detail: str = "", tests: str = "", branch: str = "",
           evidence: str = "", tools: tuple[str, ...] = (),
           artefact: tuple[str, ...] = (),
           files: tuple[str, ...] = ()) -> str:
    """The report body. States what did not happen as plainly as what did."""
    cost = mission.total_cost
    lines = [
        f"# {mission.title}",
        "",
        f"**Mission:** `{mission.id}`  ",
        f"**Status:** {mission.status.value}  ",
        f"**Requested by:** {mission.requested_by or 'unknown'}  ",
        f"**Created:** {mission.created_at.isoformat()}  ",
        f"**Updated:** {mission.updated_at.isoformat()}  ",
        f"**Attempts:** {attempts}",
        "",
    ]

    if mission.plan is not None:
        lines += ["## Plan", "", f"**Goal:** {mission.plan.goal}", ""]
        for step in mission.plan.steps:
            lines.append(f"{step.order}. {step.title}")
        lines.append("")

    if evidence:
        # What the agent actually observed, step by step. The worker computed
        # this and dropped it: `result.report` was set and never passed here,
        # so a report said a mission succeeded without saying what was checked.
        lines += ["## Evidence", "",
                  "What ran, and what each step establishes.", "",
                  "```", evidence.strip(), "```", ""]

    lines += ["## Agent", ""]
    if mission.invocations:
        for call in mission.invocations:
            tokens = ("tokens unavailable" if call.input_tokens is None
                      else f"{call.input_tokens} in / {call.output_tokens} out")
            lines.append(f"- `{call.provider}/{call.model}` — {call.task or 'call'}"
                         f" — {tokens} — cost {call.cost_status}")
    else:
        lines.append("No agent invocation was recorded.")
    lines += ["", "**Total cost:** "
              + ("not reported by any provider" if cost is None else f"{cost}"), ""]

    if mission.signal_id:
        # A delivery is reviewed by somebody deciding whether to send it, and
        # that decision needs the chain: which opportunity, approved to what
        # scope, carried out by which declared recipe and role, producing which
        # files, on the strength of which evidence. Spread across the report it
        # is technically present and practically unreadable.
        lines += [
            "## Delivery", "",
            f"**Source opportunity:** `{mission.signal_id}`  ",
            f"**Approved scope:** {mission.approved_scope or 'not recorded'}  ",
            f"**Approved by:** {mission.requested_by or 'unknown'}  ",
            f"**Origin:** {mission.origin_name or 'none'}"
            + (f" → `{mission.origin}` ({mission.origin_kind})"
               if mission.origin else "") + "  ",
            f"**Recipe:** `{mission.recipe or 'none'}`  ",
            f"**Agent / role:** `{mission.agent_id or 'none'}`  ",
            f"**Tools used:** {', '.join(f'`{t}`' for t in tools) or 'none'}  ",
            f"**Workspace:** `{mission.workspace or 'none'}`  ",
            f"**Cost:** {'not reported by any provider' if cost is None else cost}"
            f" ({'REPORTED' if cost is not None else 'UNKNOWN'})  ",
            f"**Final status:** {mission.status.value}",
            "",
        ]
        if artefact:
            lines += ["**Artefact produced:**", ""]
            lines += [f"- `{name}`" for name in artefact]
            # Where to actually get it. The mission's worktree is torn down on
            # success — the commit is what is durable — so a reviewer told only
            # that four files exist finds an empty directory and concludes the
            # delivery lied. This is the command that produces the artefact.
            lines += [
                "",
                f"Committed to branch `mission/{mission.id}` in "
                f"`{mission.workspace or 'the mission workspace'}`. The "
                "worktree is removed once the commit is made, so read it with:",
                "",
                "```",
                f"git -C {mission.workspace or '<workspace>'} show "
                f"mission/{mission.id}:{artefact[0]}",
                "```",
                "",
            ]
        else:
            lines += ["**Artefact produced:** none.", ""]
        if mission.evidence_fingerprints:
            lines += [
                "**Evidence the approval rested on:**", "",
                " ".join(f"`{f}`" for f in mission.evidence_fingerprints), "",
            ]
        lines += [
            "**Not done, and out of scope for this mission:** the artefact was "
            "not published and the business was not contacted. Both are "
            "outward acts needing their own approval.", "",
        ]

    lines += ["## Result", ""]
    if files:
        lines.append("Files changed:")
        lines += [f"- `{f}`" for f in files]
        lines.append("")
    lines += [
        f"**Branch:** {branch or 'none'}  ",
        f"**Commit:** {committed or 'none — nothing was committed'}  ",
        "**Pushed:** no  ",
        f"**Tests:** {tests or 'not recorded'}",
        "",
    ]

    if mission.blockers:
        lines += ["## Blockers", ""]
        for blocker in mission.blockers:
            lines.append(f"- **{blocker.kind}** — {blocker.detail}"
                         + (f" → {blocker.action}" if blocker.action else ""))
        lines.append("")

    if detail:
        lines += ["## What did not happen", "", detail, ""]

    return "\n".join(lines)


def write(mission: Mission, *, root: Path | str = ".", attempts: int = 0,
          committed: str = "", detail: str = "", tests: str = "",
          branch: str = "", files: tuple[str, ...] = (),
          tools: tuple[str, ...] = (), artefact: tuple[str, ...] = (),
          evidence: str = "", written_by: str = "") -> Path:
    """Persist the report and return its path. Never overwrites another.

    The fields are named rather than forwarded as `**kwargs`: a passthrough
    reads as flexible and is really just untyped, and a caller misspelling one
    would silently write a report missing the field they meant to set.
    """
    body = render(mission, attempts=attempts, committed=committed,
                  detail=detail, tests=tests, branch=branch, files=files,
                  evidence=evidence, tools=tools, artefact=artefact)
    name = filename(mission)

    if store() == POSTGRES:
        # No directory is created and nothing is written to disk. The caller
        # still gets a path back, because that is what `report_path` records
        # and its meaning is unchanged — a name, resolved by the store rather
        # than by a filesystem.
        save(mission, body, path=str(REPORTS / name), written_by=written_by)
        return REPORTS / name

    directory = Path(root) / REPORTS
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path
