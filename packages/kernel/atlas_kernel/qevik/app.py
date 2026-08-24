"""The Qevik control plane, composed.

One `create_app()`. It mounts every surface and wires the state each one reads,
so that the thing the tests exercise and the thing a person opens in a browser
are the same object.

Two decisions worth stating, because both had an easier wrong answer.

**Wiring is explicit and injected, not imported.** Each surface reads what it
needs off `app.state` — the business timeline, the mission timeline, the
credential vault, the approval service. That indirection exists so a deployment
can serve the same routes from a file, a repository or a database without any
handler knowing which, and `Wiring` is where a deployment says which.

**A surface with nothing behind it refuses; it does not pretend.** Where a
dependency is genuinely absent — no research source configured, no mission
timeline to write to — the route returns 503 and says what is missing. It never
returns an empty list, because an empty list is indistinguishable from "you have
no missions" and that is the answer a person acts on.

`health()` is built on the same principle: it reports what is configured and
what is not, and never reports a component as healthy on the grounds that
nothing has failed yet.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from ..approval.models import ApprovalRequest
from ..auth import api as auth_api
from ..auth.store import AuthStore
from ..chat import api as chat_api
from ..control import sales as sales_api
from ..credentials import api as credentials_api
from ..credentials.service import CredentialService
from ..credentials.vault import FileSecretStore, Vault
from ..credits import CreditService
from ..customer import api as customer_api
from ..mission import api as mission_api
from ..mission.claims import LocalClaims
from ..mission.claims import describe as describe_claims
from ..mission.timeline import Timeline
from ..modelchoice import api as models_api
from ..modelchoice.store import SelectionStore
from ..publication import ConnectionStore

#: Every surface this application serves. The list is the composition, and
#: `test_app_composition.py` reads it against the modules on disk — a router
#: built and never added here is a router nobody can reach, which is exactly
#: what happened to all of them before this module existed.
SURFACES: tuple[str, ...] = (
    "auth", "customer", "mission", "credentials", "models", "chat", "sales",
)

#: Where the vault keeps ciphertext when a deployment does not say otherwise.
#: Outside the repository on purpose.
DEFAULT_VAULT = Path.home() / ".qevik" / "vault.json"


@dataclass
class Wiring:
    """What this deployment puts behind the routes.

    Every field has a safe default that is honest about being a default: an
    in-memory timeline is a real timeline that does not survive a restart, and
    `health()` says so rather than reporting it as storage.
    """

    #: The business timeline. A list here is a development default; production
    #: passes something backed by a database.
    business_events: list = field(default_factory=list)
    #: Conversation turns. Separate from the business timeline because a
    #: conversation is about a request, not about a customer, and one tenant's
    #: chat history should not have to be filtered out of a business's file.
    chat_events: list = field(default_factory=list)
    model_selections: Any = None
    #: Where missions are read from and written to, shared with the worker
    #: process. A path, because two processes cannot share a list.
    mission_timeline: Path | None = None
    #: Reads that a deployment supplies, because the kernel does not know where
    #: this installation keeps research.
    research_reader: Callable[..., Any] | None = None
    plan_reader: Callable[..., Any] | None = None
    public_audit_reader: Callable[..., Any] | None = None
    #: Live checks per provider, `provider -> (secret) -> (Status, detail)`.
    #: Empty means every `/test` returns 501, which is the honest answer until
    #: a real probe exists.
    credential_probes: dict[str, Callable[[str], Any]] = field(default_factory=dict)
    pending_approvals: list[ApprovalRequest] = field(default_factory=list)
    approvals: Any = None
    credentials: CredentialService | None = None
    connections: ConnectionStore | None = None
    credits: CreditService | None = None
    auth: AuthStore | None = None
    #: What decides who runs a mission. `LocalClaims` is safe for one worker;
    #: multi-worker needs a database, and `mission/claims.py` says so rather
    #: than offering a fake that makes the property appear to hold.
    claims: Any = None
    repository_root: Path = field(default_factory=Path.cwd)
    vault_path: Path = DEFAULT_VAULT

    def build_credentials(self) -> CredentialService:
        """The vault, sealed unless a master key is in the environment.

        The environment is a bootstrap, not the storage: `QEVIK_VAULT_MASTER_KEY`
        unlocks a file the user filled through the Credential Centre. Without it
        the vault refuses to store rather than falling back to plaintext, and
        `health()` reports `sealed`.
        """
        if self.credentials is not None:
            return self.credentials
        return CredentialService(Vault(FileSecretStore(self.vault_path)))


def create_app(wiring: Wiring | None = None, *, title: str = "Qevik") -> FastAPI:
    """The application. Everything mounted, everything wired."""
    wiring = wiring or Wiring()
    app = FastAPI(title=title)

    # Auth first: `auth_api.install` registers the middleware, and middleware
    # only sees routes added after it. Mounting a surface before this would
    # serve it unauthenticated, which is the kind of mistake that looks like
    # working software.
    auth_api.install(app, wiring.auth or AuthStore())

    customer_api.install(app)
    mission_api.install(app)
    credentials_api.install(app)
    models_api.install(app)
    chat_api.install(app)
    sales_api.install(app)

    timeline = (Timeline(wiring.mission_timeline)
                if wiring.mission_timeline is not None else None)

    app.state.chat_events = wiring.chat_events
    app.state.chat_sink = wiring.chat_events.append
    app.state.model_selections = wiring.model_selections or SelectionStore()
    app.state.business_events = wiring.business_events
    app.state.business_sink = wiring.business_events.append
    # `is not None`, not truthiness. `Timeline` defines `__len__`, so a brand
    # new timeline — the one every first run has — is falsy, and `if timeline`
    # silently replaced the durable store with an in-memory list on exactly the
    # deployment that most needed the durable one.
    app.state.mission_events = timeline if timeline is not None else []
    app.state.mission_sink = timeline.append if timeline is not None else None
    app.state.research_reader = wiring.research_reader
    app.state.plan_reader = wiring.plan_reader
    app.state.public_audit_reader = wiring.public_audit_reader
    app.state.credential_probes = wiring.credential_probes
    app.state.pending_approvals = wiring.pending_approvals
    app.state.approvals = wiring.approvals
    app.state.credentials = wiring.build_credentials()
    app.state.connections = wiring.connections or ConnectionStore()
    app.state.credits = wiring.credits or CreditService()
    app.state.claims = wiring.claims or LocalClaims()
    app.state.repository_root = str(wiring.repository_root)
    app.state.wiring = wiring

    @app.get("/api/health")
    def _health() -> dict:
        return health(app)

    return app


def health(app: FastAPI) -> dict:
    """What is configured, what is not, and what that costs.

    Deliberately not a boolean. "Healthy" would have to mean "nothing has failed
    yet", which is true of a deployment with no timeline, no research source and
    a sealed vault — a deployment that cannot do anything. Each component
    reports what it can actually do, and the summary is degraded rather than
    unhealthy when a component is merely absent.
    """
    state = app.state
    timeline = getattr(state, "mission_events", None)
    durable = isinstance(timeline, Timeline)
    credentials = getattr(state, "credentials", None)
    vault = getattr(credentials, "_vault", None)

    components: dict[str, dict] = {
        "missions": {
            "configured": True,
            "durable": durable,
            "detail": (f"timeline at {timeline.path}"  # type: ignore[union-attr]
                       if durable else
                       "in memory: missions do not survive a restart, and no "
                       "separate worker process can see them"),
        },
        "credentials": {
            "configured": credentials is not None,
            "sealed": bool(getattr(vault, "sealed", True)),
            "detail": ("QEVIK_VAULT_MASTER_KEY is not set, so the vault refuses "
                       "to store rather than falling back to plaintext"
                       if getattr(vault, "sealed", True) else "unsealed"),
        },
        "research": {
            "configured": getattr(state, "research_reader", None) is not None,
            "detail": "no research source configured"
            if getattr(state, "research_reader", None) is None else "",
        },
        "approvals": {
            "configured": getattr(state, "approvals", None) is not None,
            "detail": "no approval service configured"
            if getattr(state, "approvals", None) is None else "",
        },
        "claiming": {
            # Reported because the answer changes what a person may safely run.
            # A deployment that starts two workers on `LocalClaims` gets two
            # commits of the same change and no error anywhere.
            "configured": True,
            **describe_claims(getattr(state, "claims", LocalClaims())),
        },
        "probes": {
            # Named separately from `credentials` because they fail differently:
            # a vault with no probes can store keys it cannot test, and showing
            # that as one number would hide which half is missing.
            "configured": bool(getattr(state, "credential_probes", None)),
            "detail": "every credential test returns 501 until a probe exists",
        },
    }
    missing = [name for name, c in components.items()
               if not c.get("configured")]
    return {
        "surfaces": list(SURFACES),
        "components": components,
        "degraded": missing,
        "status": "ready" if not missing else "degraded",
        "note": ("Degraded means a component is absent, not that one failed. "
                 "Nothing here reports healthy on the grounds that nothing has "
                 "broken yet."),
    }


def from_environment() -> FastAPI:
    """The deployment entry point. Reads only paths, never secrets.

    `QEVIK_VAULT_MASTER_KEY` is consulted by the vault itself and never passes
    through here, so it cannot reach a log line or a traceback in this module.
    """
    root = Path(os.environ.get("QEVIK_REPOSITORY", Path.cwd()))
    timeline = os.environ.get("QEVIK_MISSION_TIMELINE", "")
    return create_app(Wiring(
        repository_root=root,
        mission_timeline=Path(timeline) if timeline else None,
        vault_path=Path(os.environ.get("QEVIK_VAULT", DEFAULT_VAULT)),
    ))
