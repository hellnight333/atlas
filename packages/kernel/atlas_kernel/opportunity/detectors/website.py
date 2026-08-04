"""Website inspection. Real fetches, real observations, no guessing.

Every finding this produces comes from something that was actually retrieved,
and the response that justified it is attached. Nothing here infers a defect
from the absence of a signal it did not look for.

Deliberately dependency-free beyond ``httpx``: the HTML parsing is a small
stdlib parser rather than another package. What is extracted -- title, meta
description, first h1, viewport, structured data, visible text length -- is
shallow enough that a real parser would be weight without benefit.

The judgement calls are named constants at the top of the file, not numbers
buried in branches, because they are the part most likely to need tuning once
real reply rates come back.
"""

from __future__ import annotations

import ssl
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from ..models import Evidence, EvidenceKind, Finding, FindingKind, NicheProfile, Prospect, Severity

#: Slower than this and a visitor on a phone notices. Seconds.
SLOW_RESPONSE_SECONDS = 3.0
#: Below this many characters of visible text, a page is a placeholder rather
#: than a website.
THIN_CONTENT_CHARS = 400
#: Per-request ceiling. Generous -- a slow site is a finding, not a failure.
REQUEST_TIMEOUT_SECONDS = 15.0
#: Cap on stored body text, so evidence stays inspectable rather than enormous.
EVIDENCE_EXCERPT_CHARS = 500


class _PageFacts(HTMLParser):
    """Pulls the handful of tags a proposal can honestly speak about."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.meta_description: str | None = None
        self.viewport: str | None = None
        self.first_h1: str | None = None
        self.has_structured_data = False
        self._text: list[str] = []
        self._capture: str | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): (value or "") for key, value in attrs}
        if tag in {"script", "style"}:
            # Structured data lives in a script tag, so check before skipping.
            if attributes.get("type", "").lower() == "application/ld+json":
                self.has_structured_data = True
            self._skip_depth += 1
            return
        if tag == "title":
            self._capture = "title"
        elif tag == "h1" and self.first_h1 is None:
            self._capture = "h1"
        elif tag == "meta":
            name = attributes.get("name", "").lower()
            if name == "description" and self.meta_description is None:
                self.meta_description = attributes.get("content", "").strip()
            elif name == "viewport" and self.viewport is None:
                self.viewport = attributes.get("content", "").strip()
        elif attributes.get("itemscope") is not None or "itemtype" in attributes:
            self.has_structured_data = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if (tag == "title" and self._capture == "title") or (tag == "h1" and self._capture == "h1"):
            self._capture = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._capture == "title" and self.title is None:
            self.title = text
        elif self._capture == "h1" and self.first_h1 is None:
            self.first_h1 = text
        self._text.append(text)

    @property
    def visible_text_length(self) -> int:
        return len(" ".join(self._text))


def _normalise(url: str) -> str:
    """Give a bare domain a scheme so it can be fetched at all."""
    url = url.strip()
    if not urlparse(url).scheme:
        return f"https://{url}"
    return url


class WebsiteDetector:
    """Inspects a prospect's website and reports evidenced defects.

    ``client`` is injectable so tests exercise the real logic against a
    transport they control. Nothing in here special-cases being under test --
    a detector that behaves differently in tests is a detector whose tests
    prove nothing.
    """

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    @property
    def name(self) -> str:
        return "website"

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=REQUEST_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": "AtlasOpportunityFactory/0.1 (+https://atlas.local)"},
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    # -- the one public method ------------------------------------------

    def inspect(self, prospect: Prospect, profile: NicheProfile) -> list[Finding]:
        if not prospect.website:
            return self._no_website(prospect)

        url = _normalise(prospect.website)
        started = time.monotonic()
        try:
            response = self._get_client().get(url)
        except ssl.SSLError as error:
            return [self._tls_invalid(prospect, url, error)]
        except httpx.HTTPError as error:
            return [self._unreachable(prospect, url, error)]
        elapsed = time.monotonic() - started

        findings: list[Finding] = []
        if response.status_code >= 400:
            findings.append(self._bad_status(prospect, url, response, elapsed))
            # A 500 tells us nothing about the page's SEO. Stop here rather than
            # generating findings about an error page's missing h1.
            return findings

        findings.extend(self._transport_findings(prospect, url, response, elapsed))
        findings.extend(self._content_findings(prospect, response))
        return findings

    # -- finding builders ------------------------------------------------

    def _evidence(
        self,
        kind: EvidenceKind,
        source: str,
        observed: dict[str, Any],
        summary: str,
    ) -> Evidence:
        return Evidence(
            kind=kind,
            source=source,
            observed=observed,
            summary=summary,
            detector=self.name,
        )

    def _no_website(self, prospect: Prospect) -> list[Finding]:
        # Asserted, not observed: the claim rests on the source record having no
        # website, and saying so plainly is more honest than dressing a missing
        # field up as an observation.
        return [
            Finding(
                prospect_id=prospect.id,
                kind=FindingKind.NO_WEBSITE,
                severity=Severity.HIGH,
                statement="No website is listed for this business.",
                evidence=[
                    self._evidence(
                        EvidenceKind.ASSERTED,
                        f"prospect:{prospect.id}",
                        {"website": None, "source": prospect.source},
                        f"No website recorded in {prospect.source}.",
                    )
                ],
            )
        ]

    def _unreachable(self, prospect: Prospect, url: str, error: Exception) -> Finding:
        return Finding(
            prospect_id=prospect.id,
            kind=FindingKind.SITE_UNREACHABLE,
            severity=Severity.HIGH,
            statement="The website did not respond when we tried to load it.",
            evidence=[
                self._evidence(
                    EvidenceKind.HTTP_RESPONSE,
                    url,
                    {"error": str(error), "error_type": type(error).__name__},
                    f"Request to {url} failed: {error}",
                )
            ],
        )

    def _tls_invalid(self, prospect: Prospect, url: str, error: Exception) -> Finding:
        return Finding(
            prospect_id=prospect.id,
            kind=FindingKind.TLS_INVALID,
            severity=Severity.HIGH,
            statement="The site's security certificate is not valid, so browsers warn visitors away.",
            evidence=[
                self._evidence(
                    EvidenceKind.TLS_CERTIFICATE,
                    url,
                    {"error": str(error)},
                    f"TLS handshake with {url} failed: {error}",
                )
            ],
        )

    def _bad_status(
        self, prospect: Prospect, url: str, response: httpx.Response, elapsed: float
    ) -> Finding:
        return Finding(
            prospect_id=prospect.id,
            kind=FindingKind.SITE_UNREACHABLE,
            severity=Severity.HIGH,
            statement=f"The website returns an error ({response.status_code}) instead of a page.",
            evidence=[
                self._evidence(
                    EvidenceKind.HTTP_RESPONSE,
                    str(response.url),
                    {
                        "status_code": response.status_code,
                        "elapsed_seconds": round(elapsed, 3),
                        "final_url": str(response.url),
                    },
                    f"GET {url} returned {response.status_code}.",
                )
            ],
        )

    def _transport_findings(
        self, prospect: Prospect, url: str, response: httpx.Response, elapsed: float
    ) -> list[Finding]:
        findings: list[Finding] = []
        final_url = str(response.url)

        if urlparse(final_url).scheme != "https":
            findings.append(
                Finding(
                    prospect_id=prospect.id,
                    kind=FindingKind.NO_HTTPS,
                    severity=Severity.HIGH,
                    statement="The site is served over an unencrypted connection, "
                    "which browsers label as 'Not secure'.",
                    evidence=[
                        self._evidence(
                            EvidenceKind.HTTP_RESPONSE,
                            final_url,
                            {
                                "scheme": urlparse(final_url).scheme,
                                "status_code": response.status_code,
                            },
                            f"{final_url} resolved over {urlparse(final_url).scheme}.",
                        )
                    ],
                )
            )

        if elapsed > SLOW_RESPONSE_SECONDS:
            findings.append(
                Finding(
                    prospect_id=prospect.id,
                    kind=FindingKind.SLOW_RESPONSE,
                    severity=Severity.MEDIUM,
                    statement=f"The homepage took {elapsed:.1f} seconds to respond, "
                    "which loses visitors on mobile connections.",
                    evidence=[
                        self._evidence(
                            EvidenceKind.TIMING,
                            final_url,
                            {
                                "elapsed_seconds": round(elapsed, 3),
                                "threshold_seconds": SLOW_RESPONSE_SECONDS,
                                "bytes": len(response.content),
                            },
                            f"GET {final_url} took {elapsed:.2f}s "
                            f"(threshold {SLOW_RESPONSE_SECONDS}s).",
                        )
                    ],
                )
            )
        return findings

    def _content_findings(self, prospect: Prospect, response: httpx.Response) -> list[Finding]:
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            return []

        parser = _PageFacts()
        try:
            parser.feed(response.text)
        except Exception:  # noqa: BLE001 — malformed markup is common and not our problem
            pass

        final_url = str(response.url)
        excerpt = response.text[:EVIDENCE_EXCERPT_CHARS]
        findings: list[Finding] = []

        def html_evidence(observed: dict[str, Any], summary: str) -> Evidence:
            return self._evidence(
                EvidenceKind.HTML_CONTENT, final_url, {**observed, "excerpt": excerpt}, summary
            )

        if not parser.viewport:
            findings.append(
                Finding(
                    prospect_id=prospect.id,
                    kind=FindingKind.NOT_MOBILE_FRIENDLY,
                    severity=Severity.HIGH,
                    statement="The site has no mobile layout setting, so it renders "
                    "desktop-sized on phones.",
                    evidence=[
                        html_evidence(
                            {"viewport_meta": None},
                            f"No <meta name=viewport> found on {final_url}.",
                        )
                    ],
                )
            )

        if not parser.title:
            findings.append(
                Finding(
                    prospect_id=prospect.id,
                    kind=FindingKind.MISSING_TITLE,
                    severity=Severity.HIGH,
                    statement="The page has no title, so search results show the "
                    "raw address instead of the business name.",
                    evidence=[html_evidence({"title": None}, f"No <title> on {final_url}.")],
                )
            )

        if not parser.meta_description:
            findings.append(
                Finding(
                    prospect_id=prospect.id,
                    kind=FindingKind.MISSING_META_DESCRIPTION,
                    severity=Severity.MEDIUM,
                    statement="The page has no description, so Google writes its own "
                    "summary of the business.",
                    evidence=[
                        html_evidence(
                            {"meta_description": None},
                            f"No <meta name=description> on {final_url}.",
                        )
                    ],
                )
            )

        if not parser.first_h1:
            findings.append(
                Finding(
                    prospect_id=prospect.id,
                    kind=FindingKind.MISSING_H1,
                    severity=Severity.LOW,
                    statement="The page has no main heading.",
                    evidence=[html_evidence({"h1": None}, f"No <h1> on {final_url}.")],
                )
            )

        if not parser.has_structured_data:
            findings.append(
                Finding(
                    prospect_id=prospect.id,
                    kind=FindingKind.NO_STRUCTURED_DATA,
                    severity=Severity.LOW,
                    statement="The site publishes no structured business details, so "
                    "opening hours and location do not appear in search results.",
                    evidence=[
                        html_evidence(
                            {"structured_data": False},
                            f"No JSON-LD or microdata on {final_url}.",
                        )
                    ],
                )
            )

        if parser.visible_text_length < THIN_CONTENT_CHARS:
            findings.append(
                Finding(
                    prospect_id=prospect.id,
                    kind=FindingKind.THIN_CONTENT,
                    severity=Severity.MEDIUM,
                    statement=f"The homepage has only {parser.visible_text_length} characters "
                    "of text, too little for search engines to rank it.",
                    evidence=[
                        html_evidence(
                            {
                                "visible_text_chars": parser.visible_text_length,
                                "threshold_chars": THIN_CONTENT_CHARS,
                            },
                            f"{parser.visible_text_length} characters of visible text "
                            f"on {final_url}.",
                        )
                    ],
                )
            )

        return findings
