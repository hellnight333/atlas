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
from atlas_kernel.mission import service  # noqa: E402
from atlas_kernel.mission.agents import (  # noqa: E402
    Behaviour,
    CodingAgent,
    FakeCodingAgent,
    LLMCodingAgent,
    Roles,
)
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


def queued(timeline: Timeline, *, tenant: str) -> list[Mission]:
    """Missions waiting to be picked up, oldest first.

    Oldest first deliberately: newest-first starves the mission that has been
    waiting longest every time a new one arrives.
    """
    folded = service.fold(timeline.read(), tenant=tenant)
    waiting = [m for m in folded
               if m.get("status") == MissionStatus.QUEUED.value
               and not m.get("claimed_by")]
    waiting.sort(key=lambda m: m.get("updated_at", ""))
    return [service.rehydrate(m, tenant=tenant) for m in waiting]


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
              repository: Path, roles: Roles) -> int:
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
    log.info("claiming %s — %s", mission.id, mission.title)
    result = worker.run(mission, tenant=tenant)
    log.info("%s finished as %s (attempts %d, commit %s)", mission.id,
             result.mission.status.value, result.attempts,
             result.committed or "none")

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
    parser.add_argument("--agent", default="llm", choices=("llm", "fake"),
                        help="'fake' runs a deterministic stub that calls no "
                             "model. Never the default: everything it produces "
                             "would claim work nothing did.")
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
    except NoAgent as refusal:
        log.error("%s", refusal)
        return 2

    if args.once:
        pass_once(timeline, tenant=args.tenant, name=args.name,
                  worktrees=worktrees, repository=repository, roles=roles)
        return 0

    log.info("watching %s for %s", timeline.path, args.tenant)
    while True:
        try:
            pass_once(timeline, tenant=args.tenant, name=args.name,
                      worktrees=worktrees, repository=repository, roles=roles)
        except KeyboardInterrupt:
            log.info("stopping")
            return 0
        except Exception:                        # noqa: BLE001 - logged, keep going
            log.exception("pass failed; continuing")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
