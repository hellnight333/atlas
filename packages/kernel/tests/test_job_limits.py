"""Bounds on a running plan, and the failure mode they exist to prevent.

The incident these come from was not an error. It was silence: the host accepted
TCP connections on 22 and 80 and answered neither, because the kernel holds a
listening socket whether or not any process is left to accept it. Every limit
here is designed to stop with a sentence instead.
"""

from __future__ import annotations

import pytest

from atlas_kernel.actions import ExecutionContext, PlanRunner, default_action_runner
from atlas_kernel.actions.limits import (
    CapacityUnavailable,
    Deadline,
    DeadlineExceeded,
    JobLimits,
    JobSlots,
)
from atlas_kernel.actions.planning import plan_website
from atlas_kernel.workspace import Workspace


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestAdmission:
    """Capacity is refused, not queued indefinitely. A system that looks alive
    and does nothing is the state hardest to diagnose from outside."""

    def test_it_refuses_rather_than_waiting_forever(self) -> None:
        slots = JobSlots(JobLimits(max_concurrent_jobs=1, capacity_wait_seconds=0.05))
        held = slots.acquire()
        with pytest.raises(CapacityUnavailable) as raised:
            slots.acquire()
        assert "not started" in str(raised.value)
        assert "QEVIK_MAX_JOBS" in str(raised.value)
        held.release()

    def test_a_released_slot_is_reusable(self) -> None:
        slots = JobSlots(JobLimits(max_concurrent_jobs=1, capacity_wait_seconds=0.05))
        with slots.acquire():
            assert slots.active == 1
        assert slots.active == 0
        with slots.acquire():
            assert slots.active == 1

    def test_a_slot_releases_on_every_path_out_including_an_exception(self) -> None:
        """Cancellation is the path that leaked during the incident."""
        slots = JobSlots(JobLimits(max_concurrent_jobs=1, capacity_wait_seconds=0.05))
        with pytest.raises(RuntimeError):
            with slots.acquire():
                raise RuntimeError("cancelled")
        assert slots.active == 0
        slots.acquire().release()

    def test_releasing_twice_does_not_raise_the_real_limit(self) -> None:
        """A double release on a bounded semaphore raises, and worse, would
        quietly grant more capacity than the host has."""
        slots = JobSlots(JobLimits(max_concurrent_jobs=1, capacity_wait_seconds=0.05))
        slot = slots.acquire()
        slot.release()
        slot.release()
        assert slots.active == 0

    def test_the_default_is_sized_for_the_canonical_host(self) -> None:
        assert JobLimits.for_host().max_concurrent_jobs == 2

    def test_the_limit_is_configurable_and_never_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("QEVIK_MAX_JOBS", "4")
        assert JobLimits().max_concurrent_jobs == 4
        monkeypatch.setenv("QEVIK_MAX_JOBS", "0")
        assert JobLimits().max_concurrent_jobs == 2, "zero would admit nothing, forever"
        monkeypatch.setenv("QEVIK_MAX_JOBS", "lots")
        assert JobLimits().max_concurrent_jobs == 2


class TestDeadlines:
    def test_it_reports_what_is_left(self) -> None:
        clock = Clock()
        deadline = Deadline(100.0, monotonic=clock)
        clock.advance(40)
        assert deadline.remaining == 60.0
        assert not deadline.expired

    def test_an_expired_deadline_names_the_budget_it_broke(self) -> None:
        clock = Clock()
        deadline = Deadline(10.0, monotonic=clock)
        clock.advance(11)
        assert deadline.expired
        with pytest.raises(DeadlineExceeded) as raised:
            deadline.check("the build")
        assert "the build" in str(raised.value)
        assert "10s budget" in str(raised.value)

    def test_a_step_never_gets_more_time_than_the_plan_has_left(self) -> None:
        """Otherwise the final step is granted its full timeout with seconds on
        the clock, and the plan overruns by the difference every time."""
        clock = Clock()
        deadline = Deadline(100.0, monotonic=clock)
        clock.advance(95)
        assert deadline.step_timeout(300.0) == 5.0

    def test_a_step_always_gets_a_usable_minimum(self) -> None:
        clock = Clock()
        deadline = Deadline(10.0, monotonic=clock)
        clock.advance(50)
        assert deadline.step_timeout(300.0) >= 1.0, "a zero timeout fails before it runs"

    def test_a_generous_budget_does_not_shorten_a_step(self) -> None:
        assert Deadline(10_000.0).step_timeout(30.0) == 30.0


class TestTheRunnerRespectsThem:
    def _ctx(self, tmp_path):
        return ExecutionContext(workspace=Workspace.create(tmp_path, "limited"))

    def test_a_plan_is_refused_when_the_host_is_full(self, tmp_path) -> None:
        limits = JobLimits(max_concurrent_jobs=1, capacity_wait_seconds=0.05)
        slots = JobSlots(limits)
        held = slots.acquire()

        runner = PlanRunner(default_action_runner(), limits=limits, slots=slots)
        report = runner.run(plan_website(goal="g", title="T", deploy=False), self._ctx(tmp_path))

        assert report.refused is True
        assert report.ok is False
        assert report.steps_succeeded == 0, "it must not have started"
        assert "REFUSED" in report.summary()
        held.release()

    def test_an_over_budget_plan_stops_and_says_so(self, tmp_path) -> None:
        """Distinct from a failure: nothing was wrong with the work, it simply
        ran too long, and the remedy is different."""
        limits = JobLimits(job_timeout_seconds=0.0001)
        runner = PlanRunner(default_action_runner(), limits=limits)
        report = runner.run(plan_website(goal="g", title="T", deploy=False), self._ctx(tmp_path))

        assert report.timed_out is True
        assert report.ok is False
        assert "budget" in report.error
        assert "TIMED OUT" in report.summary()

    def test_repairs_are_bounded(self, tmp_path) -> None:
        """An infinite retry loop is its own denial of service, and it buries
        the original fault under identical log lines."""

        class AlwaysRepairs:
            def repair(self, step, record, ctx):
                from atlas_kernel.agents.plan_models import PlanStep

                return [
                    PlanStep(
                        id=f"fix-{len(ctx.records)}",
                        description="try again",
                        capability="code.write",
                        action="code.write",
                        payload={"files": {"noop.txt": "x"}},
                        expected_output="a no-op fix that never helps",
                    )
                ]

        limits = JobLimits(max_repairs=2)
        runner = PlanRunner(default_action_runner(), repairer=AlwaysRepairs(), limits=limits)
        plan = plan_website(goal="g", title="T", python="definitely-not-a-binary", deploy=False)
        report = runner.run(plan, self._ctx(tmp_path))

        assert not report.ok
        assert report.repairs <= limits.max_repairs

    def test_an_ordinary_plan_still_runs(self, tmp_path) -> None:
        """The limits must not be so tight that normal work trips them."""
        import sys

        runner = PlanRunner(default_action_runner())
        report = runner.run(
            plan_website(goal="g", title="Fine", python=sys.executable, deploy=False),
            self._ctx(tmp_path),
        )
        assert report.ok, report.summary()
        assert not report.refused and not report.timed_out

    def test_runners_sharing_slots_share_the_host_limit(self, tmp_path) -> None:
        """What makes the limit apply to the machine rather than to one caller."""
        limits = JobLimits(max_concurrent_jobs=1, capacity_wait_seconds=0.05)
        slots = JobSlots(limits)
        held = slots.acquire()

        other = PlanRunner(default_action_runner(), limits=limits, slots=slots)
        assert other.run(
            plan_website(goal="g", title="T", deploy=False), self._ctx(tmp_path)
        ).refused
        held.release()
