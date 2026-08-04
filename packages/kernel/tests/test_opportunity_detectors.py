"""Website detection (M014).

Everything the Opportunity Factory says about a business traces to something a
detector actually retrieved. These tests drive the real detector against a
transport they control — not a stubbed detector — so what is proved is the
parsing and the judgement, not a fake.

The property worth defending hardest: a detector must never invent a defect it
did not observe. A clean site produces nothing, and each finding carries the
response that justifies it.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_kernel.opportunity.detectors.base import (
    DetectorError,
    DetectorRegistry,
    NoDetectorAvailable,
)
from atlas_kernel.opportunity.detectors.website import (
    SLOW_RESPONSE_SECONDS,
    WebsiteDetector,
)
from atlas_kernel.opportunity.models import (
    Business,
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    NicheProfile,
    Severity,
)
from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE

GOOD_PAGE = """
<!doctype html><html><head>
<title>Al Noor Dental Clinic — Dubai</title>
<meta name="description" content="Dental care in Jumeirah since 2009.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script type="application/ld+json">{"@type":"Dentist"}</script>
</head><body>
<h1>Al Noor Dental Clinic</h1>
<p>%s</p>
</body></html>
""" % ("We have provided dental care in Jumeirah since 2009. " * 20)

BARE_PAGE = "<html><body><p>Coming soon</p></body></html>"


def _business(website: str | None = "https://clinic.test") -> Business:
    return Business(
        name="Al Noor Dental Clinic",
        geography="United Arab Emirates",
        website=website,
        email="hello@clinic.test",
        sources=["seed-list"],
    )


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _kinds(findings: list[Finding]) -> set[FindingKind]:
    return {finding.kind for finding in findings}


class TestCleanSite:
    def test_a_healthy_page_produces_no_findings(self) -> None:
        """The most important test here. A detector that always finds something
        is a detector that will contact people who are doing nothing wrong."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, html=GOOD_PAGE)

        detector = WebsiteDetector(client=_client(handler))
        assert detector.inspect(_business(), EXAMPLE_PROFILE) == []


class TestDefects:
    def _findings(self, page: str, status: int = 200, **kwargs) -> list[Finding]:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, html=page, **kwargs)

        return WebsiteDetector(client=_client(handler)).inspect(_business(), EXAMPLE_PROFILE)

    def test_a_bare_page_reports_every_missing_element(self) -> None:
        kinds = _kinds(self._findings(BARE_PAGE))
        assert kinds == {
            FindingKind.NOT_MOBILE_FRIENDLY,
            FindingKind.MISSING_TITLE,
            FindingKind.MISSING_META_DESCRIPTION,
            FindingKind.MISSING_H1,
            FindingKind.NO_STRUCTURED_DATA,
            FindingKind.THIN_CONTENT,
        }

    def test_every_finding_carries_the_response_that_justifies_it(self) -> None:
        for finding in self._findings(BARE_PAGE):
            assert finding.evidence, f"{finding.kind} has no evidence"
            observed = finding.evidence[0]
            assert observed.detector == "website"
            assert observed.source.startswith("http")
            assert observed.summary

    def test_evidence_keeps_the_raw_observation_not_just_a_summary(self) -> None:
        """A summarised observation cannot be re-checked, so the excerpt is kept
        alongside it."""
        finding = next(f for f in self._findings(BARE_PAGE) if f.kind is FindingKind.MISSING_TITLE)
        assert "Coming soon" in finding.evidence[0].observed["excerpt"]

    def test_a_missing_website_is_asserted_not_pretended_to_be_observed(self) -> None:
        detector = WebsiteDetector(client=_client(lambda r: httpx.Response(200)))
        findings = detector.inspect(_business(website=None), EXAMPLE_PROFILE)
        assert [f.kind for f in findings] == [FindingKind.NO_WEBSITE]
        assert findings[0].evidence[0].kind is EvidenceKind.ASSERTED

    def test_plain_http_is_reported_as_insecure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, html=GOOD_PAGE)

        business = _business(website="http://clinic.test")
        findings = WebsiteDetector(client=_client(handler)).inspect(business, EXAMPLE_PROFILE)
        assert FindingKind.NO_HTTPS in _kinds(findings)

    def test_a_bare_domain_is_tried_over_https(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, html=GOOD_PAGE)

        business = _business(website="clinic.test")
        WebsiteDetector(client=_client(handler)).inspect(business, EXAMPLE_PROFILE)
        assert seen == ["https://clinic.test"]

    def test_an_error_page_is_not_mined_for_seo_findings(self) -> None:
        """A 500 says nothing about the site's SEO. Reporting a missing <h1> on
        an error page would be a claim about the wrong thing."""
        findings = self._findings("<html><body>Server Error</body></html>", status=500)
        assert [f.kind for f in findings] == [FindingKind.SITE_UNREACHABLE]
        assert findings[0].evidence[0].observed["status_code"] == 500

    def test_an_unreachable_site_is_reported_with_the_transport_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("name resolution failed")

        findings = WebsiteDetector(client=_client(handler)).inspect(_business(), EXAMPLE_PROFILE)
        assert [f.kind for f in findings] == [FindingKind.SITE_UNREACHABLE]
        assert "name resolution failed" in findings[0].evidence[0].observed["error"]

    def test_non_html_responses_produce_no_content_findings(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        findings = WebsiteDetector(client=_client(handler)).inspect(_business(), EXAMPLE_PROFILE)
        assert _kinds(findings) <= {FindingKind.NO_HTTPS, FindingKind.SLOW_RESPONSE}

    def test_script_and_style_text_does_not_count_as_content(self) -> None:
        """Otherwise a page with one paragraph and a large analytics blob looks
        substantial when a visitor sees nothing."""
        page = (
            "<html><head><title>T</title>"
            '<meta name="description" content="d">'
            '<meta name="viewport" content="width=device-width">'
            '<script type="application/ld+json">{"@type":"X"}</script>'
            "</head><body><h1>H</h1><script>"
            + ("var padding = 'x';" * 200)
            + "</script><p>Short.</p></body></html>"
        )
        assert FindingKind.THIN_CONTENT in _kinds(self._findings(page))


class TestSeverity:
    def test_the_things_that_lose_customers_outrank_the_cosmetic(self) -> None:
        """Severity drives both scoring and what a first email leads with, so
        getting the order wrong changes who gets contacted."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, html=BARE_PAGE)

        findings = {
            f.kind: f.severity
            for f in WebsiteDetector(client=_client(handler)).inspect(_business(), EXAMPLE_PROFILE)
        }
        assert findings[FindingKind.NOT_MOBILE_FRIENDLY] is Severity.HIGH
        assert findings[FindingKind.MISSING_TITLE] is Severity.HIGH
        assert findings[FindingKind.MISSING_H1] is Severity.LOW
        assert findings[FindingKind.NO_STRUCTURED_DATA] is Severity.LOW


class TestRegistry:
    def _profile(self) -> NicheProfile:
        return EXAMPLE_PROFILE

    def test_one_failing_detector_does_not_abandon_the_business(self) -> None:
        class Broken:
            name = "broken"

            def inspect(self, business, profile):
                raise RuntimeError("upstream down")

        class Working:
            name = "working"

            def inspect(self, business, profile):
                return [
                    Finding(
                        business_id=business.id,
                        kind=FindingKind.MISSING_H1,
                        severity=Severity.LOW,
                        statement="No main heading.",
                        evidence=[
                            Evidence(kind=EvidenceKind.HTML_CONTENT, source="https://x.test")
                        ],
                    )
                ]

        registry = DetectorRegistry()
        registry.register_detector(Broken())
        registry.register_detector(Working())
        assert len(registry.inspect(_business(), self._profile())) == 1

    def test_all_detectors_failing_raises_rather_than_reporting_a_clean_site(self) -> None:
        """ "Found nothing" and "could not look" must not render the same way —
        one of them means the business is fine."""

        class Broken:
            name = "broken"

            def inspect(self, business, profile):
                raise RuntimeError("upstream down")

        registry = DetectorRegistry()
        registry.register_detector(Broken())
        with pytest.raises(DetectorError, match="upstream down"):
            registry.inspect(_business(), self._profile())

    def test_an_unserved_capability_says_so(self) -> None:
        registry = DetectorRegistry()
        with pytest.raises(NoDetectorAvailable, match="opportunity.inspect"):
            registry.inspect(_business(), self._profile())
        with pytest.raises(NoDetectorAvailable, match="opportunity.discover"):
            registry.discover(self._profile(), 10)

    def test_re_registering_a_detector_replaces_it(self) -> None:
        class Named:
            name = "website"

            def inspect(self, business, profile):
                return []

        registry = DetectorRegistry()
        registry.register_detector(Named())
        registry.register_detector(Named())
        assert len(registry.detectors) == 1


class TestTiming:
    def test_a_slow_response_is_reported_against_the_documented_threshold(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ticks = iter([0.0, SLOW_RESPONSE_SECONDS + 1.0])
        monkeypatch.setattr(
            "atlas_kernel.opportunity.detectors.website.time.monotonic", lambda: next(ticks)
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, html=GOOD_PAGE)

        findings = WebsiteDetector(client=_client(handler)).inspect(_business(), EXAMPLE_PROFILE)
        slow = next(f for f in findings if f.kind is FindingKind.SLOW_RESPONSE)
        assert slow.evidence[0].observed["threshold_seconds"] == SLOW_RESPONSE_SECONDS
