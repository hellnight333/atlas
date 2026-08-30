"""The execution memory is repository truth, so the repository holds it to it.

`.qevik/` exists so a session can resume without the chat that produced it. Two
things would make it worse than nothing: a secret in it, because `.qevik/` is
also the credentials convention and these files are tracked; and a claim in it
that the code no longer supports, because a resuming session trusts it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MEMORY = Path(__file__).resolve().parents[3] / ".qevik"

LEDGERS = ("EXECUTION_STATE.md", "CAPABILITY_LEDGER.md", "HUMAN_ACTIONS.md",
           "BLOCKERS.md", "DECISION_QUEUE.md", "PRODUCTION_EVIDENCE.md",
           "INTEGRATION_MATRIX.md", "SESSION_LOG.md")


def _text(name: str) -> str:
    return (MEMORY / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", LEDGERS)
def test_every_ledger_exists(name: str) -> None:
    assert (MEMORY / name).is_file(), f".qevik/{name} is missing"


@pytest.mark.parametrize("name", LEDGERS)
def test_no_ledger_carries_a_secret(name: str) -> None:
    """`.qevik/` is the credentials convention and these files are tracked. A
    key pasted into a note here goes into git history, where deleting it does
    not remove it."""
    body = _text(name)

    literals = re.findall(
        r"""(?:password|secret|token|api[_-]?key)\s*[:=]\s*['"]?[A-Za-z0-9/+_-]{12,}""",
        body, re.I)
    assert literals == [], literals
    for shape in ("sk-", "AKIA", "-----BEGIN", "ghp_", "xoxb-"):
        assert shape not in body, f"{name} contains {shape!r}"


def test_the_ledgers_are_tracked_and_the_rest_of_the_directory_is_not() -> None:
    """The reason `.qevik/` is ignored at all is that credentials live under
    `~/.qevik/credentials/`. Re-including the whole directory to track eight
    files would admit a stray note somebody pasted a key into."""
    # Rules, not prose. The file's own comment explains why a wildcard
    # re-include was rejected, and matching raw text found that explanation.
    rules = [line.strip() for line
             in (MEMORY.parent / ".gitignore").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]

    assert ".qevik/*" in rules, (
        "the directory contents must stay ignored by default")
    for name in LEDGERS:
        assert f"!.qevik/{name}" in rules, name
    assert "!.qevik/*.md" not in rules, (
        "a wildcard re-include would track any markdown file dropped in here")


def test_no_ledger_claims_a_capability_the_code_does_not_have() -> None:
    """The ledger names capabilities by offer id. One naming an offer no
    executor serves is a claim a resuming session would act on."""
    from atlas_kernel.execution.capabilities import EXECUTORS

    body = _text("CAPABILITY_LEDGER.md")
    named = set(re.findall(r"`?(offer-[a-z-]+)`?", body))

    assert named <= set(EXECUTORS), (
        f"the ledger names offers nothing can execute: {named - set(EXECUTORS)}")


def test_production_evidence_never_claims_a_commercial_result() -> None:
    """The distinction the whole file exists for. A published URL is not a
    customer, and no row may say otherwise until a business actually responds."""
    body = _text("PRODUCTION_EVIDENCE.md")

    rows = [line for line in body.splitlines()
            if line.startswith("| E-") and "COMMERCIAL-VERIFIED" in line]

    assert rows == [], (
        f"a commercial claim was recorded with no external evidence: {rows}")


def test_human_actions_name_settings_rather_than_values() -> None:
    """An action tells somebody what to set. It must never record what it is
    set to."""
    body = _text("HUMAN_ACTIONS.md")

    # The names must be there — a negative control for the assertion below,
    # which would otherwise pass on an empty file.
    assert "QEVIK_SMTP_PASSWORD" in body
    assert "QEVIK_GOOGLE_PLACES_API_KEY" in body or "Google Places" in body
    # And never a value beside one.
    assert not re.search(r"QEVIK_[A-Z_]+\s*=\s*\S", body), (
        "a human action records a credential value")


def test_every_blocker_says_whether_work_continues_elsewhere() -> None:
    """The rule this file exists to enforce: one blocked capability must not
    read as a blocked project."""
    rows = [line for line in _text("BLOCKERS.md").splitlines()
            if line.startswith("| B-")]

    assert rows, "no blockers recorded at all, which is unlikely to be true"
    for row in rows:
        assert "| Yes" in row or "| No" in row, row


def test_the_decision_queue_does_not_answer_an_unknown() -> None:
    """`YouMind` is UNKNOWN in the historical record. Inventing a definition
    for it is the exact failure the queue exists to prevent."""
    body = _text("DECISION_QUEUE.md")
    line = next(l for l in body.splitlines() if "YouMind" in l)

    assert "UNKNOWN" in line
    assert "not recoverable" in line or "inventing" in line
