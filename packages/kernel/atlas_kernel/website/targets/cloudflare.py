"""Cloudflare Pages. The other shape.

This adapter exists to prove the interface does not leak the local one's
assumptions. A single implementation cannot demonstrate that, and an interface
validated only in prose is validated by nobody — so the second target is written
against a host that works differently in every way that matters:

* there is no filesystem, no path and no symlink
* publishing returns a **deployment id the host invents**, not one Atlas derives
* every deployment gets its own preview URL from the host
* promotion is an API call against that id, not an atomic rename

Everything the local target relies on is absent here, and the interface survives
unchanged, which is the evidence that ``publish``-then-``promote`` is the real
common shape rather than a local-filesystem idea with different words.

**Untested against the live API.** No Cloudflare credentials exist yet, so this
is written against the documented API and exercised through a controlled
transport. It is honest to say that means the request *shapes* are verified and
the API's real behaviour is not. The first real deployment will find whatever is
wrong; the interface it is written against will not be the thing that is wrong.
"""

from __future__ import annotations

import httpx

from .base import DeploymentError, PublishedVersion

API_ROOT = "https://api.cloudflare.com/client/v4"
#: Generous. An upload is many files over one request and a slow link is not a
#: failure.
REQUEST_TIMEOUT_SECONDS = 120.0


class CloudflarePagesTarget:
    """Publishes to a Cloudflare Pages project.

    ``client`` is injectable so the request shapes can be exercised without a
    token. Nothing here special-cases being under test — an adapter that behaves
    differently in tests is an adapter whose tests prove nothing.
    """

    def __init__(
        self,
        *,
        account_id: str,
        project: str,
        api_token: str,
        client: httpx.Client | None = None,
        name: str = "cloudflare-pages",
    ) -> None:
        self._account_id = account_id
        self._project = project
        self._api_token = api_token
        self._client = client
        self._owns_client = client is None
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={"Authorization": f"Bearer {self._api_token}"},
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    @property
    def _base(self) -> str:
        return f"{API_ROOT}/accounts/{self._account_id}/pages/projects/{self._project}"

    # -- the interface ----------------------------------------------------

    def publish(self, site_slug: str, files: dict[str, str]) -> PublishedVersion:
        """Upload a build. Cloudflare returns the id and the preview URL.

        Note what Atlas does *not* do here: it does not choose the version id.
        The local target derives one from content; this host invents one. The
        interface treats both as opaque, which is the only reason both fit.
        """
        response = self._request(
            "POST",
            f"{self._base}/deployments",
            json={
                "branch": site_slug,
                "files": {path: {"content": body} for path, body in files.items()},
            },
        )
        result = response.get("result") or {}
        deployment_id = result.get("id")
        preview_url = result.get("url")
        if not deployment_id or not preview_url:
            raise DeploymentError(
                f"Cloudflare accepted the upload but returned no deployment id or url: {result!r}"
            )
        return PublishedVersion(
            id=str(deployment_id),
            preview_url=str(preview_url),
            detail=f"uploaded {len(files)} files to project {self._project}",
        )

    def promote(self, site_slug: str, version_id: str) -> str:
        response = self._request("POST", f"{self._base}/deployments/{version_id}/retry")
        result = response.get("result") or {}
        # The canonical project URL, not the per-deployment preview one: the
        # point of promotion is that visitors reach a stable address.
        live = result.get("url") or f"https://{self._project}.pages.dev"
        return str(live)

    def remove(self, site_slug: str, version_id: str) -> None:
        self._request("DELETE", f"{self._base}/deployments/{version_id}")

    # -- transport --------------------------------------------------------

    def _request(self, method: str, url: str, **kwargs) -> dict:
        """One place where an HTTP failure becomes a DeploymentError.

        Cloudflare reports application errors inside a 200 body as well as by
        status code, so both are checked. Trusting the status alone would let a
        refused deployment look like a successful one, and the next step would
        promote nothing to production.
        """
        try:
            response = self._get_client().request(method, url, **kwargs)
        except httpx.HTTPError as error:
            raise DeploymentError(f"{method} {url} failed: {error}") from error

        if response.status_code >= 400:
            raise DeploymentError(
                f"{method} {url} returned {response.status_code}: {response.text[:300]}"
            )

        try:
            payload = response.json()
        except ValueError as error:
            raise DeploymentError(f"{method} {url} returned a non-JSON body") from error

        if isinstance(payload, dict) and payload.get("success") is False:
            errors = payload.get("errors") or []
            raise DeploymentError(f"Cloudflare refused {method} {url}: {errors}")
        return payload if isinstance(payload, dict) else {}
