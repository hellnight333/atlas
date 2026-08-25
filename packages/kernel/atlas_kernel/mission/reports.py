"""A durable report for every mission, written on every exit.

P-B1 §9. The worker records what happened whether the mission succeeded or
failed, because a failed mission with no report is the case nobody can learn
from — and a report written only on success is a record that flatters itself.

Reports are files under `docs/qevik-docs/autonomous/reports/`, one per mission,
never overwritten. The existing `BusinessEvent` timeline remains authoritative
for *state*; this is the human-readable account beside it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .models import Mission

#: Where reports live. Matches the convention already in the repository.
REPORTS = Path("docs/qevik-docs/autonomous/reports")


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
           evidence: str = "",
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
          evidence: str = "") -> Path:
    """Persist the report and return its path. Never overwrites another.

    The fields are named rather than forwarded as `**kwargs`: a passthrough
    reads as flexible and is really just untyped, and a caller misspelling one
    would silently write a report missing the field they meant to set.
    """
    directory = Path(root) / REPORTS
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename(mission)
    path.write_text(
        render(mission, attempts=attempts, committed=committed, detail=detail,
               tests=tests, branch=branch, files=files, evidence=evidence),
        encoding="utf-8")
    return path
