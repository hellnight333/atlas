"""Phase A: publish, gate, promote, verify, roll back (M015).

Four properties carry this milestone, and each has a class here.

**Atlas owns the artifact, not the host.** A build is stored byte for byte, so
deploying the same build to a second provider is an ordinary operation producing
an identical artifact — not a migration.

**Rebuild from Business memory.** Delete everything on disk and the site comes
back from the database alone, verified by fingerprint rather than by eye.

**The interface does not leak.** Two targets that share no mechanism — a
filesystem with symlinks, and an HTTP API that invents its own ids — drive the
same code path. One adapter could never demonstrate that.

**Nothing is promoted that Atlas would flag on a stranger's site.** The gate runs
against the published-but-not-live version, so it inspects what visitors would
actually be served.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from atlas_kernel.website.gate import GateFailed, OutputGate
from atlas_kernel.website.models import (
    Deployment,
    DeploymentStatus,
    Site,
    SiteBuild,
)
from atlas_kernel.website.service import WebsiteService
from atlas_kernel.website.targets.base import (
    DeploymentError,
    DeploymentTarget,
    DeploymentTargetRegistry,
    NoTargetAvailable,
    TargetRegistration,
)
from atlas_kernel.website.targets.cloudflare import CloudflarePagesTarget
from atlas_kernel.website.targets.local import LocalDirectoryTarget

# A page that satisfies the output contract: real markup in the served
# response, every tag the detector looks for, enough text to be a page.
GOOD_PAGE = (
    "<!doctype html><html><head>"
    "<title>Teqtronix — Electronics Trading, Dubai</title>"
    '<meta name="description" content="Electronics trading and distribution in Dubai.">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<script type="application/ld+json">{"@type":"Organization"}</script>'
    "</head><body><h1>Teqtronix</h1><p>"
    + ("Electronics trading and distribution across the UAE since 2016. " * 12)
    + "</p></body></html>"
)

# The kind of page Atlas sells against: no viewport, no title, no content.
BAD_PAGE = "<html><body><p>Coming soon</p></body></html>"


def _files(page: str = GOOD_PAGE) -> dict[str, str]:
    return {"index.html": page, "styles.css": "body{font-family:system-ui}"}


def _site() -> Site:
    return Site(business_id="biz-teqtronix", name="Teqtronix", domain="teqtronix.test")


def _build(site: Site, page: str = GOOD_PAGE) -> SiteBuild:
    return SiteBuild(site_id=site.id, business_id=site.business_id, files=_files(page))


def _serving_client(target: LocalDirectoryTarget) -> httpx.Client:
    """A web server in front of the local target's root.

    The local adapter deliberately does not run one — a target that behaved
    differently in tests than in production would prove nothing. So the test
    supplies the web server, which is exactly the role Caddy or nginx plays on a
    real box.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        relative = request.url.path.lstrip("/")
        candidate = target.root / relative
        # A site's document root is its `current` symlink, which is how the
        # server is configured on a real box — `root /srv/<slug>/current`. The
        # site directory itself holds `versions/` and the link, and serving it
        # directly would 404 on every live URL.
        if candidate.is_dir() and (candidate / "current").exists():
            candidate = candidate / "current"
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_file():
            return httpx.Response(404, text="not found")
        return httpx.Response(200, html=candidate.read_text(encoding="utf-8"))

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


@pytest.fixture
def local_target(tmp_path: Path) -> LocalDirectoryTarget:
    # https, because the gate rejects plain HTTP — correctly. A customer site
    # served over http is one of the defects M014 sells against, so exempting it
    # for a preview URL would be weakening the gate to make a test pass. Real
    # preview URLs are https on both hosts anyway.
    return LocalDirectoryTarget(tmp_path / "sites", base_url="https://sites.test")


@pytest.fixture
def registry(local_target: LocalDirectoryTarget) -> DeploymentTargetRegistry:
    registry = DeploymentTargetRegistry()
    registry.register(TargetRegistration(target=local_target))
    return registry


class FakeRepository:
    """In-memory stand-in, so the pipeline is testable without a database.

    Deliberately not a mock: it stores and returns real models, so a test that
    passes here is exercising the service's logic rather than its expectations.
    """

    def __init__(self) -> None:
        self.builds: dict[str, SiteBuild] = {}
        self.deployments: dict[str, Deployment] = {}
        self.events: list = []

    def save_build(self, build: SiteBuild) -> SiteBuild:
        self.builds[build.id] = build
        return build

    def get_build(self, build_id: str) -> SiteBuild | None:
        return self.builds.get(build_id)

    def stored_fingerprint(self, build_id: str) -> str | None:
        build = self.builds.get(build_id)
        return build.fingerprint if build else None

    def save_deployment(self, deployment: Deployment) -> Deployment:
        self.deployments[deployment.id] = deployment
        return deployment

    def live_deployment(self, site_id: str, target: str | None = None) -> Deployment | None:
        live = [
            d
            for d in self.deployments.values()
            if d.site_id == site_id
            and d.status is DeploymentStatus.LIVE
            and (target is None or d.target == target)
        ]
        return live[-1] if live else None

    def previous_deployment(self, site_id: str, target: str) -> Deployment | None:
        superseded = [
            d
            for d in self.deployments.values()
            if d.site_id == site_id
            and d.target == target
            and d.status is DeploymentStatus.SUPERSEDED
        ]
        return superseded[-1] if superseded else None

    def supersede_live(self, site_id: str, target: str, *, except_id: str) -> None:
        for key, deployment in list(self.deployments.items()):
            if (
                deployment.site_id == site_id
                and deployment.target == target
                and deployment.status is DeploymentStatus.LIVE
                and deployment.id != except_id
            ):
                self.deployments[key] = deployment.model_copy(
                    update={"status": DeploymentStatus.SUPERSEDED}
                )

    def record_event(self, event):
        self.events.append(event)
        return event


def _service(registry: DeploymentTargetRegistry, target: LocalDirectoryTarget) -> WebsiteService:
    client = _serving_client(target)
    return WebsiteService(
        repository=FakeRepository(),
        targets=registry,
        gate=OutputGate(client=client),
        verifier=client,
    )


class TestTheArtifactBelongsToAtlas:
    def test_the_same_build_deploys_to_a_second_target_as_a_normal_operation(
        self, tmp_path: Path
    ) -> None:
        """Moving a customer between providers must not be a migration.

        Two targets, one build, no export step and no reconstruction — and the
        artifact that lands on the second is identical to the first.
        """
        first = LocalDirectoryTarget(tmp_path / "a", base_url="https://a.test", name="host-a")
        second = LocalDirectoryTarget(tmp_path / "b", base_url="https://b.test", name="host-b")
        registry = DeploymentTargetRegistry()
        registry.register(TargetRegistration(target=first))
        registry.register(TargetRegistration(target=second, is_local=False))

        site = _site()
        service = WebsiteService(
            repository=FakeRepository(),
            targets=registry,
            gate=OutputGate(client=_serving_client(first)),
            verifier=_serving_client(first),
        )
        build = service.record_build(site, _files())

        on_a = service.deploy(site, build, target="host-a")

        # Same build, different host. Nothing is rebuilt.
        service.gate = OutputGate(client=_serving_client(second))
        service.verifier = _serving_client(second)
        on_b = service.deploy(site, build, target="host-b")

        assert on_a.status is DeploymentStatus.LIVE
        assert on_b.status is DeploymentStatus.LIVE
        assert on_a.build_id == on_b.build_id
        assert on_a.build_fingerprint == on_b.build_fingerprint

        # The bytes that landed are identical, not merely equivalent.
        slug = f"site-{site.id[:12]}"
        assert first.read(slug, on_a.remote_id or "") == second.read(slug, on_b.remote_id or "")

    def test_a_build_is_identified_by_its_content_not_its_record(self) -> None:
        """Two builds of the same files are the same artifact, whoever made
        them and whenever — which is what makes cross-provider comparison
        possible at all."""
        one = SiteBuild(site_id="s1", business_id="b1", files=_files())
        two = SiteBuild(site_id="s2", business_id="b2", files=_files(), generator="other")
        assert one.id != two.id
        assert one.fingerprint == two.fingerprint

    def test_changing_one_byte_changes_the_fingerprint(self) -> None:
        base = SiteBuild(site_id="s", business_id="b", files=_files())
        changed = SiteBuild(
            site_id="s", business_id="b", files={**_files(), "styles.css": "body{}"}
        )
        assert base.fingerprint != changed.fingerprint

    def test_a_build_must_contain_something_loadable(self) -> None:
        """A bundle of CSS with no page is not a deployable site."""
        with pytest.raises(ValueError, match="at least one HTML file"):
            SiteBuild(site_id="s", business_id="b", files={"styles.css": "body{}"})

    def test_an_empty_build_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one file"):
            SiteBuild(site_id="s", business_id="b", files={})


class TestRebuildFromMemory:
    def test_a_build_survives_the_working_directory_being_deleted(
        self, tmp_path: Path, registry: DeploymentTargetRegistry, local_target
    ) -> None:
        service = _service(registry, local_target)
        site = _site()
        build = service.record_build(site, _files())
        service.deploy(site, build)

        # Everything on disk goes.
        import shutil

        shutil.rmtree(local_target.root)
        assert not local_target.root.exists()

        # The artifact comes back from the record alone, and is provably the same.
        rebuilt = service.rebuild_from_memory(build.id)
        assert rebuilt.fingerprint == build.fingerprint
        assert rebuilt.files == build.files

    def test_a_tampered_record_is_caught_rather_than_trusted(self) -> None:
        """Loading a row and believing it verifies nothing. Comparing the stored
        fingerprint against a fresh computation is what makes the claim real."""

        class TamperedRepository(FakeRepository):
            def stored_fingerprint(self, build_id: str) -> str:
                return "not-the-real-fingerprint"

        service = WebsiteService(
            repository=TamperedRepository(), targets=DeploymentTargetRegistry()
        )
        site = _site()
        build = service.record_build(site, _files())
        with pytest.raises(ValueError, match="does not match what was stored"):
            service.rebuild_from_memory(build.id)

    def test_an_unknown_build_says_so(self) -> None:
        service = WebsiteService(repository=FakeRepository(), targets=DeploymentTargetRegistry())
        with pytest.raises(LookupError, match="no build"):
            service.rebuild_from_memory("does-not-exist")


class TestTheInterfaceDoesNotLeak:
    """Two targets sharing no mechanism, driven through one code path.

    The local target derives its own version id from content and promotes by
    renaming a symlink. Cloudflare invents an id, has no filesystem, and
    promotes with an HTTP call. If the interface had encoded either, the other
    could not be written against it.
    """

    def _cloudflare(self) -> tuple[CloudflarePagesTarget, list[httpx.Request]]:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.path.endswith("/deployments") and request.method == "POST":
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "result": {
                            "id": "cf-deployment-7",
                            "url": "https://cf-deployment-7.example.pages.dev",
                        },
                    },
                )
            if request.url.path.endswith("/retry"):
                return httpx.Response(
                    200,
                    json={"success": True, "result": {"url": "https://example.pages.dev"}},
                )
            return httpx.Response(200, json={"success": True, "result": {}})

        target = CloudflarePagesTarget(
            account_id="acct",
            project="example",
            api_token="token",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        return target, seen

    def test_both_targets_satisfy_the_same_protocol(self, local_target) -> None:
        cloudflare, _ = self._cloudflare()
        assert isinstance(local_target, DeploymentTarget)
        assert isinstance(cloudflare, DeploymentTarget)

    def test_the_host_invents_the_version_id_and_atlas_accepts_it(self) -> None:
        """The local target derives ids from content; Cloudflare hands one back.
        Atlas treats both as opaque, which is the only reason both fit."""
        cloudflare, _ = self._cloudflare()
        published = cloudflare.publish("site-x", _files())
        assert published.id == "cf-deployment-7"
        assert published.preview_url.startswith("https://")

    def test_promotion_returns_a_stable_address_not_the_preview_one(self) -> None:
        cloudflare, _ = self._cloudflare()
        published = cloudflare.publish("site-x", _files())
        live = cloudflare.promote("site-x", published.id)
        assert live == "https://example.pages.dev"
        assert live != published.preview_url

    def test_an_application_error_in_a_200_body_is_still_a_failure(self) -> None:
        """Cloudflare reports refusals inside a successful response. Trusting
        the status code alone would promote nothing to production."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"success": False, "errors": [{"message": "quota exceeded"}]}
            )

        target = CloudflarePagesTarget(
            account_id="a",
            project="p",
            api_token="t",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(DeploymentError, match="quota exceeded"):
            target.publish("site-x", _files())

    def test_a_transport_failure_becomes_a_deployment_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        target = CloudflarePagesTarget(
            account_id="a",
            project="p",
            api_token="t",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(DeploymentError, match="no route to host"):
            target.publish("site-x", _files())

    def test_a_publish_with_no_id_is_refused(self) -> None:
        """A host that accepts an upload and returns nothing usable has failed,
        however successful the status line looks."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"success": True, "result": {}})

        target = CloudflarePagesTarget(
            account_id="a",
            project="p",
            api_token="t",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(DeploymentError, match="no deployment id"):
            target.publish("site-x", _files())


class TestTheLocalTarget:
    def test_publishing_does_not_serve_anyone(self, local_target) -> None:
        """The property the gate depends on: reachable, and not yet live."""
        published = local_target.publish("site-a", _files())
        assert local_target.read("site-a", published.id) is not None
        assert local_target.live_version("site-a") is None

    def test_promoting_makes_it_live(self, local_target) -> None:
        published = local_target.publish("site-a", _files())
        local_target.promote("site-a", published.id)
        assert local_target.live_version("site-a") == published.id

    def test_promoting_an_unpublished_version_is_refused(self, local_target) -> None:
        with pytest.raises(DeploymentError, match="not published"):
            local_target.promote("site-a", "nonexistent")

    def test_republishing_the_same_artifact_lands_on_the_same_version(self, local_target) -> None:
        """Rollback republishes from Atlas's stored build, so this path runs
        often. It must be idempotent rather than accumulate a directory per
        revert."""
        first = local_target.publish("site-a", _files())
        second = local_target.publish("site-a", _files())
        assert first.id == second.id

    def test_a_build_cannot_escape_its_directory(self, local_target) -> None:
        """Build paths are data, and data that becomes a filesystem path is
        worth checking however trusted it feels."""
        with pytest.raises(DeploymentError, match="unsafe path"):
            local_target.publish("site-a", {"../../etc/passwd.html": "x"})

    def test_removing_the_live_version_is_refused(self, local_target) -> None:
        published = local_target.publish("site-a", _files())
        local_target.promote("site-a", published.id)
        with pytest.raises(DeploymentError, match="is live"):
            local_target.remove("site-a", published.id)


class TestTheGate:
    def test_a_page_that_meets_the_contract_is_promoted(self, registry, local_target) -> None:
        service = _service(registry, local_target)
        site = _site()
        deployment = service.deploy(site, service.record_build(site, _files()))
        assert deployment.status is DeploymentStatus.LIVE
        assert deployment.gate_findings == []

    def test_a_page_atlas_sells_against_is_never_promoted(self, registry, local_target) -> None:
        """The self-consistency criterion. Selling a business a fix for a
        missing viewport tag and shipping them a site without one would be
        indefensible."""
        service = _service(registry, local_target)
        site = _site()
        build = service.record_build(site, _files(BAD_PAGE))

        with pytest.raises(GateFailed, match="defect"):
            service.deploy(site, build)

        assert local_target.live_version(f"site-{site.id[:12]}") is None, (
            "a failing build reached visitors"
        )

    def test_a_blocked_deployment_records_what_was_wrong(self, registry, local_target) -> None:
        service = _service(registry, local_target)
        site = _site()
        with pytest.raises(GateFailed):
            service.deploy(site, service.record_build(site, _files(BAD_PAGE)))

        blocked = [
            d
            for d in service.repository.deployments.values()
            if d.status is DeploymentStatus.GATE_FAILED
        ]
        assert blocked, "no record of the refusal"
        assert any("not_mobile_friendly" in finding for finding in blocked[0].gate_findings)

    def test_the_gate_inspects_what_is_served_not_the_build(self, registry, local_target) -> None:
        """A gate reading files off disk cannot catch a web server pointed at
        the wrong directory, which is a real way to ship a broken site."""
        service = _service(registry, local_target)
        site = _site()
        build = service.record_build(site, _files())

        # The build is fine; what gets served is not.
        def broken(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, html=BAD_PAGE)

        service.gate = OutputGate(client=httpx.Client(transport=httpx.MockTransport(broken)))
        with pytest.raises(GateFailed):
            service.deploy(site, build)


class TestVerificationAndRollback:
    def test_a_promotion_that_is_not_reachable_is_not_recorded_as_live(
        self, registry, local_target
    ) -> None:
        """A deploy tool's exit code says the upload worked, not that anyone can
        load the page."""
        service = _service(registry, local_target)
        site = _site()
        build = service.record_build(site, _files())

        def gone(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="unavailable")

        service.verifier = httpx.Client(transport=httpx.MockTransport(gone))
        deployment = service.deploy(site, build)
        assert deployment.status is DeploymentStatus.FAILED
        assert "not reachable" in (deployment.detail or "")

    def test_rollback_returns_the_previous_version(self, registry, local_target) -> None:
        service = _service(registry, local_target)
        site = _site()

        first = service.deploy(site, service.record_build(site, _files()))
        second_page = GOOD_PAGE.replace("<h1>Teqtronix</h1>", "<h1>Teqtronix Trading</h1>")
        second = service.deploy(site, service.record_build(site, _files(second_page)))
        assert second.build_fingerprint != first.build_fingerprint

        restored = service.rollback(site)

        assert restored.status is DeploymentStatus.LIVE
        assert restored.build_fingerprint == first.build_fingerprint
        slug = f"site-{site.id[:12]}"
        assert "<h1>Teqtronix</h1>" in (local_target.read(slug, restored.remote_id or "") or "")

    def test_rollback_republishes_from_atlas_rather_than_asking_the_host(
        self, registry, local_target
    ) -> None:
        """A rollback that depends on a provider's retention is a provider
        feature wearing Atlas's name. Deleting the old version from the host
        must not stop it."""
        service = _service(registry, local_target)
        site = _site()
        slug = f"site-{site.id[:12]}"

        first = service.deploy(site, service.record_build(site, _files()))
        second = service.deploy(
            site, service.record_build(site, _files(GOOD_PAGE.replace("Trading", "Group")))
        )
        assert second.status is DeploymentStatus.LIVE

        # The host prunes the old deployment. Atlas still holds the artifact.
        import shutil

        shutil.rmtree(local_target.root / slug / "versions" / (first.remote_id or ""))

        restored = service.rollback(site)
        assert restored.status is DeploymentStatus.LIVE
        assert restored.build_fingerprint == first.build_fingerprint

    def test_rollback_with_no_history_says_so(self, registry, local_target) -> None:
        from atlas_kernel.website.service import RollbackImpossible

        service = _service(registry, local_target)
        site = _site()
        service.deploy(site, service.record_build(site, _files()))
        with pytest.raises(RollbackImpossible, match="no earlier deployment"):
            service.rollback(site)


class TestTargetSelection:
    def test_local_is_preferred_when_nothing_is_named(self, tmp_path: Path) -> None:
        registry = DeploymentTargetRegistry()
        cloud = LocalDirectoryTarget(tmp_path / "c", base_url="https://c.test", name="cloud")
        near = LocalDirectoryTarget(tmp_path / "l", base_url="https://l.test", name="near")
        registry.register(TargetRegistration(target=cloud, is_local=False))
        registry.register(TargetRegistration(target=near, is_local=True))
        assert registry.resolve().name == "near"

    def test_an_unregistered_target_is_refused_rather_than_substituted(self, registry) -> None:
        """Silently deploying a customer's site somewhere other than asked is
        worse than not deploying it."""
        with pytest.raises(NoTargetAvailable, match="not registered"):
            registry.resolve("somewhere-else")

    def test_no_targets_at_all_names_the_capability(self) -> None:
        with pytest.raises(NoTargetAvailable, match="site.deploy"):
            DeploymentTargetRegistry().resolve()

    def test_re_registering_a_target_replaces_it(self, tmp_path: Path) -> None:
        registry = DeploymentTargetRegistry()
        for _ in range(2):
            registry.register(
                TargetRegistration(
                    target=LocalDirectoryTarget(tmp_path, base_url="https://x.test", name="same")
                )
            )
        assert len(registry.targets) == 1


class TestTheBusinessTimeline:
    def test_every_step_lands_on_the_company_history(self, registry, local_target) -> None:
        service = _service(registry, local_target)
        site = _site()
        service.deploy(site, service.record_build(site, _files()))

        kinds = [event.kind for event in service.repository.events]
        assert kinds == ["built", "published", "deployed"]
        assert {event.factory for event in service.repository.events} == {"website"}
        assert {event.business_id for event in service.repository.events} == {site.business_id}

    def test_a_refusal_is_recorded_not_swallowed(self, registry, local_target) -> None:
        service = _service(registry, local_target)
        site = _site()
        with pytest.raises(GateFailed):
            service.deploy(site, service.record_build(site, _files(BAD_PAGE)))
        assert "gate_failed" in [event.kind for event in service.repository.events]

    def test_website_events_do_not_collide_with_the_opportunity_funnel(
        self, registry, local_target
    ) -> None:
        """Namespacing is why 'deployed' can never be mistaken for a funnel
        stage, and why the Opportunity Factory's rates stay correct."""
        from atlas_kernel.opportunity.metrics import build_report

        service = _service(registry, local_target)
        site = _site()
        service.deploy(site, service.record_build(site, _files()))
        report = build_report(service.repository.events)
        assert report.counts["sent"] == 0
        assert report.counts["discovered"] == 0


class TestSites:
    def test_a_site_must_be_named(self) -> None:
        with pytest.raises(ValueError, match="must have a name"):
            Site(business_id="b", name="   ")

    def test_a_site_identifies_its_customer_only_by_business_id(self) -> None:
        """There is no WebsiteClient and there never will be."""
        assert "business_id" in Site.model_fields
        assert not any("client" in name.lower() for name in Site.model_fields)


class TestSerialisation:
    def test_a_build_round_trips_through_json(self) -> None:
        """The artifact is stored as JSON. If it does not survive that, "rebuild
        from Business memory" is a claim about nothing."""
        build = SiteBuild(site_id="s", business_id="b", files=_files())
        restored = SiteBuild(**{**build.model_dump(), "files": json.loads(json.dumps(build.files))})
        assert restored.fingerprint == build.fingerprint
