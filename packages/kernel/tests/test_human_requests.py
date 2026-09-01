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
        options=[{"key": "unlimited", "label": "Unlimited"},
                 {"key": "metered", "label": "Metered like a customer"}],
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


def test_a_decision_with_no_options_is_refused_at_creation():
    """It could never be answered, and the person would find that out.

    A decision is answered by naming one of its options. Raised without any,
    it sits in the inbox accepting only `defer` and `cancel` — which is what
    happened the first time the driver parked a real boundary.

    The caller that would otherwise keep hitting this is the development loop's
    boundary classifier, which asks a question instead. That half is held by
    `test_no_boundary_becomes_a_decision_the_driver_cannot_state_options_for`
    in `test_devloop.py`, because the mapping is the driver's.
    """
    with pytest.raises(NotAcceptable, match="state the options"):
        human.raise_request(kind=ActionKind.DECISION, subject="no-options",
                            title="Which way?", why="w", created_by="test")
    # Negative control: with options stated, the same call is accepted. Without
    # this the refusal above would also pass on a `raise_request` that refused
    # every decision.
    ident = human.raise_request(
        kind=ActionKind.DECISION, subject="options-stated",
        title="Which way?", why="w", created_by="test",
        options=[{"key": "left", "label": "Left"},
                 {"key": "right", "label": "Right"}])
    try:
        assert human.get(ident)["state"] == RequestState.WAITING_FOR_INPUT.value
    finally:
        _clean(ident)
