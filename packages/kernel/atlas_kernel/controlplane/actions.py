"""Everything waiting on a human, as structured records rather than a TODO list.

A blocker written in Markdown is a blocker nobody can act on: it has no status,
no owner, no verification, and no way to tell whether it still applies. §3 of the
master directive asks for the opposite — a first-class action with an id, a
reason, exact instructions, and the capabilities it holds up.

**Actions are derived, not stored.** They are folded from state that already
exists: an integration with no connection, an approval nobody has decided, a
customer task with no proof. Storing them would create a second copy of each of
those facts, and the copy would still say "connect Search Console" the day after
somebody connected it.

That choice has one consequence worth stating: an action's identity has to be
stable across derivations, or a UI cannot tell "the same action, still open"
from "a new action". So the id is derived from what the action is *about*, not
from when it was generated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..approval.models import ApprovalRequest, ApprovalState
from ..integrations.registry import INTEGRATIONS, IntegrationStatus
from ..opportunity.tenancy import TenantId
from ..opportunity.tenancy import require as _require_tenant
from ..publication.connections import ConnectionStore


class ActionKind(StrEnum):
    """What sort of human input is wanted. Different kinds go to different
    people — a credential is an operator's job, an approval is the customer's."""

    CREDENTIAL = "credential"
    APPROVAL = "approval"
    CUSTOMER_TASK = "customer_task"
    #: Something physical, or something needing an account only the owner can
    #: sign into. Distinct from a credential because no key can be pasted to
    #: satisfy it: somebody has to be in front of the machine.
    PROVISIONING = "provisioning"


class ActionStatus(StrEnum):
    OPEN = "open"
    #: Somebody acted and the system confirmed it. Derived, so an action that is
    #: done simply stops being produced — this exists for a UI that wants to
    #: show the transition rather than have rows vanish.
    SATISFIED = "satisfied"


#: How long before an open action is worth chasing. Not a deadline anybody
#: agreed to — a threshold for surfacing, so a list of thirty actions can be
#: ordered by which have been ignored longest.
STALE_AFTER = timedelta(days=7)


class HumanAction(BaseModel):
    """One thing a person has to do, with everything needed to do it."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: ActionKind
    title: str
    #: The provider or subject this concerns.
    service: str
    #: Roadmap phase, where the action belongs to one.
    phase: str = ""
    tenant_id: str = ""
    #: True when work is stopped until this happens. False when it is merely
    #: worth doing — the distinction is what stops a list of thirty actions
    #: reading as thirty emergencies.
    blocking: bool = True
    reason: str = ""
    #: What to actually do. Written for the person, not for the system.
    instructions: str = ""
    #: What they will be asked for. Names of things, never values.
    requires: tuple[str, ...] = ()
    setup_url: str = ""
    #: Capability or measurement ids held up by this.
    affects: tuple[str, ...] = ()
    status: ActionStatus = ActionStatus.OPEN
    #: How the system will know it is done. Every action has one, or it is a
    #: request with no way to close it.
    verification: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    due_at: datetime | None = None

    @property
    def stale(self) -> bool:
        return datetime.now(UTC) - self.created_at > STALE_AFTER

    def summary(self) -> dict:
        return {
            "id": self.id, "kind": self.kind.value, "title": self.title,
            "service": self.service, "phase": self.phase,
            "tenant_id": self.tenant_id, "blocking": self.blocking,
            "reason": self.reason, "instructions": self.instructions,
            "requires": list(self.requires), "setup_url": self.setup_url,
            "affects": list(self.affects), "status": self.status.value,
            "verification": self.verification,
            "created_at": self.created_at.isoformat(),
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "stale": self.stale,
        }


def _identity(kind: ActionKind, service: str, tenant: str, subject: str = "") -> str:
    """Stable across derivations. The same open action keeps the same id."""
    parts = [kind.value, service, tenant, subject]
    return "action-" + "-".join(p for p in parts if p).replace(" ", "-").lower()[:96]


def credential_actions(store: ConnectionStore, *, tenant: TenantId | None,
                       created_at: datetime | None = None) -> tuple[HumanAction, ...]:
    """One action per integration this tenant has not connected.

    `adapter_ready=False` produces nothing: "we have not built this" is our
    move, not the customer's, and putting it on their list would ask them to
    supply a credential for something that could not use it yet.
    """
    tenant = _require_tenant(tenant, method="controlplane.credential_actions")
    at = created_at or datetime.now(UTC)
    found = []
    for integration in INTEGRATIONS:
        state = integration.status(store, tenant=tenant)
        if state is not IntegrationStatus.PENDING_CREDENTIAL:
            continue
        found.append(HumanAction(
            id=_identity(ActionKind.CREDENTIAL, integration.id, str(tenant)),
            kind=ActionKind.CREDENTIAL,
            title=f"Connect {integration.name}",
            service=integration.id, tenant_id=str(tenant),
            # Blocking only when something actually depends on it.
            blocking=bool(integration.blocks),
            reason=integration.purpose,
            instructions=(f"Add {integration.credential}"
                          + (f" — get one at {integration.setup_url}"
                             if integration.setup_url else "")
                          + ". The value is stored as a reference and is never "
                            "shown again."),
            requires=(integration.credential,),
            setup_url=integration.setup_url,
            affects=integration.blocks,
            # Asked of the integration rather than assumed here. A single
            # sentence written at this level would be wrong for every entry
            # whose real test is not "a connection row exists".
            verification=integration.verifies_by(),
            created_at=at))
    return tuple(found)


def approval_actions(pending: list[ApprovalRequest], *, tenant: TenantId | None,
                     created_at: datetime | None = None) -> tuple[HumanAction, ...]:
    """One action per approval nobody has decided.

    Reads approvals rather than creating them: this module has no way to approve
    anything, and a control plane that could satisfy its own approvals would be
    a control plane with no control in it.
    """
    tenant = _require_tenant(tenant, method="controlplane.approval_actions")
    at = created_at or datetime.now(UTC)
    found = []
    for request in pending:
        if request.state is not ApprovalState.PENDING:
            continue
        if request.metadata.get("tenant_id") not in (None, "", str(tenant)):
            continue
        found.append(HumanAction(
            id=_identity(ActionKind.APPROVAL, request.action or "approval",
                         str(tenant), request.id),
            kind=ActionKind.APPROVAL,
            title=request.title or "Approve work",
            service=request.action or "approval", tenant_id=str(tenant),
            blocking=True,
            reason="Work is waiting on a decision.",
            instructions="Review what is proposed and approve or reject it.",
            affects=(request.action,) if request.action else (),
            verification=f"approval {request.id} leaves PENDING",
            created_at=request.created_at or at,
            due_at=request.expires_at))
    return tuple(found)


def customer_task_actions(outstanding: tuple[dict, ...], *, tenant: TenantId | None,
                          created_at: datetime | None = None) -> tuple[HumanAction, ...]:
    """One action per customer obligation with no proof yet.

    Takes what `customer.tasks.outstanding` already computed rather than
    recomputing it, so the control plane and the customer's own task list cannot
    disagree about what is outstanding.
    """
    tenant = _require_tenant(tenant, method="controlplane.customer_task_actions")
    at = created_at or datetime.now(UTC)
    return tuple(
        HumanAction(
            id=_identity(ActionKind.CUSTOMER_TASK, "roadmap", str(tenant),
                         entry.get("task_id", "")),
            kind=ActionKind.CUSTOMER_TASK,
            title=entry.get("title", "Customer task"),
            service="roadmap", tenant_id=str(tenant),
            blocking=bool(entry.get("unblocks")),
            reason=entry.get("why", ""),
            instructions=entry.get("do", ""),
            affects=tuple(entry.get("unblocks") or ()),
            verification="the task is recorded complete with proof",
            created_at=at)
        for entry in outstanding)


#: Machines the documented compute topology expects, and what it takes to make
#: one of them join the fleet.
#:
#: Declared as data because the steps are the same for both boxes and were
#: otherwise only in a shell script's closing message, which nothing reads. It
#: is **not** a claim that either machine exists, is powered on, or is owned —
#: it is what would have to happen for one to appear in `atlas_workers`.
#:
#: Nothing here schedules GPU work. No agent declares a GPU tool, so a node
#: joining today advertises the same CPU tools as any other worker; that is a
#: product decision and not this list's business.
EXPECTED_NODES: tuple[dict, ...] = (
    {"name": "atlas-z8", "title": "HP Z8 — join the fleet",
     "detail": "multi-GPU workstation"},
    {"name": "atlas-lenovo", "title": "Lenovo i9 — join the fleet",
     "detail": "single-GPU workstation"},
)

#: The same sequence for both machines. Ubuntu 24.04, one image, one playbook.
_NODE_STEPS = (
    "1. On the machine: sudo bash infra/provision_node.sh, reboot, run it "
    "again. It installs the NVIDIA driver, Docker and the container toolkit, "
    "and verifies a container can see the GPU.\n"
    "2. sudo tailscale up --hostname={name} — this opens a URL you approve in "
    "a browser, which is why nobody else can do it for you.\n"
    "3. Set ATLAS_DATABASE_URL to reach Postgres over the tailnet, then start "
    "the worker with --name {name} --agent <role> --placement cloud.\n"
    "The worker registers itself, so nothing needs to be told it is coming."
)


def node_actions(known: tuple[str, ...] | None, *,
                 tenant: TenantId | None = None) -> tuple[HumanAction, ...]:
    """One action per expected machine that has not registered itself.

    `known is None` means the fleet could not be read, and that is not the same
    as no machine having joined. Asking somebody to go and provision a box that
    is already running because a query failed is exactly the wrong instruction,
    so an unreadable fleet produces no actions at all.

    Not blocking. Nothing today needs these machines — no agent declares a GPU
    tool — and marking them blocking would put two permanent emergencies at the
    top of a list whose whole value is that its top is real.
    """
    if known is None:
        return ()
    tenant_id = str(tenant or "")
    joined = {name.split(":", 1)[0] for name in known}
    return tuple(
        HumanAction(
            id=_identity(ActionKind.PROVISIONING, node["name"], tenant_id),
            kind=ActionKind.PROVISIONING,
            title=node["title"],
            service=node["name"],
            tenant_id=tenant_id,
            blocking=False,
            reason=f"The {node['detail']} has never registered with the fleet. "
                   "Nothing is waiting on it today.",
            instructions=_NODE_STEPS.format(name=node["name"]),
            requires=("physical access to the machine", "a Tailscale login"),
            affects=(),
            verification=f"a worker whose machine is {node['name']} appears in "
                         "Fabric and reports a heartbeat",
        )
        for node in EXPECTED_NODES
        if not any(name == node["name"] or name.startswith(node["name"])
                   for name in joined)
    )


def sending_identity_actions(measured: object | None, *,
                             tenant: TenantId | None = None
                             ) -> tuple[HumanAction, ...]:
    """What the sending domain still needs before mail is worth sending.

    Separate from the `smtp` credential action, because they are different
    blockers with different fixes and satisfying one does nothing for the other:
    the credential is five settings in the environment, this is DNS records in
    Cloudflare, and a channel that reports itself configured while the domain
    proves nothing sends mail straight to spam.

    Blocking, unlike the provisioning actions. Outreach is the current
    commercial track and this genuinely stops it.

    `measured is None`, or a measurement where nothing could be read, produces
    **no action**. An unreachable resolver is not a missing DNS record, and
    telling somebody to create records that already exist is how a working zone
    gets broken by a well-meant edit.
    """
    if measured is None or getattr(measured, "unreadable", True):
        return ()
    missing = tuple(getattr(measured, "missing", ()))
    if not missing:
        return ()
    domain = getattr(measured, "domain", "")
    tenant_id = str(tenant or "")
    return (HumanAction(
        id=_identity(ActionKind.PROVISIONING, f"dns:{domain}", tenant_id),
        kind=ActionKind.PROVISIONING,
        title=f"{domain} cannot send mail anybody will accept",
        service=f"dns:{domain}",
        tenant_id=tenant_id,
        blocking=True,
        reason="; ".join(
            f"{record.name}: {record.matters_because}"
            for record in getattr(measured, "records", ())
            if record.name in missing),
        instructions=(
            "Cloudflare holds this zone and Qevik has no token for it, so every "
            "record is created by hand in the Cloudflare dashboard. The exact "
            "values and the order to create them are in "
            "docs/qevik-docs/70_EMAIL_INFRASTRUCTURE.md — the verification TXT "
            "must exist before a DKIM key can be generated."),
        requires=tuple(f"a DNS {name} record on {domain}" for name in missing),
        setup_url="https://dash.cloudflare.com/",
        affects=("outreach:send",),
        verification=(
            f"dig finds {', '.join(missing)} on {domain}. This check re-runs on "
            "every read of the action centre, so the entry disappears by "
            "itself once the records resolve."),
    ),)


def centre(*, store: ConnectionStore, tenant: TenantId | None,
           pending_approvals: list[ApprovalRequest] | None = None,
           outstanding_tasks: tuple[dict, ...] = (),
           known_nodes: tuple[str, ...] | None = None,
           sending_identity: object | None = None) -> dict:
    """Everything waiting on a person, ordered by what it holds up.

    Blocking first, then by how long it has been ignored. A list ordered by
    creation puts the oldest harmless request above the one stopping today's
    work, which is how action centres get abandoned.
    """
    actions = (
        credential_actions(store, tenant=tenant)
        + approval_actions(pending_approvals or [], tenant=tenant)
        + customer_task_actions(outstanding_tasks, tenant=tenant)
        + node_actions(known_nodes, tenant=tenant)
        + sending_identity_actions(sending_identity, tenant=tenant)
    )
    ordered = sorted(actions, key=lambda a: (not a.blocking, a.created_at))
    return {
        "open": [a.summary() for a in ordered],
        "blocking": [a.summary() for a in ordered if a.blocking],
        "counts": {
            "total": len(ordered),
            "blocking": sum(1 for a in ordered if a.blocking),
            "stale": sum(1 for a in ordered if a.stale),
            **{kind.value: sum(1 for a in ordered if a.kind is kind)
               for kind in ActionKind},
        },
        "note": "Nothing here holds a credential value. An action names what is "
                "needed; the value is stored as a reference once supplied.",
    }
