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
import logging
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from atlas_kernel.credentials.models import (  # noqa: E402
    Role,
    Selection,
    chosen_for,
    registry_for,
)
from atlas_kernel.credentials.service import CredentialService  # noqa: E402
from atlas_kernel.credentials.vault import FileSecretStore, Vault  # noqa: E402
from atlas_kernel.fabric import scheduler  # noqa: E402
from atlas_kernel.fabric.scheduler import demands_from  # noqa: E402
from atlas_kernel.mission import reports, service  # noqa: E402
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

log = logging.getLogger("mission-worker")


class NoAgent(RuntimeError):
    """No model is available, and the worker will not invent one."""


def roles_for(kind: str, *, tenant: str, vault_root: Path | None = None) -> Roles:
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

    if kind == "fake":
        log.warning("running with the deterministic fake agent: no model will "
                    "be called and nothing it produces reflects real work")
        return Roles.all(FakeCodingAgent(behaviour=Behaviour.SUCCESS, writes=True))

    store = FileSecretStore(vault_root / "credentials.json") if vault_root else None
    credentials = CredentialService(Vault(store))
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


def queued(timeline: Timeline, *, tenant: str,
           connected: frozenset[str] = frozenset(),
           remaining_units: float | None = None) -> list[Mission]:
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
    demands = demands_from(folded, connected=connected,
                           remaining_units=remaining_units)
    plan = scheduler.plan(demands, tenant=tenant, done=done, concurrency=1)

    by_id = {m.get("mission_id"): m for m in folded}
    runnable = []
    for mission_id in plan["dispatchable"]:
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


def build_worker(name: str, timeline: Timeline, *, worktrees: Path,
                 repository: Path, roles: Roles) -> tuple[Worker, dict]:
    """A worker with an isolated workspace per mission.

    `held` carries the workspace out so the caller can commit and clean up; the
    worker itself is not given a repository, only a directory it may write in.
    """
    held: dict = {}

    def workspace_for(mission: Mission) -> Path:
        space = GitWorkspace.create(repository, branch=f"mission/{mission.id}",
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
        return space.commit(f"{mission.title}\n\n{outcome.summary}".strip()).sha

    def accepted(mission: Mission, outcome) -> tuple[bool, str]:
        """The agent claims it is done; check that something was actually written."""
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
    return worker, held


def pass_once(timeline: Timeline, *, tenant: str, name: str, worktrees: Path,
              repository: Path, roles: Roles, claims: object,
              report_root: Path | None = None) -> int:
    """Recover, then take at most one mission. Returns how many ran."""
    freed = release_stale(timeline, tenant=tenant)
    if freed:
        log.info("released %d stale mission(s)", freed)

    waiting = queued(timeline, tenant=tenant)
    if not waiting:
        return 0

    worker, held = build_worker(name, timeline, worktrees=worktrees,
                                repository=repository, roles=roles)
    mission = waiting[0]

    # The atomic claim, before anything else touches the mission. The scheduler
    # named it dispatchable; that is advice, and two workers can be given the
    # same advice at the same instant. This is the one place that resolves it,
    # and losing the race is ordinary — not an error.
    claims.register(mission.id) if hasattr(claims, "register") else None
    if not claims.acquire(mission.id, worker=name):
        log.info("%s went to another worker", mission.id)
        return 0

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

    # A report per mission, written by the worker rather than by whichever
    # script happened to start it. Without this a mission run in production
    # completes, commits, and leaves nothing a person can read — which the
    # console then correctly reports as "no report", because there is none.
    try:
        written = reports.write(
            result.mission, root=report_root or repository,
            attempts=result.attempts, committed=result.committed,
            detail=result.detail,
            tests=result.detail or "acceptance check",
            branch=f"mission/{mission.id}",
            evidence=result.report,
            files=tuple(held[mission.id].changed()) if mission.id in held else ())
        log.info("report written to %s", written)
        # Recorded on the mission itself, so `/api/missions/{id}/report` can
        # find it. A report nothing points at is a file in a directory.
        result.mission = result.mission.model_copy(update={
            "report_path": str(written.relative_to(report_root or repository))})
        timeline.append(service._event(result.mission, actor=name,
                                       note="report written"))
    except Exception:                            # noqa: BLE001 - logged, not fatal
        log.exception("could not write a report for %s", mission.id)

    space = held.get(mission.id)
    if space is not None and result.succeeded:
        # A failed mission's worktree is kept, so somebody can look at what the
        # agent actually wrote. A successful one has been committed already.
        space.discard()
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeline", required=True,
                        help="the JSONL mission timeline shared with the API")
    parser.add_argument("--tenant", default="tenant-qevik")
    parser.add_argument("--name", default="worker-1")
    parser.add_argument("--repository", default=str(ROOT))
    parser.add_argument("--worktrees", default="",
                        help="where isolated worktrees go (default: a temp dir)")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true",
                        help="make one pass and exit, for tests and cron")
    parser.add_argument("--claims-dsn", default="",
                        help="PostgreSQL DSN for cross-process atomic claims")
    parser.add_argument("--require-atomic-claims", action="store_true",
                        help="refuse to start unless the claim database is "
                             "reachable. Use this in production: the default "
                             "logs the loss of safety, this one prevents it")
    parser.add_argument("--agent", default="llm",
                        choices=("llm", "fake", "self-check"),
                        help="'fake' runs a deterministic stub that calls no "
                             "model. Never the default: everything it produces "
                             "would claim work nothing did.")
    parser.add_argument("--reports", default="",
                        help="where mission reports are written "
                             "(default: alongside the repository)")
    parser.add_argument("--vault", default="",
                        help="credential vault root (default: the user vault)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    timeline = Timeline(args.timeline)
    worktrees = Path(args.worktrees or tempfile.mkdtemp(prefix="qevik-missions-"))
    repository = Path(args.repository)

    try:
        roles = roles_for(args.agent, tenant=args.tenant,
                          vault_root=Path(args.vault) if args.vault else None)
        claims = claims_for(args.claims_dsn,
                            insist=args.require_atomic_claims)
    except NoAgent as refusal:
        log.error("%s", refusal)
        return 2
    log.info("claiming: %s", describe_claims(claims)["status"])

    if args.once:
        pass_once(timeline, tenant=args.tenant, name=args.name,
                  worktrees=worktrees, repository=repository, roles=roles,
                  claims=claims,
                  report_root=Path(args.reports) if args.reports else None)
        return 0

    log.info("watching %s for %s", timeline.path, args.tenant)
    while True:
        try:
            pass_once(timeline, tenant=args.tenant, name=args.name,
                      worktrees=worktrees, repository=repository, roles=roles,
                      claims=claims,
                      report_root=Path(args.reports) if args.reports else None)
        except KeyboardInterrupt:
            log.info("stopping")
            return 0
        except Exception:                        # noqa: BLE001 - logged, keep going
            log.exception("pass failed; continuing")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
