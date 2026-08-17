"""The acceptance test, run through the orchestrator rather than around it.

> "Create a small website for a fictional children's game, test it, run it
> locally, open it in Chromium, verify the rendered page, deploy it, open the
> deployed result with the browser, verify the deployed page, and return the URL
> and execution report."

The distinction this file exists to make: **no step is performed here.** The
request goes to the planner, the planner composes a plan, and `PlanRunner`
executes it. The test asserts on the report the runner produces. If the wiring
were fake — if the actions were stubs, or the outputs did not flow between steps
— every assertion below would fail, because the deployed URL that Chromium opens
is produced by the deploy step and consumed by the verification step without the
test ever seeing it.

Requires Chromium. Skips where it is absent, which on a laptop is honest and on
the canonical server never happens.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from atlas_kernel.actions import (
    ActionRecord,
    ExecutionContext,
    PlanRunner,
    PublishNotAuthorised,
    RegenerateRepairer,
    default_action_runner,
    plan_website,
)
from atlas_kernel.browser import BrowserUnavailable, PlaywrightSession
from atlas_kernel.website.targets.local import LocalDirectoryTarget
from atlas_kernel.workspace import Workspace, free_port

pytestmark = [pytest.mark.e2e, pytest.mark.integration]

REQUEST = (
    "Create a small website for a fictional children's game, test it, run it locally, "
    "open it in Chromium, verify the rendered page, deploy it, open the deployed result "
    "with the browser, verify the deployed page, and return the URL and execution report."
)

#: The server-side half of publish-then-promote, exactly as production does it.
#: `infra/atlas-sites.Caddyfile` rewrites `/{slug}/` to `/{slug}/current/`,
#: because a site directory holds `versions/` and a `current` symlink and the
#: web server is what decides which version is live. `promote()` returns
#: `/{slug}/` on that understanding, so a plain static server would 404 —
#: the fronting server is wrong in that case, not the deployment contract.
FRONT_SERVER = """import re, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial

SITE_ROOT = re.compile(r"^/([^/]+)/?$")


class Front(SimpleHTTPRequestHandler):
    def do_GET(self):
        match = SITE_ROOT.match(self.path)
        if match:
            self.path = f"/{match.group(1)}/current/"
        return super().do_GET()

    def log_message(self, *args):
        pass


ThreadingHTTPServer(
    ("127.0.0.1", int(sys.argv[1])),
    partial(Front, directory=sys.argv[2]),
).serve_forever()
"""

TITLE = "Rabbit Racer"
HEADLINE = "Rabbit Racer"
TAGLINE = "A hat-wearing rabbit races through the carrot fields."
FEATURES = ["Three friendly tracks", "No adverts, ever", "Playable in one tap"]


class StubSearch:
    """Stands in for Brave so the acceptance test does not spend money or
    depend on the network. The real client is exercised against the live API
    elsewhere; what this test proves is the *composition*, and paying five
    thousandths of a dollar per run to re-prove Brave would be a worse test, not
    a better one."""

    def search(self, query):
        from atlas_kernel.research.models import SearchResult, SearchResults

        return SearchResults(
            query=query.text,
            provider="stub",
            requests_made=1,
            approx_cost_usd=0.0,
            results=[
                SearchResult(
                    url="https://example.com/kids-game-design",
                    title="Designing games for young children",
                    description="Short sessions, forgiving controls, no dark patterns.",
                )
            ],
        )


@pytest.fixture
def browser_factory():
    try:
        PlaywrightSession(headless=True).start().close()
    except BrowserUnavailable as unavailable:
        pytest.skip(f"no browser on this machine: {unavailable}")
    return lambda: PlaywrightSession(headless=True)


def _context(tmp_path: Path, browser_factory, *, approvals=None, name="rabbit-racer"):
    workspace = Workspace.create(tmp_path / "projects", name)
    target = LocalDirectoryTarget(
        tmp_path / "published", base_url="http://127.0.0.1:0", name="local"
    )
    return (
        workspace,
        target,
        ExecutionContext(
            workspace=workspace,
            browser_factory=browser_factory,
            search_factory=StubSearch,
            deploy_target=target,
            approvals=approvals,
        ),
    )


def test_the_full_autonomous_workflow(tmp_path: Path, browser_factory) -> None:
    workspace, target, _ = _context(tmp_path, browser_factory)

    # The deployed site has to be reachable over HTTP for the browser to verify
    # it, so the target's base_url is the port we are about to serve its root on.
    deploy_port = free_port()
    target._base_url = f"http://127.0.0.1:{deploy_port}"
    local_port = free_port()

    ctx = ExecutionContext(
        workspace=workspace,
        browser_factory=browser_factory,
        search_factory=StubSearch,
        deploy_target=target,
    )

    # The request becomes a plan. Nothing below names a step.
    plan = plan_website(
        goal=REQUEST,
        title=TITLE,
        headline=HEADLINE,
        tagline=TAGLINE,
        features=FEATURES,
        research_query="design principles for children's browser games",
        slug="rabbit-racer",
        python=sys.executable,
        serve_url=f"http://127.0.0.1:{local_port}/",
    )
    assert [s.id for s in plan.steps] == [
        "research",
        "generate",
        "write",
        "test",
        "build",
        "verify_local",
        "deploy",
        "verify_deployed",
    ]

    runner = PlanRunner(default_action_runner(), repairer=RegenerateRepairer())

    # Two servers run for the duration: the project's own local server, and one
    # in front of the deployment root so the deployed URL resolves.
    target.root.mkdir(parents=True, exist_ok=True)
    serve_local = [sys.executable, "-m", "http.server", str(local_port), "--bind", "127.0.0.1"]
    front = workspace.root / "_front_server.py"
    front.write_text(FRONT_SERVER, encoding="utf-8")
    serve_deployed = [sys.executable, str(front), str(deploy_port), str(target.root)]

    # The local server must serve dist/, which the build step has not created
    # yet — so it is started from the workspace root and the plan points at
    # /dist/. Adjusting the plan, not the assertions.
    plan.steps[5].payload["url"] = f"http://127.0.0.1:{local_port}/dist/"

    with workspace.serve(serve_local, port=local_port):
        with workspace.serve(serve_deployed, port=deploy_port):
            report = runner.run(plan, ctx)

    assert report.ok, f"the workflow failed:\n{report.summary()}"
    assert report.steps_total == 8
    assert report.steps_succeeded == 8

    # Every step ran, in dependency order, and was recorded.
    assert [r.step_id for r in report.records] == [s.id for s in plan.steps]
    assert all(isinstance(r, ActionRecord) for r in report.records)

    # The composition is real: the deploy step produced a URL the test never
    # supplied, and the verification step opened exactly that URL.
    deployed_url = report.outputs["deploy"]["url"]
    assert deployed_url.startswith(f"http://127.0.0.1:{deploy_port}/rabbit-racer")
    assert report.outputs["verify_deployed"]["url"] == deployed_url

    # Verification is what a visitor received, not what the generator intended.
    for step in ("verify_local", "verify_deployed"):
        verified = report.outputs[step]
        assert verified["status"] == 200, f"{step}: {verified}"
        assert verified["verified"], f"{step}: {verified['problems']}"
        assert TITLE in verified["title"]
        assert verified["extracted"]["#headline"] == HEADLINE

    # Command execution kept stdout, exit status and duration.
    tests = report.outputs["test"]
    assert tests["exit_code"] == 0
    assert "passed" in tests["stdout"]
    assert report.outputs["build"]["ok"]

    # Research kept its provenance.
    assert report.outputs["research"]["sources"][0]["url"].startswith("https://")

    # Browser evidence survives the run.
    assert len(report.evidence) == 2
    for shot in report.evidence:
        assert Path(shot).stat().st_size > 1000, "a screenshot of nothing is not evidence"

    # And the report reads as a report.
    assert "SUCCEEDED" in report.summary()


def test_the_workflow_diagnoses_a_failure_and_repairs_itself(
    tmp_path: Path, browser_factory
) -> None:
    """Failure and recovery, not the happy path.

    The project is corrupted after generation. The test step fails for real,
    the repairer regenerates from the plan's own inputs, and the test step is
    re-run and passes — all inside the runner, with no intervention.
    """
    workspace, target, ctx = _context(tmp_path, browser_factory, name="broken-site")

    plan = plan_website(
        goal="build a site that will be broken before its tests run",
        title=TITLE,
        headline=HEADLINE,
        python=sys.executable,
        deploy=False,
    )

    # Corrupt the project between `write` and `test` by making the write step
    # emit something that cannot pass its own suite.
    class Saboteur:
        def __init__(self, inner):
            self.inner = inner

        def __call__(self, payload, context):
            result = self.inner(payload, context)
            if context.workspace.exists("app.py") and not getattr(self, "done", False):
                self.done = True
                context.workspace.write("app.py", "def render():\n    return undefined_name\n")
            return result

    actions = default_action_runner()
    from atlas_kernel.actions.handlers import code_write

    actions.register(actions.specs["code.write"], Saboteur(code_write))

    report = PlanRunner(actions, repairer=RegenerateRepairer()).run(plan, ctx)

    assert report.ok, f"the workflow did not recover:\n{report.summary()}"
    assert report.repairs == 1, "nothing was repaired"

    # The evidence of a real recovery: the test step failed, then ran again.
    test_records = [r for r in report.records if r.step_id == "test"]
    assert len(test_records) == 2
    assert not test_records[0].ok
    # The corruption removes the names the suite imports, so pytest fails during
    # collection rather than at runtime. Asserting the *category* rather than a
    # specific exception keeps this honest: what matters is that a real failure
    # was captured with its output, not which one it happened to be.
    first = test_records[0].output
    assert first["exit_code"] != 0
    assert "ERROR" in first["stdout"], "the failure output was not preserved"
    assert first["stderr"] is not None
    assert test_records[1].ok
    assert test_records[1].attempt == 2
    assert "repair(s)" in report.summary()

    # And the repair itself is in the lineage, between the two attempts.
    repair_records = [r for r in report.records if r.step_id.startswith("repair-")]
    assert len(repair_records) == 1 and repair_records[0].ok


def test_an_outward_facing_publish_is_refused_without_authorisation(
    tmp_path: Path, browser_factory
) -> None:
    """The authorisation boundary, exercised rather than described.

    A plan must not be able to publish to somewhere strangers can reach simply
    by composing steps.
    """
    workspace, target, ctx = _context(tmp_path, browser_factory, name="public-site")
    target.is_public = True  # a host the public can reach

    plan = plan_website(
        goal="publish publicly without asking",
        title=TITLE,
        headline=HEADLINE,
        python=sys.executable,
        slug="public-site",
    )
    report = PlanRunner(default_action_runner()).run(plan, ctx)

    assert not report.ok
    assert report.failed_step == "deploy"
    assert "outward-facing" in report.error
    assert "verify_deployed" not in report.outputs, "it verified something it never published"


def test_authorised_publishing_proceeds(tmp_path: Path, browser_factory) -> None:
    """The same plan, with an approval present, publishes."""

    class Approved:
        approved = True

    workspace, target, ctx = _context(
        tmp_path, browser_factory, approvals=Approved(), name="approved-site"
    )
    target.is_public = True

    plan = plan_website(
        goal="publish with approval",
        title=TITLE,
        headline=HEADLINE,
        python=sys.executable,
        slug="approved-site",
        deploy=True,
    )
    # Stop before browser verification; this test is about the boundary.
    plan.steps = [s for s in plan.steps if s.id != "verify_deployed"]

    report = PlanRunner(default_action_runner()).run(plan, ctx)
    assert report.ok, report.summary()
    assert report.outputs["deploy"]["public"] is True
    assert report.outputs["deploy"]["promoted"]


def test_a_refusal_is_never_retried_as_a_failure(tmp_path: Path, browser_factory) -> None:
    """A policy refusal and a broken build are different things, and repairing a
    refusal would mean trying to publish repeatedly without permission."""
    workspace, target, ctx = _context(tmp_path, browser_factory, name="refused-site")
    target.is_public = True

    plan = plan_website(
        goal="refusals are not repaired",
        title=TITLE,
        python=sys.executable,
        slug="refused-site",
    )
    repairer = RegenerateRepairer()
    report = PlanRunner(default_action_runner(), repairer=repairer).run(plan, ctx)

    assert not report.ok
    deploys = [r for r in report.records if r.step_id == "deploy"]
    assert len(deploys) == 1, "the refusal was retried"
    assert issubclass(PublishNotAuthorised, Exception)
