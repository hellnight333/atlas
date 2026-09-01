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
    AgentOutcome,
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
    """A mission a worker may take, reached the way a real one is.

    This used to rely on `attach_plan` honouring `approval_required=False` and
    queueing the plan directly — which was the defect: the planner decided its
    own authorisation. Policy decides now, and this plan is unpriced, names no
    agent and writes outside the reviewed-free paths, so policy holds it.

    So the fixture approves it, which is what actually happens. A fixture that
    routed around approval would be testing a path production does not have.
    """
    mission, first = create(tenant=tenant, title="Build a thing",
                            requested_by="ayoub")
    mission, second = transition(mission, MissionStatus.PLANNING, tenant=tenant)
    plan = Plan(goal="a thing", approval_required=approval_required,
                steps=(PlanStep(order=1, title="x", files=("README.md",)),))
    mission, third = attach_plan(mission, plan, tenant=tenant)
    events = [first, second, third]
    if not approval_required and mission.status is MissionStatus.AWAITING_APPROVAL:
        mission, fourth = transition(mission, MissionStatus.QUEUED, tenant=tenant,
                                     actor="ayoub", note="approved by a person")
        events.append(fourth)
    return mission, events


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


def test_an_agent_that_produced_nothing_is_not_believed() -> None:
    """The most dangerous mode: confident, and there is nothing to check.

    A coding agent's currency is files, and this one changed none. The guard
    was later generalised so a research role — whose successful run leaves the
    repository untouched by design — is judged on evidence instead; a coding
    agent is held to exactly the same standard it always was, which is what
    this asserts.
    """
    mission, _ = _queued()
    worker, _ = _worker(behaviour=Behaviour.PARTIAL)
    result = worker.run(mission, tenant=A)

    assert result.mission.status is MissionStatus.FAILED
    assert result.committed == ""
    assert "produced nothing" in result.detail


def test_the_guard_asks_the_outcome_what_its_currency_is() -> None:
    """Files for a coding role, evidence for a research one. The property the
    guard now tests, rather than the sentence it prints."""
    from atlas_kernel.mission.agents import AgentOutcome

    assert AgentOutcome(claims_done=True).produced_nothing
    assert not AgentOutcome(claims_done=True, files=("a.py",)).produced_nothing
    assert not AgentOutcome(claims_done=True, evidence_count=1).produced_nothing


def test_a_rejected_review_never_commits() -> None:
    mission, _ = _queued()
    worker, _ = _worker(behaviour=Behaviour.TEST_FAILURE)
    result = worker.run(mission, tenant=A)

    assert result.mission.status is MissionStatus.FAILED
    assert result.committed == ""
    assert "review rejected" in result.detail


# ================================ a failed mission that left live output


class _PublishesBeforeReview(FakeCodingAgent):
    """A role whose work is in production before the review sees it.

    `toolrunner.ToolAgent`'s shape, and not a hypothetical one: it persists
    findings, signals and observations inside `implement` so that a database
    briefly away does not lose evidence that was genuinely gathered. Three
    production missions in three days were then recorded as `failed` while
    their results were live.
    """

    def implement(self, plan, *, workspace_root: str, context: str = ""):
        return AgentOutcome(
            summary="40 piece(s) of evidence from 2 step(s)",
            claims_done=True, evidence_count=40,
            live_outputs="10 finding(s), 7 observation record(s)",
            notes="ok  audit  website\nFAILED  http-fetch\n    address refused")

    def review(self, plan, outcome, *, diff: str = ""):
        return outcome.model_copy(update={
            "claims_done": False,
            "summary": "the http-fetch step failed: address refused: "
                       "169.254.169.254 is not a public address"})


def test_a_failed_mission_states_the_cause_and_that_its_output_is_live() -> None:
    """Both facts, in the one record an operator reads. Neither was there: the
    note restated what the run produced, and nothing anywhere said that a
    failed mission's results were already in production."""
    mission, _ = _queued()
    worker, _ = _worker(agent=_PublishesBeforeReview())
    result = worker.run(mission, tenant=A)

    assert result.mission.status is MissionStatus.FAILED
    assert result.committed == ""
    assert "address refused" in result.detail, "the record does not say why"
    assert "10 finding(s), 7 observation record(s)" in result.detail
    assert "already live" in result.detail

    # And the same sentence survives into the folded mission, which is what
    # the console and the report read.
    assert fold(result.events, tenant=A)[0]["because"] == result.detail


def test_a_failed_mission_keeps_the_agents_own_account_of_the_run() -> None:
    """The report is written from this. A failed mission used to reach it with
    nothing, so the only record of what ran was the one-line note."""
    mission, _ = _queued()
    worker, _ = _worker(agent=_PublishesBeforeReview())
    result = worker.run(mission, tenant=A)

    assert "FAILED  http-fetch" in result.report


def test_a_failure_that_left_nothing_behind_claims_nothing_is_live() -> None:
    """The clause must be absent when it would be false — a coding role's work
    sits in a workspace a failed mission never commits."""
    mission, _ = _queued()
    worker, _ = _worker(behaviour=Behaviour.TEST_FAILURE)
    result = worker.run(mission, tenant=A)

    assert "live" not in result.detail


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


def _worker_module():
    """`infra/` is not a package on the path; the drafts tests reach it the
    same way."""
    import sys
    from pathlib import Path as _Path

    root = str(_Path(__file__).resolve().parents[3] / "infra")
    if root not in sys.path:
        sys.path.insert(0, root)
    import mission_worker

    return mission_worker


class TestWhatThisMachineHas:
    """The HP Z8 is a multi-GPU box. Reading one line of nvidia-smi described it
    as a single-card machine — wrong in the way that looks right, because the
    field is populated."""

    def _smi(self, monkeypatch, output, present=True):
        import subprocess as sp

        w = _worker_module()

        monkeypatch.setattr(w.shutil if hasattr(w, "shutil") else __import__("shutil"),
                            "which", lambda _: "/usr/bin/nvidia-smi" if present else None)
        monkeypatch.setattr(
            sp, "run",
            lambda *a, **k: sp.CompletedProcess(a, 0, stdout=output, stderr=""))

    def test_it_reports_every_card_not_the_first(self, monkeypatch) -> None:
        w = _worker_module()

        self._smi(monkeypatch,
                  "NVIDIA RTX A6000, 49140\nNVIDIA RTX A6000, 49140\n"
                  "NVIDIA RTX A4000, 16376\n")

        assert w.gpu_inventory() == [
            ("NVIDIA RTX A6000", 47), ("NVIDIA RTX A6000", 47),
            ("NVIDIA RTX A4000", 15)]

    def test_a_pinned_process_advertises_its_own_card(self, monkeypatch) -> None:
        """One worker per GPU is the topology, and CUDA_VISIBLE_DEVICES is what
        assigns them. A process pinned to card 2 that advertised card 0 would be
        matched against a device it cannot touch."""
        w = _worker_module()

        cards = [("A6000", 47), ("A6000", 47), ("A4000", 15)]
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2")

        assert w._my_gpu(cards) == ("A4000", 15)

    def test_it_never_sums_across_the_cards(self, monkeypatch) -> None:
        """Adding four cards' VRAM together claims a memory figure no single
        workload can use."""
        w = _worker_module()

        cards = [("A6000", 47)] * 4
        monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

        assert w._my_gpu(cards) == ("A6000", 47)

    def test_a_pin_this_cannot_resolve_reports_no_card(self, monkeypatch) -> None:
        """A UUID pin is valid and an index-based inventory cannot resolve it.
        Reporting the first card would be a guess."""
        w = _worker_module()

        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-4f2e1c9a")

        assert w._my_gpu([("A6000", 47), ("A4000", 15)]) is None

    def test_an_out_of_range_pin_reports_no_card(self, monkeypatch) -> None:
        w = _worker_module()

        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "7")

        assert w._my_gpu([("A6000", 47)]) is None

    def test_no_nvidia_smi_is_no_card_not_a_zero(self, monkeypatch) -> None:
        w = _worker_module()

        self._smi(monkeypatch, "", present=False)

        assert w.gpu_inventory() == []
        assert w._my_gpu([]) is None

    def test_a_card_whose_memory_will_not_parse_is_still_a_card(
            self, monkeypatch) -> None:
        """Dropping it would report a 2-GPU box as a 1-GPU box."""
        w = _worker_module()

        self._smi(monkeypatch, "NVIDIA RTX A6000, 49140\nWeird Card, [N/A]\n")

        assert w.gpu_inventory() == [("NVIDIA RTX A6000", 47), ("Weird Card", 0)]


class TestEveryRecipeDrivenRoleCanStart:
    """A role registered in three places and forgotten in a fourth started, went
    looking for a model, found none and exited 2 — on the host, after a deploy
    that had reported success."""

    def _worker(self):
        import sys
        from pathlib import Path as _Path

        root = str(_Path(__file__).resolve().parents[3] / "infra")
        if root not in sys.path:
            sys.path.insert(0, root)
        import mission_worker

        return mission_worker

    def test_the_recipe_driven_roles_are_never_listed_as_a_literal(self) -> None:
        """There were **two** copies of that set in this file — one deciding
        whether the role needs a model, one deciding whether the agent is
        rebuilt from the mission. Adding a role to the first left the second
        behind, and the worker then claimed a delivery and refused it for
        naming no approved opportunity that the mission plainly named.

        An earlier version of this test looked for the derived form *somewhere*
        in the module and passed while the second literal was still there. This
        asserts the absence of the literal instead."""
        import ast
        import inspect

        worker = self._worker()
        tree = ast.parse(inspect.getsource(worker))

        roles = set(worker.PLACEHOLDERS)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Set):
                continue
            members = {e.value for e in node.elts
                       if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            assert not (members & roles) or members == {"fake"}, (
                f"a literal role set {sorted(members)} duplicates PLACEHOLDERS; "
                "that duplication has already shipped twice")

    def test_every_registered_role_resolves_to_an_agent(self) -> None:
        worker = self._worker()

        for choice in worker.AGENT_CHOICES:
            if choice == "fake":
                continue
            assert worker._serves(choice), choice

    def test_every_placeholder_names_a_real_recipe(self) -> None:
        """A placeholder naming an unknown recipe fails at construction, which
        is start-up, which is after the deploy."""
        from atlas_kernel.fabric import recipes

        worker = self._worker()

        for role, recipe_id in worker.PLACEHOLDERS.items():
            assert recipes.get(recipe_id) is not None, f"{role}: {recipe_id}"

    def test_a_placeholder_recipe_is_runnable_by_the_role_that_serves_it(
            self) -> None:
        """The recipe's agent and the worker's agent must be the same, or the
        worker claims missions it will then refuse."""
        from atlas_kernel.fabric import recipes

        worker = self._worker()

        for role, recipe_id in worker.PLACEHOLDERS.items():
            assert recipes.get(recipe_id).agent_id == worker._serves(role), role
