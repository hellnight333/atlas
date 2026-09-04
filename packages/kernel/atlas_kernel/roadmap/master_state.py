"""`MASTER_STATE.md`, read rather than restated.

The console's Roadmap page was written against a payload with `product_a`,
`product_b` and `product_c` — a shape nobody ever built and this repository's
roadmap document does not have. So the page 404'd on every load and rendered its
own apology, correctly refusing to show a hardcoded copy on the grounds that a
second answer to "what is built" would drift from the first.

That principle is right and this module is how to honour it: parse the document
the repository already maintains, and serve what it actually says.

Deliberately a *reader*. It derives nothing, scores nothing and completes
nothing. Sections are named here because a roadmap page that rendered all
ninety-odd headings of a 1500-line file would be the file, and the file is
already readable. Everything it returns is a quotation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

#: The document. Four levels up from this module is the repository root:
#: roadmap -> atlas_kernel -> kernel -> packages -> root.
MASTER_STATE = Path(__file__).resolve().parents[4] / "MASTER_STATE.md"

#: Which sections the roadmap surface shows, in the order it shows them, with
#: the one-line note that says what each is for.
#:
#: Chosen rather than derived, and the choice is the design: this document is
#: ~1500 lines and most of it is the record of how something came to be true.
#: A roadmap answers four questions — what works, what is half-built, what is
#: stuck, and what is next — and these are the headings that answer them.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("Operational now",
     "Capabilities with the evidence that they work. Every row names a module "
     "or a verification run, so a claim here can be checked against the "
     "repository rather than believed."),
    ("Roadmap components — verified, not assumed",
     "Components that exist as modules, and what each is actually wired into. "
     "Built and imported by nothing is a real state and is named as one."),
    ("Blocked, precisely",
     "What is waiting, and on what. Precisely, because 'blocked' without a "
     "cause is indistinguishable from forgotten."),
    ("Next — chosen on dependency, not roadmap order",
     "What comes next and why that one — dependency order, not preference."),
    ("Roadmap, in dependency order",
     "The whole sequence, so a piece of work can be located in it."),
    ("Open findings",
     "Known and unfixed. Recorded here rather than in somebody's memory."),
    ("Open product decisions",
     "Questions that need an answer from a person. Nothing downstream of one "
     "of these should be started by guessing at it."),
)

_RECONCILED = re.compile(r"\*\*Last reconciled:\*\*\s*(.+)")


def _table(lines: list[str]) -> list[dict[str, str]]:
    """Rows of a markdown table, or an empty list where there is no table.

    Two columns or three; the header names them. A row is returned as the
    header's own words mapped to the cells, so a document that renames a column
    renames it here too rather than silently filling a key nobody updated.
    """
    rows: list[dict[str, str]] = []
    header: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not header:
            header = cells
            continue
        if all(set(c) <= {"-", ":", " "} for c in cells):
            continue  # the ---|--- separator
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells, strict=False)))
    return rows


def _prose(lines: list[str]) -> list[str]:
    """The paragraphs of a section, with the table taken out.

    Blank-line separated, so a paragraph survives the wrapping the document is
    written with and does not arrive as one line per line.
    """
    kept: list[str] = []
    buffer: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") or stripped.startswith("###"):
            continue
        if not stripped:
            if buffer:
                kept.append(" ".join(buffer))
                buffer = []
            continue
        buffer.append(stripped)
    if buffer:
        kept.append(" ".join(buffer))
    return kept


def _sections(text: str) -> dict[str, list[str]]:
    """Every `## ` section, by heading, as its own lines.

    `###` subsections stay inside their parent: they are the detail of the
    thing above them, and promoting them would make the roadmap a list of
    ninety headings.
    """
    found: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            found[current] = []
        elif current is not None:
            found[current].append(line)
    return found


def read(path: Path | None = None) -> dict[str, Any]:
    """The roadmap, as the document states it.

    `known: False` when the document cannot be read, which is not the same as a
    roadmap with nothing on it — the distinction this codebase draws everywhere
    a store might be unreachable.
    """
    document = path or MASTER_STATE
    try:
        text = document.read_text(encoding="utf-8")
    except OSError:
        return {
            "known": False,
            "sections": [],
            "detail": (f"{document.name} could not be read on this deployment, "
                       "which is not the same as the roadmap being empty"),
        }

    reconciled = _RECONCILED.search(text)
    available = _sections(text)

    sections: list[dict[str, Any]] = []
    for title, note in SECTIONS:
        lines = available.get(title)
        if lines is None:
            # Named here and absent there. Reported rather than skipped: a
            # section that quietly disappears from a roadmap is how a heading
            # gets renamed and a whole band of work stops being shown.
            sections.append({"title": title, "note": note, "rows": [],
                             "prose": [], "missing": True})
            continue
        sections.append({"title": title, "note": note, "rows": _table(lines),
                         "prose": _prose(lines), "missing": False})

    return {
        "known": True,
        "source": document.name,
        "reconciled_at": reconciled.group(1).strip() if reconciled else "",
        "sections": sections,
    }


__all__ = ["MASTER_STATE", "SECTIONS", "read"]
