"""The worker: claim a mission, do the work, prove it, record it, let go.

This is the process §2 requires to be independent of the browser. It takes a
queued mission, verifies it is allowed to run, gives the agent an isolated
workspace, checks the result against tests rather than against the agent's
opinion, and writes a report whether it succeeded or not.

Four properties carry the weight:

**An agent saying "done" is not done.** `AgentOutcome.claims_done` is an
assertion. The worker runs the acceptance check and treats a confident agent
with failing tests exactly as it treats a failing one — and it catches the worse
case too, an agent that reports success having changed nothing.

**Repair is bounded.** An agent that fixes a test by breaking another will do
that forever. `max_attempts` ends it, and exhausting it is a recorded failure
with the reason, not a silent give-up.

**Failure is recorded, and says what failed.** Every exit — success, test
failure, blocker, crash — leaves the mission in a defined state with a report.
A worker that dies without writing anything is the one case that cannot be
recovered from, so the release path runs in `finally`. The note carries the
cause in the failing step's own words, and — where the role has already written
results outside its workspace, which some do before anything reviews them — it
says that too. "Failed" about a run whose output is in production is a record
that is only half true.

**Nothing is committed that did not pass.** Commit is the last step and it is
reachable only from a passed review.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId
from . import service
from .agents import AgentError, AgentOutcome, MalformedResult, Roles
from .models import Blocker, Mission, MissionStatus

log = logging.getLogger(__name__)

#: How many implement→test cycles before giving up. Small on purpose: an agent
#: that has not fixed it in three tries is usually making it worse.
MAX_ATTEMPTS = 3


@dataclass
class Acceptance:
    """Whether the work is actually acceptable. Supplied by the caller.

    Injected rather than hard-coded so the worker does not know what "tests
    pass" means for a given repository — and so a test can drive the failing
    case without a repository that genuinely fails.
    """

    #: Returns (passed, detail). Never raises for an ordinary failure.
    check: Callable[[Mission, AgentOutcome], tuple[bool, str]]
    name: str = "tests"


@dataclass
class Outcome:
    """What the worker did, for the report."""

    mission: Mission
    events: list[BusinessEvent] = field(default_factory=list)
    attempts: int = 0
    committed: str = ""
    report: str = ""
    blockers: list[Blocker] = field(default_factory=list)
    detail: str = ""

    @property
    def succeeded(self) -> bool:
        return self.mission.status is MissionStatus.COMPLETE


class Worker:
    """One worker. Independent of any UI, resumable after a restart."""

    def __init__(self, *, name: str, roles: Roles, acceptance: Acceptance,
                 workspace_factory: Callable[[Mission], Path | str] | None = None,
                 committer: Callable[[Mission, AgentOutcome], str] | None = None,
                 sink: Callable[[BusinessEvent], None] | None = None,
                 max_attempts: int = MAX_ATTEMPTS) -> None:
        self.name = name
        self._roles = roles
        self._acceptance = acceptance
        #: Returns an isolated workspace root. Injected so the worker never
        #: touches the operator's working tree by default.
        self._workspace_factory = workspace_factory
        #: Returns a commit SHA, or "" when committing is not permitted here.
        self._committer = committer
        #: Called with every event as it happens, so state is durable *during*
        #: the mission rather than at the end of it. The first real run of this
        #: worker crashed after the work was done but before its caller wrote
        #: the timeline, and two missions vanished — "persisted" and "persisted
        #: if nothing goes wrong" are not the same property.
        self._sink = sink
        self._max_attempts = max(1, max_attempts)

    def _emit(self, result: Outcome, event: BusinessEvent) -> None:
        """Record an event, and persist it immediately where a sink exists.

        A sink that raises must not take the mission down with it: losing the
        log is bad, losing the work as well is worse.
        """
        result.events.append(event)
        if self._sink is None:
            return
        try:
            self._sink(event)
        except Exception:                         # noqa: BLE001 - logged, not fatal
            log.exception("worker %s could not persist an event for %s",
                          self.name, result.mission.id)

    # -- the loop ---------------------------------------------------------

    def run(self, mission: Mission, *, tenant: TenantId | None) -> Outcome:
        """Take one mission all the way, and always leave it in a known state."""
        result = Outcome(mission=mission)
        try:
            mission, event = service.claim(mission, worker=self.name, tenant=tenant)
            result.mission = mission
            self._emit(result, event)
        except service.NotPermitted as refusal:
            # Not ours to run. Nothing has changed, so nothing to release.
            result.detail = str(refusal)
            return result

        try:
            return self._execute(result, tenant=tenant)
        except Exception as failure:              # noqa: BLE001 - recorded, not swallowed
            log.exception("worker %s crashed on %s", self.name, mission.id)
            result.detail = f"{type(failure).__name__}: {failure}"[:300]
            result.mission, event = self._fail(result.mission, tenant=tenant,
                                               note=result.detail)
            self._emit(result, event)
            return result

    def _execute(self, result: Outcome, *, tenant: TenantId | None) -> Outcome:
        mission = result.mission
        plan = mission.plan
        if plan is None:
            result.detail = "no plan; a mission is not executable until planned"
            result.mission, event = self._fail(mission, tenant=tenant,
                                               note=result.detail)
            self._emit(result, event)
            return result

        # A path, and checked to be one. The first real mission run against this
        # returned a workspace *object* here, whose str() is a dataclass repr —
        # the agent then wrote its files under a directory named
        # "GitWorkspace(repository=...", the acceptance check found nothing, and
        # the mission failed three times with a message about a missing module.
        # The contract was loose enough to make that a plausible call, so it is
        # now checked at the boundary where the mistake is legible.
        workspace_root = ""
        if self._workspace_factory is not None:
            supplied = self._workspace_factory(mission)
            if not isinstance(supplied, (str, Path)):
                raise TypeError(
                    "workspace_factory must return a path to the workspace, not "
                    f"{type(supplied).__name__}. The agent writes files relative "
                    "to this value.")
            workspace_root = str(supplied)

        outcome: AgentOutcome | None = None
        passed, detail = False, ""
        while result.attempts < self._max_attempts and not passed:
            result.attempts += 1
            try:
                outcome = self._roles.implementer.implement(
                    plan, workspace_root=str(workspace_root))
            except (AgentError, MalformedResult) as failure:
                # A failed call is data. Retry within the budget rather than
                # ending the mission on one bad response.
                detail = f"{type(failure).__name__}: {failure}"[:200]
                log.info("worker %s attempt %d failed: %s", self.name,
                         result.attempts, detail)
                continue

            if outcome.invocation is not None:
                mission, event = service.record_invocation(
                    mission, outcome.invocation, tenant=tenant)
                result.mission = mission
                self._emit(result, event)

            if outcome.blockers:
                result.blockers = list(outcome.blockers)
                result.mission, event = service.transition(
                    mission, MissionStatus.BLOCKED, tenant=tenant, actor=self.name,
                    blockers=tuple(outcome.blockers),
                    note="the agent found a blocker")
                self._emit(result, event)
                return result

            # An agent that reports success having produced nothing is the
            # most dangerous mode, because it is confident and there is no
            # artefact to check. Caught here rather than by the tests, which
            # would pass.
            #
            # **Produced**, not "changed files". A research role writes no files
            # by design — an unchanged repository is its correct outcome — and
            # judging it on files failed every successful run of it. The
            # currency is declared by the outcome, so a coding agent is held to
            # exactly the same standard as before.
            if outcome.claims_done and outcome.produced_nothing:
                detail = ("the agent reported success and produced nothing: no "
                          "files changed and no evidence recorded")
                log.info("worker %s attempt %d: %s", self.name, result.attempts,
                         detail)
                continue

            mission, event = service.transition(
                mission, MissionStatus.TESTING, tenant=tenant, actor=self.name)
            result.mission = mission
            self._emit(result, event)

            passed, detail = self._acceptance.check(mission, outcome)
            if not passed:
                log.info("worker %s attempt %d: %s failed — %s", self.name,
                         result.attempts, self._acceptance.name, detail)
                # Back to work, within the budget.
                mission, event = service.transition(
                    mission, MissionStatus.PROCESSING, tenant=tenant,
                    actor=self.name, note=f"{self._acceptance.name} failed")
                result.mission = mission
                self._emit(result, event)

        if not passed or outcome is None:
            note = self._and_what_is_live(
                f"{self._acceptance.name} did not pass after "
                f"{result.attempts} attempt(s): {detail}", outcome)
            result.detail = note
            result.report = outcome.notes if outcome is not None else ""
            result.mission, event = self._fail(result.mission, tenant=tenant,
                                               note=note)
            self._emit(result, event)
            return result

        # -- review -------------------------------------------------------
        mission, event = service.transition(result.mission, MissionStatus.REVIEWING,
                                            tenant=tenant, actor=self.name)
        result.mission = mission
        self._emit(result, event)

        reviewer = self._roles.reviewer or self._roles.implementer
        reviewed = reviewer.review(plan, outcome)
        if not reviewed.claims_done:
            note = self._and_what_is_live(
                f"review rejected the change: {reviewed.summary}", reviewed)
            result.detail = note
            # The step-by-step account the agent already produced, so a failed
            # mission's report has an evidence section too. Without it the only
            # record of what went wrong is this one line, and the report — the
            # thing an operator opens — says nothing about what ran.
            result.report = reviewed.notes
            result.mission, event = self._fail(result.mission, tenant=tenant,
                                               note=note)
            self._emit(result, event)
            return result

        # -- commit, only from here ---------------------------------------
        mission, event = service.transition(result.mission, MissionStatus.COMMITTING,
                                            tenant=tenant, actor=self.name)
        result.mission = mission
        self._emit(result, event)

        if self._committer is not None:
            result.committed = self._committer(mission, outcome) or ""

        result.report = self._roles.implementer.summarize(plan, reviewed)
        mission, event = service.transition(
            result.mission, MissionStatus.COMPLETE, tenant=tenant, actor=self.name,
            claimed_by="", commits=tuple(filter(None, (result.committed,))),
            note="complete")
        result.mission = mission
        self._emit(result, event)
        return result

    def _and_what_is_live(self, note: str,
                          outcome: AgentOutcome | None) -> str:
        """The failure, and whether the run's output is already in production.

        A role may persist real results *before* the run is reviewed.
        `toolrunner.ToolAgent` does, deliberately: the responses it recorded
        are real, and losing them because a database was briefly away is the
        worse outcome. The consequence is that a mission recorded as `failed`
        can be one whose findings, signals and observations are live — and
        until this was here, nothing anywhere said both things at once.

        Adds nothing when the outcome reports nothing live, which is the
        ordinary case for a coding role: its work sits in a workspace a failed
        mission never commits.
        """
        live = (outcome.live_outputs if outcome is not None else "").strip()
        if not live:
            return note
        return (f"{note} — and this run's output is already live: {live}. It "
                "was written before the review, and the failure does not "
                "withdraw it.")

    def _fail(self, mission: Mission, *, tenant: TenantId | None,
              note: str) -> tuple[Mission, BusinessEvent]:
        """Record a failure and let the mission go.

        Releases the claim, so a failed mission is not left looking like one a
        worker is still working on.
        """
        return service.transition(mission, MissionStatus.FAILED, tenant=tenant,
                                  actor=self.name, claimed_by="", note=note)


def recover(missions: list[Mission], *, tenant: TenantId | None,
            now: datetime | None = None) -> list[tuple[Mission, BusinessEvent]]:
    """Return every mission whose worker stopped reporting.

    Called on start-up. A worker that died mid-mission left it PROCESSING with
    a claim; without this it would sit there forever looking busy.
    """
    at = now or datetime.now(UTC)
    return [service.release(mission, tenant=tenant,
                            reason="worker stopped reporting")
            for mission in service.stale(missions, now=at)]
