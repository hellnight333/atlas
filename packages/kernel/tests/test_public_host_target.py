"""The public deployment target, and the claim it refuses to make.

Every earlier way of being wrong about a deployment — files in place but the
server not reloaded, a symlink pointing at a removed version, a different site
matching the address — looks like success from the publishing side and like a
404 to the customer. So promotion here is not complete until the public URL has
been fetched and inspected.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from atlas_kernel.website.targets.public_host import (
    HOST_HEADER,
    DeploymentUnreachable,
    PublicHostTarget,
)

pytestmark = pytest.mark.integration

PAGE = {"index.html": "<!doctype html><title>Live</title><h1>Deployed by Qevik</h1>"}


def _target(tmp_path: Path, handler, *, base_url="https://sites.example.com", **kwargs):
    return PublicHostTarget(
        tmp_path / "srv",
        base_url=base_url,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


def _serving(body: str = PAGE["index.html"], status: int = 200, qevik: bool = True):
    def handler(request: httpx.Request) -> httpx.Response:
        headers = {HOST_HEADER: "sites"} if qevik else {}
        return httpx.Response(status, text=body, headers=headers)

    return handler


class TestItRefusesToClaimSuccess:
    def test_an_unreachable_url_fails_the_promotion(self, tmp_path: Path) -> None:
        """Publishing succeeded, the symlink swapped, and the customer still
        gets nothing. That is a failed deployment."""

        def dead(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        target = _target(tmp_path, dead)
        version = target.publish("site", PAGE)
        with pytest.raises(DeploymentUnreachable, match="did not serve it"):
            target.promote("site", version.id)

    def test_a_404_from_the_public_url_fails_the_promotion(self, tmp_path: Path) -> None:
        target = _target(tmp_path, _serving(status=404))
        version = target.publish("site", PAGE)
        with pytest.raises(DeploymentUnreachable):
            target.promote("site", version.id)

    def test_a_served_page_promotes_and_returns_the_url(self, tmp_path: Path) -> None:
        target = _target(tmp_path, _serving())
        version = target.publish("site", PAGE)
        assert target.promote("site", version.id) == "https://sites.example.com/site/"

    def test_verification_can_be_turned_off_for_a_host_not_yet_serving(
        self, tmp_path: Path
    ) -> None:
        """Publishing before the web server exists is legitimate; claiming it is
        live is not. The flag is explicit so the claim is never implied."""

        def dead(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        target = _target(tmp_path, dead, verify_on_promote=False)
        version = target.publish("site", PAGE)
        assert target.promote("site", version.id).endswith("/site/")


class TestVerification:
    def test_it_reports_what_actually_came_back(self, tmp_path: Path) -> None:
        target = _target(tmp_path, _serving())
        result = target.verify("https://sites.example.com/site/", expect="Deployed by Qevik")
        assert result["reachable"]
        assert result["status"] == 200
        assert result["served_by_qevik"]
        assert result["bytes"] > 0

    def test_missing_expected_content_is_a_problem(self, tmp_path: Path) -> None:
        target = _target(tmp_path, _serving())
        result = target.verify("https://sites.example.com/site/", expect="Something Else")
        assert not result["reachable"]
        assert "Something Else" in result["error"]

    def test_a_page_without_the_host_header_is_flagged(self, tmp_path: Path) -> None:
        """A parked page answering 200 is otherwise indistinguishable from a
        successful deployment."""
        target = _target(tmp_path, _serving(qevik=False))
        result = target.verify("https://sites.example.com/site/")
        assert not result["served_by_qevik"]
        assert HOST_HEADER in result["error"]

    def test_an_unreachable_host_is_reported_not_raised(self, tmp_path: Path) -> None:
        """So a caller can record the evidence of a failure."""

        def dead(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route")

        result = _target(tmp_path, dead).verify("https://sites.example.com/site/")
        assert result["reachable"] is False
        assert result["status"] == 0
        assert "could not reach" in result["error"]


class TestHonestyAboutTls:
    def test_an_ip_address_host_is_not_described_as_secure(self, tmp_path: Path) -> None:
        """A certificate authority will not issue for a bare IP, so a host
        without a domain is plain HTTP. Calling it secure would be the one lie
        this module exists to prevent."""
        target = _target(tmp_path, _serving(), base_url="http://203.0.113.10")
        assert target.is_secure is False
        assert target.verify("http://203.0.113.10/site/")["secure"] is False

    def test_an_https_host_is(self, tmp_path: Path) -> None:
        assert _target(tmp_path, _serving()).is_secure is True


class TestVersionsAndRollback:
    def test_rollback_is_an_ordinary_promotion(self, tmp_path: Path) -> None:
        """Not a special path — the same swap, which is what makes it
        trustworthy under pressure."""
        target = _target(tmp_path, _serving())
        first = target.publish("site", PAGE)
        second = target.publish("site", {"index.html": "<title>Live</title>v2"})
        target.promote("site", second.id)
        assert target.live_version("site") == second.id

        target.rollback("site", first.id)
        assert target.live_version("site") == first.id

    def test_versions_lists_what_rollback_may_choose_from(self, tmp_path: Path) -> None:
        target = _target(tmp_path, _serving())
        ids = {target.publish("site", PAGE).id, target.publish("site", {"a.html": "x"}).id}
        assert set(target.versions("site")) == ids

    def test_an_unknown_site_has_no_versions(self, tmp_path: Path) -> None:
        assert _target(tmp_path, _serving()).versions("never-deployed") == []

    def test_status_says_nothing_is_deployed_before_anything_is(self, tmp_path: Path) -> None:
        status = _target(tmp_path, _serving()).status("never-deployed")
        assert status["deployed"] is False
        assert status["live_version"] is None

    def test_status_reports_the_live_version_and_checks_it(self, tmp_path: Path) -> None:
        target = _target(tmp_path, _serving())
        version = target.publish("site", PAGE)
        target.promote("site", version.id)
        status = target.status("site")
        assert status["deployed"] and status["live_version"] == version.id
        assert status["reachable"] and status["status"] == 200


class TestTheAuthorisationBoundary:
    def test_it_declares_itself_public(self) -> None:
        """Read by the deploy handler: anything a stranger can open is a
        publication and needs approval."""
        assert PublicHostTarget.is_public is True

    def test_the_deploy_handler_refuses_it_without_approval(self, tmp_path: Path) -> None:
        from atlas_kernel.actions.handlers import PublishNotAuthorised, site_deploy

        class Ctx:
            approvals = None
            deploy_target = _target(tmp_path, _serving())

        with pytest.raises(PublishNotAuthorised, match="outward-facing"):
            site_deploy({"slug": "site"}, Ctx())
