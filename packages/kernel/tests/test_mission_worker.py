"""The worker, tested on the agent that lies about having finished.

§6 states it plainly: an agent saying "done" is not success. Most of what
follows is that sentence turned into assertions — a confident agent with failing
tests, a confident agent that changed nothing, a review that rejects work the
implementer was happy with. None of them may reach a commit.

The other half is recovery. A worker that dies must leave the mission
recoverable rather than looking busy forever, and the UI must be irrelevant to
all of it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlas_kernel.mission import (
    MissionStatus,
    Plan,
    PlanStep,
    attach_plan,
    claim,
    create,
    fold,
    transition,
)
from atlas_kernel.mission.agents import (
    AgentError,
    AgentTimeout,
    Behaviour,
    FakeCodingAgent,
    MalformedResult,
    Roles,
)
from atlas_kernel.mission.service import NotPermitted
from atlas_kernel.mission.worker import Acceptance, Worker, recover

A, B = "tenant-alpha", "tenant-beta"

PASSING = Acceptance(check=lambda mission, outcome: (True, ""))
FAILING = Acceptance(check=lambda mission, outcome: (False, "2 tests failed"))


def _queued(tenant=A, *, approval_required=False):
    mission, first = create(tenant=tenant, title="Build a thing",
                            requested_by="ayoub")
    mission, second = transition(mission, MissionStatus.PLANNING, tenant=tenant)
    plan = Plan(goal="a thing", approval_required=approval_required,
                steps=(PlanStep(order=1, title="x", files=("README.md",)),))
    mission, third = attach_plan(mission, plan, tenant=tenant)
    return mission, [first, second, third]


def _worker(behaviour=Behaviour.SUCCESS, acceptance=PASSING, *, name="w1",
            committer=None, max_attempts=3, agent=None):
    agent = agent or FakeCodingAgent(behaviour=behaviour)
    return Worker(name=name, roles=Roles.all(agent), acceptance=acceptance,
                  committer=committer or (lambda m, o: "abc123"),
                  max_attempts=max_attempts), agent


# ============================================ the positive complete loop

def test_the_complete_loop_reaches_commit() -> None:
    """Plan → claim → implement → test → review → commit → complete."""
    mission, events = _queued()
    worker, _agent = _worker()
    result = worker.run(mission, tenant=A)

    assert result.succeeded
    assert result.mission.status is MissionStatus.COMPLETE
    assert result.committed == "abc123"
    assert result.report
    assert result.mission.claimed_by == "", "a finished mission holds no claim"

    statuses = [e.detail["status"] for e in result.events]
    for required in ("processing", "testing", "reviewing", "committing", "complete"):
        assert required in statuses, f"{required} missing from {statuses}"


def test_the_whole_history_survives_in_events() -> None:
    mission, events = _queued()
    worker, _ = _worker()
    result = worker.run(mission, tenant=A)
    everything = events + result.events

    current = fold(everything, tenant=A)
    assert len(current) == 1
    assert current[0]["status"] == "complete"
    assert current[0]["commits"] == ["abc123"]


# ============================================ "done" is not done

def test_an_agent_with_failing_tests_never_commits() -> None:
    mission, _ = _queued()
    worker, _agent = _worker(acceptance=FAILING)
    result = worker.run(mission, tenant=A)

    assert result.mission.status is MissionStatus.FAILED
    assert result.committed == ""
    assert "did not pass" in result.detail


def test_an_agent_that_changed_nothing_is_not_believed() -> None:
    """The most dangerous mode: confident, and the repository is unchanged."""
    mission, _ = _queued()
    worker, _ = _worker(behaviour=Behaviour.PARTIAL)
    result = worker.run(mission, tenant=A)

    assert result.mission.status is MissionStatus.FAILED
    assert result.committed == ""
    assert "changed no files" in result.detail


def test_a_rejected_review_never_commits() -> None:
    mission, _ = _queued()
    worker, _ = _worker(behaviour=Behaviour.TEST_FAILURE)
    result = worker.run(mission, tenant=A)

    assert result.mission.status is MissionStatus.FAILED
    assert result.committed == ""
    assert "review rejected" in result.detail


def test_nothing_commits_without_passing_through_review() -> None:
    """A read of the worker: COMMITTING must only follow REVIEWING."""
    from pathlib import Path

    from atlas_kernel.mission import worker as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    before, _, _after = source.partition("MissionStatus.COMMITTING")
    assert "MissionStatus.REVIEWING" in before
    assert "reviewed.claims_done" in before


# ============================================ agent failure modes

def test_an_agent_error_is_retried_then_recorded() -> None:
    mission, _ = _queued()
    worker, _ = _worker(behaviour=Behaviour.FAILURE)
    result = worker.run(mission, tenant=A)

    assert result.attempts == 3, "bounded, and it actually retried"
    assert result.mission.status is MissionStatus.FAILED
    assert "AgentError" in result.detail


def test_a_timeout_is_not_confused_with_a_failure() -> None:
    agent = FakeCodingAgent(behaviour=Behaviour.TIMEOUT)
    with pytest.raises(AgentTimeout):
        agent.implement(Plan(goal="x"), workspace_root="/tmp")
    assert issubclass(AgentTimeout, AgentError)


def test_a_malformed_result_is_its_own_failure() -> None:
    """Untrusted input. A half-parsed reply must not read as partial success."""
    agent = FakeCodingAgent(behaviour=Behaviour.MALFORMED)
    with pytest.raises(MalformedResult):
        agent.plan("x")
    mission, _ = _queued()
    worker, _ = _worker(behaviour=Behaviour.MALFORMED)
    result = worker.run(mission, tenant=A)
    assert result.mission.status is MissionStatus.FAILED


def test_an_agent_that_recovers_within_the_budget_succeeds() -> None:
    """The retry must actually retry, not merely stop."""
    agent = FakeCodingAgent(behaviour=Behaviour.FAILURE, succeed_after=2)
    worker, _ = _worker(agent=agent)
    mission, _ = _queued()
    result = worker.run(mission, tenant=A)

    assert result.succeeded
    assert result.attempts > 1


def test_repair_is_bounded() -> None:
    """An agent that fixes one test by breaking another would run forever."""
    mission, _ = _queued()
    worker, _ = _worker(acceptance=FAILING, max_attempts=2)
    result = worker.run(mission, tenant=A)
    assert result.attempts == 2
    assert result.mission.status is MissionStatus.FAILED


def test_a_discovered_blocker_stops_the_mission_without_failing_it() -> None:
    mission, _ = _queued()
    worker, _ = _worker(behaviour=Behaviour.BLOCKER)
    result = worker.run(mission, tenant=A)

    assert result.mission.status is MissionStatus.BLOCKED
    assert result.blockers and result.blockers[0].kind == "PENDING_CREDENTIAL"
    assert result.blockers[0].action, "a blocker must say what to do about it"
    assert result.committed == ""


# ============================================ approval and tenancy

def test_a_mission_awaiting_approval_is_not_executed() -> None:
    mission, _ = _queued(approval_required=True)
    assert mission.status is MissionStatus.AWAITING_APPROVAL

    worker, agent = _worker()
    result = worker.run(mission, tenant=A)
    assert result.mission.status is MissionStatus.AWAITING_APPROVAL
    assert agent.calls == 0, "the agent was never invoked"
    assert "not claimable" in result.detail


def test_a_worker_cannot_run_another_tenants_mission() -> None:
    mission, _ = _queued(tenant=A)
    worker, agent = _worker()
    result = worker.run(mission, tenant=B)

    assert result.mission.status is not MissionStatus.COMPLETE
    assert agent.calls == 0


def test_two_workers_cannot_hold_one_mission() -> None:
    mission, _ = _queued()
    mission, _ = claim(mission, worker="w1", tenant=A)
    with pytest.raises(NotPermitted, match="already held"):
        claim(mission, worker="w2", tenant=A)


def test_a_mission_with_no_plan_is_not_executed() -> None:
    mission, _ = create(tenant=A, title="unplanned")
    mission, _ = transition(mission, MissionStatus.PLANNING, tenant=A)
    mission, _ = transition(mission, MissionStatus.QUEUED, tenant=A)

    worker, agent = _worker()
    result = worker.run(mission, tenant=A)
    assert result.mission.status is MissionStatus.FAILED
    assert "no plan" in result.detail
    assert agent.calls == 0


# ============================================ recovery

def test_a_dead_workers_mission_is_recovered_on_restart() -> None:
    mission, _ = _queued()
    mission, _ = claim(mission, worker="w1", tenant=A)
    abandoned = mission.model_copy(update={
        "updated_at": datetime.now(UTC) - timedelta(hours=6)})

    recovered = recover([abandoned], tenant=A)
    assert len(recovered) == 1
    returned, event = recovered[0]
    assert returned.status is MissionStatus.QUEUED
    assert returned.claimed_by == ""
    assert "stopped reporting" in event.detail["note"]


def test_a_live_workers_mission_is_not_stolen() -> None:
    mission, _ = _queued()
    mission, _ = claim(mission, worker="w1", tenant=A)
    assert recover([mission], tenant=A) == []


def test_a_failed_mission_releases_its_claim() -> None:
    """Or it sits there looking like work somebody is still doing."""
    mission, _ = _queued()
    worker, _ = _worker(acceptance=FAILING)
    result = worker.run(mission, tenant=A)
    assert result.mission.status is MissionStatus.FAILED
    assert result.mission.claimed_by == ""


def test_a_crashing_acceptance_check_still_leaves_a_known_state() -> None:
    """A worker that dies without recording anything is the one case that
    cannot be recovered from."""
    def explodes(mission, outcome):
        raise RuntimeError("the test runner itself broke")

    mission, _ = _queued()
    worker, _ = _worker(acceptance=Acceptance(check=explodes))
    result = worker.run(mission, tenant=A)

    assert result.mission.status is MissionStatus.FAILED
    assert "RuntimeError" in result.detail
    assert result.mission.claimed_by == ""


# ============================================ the UI is irrelevant

def test_the_worker_depends_on_no_ui_or_http() -> None:
    """Closing the browser cannot stop work that never referenced it."""
    from pathlib import Path

    from atlas_kernel.mission import worker as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("fastapi", "APIRouter", "Request", "httpx", "websocket"):
        assert forbidden not in source, forbidden


def test_the_worker_never_pushes() -> None:
    """Committing is permitted; pushing is not, and not by omission."""
    from pathlib import Path

    from atlas_kernel.mission import worker as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("push", "force", "reset --hard"):
        assert forbidden not in source, forbidden


def test_a_worker_without_a_committer_completes_without_committing() -> None:
    """Commit permission is injected. Absent it, work still finishes cleanly."""
    agent = FakeCodingAgent()
    worker = Worker(name="w1", roles=Roles.all(agent), acceptance=PASSING,
                    committer=None)
    mission, _ = _queued()
    result = worker.run(mission, tenant=A)
    assert result.succeeded and result.committed == ""


# ============================================ costs and secrets

def test_no_event_carries_a_secret(monkeypatch) -> None:
    monkeypatch.setenv("QEVIK_FAKE_TOKEN", "a-real-looking-secret-value")
    mission, events = _queued()
    worker, _ = _worker()
    result = worker.run(mission, tenant=A)
    blob = repr([e.detail for e in events + result.events])
    assert "a-real-looking-secret-value" not in blob


def test_an_agent_that_reports_no_cost_yields_no_total() -> None:
    mission, _ = _queued()
    worker, _ = _worker()
    result = worker.run(mission, tenant=A)
    assert result.mission.invocations, "the call was recorded"
    assert result.mission.total_cost is None, "None, never 0.0"


def test_review_can_be_independent_of_implementation() -> None:
    """A reviewer grading its own work is not a review."""
    implementer = FakeCodingAgent(name="impl")
    reviewer = FakeCodingAgent(name="rev")
    roles = Roles(planner=implementer, implementer=implementer, reviewer=reviewer)
    assert roles.review_is_independent
    assert not Roles.all(implementer).review_is_independent
