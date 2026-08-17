"""Bounds on what a running plan may consume.

The cgroup in `infra/systemd/qevik-jobs.slice` is the real protection — the
kernel is the only thing that can say no on behalf of the whole machine. These
limits sit above it and exist for a different reason: to fail *legibly*.

A cgroup kills. That is correct and it is also an OOM line in `dmesg` and a step
that simply vanished. The limits here stop the same runaway earlier and leave a
sentence explaining what happened, which is the difference between an incident
that takes twenty minutes to diagnose and one that takes twenty seconds.

Three rules, each from something that actually went wrong:

**Nothing waits forever.** Every wait has a deadline and a message naming the
limit it hit. During the outage the failure mode was not an error, it was
silence — the box accepted connections and answered nothing.

**Capacity is refused, not queued indefinitely.** A plan that arrives when the
host is already loaded is rejected with a reason. Queueing it would produce a
system that looks alive and does nothing, which is the state that is hardest to
diagnose from outside.

**Retries are bounded and never tight.** An infinite retry loop is its own
denial of service, and it buries the original fault under identical log lines.
"""

from __future__ import annotations

import os
import threading
import time

from pydantic import BaseModel, ConfigDict, Field


class CapacityUnavailable(RuntimeError):
    """The system declined to start this work.

    Not a failure of the work — the work never ran. Distinct so a caller can
    retry later rather than treating it as a broken plan.
    """


class DeadlineExceeded(RuntimeError):
    """A plan or step ran past the time it was allowed."""


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return value if value > 0 else default


class JobLimits(BaseModel):
    """What a single plan may take, and how many may run at once.

    Defaults are sized for the canonical host: 4 vCPU, 8 GB shared with
    PostgreSQL, the API and Caddy. They are deliberately conservative — the cost
    of a limit being slightly too low is a legible refusal, and the cost of it
    being too high was a machine that had to be power-cycled.
    """

    model_config = ConfigDict(frozen=True)

    #: Concurrent plans. Two browser-using plans already approach what the
    #: browser cap allows, so more would only queue inside the semaphore below.
    max_concurrent_jobs: int = Field(default_factory=lambda: _env_int("QEVIK_MAX_JOBS", 2))
    #: Wall-clock for a whole plan. Long enough for a build with tests, short
    #: enough that a wedged plan is noticed within a coffee break.
    job_timeout_seconds: float = 900.0
    #: Wall-clock for one action.
    step_timeout_seconds: float = 300.0
    #: How long to wait for a free slot before refusing. Refusing beats queueing:
    #: a caller that gets an answer can decide, and one that blocks cannot.
    capacity_wait_seconds: float = 30.0
    #: Repairs per plan. Bounded, and never tight — see the module docstring.
    max_repairs: int = 3

    @classmethod
    def for_host(cls) -> JobLimits:
        return cls()


class JobSlots:
    """Admission control for whole plans.

    Bounded and timed. `acquire` returns a context manager so a slot is released
    on every path out — including cancellation, which is the path that leaked
    during the incident.
    """

    def __init__(self, limits: JobLimits | None = None) -> None:
        self.limits = limits or JobLimits.for_host()
        self._semaphore = threading.BoundedSemaphore(self.limits.max_concurrent_jobs)
        self._active = 0
        self._lock = threading.Lock()

    @property
    def active(self) -> int:
        return self._active

    def acquire(self):
        """Take a slot, or refuse with a reason."""
        limits = self.limits
        if not self._semaphore.acquire(timeout=limits.capacity_wait_seconds):
            raise CapacityUnavailable(
                f"no job slot free after {limits.capacity_wait_seconds:g}s "
                f"({limits.max_concurrent_jobs} running; set QEVIK_MAX_JOBS to change). "
                "The work was not started."
            )
        with self._lock:
            self._active += 1
        return _Slot(self)

    def _release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
        try:
            self._semaphore.release()
        except ValueError:  # pragma: no cover - guarded by _Slot being one-shot
            pass


class _Slot:
    """Held for the duration of a plan. Releases exactly once, on any exit."""

    def __init__(self, slots: JobSlots) -> None:
        self._slots = slots
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._slots._release()

    def __enter__(self) -> _Slot:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class Deadline:
    """A wall-clock budget for a plan, checked between steps.

    Checked *between* steps rather than enforced mid-step on purpose: killing an
    action halfway leaves a half-written workspace and a half-finished
    deployment, which is worse than a slightly late refusal. Individual actions
    carry their own timeouts — subprocess, browser, HTTP — so nothing inside a
    step can run unbounded either.
    """

    def __init__(self, seconds: float, *, monotonic=time.monotonic) -> None:
        self._monotonic = monotonic
        self.seconds = seconds
        self.started_at = monotonic()

    @property
    def elapsed(self) -> float:
        return self._monotonic() - self.started_at

    @property
    def remaining(self) -> float:
        return max(0.0, self.seconds - self.elapsed)

    @property
    def expired(self) -> bool:
        return self.remaining <= 0

    def check(self, what: str = "the plan") -> None:
        if self.expired:
            raise DeadlineExceeded(
                f"{what} ran past its {self.seconds:g}s budget "
                f"({self.elapsed:.1f}s elapsed). Stopped rather than left running."
            )

    def step_timeout(self, ceiling: float) -> float:
        """The shorter of what a step may take and what the plan has left.

        Without this a final step could be granted its full timeout with seconds
        left on the plan's budget, and the plan would overrun by the difference
        every time.
        """
        return max(1.0, min(ceiling, self.remaining))
