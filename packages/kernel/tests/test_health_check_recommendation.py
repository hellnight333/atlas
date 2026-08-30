"""The health check as the first action for an evidenced weak web presence.

A product decision taken by the owner on 2026-08-30: a rebuild asserts Qevik
knows what a business needs; a health check asserts only what an audit observed.
The second can honestly be offered to a stranger on the strength of a scan.

What these tests defend is the word *evidenced*. "Every weak website" is not the
rule, and the failure each gate prevents has a business on the other end of it.
"""

from __future__ import annotations

from atlas_kernel.opportunity.detect import (
    HEALTH_CHECK_OFFER,
    WEBSITE_OFFER,
    WORTH_RAISING,
    health_check_ready,
    weak_web_presence,
)
from atlas_kernel.opportunity.models import (
    Business,
    Evidence,
    Finding,
    FindingKind,
    Severity,
)
from atlas_kernel.opportunity.signals import Reach


def _evidence(note: str = "the server answered") -> Evidence:
    return Evidence(kind="http_response", statement=note, source="fetcher",
                    detail={"status": 200})


def _finding(kind: FindingKind, severity: Severity = Severity.HIGH) -> Finding:
    return Finding(business_id="biz-1", kind=kind, severity=severity,
                   statement=str(kind.value), confidence=0.9,
                   evidence=[_evidence()])


def _business() -> Business:
    return Business(name="Example Clinic", website="https://example.test/",
                    geography="Dubai")


def _signal(findings):
    return weak_web_presence(_business(), findings, _evidence(), source="audit")


class TestWhenAHealthCheckMayBeOffered:
    def test_an_evidenced_weak_site_is_offered_one(self) -> None:
        signal = _signal([_finding(FindingKind.MISSING_TITLE),
                          _finding(FindingKind.MISSING_H1)])

        action = signal.actions[0]
        assert action.capability == HEALTH_CHECK_OFFER
        assert action.reach is Reach.OUTWARD
        assert action.needs_approval is True, (
            "approaching a business is not undoable and no audit result may "
            "make it automatic")

    def test_a_site_that_never_answered_is_not_offered_one(self) -> None:
        """No page was read, so there is nothing to report. A health check built
        from that is a bounce notice with a logo on it."""
        assert health_check_ready([
            _finding(FindingKind.SITE_UNREACHABLE),
            _finding(FindingKind.MISSING_TITLE)]) is False

    def test_a_single_light_defect_is_not_enough(self) -> None:
        """The same bar `WORTH_RAISING` already sets for raising an opportunity
        at all. A diagnostic reporting one missing meta description makes the
        next one easier to ignore."""
        assert health_check_ready(
            [_finding(FindingKind.MISSING_META_DESCRIPTION, Severity.LOW)]) is False

    def test_nothing_observed_offers_nothing(self) -> None:
        assert health_check_ready([]) is False

    def test_it_refuses_when_no_executor_exists(self, monkeypatch) -> None:
        """Offering work nothing can carry out is what `executable` exists to
        prevent — the arabic-experience offer is why."""
        import atlas_kernel.opportunity.detect as detect

        monkeypatch.setattr(detect, "executable", lambda offer: False)

        assert detect.health_check_ready(
            [_finding(FindingKind.MISSING_TITLE),
             _finding(FindingKind.MISSING_H1)]) is False


class TestWhatTheRecommendationSays:
    def test_it_does_not_promise_a_rebuild(self) -> None:
        """The health check is a diagnostic. A statement that sold a rebuild
        would be asserting Qevik knows what they need from a scan."""
        signal = _signal([_finding(FindingKind.MISSING_TITLE),
                          _finding(FindingKind.MISSING_H1)])

        statement = signal.actions[0].statement
        assert "health check" in statement.lower()
        assert "reports only what was observed" in statement

    def test_it_says_what_a_rebuild_would_answer_where_one_would(self) -> None:
        """The operator is deciding whether to approach the business. What
        Qevik could go on to do for them is part of that decision."""
        signal = _signal([_finding(FindingKind.THIN_CONTENT),
                          _finding(FindingKind.MISSING_TITLE)])

        assert "A rebuild would answer" in signal.actions[0].statement

    def test_it_makes_no_claim_about_the_business_performance(self) -> None:
        """The guardrail the whole engine rests on."""
        signal = _signal([_finding(FindingKind.MISSING_TITLE),
                          _finding(FindingKind.MISSING_H1)])

        statement = signal.actions[0].statement.lower()
        for unsupported in ("revenue", "customers", "patients", "ranking",
                            "traffic", "more leads", "lose"):
            assert unsupported not in statement, unsupported


class TestTheRebuildOfferIsNotReplaced:
    def test_it_is_still_the_offer_when_a_health_check_cannot_be_built(
            self, monkeypatch) -> None:
        """A first action, not a replacement. If the health check cannot be
        offered but a rebuild answers the defects, the rebuild is still what
        the opportunity suggests."""
        import atlas_kernel.opportunity.detect as detect

        monkeypatch.setattr(detect, "health_check_ready", lambda _f: False)
        signal = _signal([_finding(FindingKind.THIN_CONTENT),
                          _finding(FindingKind.MISSING_TITLE)])

        assert signal.actions[0].capability == WEBSITE_OFFER

    def test_the_offer_catalogue_still_holds_both(self) -> None:
        from atlas_kernel.recommendation.offers import BY_ID

        assert BY_ID[WEBSITE_OFFER] is not None
        assert BY_ID[HEALTH_CHECK_OFFER] is not None


def test_the_bar_is_the_one_already_written_down() -> None:
    """`WORTH_RAISING` is where this number lives. A second threshold for the
    same judgement is a second thing to move when reply rates come back."""
    import ast
    import inspect

    import atlas_kernel.opportunity.detect as detect

    source = inspect.getsource(detect.health_check_ready)
    # `bool` is a subclass of `int`, so `False` counts as a number without this.
    numbers = {n.value for n in ast.walk(ast.parse(source))
               if isinstance(n, ast.Constant)
               and isinstance(n.value, int) and not isinstance(n.value, bool)}

    assert not numbers, (
        f"health_check_ready hard-codes {numbers}; the bar is WORTH_RAISING")
    assert WORTH_RAISING == 2
