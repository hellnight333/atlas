"""Persistence for the Website Factory (M015).

The claim this file has to make true: **the artifact is in the database.**

Everything else here is ordinary round-tripping. But "rebuild from Business
memory" and "moving a customer between providers is a normal deployment" are
both the same fact — Atlas holds the bytes — and a row pointing at a directory
on somebody's laptop would satisfy every type in the package while making both
claims false.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from atlas_kernel import db
from atlas_kernel.opportunity.models import BusinessEvent
from atlas_kernel.website.models import (
    Deployment,
    DeploymentStatus,
    Site,
    SiteBuild,
)
from atlas_kernel.website.repository import WebsiteRepository

PAGE = (
    "<!doctype html><html><head><title>T</title>"
    '<meta name="viewport" content="width=device-width"></head>'
    "<body><h1>T</h1><p>Content.</p></body></html>"
)


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


@pytest.fixture
def repo() -> WebsiteRepository:
    return WebsiteRepository()


@pytest.fixture
def unique() -> str:
    return uuid4().hex[:10]


def _site(unique: str) -> Site:
    return Site(
        business_id=f"biz-{unique}",
        name="Teqtronix",
        domain=f"{unique}.test",
        content={"tagline": "Electronics trading"},
    )


def _files() -> dict[str, str]:
    return {"index.html": PAGE, "styles.css": "body{margin:0}"}


class TestSites:
    def test_round_trip(self, repo: WebsiteRepository, unique: str) -> None:
        saved = repo.save_site(_site(unique))
        loaded = repo.get_site(saved.id)
        assert loaded is not None
        assert loaded.domain == f"{unique}.test"
        assert loaded.content == {"tagline": "Electronics trading"}

    def test_saving_twice_updates_rather_than_duplicating(
        self, repo: WebsiteRepository, unique: str
    ) -> None:
        site = repo.save_site(_site(unique))
        repo.save_site(site.model_copy(update={"domain": "moved.test"}))
        loaded = repo.get_site(site.id)
        assert loaded is not None and loaded.domain == "moved.test"

    def test_sites_are_found_by_business(self, repo: WebsiteRepository, unique: str) -> None:
        site = repo.save_site(_site(unique))
        assert [s.id for s in repo.list_sites(business_id=site.business_id)] == [site.id]

    def test_unknown_site_is_none(self, repo: WebsiteRepository) -> None:
        assert repo.get_site("does-not-exist") is None


class TestTheArtifactIsInTheDatabase:
    def test_the_files_themselves_survive_the_round_trip(
        self, repo: WebsiteRepository, unique: str
    ) -> None:
        """Not a path, not a reference — the bytes. This is the whole mechanism
        behind rebuild-from-memory and behind changing host without a migration."""
        site = repo.save_site(_site(unique))
        build = repo.save_build(
            SiteBuild(site_id=site.id, business_id=site.business_id, files=_files())
        )
        loaded = repo.get_build(build.id)
        assert loaded is not None
        assert loaded.files == _files()
        assert loaded.files["index.html"] == PAGE

    def test_the_fingerprint_survives_and_still_matches(
        self, repo: WebsiteRepository, unique: str
    ) -> None:
        """Stored once, recomputed on read. The redundancy is the check: it
        catches both an altered record and non-deterministic rendering."""
        site = repo.save_site(_site(unique))
        build = repo.save_build(
            SiteBuild(site_id=site.id, business_id=site.business_id, files=_files())
        )
        loaded = repo.get_build(build.id)
        assert loaded is not None
        assert loaded.fingerprint == build.fingerprint
        assert repo.stored_fingerprint(build.id) == build.fingerprint

    def test_provenance_survives(self, repo: WebsiteRepository, unique: str) -> None:
        site = repo.save_site(_site(unique))
        build = repo.save_build(
            SiteBuild(
                site_id=site.id,
                business_id=site.business_id,
                files=_files(),
                generator="authored",
                provenance={"theme": "clean-v1", "author": "ayoub"},
            )
        )
        loaded = repo.get_build(build.id)
        assert loaded is not None
        assert loaded.provenance == {"theme": "clean-v1", "author": "ayoub"}
        assert loaded.generator == "authored"

    def test_builds_are_listed_for_a_site(self, repo: WebsiteRepository, unique: str) -> None:
        site = repo.save_site(_site(unique))
        for suffix in ("a", "b"):
            repo.save_build(
                SiteBuild(
                    site_id=site.id,
                    business_id=site.business_id,
                    files={"index.html": PAGE.replace("<h1>T</h1>", f"<h1>{suffix}</h1>")},
                )
            )
        assert len(repo.list_builds(site.id)) == 2

    def test_unknown_build_is_none(self, repo: WebsiteRepository) -> None:
        assert repo.get_build("does-not-exist") is None
        assert repo.stored_fingerprint("does-not-exist") is None


class TestDeployments:
    def _deployment(self, site: Site, build: SiteBuild, **overrides) -> Deployment:
        payload = {
            "build_id": build.id,
            "site_id": site.id,
            "business_id": site.business_id,
            "target": "local",
            "build_fingerprint": build.fingerprint,
        }
        payload.update(overrides)
        return Deployment(**payload)

    def _prepared(self, repo: WebsiteRepository, unique: str) -> tuple[Site, SiteBuild]:
        site = repo.save_site(_site(unique))
        build = repo.save_build(
            SiteBuild(site_id=site.id, business_id=site.business_id, files=_files())
        )
        return site, build

    def test_a_deployment_updates_in_place_as_it_progresses(
        self, repo: WebsiteRepository, unique: str
    ) -> None:
        site, build = self._prepared(repo, unique)
        deployment = repo.save_deployment(self._deployment(site, build))
        repo.save_deployment(
            deployment.model_copy(
                update={
                    "status": DeploymentStatus.LIVE,
                    "live_url": "https://x.test/",
                    "remote_id": "v1",
                }
            )
        )
        loaded = repo.get_deployment(deployment.id)
        assert loaded is not None
        assert loaded.status is DeploymentStatus.LIVE
        assert loaded.live_url == "https://x.test/"

    def test_gate_findings_survive(self, repo: WebsiteRepository, unique: str) -> None:
        """A refusal that loses its reasons is a refusal nobody can act on."""
        site, build = self._prepared(repo, unique)
        deployment = repo.save_deployment(
            self._deployment(
                site,
                build,
                status=DeploymentStatus.GATE_FAILED,
                gate_findings=["missing_title: The page has no title."],
            )
        )
        loaded = repo.get_deployment(deployment.id)
        assert loaded is not None
        assert loaded.gate_findings == ["missing_title: The page has no title."]

    def test_atlas_knows_what_is_live(self, repo: WebsiteRepository, unique: str) -> None:
        """Atlas's record, never read back from a provider's API — which depends
        on an account that can be closed."""
        site, build = self._prepared(repo, unique)
        repo.save_deployment(self._deployment(site, build, status=DeploymentStatus.SUPERSEDED))
        live = repo.save_deployment(self._deployment(site, build, status=DeploymentStatus.LIVE))
        assert (found := repo.live_deployment(site.id)) is not None
        assert found.id == live.id

    def test_one_build_can_be_live_on_two_hosts_at_once(
        self, repo: WebsiteRepository, unique: str
    ) -> None:
        """The same artifact on Cloudflare and Hetzner is two deployments of one
        build. That is what makes moving a customer a promotion rather than a
        rebuild."""
        site, build = self._prepared(repo, unique)
        repo.save_deployment(
            self._deployment(site, build, target="cloudflare", status=DeploymentStatus.LIVE)
        )
        repo.save_deployment(
            self._deployment(site, build, target="hetzner", status=DeploymentStatus.LIVE)
        )
        assert (a := repo.live_deployment(site.id, "cloudflare")) is not None
        assert (b := repo.live_deployment(site.id, "hetzner")) is not None
        assert a.build_id == b.build_id == build.id

    def test_superseding_leaves_the_new_one_alone(
        self, repo: WebsiteRepository, unique: str
    ) -> None:
        site, build = self._prepared(repo, unique)
        old = repo.save_deployment(self._deployment(site, build, status=DeploymentStatus.LIVE))
        new = repo.save_deployment(self._deployment(site, build, status=DeploymentStatus.LIVE))
        repo.supersede_live(site.id, "local", except_id=new.id)

        assert (was_old := repo.get_deployment(old.id)) is not None
        assert (still_new := repo.get_deployment(new.id)) is not None
        assert was_old.status is DeploymentStatus.SUPERSEDED
        assert still_new.status is DeploymentStatus.LIVE

    def test_rollback_targets_the_last_thing_that_actually_served(
        self, repo: WebsiteRepository, unique: str
    ) -> None:
        """Failed and gate-blocked deployments never reached a visitor, so going
        "back" to one would be going somewhere new."""
        site, build = self._prepared(repo, unique)
        served = repo.save_deployment(
            self._deployment(site, build, status=DeploymentStatus.SUPERSEDED)
        )
        repo.save_deployment(self._deployment(site, build, status=DeploymentStatus.GATE_FAILED))
        repo.save_deployment(self._deployment(site, build, status=DeploymentStatus.FAILED))

        assert (previous := repo.previous_deployment(site.id, "local")) is not None
        assert previous.id == served.id

    def test_no_history_means_no_previous_deployment(
        self, repo: WebsiteRepository, unique: str
    ) -> None:
        site, build = self._prepared(repo, unique)
        repo.save_deployment(self._deployment(site, build, status=DeploymentStatus.LIVE))
        assert repo.previous_deployment(site.id, "local") is None

    def test_deployments_are_listed_for_a_site(self, repo: WebsiteRepository, unique: str) -> None:
        site, build = self._prepared(repo, unique)
        for _ in range(3):
            repo.save_deployment(self._deployment(site, build))
        assert len(repo.list_deployments(site.id)) == 3


class TestTheSharedTimeline:
    def test_website_events_go_to_the_business_timeline_not_a_website_one(
        self, repo: WebsiteRepository, unique: str
    ) -> None:
        """One company, one history. A separate website log would split it, and
        the split is invisible until someone asks what Atlas has done for a
        customer."""
        site = repo.save_site(_site(unique))
        repo.record_event(
            BusinessEvent(business_id=site.business_id, factory="website", kind="deployed")
        )
        history = repo.timeline(site.business_id)
        assert [(e.factory, e.kind) for e in history] == [("website", "deployed")]

    def test_the_timeline_is_shared_with_the_opportunity_factory(
        self, repo: WebsiteRepository, unique: str
    ) -> None:
        from atlas_kernel.opportunity.repository import OpportunityRepository

        site = repo.save_site(_site(unique))
        OpportunityRepository().record_event(
            BusinessEvent(business_id=site.business_id, kind="sent")
        )
        repo.record_event(
            BusinessEvent(business_id=site.business_id, factory="website", kind="deployed")
        )
        assert [e.kind for e in repo.timeline(site.business_id)] == ["sent", "deployed"]
