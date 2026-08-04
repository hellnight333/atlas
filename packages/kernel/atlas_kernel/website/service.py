"""Build, publish, gate, promote, verify. And rollback, which is none of those.

The order is the design. Publication happens before the gate so the gate can
inspect what visitors would actually be served; promotion happens after it so
nobody is served anything that failed. Verification happens after promotion
because a deploy tool's exit code says the upload worked, not that a person can
load the page.

**Rollback republishes from Atlas's own stored build rather than asking the host
to revert.** It is slower than promoting a version the provider still has, and
it is chosen deliberately: a rollback that depends on a provider's retention is
a provider feature wearing Atlas's name, and it fails silently the day the
provider is swapped or prunes an old deployment. Doing it this way also means
the provider-independence invariant is exercised every time anyone reverts,
rather than the first time somebody tries to move a customer.

Note what this deliberately does not have: a method that builds, deploys and
promotes without a gate. The gate is not optional and there is no fast path
around it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from ..opportunity.models import BusinessEvent
from .gate import GateFailed, GateResult, OutputGate
from .models import (
    Deployment,
    DeploymentStatus,
    Site,
    SiteBuild,
    VerificationResult,
)
from .repository import WebsiteRepository
from .targets.base import DeploymentError, DeploymentTargetRegistry

#: Recorded on the business timeline. Namespaced by factory, so these never
#: collide with the Opportunity Factory's funnel stages.
WEBSITE_FACTORY = "website"

VERIFY_TIMEOUT_SECONDS = 20.0


class RollbackImpossible(RuntimeError):
    """There is no earlier version to go back to."""


@dataclass
class WebsiteService:
    repository: WebsiteRepository
    targets: DeploymentTargetRegistry
    gate: OutputGate = field(default_factory=OutputGate)
    #: For verifying live URLs. Separate from the gate's client so a test can
    #: control them independently — they inspect different things at different
    #: moments.
    verifier: httpx.Client | None = None

    # -- building ---------------------------------------------------------

    def record_build(
        self,
        site: Site,
        files: dict[str, str],
        *,
        generator: str = "authored",
        provenance: dict | None = None,
    ) -> SiteBuild:
        """Store an artifact. Phase A authors the files; Phase B generates them.

        Storing the bytes rather than a path is the whole point: this is what
        "rebuild from Business memory" means, and it is what lets a build be sent
        to a second provider without anyone reconstructing anything.
        """
        build = SiteBuild(
            site_id=site.id,
            business_id=site.business_id,
            files=files,
            generator=generator,
            provenance=provenance or {},
        )
        self.repository.save_build(build)
        self._record(
            site.business_id,
            "built",
            {"build_id": build.id, "fingerprint": build.fingerprint, "files": len(files)},
        )
        return build

    def rebuild_from_memory(self, build_id: str) -> SiteBuild:
        """Reconstruct a build from the durable record and prove it is the same.

        The check is the point. Loading a row and trusting it would verify
        nothing; comparing the fingerprint of what came back against what was
        stored is what makes "reproducible" a claim rather than an aspiration.
        """
        build = self.repository.get_build(build_id)
        if build is None:
            raise LookupError(f"no build {build_id} in Atlas's record")
        stored = self.repository.stored_fingerprint(build_id)
        if stored and stored != build.fingerprint:
            raise ValueError(
                f"build {build_id} does not match what was stored "
                f"(stored {stored}, rebuilt {build.fingerprint}) — "
                "the record has been altered or rendering is not deterministic"
            )
        return build

    # -- deploying --------------------------------------------------------

    def deploy(
        self,
        site: Site,
        build: SiteBuild,
        *,
        target: str | None = None,
    ) -> Deployment:
        """Publish, gate, promote, verify. Returns the live deployment."""
        registration = self.targets.resolve(target)
        slug = _slug(site)

        deployment = Deployment(
            build_id=build.id,
            site_id=site.id,
            business_id=site.business_id,
            target=registration.name,
            build_fingerprint=build.fingerprint,
        )

        try:
            published = registration.target.publish(slug, build.files)
        except DeploymentError as error:
            deployment = deployment.model_copy(
                update={"status": DeploymentStatus.FAILED, "detail": str(error)}
            )
            self.repository.save_deployment(deployment)
            self._record(site.business_id, "publish_failed", {"error": str(error)})
            raise

        deployment = deployment.model_copy(
            update={
                "status": DeploymentStatus.PUBLISHED,
                "remote_id": published.id,
                "preview_url": published.preview_url,
                "detail": published.detail,
            }
        )
        self.repository.save_deployment(deployment)
        self._record(
            site.business_id,
            "published",
            {"target": registration.name, "preview_url": published.preview_url},
        )

        result = self.gate.check(published.preview_url, site_name=site.name)
        if not result.passed:
            deployment = deployment.model_copy(
                update={
                    "status": DeploymentStatus.GATE_FAILED,
                    "gate_findings": result.summary,
                    "detail": "blocked before promotion by Atlas's own detector",
                }
            )
            self.repository.save_deployment(deployment)
            self._record(
                site.business_id,
                "gate_failed",
                {"findings": result.summary, "url": published.preview_url},
            )
            result.raise_if_failed()

        return self._promote(site, deployment, registration.target, slug)

    def _promote(self, site: Site, deployment: Deployment, target, slug: str) -> Deployment:
        try:
            live_url = target.promote(slug, deployment.remote_id or "")
        except DeploymentError as error:
            failed = deployment.model_copy(
                update={"status": DeploymentStatus.FAILED, "detail": str(error)}
            )
            self.repository.save_deployment(failed)
            self._record(site.business_id, "promote_failed", {"error": str(error)})
            raise

        verification = self.verify(live_url)
        if not verification.ok:
            failed = deployment.model_copy(
                update={
                    "status": DeploymentStatus.FAILED,
                    "live_url": live_url,
                    "detail": f"promoted but not reachable: {verification.detail}",
                }
            )
            self.repository.save_deployment(failed)
            self._record(
                site.business_id,
                "verify_failed",
                {"url": live_url, "detail": verification.detail},
            )
            return failed

        # Only now is anything else superseded. Doing it earlier would leave no
        # recorded live deployment during the window where the new one might
        # still fail.
        self.repository.supersede_live(site.id, deployment.target, except_id=deployment.id)
        live = deployment.model_copy(
            update={
                "status": DeploymentStatus.LIVE,
                "live_url": live_url,
                "promoted_at": datetime.now(UTC),
                "detail": None,
            }
        )
        self.repository.save_deployment(live)
        self._record(
            site.business_id,
            "deployed",
            {
                "target": live.target,
                "url": live_url,
                "fingerprint": live.build_fingerprint,
                "status_code": verification.status_code,
            },
        )
        return live

    # -- reverting --------------------------------------------------------

    def rollback(self, site: Site, *, target: str | None = None) -> Deployment:
        """Put the previous version back, from Atlas's own artifact."""
        registration = self.targets.resolve(target)
        previous = self.repository.previous_deployment(site.id, registration.name)
        if previous is None:
            raise RollbackImpossible(
                f"{site.name} has no earlier deployment on {registration.name} to return to"
            )

        build = self.repository.get_build(previous.build_id)
        if build is None:  # pragma: no cover - defensive
            raise RollbackImpossible(
                f"the build behind {previous.id} is missing from Atlas's record"
            )

        # Republished rather than re-promoted, deliberately. See module docstring.
        self._record(
            site.business_id,
            "rolling_back",
            {"to_build": build.id, "fingerprint": build.fingerprint},
        )
        restored = self.deploy(site, build, target=registration.name)
        self._record(
            site.business_id,
            "rolled_back",
            {"to_build": build.id, "url": restored.live_url},
        )
        return restored

    # -- checking ---------------------------------------------------------

    def verify(self, url: str) -> VerificationResult:
        """Fetch the URL and report what came back.

        Any non-2xx is a failure, including a redirect chain that ends badly. A
        site that answers 500 has been deployed successfully by every measure
        except the one that matters.
        """
        client = self.verifier or httpx.Client(
            timeout=VERIFY_TIMEOUT_SECONDS, follow_redirects=True
        )
        started = time.monotonic()
        try:
            response = client.get(url)
        except httpx.HTTPError as error:
            return VerificationResult(url=url, ok=False, detail=str(error))
        elapsed = time.monotonic() - started
        return VerificationResult(
            url=url,
            ok=200 <= response.status_code < 300,
            status_code=response.status_code,
            elapsed_seconds=round(elapsed, 3),
            detail="" if response.is_success else f"returned {response.status_code}",
        )

    def check_live(self, site: Site) -> VerificationResult:
        """Health check for a site already serving. Phase C's building block."""
        deployment = self.repository.live_deployment(site.id)
        if deployment is None or not deployment.live_url:
            raise LookupError(f"{site.name} has no live deployment to check")
        result = self.verify(deployment.live_url)
        self._record(
            site.business_id,
            "checked" if result.ok else "check_failed",
            {"url": deployment.live_url, "status_code": result.status_code},
        )
        return result

    # -- internals --------------------------------------------------------

    def _record(self, business_id: str, kind: str, detail: dict | None = None) -> BusinessEvent:
        event = BusinessEvent(
            business_id=business_id,
            factory=WEBSITE_FACTORY,
            kind=kind,
            detail=detail or {},
        )
        self.repository.record_event(event)
        return event


def _slug(site: Site) -> str:
    """A filesystem- and URL-safe name for a site.

    Derived from the id rather than the name: names change, and a slug that
    changes moves every published version of a site to a new location.
    """
    return f"site-{site.id[:12]}"


__all__ = [
    "GateFailed",
    "GateResult",
    "RollbackImpossible",
    "WEBSITE_FACTORY",
    "WebsiteService",
]
