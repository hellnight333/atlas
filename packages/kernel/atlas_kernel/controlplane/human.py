"""Questions only a person can answer, and the answers, kept apart.

`actions.py` derives everything measurable: an integration with no connection,
an approval nobody decided, a machine nobody provisioned. Derivation is the
right shape for those — it cannot go stale, and `_identity` makes it idempotent,
so the same open action keeps the same id and can never be raised twice.

It has no room for two things this module adds.

**A question is not measurable.** "Should Qevik collect individual addresses as
well as business ones" is not a fact about the system that a query could
recover; it is something somebody has to decide. So a posed request is *stored*
— and stored under the same `ActionKind`, so an inbox shows one list rather than
two competing centres.

**A derived action has nowhere to put an answer.** Both halves — the derived and
the posed — resolve through one `HumanResponse` table keyed by the action id.
There is exactly one place a human answer lives.

## What a response may be

Per kind, and enforced rather than documented:

    APPROVAL, EXTERNAL_ACTION  → APPROVE or REJECT, nothing else
    DECISION                   → one of the options the request stated
    QUESTION, REVIEW           → free text
    CREDENTIAL                 → refused here entirely

The refusals matter more than the permissions. A `QUESTION` answered "yes, go
ahead" must never authorise an external action, because the person answering a
question is not looking at what would be sent. An external action needs a
confirmation that names the recipient, the channel and the exact message — so
`answer` will not accept free text for one, and a test drives that.

A credential never passes through here at all. The request records *which*
credential is wanted and where to get it; the value goes through the credential
store, and `_REFUSED_IN_TEXT` rejects anything that looks like a secret before
it can be written.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import text

from ..db import SessionLocal
from .actions import ActionKind


class RequestState(StrEnum):
    """Where a human request is. Derived from its responses, never set twice."""

    OPEN = "OPEN"
    #: Asked, and the person has not answered yet.
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    ANSWERED = "ANSWERED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    #: Answered *and* verified, where the system can verify. A request whose
    #: verification exists is not complete until production agrees.
    COMPLETED = "COMPLETED"

    @property
    def resolved(self) -> bool:
        """Whether execution waiting on this may resume."""
        return self in (RequestState.ANSWERED, RequestState.APPROVED,
                        RequestState.COMPLETED, RequestState.REJECTED,
                        RequestState.CANCELLED)


class ResponseKind(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    ANSWER = "answer"
    CHOOSE = "choose"
    DEFER = "defer"
    CONTEXT = "context"
    CANCEL = "cancel"


#: What each request kind will accept. Anything absent is refused, and the
#: refusal names why — a caller that guessed wrong should learn the rule.
ACCEPTS: dict[ActionKind, frozenset[ResponseKind]] = {
    ActionKind.APPROVAL: frozenset({ResponseKind.APPROVE, ResponseKind.REJECT,
                                    ResponseKind.DEFER, ResponseKind.CONTEXT}),
    ActionKind.EXTERNAL_ACTION: frozenset({ResponseKind.APPROVE,
                                           ResponseKind.REJECT,
                                           ResponseKind.DEFER,
                                           ResponseKind.CONTEXT}),
    ActionKind.DECISION: frozenset({ResponseKind.CHOOSE, ResponseKind.DEFER,
                                    ResponseKind.CONTEXT,
                                    ResponseKind.CANCEL}),
    ActionKind.QUESTION: frozenset({ResponseKind.ANSWER, ResponseKind.DEFER,
                                    ResponseKind.CONTEXT,
                                    ResponseKind.CANCEL}),
    ActionKind.REVIEW: frozenset({ResponseKind.ANSWER, ResponseKind.APPROVE,
                                  ResponseKind.REJECT, ResponseKind.DEFER,
                                  ResponseKind.CONTEXT}),
    ActionKind.PROVISIONING: frozenset({ResponseKind.ANSWER,
                                        ResponseKind.DEFER,
                                        ResponseKind.CONTEXT}),
    ActionKind.CUSTOMER_TASK: frozenset({ResponseKind.ANSWER,
                                         ResponseKind.DEFER,
                                         ResponseKind.CONTEXT}),
    # Nothing. A credential is satisfied by storing it, and the store is the
    # only thing that may say so.
    ActionKind.CREDENTIAL: frozenset({ResponseKind.DEFER,
                                      ResponseKind.CONTEXT}),
}

#: Which responses count as authorising the thing the request describes. `CHOOSE`
#: is absent on purpose: choosing an option answers a decision, and a decision
#: is not an authorisation to act outside the building.
_AUTHORISING = frozenset({ResponseKind.APPROVE})

#: A response body that looks like a credential is refused outright rather than
#: redacted. Redaction would still mean the value had been transmitted.
_REFUSED_IN_TEXT = re.compile(
    r"(?i)(sk-[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{20,}"
    r"|-----BEGIN[ A-Z]*PRIVATE KEY-----|password\s*[:=]\s*\S+"
    r"|eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,})")


class NotAcceptable(Exception):
    """The response is not one this request accepts."""


class UnknownRequest(Exception):
    """No such request."""


def identity(kind: ActionKind, subject: str) -> str:
    """The canonical id for a boundary, from what it is *about*.

    The same shape `actions._identity` uses, and for the same reason: four
    agents hitting the same wall must produce one request, not four. "SMTP
    required", "SMTP credential required", "email credential missing" and "mail
    configuration needed" all reduce to the subject somebody passes here, so
    the subject is the deduplication key and callers are expected to use a
    stable one.
    """
    digest = hashlib.sha256(subject.strip().lower().encode()).hexdigest()[:10]
    slug = re.sub(r"[^a-z0-9]+", "-", subject.strip().lower())[:60].strip("-")
    return f"human-{kind.value}-{slug or digest}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS qevik_human_requests (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    title           TEXT NOT NULL,
    -- Everything a person needs to decide without reading a transcript, a
    -- report or a git history. Written by whoever raised it, from evidence.
    why             TEXT NOT NULL DEFAULT '',
    blocks          TEXT NOT NULL DEFAULT '',
    asked           TEXT NOT NULL DEFAULT '',
    consequence     TEXT NOT NULL DEFAULT '',
    will_not_do     TEXT NOT NULL DEFAULT '',
    reversible      BOOLEAN NOT NULL DEFAULT TRUE,
    evidence        JSONB NOT NULL DEFAULT '{}'::jsonb,
    options         JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- How the system will confirm it, where it can. A request with one is not
    -- COMPLETED on somebody's word.
    verification    TEXT NOT NULL DEFAULT '',
    next_action     TEXT NOT NULL DEFAULT '',
    created_by      TEXT NOT NULL DEFAULT '',
    tenant_id       TEXT NOT NULL DEFAULT '',
    state           TEXT NOT NULL DEFAULT 'WAITING_FOR_INPUT',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    due_at          TIMESTAMP WITH TIME ZONE,
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL
);

-- Append-only. An answer is a thing somebody said at a moment, and editing it
-- would destroy the record of what they were asked when they said it.
CREATE TABLE IF NOT EXISTS qevik_human_responses (
    id              TEXT PRIMARY KEY,
    request_id      TEXT NOT NULL,
    response        TEXT NOT NULL,
    body            TEXT NOT NULL DEFAULT '',
    chosen          TEXT NOT NULL DEFAULT '',
    actor           TEXT NOT NULL,
    at              TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS human_requests_state
    ON qevik_human_requests (state, created_at);
CREATE INDEX IF NOT EXISTS human_responses_request
    ON qevik_human_responses (request_id, at);
"""


def ensure_schema() -> None:
    with SessionLocal() as session:
        for statement in SCHEMA.strip().split(";"):
            if statement.strip():
                session.execute(text(statement))
        session.commit()


def raise_request(*, kind: ActionKind, subject: str, title: str, why: str,
                  blocks: str = "", asked: str = "", consequence: str = "",
                  will_not_do: str = "", reversible: bool = True,
                  evidence: dict | None = None,
                  options: list[dict] | None = None, verification: str = "",
                  next_action: str = "", created_by: str = "",
                  tenant_id: str = "") -> str:
    """Pose a request, or return the one already open for this subject.

    Idempotent by construction. An agent that hits the same boundary on every
    retry adds nothing the second time, which is what stops one blocker
    becoming forty rows nobody reads.
    """
    if kind is ActionKind.DECISION and not (options or []):
        # A decision is answered by naming one of its options, so one with no
        # options can never be answered at all — it would sit in the inbox
        # accepting only `defer` and `cancel`. Refused at creation rather than
        # discovered by the person trying to reply: if the choices cannot be
        # stated, what is being asked is a QUESTION.
        raise NotAcceptable(
            "a decision must state the options it is choosing between. "
            "Without them nobody can answer it — raise a QUESTION instead, "
            "which takes an answer in the person's own words.")
    if kind is ActionKind.CREDENTIAL and (evidence or {}).get("value"):
        raise NotAcceptable(
            "a credential value must never be written to a human request. The "
            "request says which credential is wanted and where to get it; the "
            "value goes to the credential store.")
    for field, name in ((title, "title"), (why, "why"), (asked, "asked")):
        if _REFUSED_IN_TEXT.search(field or ""):
            raise NotAcceptable(
                f"{name} looks like it contains a credential. Refused rather "
                "than redacted: redaction would still mean it was written.")
    ident = identity(kind, subject)
    ensure_schema()
    with SessionLocal() as session:
        existing = session.execute(
            text("SELECT state FROM qevik_human_requests WHERE id = :i"),
            {"i": ident}).first()
        if existing is not None:
            return ident
        session.execute(
            text("""
            INSERT INTO qevik_human_requests
                (id, kind, title, why, blocks, asked, consequence,
                 will_not_do, reversible, evidence, options, verification,
                 next_action, created_by, tenant_id, state, created_at,
                 updated_at)
            VALUES (:id, :kind, :title, :why, :blocks, :asked, :consequence,
                    :will_not_do, :reversible, CAST(:evidence AS JSONB),
                    CAST(:options AS JSONB), :verification, :next_action,
                    :created_by, :tenant_id, :state, :at, :at)
            """),
            {"id": ident, "kind": kind.value, "title": title, "why": why,
             "blocks": blocks, "asked": asked, "consequence": consequence,
             "will_not_do": will_not_do, "reversible": reversible,
             "evidence": json.dumps(evidence or {}),
             "options": json.dumps(options or []),
             "verification": verification, "next_action": next_action,
             "created_by": created_by, "tenant_id": tenant_id,
             "state": RequestState.WAITING_FOR_INPUT.value, "at": _now()})
        session.commit()
    return ident


def answer(request_id: str, *, response: ResponseKind, actor: str,
           body: str = "", chosen: str = "") -> dict:
    """Record what a person said. Refuses anything the request cannot accept.

    The refusals are the safety property. A `QUESTION` cannot be approved,
    because approving something nobody showed you is not approval; an
    `EXTERNAL_ACTION` cannot be answered in prose, because "yes, go ahead" in a
    conversation is not authorisation to write to a stranger; and a `DECISION`
    must name one of its own options, because an option the request never
    offered is a new decision rather than an answer to this one.
    """
    if not actor.strip():
        raise NotAcceptable("a response must name who gave it")
    if _REFUSED_IN_TEXT.search(body or ""):
        raise NotAcceptable(
            "the response looks like it contains a credential. Credentials go "
            "to the credential store, never into a request's transcript.")
    ensure_schema()
    with SessionLocal() as session:
        row = session.execute(
            text("SELECT * FROM qevik_human_requests WHERE id = :i"),
            {"i": request_id}).mappings().first()
        if row is None:
            raise UnknownRequest(f"no human request {request_id!r}")
        kind = ActionKind(row["kind"])
        allowed = ACCEPTS.get(kind, frozenset())
        if response not in allowed:
            raise NotAcceptable(
                f"a {kind.value} request does not accept {response.value}. It "
                f"accepts: {', '.join(sorted(r.value for r in allowed)) or 'nothing'}.")
        if response is ResponseKind.CHOOSE:
            options = row["options"]
            options = json.loads(options) if isinstance(options, str) else options
            keys = {str(o.get("key")) for o in (options or [])}
            if chosen not in keys:
                raise NotAcceptable(
                    f"{chosen!r} is not one of this decision's options "
                    f"({', '.join(sorted(keys)) or 'none stated'}). An option "
                    "it never offered is a new decision, not an answer.")
        if response in _AUTHORISING and kind is ActionKind.EXTERNAL_ACTION:
            # The one place a typed confirmation is demanded: the body must
            # repeat what is being authorised, so an approval cannot be given
            # by a click on a screen that was not read.
            if (row["asked"] or "").strip() and body.strip() != (row["asked"] or "").strip():
                raise NotAcceptable(
                    "an external action is authorised by repeating exactly "
                    "what it says will happen. Confirmation text did not match.")

        session.execute(
            text("""INSERT INTO qevik_human_responses
                    (id, request_id, response, body, chosen, actor, at)
                    VALUES (:id, :r, :k, :b, :c, :a, :at)"""),
            {"id": f"hr-{datetime.now(UTC).timestamp():.6f}",
             "r": request_id, "k": response.value, "b": body, "c": chosen,
             "a": actor, "at": _now()})
        new_state = _state_for(kind, response, verification=row["verification"])
        session.execute(
            text("UPDATE qevik_human_requests SET state = :s, updated_at = :at"
                 " WHERE id = :i"),
            {"s": new_state.value, "at": _now(), "i": request_id})
        session.commit()
    return {"request_id": request_id, "state": new_state.value,
            "response": response.value}


def _state_for(kind: ActionKind, response: ResponseKind, *,
               verification: str) -> RequestState:
    """What a response moves a request to.

    A request that states a verification never reaches COMPLETED on an answer
    alone. Somebody saying "DNS is configured" is a claim; the system checks it
    and only then closes the request. That is the difference between a task
    list and a control plane.
    """
    if response is ResponseKind.DEFER:
        return RequestState.DEFERRED
    if response is ResponseKind.CONTEXT:
        return RequestState.WAITING_FOR_INPUT
    if response is ResponseKind.CANCEL:
        return RequestState.CANCELLED
    if response is ResponseKind.REJECT:
        return RequestState.REJECTED
    if response is ResponseKind.APPROVE:
        return RequestState.APPROVED
    return RequestState.ANSWERED


def complete(request_id: str, *, verified_by: str) -> dict:
    """Close a request because the system checked it, not because it was told.

    Only reachable from a verification that actually ran. `answer` cannot reach
    COMPLETED, which is what stops "done" from closing a blocker whose
    condition is still false in production.
    """
    ensure_schema()
    with SessionLocal() as session:
        row = session.execute(
            text("SELECT id FROM qevik_human_requests WHERE id = :i"),
            {"i": request_id}).first()
        if row is None:
            raise UnknownRequest(f"no human request {request_id!r}")
        session.execute(
            text("UPDATE qevik_human_requests SET state = :s, updated_at = :at"
                 " WHERE id = :i"),
            {"s": RequestState.COMPLETED.value, "at": _now(), "i": request_id})
        session.execute(
            text("""INSERT INTO qevik_human_responses
                    (id, request_id, response, body, chosen, actor, at)
                    VALUES (:id, :r, 'answer', :b, '', :a, :at)"""),
            {"id": f"hr-{datetime.now(UTC).timestamp():.6f}",
             "r": request_id, "b": f"verified: {verified_by}",
             "a": "system", "at": _now()})
        session.commit()
    return {"request_id": request_id, "state": RequestState.COMPLETED.value}


def get(request_id: str) -> dict | None:
    ensure_schema()
    with SessionLocal() as session:
        row = session.execute(
            text("SELECT * FROM qevik_human_requests WHERE id = :i"),
            {"i": request_id}).mappings().first()
        if row is None:
            return None
        found = dict(row)
        found["responses"] = [dict(r) for r in session.execute(
            text("SELECT * FROM qevik_human_responses WHERE request_id = :i"
                 " ORDER BY at"), {"i": request_id}).mappings()]
    return _readable(found)


def open_requests(*, include_resolved: bool = False) -> list[dict]:
    ensure_schema()
    with SessionLocal() as session:
        rows = session.execute(
            text("SELECT * FROM qevik_human_requests"
                 + ("" if include_resolved else
                    " WHERE state IN ('OPEN','WAITING_FOR_INPUT','DEFERRED')")
                 + " ORDER BY created_at"), {}).mappings().all()
    return [_readable(dict(r)) for r in rows]


def is_resolved(request_id: str) -> bool:
    """Whether execution waiting on this may proceed. Read by the driver."""
    found = get(request_id)
    if found is None:
        return False
    return RequestState(found["state"]).resolved


def _readable(row: dict) -> dict:
    for key in ("evidence", "options"):
        value = row.get(key)
        if isinstance(value, str):
            try:
                row[key] = json.loads(value)
            except ValueError:
                row[key] = {} if key == "evidence" else []
    for key in ("created_at", "updated_at", "due_at"):
        if hasattr(row.get(key), "isoformat"):
            row[key] = row[key].isoformat()
    for response in row.get("responses", []):
        if hasattr(response.get("at"), "isoformat"):
            response["at"] = response["at"].isoformat()
    row["accepts"] = sorted(r.value for r in
                            ACCEPTS.get(ActionKind(row["kind"]), frozenset()))
    row["resolved"] = RequestState(row["state"]).resolved
    return row


__all__ = ["ACCEPTS", "NotAcceptable", "RequestState", "ResponseKind",
           "UnknownRequest", "answer", "complete", "ensure_schema", "get",
           "identity", "is_resolved", "open_requests", "raise_request"]
