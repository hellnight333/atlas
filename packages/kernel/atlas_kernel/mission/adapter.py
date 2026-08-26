"""The join between an agent *record* and a process that does something.

The registry says an agent exists and what it may reach. The tool table says
what those tools can do and whether a container helps. The sandbox can contain a
process. Nothing connected the three, so `Agent.tools` was a list nobody
consulted and the sandbox was a capability nothing used.

This is that connection, and it is deliberately thin: it resolves the record,
derives the isolation from the tools rather than being told, runs the commands,
and returns evidence. It decides nothing about *whether* — policy did that
before the mission was queued.

## Isolation is derived, never passed in

    needs_network(agent)  ->  Isolation(network=…)
    agent.needs_sandbox   ->  Bubblewrap, or a refusal

A caller that could hand in its own `Isolation` could hand in one with the
network on and the workspace set to `/`. The adapter reads the agent's own
declaration, so the confinement matches what the registry promised.

## An unrunnable agent refuses here, not at the provider

`agent.blocked_by` is checked before anything starts. Discovering a missing
credential halfway through a mission means the money is spent and the customer
was already told the work was happening.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..fabric.agents import Agent, Registry
from ..fabric.sandbox import (
    Confinement,
    Isolation,
    NoSandbox,
    NotIsolated,
)
from ..fabric.sandbox import (
    Outcome as SandboxOutcome,
)
from ..fabric.sandbox import available as sandbox_available
from ..fabric.tools import for_agent, needs_network
from .agents import AgentOutcome, Plan
from .models import Blocker

log = logging.getLogger(__name__)

#: How long one step of deterministic work may take. Short: these are checks,
#: not builds, and a check that runs for ten minutes is a hung check.
STEP_SECONDS = 180


class NotRunnable(RuntimeError):
    """The registry lists this agent and this host cannot run it."""


@dataclass
class Step:
    """One tool invocation, and what it is meant to establish.

    `proves` is not decoration. A step whose output nobody can interpret is a
    step that produces noise in the evidence, and evidence nobody reads is the
    same as none.

    `tool` names an entry in `fabric.tools`, and the adapter refuses a step
    whose tool the agent does not declare. Before this, the tool contract was
    consulted only in aggregate — to decide whether the agent needed the
    network or a sandbox — and never per step. An agent declared with
    `tools=("filesystem",)` could therefore run any command at all, including
    one that reaches the network, and the isolation derived from its
    *declaration* would be wrong about the work it was actually doing.

    That is the same shape as an agent substitution: the blast radius somebody
    approved and the one that runs diverge, quietly.

    Defaults to `shell`, which every step here has always been in practice.
    """

    command: list[str]
    proves: str
    tool: str = "shell"


@dataclass
class Evidence:
    """What actually happened, per step, kept whether it passed or not.

    A failed step's output is the part somebody needs. Discarding it and keeping
    only "failed" is how a report becomes unactionable.
    """

    step: str
    proves: str
    exit_code: int | None
    passed: bool
    output: str
    confinement: str
    timed_out: bool = False

    def summary(self) -> dict:
        return {"step": self.step, "proves": self.proves,
                "exit_code": self.exit_code, "passed": self.passed,
                "timed_out": self.timed_out, "confinement": self.confinement,
                # Truncated in the record, not in the log. A report is read by a
                # person; a megabyte of stdout in it helps nobody.
                "output": self.output[-2000:]}


@dataclass
class Adapter:
    """Runs an agent's work through its declared tools and isolation."""

    agent: Agent
    sandbox: object = field(default_factory=sandbox_available)

    @classmethod
    def for_id(cls, agent_id: str, *, registry: Registry | None = None,
               sandbox: object | None = None) -> Adapter:
        found = (registry or Registry()).get(agent_id)
        return cls(agent=found, sandbox=sandbox or sandbox_available())

    # -- what this host can actually do with it ---------------------------

    def refusal(self) -> str:
        """Why this agent cannot run here, or "" if it can.

        Returned rather than raised so a caller can *report* the gap. Running is
        what refuses.
        """
        if self.agent.blocked_by:
            return (f"{self.agent.id} is not runnable: "
                    f"{self.agent.why_not_ready}")
        if self.agent.needs_sandbox:
            confinement = getattr(self.sandbox, "confinement", Confinement.NONE)
            if confinement is not Confinement.FULL:
                return (f"{self.agent.id} writes files with its own tool loop "
                        "and this host cannot contain it. Running it here would "
                        "put an unconfined process on the machine.")
        return ""

    def isolation_for(self, workspace: Path, *, seconds: int = STEP_SECONDS
                      ) -> Isolation:
        """Derived from the agent's tools, never supplied.

        A caller that could pass its own could pass one with the network on and
        the workspace set to `/`.
        """
        return Isolation(workspace=workspace,
                         network=needs_network(self.agent), seconds=seconds)

    def describe(self) -> dict:
        """What this adapter would do, for a report or a health check."""
        return {
            "agent": self.agent.id,
            "backend": self.agent.backend.value,
            "blast": self.agent.blast.value,
            "approval": self.agent.approval,
            "tools": [t.id for t in for_agent(self.agent)],
            "needs_network": needs_network(self.agent),
            "needs_sandbox": self.agent.needs_sandbox,
            "confinement": getattr(self.sandbox, "confinement",
                                   Confinement.NONE).value,
            "runnable": self.refusal() == "",
            "why_not": self.refusal(),
        }

    # -- running ----------------------------------------------------------

    def run(self, steps: list[Step], *, workspace: Path) -> list[Evidence]:
        """Every step, in order, stopping at the first failure.

        Stopping matters: a later step run against the state a failed step left
        behind produces evidence about a situation that was never meant to
        exist.
        """
        refused = self.refusal()
        if refused:
            raise NotRunnable(refused)

        # Every step, before the first one runs. A sequence half-executed and
        # then refused has already changed the workspace, and the refusal
        # arrives too late to mean anything.
        undeclared = self.undeclared_tools(steps)
        if undeclared:
            declared = ", ".join(sorted(t.id for t in
                                        for_agent(self.agent))) or "no tools"
            raise NotRunnable(
                f"{self.agent.id} declares {declared} and these steps use "
                f"{', '.join(undeclared)}. An agent may only use what its "
                "registry entry says it uses — the isolation it runs under is "
                "derived from that declaration, so a step outside it runs with "
                "the wrong containment.")

        isolation = self.isolation_for(workspace)
        collected: list[Evidence] = []
        for step in steps:
            outcome = self._run_one(step, isolation)
            passed = outcome.exit_code == 0 and not outcome.timed_out
            collected.append(Evidence(
                step=" ".join(step.command), proves=step.proves,
                exit_code=outcome.exit_code, passed=passed,
                output=(outcome.stdout + outcome.stderr).strip(),
                confinement=outcome.confinement.value,
                timed_out=outcome.timed_out))
            if not passed:
                break
        return collected

    def undeclared_tools(self, steps: list[Step]) -> tuple[str, ...]:
        """Tools these steps use that the agent does not declare.

        A tool nobody has ever declared is reported too, rather than skipped:
        a typo in a step is not permission.
        """
        declared = {tool.id for tool in for_agent(self.agent)}
        wanted = {step.tool for step in steps}
        return tuple(sorted(wanted - declared))

    def _run_one(self, step: Step, isolation: Isolation) -> SandboxOutcome:
        """Inside the sandbox when the agent needs one, refusing when it cannot.

        An agent that does *not* need a sandbox — a deterministic executor — is
        still run inside one where the host has it, because containment costs
        nothing here and an executor with a bug is still a process.
        """
        confinement = getattr(self.sandbox, "confinement", Confinement.NONE)
        if confinement is Confinement.FULL:
            return self.sandbox.run(step.command, isolation)  # type: ignore[attr-defined]
        if self.agent.needs_sandbox:
            raise NotRunnable(
                f"{self.agent.id} needs a container and this host has none")
        # No sandbox, and this agent does not require one. Say so in the
        # evidence rather than letting a reader assume it was contained.
        return self._unconfined(step, isolation)

    def _unconfined(self, step: Step, isolation: Isolation) -> SandboxOutcome:
        import subprocess

        binary = shutil.which(step.command[0])
        if binary is None:
            return SandboxOutcome(ran=False, exit_code=127, stdout="",
                                  stderr=f"{step.command[0]} is not installed",
                                  confinement=Confinement.NONE,
                                  detail="the command does not exist here")
        try:
            done = subprocess.run(  # noqa: S603 - argv list, never a shell
                [binary, *step.command[1:]], cwd=isolation.workspace,
                capture_output=True, text=True, timeout=isolation.seconds,
                env=isolation.env(), check=False)
        except subprocess.TimeoutExpired:
            return SandboxOutcome(ran=True, exit_code=None, stdout="", stderr="",
                                  timed_out=True, confinement=Confinement.NONE,
                                  detail=f"killed after {isolation.seconds}s")
        return SandboxOutcome(ran=True, exit_code=done.returncode,
                              stdout=done.stdout, stderr=done.stderr,
                              confinement=Confinement.NONE,
                              detail="not contained: this host has no sandbox")


class DeterministicAgent:
    """A `CodingAgent` backed by commands rather than by a model.

    Satisfies the same protocol the worker already drives, so nothing in the
    worker learns a second way to run work. What it does *not* do is invent
    anything: every step is declared up front, and the outcome is whether those
    steps passed.

    It exists because proving the whole path end to end should not require
    spending money or trusting a model to behave. A mission run through this
    exercises registry → adapter → tool contract → sandbox → evidence exactly as
    a model-backed one would; only the source of the work differs.
    """

    def __init__(self, *, adapter: Adapter, steps: list[Step],
                 name: str = "") -> None:
        self._adapter = adapter
        self._steps = steps
        self._name = name or f"deterministic:{adapter.agent.id}"
        #: Kept so the worker's report can carry what was actually observed.
        self.evidence: list[Evidence] = []

    @property
    def name(self) -> str:
        return self._name

    def plan(self, request: str, *, context: str = "") -> Plan:
        from .models import PlanStep

        return Plan(
            goal=request,
            why="Declared steps, run through the agent's own tools and "
                "isolation. Nothing here is proposed by a model.",
            steps=tuple(PlanStep(order=i, title=step.proves,
                                 why=" ".join(step.command))
                        for i, step in enumerate(self._steps, start=1)),
            approval_required=True, estimated_cost=0.0, cost_status="REPORTED")

    def implement(self, plan: Plan, *, workspace_root: str,
                  context: str = "") -> AgentOutcome:
        try:
            self.evidence = self._adapter.run(self._steps,
                                              workspace=Path(workspace_root))
        except NotRunnable as refused:
            return AgentOutcome(
                summary=str(refused), claims_done=False,
                blockers=(Blocker(kind="PENDING_INFRASTRUCTURE",
                                  detail=str(refused),
                                  action="Run this on a host that can contain "
                                         "it, or attach one."),))
        passed = bool(self.evidence) and all(e.passed for e in self.evidence)
        written = self._written(Path(workspace_root))
        return AgentOutcome(
            summary=self._summary(passed), files=written, claims_done=passed)

    def review(self, plan: Plan, outcome: AgentOutcome, *,
               diff: str = "") -> AgentOutcome:
        """Re-reads the evidence rather than re-running it.

        A review that re-ran the steps would be measuring a second execution and
        calling it a review of the first.
        """
        passed = bool(self.evidence) and all(e.passed for e in self.evidence)
        return outcome.model_copy(update={
            "claims_done": passed and outcome.claims_done,
            "summary": (outcome.summary if passed else
                        "the recorded evidence does not support completion")})

    def summarize(self, plan: Plan, outcome: AgentOutcome) -> str:
        lines = [f"{'ok' if e.passed else 'FAILED'}  {e.proves}  ({e.step})"
                 for e in self.evidence]
        return "\n".join(lines) or "nothing ran"

    def _summary(self, passed: bool) -> str:
        ran = len(self.evidence)
        if passed:
            return f"{ran} step(s) ran and every one passed"
        failed = next((e for e in self.evidence if not e.passed), None)
        if failed is None:
            return "no steps ran"
        return f"failed at: {failed.proves}"

    def _written(self, workspace: Path) -> tuple[str, ...]:
        """Files the steps produced, observed rather than claimed.

        The worker checks an agent's file list against the workspace. This is
        the one agent that can simply look, so it does — a claimed list is a
        claim even when the claimant is deterministic.
        """
        if not workspace.is_dir():
            return ()
        return tuple(sorted(
            str(p.relative_to(workspace)) for p in workspace.rglob("*")
            if p.is_file() and ".git" not in p.parts))


#: What the self-check agent does, defined once.
#:
#: In this module rather than in the worker script, because the control plane
#: proposes these steps as a plan and the worker executes them — two places
#: writing the same list is two places for it to drift, and the drift would be
#: invisible: the plan a person approved would stop describing what ran.
#:
#: Every effect is inside a discardable checkout, nothing is generated, no
#: provider is called and the third step *asserts* the confinement rather than
#: assuming it.
#: The canary's steps, **derived from the recipe** rather than written again.
#: They were a hardcoded list here; a recipe declaring the same three commands
#: would have been a second copy that drifts — the exact failure the recipe
#: primitive exists to prevent, introduced by the thing preventing it.
#:
#: The import is inside the function to keep the graph one-way: `fabric.recipes`
#: converts to this module's `Step`, so a module-level import back would cycle.
def self_check_steps() -> list[Step]:
    from ..fabric.recipes import get as recipe_for
    return recipe_for("execution-canary").for_adapter()


SELF_CHECK_STEPS: list[Step] = self_check_steps()


def build(agent_id: str, steps: list[Step], *, registry: Registry | None = None,
          sandbox: object | None = None) -> DeterministicAgent:
    """An agent ready to be handed to the worker, or a refusal.

    Raises when the registry does not list the agent — a worker configured
    against a name nobody wrote should fail at start-up, not at dispatch.
    """
    adapter = Adapter.for_id(agent_id, registry=registry, sandbox=sandbox)
    return DeterministicAgent(adapter=adapter, steps=steps)


__all__ = ["SELF_CHECK_STEPS", "Adapter", "DeterministicAgent", "Evidence",
           "NoSandbox", "NotIsolated", "NotRunnable", "Step", "build",
           "self_check_steps"]
