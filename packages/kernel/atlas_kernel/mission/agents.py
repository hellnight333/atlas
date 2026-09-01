"""The coding-agent boundary: plan, implement, review, summarize.

Distinct from `llm.LLMProvider`, which is a text-completion adapter. A coding
agent is the thing that changes a repository, and its contract is different: it
reports which files it touched, whether it believes the work is done, and what
stopped it. `LLMCodingAgent` adapts one to the other, so Claude, Codex, Qwen and
DeepSeek all arrive through the existing `ModelRegistry` rather than through four
new integrations.

**An agent saying "done" is not success.** §6 is explicit and so is this
module: `AgentOutcome.claims_done` is what the agent asserted, and nothing reads
it as a verdict. Tests, review and acceptance decide, and the worker treats a
confident agent with failing tests exactly as it treats a failing one.

`FakeCodingAgent` is mandatory rather than a convenience. Every failure mode the
worker has to survive — a timeout, a malformed report, half-finished work, an
agent that discovers a blocker — is a branch that would otherwise only ever run
in production against a real provider, which is the worst place to find out that
the handling is wrong.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from ..llm.models import Completion, Message, ModelSpec, Role
from ..llm.providers import LLMProvider
from .models import AgentInvocation, Blocker, Plan, PlanStep


class AgentError(RuntimeError):
    """The agent could not complete the call. Never a verdict about the work."""


class AgentTimeout(AgentError):
    """The agent exceeded its budget. Distinct from failing: nothing is known
    about the work, where a failure at least reports what went wrong."""


class MalformedResult(AgentError):
    """The agent returned something that is not a usable result.

    Its own class because the response is untrusted input — §30 — and a
    half-parsed one must not be treated as a partial success.
    """


class AgentOutcome(BaseModel):
    """What one agent call produced. Claims, not conclusions."""

    model_config = ConfigDict(frozen=True)

    summary: str = ""
    #: Paths the agent says it changed. Verified against the workspace by the
    #: caller — an agent's file list is a claim like any other.
    files: tuple[str, ...] = ()
    #: What the agent believes. Deliberately named so no caller mistakes it for
    #: a result: tests decide, not the agent.
    claims_done: bool = False
    blockers: tuple[Blocker, ...] = ()
    #: Free text the agent produced, kept for the report.
    notes: str = ""
    #: How many pieces of evidence the agent recorded. The currency of a role
    #: that writes no files: a research agent's successful run leaves the
    #: repository exactly as it found it, which is the correct outcome and would
    #: otherwise look identical to having done nothing.
    #:
    #: A coding agent leaves this at zero and is judged on `files`, as before.
    evidence_count: int = 0
    #: What this run has already written **outside** the mission's workspace,
    #: named and counted. Empty when it has written nothing there, which is the
    #: ordinary case for a coding role: its work sits in a workspace a failed
    #: mission never commits.
    #:
    #: Not so for a role that observes the world. `toolrunner.ToolAgent`
    #: persists findings, signals, observations and contactability *inside*
    #: `implement`, before anything reviews the run — deliberately, so that a
    #: database briefly away does not lose evidence that was genuinely
    #: gathered. A mission recorded as `failed` can therefore be one whose
    #: results are in production, and the worker writes this into the failure
    #: note so the record says both things at once.
    live_outputs: str = ""

    @property
    def produced_nothing(self) -> bool:
        """Whether this run has anything to show for itself.

        An agent that reports success having produced nothing is the most
        dangerous mode — it is confident, and there is no artefact to check.
        What counts as an artefact depends on the role, which is why this asks
        the outcome rather than assuming files.
        """
        return not self.files and not self.evidence_count
    invocation: AgentInvocation | None = None


@runtime_checkable
class CodingAgent(Protocol):
    """Something that can be asked to change a repository."""

    @property
    def name(self) -> str: ...

    def plan(self, request: str, *, context: str = "") -> Plan: ...

    def implement(self, plan: Plan, *, workspace_root: str,
                  context: str = "") -> AgentOutcome: ...

    def review(self, plan: Plan, outcome: AgentOutcome, *,
               diff: str = "") -> AgentOutcome: ...

    def summarize(self, plan: Plan, outcome: AgentOutcome) -> str: ...


class Behaviour(StrEnum):
    """How the fake agent misbehaves. One per branch the worker must survive."""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    MALFORMED = "malformed"
    #: Reports done, but touched nothing. The most dangerous mode, because the
    #: agent is confident and the repository is unchanged.
    PARTIAL = "partial"
    #: Real work, and the tests do not pass. The worker must not commit it.
    TEST_FAILURE = "test_failure"
    BLOCKER = "blocker"


class FakeCodingAgent:
    """Deterministic agent for tests. Never calls anything.

    Not a simulator of a real agent's judgement — it returns what the test set
    up, so a test asserting the worker retried is asserting the worker's
    behaviour rather than a guess about what Claude would have done.
    """

    #: What a blocker looks like when a test did not specify one. Present so
    #: the BLOCKER behaviour is never a no-op that quietly reports success.
    DEFAULT_BLOCKER = Blocker(kind="PENDING_CREDENTIAL",
                              detail="a credential is required",
                              action="Add the credential")

    def __init__(self, *, name: str = "fake", behaviour: Behaviour = Behaviour.SUCCESS,
                 files: tuple[str, ...] = ("README.md",),
                 blockers: tuple[Blocker, ...] = (),
                 succeed_after: int | None = None,
                 writes: bool = False) -> None:
        self._name = name
        self._behaviour = behaviour
        self._files = files
        #: Whether `implement` actually creates the files it names.
        #:
        #: Off by default, and that default is the useful one: a unit test of
        #: the worker wants an agent that *claims* completion without writing
        #: anything, because catching exactly that claim is the acceptance
        #: check's whole job. Turned on only when something needs to exercise
        #: the acceptance-and-commit path end to end, where a claim with no
        #: file behind it stops the run before it reaches either.
        self._writes = writes
        self._blockers = blockers or (self.DEFAULT_BLOCKER,)
        #: Lets a test drive "fails twice, then works", which is the only way to
        #: check that bounded retry actually retries rather than merely stopping.
        self._succeed_after = succeed_after
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def behaviour(self) -> Behaviour:
        if self._succeed_after is not None and self.calls > self._succeed_after:
            return Behaviour.SUCCESS
        return self._behaviour

    def _invocation(self, task: str) -> AgentInvocation:
        return AgentInvocation(provider="fake", model=self._name, task=task,
                               cost_status="UNKNOWN")

    def plan(self, request: str, *, context: str = "") -> Plan:
        self.calls += 1
        if self.behaviour is Behaviour.BLOCKER:
            return Plan(goal=request, approval_required=False,
                        blockers=self._blockers)
        if self.behaviour is Behaviour.MALFORMED:
            raise MalformedResult("the agent returned no usable plan")
        return Plan(goal=request, why=context, approval_required=False,
                    steps=(PlanStep(order=1, title=f"Implement: {request}",
                                    files=self._files),))

    def implement(self, plan: Plan, *, workspace_root: str,
                  context: str = "") -> AgentOutcome:
        self.calls += 1
        behaviour = self.behaviour
        if behaviour is Behaviour.TIMEOUT:
            raise AgentTimeout("the agent exceeded its time budget")
        if behaviour is Behaviour.FAILURE:
            raise AgentError("the agent could not complete the work")
        if behaviour is Behaviour.MALFORMED:
            raise MalformedResult("the agent returned an unusable result")
        if behaviour is Behaviour.BLOCKER:
            return AgentOutcome(summary="blocked", claims_done=False,
                                blockers=self._blockers,
                                invocation=self._invocation("implement"))
        if behaviour is Behaviour.PARTIAL:
            # Confident, and changed nothing. The worker must catch this.
            return AgentOutcome(summary="done", claims_done=True, files=(),
                                invocation=self._invocation("implement"))
        if self._writes:
            for name in self._files:
                path = Path(workspace_root) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{plan.goal}\n", encoding="utf-8")
        return AgentOutcome(summary=f"implemented {plan.goal}", files=self._files,
                            claims_done=True,
                            invocation=self._invocation("implement"))

    def review(self, plan: Plan, outcome: AgentOutcome, *,
               diff: str = "") -> AgentOutcome:
        self.calls += 1
        if self.behaviour is Behaviour.TEST_FAILURE:
            return AgentOutcome(summary="the change does not do what was asked",
                                claims_done=False, files=outcome.files,
                                invocation=self._invocation("review"))
        return outcome.model_copy(update={
            "summary": "review passed", "claims_done": True,
            "invocation": self._invocation("review")})

    def summarize(self, plan: Plan, outcome: AgentOutcome) -> str:
        self.calls += 1
        return f"{plan.goal}: {outcome.summary}"


class LLMCodingAgent:
    """Adapts any registered model to the coding-agent contract.

    Claude, Codex, Qwen and DeepSeek all arrive here through the existing
    `ModelRegistry` — the OpenAI-compatible provider already covers three of
    them — so adding a model is a registration rather than a new integration.

    Deliberately thin. It builds prompts, calls the provider and converts the
    reply; it makes no decision about whether the work succeeded, because that
    is the worker's job and an agent grading itself is the failure this whole
    module is arranged to prevent.
    """

    def __init__(self, provider: LLMProvider, spec: ModelSpec, *,
                 name: str = "") -> None:
        self._provider = provider
        self._spec = spec
        self._name = name or spec.id

    @property
    def name(self) -> str:
        return self._name

    def _ask(self, task: str, prompt: str) -> tuple[str, AgentInvocation]:
        messages = [Message(role=Role.USER, content=prompt)]
        completion: Completion = self._provider.complete(
            messages, self._spec,
            max_tokens=self._spec.max_output_tokens,
            # Low, deliberately. This writes code and reviews diffs, where a
            # creative reformulation of what the file already says is a defect.
            temperature=0.1)
        text = (completion.text or "").strip()
        if not text:
            raise MalformedResult(f"{self._name} returned nothing for {task}")

        usage = getattr(completion, "usage", None)
        prompt_tokens = getattr(usage, "input_tokens", None) if usage else None
        output_tokens = getattr(usage, "output_tokens", None) if usage else None
        # Cost only where the price table has both numbers. ESTIMATED says so;
        # a figure with no provenance would be the one number nobody can check.
        cost = None
        status = "UNKNOWN"
        if prompt_tokens is not None and output_tokens is not None and (
                self._spec.input_cost_per_mtok or self._spec.output_cost_per_mtok):
            cost = (prompt_tokens / 1_000_000 * self._spec.input_cost_per_mtok
                    + output_tokens / 1_000_000 * self._spec.output_cost_per_mtok)
            status = "ESTIMATED"
        return text, AgentInvocation(
            provider=self._spec.provider, model=self._spec.id, task=task,
            input_tokens=prompt_tokens, output_tokens=output_tokens,
            cost=cost, cost_status=status,
            currency="USD" if cost is not None else "")

    def plan(self, request: str, *, context: str = "") -> Plan:
        text, _ = self._ask("plan", f"{context}\n\nPlan this work:\n{request}")
        return Plan(goal=request, why=text, approval_required=True,
                    steps=(PlanStep(order=1, title=request),))

    def implement(self, plan: Plan, *, workspace_root: str,
                  context: str = "") -> AgentOutcome:
        text, invocation = self._ask(
            "implement", f"{context}\n\nImplement this plan:\n{plan.goal}")
        # `claims_done` is the model's assertion and is treated as one.
        return AgentOutcome(summary=text[:400], notes=text, claims_done=True,
                            invocation=invocation)

    def review(self, plan: Plan, outcome: AgentOutcome, *,
               diff: str = "") -> AgentOutcome:
        text, invocation = self._ask(
            "review", f"Review this change against the goal {plan.goal!r}:\n{diff}")
        return outcome.model_copy(update={"summary": text[:400],
                                          "invocation": invocation})

    def summarize(self, plan: Plan, outcome: AgentOutcome) -> str:
        text, _ = self._ask("summarize", f"Summarise: {plan.goal} — {outcome.summary}")
        return text


class Roles(BaseModel):
    """Which agent does which part. Planning, implementation and review may
    legitimately use different models — a cheaper one to plan, a stronger one to
    write, and an *independent* one to review, so the reviewer is not grading
    its own work."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    planner: CodingAgent
    implementer: CodingAgent
    reviewer: CodingAgent | None = None

    @property
    def review_is_independent(self) -> bool:
        """Whether the reviewer is a different agent from the implementer."""
        if self.reviewer is None:
            return False
        return getattr(self.reviewer, "name", "") != getattr(self.implementer, "name", "")

    @classmethod
    def all(cls, agent: CodingAgent) -> Roles:
        """One agent for everything. Honest about not being independent."""
        return cls(planner=agent, implementer=agent, reviewer=agent)
