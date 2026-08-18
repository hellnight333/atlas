"""Pausing a plan when it reaches something a human must decide.

The previous boundary was a flag on submission: the operator said "publishing is
allowed" before any plan existed, and every deploy in that run inherited it.
That answers the wrong question. At submission nobody knows what will be
published, to where, or what it will say — so the consent was to a category, not
to an act.

This replaces it with consent to a specific act. When a plan reaches an action
whose category requires approval, the run **stops**, records exactly what it
proposes to do, and exits. A person reads the actual target and the actual
content, decides, and the plan resumes from that step.

Three properties do the security work.

**An approval is bound to a fingerprint of the action and its material
parameters.** Approving a deploy of *this* content to *this* slug does not
approve a different one. If the proposal changes after approval — a different
URL, different copy, a different recipient — the fingerprint changes and the
approval no longer matches, so a fresh decision is required. This is what stops
an approval being obtained for something harmless and spent on something else.

**Nothing in the plan can create an approval and satisfy it.** The gate only
*reads* decisions; approving is an authenticated HTTP call by a human with the
scope. A plan, a model and a compromised worker can all request, and none can
decide.

**A used approval is spent.** The resumed run records the step as complete
before continuing, so a replay cannot execute the same approved action twice.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..auth import Scope


class Risk(StrEnum):
    """What kind of harm the action can do, for the person deciding."""

    #: Confined to a workspace on this machine. No approval.
    INTERNAL = "internal"
    #: Reachable by the public.
    PUBLIC = "public"
    #: Reaches a named human outside the system.
    OUTBOUND = "outbound"
    #: Spends money or commits to spending it.
    FINANCIAL = "financial"
    #: Removes or overwrites something.
    DESTRUCTIVE = "destructive"


#: Which actions need a human, and why. Keyed on the action name, so a new
#: action is *unlisted* rather than silently ungated — see `classify`.
GATED_ACTIONS: dict[str, tuple[Scope, Risk]] = {
    "site.deploy": (Scope.PUBLISH, Risk.PUBLIC),
    "email.send": (Scope.COMMUNICATE, Risk.OUTBOUND),
    "message.send": (Scope.COMMUNICATE, Risk.OUTBOUND),
    "payment.create": (Scope.FINANCIAL, Risk.FINANCIAL),
    "domain.purchase": (Scope.FINANCIAL, Risk.FINANCIAL),
    "account.create": (Scope.COMMUNICATE, Risk.OUTBOUND),
    "site.remove": (Scope.DESTRUCTIVE, Risk.DESTRUCTIVE),
    "publish.upload": (Scope.PUBLISH, Risk.PUBLIC),
}

#: Actions known to be confined to this machine. Listing them explicitly means
#: an action that is neither gated nor listed here is treated as unknown, and
#: unknown is gated — a new capability should have to argue that it is harmless
#: rather than be assumed so.
INTERNAL_ACTIONS = frozenset(
    {"web.search", "code.generate", "code.write", "code.execute", "browser.operate"}
)

#: How long a request stays answerable. Long enough for someone to sleep on it,
#: short enough that a stale approval cannot be spent weeks later against a
#: world that has moved on.
DEFAULT_TTL = timedelta(hours=48)

#: Parameters that change *what* is done, as opposed to how it is reported.
#: Only these enter the fingerprint, so re-running the same publish after a
#: cosmetic change to a screenshot name does not demand a second decision —
#: while any change to the target or the content does.
MATERIAL_KEYS = frozenset(
    {
        "slug",
        "source_dir",
        "url",
        "to",
        "recipient",
        "subject",
        "body",
        "amount",
        "currency",
        "vendor",
        "account",
        "platform",
        "title",
        "description",
        "visibility",
        "public",
        "promote",
    }
)


class ApprovalOutcome(StrEnum):
    ALLOWED = "allowed"
    WAITING = "waiting"
    REJECTED = "rejected"
    EXPIRED = "expired"


def classify(action: str) -> tuple[Scope, Risk] | None:
    """What this action needs, or None if it is confined to this machine.

    An action that is neither gated nor known-internal returns a gate rather
    than a pass. Failing open on an unrecognised capability is how something
    outward-facing ships ungated because nobody remembered to list it.
    """
    if action in GATED_ACTIONS:
        return GATED_ACTIONS[action]
    if action in INTERNAL_ACTIONS:
        return None
    return (Scope.ADMIN, Risk.DESTRUCTIVE)


def material(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The parts of a payload a decision is actually about."""
    return {k: v for k, v in sorted(payload.items()) if k in MATERIAL_KEYS}


def fingerprint(action: str, payload: dict[str, Any]) -> str:
    """A stable digest of the act being proposed.

    Computed over the *resolved* payload, so ``${deploy.url}`` has already
    become the real URL. Fingerprinting the unresolved plan would bind consent
    to a template rather than to what will happen.
    """
    body = json.dumps(
        {"action": action, "material": material(action, payload)},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


class ApprovalProposal(BaseModel):
    """What a person is being asked to allow.

    Deliberately verbose. "Approve action" tells a reviewer nothing, and a
    reviewer who cannot see the target and the content is rubber-stamping.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    step_id: str
    action: str
    scope: Scope
    risk: Risk
    fingerprint: str
    #: The full resolved payload, for display. The fingerprint covers only the
    #: material subset, but a reviewer should see everything.
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    target: str = ""
    project_id: str | None = None
    estimated_cost: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = "qevik"
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + DEFAULT_TTL)

    def title(self) -> str:
        return f"{self.action} → {self.target or 'unspecified target'}"


def describe(action: str, payload: dict[str, Any]) -> tuple[str, str]:
    """A human summary and the exact external target.

    The target is pulled out separately because it is the single fact a reviewer
    most needs and the one most easily lost inside a payload dump.
    """
    if action == "site.deploy":
        slug = payload.get("slug", "?")
        return (
            f"Publish the built site to the public host as {slug!r}"
            + (" and point the live URL at it" if payload.get("promote", True) else ""),
            str(payload.get("url") or f"/{slug}/"),
        )
    if action in ("email.send", "message.send"):
        return (
            f"Send a message to {payload.get('to', 'an external recipient')}",
            str(payload.get("to", "")),
        )
    if action in ("payment.create", "domain.purchase"):
        return (
            f"Spend {payload.get('amount', '?')} {payload.get('currency', '')}"
            f" with {payload.get('vendor', 'a vendor')}",
            str(payload.get("vendor", "")),
        )
    if action == "site.remove":
        return (f"Remove {payload.get('slug', 'a published site')}", str(payload.get("slug", "")))
    return (f"Perform {action}", str(payload.get("url") or payload.get("target") or ""))


# -- durability ----------------------------------------------------------

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS qevik_approvals (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        step_id TEXT NOT NULL,
        project_id TEXT,
        action TEXT NOT NULL,
        required_scope TEXT NOT NULL,
        risk TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        payload JSONB NOT NULL,
        summary TEXT NOT NULL,
        target TEXT NOT NULL,
        estimated_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
        evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
        provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
        status TEXT NOT NULL DEFAULT 'pending',
        requested_by TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        expires_at TIMESTAMP WITH TIME ZONE,
        decided_by TEXT,
        decided_at TIMESTAMP WITH TIME ZONE,
        decision_reason TEXT NOT NULL DEFAULT '',
        consumed_at TIMESTAMP WITH TIME ZONE
    )
    """,
    "CREATE INDEX IF NOT EXISTS qevik_approvals_pending ON qevik_approvals (status, created_at)",
    "CREATE INDEX IF NOT EXISTS qevik_approvals_job ON qevik_approvals (job_id)",
    # The lookup on the hot path: "is there a live decision for exactly this
    # act?" Without it, resuming a plan scans the table.
    "CREATE INDEX IF NOT EXISTS qevik_approvals_fp ON qevik_approvals (fingerprint, status)",
)


def init_approvals() -> None:
    from sqlalchemy import text

    from ..db import engine

    with engine.begin() as conn:
        for statement in SCHEMA:
            conn.execute(text(statement))


class ApprovalStore:
    """Approval requests, in PostgreSQL.

    Every state transition out of pending is an authenticated human decision
    recorded here. Nothing in a plan can reach these methods with a decision —
    the gate only reads.
    """

    def request(self, proposal: ApprovalProposal) -> str:
        """Record a proposal, or return the id of one already pending for it.

        Re-requesting the same fingerprint returns the existing row rather than
        stacking duplicates: a job that pauses, is restarted and pauses again on
        the same step must present one decision, not a growing queue of
        identical ones.
        """
        from sqlalchemy import text

        from ..db import engine

        with engine.begin() as conn:
            existing = conn.execute(
                text(
                    "SELECT id FROM qevik_approvals WHERE job_id = :j AND fingerprint = :f"
                    " AND status = 'pending'"
                ),
                {"j": proposal.job_id, "f": proposal.fingerprint},
            ).first()
            if existing:
                return existing.id

            # Derived from the job AND the fingerprint. Using the fingerprint
            # alone made the id collide whenever two jobs proposed the same act
            # — and with ON CONFLICT DO NOTHING the second job silently adopted
            # the first one's row, so approving job A would have unblocked job
            # B's identical publish. A decision is about one job's proposal.
            approval_id = "apr_" + hashlib.sha256(
                f"{proposal.job_id}:{proposal.fingerprint}".encode()
            ).hexdigest()[:16]
            conn.execute(
                text(
                    "INSERT INTO qevik_approvals (id, job_id, step_id, project_id, action,"
                    " required_scope, risk, fingerprint, payload, summary, target,"
                    " estimated_cost, evidence, provenance, status, requested_by, created_at,"
                    " expires_at) VALUES (:id, :job, :step, :proj, :act, :scope, :risk, :fp,"
                    " CAST(:payload AS JSONB), :summary, :target, :cost,"
                    " CAST(:evidence AS JSONB), CAST(:prov AS JSONB), 'pending', :by, :at, :exp)"
                    " ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": approval_id,
                    "job": proposal.job_id,
                    "step": proposal.step_id,
                    "proj": proposal.project_id,
                    "act": proposal.action,
                    "scope": str(proposal.scope),
                    "risk": str(proposal.risk),
                    "fp": proposal.fingerprint,
                    "payload": json.dumps(proposal.payload, default=str),
                    "summary": proposal.summary,
                    "target": proposal.target,
                    "cost": proposal.estimated_cost,
                    "evidence": json.dumps(proposal.evidence),
                    "prov": json.dumps(proposal.provenance, default=str),
                    "by": proposal.requested_by,
                    "at": datetime.now(UTC),
                    "exp": proposal.expires_at,
                },
            )
        return approval_id

    def get(self, approval_id: str) -> dict | None:
        from sqlalchemy import text

        from ..db import engine

        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM qevik_approvals WHERE id = :i"), {"i": approval_id}
            ).first()
        return self._expire(dict(row._mapping)) if row else None

    def pending(self, limit: int = 50) -> list[dict]:
        from sqlalchemy import text

        from ..db import engine

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM qevik_approvals WHERE status = 'pending'"
                    " ORDER BY created_at DESC LIMIT :l"
                ),
                {"l": limit},
            ).all()
        return [self._expire(dict(r._mapping)) for r in rows]

    def for_job(self, job_id: str) -> list[dict]:
        from sqlalchemy import text

        from ..db import engine

        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM qevik_approvals WHERE job_id = :j ORDER BY created_at"),
                {"j": job_id},
            ).all()
        return [self._expire(dict(r._mapping)) for r in rows]

    def _expire(self, row: dict) -> dict:
        """Enforce expiry on read.

        A request that has run out of time is expired the moment anyone looks,
        rather than whenever a sweeper happens to run. Otherwise a stale
        approval stays spendable purely because nothing has cleaned it up.
        """
        if row.get("status") != "pending":
            return row
        expires = row.get("expires_at")
        if expires is None:
            return row
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if datetime.now(UTC) >= expires:
            from sqlalchemy import text

            from ..db import engine

            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE qevik_approvals SET status = 'expired' WHERE id = :i"
                        " AND status = 'pending'"
                    ),
                    {"i": row["id"]},
                )
            row["status"] = "expired"
        return row

    def decide(self, approval_id: str, *, approve: bool, decided_by: str, reason: str = "") -> dict:
        """Record a human decision. The only way out of pending.

        `decided_by` is the authenticated session's identity, passed by the
        endpoint — never a field a client can send. A decision attributed to
        whoever the caller claimed to be is not an audit trail.

        The update is conditional on the row still being pending, so two
        reviewers racing produce one decision rather than the last writer
        silently overwriting the first.
        """
        from sqlalchemy import text

        from ..db import engine

        current = self.get(approval_id)
        if current is None:
            raise KeyError(f"no approval {approval_id!r}")
        if current["status"] != "pending":
            raise ValueError(
                f"approval {approval_id} is already {current['status']}; "
                "decisions are final and a new request is required"
            )

        with engine.begin() as conn:
            updated = conn.execute(
                text(
                    "UPDATE qevik_approvals SET status = :s, decided_by = :who,"
                    " decided_at = :at, decision_reason = :why"
                    " WHERE id = :i AND status = 'pending'"
                ),
                {
                    "s": "approved" if approve else "rejected",
                    "who": decided_by,
                    "at": datetime.now(UTC),
                    "why": reason[:500],
                    "i": approval_id,
                },
            ).rowcount
        if not updated:
            raise ValueError(f"approval {approval_id} was decided by someone else first")
        return self.get(approval_id)

    def live_decision(self, job_id: str, fingerprint_: str) -> dict | None:
        """An unspent decision for exactly this act, if one exists."""
        from sqlalchemy import text

        from ..db import engine

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT * FROM qevik_approvals WHERE job_id = :j AND fingerprint = :f"
                    " AND consumed_at IS NULL ORDER BY created_at DESC LIMIT 1"
                ),
                {"j": job_id, "f": fingerprint_},
            ).first()
        return self._expire(dict(row._mapping)) if row else None

    def consume(self, approval_id: str) -> None:
        """Mark an approval spent, so it cannot authorise a second execution."""
        from sqlalchemy import text

        from ..db import engine

        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE qevik_approvals SET consumed_at = :at WHERE id = :i"
                    " AND consumed_at IS NULL"
                ),
                {"at": datetime.now(UTC), "i": approval_id},
            )


# -- the gate ------------------------------------------------------------


class GateDecision(BaseModel):
    """What the gate says about one step, right now."""

    model_config = ConfigDict(frozen=True)

    outcome: ApprovalOutcome
    approval_id: str = ""
    reason: str = ""
    proposal: ApprovalProposal | None = None


class ApprovalGate:
    """Decides whether a step may run, and records a proposal when it may not.

    Reads decisions; never makes them. That asymmetry is the whole security
    model: everything inside a plan can reach this class, and nothing inside a
    plan can approve.
    """

    def __init__(self, store: ApprovalStore | None = None, *, requested_by: str = "qevik") -> None:
        self.store = store or ApprovalStore()
        self.requested_by = requested_by

    def check(
        self,
        *,
        job_id: str,
        step_id: str,
        action: str,
        payload: dict[str, Any],
        project_id: str | None = None,
        evidence: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> GateDecision:
        classification = classify(action)
        if classification is None:
            return GateDecision(outcome=ApprovalOutcome.ALLOWED, reason="internal action")

        scope, risk = classification
        fp = fingerprint(action, payload)
        decision = self.store.live_decision(job_id, fp)

        if decision is not None:
            status = decision["status"]
            if status == "approved":
                return GateDecision(
                    outcome=ApprovalOutcome.ALLOWED,
                    approval_id=decision["id"],
                    reason=f"approved by {decision['decided_by']}",
                )
            if status == "rejected":
                return GateDecision(
                    outcome=ApprovalOutcome.REJECTED,
                    approval_id=decision["id"],
                    reason=decision.get("decision_reason") or "rejected by a reviewer",
                )
            if status == "expired":
                return GateDecision(
                    outcome=ApprovalOutcome.EXPIRED,
                    approval_id=decision["id"],
                    reason="the approval request expired before anyone decided",
                )
            # Still pending — the same request, not a new one.
            return GateDecision(
                outcome=ApprovalOutcome.WAITING,
                approval_id=decision["id"],
                reason="waiting for a human decision",
            )

        summary, target = describe(action, payload)
        proposal = ApprovalProposal(
            job_id=job_id,
            step_id=step_id,
            action=action,
            scope=scope,
            risk=risk,
            fingerprint=fp,
            payload=payload,
            summary=summary,
            target=target,
            project_id=project_id,
            evidence=evidence or [],
            provenance=provenance or {},
            requested_by=self.requested_by,
        )
        approval_id = self.store.request(proposal)
        return GateDecision(
            outcome=ApprovalOutcome.WAITING,
            approval_id=approval_id,
            reason="approval requested",
            proposal=proposal,
        )

    def consume(self, approval_id: str) -> None:
        if approval_id:
            self.store.consume(approval_id)
