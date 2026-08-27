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
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from ..models import Business, Evidence, EvidenceKind, Finding, FindingKind, NicheProfile, Severity

#: Slower than this and a visitor on a phone notices. Seconds.
SLOW_RESPONSE_SECONDS = 3.0
#: Below this many characters of visible text, a page is a placeholder rather
#: than a website.
THIN_CONTENT_CHARS = 400
#: Per-request ceiling. Generous -- a slow site is a finding, not a failure.
REQUEST_TIMEOUT_SECONDS = 15.0
#: Cap on stored body text, so evidence stays inspectable rather than enormous.
EVIDENCE_EXCERPT_CHARS = 500

# -- Confidence -------------------------------------------------------------
#
# Every number below is justified by *how the observation was made*, not by how
# strongly the detector feels about it. A confidence a detector invents is worse
# than none at all, because it looks like rigour while being decoration.

#: A transport failure Atlas watched happen. About as certain as this gets --
#: though a site can be down for a minute and fine for a year.
OBSERVED_FAILURE_CONFIDENCE = 0.95

#: A tag read straight out of the returned document. Nearly certain, and short
#: of it for one real reason: single-page applications inject <title> and meta
#: tags client-side, so a served document without them is not always a page
#: without them. Common enough to matter, rare enough not to suppress.
DIRECT_MARKUP_CONFIDENCE = 0.85

#: Counting visible text in the served HTML. Same client-rendering caveat, and
#: it bites harder here: a React site legitimately ships almost no body text.
RENDERED_CONTENT_CONFIDENCE = 0.7

#: One timing sample, over one network, from one place. Enough to raise the
#: question and nowhere near enough to assert as fact -- which is exactly what
#: the confidence floor is for.
SINGLE_SAMPLE_TIMING_CONFIDENCE = 0.45

#: A field missing from somebody else's record. Only ever as good as the source,
#: and the source is often a directory nobody has updated in three years.
SOURCE_RECORD_CONFIDENCE = 0.6


class _PageFacts(HTMLParser):
    """Pulls the handful of tags a proposal can honestly speak about."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.meta_description: str | None = None
        self.viewport: str | None = None
        self.first_h1: str | None = None
        self.has_structured_data = False
        #: Whether ``</head>`` was reached. The difference between "this page
        #: has no <title>" and "the part of the page we kept has none", which
        #: matters the moment a body arrives truncated.
        self.head_closed = False
        self._text: list[str] = []
        self._capture: str | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): (value or "") for key, value in attrs}
        if tag == "body":
            # A document that has opened <body> has finished its head, whether
            # or not it bothered to close it — browsers read it that way. On
            # the *start* tag rather than the end, because a body that was
            # truncated never reaches `</body>`, and waiting for one would
            # suppress the head findings of exactly the pages truncation
            # affects.
            self.head_closed = True
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
        if tag == "head":
            self.head_closed = True
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


@dataclass(frozen=True)
class PageObservation:
    """One fetched page as facts, rather than as whichever object fetched it.

    Both callers build one of these: `WebsiteDetector.inspect`, from a live
    httpx response, and `opportunity/verification.py`, from evidence a
    verification mission recorded hours earlier. That is the point — one
    definition of *what was seen* is what makes one definition of *what counts
    as a defect* possible. The alternative, a second set of rules reading
    recorded evidence, drifts from this one the first time a threshold moves.

    `body_complete` is the field that earns its place. A body that arrived
    truncated, or was dropped for being enormous, cannot support a finding of
    the form "this page has no X" — the X may be in the part that is missing.
    That is `NOT_VERIFIED`, not `CONFIRMED_ABSENT`, and the distinction is the
    same one the rest of this system spends its time protecting.
    """

    requested_url: str
    final_url: str
    status: int
    content_type: str
    elapsed_seconds: float
    bytes: int
    body: str
    #: False when the body was truncated or never kept. Findings that reason
    #: from absence are suppressed rather than guessed.
    body_complete: bool = True

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type.lower()

    @property
    def scheme(self) -> str:
        return urlparse(self.final_url).scheme


class WebsiteDetector:
    """Inspects a business's website and reports evidenced defects.

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

    def inspect(self, business: Business, profile: NicheProfile) -> list[Finding]:
        if not business.website:
            return self._no_website(business)

        url = _normalise(business.website)
        started = time.monotonic()
        try:
            response = self._get_client().get(url)
        except ssl.SSLError as error:
            return [self._tls_invalid(business, url, error)]
        except httpx.HTTPError as error:
            return [self._unreachable(business, url, error)]
        elapsed = time.monotonic() - started

        page = PageObservation(
            requested_url=url,
            final_url=str(response.url),
            status=response.status_code,
            content_type=response.headers.get("content-type", ""),
            elapsed_seconds=elapsed,
            bytes=len(response.content),
            body=response.text,
            # A live response was read in full or it raised. Nothing here
            # truncates, so nothing here has to suppress.
            body_complete=True,
        )
        return self.findings_from(business, page)

    # -- the shared rules ------------------------------------------------

    def findings_from(self, business: Business,
                      page: PageObservation) -> list[Finding]:
        """Every defect one observed page supports. The single set of rules.

        `inspect` reaches this with a response it just made; verification
        reaches it with one recorded earlier. Neither can produce a finding the
        other would not, which is the property that makes an audit of stored
        evidence worth the same as an audit performed live.
        """
        if page.status >= 400:
            # A 500 tells us nothing about the page's SEO. Stop here rather than
            # generating findings about an error page's missing h1.
            return [self._bad_status(business, page)]

        findings = self._transport_findings(business, page)
        findings.extend(self._content_findings(business, page))
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

    def _no_website(self, business: Business) -> list[Finding]:
        # Asserted, not observed: the claim rests on the source record having no
        # website, and saying so plainly is more honest than dressing a missing
        # field up as an observation.
        return [
            Finding(
                business_id=business.id,
                kind=FindingKind.NO_WEBSITE,
                severity=Severity.HIGH,
                confidence=SOURCE_RECORD_CONFIDENCE,
                statement="No website is listed for this business.",
                evidence=[
                    self._evidence(
                        EvidenceKind.ASSERTED,
                        f"business:{business.id}",
                        {"website": None, "sources": business.sources},
                        f"No website recorded in {', '.join(business.sources) or 'the source record'}.",
                    )
                ],
            )
        ]

    def _unreachable(self, business: Business, url: str, error: Exception) -> Finding:
        return Finding(
            business_id=business.id,
            kind=FindingKind.SITE_UNREACHABLE,
            severity=Severity.HIGH,
            confidence=OBSERVED_FAILURE_CONFIDENCE,
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

    def _tls_invalid(self, business: Business, url: str, error: Exception) -> Finding:
        return Finding(
            business_id=business.id,
            kind=FindingKind.TLS_INVALID,
            severity=Severity.HIGH,
            confidence=OBSERVED_FAILURE_CONFIDENCE,
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

    def _bad_status(self, business: Business, page: PageObservation) -> Finding:
        return Finding(
            business_id=business.id,
            kind=FindingKind.SITE_UNREACHABLE,
            severity=Severity.HIGH,
            confidence=OBSERVED_FAILURE_CONFIDENCE,
            statement=f"The website returns an error ({page.status}) instead of a page.",
            evidence=[
                self._evidence(
                    EvidenceKind.HTTP_RESPONSE,
                    page.final_url,
                    {
                        "status_code": page.status,
                        "elapsed_seconds": round(page.elapsed_seconds, 3),
                        "final_url": page.final_url,
                    },
                    f"GET {page.requested_url} returned {page.status}.",
                )
            ],
        )

    def _transport_findings(
        self, business: Business, page: PageObservation
    ) -> list[Finding]:
        findings: list[Finding] = []
        final_url = page.final_url
        elapsed = page.elapsed_seconds

        if page.scheme != "https":
            findings.append(
                Finding(
                    business_id=business.id,
                    kind=FindingKind.NO_HTTPS,
                    severity=Severity.HIGH,
                    confidence=OBSERVED_FAILURE_CONFIDENCE,
                    statement="The site is served over an unencrypted connection, "
                    "which browsers label as 'Not secure'.",
                    evidence=[
                        self._evidence(
                            EvidenceKind.HTTP_RESPONSE,
                            final_url,
                            {
                                "scheme": page.scheme,
                                "status_code": page.status,
                            },
                            f"{final_url} resolved over {page.scheme}.",
                        )
                    ],
                )
            )

        if elapsed > SLOW_RESPONSE_SECONDS:
            findings.append(
                Finding(
                    business_id=business.id,
                    kind=FindingKind.SLOW_RESPONSE,
                    severity=Severity.MEDIUM,
                    confidence=SINGLE_SAMPLE_TIMING_CONFIDENCE,
                    statement=f"The homepage took {elapsed:.1f} seconds to respond, "
                    "which loses visitors on mobile connections.",
                    evidence=[
                        self._evidence(
                            EvidenceKind.TIMING,
                            final_url,
                            {
                                "elapsed_seconds": round(elapsed, 3),
                                "threshold_seconds": SLOW_RESPONSE_SECONDS,
                                "bytes": page.bytes,
                            },
                            f"GET {final_url} took {elapsed:.2f}s "
                            f"(threshold {SLOW_RESPONSE_SECONDS}s).",
                        )
                    ],
                )
            )
        return findings

    def _content_findings(self, business: Business,
                          page: PageObservation) -> list[Finding]:
        """Findings the returned markup supports. Nothing the markup omits.

        Two gates before any of it. The document must be HTML — an absent
        ``<title>`` in a PDF is not a defect — and enough of it must be present
        to speak about. A truncated body supports the head findings once
        ``</head>`` has actually been reached inside the part that arrived, and
        supports none of the whole-document ones: an h1, a JSON-LD block or
        four hundred more characters of text may all be sitting in the region
        that was cut off. Reporting those as absent would be inventing a
        finding out of a storage limit.
        """
        if not page.is_html:
            return []

        parser = _PageFacts()
        try:
            parser.feed(page.body)
        except Exception:  # noqa: BLE001 — malformed markup is common and not our problem
            pass

        whole_document = page.body_complete
        if not whole_document and not parser.head_closed:
            return []

        final_url = page.final_url
        excerpt = page.body[:EVIDENCE_EXCERPT_CHARS]
        findings: list[Finding] = []

        def html_evidence(observed: dict[str, Any], summary: str) -> Evidence:
            return self._evidence(
                EvidenceKind.HTML_CONTENT, final_url, {**observed, "excerpt": excerpt}, summary
            )

        if not parser.viewport:
            findings.append(
                Finding(
                    business_id=business.id,
                    kind=FindingKind.NOT_MOBILE_FRIENDLY,
                    severity=Severity.HIGH,
                    confidence=DIRECT_MARKUP_CONFIDENCE,
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
                    business_id=business.id,
                    kind=FindingKind.MISSING_TITLE,
                    severity=Severity.HIGH,
                    confidence=DIRECT_MARKUP_CONFIDENCE,
                    statement="The page has no title, so search results show the "
                    "raw address instead of the business name.",
                    evidence=[html_evidence({"title": None}, f"No <title> on {final_url}.")],
                )
            )

        if not parser.meta_description:
            findings.append(
                Finding(
                    business_id=business.id,
                    kind=FindingKind.MISSING_META_DESCRIPTION,
                    severity=Severity.MEDIUM,
                    confidence=DIRECT_MARKUP_CONFIDENCE,
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

        if whole_document and not parser.first_h1:
            findings.append(
                Finding(
                    business_id=business.id,
                    kind=FindingKind.MISSING_H1,
                    severity=Severity.LOW,
                    confidence=DIRECT_MARKUP_CONFIDENCE,
                    statement="The page has no main heading.",
                    evidence=[html_evidence({"h1": None}, f"No <h1> on {final_url}.")],
                )
            )

        if whole_document and not parser.has_structured_data:
            findings.append(
                Finding(
                    business_id=business.id,
                    kind=FindingKind.NO_STRUCTURED_DATA,
                    severity=Severity.LOW,
                    confidence=DIRECT_MARKUP_CONFIDENCE,
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

        if whole_document and parser.visible_text_length < THIN_CONTENT_CHARS:
            findings.append(
                Finding(
                    business_id=business.id,
                    kind=FindingKind.THIN_CONTENT,
                    severity=Severity.MEDIUM,
                    confidence=RENDERED_CONTENT_CONFIDENCE,
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
