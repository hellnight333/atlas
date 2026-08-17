"""A model-driven planner, and the validation that makes it safe to use.

The deterministic planner knows one shape of work. This one composes the
registered actions freely, which is the point — and also the risk, because a
language model asked for a plan will occasionally invent an action that does not
exist, reference a step that never ran, or quietly omit the verification step.

So **nothing a model produces is trusted as a plan until it validates.** Every
action name must be registered, every reference must resolve to an earlier step,
the graph must be acyclic, and the plan must be non-empty. A plan that fails
validation is rejected with the reason, and the caller falls back to the
deterministic planner rather than executing something half-understood.

Two things the model deliberately cannot do.

**It cannot grant itself authorisation.** Approval is enforced in the deploy
handler against the execution context, not in the plan, so a model emitting
``"public": true`` produces a plan that is *refused* at run time exactly as a
hand-written one would be. The planner is untrusted input; the boundary does not
move because the author changed.

**It cannot invent a shell string.** ``code.execute`` takes argv, and a plan
whose argv is a string is rejected during validation rather than assembled into
something a shell interprets.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..agents.plan_models import ExecutionPlan, PlanStep
from ..llm.models import Message, Role
from .handlers import CODE_EXECUTE
from .runner import REFERENCE, ActionError, topological

#: What the model is told it may use. Generated from the registry rather than
#: written out, so an action added later is available to the planner without
#: anyone remembering to update a prompt.
SYSTEM = """You plan work for Qevik, an autonomous build system.

Return ONLY a JSON object. No prose, no markdown fence.

{{
  "steps": [
    {{"id": "short_id", "action": "<one of the actions below>",
     "description": "what this step does",
     "payload": {{...}}, "dependencies": ["earlier_step_id"]}}
  ]
}}

Available actions and their payloads:
{actions}

Referencing earlier steps: a payload value may be "${{step_id.key}}" and will be
replaced with that step's output when the step runs. Example: after a deploy
step called "deploy", use "${{deploy.url}}" to get the deployed URL.

Rules you must follow:
- Use only the actions listed above. Inventing one makes the plan invalid.
- Every id must be unique; every dependency must name an earlier step.
- code.execute takes "argv" as a LIST of strings, never a shell string.
- After generating code, always write it, then run its tests before building.
- After deploying, always verify the deployed URL with browser.operate.
- Never skip verification. A build that was not opened in a browser is not done.
"""

ACTION_HELP = {
    "web.search": '{"query": "...", "count": 5} -> {sources: [{url,title,description}], top_url}',
    "code.generate": (
        '{"title": "...", "headline": "...", "tagline": "...", "features": ["..."]} '
        "-> {files: {path: content}}"
    ),
    "code.write": '{"files": {"path": "content"}} -> {written: [...]}',
    "code.execute": (
        '{"argv": ["python3", "-m", "pytest", "-q"], "timeout": 300} '
        "-> {exit_code, ok, stdout, stderr, tail}"
    ),
    "browser.operate": (
        '{"url": "...", "expect_title": "...", "expect_text": {"#id": "text"}, '
        '"screenshot": "name.png"} -> {status, title, verified, problems, extracted}'
    ),
    "site.deploy": ('{"slug": "...", "source_dir": "dist", "promote": true} -> {url, version_id}'),
}

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


class PlanRejected(ActionError):
    """The model produced something that is not a usable plan.

    Carries the reason, because "the model was wrong" is not actionable and
    "referenced step 'reserch' which does not exist" is.
    """


def extract_json(text: str) -> dict[str, Any]:
    """Pull the JSON object out of a model's reply.

    Models fence their JSON despite being asked not to, and they preface it with
    a sentence despite being asked not to. Tolerating both is cheaper than a
    retry, and neither makes the result less checkable — everything is validated
    afterwards regardless.
    """
    fenced = _FENCE.search(text)
    candidate = (fenced.group(1) if fenced else text).strip()

    # The whole reply first. Going straight to brace-slicing would quietly
    # accept a JSON array by finding the first object inside it, which is a
    # different plan from the one the model returned.
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        if not isinstance(parsed, dict):
            raise PlanRejected(f"the reply was JSON but not an object: {type(parsed).__name__}")
        return parsed

    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise PlanRejected(f"no JSON object in the reply: {text[:200]!r}")
    try:
        sliced = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as error:
        raise PlanRejected(f"the reply was not valid JSON: {error}") from error
    if not isinstance(sliced, dict):
        raise PlanRejected("the reply was JSON but not an object")
    return sliced


def validate(raw: dict[str, Any], *, known_actions: set[str]) -> list[PlanStep]:
    """Turn a model's JSON into steps, or refuse with the reason."""
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise PlanRejected("the plan has no steps")

    seen: set[str] = set()
    steps: list[PlanStep] = []

    for index, item in enumerate(steps_raw):
        if not isinstance(item, dict):
            raise PlanRejected(f"step {index} is not an object")
        step_id = str(item.get("id") or "").strip()
        action = str(item.get("action") or "").strip()

        if not step_id:
            raise PlanRejected(f"step {index} has no id")
        if step_id in seen:
            raise PlanRejected(f"duplicate step id {step_id!r}")
        if action not in known_actions:
            raise PlanRejected(
                f"step {step_id!r} uses unknown action {action!r}. "
                f"Registered: {', '.join(sorted(known_actions))}"
            )

        payload = item.get("payload") or {}
        if not isinstance(payload, dict):
            raise PlanRejected(f"step {step_id!r} has a non-object payload")

        if action == CODE_EXECUTE and not isinstance(payload.get("argv"), list):
            raise PlanRejected(
                f"step {step_id!r} passes argv as {type(payload.get('argv')).__name__}; "
                "code.execute takes a list of strings and never a shell string"
            )

        dependencies = [str(d) for d in (item.get("dependencies") or [])]
        for dependency in dependencies:
            if dependency not in seen:
                raise PlanRejected(
                    f"step {step_id!r} depends on {dependency!r}, which is not an earlier step"
                )

        # Every ${...} must point at a step that has already run. Catching this
        # here rather than at execution turns a mid-run failure — after files
        # are written and money is spent — into a rejected plan.
        for referenced in _references(payload):
            target = referenced.split(".", 1)[0]
            if target not in seen:
                raise PlanRejected(
                    f"step {step_id!r} references ${{{referenced}}}, but {target!r} "
                    "has not run by then"
                )

        seen.add(step_id)
        steps.append(
            PlanStep(
                id=step_id,
                description=str(item.get("description") or action),
                capability=action,
                action=action,
                payload=payload,
                expected_output=str(item.get("expected_output") or ""),
                dependencies=dependencies,
            )
        )

    topological(steps)  # refuses a cycle
    return steps


def _references(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [r for v in value.values() for r in _references(v)]
    if isinstance(value, list):
        return [r for v in value for r in _references(v)]
    if isinstance(value, str):
        return REFERENCE.findall(value)
    return []


class LLMPlanner:
    """Composes a plan with a language model, and checks its work.

    Falls back to a deterministic planner when no model is configured or the
    model's plan does not validate. Falling back is not a failure mode to hide:
    it is the reason this can be switched on before every model in the fleet is
    reliable.
    """

    def __init__(
        self,
        registry,
        *,
        actions,
        fallback=None,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> None:
        self.registry = registry
        self.actions = actions
        self.fallback = fallback
        self.max_tokens = max_tokens
        # Zero by default: a plan is a structured artifact, not prose, and
        # sampling variety here buys nothing and costs reproducibility.
        self.temperature = temperature
        #: Why the last call fell back, if it did. Reported, never swallowed.
        self.last_fallback_reason = ""
        self.last_model = ""

    @property
    def available(self) -> bool:
        try:
            self.registry.resolve()
            return True
        except Exception:  # noqa: BLE001 - any resolution failure means no model
            return False

    def _prompt(self, request: str) -> list[Message]:
        catalogue = "\n".join(
            f"- {name}: {ACTION_HELP.get(name, 'see the action registry')}"
            for name in sorted(self.actions.registered())
        )
        return [
            Message(role=Role.SYSTEM, content=SYSTEM.format(actions=catalogue)),
            Message(role=Role.USER, content=request),
        ]

    def plan(self, request: str, **fallback_kwargs) -> ExecutionPlan:
        self.last_fallback_reason = ""
        try:
            registration = self.registry.resolve(needs_json=True)
        except Exception as error:  # noqa: BLE001
            return self._fall_back(f"no model configured ({error})", request, fallback_kwargs)

        self.last_model = registration.spec.id
        try:
            completion = registration.provider.complete(
                self._prompt(request),
                registration.spec,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            steps = validate(
                extract_json(completion.text), known_actions=set(self.actions.registered())
            )
        except PlanRejected as rejected:
            return self._fall_back(
                f"the model's plan was rejected: {rejected}", request, fallback_kwargs
            )
        except Exception as error:  # noqa: BLE001
            return self._fall_back(f"the model call failed: {error}", request, fallback_kwargs)

        return ExecutionPlan(
            goal=request,
            steps=steps,
            capabilities_required=sorted({s.capability for s in steps}),
            expected_outputs=["Composed by " + registration.spec.id],
            confidence=0.7,
            review_required=any(s.action == "site.deploy" for s in steps),
            context_snapshot={"planner": "llm", "model": registration.spec.id},
        )

    def _fall_back(self, reason: str, request: str, kwargs: dict[str, Any]) -> ExecutionPlan:
        self.last_fallback_reason = reason
        if self.fallback is None:
            raise PlanRejected(reason)
        plan = self.fallback(goal=request, **kwargs)
        # Recorded on the plan itself, so a run that used the fallback can never
        # be mistaken later for one the model composed.
        return plan.model_copy(
            update={"context_snapshot": {"planner": "deterministic", "fallback_reason": reason}}
        )
