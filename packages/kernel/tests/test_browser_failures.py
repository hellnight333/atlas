"""Whose fault was it that the page did not load?

Seven of sixty audited businesses were recorded `reachable=False` because our
own browser interrupted its own navigation — including two large retailers
whose sites plainly work. Each was then dropped from the funnel for a defect
that was ours.
"""

from __future__ import annotations

import pytest

from atlas_kernel.browser.failures import ours, reachability


class TestFailuresThatAreOurs:
    @pytest.mark.parametrize("error", [
        'Page.goto: Navigation to "https://a.test/" is interrupted by another '
        'navigation to "https://b.test/"',
        "Target page, context or browser has been closed",
        "Execution context was destroyed, most likely because of a navigation",
        "Protocol error (Page.navigate): Session closed",
        "Cannot allocate memory",
    ])
    def test_they_are_recognised(self, error: str) -> None:
        assert ours(error) != ""

    def test_the_reason_is_written_for_a_person(self) -> None:
        because = ours('Navigation to "x" is interrupted by another navigation')

        assert "our browser" in because

    def test_reachability_is_not_established_rather_than_false(self) -> None:
        """The distinction the whole module exists for. A site we could not
        check is not a site that is down."""
        answered, because = reachability(
            'Navigation to "x" is interrupted by another navigation to "y"')

        assert answered is None
        assert answered is not False, "None and False are different claims"
        assert because


class TestFailuresThatAreTheirs:
    @pytest.mark.parametrize("error", [
        "net::ERR_NAME_NOT_RESOLVED at https://nope.test/",
        "net::ERR_CONNECTION_REFUSED",
        "net::ERR_CERT_DATE_INVALID",
        "Timeout 30000ms exceeded",
        "net::ERR_ABORTED",
    ])
    def test_they_stay_a_finding_about_the_site(self, error: str) -> None:
        """Conservative on purpose. Being wrong this way costs an audit; being
        wrong the other way tells a business their site is down when it is
        not."""
        assert ours(error) == ""
        answered, _ = reachability(error)
        assert answered is False

    def test_an_empty_error_is_not_claimed_as_ours(self) -> None:
        assert ours("") == ""
        assert reachability("")[0] is False


def test_the_audit_records_which_it_was() -> None:
    """Structural: the classifier is useless if the audit still writes False
    for everything."""
    from pathlib import Path

    script = (Path(__file__).resolve().parents[3]
              / "infra" / "audit_discovered.py").read_text(encoding="utf-8")

    assert "from atlas_kernel.browser.failures import reachability" in script
    assert "reachable=answered" in script
    assert "check_failed_because" in script
    assert "reachable=False," not in script, (
        "the audit still hard-codes a claim that the site did not answer")
