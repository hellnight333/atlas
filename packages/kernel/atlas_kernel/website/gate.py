"""Atlas inspects its own work with the tool it judges strangers by.

M014 sells businesses a fix for missing viewport tags, absent titles, thin
content and slow pages. Shipping a site with any of those would be indefensible,
so the same detector runs against every site Atlas deploys and a finding blocks
promotion.

**It runs against the published version, not the build directory.** That is what
publish-then-promote buys: the artifact is reachable at the real host over the
real TLS and no visitor is being served it, so the gate inspects exactly what
they would get rather than a local approximation of it. A gate that reads files
off disk cannot catch a web server configured to serve the wrong directory, and
that is a real way to ship a broken site.

The detector is imported from the Opportunity Factory rather than copied or
extracted. Copying would let the two drift, and the drift would be silent and in
the worst direction — Atlas would keep selling against a defect it had stopped
checking for in its own work. Extracting it would mean reshaping frozen M014 for
a second consumer's convenience. If a third consumer appears, that is when it
moves.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from ..opportunity.detectors.website import WebsiteDetector
from ..opportunity.models import Business, Finding, NicheProfile

#: The gate's own profile. Threshold zero and confidence floor zero on purpose:
#: qualification exists to decide who is worth *contacting*, and a defect too
#: small to justify emailing a stranger is still a defect Atlas will not ship.
#: Every finding counts here.
GATE_PROFILE = NicheProfile(
    id="atlas-own-output",
    name="Atlas's own deployed sites",
    geography="",
    offer="",
    qualify_threshold=0.0,
    min_confidence=0.0,
)


class GateFailed(RuntimeError):
    """The site was not fit to promote. Not a host failure — see DeploymentError."""


@dataclass
class GateResult:
    passed: bool
    findings: list[Finding] = field(default_factory=list)
    url: str = ""

    @property
    def summary(self) -> list[str]:
        return [f"{finding.kind.value}: {finding.statement}" for finding in self.findings]

    def raise_if_failed(self) -> None:
        if not self.passed:
            raise GateFailed(
                f"{self.url} would ship with {len(self.findings)} defect(s) Atlas "
                f"sells against: {'; '.join(self.summary)}"
            )


class OutputGate:
    """Runs the M014 detector against a published-but-not-live URL."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._detector = WebsiteDetector(client=client)

    def check(self, preview_url: str, *, site_name: str = "site under test") -> GateResult:
        """Inspect what visitors would be served.

        The detector's entry point takes a business, so one is constructed for
        the URL. It is a local value that is never stored — a throwaway that
        exists to reuse the real code path rather than a second customer record.
        ``tests/test_one_customer_entity.py`` is why that distinction is worth
        stating out loud.
        """
        subject = Business(name=site_name, website=preview_url)
        findings = self._detector.inspect(subject, GATE_PROFILE)
        return GateResult(passed=not findings, findings=findings, url=preview_url)
