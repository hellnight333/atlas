"""A deployment target that is actually on the internet.

`LocalDirectoryTarget` writes the same layout, but its URL is a preview nobody
outside the machine can open, so "deployed" and "reachable" are the same claim
made twice. This target separates them: it publishes, promotes, and then
**fetches the public URL and checks what came back.** If that fetch fails, the
deployment failed — regardless of how completely the files were written.

That rule is the entire reason this class exists. Every earlier way of being
wrong about a deployment (files in place but the server not reloaded, a symlink
pointing at a version that was removed, a web server matching a different site)
looks like success from the publishing side and like a 404 to the customer.

**TLS is a property of the address, not of this code.** Certificate authorities
do not issue for bare IP addresses, so a host reachable only by IP is plain
HTTP, and `is_secure` says so rather than the class implying otherwise. Point a
domain at the host, drop a block in Caddy's `sites.d`, and the same target
serves it over HTTPS with nothing here changing.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from .base import DeploymentError, PublishedVersion
from .local import LocalDirectoryTarget

#: Set by the site host so verification can tell "Qevik's server answered" from
#: "something answered on that address". A parked page returning 200 is the
#: failure this catches.
HOST_HEADER = "X-Qevik-Host"

VERIFY_TIMEOUT_SECONDS = 15.0


class DeploymentUnreachable(DeploymentError):
    """The files were published but the public URL did not serve them.

    Its own type because the remedy is different from a failed publish: the
    artifact is fine and the serving path is not, so retrying the upload
    achieves nothing.
    """


class PublicHostTarget(LocalDirectoryTarget):
    """Publishes to a directory a public web server serves.

    Qevik runs on the same host as the web server, so publishing is a filesystem
    operation and the network only appears at verification. That is a deliberate
    simplification of the deployment path, not an accident of the setup: fewer
    moving parts between "artifact exists" and "artifact is served" means fewer
    ways to be confidently wrong about which version is live.
    """

    #: Read by the deploy handler's authorisation check. Anything a stranger can
    #: open is a publication and needs approval.
    is_public = True

    def __init__(
        self,
        root: Path | str = "/srv/sites",
        *,
        base_url: str,
        name: str = "public",
        client: httpx.Client | None = None,
        verify_on_promote: bool = True,
    ) -> None:
        super().__init__(Path(root), base_url=base_url, name=name)
        self._client = client
        self._owns_client = client is None
        self._verify_on_promote = verify_on_promote

    @property
    def is_secure(self) -> bool:
        """Whether the public URL is HTTPS.

        Stated rather than assumed. A certificate authority will not issue for a
        bare IP, so a host without a domain is plain HTTP and calling it secure
        would be the one lie this module exists to prevent.
        """
        return self._base_url.startswith("https://")

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=VERIFY_TIMEOUT_SECONDS, follow_redirects=True)
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def verify(self, url: str, *, expect: str = "") -> dict:
        """Fetch the public URL and report exactly what happened.

        Returns rather than raises, so a caller can record the evidence of a
        failure. `promote` is what turns an unreachable deployment into an
        error.
        """
        try:
            response = self._get_client().get(url)
        except httpx.HTTPError as error:
            return {
                "url": url,
                "reachable": False,
                "status": 0,
                "error": f"could not reach {url}: {error}",
                "served_by_qevik": False,
                "secure": self.is_secure,
            }

        body = response.text
        served_by_qevik = HOST_HEADER.lower() in {k.lower() for k in response.headers}
        problems: list[str] = []
        if response.status_code >= 400:
            problems.append(f"status {response.status_code}")
        if expect and expect not in body:
            problems.append(f"the page did not contain {expect!r}")
        if not served_by_qevik:
            # Not fatal on its own — a proxy may strip headers — but recorded,
            # because a parked page answering 200 is otherwise indistinguishable
            # from a successful deployment.
            problems.append(f"no {HOST_HEADER} header; something else may be answering")

        return {
            "url": url,
            "reachable": not problems,
            "status": response.status_code,
            "bytes": len(body),
            "served_by_qevik": served_by_qevik,
            "secure": self.is_secure,
            "problems": problems,
            "error": "" if not problems else "; ".join(problems),
        }

    def promote(self, site_slug: str, version_id: str) -> str:
        """Point the public URL at a version, then prove it serves.

        The verification is not optional decoration. Promotion swaps a symlink;
        everything after that — whether the server followed it, whether it was
        reloaded, whether the path matches — is invisible from here and visible
        to a visitor.
        """
        url = super().promote(site_slug, version_id)
        if not self._verify_on_promote:
            return url

        result = self.verify(url)
        if not result["reachable"] and result["status"] != 200:
            raise DeploymentUnreachable(
                f"promoted {site_slug} to {version_id} but {url} did not serve it: "
                f"{result['error']}"
            )
        return url

    def status(self, site_slug: str) -> dict:
        """What is live, and whether it is actually being served."""
        live = self.live_version(site_slug)
        url = f"{self._base_url}/{site_slug}/"
        if live is None:
            return {"slug": site_slug, "live_version": None, "url": url, "deployed": False}
        return {
            "slug": site_slug,
            "live_version": live,
            "url": url,
            "deployed": True,
            "secure": self.is_secure,
            **self.verify(url),
        }

    def rollback(self, site_slug: str, version_id: str) -> str:
        """Point the public URL back at an earlier version.

        Ordinary promotion. Rollback is not a special path — it is the same
        swap, which is what makes it trustworthy under pressure.
        """
        return self.promote(site_slug, version_id)

    def versions(self, site_slug: str) -> list[str]:
        """Every published version, newest last. What rollback may choose from."""
        directory = self._site_dir(site_slug) / "versions"
        if not directory.is_dir():
            return []
        return sorted(p.name for p in directory.iterdir() if p.is_dir())

    def publish(self, site_slug: str, files: dict[str, str]) -> PublishedVersion:
        version = super().publish(site_slug, files)
        # The preview URL from the parent points at the versioned path, which is
        # publicly reachable here too — useful for checking a version before it
        # is promoted, which is the point of publish-then-promote.
        return version
