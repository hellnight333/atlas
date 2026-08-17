"""Browser execution — the interface, not the runtime.

Playwright itself is exercised live on the server; these defend the contract
that keeps it replaceable, and the authorisation model that keeps it safe.

The important one is ``allowed_actions``. §21 asks for per-task authorisation,
and the failure it prevents is specific: a planner that decides a research crawl
should log in somewhere. Least privilege stated per job rather than per profile.
"""

from __future__ import annotations

import pytest

from atlas_kernel.browser.models import (
    BROWSER_OPERATE,
    BrowserJob,
    BrowserJobStatus,
    BrowserProfile,
    ElementRef,
    PageSnapshot,
    Screenshot,
)
from atlas_kernel.browser.session import BrowserSession, BrowserUnavailable, PlaywrightSession


class TestTheInterfaceIsQeviksNotPlaywrights:
    def test_the_playwright_backend_satisfies_the_protocol(self) -> None:
        assert isinstance(PlaywrightSession(), BrowserSession)

    def test_a_second_backend_needs_only_the_protocol(self) -> None:
        """What makes the runtime replaceable — a remote browser service, an
        Iran worker, or another agent framework registers the same way."""

        class Remote:
            def open(self, url):
                return PageSnapshot(url=url, status=200)

            def snapshot(self):
                return PageSnapshot(url="about:blank")

            def click(self, ref):
                return PageSnapshot(url="about:blank")

            def type(self, ref, text):
                return PageSnapshot(url="about:blank")

            def extract(self, expression):
                return None

            def screenshot(self, path, *, full_page=True):
                return Screenshot(url="", path=str(path))

            def close(self): ...

        assert isinstance(Remote(), BrowserSession)

    def test_there_is_no_do_the_task_method(self) -> None:
        """Qevik plans; the browser performs named steps. A second autonomous
        loop inside a step makes failure unattributable and cost unbounded."""
        for forbidden in ("do_task", "run_objective", "autonomous", "agent"):
            assert not hasattr(PlaywrightSession(), forbidden)

    def test_a_missing_runtime_is_a_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Distinct from a page failing, because the fix is entirely different.

        The absence is simulated rather than inherited from the machine. An
        earlier version skipped when playwright was importable, which meant the
        test asserted nothing on the server — where playwright is installed —
        and asserted everything on a laptop where it is not. A test whose
        meaning depends on what happens to be installed is the one nobody
        investigates when it breaks.
        """
        import sys

        # `from playwright.sync_api import ...` raises ImportError when the
        # entry is None, which is exactly what an uninstalled runtime does.
        monkeypatch.setitem(sys.modules, "playwright", None)
        monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
        with pytest.raises(BrowserUnavailable, match="playwright install"):
            PlaywrightSession().start()

    def test_acting_before_starting_says_so(self) -> None:
        with pytest.raises(Exception, match="not started"):
            PlaywrightSession().snapshot()


class TestAuthorisation:
    def test_a_research_job_cannot_type_by_default(self) -> None:
        """The failure this prevents: a planner deciding a crawl should log in."""
        job = BrowserJob(target_url="https://x.test", objective="crawl")
        assert job.permits("open") and job.permits("screenshot")
        assert not job.permits("type")
        assert not job.permits("click")

    def test_permissions_are_per_job_not_per_profile(self) -> None:
        job = BrowserJob(
            target_url="https://x.test",
            objective="fill a form",
            allowed_actions=["open", "snapshot", "click", "type"],
        )
        assert job.permits("type")

    def test_research_is_the_default_profile(self) -> None:
        """The one carrying no credentials. Choosing the operational profile
        should be a decision someone made, not a default they inherited."""
        assert BrowserJob().profile is BrowserProfile.RESEARCH

    def test_both_profiles_exist_and_are_distinct(self) -> None:
        assert BrowserProfile.RESEARCH != BrowserProfile.OPERATIONAL


class TestSnapshots:
    def test_a_snapshot_knows_whether_the_page_worked(self) -> None:
        assert PageSnapshot(url="https://x.test", status=200).ok
        assert not PageSnapshot(url="https://x.test", status=500).ok
        assert not PageSnapshot(url="https://x.test", status=None).ok

    def test_console_errors_are_carried_as_evidence(self) -> None:
        """§17 asks for them, and they separate "the page loaded" from "the
        page works"."""
        snap = PageSnapshot(
            url="https://x.test", status=200, console_errors=["error: undefined is not a function"]
        )
        assert snap.ok
        assert snap.console_errors

    def test_elements_say_whether_they_accept_input(self) -> None:
        """So a caller can tell a button from a text field without guessing
        from the name."""
        assert ElementRef(ref="#email", role="input", name="Email", editable=True).editable
        assert not ElementRef(ref="#go", role="button", name="Search").editable


class TestJobLifecycle:
    def test_the_statuses_match_the_specification(self) -> None:
        for expected in (
            "queued",
            "running",
            "waiting_for_approval",
            "blocked",
            "failed",
            "completed",
            "cancelled",
        ):
            assert expected in {s.value for s in BrowserJobStatus}

    def test_a_job_belongs_to_a_run_rather_than_a_parallel_system(self) -> None:
        """Browser work appears in the same history as everything else."""
        assert "run_id" in BrowserJob.model_fields

    def test_the_capability_is_named_not_the_runtime(self) -> None:
        assert BROWSER_OPERATE == "browser.operate"
        assert "playwright" not in BROWSER_OPERATE
