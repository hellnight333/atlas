"""A Zustand selector must not build a new value (P0, 2026-08-04).

This guards against one specific bug that took the entire desktop application
down, and which is close to invisible in review:

    const jobs = useActivityStore((state) => state.jobs.filter(...))

`.filter` returns a new array on every call. A Zustand selector *is* the
`getSnapshot` for `useSyncExternalStore`: React compares the value it read
during render with the one it reads at commit, sees two different arrays, and
re-renders to catch up. Forever. React reports that as error #185, "Maximum
update depth exceeded".

It cost a day. The shell booted perfectly, the log ended at "rendering main
application", and the only visible symptom was react-router's developer
fallback — so it looked like a startup problem for as long as nobody had the
component names.

Lives with the Python tests because that is the suite CI runs; it needs no
frontend test runner, and a scan is all this requires.
"""

from __future__ import annotations

import re
from pathlib import Path

DESKTOP_SRC = Path(__file__).resolve().parents[3] / "apps" / "desktop" / "src"

#: Operations that return a fresh object or array. Harmless anywhere else;
#: fatal inside a selector.
CONSTRUCTS_A_NEW_VALUE = re.compile(
    r"\.filter\(|\.map\(|\.sort\(|\.slice\(|\.concat\(|\.reduce\(|"
    r"\?\?\s*[\[{]|\|\|\s*[\[{]|Object\.(keys|values|entries)\(|\[\s*\.\.\."
)

#: A store hook call and whatever it was given, across line breaks.
STORE_CALL = re.compile(r"use[A-Za-z]*Store\((.{0,300}?)\)\s*(?:\n|$)", re.S)


def _sources() -> list[Path]:
    if not DESKTOP_SRC.exists():
        return []
    return sorted(DESKTOP_SRC.rglob("*.tsx")) + sorted(DESKTOP_SRC.rglob("*.ts"))


def test_no_selector_builds_a_new_value() -> None:
    offenders: list[str] = []

    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for match in STORE_CALL.finditer(text):
            body = match.group(1)
            if "=>" not in body:
                continue
            # `useShallow` compares contents, so building a value is safe there.
            if "useShallow" in body:
                continue
            if CONSTRUCTS_A_NEW_VALUE.search(body):
                line = text[: match.start()].count("\n") + 1
                offenders.append(
                    f"{path.relative_to(DESKTOP_SRC.parent)}:{line}\n"
                    f"      {' '.join(body.split())[:120]}"
                )

    assert not offenders, (
        "A Zustand selector returns a newly built value, which makes React "
        "re-render without end (error #185):\n\n  "
        + "\n  ".join(offenders)
        + "\n\nSelect the stored value and derive from it in a `useMemo`, or wrap "
        "the selector in `useShallow`."
    )


def test_the_guard_would_actually_catch_the_original_bug() -> None:
    """A guard nobody has seen fail is a guard nobody should trust."""
    original = "const jobs = useActivityStore((state) => state.jobs.filter((j) => j.state === 'running'))\n"
    match = STORE_CALL.search(original)
    assert match is not None
    assert CONSTRUCTS_A_NEW_VALUE.search(match.group(1))


def test_the_guard_permits_a_plain_selector() -> None:
    """It must not fire on the correct form, or it will be deleted."""
    fine = "const jobs = useActivityStore((state) => state.jobs)\n"
    match = STORE_CALL.search(fine)
    assert match is not None
    assert not CONSTRUCTS_A_NEW_VALUE.search(match.group(1))


def test_the_desktop_source_is_where_this_expects_it() -> None:
    """So a moved directory fails loudly instead of silently passing forever."""
    assert DESKTOP_SRC.exists(), f"desktop source not found at {DESKTOP_SRC}"
    assert _sources(), "no desktop sources scanned"
