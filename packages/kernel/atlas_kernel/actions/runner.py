"""Running a plan: order the steps, thread their outputs, repair what breaks.

`ExecutionPlan` and `PlanStep` already existed; nothing executed them. A plan
was a description. This turns it into something that runs.

Three things make it a plan rather than a list.

**Dependencies decide order.** Steps are sorted topologically, so a plan may be
written in any order and a cycle is refused rather than deadlocked.

**Outputs flow forward.** A payload may reference an earlier step —
``{"url": "${deploy.url}"}`` — and the reference is resolved at the moment the
step runs. Without this the composition is fictional: every step would need to
be told in advance what the previous one was going to produce.

**Failure is a branch, not an end.** When a step fails, a repairer may diagnose
it and insert corrective steps, after which the failed step is retried. That is
the difference between a pipeline and a loop: a pipeline that meets a failing
test stops, and this fixes it and runs the test again.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..agents.plan_models import ExecutionPlan, PlanStep
from ..models import ActionSpec
from .context import ActionRecord, ExecutionContext
from .handlers import (
    BROWSER_OPERATE,
    CODE_EXECUTE,
    CODE_GENERATE,
    CODE_WRITE,
    SITE_DEPLOY,
    WEB_SEARCH,
    ActionError,
    PublishNotAuthorised,
    browser_operate,
    code_execute,
    code_generate,
    code_write,
    site_deploy,
    web_search,
)
from .limits import CapacityUnavailable, Deadline, JobLimits, JobSlots

#: ${step_id.key}, ${step_id.key.nested} or ${step_id.list[0].key}
#:
#: Bracket indexing is included because models write it — it is the obvious
#: syntax for "the first search result" — and the earlier pattern silently did
#: not match it. An unmatched reference was left in place as a literal, so
#: "${search.sources[0].title}" was rendered onto a published page as those
#: exact characters and every step reported success.
REFERENCE = re.compile(r"\$\{([A-Za-z0-9_.\-\[\]]+)\}")

#: How many times a step may be repaired before the plan gives up. A repairer
#: that cannot fix something in two attempts is looping, not converging.
MAX_ATTEMPTS = 3


class Repairer(Protocol):
    """Diagnoses a failed step and proposes corrective steps.

    Returning an empty list means "I cannot fix this", which ends the plan
    honestly rather than retrying the same thing until the attempt limit.
    """

    def repair(
        self, step: PlanStep, record: ActionRecord, ctx: ExecutionContext
    ) -> list[PlanStep]: ...


class PlanReport(BaseModel):
    """What happened, in the form the operator asked to be reported."""

    model_config = ConfigDict(frozen=True)

    plan_id: str
    goal: str
    ok: bool
    steps_total: int
    steps_succeeded: int
    steps_failed: int
    repairs: int = 0
    duration_seconds: float = 0.0
    failed_step: str = ""
    error: str = ""
    #: Set when the plan was stopped by its own budget rather than by a step
    #: failing. A different thing from a failure, and a different remedy.
    timed_out: bool = False
    #: Set when the work never started because the host was already at capacity.
    refused: bool = False
    outputs: dict[str, Any] = Field(default_factory=dict)
    records: list[ActionRecord] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)

    def provenance(self) -> dict[str, Any]:
        """Where the output came from: evidence, who read it, what it decided.

        Built from what executed rather than from what the plan intended, and
        keyed on actions rather than step names so it describes any plan a model
        composes. The question it answers is the one a customer eventually asks
        — "why does my page say this?" — and it can only be answered if the
        chain from source URL to published artifact was recorded as it happened.
        """
        from .llm_planner import INFORMATIONAL_ACTIONS

        researched = [
            {
                "step": r.step_id,
                "query": r.output.get("query", ""),
                "sources": [s.get("url", "") for s in (r.output.get("sources") or [])],
            }
            for r in self.records
            if r.action in INFORMATIONAL_ACTIONS and r.ok
        ]
        evidence_steps = {entry["step"] for entry in researched}

        decisions = [
            {
                "step": r.step_id,
                "action": r.action,
                "consumed_from": [s for s in r.consumed_from if s in evidence_steps],
                # What the decision actually produced, as user-facing copy.
                "produced": {
                    k: v
                    for k, v in r.payload.items()
                    if k in ("title", "headline", "tagline") and isinstance(v, str)
                },
            }
            for r in self.records
            if r.ok and any(s in evidence_steps for s in r.consumed_from)
        ]

        artifacts = {
            "files": sorted(
                {f for r in self.records if r.ok for f in (r.output.get("written") or [])}
            ),
            "deployed_url": next(
                (r.output.get("url", "") for r in reversed(self.records)
                 if r.action == "site.deploy" and r.ok), ""
            ),
            "evidence": list(self.evidence),
        }

        return {
            "researched": researched,
            "evidence_consumed": bool(decisions),
            "decisions": decisions,
            "artifacts": artifacts,
        }

    def render_provenance(self) -> str:
        """The provenance as a person reads it."""
        p = self.provenance()
        if not p["researched"]:
            return "provenance: no external research was used."
        lines = ["provenance:"]
        for entry in p["researched"]:
            lines.append(f"  researched {entry['query']!r} -> {len(entry['sources'])} source(s)")
            lines.extend(f"    - {url}" for url in entry["sources"][:5])
        if not p["decisions"]:
            lines.append("  NOTHING CONSUMED IT — the research did not reach a decision.")
        for decision in p["decisions"]:
            lines.append(
                f"  {decision['step']} ({decision['action']}) read "
                f"{', '.join(decision['consumed_from'])} and produced:"
            )
            lines.extend(f"    {k}: {v}" for k, v in decision["produced"].items())
        if p["artifacts"]["deployed_url"]:
            lines.append(f"  deployed: {p['artifacts']['deployed_url']}")
        return "\n".join(lines)

    def summary(self) -> str:
        if self.refused:
            head = f"REFUSED: {self.error}"
        elif self.timed_out:
            head = f"TIMED OUT: {self.error}"
        elif self.ok:
            head = "SUCCEEDED"
        else:
            head = f"FAILED at {self.failed_step}: {self.error}"
        lines = [
            f"{head} — {self.steps_succeeded}/{self.steps_total} steps"
            + (f", {self.repairs} repair(s)" if self.repairs else "")
            + f", {self.duration_seconds:.1f}s",
        ]
        lines.extend(f"  {i}. {r}" for i, r in enumerate(self.records, 1))
        if self.evidence:
            lines.append(f"  evidence: {len(self.evidence)} artifact(s)")
        return "\n".join(lines)


def resolve(value: Any, outputs: dict[str, dict[str, Any]]) -> Any:
    """Replace ``${step.key}`` references with earlier steps' outputs.

    A whole-string reference keeps the original type — ``${search.count}`` is an
    int, not "5" — while an embedded one interpolates. Losing the type here
    would silently turn every referenced number into a string at the exact point
    a caller stops looking.
    """
    if isinstance(value, dict):
        return {k: resolve(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, outputs) for v in value]
    if not isinstance(value, str):
        return value

    whole = REFERENCE.fullmatch(value)
    if whole:
        return _lookup(whole.group(1), outputs)
    return REFERENCE.sub(lambda m: str(_lookup(m.group(1), outputs)), value)


def _lookup(path: str, outputs: dict[str, dict[str, Any]]) -> Any:
    # list[0] and list.0 mean the same thing. Accepting both costs one line and
    # saves a class of silent failure, because a model will write either.
    path = path.replace("[", ".").replace("]", "")
    step_id, _, rest = path.partition(".")
    if step_id not in outputs:
        raise ActionError(
            f"step {step_id!r} has no output yet — referenced as ${{{path}}}. "
            "Either it has not run or it is missing from this step's dependencies."
        )
    current: Any = outputs[step_id]
    for part in filter(None, rest.split(".")):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ActionError(f"${{{path}}} does not exist in the output of {step_id!r}")
    return current


def topological(steps: list[PlanStep]) -> list[PlanStep]:
    """Dependency order. Refuses a cycle rather than hanging on one."""
    by_id = {s.id: s for s in steps}
    ordered: list[PlanStep] = []
    state: dict[str, int] = {}

    def visit(step: PlanStep) -> None:
        mark = state.get(step.id, 0)
        if mark == 1:
            raise ActionError(f"the plan has a dependency cycle involving {step.id!r}")
        if mark == 2:
            return
        state[step.id] = 1
        for dependency in step.dependencies:
            if dependency in by_id:
                visit(by_id[dependency])
        state[step.id] = 2
        ordered.append(step)

    for step in steps:
        visit(step)
    return ordered


class ActionRunner:
    """Maps action names to the code that performs them."""

    def __init__(self) -> None:
        self._handlers: dict[str, Any] = {}
        self.specs: dict[str, ActionSpec] = {}

    def register(self, spec: ActionSpec, handler) -> None:
        self._handlers[spec.name] = handler
        self.specs[spec.name] = spec

    def registered(self) -> list[str]:
        return sorted(self._handlers)

    def execute(self, step: PlanStep, ctx: ExecutionContext, *, attempt: int = 1) -> ActionRecord:
        handler = self._handlers.get(step.action)
        started = time.monotonic()

        if handler is None:
            return ctx.record(
                ActionRecord(
                    step_id=step.id,
                    action=step.action,
                    capability=step.capability,
                    ok=False,
                    attempt=attempt,
                    error=(
                        f"no handler for {step.action!r}. Registered: "
                        f"{', '.join(self.registered()) or 'none'}"
                    ),
                )
            )

        # Captured before resolution replaces them, because afterwards the
        # payload contains values and no record of where they came from.
        consumed = sorted(
            {
                ref.split(".", 1)[0].split("[", 1)[0]
                for ref in REFERENCE.findall(json.dumps(step.payload, default=str))
            }
        )
        try:
            payload = resolve(step.payload, ctx.outputs)
            # Nothing may reach a handler still carrying template syntax. A
            # reference that survives resolution is a bug in the plan or in the
            # resolver, and passing it through publishes "${...}" to a customer
            # while every step reports success.
            leftover = REFERENCE.findall(json.dumps(payload, default=str))
            if leftover:
                raise ActionError(
                    f"unresolved reference(s) {leftover} in step {step.id!r}. "
                    "The step they name produced no such value."
                )
        except ActionError as error:
            return ctx.record(
                ActionRecord(
                    step_id=step.id,
                    action=step.action,
                    capability=step.capability,
                    ok=False,
                    attempt=attempt,
                    error=str(error),
                    duration_seconds=round(time.monotonic() - started, 3),
                    consumed_from=consumed,
                )
            )

        try:
            output = handler(payload, ctx) or {}
            # An action may report failure in its output rather than by raising —
            # a failing test is data, not an exception — so both are honoured.
            ok = bool(output.get("ok", True))
            error = (
                "" if ok else str(output.get("error") or output.get("tail") or "reported failure")
            )
        except PublishNotAuthorised as refusal:
            # A policy refusal, never a failure to retry.
            output, ok, error = {"refused": True}, False, str(refusal)
        except Exception as failure:  # noqa: BLE001 - the record is the point
            output, ok, error = {}, False, f"{type(failure).__name__}: {failure}"

        return ctx.record(
            ActionRecord(
                step_id=step.id,
                action=step.action,
                capability=step.capability,
                payload=payload if isinstance(payload, dict) else {},
                output=output,
                ok=ok,
                error=error,
                attempt=attempt,
                duration_seconds=round(time.monotonic() - started, 3),
                evidence=[str(p) for p in (output.get("evidence") or [])],
                consumed_from=consumed,
            )
        )


class PlanRunner:
    """Executes an `ExecutionPlan` against real actions, within bounds.

    The bounds are not decoration. A plan that runs unbounded on a shared host
    is how the control plane became unreachable: the failure was not an error,
    it was silence. Everything here is designed to stop with a sentence rather
    than to keep going quietly.
    """

    def __init__(
        self,
        actions: ActionRunner,
        *,
        repairer: Repairer | None = None,
        limits: JobLimits | None = None,
        slots: JobSlots | None = None,
    ) -> None:
        self.actions = actions
        self.repairer = repairer
        self.limits = limits or (slots.limits if slots else JobLimits.for_host())
        #: Shared across runners when one is passed in, which is what makes the
        #: concurrency limit apply to the host rather than to one caller.
        self.slots = slots or JobSlots(self.limits)

    def run(self, plan: ExecutionPlan, ctx: ExecutionContext) -> PlanReport:
        started = time.monotonic()
        try:
            slot = self.slots.acquire()
        except CapacityUnavailable as refusal:
            # Refused, not failed. The work never ran, so there is nothing to
            # diagnose and everything to retry later.
            return PlanReport(
                plan_id=plan.plan_id,
                goal=plan.goal,
                ok=False,
                refused=True,
                error=str(refusal),
                steps_total=len(plan.steps),
                steps_succeeded=0,
                steps_failed=0,
                duration_seconds=round(time.monotonic() - started, 3),
            )
        with slot:
            return self._run_within_budget(plan, ctx, started)

    def _run_within_budget(
        self, plan: ExecutionPlan, ctx: ExecutionContext, started: float
    ) -> PlanReport:
        ordered = topological(plan.steps)
        deadline = Deadline(self.limits.job_timeout_seconds)
        repairs = 0
        failed_step = error = ""
        timed_out = False

        for step in ordered:
            # Between steps, never mid-step: killing an action halfway leaves a
            # half-written workspace and a half-finished deployment, which is
            # worse than a slightly late stop.
            if deadline.expired:
                timed_out = True
                failed_step = step.id
                error = (
                    f"the plan ran past its {deadline.seconds:g}s budget before {step.id!r} "
                    f"({deadline.elapsed:.1f}s elapsed). Stopped rather than left running."
                )
                break

            # A step never gets more time than the plan has left, or the plan
            # overruns by the difference on its final step every time.
            if step.action == "code.execute" and isinstance(step.payload, dict):
                ceiling = float(step.payload.get("timeout", self.limits.step_timeout_seconds))
                step.payload["timeout"] = deadline.step_timeout(ceiling)

            record = self.actions.execute(step, ctx)
            attempt = 1

            while (
                not record.ok
                and self.repairer is not None
                and attempt < MAX_ATTEMPTS
                and repairs < self.limits.max_repairs
                and not deadline.expired
            ):
                if isinstance(record.error, str) and "not authorised" in record.error.lower():
                    break  # a refusal is not repaired; it is escalated
                fixes = self.repairer.repair(step, record, ctx)
                if not fixes:
                    break
                for fix in fixes:
                    repairs += 1
                    fix_record = self.actions.execute(fix, ctx)
                    if not fix_record.ok:
                        break
                attempt += 1
                record = self.actions.execute(step, ctx, attempt=attempt)

            if not record.ok:
                failed_step, error = step.id, record.error
                break

        succeeded = sum(1 for r in ctx.records if r.ok)
        return PlanReport(
            plan_id=plan.plan_id,
            goal=plan.goal,
            ok=not failed_step,
            steps_total=len(ordered),
            steps_succeeded=succeeded,
            steps_failed=sum(1 for r in ctx.records if not r.ok),
            repairs=repairs,
            duration_seconds=round(time.monotonic() - started, 3),
            failed_step=failed_step,
            error=error,
            timed_out=timed_out,
            outputs=dict(ctx.outputs),
            records=list(ctx.records),
            evidence=ctx.evidence,
        )


def default_action_runner() -> ActionRunner:
    """Every verified capability, registered as an executable action."""
    runner = ActionRunner()
    for name, description, handler in (
        (WEB_SEARCH, "Search the open web and keep source URLs", web_search),
        (CODE_GENERATE, "Generate the files for a small static site", code_generate),
        (CODE_WRITE, "Write files into the project workspace", code_write),
        (CODE_EXECUTE, "Run a command in the workspace and capture its output", code_execute),
        (BROWSER_OPERATE, "Open a page, verify it, and keep evidence", browser_operate),
        (SITE_DEPLOY, "Publish a built site and promote it", site_deploy),
    ):
        runner.register(ActionSpec(name=name, description=description), handler)
    return runner
