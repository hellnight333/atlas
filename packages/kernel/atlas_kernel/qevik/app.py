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

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request

from ..approval.models import ApprovalRequest
from ..auth import api as auth_api
from ..auth.api import current_user
from ..auth.models import User
from ..auth.store import AuthStore, init_auth
from ..chat import api as chat_api
from ..control import sales as sales_api
from ..credentials import api as credentials_api
from ..credentials.probes import PROBES
from ..credentials.service import CredentialService
from ..credentials.vault import FileSecretStore, Vault
from ..credits import CreditService
from ..customer import api as customer_api
from ..fabric import Registry as AgentRegistry
from ..fabric.sandbox import Confinement
from ..fabric.sandbox import available as sandbox_available
from ..fabric.sandbox import describe as describe_sandbox
from ..mission import api as mission_api
from ..mission.claims import LocalClaims
from ..mission.claims import describe as describe_claims
from ..mission.timeline import Timeline
from ..modelchoice import api as models_api
from ..modelchoice.store import SelectionStore
from ..publication import ConnectionStore
from . import live

log = logging.getLogger(__name__)

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
    #:
    #: A list is in-memory and correct for a test. A deployment passes
    #: `chat_timeline` instead: a list meant every restart forgot every
    #: conversation, so the sentence a person typed, the plan proposed from it
    #: and the approval that queued a mission all vanished while the mission
    #: itself survived — leaving work in flight that nothing could explain.
    chat_events: list = field(default_factory=list)
    #: Where conversations are read from and written to. A path, because the
    #: console and any future worker are separate processes.
    chat_timeline: Path | None = None
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
    #: What decides who runs a mission. `LocalClaims` is safe for one worker.
    #: Multi-worker needs a database: set `claims_dsn` and this builds a
    #: `PostgresClaims` — whose algorithm has now been demonstrated against a
    #: real database, see `mission/claims.py::DEMONSTRATED_BY`.
    claims: Any = None
    #: What would contain a CLI coding agent. None asks the host.
    sandbox: Any = None
    #: A PostgreSQL DSN. Absent, the deployment stays single-worker and
    #: `/api/health` says so — rather than defaulting to a database that may
    #: not be there and failing at the first claim.
    claims_dsn: str = ""
    #: Whether this deployment *declares* it needs multi-worker safety. When it
    #: does, an unreachable claim database is fatal rather than a downgrade.
    require_atomic_claims: bool = False
    repository_root: Path = field(default_factory=Path.cwd)
    #: Where the worker writes mission reports. Separate from the repository
    #: root because a deployment keeps reports on durable storage rather than
    #: inside a checkout that a deploy replaces — and because the worker is
    #: started with its own `--reports`, which this must agree with.
    reports_root: Path | None = None
    vault_path: Path = DEFAULT_VAULT
    #: Where the control panel's files live. None uses the repository copy.
    console: Path | None = None

    #: Where credential *records* live. The vault holds the secret; this holds
    #: the fingerprint, hint and verification result that the Centre reads.
    #: Without it a saved credential reverts to NOT_CONFIGURED on restart while
    #: its key sits in the vault, unreachable and impossible to forget.
    credential_timeline: Path | None = None
    #: Where allowances and spends live. The ledger rebuilds from this, so the
    #: month's usage is not forgotten by a redeploy — and the worker draws on
    #: the same file, so both processes see one balance rather than two.
    quota_timeline: Path | None = None

    def build_credentials(self) -> CredentialService:
        """The vault, sealed unless a master key is in the environment.

        The environment is a bootstrap, not the storage: `QEVIK_VAULT_MASTER_KEY`
        unlocks a file the user filled through the Credential Centre. Without it
        the vault refuses to store rather than falling back to plaintext, and
        `health()` reports `sealed`.
        """
        if self.credentials is not None:
            return self.credentials
        vault = Vault(FileSecretStore(self.vault_path))
        if self.credential_timeline is None:
            return CredentialService(vault)
        timeline = Timeline(self.credential_timeline)
        return CredentialService(vault, events=timeline.read(),
                                 sink=timeline.append)


def create_app(wiring: Wiring | None = None, *, title: str = "Qevik") -> FastAPI:
    """The application. Everything mounted, everything wired."""
    wiring = wiring or Wiring()
    app = FastAPI(title=title)

    # The schema this application depends on, ensured before anything uses it.
    #
    # `init_auth()` carries the auth tables *and their migrations* — including
    # the `tenant_id` column every customer route reads. It was called only by
    # `atlas_kernel/api.py`, so this application assumed a schema it never
    # created: a fresh deployment failed at the first login rather than at
    # start-up, and an existing one silently ran without a migration the code
    # required. Production reached exactly that state — the column was absent
    # while the code that reads it was deployed.
    #
    # Wrapped for the same reason `api.py` wraps it: this module is imported by
    # tests and tooling with no database, and an import-time connection failure
    # there must not break things unrelated to the control plane. A control
    # plane that cannot reach its schema refuses requests; it does not fail to
    # start and it does not run open.
    try:
        init_auth()
    except Exception:                            # noqa: BLE001 - logged, not fatal
        log.exception("the auth schema could not be ensured")

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

    # `is not None`, never truthiness: `Timeline` defines `__len__`, so a brand
    # new one is falsy and `or` would silently swap durable storage for a list.
    chat = (Timeline(wiring.chat_timeline)
            if wiring.chat_timeline is not None else None)
    app.state.chat_events = chat if chat is not None else wiring.chat_events
    app.state.chat_sink = (chat.append if chat is not None
                           else wiring.chat_events.append)
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
    # Real probes unless the deployment supplied its own. Empty was the
    # default, and it made /test answer 501 for every provider — so a stored
    # credential could never leave PENDING_CREDENTIAL and the Centre could not
    # tell a good key from a typo.
    app.state.credential_probes = wiring.credential_probes or dict(PROBES)
    app.state.pending_approvals = wiring.pending_approvals
    app.state.approvals = wiring.approvals
    app.state.credentials = wiring.build_credentials()
    app.state.connections = wiring.connections or ConnectionStore()
    app.state.credits = wiring.credits or CreditService(
        _ledger_for(wiring.quota_timeline))
    app.state.quota = app.state.credits._ledger        # noqa: SLF001
    app.state.claims = wiring.claims or _claims_for(
        wiring.claims_dsn, insist=wiring.require_atomic_claims)
    app.state.sandbox = wiring.sandbox or sandbox_available()
    # The agents this host can actually run. A CLI agent's readiness is a
    # fact about the machine, so it is decided here — once — from the same
    # sandbox the runner would use, rather than inferred twice.
    app.state.agents = (
        AgentRegistry().on_a_host_with_a_sandbox()
        if getattr(app.state.sandbox, "confinement", None) is Confinement.FULL
        else AgentRegistry())
    app.state.repository_root = str(wiring.repository_root)
    app.state.reports_root = str(wiring.reports_root or wiring.repository_root)
    app.state.wiring = wiring

    @app.get("/api/health")
    def _health() -> dict:
        return health(app)

    @app.get("/api/status")
    def _status(request: Request, since: str = "",
                user: User = Depends(current_user)) -> dict:
        """What changed, for a console that refreshes itself.

        `since` is the version the caller last saw. Unchanged means a few bytes
        and no re-render, which is what makes asking every few seconds cheap.

        Tenant-scoped: the digest is computed over one tenant's events, so a
        change in another tenant's work cannot even signal.
        """
        tenant = (user.tenant_id or "").strip()
        if not tenant:
            raise HTTPException(
                status_code=403,
                detail="this account is not attached to a tenant, so it has no "
                       "status of its own.")
        current = live.snapshot(getattr(request.app.state, "mission_events", []),
                                getattr(request.app.state, "chat_events", []),
                                tenant=tenant)
        if since and since == current["version"]:
            return {"version": current["version"], "changed": False}
        return {**current, "changed": True}

    @app.get("/health", include_in_schema=False)
    def _liveness() -> dict:
        """Liveness, and nothing else.

        Public — systemd and Caddy check it before anybody has a session — so it
        must say only that the process is answering. `/api/health` reports
        whether the vault is sealed and which components are absent, which is
        deployment posture and sits behind authentication.
        """
        return {"status": "ok"}

    _serve_console(app, wiring.console)
    return app


#: The control panel, as built. One directory of static files with no build step
#: — a deployment decision rather than a stylistic one: the console has to be
#: serveable by copying a directory onto a host, and every build chain is another
#: thing that can be broken on the day the operator needs it most.
# qevik -> atlas_kernel -> kernel -> packages -> repository root.
CONSOLE = Path(__file__).resolve().parents[4] / "apps" / "control" / "src"


def _serve_console(app: FastAPI, root: Path | None) -> None:
    """Serve the console from the same process that serves the API.

    Optional, and absent rather than faked when the directory is missing: a
    deployment serving the API alone is a real configuration (Caddy serves the
    files in production), and inventing a placeholder page would make a missing
    console look like a working one.
    """
    directory = root or CONSOLE
    index = directory / "index.html"
    if not index.is_file():
        return

    from fastapi.responses import FileResponse, HTMLResponse

    @app.get("/", include_in_schema=False)
    def _console() -> HTMLResponse:
        return HTMLResponse(index.read_text(encoding="utf-8"))

    from ..auth.api import CONSOLE_PATHS

    @app.get("/{path:path}", include_in_schema=False)
    def _console_asset(path: str) -> FileResponse | HTMLResponse:
        """A console asset, or the shell for a client-side route.

        **Never a catch-all.** An earlier version returned the shell for any
        unmatched path, and mounted onto an application with its own routes it
        shadowed them — `/api/missions` came back as HTML with a 200, which is
        worse than a 404 because only the second is obviously broken and
        anything not checking content type reads it as success.

        So an unknown path 404s. Route ordering is not a thing to rest this on:
        registration order is invisible at the call site and one `install()`
        moving would silently reopen it.
        """
        # Resolved under the console directory and refused if it escapes: the
        # path comes from the URL, and serving whatever it names is an
        # arbitrary-file-read with extra steps.
        candidate = (directory / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(directory.resolve()):
            return FileResponse(candidate)
        if f"/{path}" in CONSOLE_PATHS:
            # A client-side route. The shell rather than a 404 is what makes a
            # deep link survive a reload.
            return HTMLResponse(index.read_text(encoding="utf-8"))
        raise HTTPException(status_code=404, detail="no such path")


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
        "sandbox": {
            # A CLI coding agent writes files and runs commands with its own
            # tool loop. Whether this host can contain one is a property of the
            # machine, so it is reported rather than assumed — and the answer
            # decides whether such an agent may run here at all.
            "configured": True,
            **describe_sandbox(getattr(state, "sandbox", None)
                               or sandbox_available()),
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


class UnsafeClaiming(RuntimeError):
    """A deployment that declared multi-worker safety cannot provide it.

    Raised at start-up, so the process dies rather than serving. That is the
    point: the failure this prevents is not an outage, it is a *quiet success* —
    an operator believing two workers are safe while both hold the same mission.
    """


def _ledger_for(timeline: Path | None) -> Any:
    """The one ledger, rebuilt from its timeline.

    Everything that draws on an allowance — `credits`, `fabric.budgets` — shares
    this. A second ledger anywhere would be a second answer to "what is left",
    and the operator would be reading whichever one happened to be in front of
    them.
    """
    from ..quota.ledger import QuotaLedger

    if timeline is None:
        return QuotaLedger()
    events = Timeline(timeline)
    return QuotaLedger(events=events.read(), sink=events.append)


def _claims_for(dsn: str, *, insist: bool = False) -> Any:
    """Postgres-backed claims when a DSN is configured, otherwise one worker.

    **`insist` is the deployment declaring what it is.** Without it, an
    unreachable database falls back to `LocalClaims` and logs the loss loudly —
    the right default for a single-worker deployment, where refusing to start
    would take the control plane down over a capability only the worker needs.

    With it, an unreachable database is fatal. A deployment that runs two
    workers and silently degrades to single-worker claiming does not fail: it
    succeeds twice, produces two commits of the same change, and nothing
    anywhere reports an error. Dying at start-up is recoverable; that is not.

    `/api/health` reports which is in use either way, so "we are running two
    workers" stays a claim the operator can check rather than assume.
    """
    if not dsn.strip():
        if insist:
            raise UnsafeClaiming(
                "QEVIK_REQUIRE_ATOMIC_CLAIMS is set and QEVIK_CLAIMS_DSN is "
                "not. Refusing to start: this deployment says it needs "
                "multi-worker safety and has no database to provide it.")
        return LocalClaims()
    try:
        import psycopg

        from ..mission.claims import PostgresClaims

        claims = PostgresClaims(psycopg.connect(dsn, autocommit=False),
                                i_have_a_database=True)
        claims.install()
        log.info("claims: Postgres-backed, multi-worker safe")
        return claims
    except Exception as failure:                 # noqa: BLE001 - reported below
        if insist:
            # The message carries the exception *type*, never the DSN: a
            # connection error quotes what it tried to connect to, and a DSN
            # carries a password.
            raise UnsafeClaiming(
                f"the claim database could not be reached "
                f"({type(failure).__name__}). Refusing to start rather than "
                "falling back to single-worker claiming, which would let two "
                "workers run one mission with no error anywhere."
            ) from failure
        log.exception("claims: the database was configured and could not be "
                      "reached; falling back to single-worker claiming, which "
                      "is NOT safe for two workers")
        return LocalClaims()


def from_environment() -> FastAPI:
    """The deployment entry point. Reads only paths, never secrets.

    `QEVIK_VAULT_MASTER_KEY` is consulted by the vault itself and never passes
    through here, so it cannot reach a log line or a traceback in this module.

    `QEVIK_STATE` is one directory holding everything that must outlive a
    restart: the mission timeline, the conversation store and the vault. A
    deployment that set none of them individually used to get an in-memory
    timeline, which is a real configuration and the wrong one for a server.
    """
    root = Path(os.environ.get("QEVIK_REPOSITORY", Path.cwd()))
    state = os.environ.get("QEVIK_STATE", "")

    timeline = os.environ.get("QEVIK_MISSION_TIMELINE", "")
    if not timeline and state:
        timeline = str(Path(state) / "missions.jsonl")

    vault = os.environ.get("QEVIK_VAULT", "")
    if not vault:
        vault = str(Path(state) / "vault.json") if state else str(DEFAULT_VAULT)

    # Beside the vault, in the same durable directory. Its own file rather than
    # the mission timeline: both are append-only JSONL and mixing them would
    # make "what happened to this mission" and "what happened to this key" one
    # log that neither reader wants whole.
    # Reports live beside the rest of the durable state by default, so the
    # worker and this surface agree without either being configured.
    report_root = os.environ.get("QEVIK_REPORTS", "")
    if not report_root and state:
        report_root = str(Path(state) / "reports")

    quota = os.environ.get("QEVIK_QUOTA_TIMELINE", "")
    if not quota and state:
        quota = str(Path(state) / "quota.jsonl")

    credentials = os.environ.get("QEVIK_CREDENTIAL_TIMELINE", "")
    if not credentials and state:
        credentials = str(Path(state) / "credentials.jsonl")

    chat = os.environ.get("QEVIK_CHAT_TIMELINE", "")
    if not chat and state:
        chat = str(Path(state) / "chat.jsonl")

    turns: list = []
    if state:
        Path(state).mkdir(parents=True, exist_ok=True)

    return create_app(Wiring(
        repository_root=root,
        mission_timeline=Path(timeline) if timeline else None,
        vault_path=Path(vault),
        credential_timeline=Path(credentials) if credentials else None,
        reports_root=Path(report_root) if report_root else None,
        quota_timeline=Path(quota) if quota else None,
        chat_events=turns,
        chat_timeline=Path(chat) if chat else None,
        claims_dsn=os.environ.get("QEVIK_CLAIMS_DSN", ""),
        require_atomic_claims=os.environ.get(
            "QEVIK_REQUIRE_ATOMIC_CLAIMS", "").strip().lower()
        in ("1", "true", "yes"),
    ))
