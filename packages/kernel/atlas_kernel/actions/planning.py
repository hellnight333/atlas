"""Turning a request into a plan, and repairing a plan that breaks.

The planner here is deterministic. That is a deliberate choice rather than a
placeholder: the shape of "build a site, test it, verify it, deploy it, verify
the deployment" is known, and a language model asked to invent that shape will
occasionally omit the verification step — which is the one step whose absence
nobody notices, because everything still reports success.

What a model is genuinely better at is the *content*: the name, the tagline, the
features. Those enter through the payload. `code.generate` renders the markup so
the site is reproducible from stored inputs, which the website factory already
established as a requirement.

`ModelRegistry` is wired and would let an LLM planner register alongside this
one without changing anything below. It is not used here because no model
credential is configured on the server — a real external dependency, recorded as
such rather than papered over.
"""

from __future__ import annotations

import re

from ..agents.plan_models import ExecutionPlan, PlanStep
from .context import ActionRecord, ExecutionContext
from .handlers import (
    BROWSER_OPERATE,
    CODE_EXECUTE,
    CODE_GENERATE,
    CODE_WRITE,
    SITE_DEPLOY,
    WEB_SEARCH,
)

PYTEST = ["python3", "-m", "pytest", "-q", "test_app.py", "-p", "no:cacheprovider"]


def plan_website(
    *,
    goal: str,
    title: str,
    headline: str = "",
    tagline: str = "",
    features: list[str] | None = None,
    research_query: str = "",
    slug: str = "",
    python: str = "python3",
    serve_url: str = "",
    deploy: bool = True,
) -> ExecutionPlan:
    """Compose the full build → test → verify → deploy → verify workflow.

    Every step's dependencies are declared, so the runner orders them and a
    later step can reference an earlier one's output. Nothing here executes;
    this returns a description that `PlanRunner` runs.
    """
    pytest_argv = [python, *PYTEST[1:]]
    steps: list[PlanStep] = []

    if research_query:
        steps.append(
            PlanStep(
                id="research",
                description=f"Research: {research_query}",
                capability=WEB_SEARCH,
                action=WEB_SEARCH,
                payload={"query": research_query, "count": 5},
                expected_output="Source URLs and snippets, with provenance",
            )
        )

    steps.append(
        PlanStep(
            id="generate",
            description=f"Generate the site for {title!r}",
            capability=CODE_GENERATE,
            action=CODE_GENERATE,
            payload={
                "title": title,
                "headline": headline or title,
                "tagline": tagline,
                "features": features or [],
            },
            expected_output="app.py, test_app.py and build.py",
            dependencies=["research"] if research_query else [],
        )
    )
    steps.append(
        PlanStep(
            id="write",
            description="Write the generated files into the workspace",
            capability=CODE_WRITE,
            action=CODE_WRITE,
            # The composition that makes this a plan: the files come from the
            # step before, resolved when this one runs.
            payload={"files": "${generate.files}"},
            expected_output="Files on disk",
            dependencies=["generate"],
        )
    )
    steps.append(
        PlanStep(
            id="test",
            description="Run the project's own test suite",
            capability=CODE_EXECUTE,
            action=CODE_EXECUTE,
            payload={"argv": pytest_argv},
            expected_output="A passing suite",
            dependencies=["write"],
        )
    )
    steps.append(
        PlanStep(
            id="build",
            description="Build the distributable site",
            capability=CODE_EXECUTE,
            action=CODE_EXECUTE,
            payload={"argv": [python, "build.py"]},
            expected_output="dist/index.html",
            dependencies=["test"],
        )
    )
    if serve_url:
        steps.append(
            PlanStep(
                id="verify_local",
                description="Open the locally served site in Chromium and verify it",
                capability=BROWSER_OPERATE,
                action=BROWSER_OPERATE,
                payload={
                    "url": serve_url,
                    "expect_title": title,
                    "expect_text": {"#headline": headline or title},
                    "screenshot": "local.png",
                },
                expected_output="A 200 with the expected headline, and a screenshot",
                dependencies=["build"],
            )
        )
    if deploy:
        steps.append(
            PlanStep(
                id="deploy",
                description="Publish the built site and promote it",
                capability=SITE_DEPLOY,
                action=SITE_DEPLOY,
                payload={"slug": slug or title, "source_dir": "dist", "promote": True},
                expected_output="A deployed URL",
                dependencies=["verify_local"] if serve_url else ["build"],
                review_required=True,
            )
        )
        steps.append(
            PlanStep(
                id="verify_deployed",
                description="Open the deployed URL and verify what a visitor receives",
                capability=BROWSER_OPERATE,
                action=BROWSER_OPERATE,
                payload={
                    "url": "${deploy.url}",
                    "expect_title": title,
                    "expect_text": {"#headline": headline or title},
                    "screenshot": "deployed.png",
                },
                expected_output="The deployed page verified in a browser",
                dependencies=["deploy"],
            )
        )

    return ExecutionPlan(
        goal=goal,
        steps=steps,
        capabilities_required=sorted({s.capability for s in steps}),
        expected_outputs=["A deployed, browser-verified website URL"],
        confidence=0.9,
        review_required=deploy,
    )


_TITLE = re.compile(r"(?:website|site|game)\s+(?:for|about|called)\s+(?:a\s+)?(.+)", re.I)


def title_from_request(request: str, fallback: str = "New Project") -> str:
    """Pull a usable name out of a plain-language request.

    Small on purpose. Overreaching here produces a confidently wrong project
    name, and the caller can always pass one.
    """
    match = _TITLE.search(request)
    if not match:
        return fallback
    title = re.split(r"[,.]| and | then ", match.group(1))[0].strip()
    return " ".join(word.capitalize() for word in title.split()) or fallback


class RegenerateRepairer:
    """Repairs a failing project by regenerating it from the plan's inputs.

    Deterministic, and effective against the failure that actually happens: a
    project whose files were corrupted, truncated or hand-edited into something
    that no longer passes its own tests. Regenerating from the recorded inputs
    restores a known-good state, and the test then re-runs and proves it.

    It cannot repair a *bad specification* — if the generated code is wrong by
    design, regenerating produces the same wrong code, so it returns nothing
    after the first attempt rather than looping. A model-driven repairer is the
    natural upgrade and registers in the same place; it needs a credential that
    the server does not have.
    """

    def __init__(self) -> None:
        self.attempts = 0

    def repair(self, step: PlanStep, record: ActionRecord, ctx: ExecutionContext) -> list[PlanStep]:
        # Only a failing command is repairable this way; a browser or deploy
        # failure means something outside the workspace is wrong.
        if step.action != CODE_EXECUTE or self.attempts >= 1:
            return []
        generated = ctx.outputs.get("generate", {}).get("files")
        if not generated:
            return []
        self.attempts += 1
        return [
            PlanStep(
                id=f"repair-{step.id}-{self.attempts}",
                description=f"Regenerate the project after: {record.error[:80]}",
                capability=CODE_WRITE,
                action=CODE_WRITE,
                payload={"files": generated},
                expected_output="The generated files restored",
            )
        ]
