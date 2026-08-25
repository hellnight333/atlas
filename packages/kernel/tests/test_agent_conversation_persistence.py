"""Agent-to-agent conversations are not persisted, and must not need to be yet.

`fabric/protocol.py` defines an `Exchange` and a `Conversation` — a *different*
thing from the chat conversations a person has, which are durable in
`chat.jsonl`. This one is agents asking each other for capabilities.

It has no persistence, and that is currently correct: **nothing on the live path
produces one.** A mission runs as

    mission → scheduler → claim → worker → registry → adapter
    → tool contract → sandbox → evidence → report

with a single agent running declared steps. No message is exchanged between
agents anywhere in it, so there is nothing to persist, and building storage for
a type nothing creates is work that ages without ever being exercised.

## The tripwire

The moment something *does* construct an `Exchange`, this becomes a real gap:
an agent conversation that vanishes on restart takes with it the reasoning
behind whatever mission it produced — the same failure user chat had, where the
mission survived and the sentence that justified it did not.

So the test below fails when the first producer appears, and says what to do.
It is not asserting that the feature is unnecessary forever; it is making the
day it becomes necessary loud instead of silent.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
KERNEL = ROOT / "packages" / "kernel" / "atlas_kernel"
INFRA = ROOT / "infra"

#: The module that defines the type, and the package that re-exports it. Neither
#: is a producer.
DEFINERS = {KERNEL / "fabric" / "protocol.py", KERNEL / "fabric" / "__init__.py"}


def _live_sources() -> list[Path]:
    """Everything that runs in production. Tests are not included: a test may
    construct an `Exchange` freely, and several do."""
    found = [p for p in KERNEL.rglob("*.py") if "__pycache__" not in p.parts]
    found += [p for p in INFRA.glob("*.py")]
    return [p for p in found if p not in DEFINERS]


def _constructs_an_exchange(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:                                   # pragma: no cover
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "Exchange":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "Exchange":
                return True
    return False


def test_nothing_on_the_live_path_holds_an_agent_conversation() -> None:
    """When this fails, the feature it guards has become necessary.

    Persist `Conversation` before shipping whatever produced it, using the fold
    the rest of the system already uses — `mission.fold`, `credentials.restore`,
    `QuotaLedger._replay` are all the same shape. Do **not** invent a second
    storage mechanism, and do not delete this test to make the failure go away:
    replace it with one asserting the conversation survives a restart.
    """
    producers = [p.relative_to(ROOT) for p in _live_sources()
                 if _constructs_an_exchange(p)]
    assert producers == [], (
        f"{producers} now creates agent-to-agent conversations, which have no "
        "persistence. An exchange that vanishes on restart takes the reasoning "
        "behind its mission with it — the same failure user chat had. Persist "
        "it with the existing event fold before shipping this."
    )


def test_the_type_it_guards_actually_exists() -> None:
    """The negative control. If `Exchange` were renamed or removed, the test
    above would pass by finding nothing, and the guard would be gone without
    anybody noticing."""
    from atlas_kernel.fabric.protocol import Conversation, Exchange

    assert Exchange is not None
    assert "messages" in Conversation.model_fields


def test_the_detector_would_notice_a_producer(tmp_path) -> None:
    """The other negative control: prove the AST walk actually fires, rather
    than passing because it never matches anything."""
    sample = tmp_path / "producer.py"
    sample.write_text("from atlas_kernel.fabric import Exchange\n"
                      "def go():\n    return Exchange()\n", encoding="utf-8")
    assert _constructs_an_exchange(sample) is True

    quiet = tmp_path / "quiet.py"
    quiet.write_text("def go():\n    return 1\n", encoding="utf-8")
    assert _constructs_an_exchange(quiet) is False


def test_user_chat_is_a_different_thing_and_is_persisted() -> None:
    """These are easy to confuse and have opposite states. A reader who mixes
    them up either builds storage that exists or ships without storage that
    does not."""
    from atlas_kernel.chat import service as chat

    assert hasattr(chat, "fold"), "user conversations fold from events"
    assert hasattr(chat, "rehydrate")

    from atlas_kernel.fabric import protocol

    assert not hasattr(protocol, "fold"), (
        "if the agent protocol gained a fold, the tripwire above should be "
        "replaced with a durability test rather than left in place")


@pytest.mark.parametrize("shape", ["fold", "restore", "_replay"])
def test_the_pattern_to_follow_already_exists(shape: str) -> None:
    """Whoever implements this should copy one of these, not invent a third."""
    from atlas_kernel.credentials import service as credentials
    from atlas_kernel.mission import service as mission
    from atlas_kernel.quota.ledger import QuotaLedger

    assert any([hasattr(mission, shape), hasattr(credentials, shape),
                hasattr(QuotaLedger, shape)]), shape
