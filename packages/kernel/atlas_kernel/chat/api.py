"""The chat surface. Nothing here runs anything.

A message becomes a conversation turn. A conversation becomes a proposed plan. A
plan is shown, and a person approves it. Approval appends a queued mission to
the timeline and returns — a worker in another process picks it up.

The route that would be convenient and is deliberately absent is "send a message
and do what it says". That route would make natural language the authorisation
boundary, and natural language arrives here already contaminated: a plan is
written by a model that has read the customer's website, their emails and their
research. Requiring a person to look at the plan first is what keeps a prompt
injection a proposal rather than an action.

`test_chat.py` reads this module for `subprocess`, `Worker(`, `GitWorkspace` and
friends, because that property is exactly the kind that stays true in the
docstring after it stops being true in the code.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth.api import current_user, requires
from ..auth.models import Scope, User
from ..opportunity.tenancy import TenantId
from . import planner, service
from .models import Conversation, Role
from .service import PlanRejected

#: Identical for a conversation that does not exist and one belonging to
#: somebody else. The difference would say which ids exist.
NOT_FOUND = "no such conversation"


def current_tenant(user: User = Depends(current_user)) -> TenantId:
    tenant = (user.tenant_id or "").strip()
    if not tenant:
        raise HTTPException(
            status_code=403,
            detail="this account is not attached to a tenant, so it has no "
                   "conversations of its own.")
    return tenant


def _events(request: Request) -> list:
    source = getattr(request.app.state, "chat_events", None)
    return list(source or [])


def _append(request: Request, *events: Any) -> None:
    """Persist, or refuse. Never a silent no-op.

    A conversation that returns 200 and persists nothing is a conversation the
    person re-opens to find empty, having watched Qevik agree to something.
    """
    sink = getattr(request.app.state, "chat_sink", None)
    if sink is None:
        raise HTTPException(
            status_code=503,
            detail="no conversation store is configured to write to, so this "
                   "would have been accepted and lost")
    for event in events:
        sink(event)


def _mission_sink(request: Request) -> Any:
    sink = getattr(request.app.state, "mission_sink", None)
    if sink is None:
        raise HTTPException(
            status_code=503,
            detail="no mission timeline is configured, so an approved plan "
                   "would be accepted and never run")
    return sink


def _one(request: Request, conversation_id: str, tenant: TenantId) -> dict:
    for summary in service.fold(_events(request), tenant=tenant):
        if summary.get("conversation_id") == conversation_id:
            return summary
    raise HTTPException(status_code=404, detail=NOT_FOUND)


def _load(request: Request, conversation_id: str,
          tenant: TenantId) -> Conversation:
    try:
        return service.rehydrate(_one(request, conversation_id, tenant),
                                 tenant=tenant)
    except PlanRejected as refused:              # pragma: no cover - fold scopes
        raise HTTPException(status_code=404, detail=NOT_FOUND) from refused


class Opening(BaseModel):
    """The first thing somebody says."""

    text: str = Field(min_length=1, max_length=service.MAX_MESSAGE)
    business_id: str = Field(default="", max_length=200)


class Said(BaseModel):
    text: str = Field(min_length=1, max_length=service.MAX_MESSAGE)


class Verdict(BaseModel):
    """A person's answer to a proposed plan.

    No `approved_by`: the approver is the authenticated session, and a field for
    it would be a field to lie in.
    """

    approved: bool
    why: str = Field(default="", max_length=2000)
    #: Which repository the resulting mission is about, by name. Empty means
    #: Qevik's own source, which is the right default here and needs a person
    #: either way. A key from the worker's allow-list, never a path.
    origin: str = Field(default="", max_length=64)


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/chat", tags=["chat"])

    @router.get("")
    def listing(request: Request, tenant: TenantId = Depends(current_tenant),
                _: User = Depends(requires(Scope.READ))) -> dict:
        found = service.fold(_events(request), tenant=tenant)
        return {
            "conversations": found,
            "counts": {
                "total": len(found),
                "awaiting_approval": sum(1 for c in found
                                         if c.get("status") == "plan_proposed"),
            },
        }

    @router.post("", status_code=201)
    def open_conversation(body: Opening, request: Request,
                          tenant: TenantId = Depends(current_tenant),
                          user: User = Depends(requires(Scope.READ))) -> dict:
        """Start a conversation. READ, because saying something runs nothing."""
        try:
            conversation, event = service.start(
                tenant=tenant, text=body.text, started_by=user.username,
                business_id=body.business_id)
        except PlanRejected as refused:
            raise HTTPException(status_code=422, detail=str(refused)) from refused
        _append(request, event)
        return conversation.summary()

    @router.get("/{conversation_id}")
    def detail(conversation_id: str, request: Request,
               tenant: TenantId = Depends(current_tenant),
               _: User = Depends(requires(Scope.READ))) -> dict:
        return _one(request, conversation_id, tenant)

    @router.get("/{conversation_id}/history")
    def turns(conversation_id: str, request: Request,
              tenant: TenantId = Depends(current_tenant),
              _: User = Depends(requires(Scope.READ))) -> dict:
        """Every turn, oldest first. Establishes the conversation first, so an
        id belonging to somebody else is absent rather than empty."""
        _one(request, conversation_id, tenant)
        return {"conversation_id": conversation_id,
                "history": service.history(_events(request), conversation_id,
                                           tenant=tenant)}

    @router.post("/{conversation_id}/messages")
    def say(conversation_id: str, body: Said, request: Request,
            tenant: TenantId = Depends(current_tenant),
            _: User = Depends(requires(Scope.READ))) -> dict:
        conversation = _load(request, conversation_id, tenant)
        try:
            updated, event = service.send(conversation, tenant=tenant,
                                          text=body.text, role=Role.USER)
        except PlanRejected as refused:
            raise HTTPException(status_code=422, detail=str(refused)) from refused
        _append(request, event)
        return updated.summary()

    @router.post("/{conversation_id}/plan")
    def propose(conversation_id: str, request: Request,
                tenant: TenantId = Depends(current_tenant),
                _: User = Depends(requires(Scope.EXECUTE))) -> dict:
        """Ask a model for a plan. Produces a proposal, never an action.

        EXECUTE rather than READ: planning spends money at a provider even
        though it changes nothing here.

        With no model configured this returns a plan whose only content is a
        blocker naming the credential. It does **not** return a template — a
        template plan looks like understanding, gets approved, and queues steps
        nobody derived from the request.
        """
        conversation = _load(request, conversation_id, tenant)
        credentials = getattr(request.app.state, "credentials", None)
        if credentials is None:
            raise HTTPException(status_code=503,
                                detail="no credential vault is configured, so "
                                       "no planning model can be resolved")
        selections = getattr(request.app.state, "model_selections", None)
        selection = selections.get(tenant=tenant) if selections else None

        proposal = planner.propose(conversation, tenant=tenant,
                                   credentials=credentials, selection=selection)
        try:
            updated, event = service.plan_for(
                conversation, proposal.plan, tenant=tenant,
                provider=proposal.provider, model=proposal.model)
        except PlanRejected as refused:
            raise HTTPException(status_code=409, detail=str(refused)) from refused
        _append(request, event)
        return {**updated.summary(), "proposal": proposal.summary(),
                "blocked": proposal.blocked}

    @router.post("/{conversation_id}/decide")
    def decide(conversation_id: str, body: Verdict, request: Request,
               tenant: TenantId = Depends(current_tenant),
               user: User = Depends(requires(Scope.EXECUTE))) -> dict:
        """Approve or decline the proposed plan.

        Approving appends a queued mission and returns. It does not run it: the
        worker is a separate process, which is why the response says the page
        can be closed.
        """
        conversation = _load(request, conversation_id, tenant)

        if not body.approved:
            try:
                updated, event = service.reject(conversation, tenant=tenant,
                                                rejected_by=user.username,
                                                why=body.why)
            except PlanRejected as refused:
                raise HTTPException(status_code=409,
                                    detail=str(refused)) from refused
            _append(request, event)
            return {**updated.summary(), "mission_id": "",
                    "note": "declined. The plan is kept on the conversation."}

        # Resolved before anything is appended: approving into a deployment with
        # no mission timeline would mark the conversation approved and queue
        # nothing, which is the one outcome worse than refusing.
        sink = _mission_sink(request)
        try:
            updated, mission, events = service.approve(
                conversation, tenant=tenant, approved_by=user.username,
                origin_name=body.origin)
        except PlanRejected as refused:
            raise HTTPException(status_code=409, detail=str(refused)) from refused

        chat_events = [e for e in events if e.factory == "chat"]
        for event in (e for e in events if e.factory != "chat"):
            sink(event)
        _append(request, *chat_events)
        return {**updated.summary(), "mission_id": mission.id,
                "mission_status": mission.status.value,
                "note": "queued. It runs in a separate process, so closing "
                        "this page does not stop it."}

    return router


def install(app: Any) -> None:
    app.include_router(build_router())
    if getattr(app.state, "chat_events", None) is None:
        # One list, read and appended. `ConversationStore.read()` returns a copy
        # — correct for a reader, and wrong here: the sink would append to the
        # store while every read saw the snapshot taken at start-up, so a
        # conversation would be written and never appear.
        turns: list = []
        app.state.chat_events = turns
        app.state.chat_sink = turns.append
