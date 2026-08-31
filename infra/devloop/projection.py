"""Writing the queue back out as something a person reads.

SQLite is the driver's state; `.qevik/EXECUTION_STATE.md` is the projection.
Keeping that direction fixed is what stops the two disagreeing: nothing here
reads the markdown to decide anything, and nothing outside here writes the
section this owns.

A boundary the driver hits is parked into the ledger that already owns that
kind of fact — `HUMAN_ACTIONS.md` for a credential, an account or a machine,
`DECISION_QUEUE.md` for a product or architecture question. Those files are the
human-readable half of the control plane's own action centre, and inventing a
third place for the driver's blockers would be exactly the competing
representation this design refuses.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from .queue import Queue, State, redact

#: The block this module owns inside EXECUTION_STATE.md. Everything between the
#: markers is rewritten; everything outside is left exactly as a person wrote
#: it, because the rest of that file is prose the driver has no business
#: editing.
BEGIN = "<!-- devloop:begin -->"
END = "<!-- devloop:end -->"


def _section(queue: Queue) -> str:
    by_state: dict[str, list[dict]] = {}
    for task in queue.tasks():
        by_state.setdefault(task["state"], []).append(task)

    running = sum(len(by_state.get(s, [])) for s in State.IN_FLIGHT)
    lines = [
        BEGIN,
        "## Development loop",
        "",
        f"_Written by `infra/devloop/driver.py` at "
        f"{datetime.now(UTC).isoformat(timespec='seconds')}. The queue is the "
        f"source of truth; this is its projection._",
        "",
        f"- **{len(by_state.get(State.DONE, []))} done** · {running} in flight "
        f"· {len(by_state.get(State.QUEUED, []))} queued",
        f"- **{len(by_state.get(State.WAITING_FOR_HUMAN, []))} waiting on a "
        f"person** · {len(by_state.get(State.CONTESTED, []))} contested · "
        f"{len(by_state.get(State.BLOCKED, []))} blocked",
        "",
    ]

    parked = by_state.get(State.WAITING_FOR_HUMAN, [])
    if parked:
        lines += ["### Waiting on you", ""]
        for task in parked:
            lines.append(f"- **{task['title']}** — waits on "
                         f"`{task['blocked_by'] or 'unnamed boundary'}`, "
                         f"resumes at `{task['resume_stage'] or 'the start'}`")
        lines.append("")

    contested = by_state.get(State.CONTESTED, [])
    if contested:
        lines += ["### Contested — the reviewer still objects", ""]
        for task in contested:
            found = queue.findings(task["id"])
            lines.append(f"- **{task['title']}** — {len(found)} finding(s) "
                         f"after {task['review_rounds']} round(s). "
                         f"{task['detail'] or ''}".rstrip())
        lines.append("")

    health = queue.last_reviewer_health()
    if health:
        lines += [
            f"_Reviewer negative control: "
            f"{'detected the planted defect' if health['detected'] else '**did not detect the planted defect**'} "
            f"({health['at'][:19]})._", ""]
    lines.append(END)
    return "\n".join(lines)


def write(repo: Path, queue: Queue) -> None:
    """Refresh the driver's block in EXECUTION_STATE.md. Idempotent."""
    path = repo / ".qevik" / "EXECUTION_STATE.md"
    if not path.exists():
        return
    body = path.read_text()
    block = _section(queue)
    if BEGIN in body and END in body:
        body = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), block, body,
                      flags=re.S)
    else:
        body = body.rstrip() + "\n\n" + block + "\n"
    path.write_text(body)


def _append_once(path: Path, marker: str, block: str) -> bool:
    """Append unless the marker is already there. Returns whether it wrote.

    Idempotence matters more here than anywhere else in the driver: a boundary
    is hit every time the blocked task is retried, and a ledger that grew an
    entry per retry would bury the four real ones under two hundred copies.
    """
    if not path.exists():
        return False
    body = path.read_text()
    if marker in body:
        return False
    path.write_text(body.rstrip() + "\n\n" + block.rstrip() + "\n")
    return True


def park_boundary(repo: Path, task: dict, boundary: str) -> str:
    """Record a human boundary in the ledger that owns that kind of fact.

    Returns the marker used, which is also the idempotency key: the same
    boundary from the same task never appears twice.
    """
    marker = f"<!-- devloop:{task['id']} -->"
    decisionish = any(word in boundary.lower() for word in
                      ("decision", "policy", "product", "architecture",
                       "should qevik", "which "))
    target = ("DECISION_QUEUE.md" if decisionish else "HUMAN_ACTIONS.md")
    block = (
        f"{marker}\n"
        f"## From the development loop — {redact(task['title'])}\n\n"
        f"**Open.** The loop parked this task rather than guessing.\n\n"
        f"- **What it was doing:** {redact(task['brief'])[:400]}\n"
        f"- **Where it stopped:** {redact(boundary)}\n"
        f"- **Driver task:** `{task['id']}`\n\n"
        f"Nothing was changed, sent, deployed or decided. The task resumes "
        f"from where it stopped once this is resolved.\n")
    _append_once(repo / ".qevik" / target, marker, block)
    return marker


def park_contested(repo: Path, task: dict, findings: list[dict]) -> str:
    """A disagreement three rounds could not settle is a person's to read."""
    marker = f"<!-- devloop:contested:{task['id']} -->"
    listed = "\n".join(
        f"  - `{f['file']}` [{f['severity']}] {redact(f['claim'])}"
        for f in findings if f["severity"] in ("blocking", "major"))
    block = (
        f"{marker}\n"
        f"## Contested — {redact(task['title'])}\n\n"
        f"The reviewer raised findings the builder did not settle in three "
        f"rounds. The work is committed and **not deployed**.\n\n"
        f"{listed}\n\n"
        f"- **Driver task:** `{task['id']}`\n"
        f"- **Review unit:** `{(task.get('base_sha') or '')[:12]}.."
        f"{(task.get('head_sha') or '')[:12]}`\n")
    _append_once(repo / ".qevik" / "DECISION_QUEUE.md", marker, block)
    return marker


__all__ = ["BEGIN", "END", "park_boundary", "park_contested", "write"]
