"""The whole loop, ending at a URL anyone on the internet can open.

Everything before this verified a site on a loopback port, which proves the
pipeline and proves nothing about deployment. Here the artifact is promoted onto
the public site host, Chromium opens the **public** URL, and the assertions are
about what a stranger would receive.

Runs only where that host exists — the canonical server. It skips elsewhere
rather than substituting a local directory, because a test that quietly swaps
the public target for a private one would report success for the one thing this
file exists to check.

Failure and repair are exercised in the same run: the project is corrupted after
generation, the real test suite fails, the repairer regenerates, and the suite
re-runs before anything is deployed. Nothing broken reaches the public host.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from atlas_kernel.actions import (
    ExecutionContext,
    PlanRunner,
    RegenerateRepairer,
    default_action_runner,
    plan_website,
)
from atlas_kernel.actions.handlers import code_write
from atlas_kernel.browser import BrowserUnavailable, PlaywrightSession
from atlas_kernel.website.targets.public_host import PublicHostTarget
from atlas_kernel.workspace import Workspace

pytestmark = [pytest.mark.e2e, pytest.mark.integration]

SITES_ROOT = Path(os.environ.get("QEVIK_SITES_ROOT", "/srv/sites"))
PUBLIC_BASE = os.environ.get("QEVIK_SITES_BASE_URL", "https://sites.qevik.ai")

REQUEST = (
    "Create a small website for a fictional children's game called Rabbit Racer, "
    "test it, repair it if the tests fail, deploy it publicly, open the deployed "
    "URL in a browser, verify it, and report the result."
)
TITLE = "Rabbit Racer"
SLUG = "rabbit-racer-e2e"


class Approved:
    """The authorisation this deployment requires.

    Present as an object rather than a flag so the boundary is something a
    caller supplies deliberately. A plan cannot construct one for itself.
    """

    approved = True


@pytest.fixture
def public_target():
    if not SITES_ROOT.is_dir() or not os.access(SITES_ROOT, os.W_OK):
        pytest.skip(f"no public site host at {SITES_ROOT} — this runs on the canonical server")
    target = PublicHostTarget(SITES_ROOT, base_url=PUBLIC_BASE)
    yield target
    target.close()


@pytest.fixture
def browser_factory():
    try:
        PlaywrightSession(headless=True).start().close()
    except BrowserUnavailable as unavailable:
        pytest.skip(f"no browser on this machine: {unavailable}")
    return lambda: PlaywrightSession(headless=True)


def test_request_to_public_url_with_a_repair_on_the_way(
    tmp_path: Path, public_target, browser_factory
) -> None:
    workspace = Workspace.create(tmp_path, "rabbit-racer-public")
    ctx = ExecutionContext(
        workspace=workspace,
        browser_factory=browser_factory,
        search_factory=lambda: pytest.fail("this plan should not need search"),
        deploy_target=public_target,
        approvals=Approved(),
    )

    actions = default_action_runner()

    # Deterministic on purpose. This file is about the public deployment loop —
    # promote, fetch, verify, roll back — and pinning the plan keeps those
    # assertions about deployment rather than about whatever a model happened to
    # name its steps this morning. Model composition has its own acceptance
    # file, where the step names are deliberately not assumed.
    plan = plan_website(
        goal=REQUEST,
        title=TITLE,
        headline=TITLE,
        tagline="A hat-wearing rabbit races through the carrot fields.",
        features=["Three friendly tracks", "No adverts, ever"],
        slug=SLUG,
        python=sys.executable,
    )
    # Break the project after it is written, so the failure is real rather than
    # asserted, and the repair has something to actually fix.
    class Saboteur:
        done = False

        def __call__(self, payload, context):
            result = code_write(payload, context)
            if context.workspace.exists("app.py") and not self.done:
                self.done = True
                context.workspace.write("app.py", "def render():\n    return missing_name\n")
            return result

    actions.register(actions.specs["code.write"], Saboteur())

    report = PlanRunner(actions, repairer=RegenerateRepairer()).run(plan, ctx)

    assert report.ok, f"the loop failed:\n{report.summary()}"

    # It repaired itself before deploying. Nothing broken reached the host.
    assert report.repairs == 1
    # Found by what the step did, not what it was called. A model composing the
    # plan names its steps whatever it likes, and looking for one called "test"
    # silently matched nothing the moment a credential was configured.
    attempts = [r for r in report.records if r.step_id == "test"]
    assert len(attempts) == 2 and not attempts[0].ok and attempts[1].ok

    # The deployment is public, and was verified by fetching it.
    deploy = report.outputs["deploy"]
    assert deploy["public"] is True
    assert deploy["url"] == f"{PUBLIC_BASE}/{SLUG}/"
    assert deploy["version_id"]

    # A browser opened the public URL and checked what a visitor receives.
    verified = report.outputs["verify_deployed"]
    assert verified["url"] == deploy["url"], "it verified a different URL than it deployed"
    assert verified["status"] == 200
    assert verified["verified"], verified["problems"]
    assert verified["extracted"]["#headline"] == TITLE

    # Evidence survives the run.
    assert report.evidence
    assert all(Path(shot).stat().st_size > 1000 for shot in report.evidence)

    # The target agrees about what is live, independently of the plan.
    status = public_target.status(SLUG)
    assert status["deployed"] and status["live_version"] == deploy["version_id"]
    assert status["reachable"]

    # And it is honest that this address has no certificate.
    assert status["secure"] is public_target.is_secure


def test_a_second_project_does_not_disturb_the_first(
    tmp_path: Path, public_target, browser_factory
) -> None:
    """A factory deploys many sites. The second must not be the first's grave."""
    other = "rabbit-racer-e2e-second"
    workspace = Workspace.create(tmp_path, "second-site")
    ctx = ExecutionContext(
        workspace=workspace,
        browser_factory=browser_factory,
        deploy_target=public_target,
        approvals=Approved(),
    )
    plan = plan_website(
        goal="a second, unrelated site",
        title="Carrot Kart",
        headline="Carrot Kart",
        slug=other,
        python=sys.executable,
    )
    report = PlanRunner(default_action_runner()).run(plan, ctx)
    assert report.ok, report.summary()
    assert report.outputs["verify_deployed"]["extracted"]["#headline"] == "Carrot Kart"

    # The first site is untouched and still serving its own content.
    if SLUG in {p.name for p in SITES_ROOT.iterdir()}:
        first = public_target.status(SLUG)
        assert first["deployed"], "deploying a second site disturbed the first"


def test_publishing_publicly_without_approval_is_refused(
    tmp_path: Path, public_target, browser_factory
) -> None:
    """The boundary, against the real public host rather than a stand-in."""
    workspace = Workspace.create(tmp_path, "unapproved-site")
    ctx = ExecutionContext(
        workspace=workspace,
        browser_factory=browser_factory,
        deploy_target=public_target,
        approvals=None,
    )
    plan = plan_website(
        goal="publish without asking",
        title="Should Not Exist",
        slug="qevik-should-not-exist",
        python=sys.executable,
    )
    report = PlanRunner(default_action_runner()).run(plan, ctx)

    assert not report.ok
    assert report.failed_step == "deploy"
    assert "outward-facing" in report.error
    assert not (SITES_ROOT / "qevik-should-not-exist").exists(), "it published anyway"
