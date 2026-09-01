"""A message may be saved only while it is in the state the caller read.

`OpportunityRepository.save_message` was an unconditional upsert:
`ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, ...` with no
predicate at all. Nothing in the opportunity package carries an expected state
or a version, so every caller that reads a message, decides something from its
status and writes it back was a check-then-write with no atomicity — between
the read and the write another worker can record a send, an approval or a
suppression, and the save replaced it silently.

Two properties are under test, and they pull in opposite directions on purpose:

* **The guard holds.** With `expecting`, the update carries the caller's
  belief about the row into the same statement that writes, so a save whose
  premise has expired lands nowhere and says so.
* **Nothing else moved.** Every existing call site passes no expectation, and
  the unconditional path is still the unconditional upsert it always was —
  blind overwrite included. That is *demonstrated* here rather than asserted:
  the old behaviour is exercised, and the call sites are read.
"""

from __future__ import annotations

import ast
import inspect
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from atlas_kernel import db
from atlas_kernel.db import SessionLocal
from atlas_kernel.opportunity.models import OutreachMessage, OutreachStatus
from atlas_kernel.opportunity.repository import OpportunityRepository, StaleMessage


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


@pytest.fixture
def repo() -> OpportunityRepository:
    return OpportunityRepository()


@pytest.fixture
def business_id():
    """A business no earlier run has used, whose messages are removed after.

    The test database persists between runs, and a conditional write is about
    one specific row; a fixture shared with history would make these tests pass
    or fail for reasons unrelated to the predicate.
    """
    identifier = f"biz-conditional-{uuid4().hex[:12]}"
    yield identifier
    with SessionLocal() as session:
        session.execute(
            text("DELETE FROM atlas_outreach_messages WHERE business_id = :b"),
            {"b": identifier})
        session.commit()


def _draft(business: str, **overrides) -> OutreachMessage:
    return OutreachMessage(
        proposal_id="p-conditional",
        business_id=business,
        channel="recording",
        recipient="owner@clinic.test",
        subject="What we found on your site",
        body="Your homepage has no title.",
        **overrides)


def _stored(repo: OpportunityRepository, business: str,
            message_id: str) -> OutreachMessage | None:
    for found in repo.messages_for(business):
        if found.id == message_id:
            return found
    return None


def _somebody_else_sends(repo: OpportunityRepository,
                         message: OutreachMessage) -> OutreachMessage:
    """A second worker recording a send, between another caller's read and write.

    Deliberately the ordinary unconditional save, because that is what the
    other worker is running. The race is not manufactured with raw SQL; it is
    two callers using the same repository.
    """
    sent = message.model_copy(update={
        "status": OutreachStatus.SENT,
        "sent_at": datetime.now(UTC),
        "provider_message_id": "provider-1"})
    return repo.save_message(sent)


# --------------------------------------------------------------- the guard

def test_a_write_lands_while_the_state_it_read_still_holds(repo, business_id):
    """The ordinary case. An expectation is a guard, not an obstacle."""
    draft = repo.save_message(_draft(business_id))
    approved = draft.model_copy(update={
        "status": OutreachStatus.APPROVED_FOR_MANUAL_SEND,
        "approved_fingerprint": "fp-1"})

    repo.save_message(approved, expecting=OutreachStatus.DRAFT)

    after = _stored(repo, business_id, draft.id)
    assert after is not None
    assert after.status is OutreachStatus.APPROVED_FOR_MANUAL_SEND
    assert after.approved_fingerprint == "fp-1"


def test_a_write_is_refused_once_the_state_has_moved(repo, business_id):
    """The whole point. A caller holding a draft it read a moment ago decides
    to approve it; by the time it writes, somebody else has recorded a send.

    Without the predicate this save succeeds and the send is gone — the row
    reads `approved_for_manual_send` with no `sent_at`, and Qevik has no record
    that it contacted a stranger."""
    draft = repo.save_message(_draft(business_id))
    _somebody_else_sends(repo, draft)

    stale_decision = draft.model_copy(update={
        "status": OutreachStatus.APPROVED_FOR_MANUAL_SEND,
        "approved_fingerprint": "fp-1"})
    with pytest.raises(StaleMessage):
        repo.save_message(stale_decision, expecting=OutreachStatus.DRAFT)


def test_a_refused_write_leaves_the_row_exactly_as_it_found_it(repo, business_id):
    """A refusal that half-wrote would be worse than the race: the send would
    keep its status and lose the evidence that it happened."""
    draft = repo.save_message(_draft(business_id))
    sent = _somebody_else_sends(repo, draft)

    stale_decision = draft.model_copy(update={
        "status": OutreachStatus.APPROVED_FOR_MANUAL_SEND,
        "approved_fingerprint": "fp-1",
        "detail": "approved by the operator"})
    with pytest.raises(StaleMessage):
        repo.save_message(stale_decision, expecting=OutreachStatus.DRAFT)

    after = _stored(repo, business_id, draft.id)
    assert after is not None
    assert after.status is OutreachStatus.SENT
    assert after.provider_message_id == "provider-1"
    assert after.sent_at is not None
    assert after.approved_fingerprint is None
    assert after.detail is None
    assert after.sent_at == sent.sent_at


def test_the_refusal_says_what_it_expected_and_what_it_found(repo, business_id):
    """A bare refusal is not actionable. A caller that meant to approve a draft
    and finds it `sent` is in a different situation from one that finds it
    `suppressed`, and only the second is a reason to stop trying."""
    draft = repo.save_message(_draft(business_id))
    _somebody_else_sends(repo, draft)

    with pytest.raises(StaleMessage) as refusal:
        repo.save_message(
            draft.model_copy(update={"status": OutreachStatus.APPROVED}),
            expecting=OutreachStatus.DRAFT)

    assert refusal.value.message_id == draft.id
    assert refusal.value.expected == "draft"
    assert refusal.value.found == "sent"
    assert "sent" in str(refusal.value) and "draft" in str(refusal.value)


def test_only_one_of_two_callers_can_take_the_same_transition(repo, business_id):
    """Two workers read the same draft and both decide to approve it. Exactly
    one write may take effect, and the loser must be told it lost."""
    draft = repo.save_message(_draft(business_id))
    first = draft.model_copy(update={"status": OutreachStatus.APPROVED,
                                     "approved_fingerprint": "fp-first"})
    second = draft.model_copy(update={"status": OutreachStatus.APPROVED,
                                      "approved_fingerprint": "fp-second"})

    repo.save_message(first, expecting=OutreachStatus.DRAFT)
    with pytest.raises(StaleMessage) as refusal:
        repo.save_message(second, expecting=OutreachStatus.DRAFT)

    assert refusal.value.found == "approved"
    after = _stored(repo, business_id, draft.id)
    assert after is not None and after.approved_fingerprint == "fp-first"


def test_a_message_that_is_not_there_is_refused_rather_than_created(repo, business_id):
    """An expectation about a row's current status presupposes the row. An
    insert here would manufacture exactly the state the caller claimed to have
    read, which is the failure this parameter exists to prevent."""
    absent = _draft(business_id, status=OutreachStatus.APPROVED)

    with pytest.raises(StaleMessage) as refusal:
        repo.save_message(absent, expecting=OutreachStatus.DRAFT)

    assert refusal.value.found is None
    assert "no message" in str(refusal.value)
    assert _stored(repo, business_id, absent.id) is None


def test_an_expectation_may_be_named_as_a_plain_string(repo, business_id):
    """Callers that carry a status as text — an API payload, a row read
    elsewhere — should not have to reconstruct the enum to use the guard."""
    draft = repo.save_message(_draft(business_id))

    repo.save_message(draft.model_copy(update={"status": OutreachStatus.REJECTED}),
                      expecting="draft")

    after = _stored(repo, business_id, draft.id)
    assert after is not None and after.status is OutreachStatus.REJECTED


def test_an_expectation_that_is_not_a_status_is_refused_immediately(repo, business_id):
    """A misspelled expectation would otherwise match nothing for ever and look
    exactly like losing every race — a guard that silently never passes is
    indistinguishable from a system under permanent contention."""
    draft = repo.save_message(_draft(business_id))

    with pytest.raises(ValueError) as complaint:
        repo.save_message(draft.model_copy(update={"status": OutreachStatus.SENT}),
                          expecting="approved_for_manual_sending")

    assert "not an outreach status" in str(complaint.value)
    after = _stored(repo, business_id, draft.id)
    assert after is not None and after.status is OutreachStatus.DRAFT


def test_the_guarded_write_touches_the_same_columns_as_the_unguarded_one(
        repo, business_id):
    """The guarded save is the same write, guarded — not a different one.

    The upsert deliberately never rewrites the words on conflict: `subject` and
    `body` are what somebody approved. A guarded save that started rewriting
    them would let an expectation about *status* carry an edit of the message
    past a fingerprint nobody checked."""
    guarded = repo.save_message(_draft(business_id))
    unguarded = repo.save_message(_draft(business_id))

    repo.save_message(
        guarded.model_copy(update={"status": OutreachStatus.APPROVED,
                                   "subject": "rewritten", "body": "rewritten"}),
        expecting=OutreachStatus.DRAFT)
    repo.save_message(
        unguarded.model_copy(update={"status": OutreachStatus.APPROVED,
                                     "subject": "rewritten", "body": "rewritten"}))

    after_guarded = _stored(repo, business_id, guarded.id)
    after_unguarded = _stored(repo, business_id, unguarded.id)
    assert after_guarded is not None and after_unguarded is not None
    assert after_guarded.status is after_unguarded.status is OutreachStatus.APPROVED
    assert after_guarded.subject == after_unguarded.subject == guarded.subject
    assert after_guarded.body == after_unguarded.body == guarded.body


# ------------------------------------------- nothing else moved: the old path

def test_a_save_with_no_expectation_still_creates_the_row(repo, business_id):
    draft = _draft(business_id)
    returned = repo.save_message(draft)

    assert returned is draft, "the unconditional save still returns its argument"
    stored = _stored(repo, business_id, draft.id)
    assert stored is not None and stored.status is OutreachStatus.DRAFT


def test_a_save_with_no_expectation_still_overwrites_blindly(repo, business_id):
    """The behaviour every existing caller depends on, kept exactly.

    This is also the race, written down. A stale copy saved with no expectation
    still replaces a recorded send — which is why the guard is opt-in and why
    the callers that read-then-write have to be moved onto it deliberately,
    one at a time, rather than by changing what this line means underneath
    them."""
    draft = repo.save_message(_draft(business_id))
    _somebody_else_sends(repo, draft)

    repo.save_message(draft.model_copy(
        update={"status": OutreachStatus.APPROVED_FOR_MANUAL_SEND}))

    after = _stored(repo, business_id, draft.id)
    assert after is not None
    assert after.status is OutreachStatus.APPROVED_FOR_MANUAL_SEND
    assert after.provider_message_id is None, "still an unconditional overwrite"


def test_a_save_with_no_expectation_updates_in_place_as_it_progresses(
        repo, business_id):
    """The property `test_opportunity_repository` already relies on: one row per
    message, moved through its states, so the contact history counts one
    contact rather than one per save."""
    draft = repo.save_message(_draft(business_id))
    repo.save_message(draft.model_copy(update={
        "status": OutreachStatus.SENT, "sent_at": datetime.now(UTC),
        "provider_message_id": "recorded-1"}))

    rows = repo.messages_for(business_id)
    assert len(rows) == 1
    assert rows[0].status is OutreachStatus.SENT
    assert rows[0].provider_message_id == "recorded-1"


def test_the_expectation_is_optional_and_keyword_only():
    """Additive, positionally and by keyword. A positional second parameter
    would change what an existing `save_message(x, y)` means, and a required
    one would change every call site at once."""
    signature = inspect.signature(OpportunityRepository.save_message)
    expecting = signature.parameters["expecting"]
    assert expecting.default is None
    assert expecting.kind is inspect.Parameter.KEYWORD_ONLY
    assert [name for name in signature.parameters
            if signature.parameters[name].kind is not inspect.Parameter.KEYWORD_ONLY
            ] == ["self", "message"]


# ------------------------------------------ nothing else moved: the callers

_PRUNED = {".git", ".venv", "venv", "node_modules", "__pycache__", ".next",
           ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build",
           "site-packages"}


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _python_sources() -> list[Path]:
    found: list[Path] = []
    for directory, subdirectories, files in os.walk(_repository_root()):
        subdirectories[:] = [d for d in subdirectories if d not in _PRUNED]
        found.extend(Path(directory) / name for name in files
                     if name.endswith(".py"))
    return found


def _save_message_calls() -> list[tuple[Path, ast.Call]]:
    calls: list[tuple[Path, ast.Call]] = []
    for path in _python_sources():
        if path.name == Path(__file__).name:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # not ours to police
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (node.func.attr if isinstance(node.func, ast.Attribute)
                    else node.func.id if isinstance(node.func, ast.Name) else "")
            if name == "save_message":
                calls.append((path, node))
    return calls


def test_no_existing_caller_names_an_expectation():
    """Read, not assumed. The claim being made about this change is that every
    call site in the repository is on the unconditional path — which is a fact
    about the source, so the source is what is checked.

    The moment a caller is rewired onto the guard, this test is the thing that
    says so out loud, and whoever does it has to come back here and say which
    caller and why."""
    calls = _save_message_calls()
    reached = {str(path.relative_to(_repository_root())) for path, _ in calls}
    # Anchored to the four production callers rather than to a count alone. A
    # scan that quietly stopped reaching them would still find the tests and
    # still pass, and would be proving nothing about the code that runs.
    for caller in ("packages/kernel/atlas_kernel/opportunity/service.py",
                   "packages/kernel/atlas_kernel/mission/api.py",
                   "infra/approve_send.py",
                   "infra/outreach_drafts.py"):
        assert caller in reached, (
            f"{caller} calls save_message and the scan did not reach it; this "
            "test proves nothing until it does")
    named = [f"{path}:{call.lineno}" for path, call in calls
             if any(keyword.arg == "expecting" for keyword in call.keywords)
             or len(call.args) > 1]
    assert not named, f"a caller already passes an expectation: {named}"
