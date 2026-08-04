"""Autonomous, multi-source discovery and confidence scoring (M014).

Two additions that only matter once discovery stops being a list somebody typed.

**Multi-source.** Several sources report overlapping businesses, one of them is
down, and the run has to produce a coherent, deduplicated result that is honest
about what it could not reach. A run that quietly covered half the sources looks
identical to a clean one unless it says otherwise.

**Confidence.** Not every observation deserves the same weight. Reading a missing
``<title>`` out of the markup is near-certain; calling a site slow from a single
timing sample is a guess with a network in the way. The floor exists so weak
signals cannot sum their way past the qualification bar and arrive at a business
owner stated as fact.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_kernel.opportunity.detectors.base import DetectorRegistry, DiscoveryResult
from atlas_kernel.opportunity.detectors.website import (
    DIRECT_MARKUP_CONFIDENCE,
    SINGLE_SAMPLE_TIMING_CONFIDENCE,
    SLOW_RESPONSE_SECONDS,
    SOURCE_RECORD_CONFIDENCE,
    WebsiteDetector,
)
from atlas_kernel.opportunity.models import (
    Business,
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    OpportunityStage,
    Severity,
)
from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE
from atlas_kernel.opportunity.qualification import applicable_findings, qualify, score
from atlas_kernel.opportunity.sources import SeedListSource

BARE_PAGE = "<html><body><p>Coming soon</p></body></html>"


class FixedSource:
    """A source that returns exactly what it was given."""

    def __init__(self, label: str, businesses: list[Business]) -> None:
        self._label = label
        self._businesses = businesses

    @property
    def name(self) -> str:
        return self._label

    def discover(self, profile, limit):
        return [b.model_copy(update={"sources": [self._label]}) for b in self._businesses[:limit]]


class BrokenSource:
    name = "broken"

    def discover(self, profile, limit):
        raise RuntimeError("rate limited")


def _business(name: str, website: str | None, email: str | None = None) -> Business:
    return Business(name=name, geography="Dubai", website=website, email=email)


class TestMultiSourceDiscovery:
    def test_two_sources_finding_the_same_business_produce_one_record(self) -> None:
        """The normal case once discovery is autonomous, not an edge case. An
        unresolved duplicate is inspected twice, counted twice, contacted twice."""
        registry = DetectorRegistry()
        registry.register_source(
            FixedSource("google-maps", [_business("Al Noor Dental Clinic", "https://alnoor.ae")])
        )
        registry.register_source(
            FixedSource("directory", [_business("AL NOOR DENTAL CLINIC LLC", "www.alnoor.ae")])
        )

        result = registry.discover(EXAMPLE_PROFILE, limit=10)

        assert len(result.businesses) == 1
        assert result.duplicates_merged == 1
        assert result.businesses[0].sources == ["google-maps", "directory"]

    def test_different_businesses_from_different_sources_are_all_kept(self) -> None:
        registry = DetectorRegistry()
        registry.register_source(
            FixedSource("maps", [_business("Al Noor Dental", "https://alnoor.ae")])
        )
        registry.register_source(
            FixedSource("directory", [_business("Jumeirah Garage", "https://garage.ae")])
        )
        assert len(registry.discover(EXAMPLE_PROFILE, limit=10).businesses) == 2

    def test_a_failing_source_does_not_end_the_run(self) -> None:
        """Four sources with one rate-limited should return three sources'
        worth of businesses, not an exception."""
        registry = DetectorRegistry()
        registry.register_source(BrokenSource())
        registry.register_source(
            FixedSource("working", [_business("Al Noor Dental", "https://alnoor.ae")])
        )

        result = registry.discover(EXAMPLE_PROFILE, limit=10)

        assert len(result.businesses) == 1
        assert result.source_failures == {"broken": "rate limited"}

    def test_a_degraded_run_says_so_rather_than_looking_clean(self) -> None:
        registry = DetectorRegistry()
        registry.register_source(BrokenSource())
        registry.register_source(
            FixedSource("working", [_business("Al Noor", "https://alnoor.ae")])
        )
        assert registry.discover(EXAMPLE_PROFILE, limit=10).source_failures

    def test_lookalikes_are_reported_for_a_human_and_not_merged(self) -> None:
        registry = DetectorRegistry()
        registry.register_source(
            FixedSource(
                "maps",
                [
                    _business("Al Noor Clinic", "https://alnoor-jumeirah.ae"),
                    _business("Al Noor Clinic", "https://alnoor-marina.ae"),
                ],
            )
        )
        result = registry.discover(EXAMPLE_PROFILE, limit=10)
        assert len(result.businesses) == 2
        assert len(result.possible_duplicates) == 1

    def test_the_limit_is_honoured_across_sources(self) -> None:
        registry = DetectorRegistry()
        registry.register_source(
            FixedSource("a", [_business(f"A{i}", f"https://a{i}.ae") for i in range(5)])
        )
        registry.register_source(
            FixedSource("b", [_business(f"B{i}", f"https://b{i}.ae") for i in range(5)])
        )
        assert len(registry.discover(EXAMPLE_PROFILE, limit=3).businesses) == 3

    def test_the_seed_list_is_just_another_source(self) -> None:
        """Nothing privileges it. That is what makes discovery autonomous-ready
        rather than seed-list-with-extras."""
        registry = DetectorRegistry()
        registry.register_source(
            SeedListSource.from_csv("name,website\nAl Noor,https://alnoor.ae\n")
        )
        registry.register_source(
            FixedSource("maps", [_business("Jumeirah Garage", "https://garage.ae")])
        )
        result = registry.discover(EXAMPLE_PROFILE, limit=10)
        assert {b.name for b in result.businesses} == {"Al Noor", "Jumeirah Garage"}

    def test_the_result_iterates_like_a_list(self) -> None:
        registry = DetectorRegistry()
        registry.register_source(FixedSource("a", [_business("A", "https://a.ae")]))
        result = registry.discover(EXAMPLE_PROFILE, limit=10)
        assert isinstance(result, DiscoveryResult)
        assert [b.name for b in result] == ["A"]


class TestConfidenceIsJustified:
    def _findings(self, page: str = BARE_PAGE) -> list[Finding]:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, html=page)

        client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
        return WebsiteDetector(client=client).inspect(
            _business("Al Noor", "https://alnoor.ae", "hello@alnoor.ae"), EXAMPLE_PROFILE
        )

    def test_reading_a_tag_out_of_the_markup_is_near_certain(self) -> None:
        missing_title = next(f for f in self._findings() if f.kind is FindingKind.MISSING_TITLE)
        assert missing_title.confidence == DIRECT_MARKUP_CONFIDENCE

    def test_a_single_timing_sample_is_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One measurement, over one network, from one place. Enough to raise
        the question, nowhere near enough to assert."""
        ticks = iter([0.0, SLOW_RESPONSE_SECONDS + 1.0])
        monkeypatch.setattr(
            "atlas_kernel.opportunity.detectors.website.time.monotonic", lambda: next(ticks)
        )
        slow = next(f for f in self._findings() if f.kind is FindingKind.SLOW_RESPONSE)
        assert slow.confidence == SINGLE_SAMPLE_TIMING_CONFIDENCE
        assert slow.confidence < DIRECT_MARKUP_CONFIDENCE

    def test_a_gap_in_someone_elses_record_is_weaker_than_our_own_observation(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            return httpx.Response(200)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        findings = WebsiteDetector(client=client).inspect(
            _business("Al Noor", None), EXAMPLE_PROFILE
        )
        assert findings[0].confidence == SOURCE_RECORD_CONFIDENCE
        assert findings[0].evidence[0].kind is EvidenceKind.ASSERTED

    def test_confidence_must_be_a_proportion(self) -> None:
        with pytest.raises(ValueError, match="between 0 and 1"):
            Finding(
                business_id="b1",
                kind=FindingKind.MISSING_TITLE,
                severity=Severity.HIGH,
                statement="No title.",
                confidence=1.4,
                evidence=[Evidence(kind=EvidenceKind.HTML_CONTENT, source="https://x.ae")],
            )


class TestConfidenceChangesTheOutcome:
    def _finding(self, severity: Severity, confidence: float) -> Finding:
        return Finding(
            business_id="b1",
            kind=FindingKind.MISSING_TITLE,
            severity=severity,
            statement="No title.",
            confidence=confidence,
            evidence=[Evidence(kind=EvidenceKind.HTML_CONTENT, source="https://x.ae")],
        )

    def test_a_high_severity_guess_scores_below_a_certainty(self) -> None:
        guess = self._finding(Severity.HIGH, 0.4)
        certain = self._finding(Severity.MEDIUM, 1.0)
        assert guess.weight < certain.weight

    def test_the_score_is_severity_discounted_by_confidence(self) -> None:
        assert score([self._finding(Severity.HIGH, 0.5)]) == pytest.approx(2.5)

    def test_weak_signals_are_dropped_before_scoring_not_merely_discounted(self) -> None:
        """Otherwise enough weak signals sum past the bar and arrive as
        confident assertions about someone's business."""
        weak = [self._finding(Severity.HIGH, 0.1) for _ in range(20)]
        assert applicable_findings(weak, EXAMPLE_PROFILE) == []
        assert (
            qualify(_business("Al Noor", "https://alnoor.ae"), weak, EXAMPLE_PROFILE).stage
            is OpportunityStage.DISQUALIFIED
        )

    def test_a_niche_can_demand_more_certainty(self) -> None:
        finding = self._finding(Severity.HIGH, 0.6)
        lenient = EXAMPLE_PROFILE.model_copy(update={"min_confidence": 0.5})
        strict = EXAMPLE_PROFILE.model_copy(update={"min_confidence": 0.8})
        assert applicable_findings([finding], lenient) == [finding]
        assert applicable_findings([finding], strict) == []

    def test_confidence_is_part_of_the_fingerprint(self) -> None:
        """A re-run that becomes less sure has changed the facts, and an
        approval granted on the confident version should not survive it."""
        confident = self._finding(Severity.HIGH, 0.9)
        unsure = confident.model_copy(update={"confidence": 0.5})
        assert confident.fingerprint != unsure.fingerprint
