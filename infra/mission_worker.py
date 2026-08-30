"""The mission worker, as its own process.

This is the thing that makes "closing the UI does not stop a running mission"
true. It shares nothing with the HTTP surface except a file: no import, no
socket, no parent process. Restart the API to deploy and this keeps working;
kill this and the API keeps serving, showing the mission exactly where it
stopped.

    python3 infra/mission_worker.py --timeline <path> --tenant tenant-qevik
    python3 infra/mission_worker.py --timeline <path> --once     # one pass, exit

**Recovery runs before anything is claimed.** A worker that died mid-mission
left it PROCESSING with a claim on it, and without releasing those first the
mission sits there looking busy forever. `recover()` finds exactly the stale
ones and returns them to the queue with the reason recorded.

**One mission at a time, and only QUEUED ones.** Claiming is safe against this
worker restarting, not against two workers racing — folding a file cannot
compare-and-set. Run one. The limitation is recorded in
`atlas_kernel/mission/timeline.py` rather than papered over.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import socket
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from atlas_kernel.credentials.location import (  # noqa: E402
    CredentialPaths,
    paths_for,
)
from atlas_kernel.credentials.location import (  # noqa: E402
    describe as describe_credentials,
)
from atlas_kernel.credentials.models import (  # noqa: E402
    Role,
    Selection,
    chosen_for,
    registry_for,
)
from atlas_kernel.credentials.service import CredentialService, usable_for  # noqa: E402
from atlas_kernel.credentials.vault import FileSecretStore, Vault  # noqa: E402
from atlas_kernel.fabric import recipes, scheduler  # noqa: E402
from atlas_kernel.fabric.agents import Registry as AgentRegistry  # noqa: E402
from atlas_kernel.fabric.budgets import (  # noqa: E402
    Envelope,
    Unmetered,
    assess,
    reserve,
)
from atlas_kernel.fabric.scheduler import demands_from  # noqa: E402
from atlas_kernel.mission import (  # noqa: E402
    origins,
    policy,
    recurrence,
    reports,
    scratch,
    service,
    toolrunner,
)
from atlas_kernel.mission.agents import (  # noqa: E402
    Behaviour,
    CodingAgent,
    FakeCodingAgent,
    LLMCodingAgent,
    Roles,
)
from atlas_kernel.mission.claims import (  # noqa: E402
    LocalClaims,
    NotVerified,
    PostgresClaims,
)
from atlas_kernel.mission.claims import describe as describe_claims  # noqa: E402
from atlas_kernel.mission.gitspace import GitWorkspace  # noqa: E402
from atlas_kernel.mission.models import TERMINAL, Mission, MissionStatus  # noqa: E402
from atlas_kernel.mission.timeline import Timeline  # noqa: E402
from atlas_kernel.mission.worker import Acceptance, Worker, recover  # noqa: E402
from atlas_kernel.quota.ledger import QuotaLedger  # noqa: E402
from atlas_kernel.quota.models import QuotaExhausted  # noqa: E402

log = logging.getLogger("mission-worker")


class NoAgent(RuntimeError):
    """No model is available, and the worker will not invent one."""


def roles_for(kind: str, *, tenant: str,
              credentials_at: CredentialPaths | None = None) -> Roles:
    """The agents this worker runs missions with.

    `--agent fake` is a real choice a person has to make, never a fallback. A
    worker that quietly substituted a deterministic stub when no credential was
    configured would commit files, write reports and mark missions complete —
    and every one of those artefacts would claim work an LLM never did. Refusing
    is the only honest failure here, so a missing credential raises.

    The registry comes from the credential vault rather than the environment, so
    the key is read from the encrypted store at the moment it is used and never
    materialises in a process listing or a shell history.
    """
    if kind == "self-check":
        # Resolved through the agent registry and run through its own tools and
        # isolation — the same boundary a model-backed agent crosses. Nothing
        # here calls a provider, so it costs nothing and can prove the path.
        from atlas_kernel.mission.adapter import SELF_CHECK_STEPS, build

        checker = build("self-check", SELF_CHECK_STEPS)
        log.info("self-check agent: %s", checker._adapter.describe())
        return Roles.all(checker)

    # Derived from `PLACEHOLDERS`, not written out again. It *was* written out
    # again — as a literal set here — and adding `healthcheck` to
    # `REGISTERED_AS`, `AGENT_CHOICES` and `PLACEHOLDERS` still left it out of
    # this one. The worker went looking for a model, found none, and exited 2 on
    # the host after a deploy that had reported success. A role is recipe-driven
    # exactly when it has a placeholder recipe; there is no second answer.
    if kind in PLACEHOLDERS:
        # The non-coding roles, one construction. They plan nothing, call no
        # provider, and carry out a *declared recipe* through the tools that
        # recipe's agent is registered for. What separates them is which agent
        # the worker serves and therefore which missions it may take — research
        # fetches and audits, delivery builds what an approval asked for.
        #
        # The recipe is named by the **mission**, not by this worker, and is
        # resolved in `build_worker` where the mission is in hand. A placeholder
        # is built here only so the roles object exists; running a mission that
        # names no recipe is refused rather than defaulted, because defaulting
        # would pick one nobody asked for.
        from atlas_kernel.mission.toolrunner import ToolAgent

        placeholder = ToolAgent(recipes.get(PLACEHOLDERS[kind]))
        log.info("%s role: recipes are named by the mission; this worker "
                 "dispatches %s", kind,
                 ", ".join(sorted(t for t in toolrunner.DISPATCHABLE)))
        return Roles.all(placeholder)

    if kind == "fake":
        log.warning("running with the deterministic fake agent: no model will "
                    "be called and nothing it produces reflects real work")
        return Roles.all(FakeCodingAgent(behaviour=Behaviour.SUCCESS, writes=True))

    # Exactly what the Credential Centre wrote, resolved by the one module that
    # decides where that is. Both halves together: the vault holds the secret
    # and the timeline holds the record, and a process with only one of them
    # finds nothing.
    where = credentials_at or paths_for()
    records = Timeline(where.records)
    credentials = CredentialService(Vault(FileSecretStore(where.vault)),
                                    events=records.read(), sink=records.append)
    log.info("credentials: %s", where.summary())
    registry = registry_for(credentials, tenant=tenant)
    selection = Selection()

    def agent_for(role: Role) -> CodingAgent:
        spec, why = chosen_for(registry, selection, role)
        if spec is None:
            raise NoAgent(
                f"no model is available for {role.value}: {why}. Add a "
                "credential through the credential centre, or run with "
                "--agent fake if a deterministic stub is what you actually "
                "want. This worker will not substitute one silently.")
        found = next((r for r in registry.models if r.name == spec.id), None)
        if found is None:                        # pragma: no cover - chosen_for
            raise NoAgent(f"{spec.id} was chosen for {role.value} but is not "
                          "registered, which should be impossible")
        log.info("%s: %s (%s)", role.value, spec.id, why)
        return LLMCodingAgent(found.provider, spec)

    # An independent reviewer where the registry offers one: an agent grading
    # its own diff is the failure the whole mission module is arranged around.
    return Roles(planner=agent_for(Role.PLANNING),
                 implementer=agent_for(Role.IMPLEMENTATION),
                 reviewer=agent_for(Role.REVIEW))


#: What each `--agent` choice is called in the agent registry. The scheduler
#: needs the *declared* agent to know a mission's placement and which
#: credentials it requires; `_agent_of` cannot help, because it reads the
#: invocations a mission has already recorded and dispatch happens before there
#: are any. `fake` is deliberately absent: it is not a declared agent, and the
#: scheduler treating it as unknown is the correct answer.
REGISTERED_AS = {"self-check": "self-check", "llm": "implementer",
                 "research": "researcher", "delivery": "website-builder",
                 "publish": "site-publisher",
                 # One agent per process, like every other role. `health-check`
                 # declares one tool and `deliver-health-check` names it, so a
                 # process started here can run that recipe and nothing else.
                 "healthcheck": "health-check"}

#: What `--agent` accepts. **Derived**, not written out again.
#:
#: It was written out again, and a role added to `REGISTERED_AS` was rejected by
#: argparse as an invalid choice — the worker knew the role and its own command
#: line did not. `fake` is the only entry that is not a registered agent, which
#: is the whole point of it and why it is added rather than filtered out.
AGENT_CHOICES: tuple[str, ...] = (*sorted(REGISTERED_AS), "fake")

#: A recipe the research role can be constructed with before a mission names
#: one. Never executed under this name: `build_worker` replaces the agent with
#: one built from the mission's own `recipe`, and a mission naming none is
#: refused. It exists because `Roles` must hold an agent to be constructed.
RESEARCH_PLACEHOLDER = "discover-uae-dental"

#: The recipe each recipe-driven role is constructed with before a mission
#: names one. Never executed under these names — `build_worker` replaces the
#: agent with one built from the mission's own `recipe`, and a mission naming
#: none is refused.
PLACEHOLDERS = {"research": RESEARCH_PLACEHOLDER,
                "delivery": "deliver-website",
                "publish": "publish-website",
                "healthcheck": "deliver-health-check"}


def queued(timeline: Timeline, *, tenant: str,
           connected: frozenset[str] = frozenset(),
           remaining_units: float | None = None,
           agent_id: str = "", worker_name: str = "",
           nodes: tuple | None = None) -> list[Mission]:
    """Missions the **scheduler** says may run, in the order it chose.

    This used to sort by timestamp and take the first. That is not an ordering
    policy, it is the absence of one: it could not tell urgent from routine,
    could not honour a deferral somebody set, and would happily start a mission
    whose budget or credentials could not carry it to the end.

    The scheduler already answers all of that, and it decides *order*, never
    *whether* — every mission here is one policy already queued.
    """
    folded = service.fold(timeline.read(), tenant=tenant)
    done = frozenset(m["mission_id"] for m in folded
                     if m.get("status") == MissionStatus.COMPLETE.value)
    # Which agent would carry each of these out — this worker's, since this
    # worker is the one asking. Without it every demand had `placement=EITHER`
    # and **no credential requirements at all**, so the scheduler's rule about a
    # missing credential could never fire: a mission whose agent needs a key
    # nobody configured was dispatched, told the operator it was running, and
    # failed at the provider.
    # The mission's own recorded agent wins: it is what policy was told when the
    # plan was approved. This worker's configured agent is the fallback for a
    # mission whose plan named nobody — an older one, or one from a path that
    # does not name an agent.
    routes = {str(m.get("mission_id", "")): (str(m.get("agent_id", "")) or agent_id)
              for m in folded}
    routes = {k: v for k, v in routes.items() if v}

    # Missions this worker cannot carry out are not offered to it at all.
    #
    # `policy.refuse_agent_substitution` catches a mismatch after the claim, and
    # that is the right backstop — but the claim is a race, so with two workers
    # running each one took the other's mission and refused it. Both nightly
    # recurrences ended BLOCKED within a minute of deploying, each blocked by
    # the worker that was never meant to run it.
    #
    # A worker filtering its own queue is the fix. The backstop stays, and now
    # releases instead of blocking: "not by me" is not a defect in the mission.
    #
    # A mission naming no agent used to be offered to **every** worker -- the
    # clause read `not m.get("agent_id") or m.get("agent_id") == agent_id`. That
    # is an unrouted mission becoming eligible everywhere, which is the same
    # mistake as Atlas reading an unresolvable capability as "no constraint":
    # absence of a requirement is not permission to run anywhere. Unknown is not
    # a wildcard.
    #
    # Explicitly routed work is untouched -- 16 of the 17 missions in the
    # production timeline name both an agent and a recipe, and the one that
    # names neither is `cancelled`, so nothing live changes. Unrouted work is now
    # offered to nobody and is visible as waiting rather than quietly running on
    # whichever worker asked first.
    if agent_id:
        mine = {m.get("mission_id") for m in folded
                if m.get("agent_id") == agent_id}
        folded = [m for m in folded if m.get("mission_id") in mine]
    demands = demands_from(folded, agents=AgentRegistry(), agent_for=routes,
                           connected=connected,
                           remaining_units=remaining_units)
    plan = scheduler.plan(demands, tenant=tenant, done=done, concurrency=1,
                          nodes=nodes)

    by_id = {m.get("mission_id"): m for m in folded}
    assigned = plan.get("assigned") or {}
    runnable = []
    for mission_id in plan["dispatchable"]:
        # Who the scheduler chose. Not "may I run this?" asked again here --
        # this worker reads the answer rather than deciding it, which is what
        # keeps eligibility in one place. When nothing was assigned (no node
        # information was supplied) the queue is taken as before.
        picked = assigned.get(mission_id, "")
        if picked and worker_name and picked != worker_name:
            continue
        summary = by_id.get(mission_id)
        # Only what is genuinely unclaimed and queued. The scheduler's advice is
        # about order; the claim is what decides who, and a mission already held
        # must not be offered again.
        if summary and summary.get("status") == MissionStatus.QUEUED.value \
                and not summary.get("claimed_by"):
            runnable.append(service.rehydrate(summary, tenant=tenant))
    if not runnable:
        _log_why_nothing_runs(plan)
    return runnable


def _log_why_nothing_runs(plan: dict) -> None:
    """Say what is holding the queue, once, rather than logging silence.

    A worker that prints nothing while five missions sit BLOCKED looks healthy
    and is the reason nobody notices for a week.
    """
    for queue in ("BLOCKED", "WAITING", "SCHEDULED"):
        for row in plan["queues"].get(queue, [])[:3]:
            log.info("%s: %s — %s", queue, row["mission_id"], row["why"])


def _charge(result, *, tenant: str, ledger, timeline: Timeline,
            name: str) -> None:
    """Draw the mission's real cost from every scope that bounds it.

    Uses the existing `fabric.budgets` over the existing `QuotaLedger`. Nothing
    here is a second budget: `reserve()` checks tenant, mission and agent and
    commits to all of them or none, and the ledger persists to the same timeline
    the control plane reads.

    **An unknown cost is recorded, not invented.** `Mission.total_cost` is
    `None` when no invocation reported one — a deterministic agent, or a
    provider that does not say. Charging a guessed number would put a fiction in
    the ledger; charging zero would say the work was free. So the fact is
    written to the timeline instead, where an uncharged mission is visible.
    """
    mission = result.mission
    spent = mission.total_cost
    envelope = Envelope(tenant_id=str(tenant), mission_id=mission.id,
                        agent_id=_agent_of(mission))
    if spent is None:
        log.info("%s: no provider reported a cost; nothing charged", mission.id)
        timeline.append(service._event(
            mission, actor=name,
            note="cost UNKNOWN: no invocation reported one, so nothing was "
                 "charged. This is not a zero."))
        return
    try:
        verdict = reserve(ledger, envelope, spent,
                          note=f"mission {mission.id}")
    except Unmetered:
        # The tenant is not on a plan. Ordinary for a self-hosted deployment,
        # and the mission has already run — refusing now would change nothing
        # except hiding what it cost.
        log.info("%s: no allowance configured; %s units recorded, not charged",
                 mission.id, spent)
        timeline.append(service._event(
            mission, actor=name,
            note=f"cost {spent:g} units, not charged: this tenant is not on a "
                 "plan"))
        return
    except QuotaExhausted as over:
        log.warning("%s: cost %s exceeded an allowance: %s", mission.id, spent,
                    over)
        timeline.append(service._event(
            mission, actor=name,
            note=f"cost {spent:g} units and overran an allowance: {over}"))
        return
    log.info("%s: charged %s units (%s)", mission.id, spent,
             ", ".join(f"{k} {v:g} left" for k, v in verdict.remaining.items()))
    timeline.append(service._event(
        mission, actor=name,
        note=f"charged {spent:g} units against "
             f"{', '.join(sorted(verdict.remaining))}"))


def _agent_of(mission) -> str:
    """Which agent did the work, for the per-agent allowance.

    Read from the recorded invocations rather than from the worker's own
    configuration: the record is what happened, and the configuration is what
    was intended.
    """
    for call in reversed(mission.invocations):
        if call.provider:
            return call.provider
    return ""


def claims_for(dsn: str, *, insist: bool) -> object:
    """What decides who runs a mission on this worker.

    **No silent fallback.** A production worker started with a DSN it cannot
    reach must not quietly become a single-worker deployment: the operator
    believes two workers are safe, both claim the same mission, and two commits
    of the same change appear with no error anywhere. `--require-atomic-claims`
    makes that a refusal to start, which is loud and recoverable.

    Without a DSN it is `LocalClaims`, which is correct for one worker and says
    so in `describe()`.
    """
    if not dsn.strip():
        if insist:
            raise NoAgent(
                "--require-atomic-claims was given with no --claims-dsn. "
                "Refusing to start: a worker cannot promise multi-worker "
                "safety it has no database for.")
        return LocalClaims()
    import psycopg

    try:
        claims = PostgresClaims(psycopg.connect(dsn, autocommit=False),
                                i_have_a_database=True)
        claims.install()
    except (NotVerified, Exception) as failure:   # noqa: BLE001 - reported below
        if insist:
            raise NoAgent(
                f"the claim database could not be reached ({type(failure).__name__}). "
                "Refusing to start rather than falling back to single-worker "
                "claiming, which would let two workers run one mission."
            ) from failure
        log.error("claims: the database was configured and could not be "
                  "reached; this worker is NOT safe to run alongside another")
        return LocalClaims()
    log.info("claims: Postgres-backed, multi-worker safe")
    return claims


def release_stale(timeline: Timeline, *, tenant: str) -> int:
    """Return missions whose worker stopped reporting. Runs before claiming."""
    folded = service.fold(timeline.read(), tenant=tenant)
    live = [service.rehydrate(m, tenant=tenant) for m in folded
            if MissionStatus(m.get("status", "draft")) not in TERMINAL]
    released = recover(live, tenant=tenant)
    for _, event in released:
        timeline.append(event)
    return len(released)


# ---------------------------------------------------------------- the node
#
# A worker announces the machine it is on and keeps saying it is alive. That is
# all this section does. It does not change how work is found, ordered, claimed
# or dispatched — the seam is deliberately one call at start-up and one call per
# pass, so that adopting the cluster substrate cannot alter mission behaviour.
#
# The registry, heartbeat, tables and endpoints already exist in
# `atlas_kernel/cluster` and are used by the Atlas API. Nothing here is a second
# implementation of any of them.


def _probe_resources():
    """What this machine actually has. Absent facts stay absent.

    A missing GPU is `None`, never a guess and never a zero-that-reads-as-known:
    `vram_gb` stays 0 only because there is no card to have any. Every earlier
    row in `atlas_workers` carries zeros for everything, which is what an
    unpopulated schema looks like and is exactly what this replaces.
    """
    import shutil
    import subprocess

    from atlas_kernel.cluster.models import WorkerResources

    cores = os.cpu_count() or 0

    ram_gb = 0
    try:                                          # Linux
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    ram_gb = int(int(line.split()[1]) / 1024 / 1024)
                    break
    except OSError:
        try:                                      # macOS
            out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True, timeout=5,
                                 check=False).stdout.strip()
            ram_gb = int(int(out) / 1024**3) if out.isdigit() else 0
        except (OSError, subprocess.SubprocessError):
            ram_gb = 0

    cards = gpu_inventory()
    mine = _my_gpu(cards)
    gpu = mine[0] if mine else None
    vram_gb = mine[1] if mine else 0

    return WorkerResources(cpu_cores=cores, ram_gb=ram_gb, gpu=gpu,
                           vram_gb=vram_gb)


def gpu_inventory() -> list[tuple[str, int]]:
    """Every card this machine has, as `(name, vram_gb)`, in nvidia-smi order.

    All of them, not the first. The HP Z8 is a multi-GPU box and reading one
    line described it as a single-card machine — which is the kind of wrong that
    looks right, because the field is populated.

    An empty list means no card *or* no answer, and the two are told apart by
    the caller: `WorkerResources.gpu` stays `None` either way, because a card
    that will not answer is not a card we can describe.
    """
    import shutil
    import subprocess

    if not shutil.which("nvidia-smi"):
        return []
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found: list[tuple[str, int]] = []
    for line in out.strip().splitlines():
        name, _, memory = line.partition(",")
        name, memory = name.strip(), memory.strip()
        if not name:
            continue
        # Absent stays absent: a card whose memory did not parse is reported
        # with 0 VRAM rather than dropped, because the card is real.
        found.append((name, int(int(memory) / 1024) if memory.isdigit() else 0))
    return found


def _my_gpu(cards: list[tuple[str, int]]) -> tuple[str, int] | None:
    """Which card *this process* owns.

    One worker process per GPU is the documented topology, and the thing that
    assigns them is `CUDA_VISIBLE_DEVICES`. A process pinned to card 2 must
    advertise card 2 — advertising the first card would have the scheduler
    match against a device this process cannot touch.

    **Never sums.** Four processes on one box each report their own card; adding
    their VRAM together would claim the machine has four times the memory any
    single workload can use, which is the resource lie this whole path exists to
    avoid.

    With no pin, the first card is reported and the rest are recorded in the
    registration metadata rather than being silently lost.
    """
    if not cards:
        return None
    pinned = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    if not pinned:
        return cards[0]
    first = pinned.split(",")[0].strip()
    # A UUID pin (CUDA_VISIBLE_DEVICES=GPU-<uuid>) is a real and valid form that
    # this index-based inventory cannot resolve. Reporting the first card would
    # be a guess; reporting none is the truth.
    if not first.isdigit():
        return None
    index = int(first)
    return cards[index] if 0 <= index < len(cards) else None


def _serves(agent_choice: str) -> str:
    """The agent this worker runs as, by the name a mission would record.

    `REGISTERED_AS` maps a `--agent` choice onto its `fabric.agents` id, and
    every choice has one **except `fake`**, which is deliberately not a
    registered agent. Looking it up with a default of `""` said this worker had
    no declared agent at all -- so a mission routed to `fake` was refused by the
    only worker that could run it, and the fake path worked solely because such
    missions used to name nobody. They no longer can: a mission naming nobody is
    not dispatchable.

    So an unregistered choice serves itself. A worker started with `--agent
    fake` serves `fake`, which is the truth and is what a mission records.
    """
    return REGISTERED_AS.get(agent_choice, agent_choice)


def _capabilities_for(agent_choice: str) -> list[str]:
    """What this worker can do, **derived from the tools its agent declares**.

    Not a second list. `fabric.tools.for_agent` already answers "what may this
    role reach", and a hand-kept capability list beside it is the drift this
    codebase has been bitten by repeatedly — the agent would gain a tool and the
    advertisement would not notice.

    Tool ids are the vocabulary. `WorkerCapability` has its own words for the
    workloads a node can host, and mapping one onto the other would be a third
    thing to keep in step; a capability nobody can act on yet is better named
    honestly than translated.
    """
    from atlas_kernel.fabric.agents import Registry as AgentRegistry
    from atlas_kernel.fabric.agents import UnknownAgent
    from atlas_kernel.fabric.tools import for_agent

    agent_id = _serves(agent_choice)
    if not agent_id:
        return []
    try:
        agent = AgentRegistry().get(agent_id)
    except UnknownAgent:
        return []
    return sorted(tool.id for tool in for_agent(agent))


def _node_snapshots():
    """The workers the scheduler is told about. One definition, in the kernel,
    because `GET /schedule` has to give the same answer this dispatch does."""
    from atlas_kernel.mission.nodes import snapshots
    return snapshots()


def _node_services():
    """The cluster services, constructed from what this process already has.

    Direct, not over HTTP. The worker and the Atlas API talk to the same
    database, and adding a route for a process that can already reach the table
    would be a second way in for no gain.
    """
    # `agents` first, and not for tidiness. `event_bus` imports `agents`, which
    # imports `runtime`, which imports `worker`, which imports `event_bus` — a
    # cycle that resolves only when `agents` is the first of them to load.
    # `composition_root` gets this for free by importing `agents.runtime` at the
    # top of the file; a lazy import inside a function does not, and lands in
    # the middle of the cycle.
    #
    # Pre-existing and left alone: untangling it is a change to the Atlas
    # lineage, which this slice does not touch.
    import atlas_kernel.agents  # noqa: F401  (import order, see above)
    from atlas_kernel.cluster.heartbeat_service import HeartbeatService
    from atlas_kernel.cluster.worker_registry import WorkerRegistry
    from atlas_kernel.event_bus import EventBus
    from atlas_kernel.repository import AtlasRepository

    repository = AtlasRepository()
    bus = EventBus()
    registry = WorkerRegistry(repository, bus)
    return registry, HeartbeatService(repository, bus, registry)


def _source_fingerprint() -> str:
    """The sha256 of this file, first 12 -- what is actually running here.

    A deploy reported success while shipping none of this file: `deploy_control.sh`
    synced `packages/kernel/atlas_kernel/` and the console, and nothing has ever
    shipped `infra/`. The host's own git checkout is 181 commits behind and does
    not track this file at all, so "is production running the repository's
    worker?" had no answer that could be checked.

    Reported through the `version` field the registry already stores, so the
    answer is one query rather than an ssh and a hash. This file is the whole of
    the worker's out-of-band code -- it imports only the standard library and
    `atlas_kernel`, and `atlas_kernel` is shipped and health-checked by the
    existing deploy.

    Unreadable source is reported as `unknown` rather than crashing the worker: a
    node that cannot describe itself must still do its work.
    """
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
    except OSError:
        log.exception("could not fingerprint own source")
        return "unknown"


def _register_node(name: str, agent_choice: str, placement: str = "either") -> str:
    """Announce this machine once, at start-up. Returns the worker id, or "".

    **A failure here does not stop the worker.** A node that cannot announce
    itself must still do the work it already knows about: the ledger, the claims
    and the missions are unaffected by whether anybody knows this machine
    exists. Reported loudly and carried on from.

    Idempotent per hostname, so a restart keeps the id and its history rather
    than accumulating a row per boot.
    """
    try:
        from atlas_kernel.cluster.models import WorkerRegistration

        registry, _ = _node_services()
        resources = _probe_resources()
        capabilities = _capabilities_for(agent_choice)
        machine = socket.gethostname()
        # One identity per **worker process**, not per machine.
        #
        # Four Qevik workers share this host and declare different tools. A
        # machine-level identity would collapse them into one row whose
        # capabilities are whichever process registered last, and later
        # capability-matched dispatch would route `site-publish` work to a
        # machine that collectively claims every tool rather than to the
        # publisher that holds it.
        #
        # `hostname` carries the same composite, and that is not decoration:
        # `WorkerRegistry.register` falls back to `get_worker_by_hostname` when
        # the explicit id is not found, so a shared hostname would have the
        # second process adopt the first process's row on its very first
        # registration. The machine is kept in `metadata` and `tags`, where
        # nothing is lost.
        identity = f"{machine}:{name}"
        node = registry.register(WorkerRegistration(
            worker_id=identity,
            hostname=identity,
            display_name=name,
            platform=sys.platform,
            resources=resources,
            capabilities=capabilities,
            max_concurrency=1,
            # This process collects Qevik missions. It never polls the Atlas
            # execution queue, so it must not be handed an Atlas execution --
            # which capability alone could not prevent, because an unresolvable
            # capability becomes "" and "" is read as no constraint at all.
            accepts_execution_dispatch=False,
            version=_source_fingerprint(),
            # `serves:` is the registered agent id, not the `--agent` choice.
            # The scheduler matches a mission's recorded agent against it, and
            # the two vocabularies differ: `--agent research` serves
            # `researcher`. `placement:` is what this machine can satisfy,
            # stated rather than guessed at.
            tags=[f"role:{agent_choice}", f"serves:{_serves(agent_choice)}",
                  f"placement:{placement}", f"machine:{machine}",
                  "qevik-mission-worker"],
            metadata={"machine": machine, "worker_name": name,
                      "agent": agent_choice, "serves": _serves(agent_choice),
                      "placement": placement,
                      # Every card on the box, so a multi-GPU host is not
                      # described by whichever one this process happens to own.
                      # `resources` stays this process's card alone and is never
                      # a sum; this is the inventory beside it.
                      "gpus": [{"name": n, "vram_gb": v}
                               for n, v in gpu_inventory()],
                      "cuda_visible_devices":
                          os.environ.get("CUDA_VISIBLE_DEVICES", "")}))
        log.info("registered as %s on %s: %d core(s), %d GB RAM, gpu=%s, "
                 "capabilities %s", node.id, machine,
                 resources.cpu_cores, resources.ram_gb,
                 resources.gpu or "none", ", ".join(capabilities) or "none")
        return node.id
    except Exception:                             # noqa: BLE001 - reported
        log.exception("could not register this node; continuing without it. "
                      "The ledger, the claims and the missions do not depend "
                      "on anybody knowing this machine exists.")
        return ""


def _stand_down(worker_id: str) -> None:
    """Mark this node offline as the process leaves.

    A registration outlives the process that made it. The heartbeat timeout
    eventually notices, but for those ninety seconds a worker that has already
    exited still looks like a healthy candidate -- and once the scheduler
    started *choosing* a worker rather than merely allowing one, that gap
    stopped being cosmetic: work was assigned to a process that had gone, and
    the worker still running skipped it because it had not been chosen.

    Found by running the real binary, not in the test suite: five node rows all
    serving `self-check`, all left behind by earlier runs, all inside the
    heartbeat window.

    Best effort by design. A worker killed outright cannot run this, which is
    exactly what the heartbeat timeout is still there for.
    """
    if not worker_id:
        return
    try:
        registry, _ = _node_services()
        registry.mark_offline(worker_id, reason="worker exited")
    except Exception:
        log.exception("could not stand down %s; the heartbeat timeout will",
                      worker_id)


def _heartbeat(worker_id: str) -> None:
    """Say this machine is alive. Runs every pass, whatever the pass found.

    Independent of mission activity on purpose. Liveness of a *machine* and
    progress of a *mission* are different facts with different timeouts — 90
    seconds here, 900 for a claim — and a heartbeat that only fired when work
    was running would report an idle worker as dead.
    """
    if not worker_id:
        return
    try:
        from atlas_kernel.cluster.models import HeartbeatReport

        _, heartbeats = _node_services()
        heartbeats.record(HeartbeatReport(worker_id=worker_id))
    except Exception:                             # noqa: BLE001 - reported
        log.warning("heartbeat failed for %s; the mission work is unaffected",
                    worker_id, exc_info=True)


def _tools_of(mission: Mission) -> tuple[str, ...]:
    """The tools this mission's declared recipe may use.

    Read from the declaration rather than from what happened to run, so a
    report says what the mission was *permitted*, which is the question a
    reviewer asking "could this have contacted anybody" is really asking.
    """
    if not mission.recipe:
        return ()
    try:
        return recipes.get(mission.recipe).tools
    except recipes.UnknownRecipe:
        return ()


def _artefact_of(worker: object) -> tuple[str, ...]:
    """What the delivering agent wrote, if this mission delivered anything.

    Dug out defensively: most roles have no artefact, and a report that failed
    to be written because a role lacked an attribute would lose the account of
    a mission that did run.
    """
    roles = getattr(worker, "_roles", None)
    return tuple(getattr(getattr(roles, "implementer", None), "artefact", ()) or ())


def build_worker(name: str, timeline: Timeline, *, worktrees: Path,
                 origin: origins.Origin, roles: Roles,
                 scratch_root: Path, agent_choice: str = "",
                 mission: Mission | None = None,
                 tenant: str = "") -> tuple[Worker, dict]:
    """A worker with an isolated workspace per mission.

    `held` carries the workspace out so the caller can commit and clean up; the
    worker itself is not given a repository, only a directory it may write in.

    `origin` has already been resolved from the mission's declared name
    against the allow-list, and is only ever read. Each mission gets
    its own clone under `scratch_root`, and the worktree is added inside that
    clone. Before this, `git worktree add` ran in the origin and wrote a ref, a
    worktree entry and every committed object into it — so a mission modified
    the production checkout simply by running, and a failed one left its branch
    behind there.

    An EMPTY origin gives a fresh repository instead. Work that has
    no source to start from still needs somewhere to write, and handing it a
    clone of Qevik because that is what was lying around is how unrelated work
    gets classified as self-modification.
    """
    held: dict = {}
    spaces: dict = {}

    # A research role carries out the recipe the **mission** names. The roles
    # object was built at start-up with a placeholder, because `Roles` must hold
    # an agent to exist; this replaces it with one built from the mission in
    # hand. A mission naming no recipe is refused in `pass_once` rather than
    # defaulted — defaulting would run a recipe nobody asked for.
    if agent_choice in {"research", "delivery", "publish"} \
            and mission is not None and mission.recipe:
        from atlas_kernel.mission.toolrunner import ToolAgent

        # The repository is what turns evidence into memory, and for a
        # verification recipe it is also where the targets come from. Without
        # it such a run fetches nothing and remembers nothing.
        #
        # `needs_memory` rather than `.extractor`, which is what this asked
        # before: the condition lived here while the fields that decide it live
        # on the recipe, and the two drifted the moment `audit` and
        # `targets_from` were added.
        memory = None
        if recipes.get(mission.recipe).needs_memory:
            try:
                from atlas_kernel.opportunity.repository import (
                    OpportunityRepository,
                )

                memory = OpportunityRepository()
            except Exception:                     # noqa: BLE001 - reported
                log.exception("%s needs business memory and it could not be "
                              "opened; the run will produce evidence and "
                              "remember nothing", mission.recipe)
        # The workspace of the mission being published, resolved here because
        # this owns the ledger. A publisher that guessed the path would be a
        # publisher that can be pointed at a directory by naming a mission.
        source_workspace = ""
        if mission.publishes:
            source = next(
                (m for m in service.fold(Timeline(timeline.path).read(),
                                         tenant=tenant)
                 if m["mission_id"] == mission.publishes), {})
            source_workspace = source.get("workspace") or ""

        roles = Roles.all(ToolAgent(recipes.get(mission.recipe),
                                    repository=memory, tenant=tenant,
                                    # The approval, by id. The agent reads the
                                    # opportunity itself and re-checks it; this
                                    # hands over a key, never a record.
                                    signal_id=mission.signal_id,
                                    publishes=mission.publishes,
                                    scratch_root=str(scratch_root),
                                    source_workspace=source_workspace,
                                    mission_id=mission.id))
        log.info("%s: recipe %s%s%s", mission.id, mission.recipe,
                 "" if memory is None else " (business memory available)",
                 f" delivering {mission.signal_id}" if mission.signal_id else "")

    def workspace_for(mission: Mission) -> Path:
        area = scratch.prepare(origin.location(), mission_id=mission.id,
                               root=scratch_root)
        spaces[mission.id] = area
        space = GitWorkspace.create(area.path, branch=f"mission/{mission.id}",
                                    worktrees=worktrees)
        held[mission.id] = space
        # A path, never the GitWorkspace itself. Handing back the object made an
        # agent write files into a directory literally named
        # `GitWorkspace(repository=…` and three missions failed before anybody
        # looked at the filename.
        return space.root

    def commit(mission: Mission, outcome) -> str:
        space = held.get(mission.id)
        if space is None:
            return ""
        # A role that writes no files has nothing to commit, and that is its
        # correct outcome rather than a failure. `GitWorkspace.commit` refuses
        # an unchanged tree — rightly, for a coding role — so this asks first.
        #
        # It is not a way for a coding role to skip committing: an agent that
        # claimed success and produced nothing was already refused upstream by
        # `outcome.produced_nothing`, before the tests ever ran.
        if not outcome.files:
            log.info("%s: nothing to commit — the role produced %d piece(s) of "
                     "evidence and no files", mission.id,
                     getattr(outcome, "evidence_count", 0))
            return ""
        return space.commit(f"{mission.title}\n\n{outcome.summary}".strip()).sha

    def accepted(mission: Mission, outcome) -> tuple[bool, str]:
        """The agent claims it is done; check that something actually happened.

        Two questions, because there are two kinds of role and one question
        does not fit both. A coding role is checked on files written. A
        research role writes none by design — asking it for files would fail
        every successful run — so it is checked on **evidence recorded**.

        Which question is asked comes from the role this worker was started
        with, not from what the outcome happens to contain: an outcome with no
        files could be a research run or a coding run that did nothing, and
        guessing from the shape would let the second pass as the first.
        """
        if agent_choice == "research":
            recorded = getattr(roles.implementer, "result", None)
            if recorded is None or not recorded.evidence:
                return False, ("the mission claims completion and recorded no "
                               "evidence, which is not a successful research run")
            return True, (f"{len(recorded.evidence)} piece(s) of evidence via "
                          f"{', '.join(recorded.tools_invoked)}")

        if agent_choice == "publish":
            # A publication writes to the site host and changes nothing in its
            # workspace, so the file question is the wrong one — asked of it,
            # every successful publication fails. It is checked on the
            # verification fetch: the address was requested afterwards and
            # answered, which is the only evidence that distinguishes a
            # publication from a claim about one.
            recorded = getattr(roles.implementer, "result", None)
            published = getattr(roles.implementer, "published", ())
            if recorded is None or not recorded.evidence:
                return False, ("the mission claims a publication and recorded "
                               "no fetch of the address, so nothing establishes "
                               "that a visitor gets the page")
            return True, (f"{len(published)} file(s) published, and the address "
                          "was fetched and served them")

        space = held.get(mission.id)
        if space is None:
            return False, "no workspace was created"
        written = [f for f in outcome.files if (space.root / f).is_file()]
        if not written:
            return False, "the mission claims completion but wrote no files"
        return True, f"{len(written)} file(s) written"

    worker = Worker(name=name, roles=roles,
                    acceptance=Acceptance(check=accepted, name="wrote something"),
                    workspace_factory=workspace_for, committer=commit,
                    sink=timeline.append)
    # Both maps: the caller needs the workspace to commit, and the scratch to
    # record what the mission actually operated on.
    return worker, {"worktrees": held, "scratch": spaces}


def credential_service(credentials_at: CredentialPaths) -> object:
    """The vault this worker reads, opened once.

    Separate from `roles_for` so the dispatch check and the agents share one
    view: two `CredentialService` objects over the same files would answer the
    same question at different moments and disagree about what is configured.
    """
    records = Timeline(credentials_at.records)
    return CredentialService(Vault(FileSecretStore(credentials_at.vault)),
                             events=records.read(), sink=records.append)


def tenant_headroom(ledger: object, tenant: str) -> float | None:
    """What this tenant can still afford, or None if nothing meters it.

    `budgets.assess` exists so "the scheduler can decline to start work it
    cannot finish", and nothing was calling it: `queued()` accepted
    `remaining_units` and `pass_once` never passed one, so the budget was
    consulted **after** the work — by `_charge` — and never before it. A mission
    beyond its tenant's allowance dispatched, ran, cost money, and was refused
    at the ledger afterwards.

    `None` is UNKNOWN and stays UNKNOWN all the way to the scheduler, which has
    its own rule for unpriced work. It is never turned into a number here, and
    an unmetered tenant is not one with an infinite balance — it is one nobody
    measured.
    """
    try:
        return assess(ledger, Envelope(tenant_id=str(tenant)), 0.0).headroom
    except Unmetered:
        return None
    except Exception:                             # noqa: BLE001 - logged, not fatal
        log.exception("could not read the allowance for %s; treating it as "
                      "unknown rather than as plenty", tenant)
        return None


def refuse_over_budget(ledger: object, mission: Mission, *,
                       tenant: str) -> str:
    """Why this mission cannot be afforded, or "".

    A gate, not advice. `budgets.assess` asks **every** scope the work sits
    inside — tenant, mission, agent — and spends nothing doing it, which is
    precisely why it exists: "the scheduler can decline to start work it cannot
    finish without that question itself costing an allowance."

    The scheduler's own budget rule runs earlier, on the tenant's headroom from
    a fold that may be seconds old. This is the last word, taken from the ledger
    at the moment of dispatch.

    An **unpriced** plan is not refused here. It is not free, and it is not
    zero: `policy.decide` already required a person for it, and refusing it
    again on a cost nobody stated would wall off every unestimated mission for
    ever. What it must never do is charge a guessed number, and it does not —
    `_charge` records UNKNOWN afterwards instead.

    An unmetered tenant is not one with an infinite balance; it is one nobody
    measured, and there is nothing to refuse it against.
    """
    estimate = mission.plan.estimated_cost if mission.plan else None
    if estimate is None:
        return ""
    envelope = Envelope(tenant_id=str(tenant), mission_id=mission.id,
                        agent_id=mission.agent_id)
    try:
        verdict = assess(ledger, envelope, float(estimate))
    except Unmetered:
        return ""
    except Exception:                             # noqa: BLE001 - logged, not fatal
        log.exception("could not assess the budget for %s; refusing rather than "
                      "assuming it fits", mission.id)
        return ("the allowance could not be read, and starting work that might "
                "not be covered is worse than waiting for an answer")
    if verdict.affordable:
        return ""
    scope = verdict.refused_by.value if verdict.refused_by else "an allowance"
    return (f"this needs about {estimate:g} units and the {scope} allowance "
            f"cannot carry it: {verdict.reason}. Stopping halfway spends the "
            "money and produces nothing.")


def tick_recurrences(timeline: Timeline, *, tenant: str, name: str,
                     claims: object, registry: origins.Registry,
                     at: datetime | None = None) -> int:
    """Create missions for any recurrence that has come due. Returns how many.

    Runs inside the worker rather than as a daemon of its own, because a second
    process that also puts work in the queue is a second orchestrator however
    small it is. This only ever calls `service.create` and `service.attach_plan`
    — the same two functions a request typed into the console goes through — and
    then stops. It never claims, dispatches or runs anything.

    Two workers tick at the same time, so the occurrence key is held through the
    same `Claims` the missions themselves use. Losing that race is ordinary. The
    lock is not the only guard: `assess` independently refuses an occurrence
    that already has a mission, which is what covers the case where a lock was
    reclaimed after a crash. A lock is a hint about now; a mission is a fact.
    """
    moment = at or datetime.now(UTC)
    due = recurrence.declared(tenant=tenant)
    if not due:
        return 0

    folded = service.fold(timeline.read(), tenant=tenant)
    created = 0
    for rule in due:
        firing = recurrence.assess(rule, at=moment, missions=folded)
        if not firing.fires:
            log.debug("recurrence %s held: %s (%s)", rule.id,
                      firing.hold.value if firing.hold else "?", firing.detail)
            continue

        # Resolved before the mission exists. A recurrence naming an origin
        # this worker cannot serve is a configuration error, and the place to
        # find that out is here — not after a mission has been created that
        # nothing can dispatch.
        try:
            origin = registry.resolve(rule.origin_name)
        except origins.UnknownOrigin as refusal:
            log.error("recurrence %s names an origin this worker does not have: "
                      "%s", rule.id, refusal)
            continue

        claims.register(firing.key) if hasattr(claims, "register") else None
        if not claims.acquire(firing.key, worker=name):
            log.info("recurrence %s: %s is being created by another worker",
                     rule.id, firing.key)
            continue
        try:
            mission, events = recurrence.enqueue(rule, firing, tenant=tenant,
                                                 origin=origin)
            for event in events:
                timeline.append(event)
            created += 1
            log.info("recurrence %s created %s (%s) as %s in origin %s",
                     rule.id, mission.id, firing.key, mission.status.value,
                     origin.name)
        finally:
            claims.release(firing.key, worker=name)
    return created


def pass_once(timeline: Timeline, *, tenant: str, name: str, worktrees: Path,
              node_id: str = "",
              registry: origins.Registry, roles: Roles, claims: object,
              ledger: object, scratch_root: Path, report_root: Path,
              credentials: object = None, agent_choice: str = "") -> int:
    """Recover, then take at most one mission. Returns how many ran."""
    # First, and unconditionally. A heartbeat that fired only when work was
    # found would report an idle worker as dead — and "idle" is the normal
    # state of a worker between nightly recurrences.
    _heartbeat(node_id)

    freed = release_stale(timeline, tenant=tenant)
    if freed:
        log.info("released %d stale mission(s)", freed)

    # Before looking for work, create any that has come due. A recurrence that
    # fires into an empty queue should be picked up on this same pass rather
    # than waiting for the next one.
    made = tick_recurrences(timeline, tenant=tenant, name=name, claims=claims,
                            registry=registry)
    if made:
        log.info("%d recurring mission(s) created", made)

    # The allowance, before choosing work rather than after doing it. The
    # scheduler refuses a mission whose estimate the tenant cannot carry, and an
    # unpriced mission needs headroom of its own.
    waiting = queued(timeline, tenant=tenant,
                     connected=usable_for(credentials, tenant=tenant),
                     remaining_units=tenant_headroom(ledger, tenant),
                     agent_id=_serves(agent_choice),
                     worker_name=name, nodes=_node_snapshots())
    if not waiting:
        return 0

    mission = waiting[0]

    # The atomic claim, before anything else touches the mission. The scheduler
    # named it dispatchable; that is advice, and two workers can be given the
    # same advice at the same instant. This is the one place that resolves it,
    # and losing the race is ordinary — not an error.
    claims.register(mission.id) if hasattr(claims, "register") else None
    if not claims.acquire(mission.id, worker=name):
        log.info("%s went to another worker", mission.id)
        return 0

    # Everything from here to the run is inside `_refuse`, which releases the
    # claim whatever happens.
    #
    # It did not used to be. Each refusal released the claim on its own normal
    # path, and one of them raised on the line *before* the release — a
    # `PermissionError` appending to the timeline — so the claim was stranded
    # and **both** workers reported "went to another worker" for fifteen
    # minutes, until the staleness reclaim freed it. Found in production, on the
    # first real deploy, because a file had the wrong owner.
    #
    # A refusal that leaks a claim is worse than the thing it refuses.
    def _refuse(note: str) -> int:
        log.error("refusing %s: %s", mission.id, note)
        try:
            blocked, event = service.transition(
                mission, MissionStatus.BLOCKED, tenant=tenant, actor=name,
                claimed_by="", note=note[:300])
            timeline.append(event)
        except Exception:                         # noqa: BLE001 - logged, not fatal
            log.exception("could not record the refusal of %s; releasing the "
                          "claim anyway so it is not stranded", mission.id)
        finally:
            claims.release(mission.id, worker=name)
        return 0

    # Which repository this mission is allowed to touch. The mission names a
    # key; the registry — built at start-up from code and deployment
    # configuration — is the only thing that turns a key into a location. A name
    # nobody registered is a refusal, never a fall back to the default, because
    # the default is Qevik.
    try:
        origin = registry.resolve(mission.origin_name)
    except origins.UnknownOrigin as refusal:
        return _refuse(str(refusal))
    log.info("%s: origin %s (%s)", mission.id, origin.name, origin.kind.value)

    # A research mission must name the recipe it carries out. Refused rather
    # than defaulted: a worker that picked one would be choosing the work.
    if agent_choice == "research" and not mission.recipe:
        return _refuse(
            "this worker runs declared recipes and the mission names none. "
            f"Known: {', '.join(sorted(r.id for r in recipes.RECIPES))}")
    if agent_choice == "research" and mission.recipe:
        try:
            recipes.get(mission.recipe)
        except recipes.UnknownRecipe as unknown:
            return _refuse(str(unknown))

    worker, workspaces = build_worker(name, timeline, worktrees=worktrees,
                                      origin=origin, roles=roles,
                                      scratch_root=scratch_root,
                                      agent_choice=agent_choice,
                                      mission=mission, tenant=tenant)
    held, scratches = workspaces["worktrees"], workspaces["scratch"]

    # The origin is a fact; what the plan declared about it is a field. They can
    # disagree, and this is where that is caught — after the claim, so the
    # refusal is recorded against a mission somebody can find, and before any
    # agent runs.
    #
    # Three of them, all in the same place and all before any agent runs. Each
    # asks about a different thing that could have changed between the moment a
    # person approved the plan and the moment this worker picked it up.
    serves = _serves(agent_choice)

    # A mismatch here means this worker cannot run it — **not** that the mission
    # is bad. It is released for a worker that serves the right agent, and left
    # queued. Blocking it would take a perfectly good mission out of the queue
    # because the wrong process happened to win a race for it.
    mismatch = policy.refuse_agent_substitution(mission.agent_id, serves)
    if mismatch:
        log.info("%s is not for this worker: %s", mission.id, mismatch)
        claims.release(mission.id, worker=name)
        return 0

    for refusal in (
        # ...the repository it will actually touch
        policy.refuse_unapproved_self_modification(
            service.history(timeline.read(), mission.id, tenant=tenant),
            origin_is_qevik=origin.modifies_qevik_itself),
        # ...the repository and the budget below. The agent is checked
        # separately, just above, because its answer is "not by me" rather than
        # "not at all" and the two must not share an outcome.

        # ...and whether every allowance it sits inside can still carry it. The
        # scheduler already checked the tenant's headroom, which is advice
        # computed from a fold that may be seconds old; this asks the ledger
        # itself, across tenant, mission and agent, with the actual estimate.
        refuse_over_budget(ledger, mission, tenant=tenant),
    ):
        if not refusal:
            continue
        return _refuse(refusal)

    log.info("claiming %s — %s", mission.id, mission.title)
    try:
        result = worker.run(mission, tenant=tenant)
    finally:
        # Released whatever happened. A worker that crashes holding a claim
        # leaves the mission looking busy until the staleness timeout, and the
        # timeout is a backstop rather than the mechanism.
        claims.release(mission.id, worker=name)
    log.info("%s finished as %s (attempts %d, commit %s)", mission.id,
             result.mission.status.value, result.attempts,
             result.committed or "none")

    # Where the work actually happened, recorded on the mission itself. Without
    # it a report says "committed abc1234" and nothing anywhere says which
    # repository that sha exists in — which, now that it is never the production
    # one, is the difference between a commit somebody can find and a rumour.
    area = scratches.get(mission.id)
    if area is not None:
        result.mission = result.mission.model_copy(update={
            "workspace": str(area.path),
            "origin": str(area.origin) if area.origin else "",
            "origin_kind": area.kind.value})
        timeline.append(service._event(result.mission, actor=name,
                                       note=f"worked in {area.kind.value} scratch"))

    # What it cost, charged against every enclosing allowance.
    #
    # After the work, not before: the estimate gates *dispatch* (the scheduler
    # already refused missions the tenant cannot afford), and this records what
    # was actually consumed. Charging an estimate up front and never reconciling
    # is how a month's usage drifts away from the month's bill.
    _charge(result, tenant=tenant, ledger=ledger, timeline=timeline, name=name)

    # A report per mission, written by the worker rather than by whichever
    # script happened to start it. Without this a mission run in production
    # completes, commits, and leaves nothing a person can read — which the
    # console then correctly reports as "no report", because there is none.
    try:
        written = reports.write(
            result.mission, root=report_root,
            attempts=result.attempts, committed=result.committed,
            detail=result.detail,
            tests=result.detail or "acceptance check",
            branch=f"mission/{mission.id}",
            evidence=result.report,
            tools=_tools_of(mission),
            artefact=_artefact_of(worker),
            files=tuple(held[mission.id].changed()) if mission.id in held else ())
        log.info("report written to %s", written)
        # Recorded on the mission itself, so `/api/missions/{id}/report` can
        # find it. A report nothing points at is a file in a directory.
        result.mission = result.mission.model_copy(update={
            "report_path": str(written.relative_to(report_root))})
        timeline.append(service._event(result.mission, actor=name,
                                       note="report written"))
    except Exception:                            # noqa: BLE001 - logged, not fatal
        log.exception("could not write a report for %s", mission.id)

    space = held.get(mission.id)
    if space is not None and result.succeeded:
        # A failed mission's worktree is kept, so somebody can look at what the
        # agent actually wrote. A successful one has been committed already.
        space.discard()

    # The scratch clone is **never** discarded here, and the first version of
    # this code discarded it on success — which destroyed the commit. That is
    # the difference the clone makes: the branch used to live in the origin
    # repository and survived cleanup on its own, and now it exists only here.
    # Deleting it after a successful mission throws away the exact artefact the
    # promotion boundary exists to hand to a person.
    #
    # So clones accumulate, at roughly the size of the origin each. Pruning them
    # needs a record of what has been promoted, which does not exist yet;
    # keeping a deliverable is the right way to be wrong in the meantime.
    area = scratches.get(mission.id)
    if area is not None:
        log.info("%s: commits are in %s (branch mission/%s) — not promoted",
                 mission.id, area.path, mission.id)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeline", required=True,
                        help="the JSONL mission timeline shared with the API")
    parser.add_argument("--tenant", default="tenant-qevik")
    parser.add_argument("--name", default="worker-1")
    parser.add_argument("--origin", action="append", default=[], metavar="NAME=PATH",
                        help="a customer repository a mission may name. "
                             "Repeatable. The built-in origins are 'qevik' "
                             "(this checkout, self-modification) and 'none' "
                             "(no source). An entry pointing at Qevik's own "
                             "repository is refused at start-up")
    # --repository is gone on purpose. It was one global repository for the
    # whole process, which meant every mission on a worker was the same kind of
    # mission. Refused rather than ignored: a unit file still passing it would
    # otherwise start successfully and silently do something else.
    parser.add_argument("--repository", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--scratch", default="",
                        help="where each mission's clone of the origin goes "
                             "(default: a temp dir). The origin itself is only "
                             "ever read")
    parser.add_argument("--worktrees", default="",
                        help="where isolated worktrees go (default: a temp dir)")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true",
                        help="make one pass and exit, for tests and cron")
    # Defaulted from the environment, not required on the command line: a DSN
    # carries a password, and a password on an argv line is visible in `ps` to
    # every user on the host. An EnvironmentFile at 0600 is not.
    parser.add_argument("--quota-timeline", default="",
                        help="where allowances and spends live. Defaults to "
                             "quota.jsonl beside the mission timeline, which "
                             "is where the control plane keeps it — a separate "
                             "file would give the worker its own balance")
    parser.add_argument("--claims-dsn",
                        default=os.environ.get("QEVIK_CLAIMS_DSN", ""),
                        help="PostgreSQL DSN for cross-process atomic claims. "
                             "Defaults to QEVIK_CLAIMS_DSN, which is where it "
                             "belongs — argv is world-readable")
    parser.add_argument("--require-atomic-claims", action="store_true",
                        default=os.environ.get(
                            "QEVIK_REQUIRE_ATOMIC_CLAIMS", ""
                        ).strip().lower() in ("1", "true", "yes"),
                        help="refuse to start unless the claim database is "
                             "reachable. Use this in production: the default "
                             "logs the loss of safety, this one prevents it")
    parser.add_argument("--placement", default="either",
                        choices=("either", "local", "cloud"),
                        help="what this machine can satisfy. `local` is the "
                             "operator's own machine; `cloud` survives it "
                             "sleeping. Stated rather than detected, because a "
                             "guess here decides where somebody's work runs.")
    parser.add_argument("--agent", default="llm", choices=AGENT_CHOICES,
                        help="'research' carries out a declared recipe through "
                             "registered tools and calls no model; 'delivery' "
                             "builds the artefact an approved opportunity asked "
                             "for. 'fake' runs a deterministic stub. Never the "
                             "default: everything it produces would claim work "
                             "nothing did.")
    parser.add_argument("--reports", default="",
                        help="where mission reports are written "
                             "(default: alongside the repository)")
    parser.add_argument("--state", default="",
                        help="the durable state directory the Credential "
                             "Centre writes to. Defaults to QEVIK_STATE. Names "
                             "a directory, never a file: the file names belong "
                             "to credentials.location, and a caller choosing "
                             "one is how the two processes drifted apart")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    timeline = Timeline(args.timeline)
    # The same file the control plane reads. Two ledgers would be two answers
    # to "what is left", and nobody could say which one the bill came from.
    quota_path = Path(args.quota_timeline or
                      Path(args.timeline).parent / "quota.jsonl")
    quota_events = Timeline(quota_path)
    ledger = QuotaLedger(events=quota_events.read(), sink=quota_events.append)
    worktrees = Path(args.worktrees or tempfile.mkdtemp(prefix="qevik-missions-"))
    scratch_root = Path(args.scratch or tempfile.mkdtemp(prefix="qevik-scratch-"))
    # Resolved once. `report_root or repository` was the old fallback, and it
    # stops being safe the moment there is no single repository to fall back to.
    report_root = Path(args.reports) if args.reports else Path(
        tempfile.mkdtemp(prefix="qevik-reports-"))

    # The allow-list, built here so a bad entry fails at start-up in front of
    # whoever configured it. There is deliberately no global repository any
    # more: each mission names an origin and the registry resolves it.
    #
    # `QEVIK_ORIGINS` first, then `--origin`. The environment is what a
    # deployment sets, and it is what the **control plane** reads — so a
    # customer origin configured there is one the console can offer and the
    # worker can serve, from a single declaration. `--origin` is for a harness
    # or a one-off, and a name given both ways is refused rather than quietly
    # taking one of them.
    try:
        declared = origins.from_environment()
        for name, path in origins.parse_pairs(args.origin).items():
            if name in declared:
                raise origins.OriginRefused(
                    f"{name!r} is set in {origins.ENVIRONMENT} and given with "
                    "--origin. Whichever won would be invisible; pick one.")
            declared[name] = path
        registry = origins.Registry.build(declared)
    except origins.OriginRefused as refusal:
        log.error("origins: %s", refusal)
        return 2
    log.info("origins: %s — each mission names one; a name nobody registered is "
             "refused, never defaulted", ", ".join(
                 f"{o.name}({o.kind.value})" for o in registry.origins))
    log.info("clones go under %s; every origin is read-only", scratch_root)

    if args.repository is not None:
        log.error(
            "--repository is gone. It set one repository for the whole worker, "
            "so every mission on it was the same kind of mission. A mission now "
            "names its own origin and the worker resolves it against an "
            "allow-list: use --origin NAME=PATH for a customer repository. The "
            "built-ins 'qevik' and 'none' need no configuration.")
        return 2

    credentials_at = paths_for(args.state or None)
    credentials = credential_service(credentials_at)
    try:
        roles = roles_for(args.agent, tenant=args.tenant,
                          credentials_at=credentials_at)
        claims = claims_for(args.claims_dsn,
                            insist=args.require_atomic_claims)
    except NoAgent as refusal:
        log.error("%s", refusal)
        return 2
    log.info("claiming: %s", describe_claims(claims)["status"])
    # Where this process looks for credentials, said once at start-up whether or
    # not this agent needs any. The bug that made this module necessary was
    # invisible precisely because neither process ever printed which file it was
    # reading — an operator comparing a Centre showing CONNECTED against a
    # worker saying "no credential configured" had nothing to compare.
    log.info("credentials: %s", describe_credentials(credentials_at.state))

    # Announced once, at start-up, beside the other things this worker says
    # about itself. A failure returns "" and everything below carries on.
    node_id = _register_node(args.name, args.agent, args.placement)

    if args.once:
        try:
            pass_once(timeline, tenant=args.tenant, name=args.name,
                      node_id=node_id,
                      worktrees=worktrees, registry=registry, roles=roles,
                      claims=claims, ledger=ledger, scratch_root=scratch_root,
                      report_root=report_root, credentials=credentials,
                      agent_choice=args.agent)
        finally:
            # A single pass exits immediately, so without this it leaves a row
            # that looks alive for the next ninety seconds.
            _stand_down(node_id)
        return 0

    # The store, not the path. It said "watching …/missions.jsonl" while reading
    # Postgres, which is the log telling an operator the wrong thing about where
    # the state is — the sentence somebody reads first during an incident.
    log.info("watching the %s ledger for %s%s", timeline.backend, args.tenant,
             "" if timeline.networked else f" at {timeline.path}")
    try:
        while True:
            try:
                pass_once(timeline, tenant=args.tenant, name=args.name,
                          node_id=node_id,
                          worktrees=worktrees, registry=registry, roles=roles,
                          claims=claims, ledger=ledger, scratch_root=scratch_root,
                          report_root=report_root, credentials=credentials,
                          agent_choice=args.agent)
            except KeyboardInterrupt:
                log.info("stopping")
                return 0
            except Exception:                    # noqa: BLE001 - logged, keep going
                log.exception("pass failed; continuing")
            time.sleep(args.interval)
    finally:
        # Whichever way the loop is left. The claim it may hold is untouched --
        # standing down says "this machine is gone", never "this mission is
        # free", and those stay two different questions with two timeouts.
        _stand_down(node_id)


if __name__ == "__main__":
    raise SystemExit(main())
