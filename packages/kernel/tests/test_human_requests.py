"""Questions only a person can answer, and the responses they may be given.

The safety property of this module is what it **refuses**. A permissive answer
path would let a casual "yes" in a conversation authorise a message to a real
business, and the whole approval boundary would be one careless reply from
being gone. So most of what follows is negative controls.
"""

from __future__ import annotations

import pytest

from atlas_kernel import db
from atlas_kernel.controlplane import human
from atlas_kernel.controlplane.actions import ActionKind
from atlas_kernel.controlplane.human import (
    NotAcceptable,
    RequestState,
    ResponseKind,
)


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()
    human.ensure_schema()


def _clean(request_id: str) -> None:
    from sqlalchemy import text

    from atlas_kernel.db import SessionLocal
    with SessionLocal() as s:
        s.execute(text("DELETE FROM qevik_human_responses WHERE request_id=:i"),
                  {"i": request_id})
        s.execute(text("DELETE FROM qevik_human_requests WHERE id=:i"),
                  {"i": request_id})
        s.commit()


def _question(subject="Collect individual addresses as well as business ones?"):
    return human.raise_request(
        kind=ActionKind.QUESTION, subject=subject,
        title="Should Qevik collect individual contact addresses?",
        why="Contact discovery reads addresses a page publishes.",
        asked="Answer in your own words.",
        created_by="test")


# ------------------------------------------------------------- idempotence


def test_the_same_boundary_raised_four_ways_is_one_request():
    """The dedup requirement, in the shape it actually arrives.

    "SMTP required", "SMTP credential required", "email credential missing"
    and "mail configuration needed" must not become four rows. They reduce to
    one subject, and the id is derived from it.
    """
    ids = {human.raise_request(kind=ActionKind.CREDENTIAL, subject="smtp",
                               title=t, why="w", created_by="test")
           for t in ("SMTP required", "SMTP credential required",
                     "Email credential missing", "Mail configuration needed")}
    try:
        assert len(ids) == 1, f"one boundary produced {len(ids)} requests"
        # Negative control: a genuinely different boundary is its own request.
        other = human.raise_request(kind=ActionKind.CREDENTIAL, subject="dns",
                                    title="DNS", why="w", created_by="test")
        assert other not in ids
        _clean(other)
    finally:
        for one in ids:
            _clean(one)


# ------------------------------------------------ what each kind will accept


def test_a_question_cannot_be_approved():
    """Approving something nobody showed you is not approval."""
    ident = _question()
    try:
        with pytest.raises(NotAcceptable, match="does not accept"):
            human.answer(ident, response=ResponseKind.APPROVE, actor="ayoub")
        # Negative control: the response it *does* accept works, so the refusal
        # above is the rule and not a broken fixture.
        got = human.answer(ident, response=ResponseKind.ANSWER, actor="ayoub",
                           body="Yes, but keep them in a separate field.")
        assert got["state"] == RequestState.ANSWERED.value
    finally:
        _clean(ident)


def test_conversation_never_authorises_an_external_action():
    """The requirement this file exists for.

    A person typing "yes, go ahead" is not looking at the recipient, the
    channel or the words. An external action is authorised by repeating exactly
    what it says will happen, and nothing else.
    """
    ident = human.raise_request(
        kind=ActionKind.EXTERNAL_ACTION, subject="send health check to apex",
        title="Send the health check to Apex Plumbing",
        why="An artefact is published and a person approved the opportunity.",
        asked="Send this exact message to 056 729 2004 on WhatsApp.",
        reversible=False, created_by="test")
    try:
        with pytest.raises(NotAcceptable, match="does not accept"):
            human.answer(ident, response=ResponseKind.ANSWER, actor="ayoub",
                         body="yes go ahead")
        with pytest.raises(NotAcceptable, match="did not match"):
            human.answer(ident, response=ResponseKind.APPROVE, actor="ayoub",
                         body="yes")
        # Only an exact repetition of what was asked authorises it.
        got = human.answer(ident, response=ResponseKind.APPROVE, actor="ayoub",
                           body="Send this exact message to 056 729 2004 on WhatsApp.")
        assert got["state"] == RequestState.APPROVED.value
    finally:
        _clean(ident)


def test_a_decision_must_choose_an_option_it_actually_offered():
    ident = human.raise_request(
        kind=ActionKind.DECISION, subject="tenant allowance",
        title="What allowance does Qevik's own tenant have?",
        why="C-27 and C-28 wait on it.",
        options=[{"key": "unlimited", "label": "Unlimited",
                  "what_changes": "Qevik's own tenant is never metered."},
                 {"key": "metered", "label": "Metered like a customer",
                  "what_changes": "Qevik's tenant spends from a quota like "
                                  "any other."}],
        created_by="test")
    try:
        with pytest.raises(NotAcceptable, match="not one of this decision"):
            human.answer(ident, response=ResponseKind.CHOOSE, actor="ayoub",
                         chosen="something-else")
        got = human.answer(ident, response=ResponseKind.CHOOSE, actor="ayoub",
                           chosen="metered")
        assert got["state"] == RequestState.ANSWERED.value
    finally:
        _clean(ident)


def test_a_credential_request_accepts_no_answer_at_all():
    """A credential is satisfied by storing it, and only the store may say so."""
    ident = human.raise_request(
        kind=ActionKind.CREDENTIAL, subject="smtp-for-test",
        title="SMTP credentials required", why="Sending has no identity.",
        created_by="test")
    try:
        for response in (ResponseKind.ANSWER, ResponseKind.APPROVE):
            with pytest.raises(NotAcceptable):
                human.answer(ident, response=response, actor="ayoub",
                             body="done")
        # Deferring is allowed: it says "not now", which authorises nothing.
        assert human.answer(ident, response=ResponseKind.DEFER,
                            actor="ayoub")["state"] == "DEFERRED"
    finally:
        _clean(ident)


# ------------------------------------------------------------ no secrets


def test_a_credential_value_cannot_be_written_into_a_request():
    with pytest.raises(NotAcceptable, match="never be written"):
        human.raise_request(kind=ActionKind.CREDENTIAL, subject="smtp-secret",
                            title="SMTP", why="w",
                            evidence={"value": "hunter2-actual-password"},
                            created_by="test")


@pytest.mark.parametrize("text", [
    "sk-abcdefghijklmnopqrstuvwxyz012345",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "password: correct-horse-battery",
])
def test_anything_shaped_like_a_secret_is_refused_not_redacted(text):
    """Refused, because redaction would still mean it had been transmitted."""
    ident = _question(subject=f"secret-probe-{abs(hash(text)) % 9999}")
    try:
        with pytest.raises(NotAcceptable, match="credential"):
            human.answer(ident, response=ResponseKind.ANSWER, actor="ayoub",
                         body=f"the setting is {text}")
        # Negative control: ordinary prose is stored.
        assert human.answer(ident, response=ResponseKind.ANSWER, actor="ayoub",
                            body="Use the shared mailbox.")["state"] == "ANSWERED"
    finally:
        _clean(ident)


# ----------------------------------------------------- verification closes


def test_saying_it_is_done_does_not_close_a_verifiable_request():
    """"DNS is configured" is a claim. The system checks it."""
    ident = human.raise_request(
        kind=ActionKind.PROVISIONING, subject="dns-for-test",
        title="DNS records required", why="Sending cannot be proved.",
        verification="MX, SPF and DMARC all resolve", created_by="test")
    try:
        got = human.answer(ident, response=ResponseKind.ANSWER, actor="ayoub",
                           body="DNS is configured.")
        assert got["state"] == RequestState.ANSWERED.value
        assert got["state"] != RequestState.COMPLETED.value, (
            "a request with a verification closed on somebody's word")
        # Only a verification that ran may complete it.
        done = human.complete(ident, verified_by="dns probe")
        assert done["state"] == RequestState.COMPLETED.value
    finally:
        _clean(ident)


def test_an_answer_is_appended_and_the_question_survives_it():
    ident = _question(subject="append-probe")
    try:
        human.answer(ident, response=ResponseKind.CONTEXT, actor="ayoub",
                     body="First thought.")
        human.answer(ident, response=ResponseKind.ANSWER, actor="ayoub",
                     body="Both kinds, stored separately.")
        found = human.get(ident)
        assert len(found["responses"]) == 2, "responses are append-only"
        assert found["title"].startswith("Should Qevik"), (
            "the original question must survive being answered")
        assert found["resolved"] is True
    finally:
        _clean(ident)


def test_resolution_is_what_the_driver_reads():
    ident = _question(subject="resolution-probe")
    try:
        assert human.is_resolved(ident) is False
        human.answer(ident, response=ResponseKind.ANSWER, actor="ayoub",
                     body="Yes.")
        assert human.is_resolved(ident) is True
        assert human.is_resolved("human-question-nothing-at-all") is False
    finally:
        _clean(ident)


# ================================================ the decision state machine
#
# A decision is the one request kind whose answer becomes a rule. Everything
# here exists so that a rule can only be made deliberately.


@pytest.mark.parametrize("options,why", [
    ([], "none at all can never be answered"),
    ([{"key": "a", "label": "A", "what_changes": "x"}], "one option is not a decision"),
    ([{"key": "a", "label": "A", "what_changes": "x"},
      {"key": "a", "label": "B", "what_changes": "y"}], "duplicate keys"),
    ([{"key": "a", "label": "", "what_changes": "x"},
      {"key": "b", "label": "B", "what_changes": "y"}], "an option with no label"),
    ([{"key": "a", "label": "A", "what_changes": ""},
      {"key": "b", "label": "B", "what_changes": "y"}], "an option that says nothing"),
])
def test_a_decision_must_be_answerable_before_it_is_asked(options, why):
    with pytest.raises(NotAcceptable):
        human.raise_request(kind=ActionKind.DECISION, subject=f"bad-{why}",
                            title="Which way?", why="w", options=options,
                            created_by="test")


def test_a_well_formed_decision_is_accepted_and_answerable():
    """The negative control for all of the above."""
    ident = human.raise_request(
        kind=ActionKind.DECISION, subject="well-formed-probe",
        title="Which way?", why="w",
        options=[{"key": "left", "label": "Go left", "what_changes": "a"},
                 {"key": "right", "label": "Go right", "what_changes": "b"}],
        created_by="test")
    try:
        got = human.answer(ident, response=ResponseKind.CHOOSE, actor="ayoub",
                           chosen="right")
        assert got["state"] == RequestState.ANSWERED.value
    finally:
        _clean(ident)


def test_prose_on_a_decision_never_becomes_the_answer():
    """Thinking aloud must not become an architectural rule.

    `CONTEXT` is how somebody adds reasoning to a decision. It must leave the
    decision open: the structured choice is the answer, and the prose beside it
    is supporting material.
    """
    ident = human.raise_request(
        kind=ActionKind.DECISION, subject="prose-probe",
        title="Which way?", why="w",
        options=[{"key": "left", "label": "Go left", "what_changes": "a"},
                 {"key": "right", "label": "Go right", "what_changes": "b"}],
        created_by="test")
    try:
        got = human.answer(ident, response=ResponseKind.CONTEXT, actor="ayoub",
                           body="I think right is probably better, do that.")
        assert got["state"] == RequestState.WAITING_FOR_INPUT.value, (
            "prose closed a decision")
        assert human.is_resolved(ident) is False, (
            "an unanswered decision reported itself resolved, so the blocked "
            "task would have resumed on a rule nobody made")
        # And the reasoning is kept, beside the still-open question.
        assert "probably better" in human.get(ident)["responses"][-1]["body"]

        # Negative control: the structured choice does resolve it.
        human.answer(ident, response=ResponseKind.CHOOSE, actor="ayoub",
                     chosen="right")
        assert human.is_resolved(ident) is True
    finally:
        _clean(ident)


def test_answering_one_decision_frees_only_its_own_blocked_tasks():
    """A decision unblocks what it was blocking, and nothing else."""
    import sys
    import tempfile
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / "infra"))
    from devloop.queue import Queue, State

    answered = human.raise_request(
        kind=ActionKind.DECISION, subject="frees-only-its-own",
        title="Which way?", why="w",
        options=[{"key": "a", "label": "A", "what_changes": "x"},
                 {"key": "b", "label": "B", "what_changes": "y"}],
        created_by="test")
    other = human.raise_request(
        kind=ActionKind.QUESTION, subject="a-different-boundary",
        title="Something else", why="w", created_by="test")
    q = Queue(_Path(tempfile.mkdtemp()) / "s.db")
    try:
        mine = [q.add(title=f"m{n}", brief="b", origin="human", paths=["infra/"]) for n in range(2)]
        theirs = q.add(title="t", brief="b", origin="human", paths=["infra/"])
        for ident, request in [(mine[0], answered), (mine[1], answered),
                               (theirs, other)]:
            q.claim(owner="d")
            q.park(ident, request_id=request, stage=State.BUILDING, sha="x",
                   reason="parked")

        human.answer(answered, response=ResponseKind.CHOOSE, actor="ayoub",
                     chosen="a")
        for ident in mine:
            assert human.is_resolved(answered) is True
            q.release(ident, because="answered")
        assert all(q.get(i)["state"] == State.QUEUED for i in mine)
        assert q.get(theirs)["state"] == State.WAITING_FOR_HUMAN, (
            "answering one decision freed a task waiting on a different one")
        assert human.is_resolved(other) is False
    finally:
        q.close()
        _clean(answered)
        _clean(other)


def test_a_posed_request_carries_every_key_the_derived_shape_guarantees():
    """One inbox must be readable one way.

    The merged list omitted `service` and four other keys, and the existing
    action-centre tests only noticed once a real posed request existed — until
    then the posed half was empty and shape-compatible by accident. A consumer
    iterating `open` must not have to ask which half a row came from.
    """
    from atlas_kernel.controlplane.actions import HumanAction

    derived_keys = set(HumanAction(
        id="x", kind=ActionKind.CREDENTIAL, title="t", service="s").summary())

    ident = human.raise_request(
        kind=ActionKind.QUESTION, subject="shape-probe",
        title="A question", why="w", created_by="test")
    try:
        posed = [r for r in human.open_requests() if r["id"] == ident][0]
        # Exactly the mapping `/api/missions/actions` performs.
        row = {"id": posed["id"], "kind": posed["kind"], "title": posed["title"],
               "service": "", "phase": "", "tenant_id": posed["tenant_id"],
               "blocking": True, "reason": posed["why"],
               "instructions": posed["asked"], "affects": [], "requires": [],
               "setup_url": "", "status": posed["state"].lower(),
               "verification": posed["verification"], "posed": True,
               "reversible": posed["reversible"], "accepts": posed["accepts"],
               "options": posed["options"], "created_at": posed["created_at"],
               "due_at": posed["due_at"], "stale": False}
        missing = derived_keys - set(row)
        assert not missing, f"a posed row is missing {sorted(missing)}"
    finally:
        _clean(ident)
