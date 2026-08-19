"""Cloudflare zone maintenance for qevik.ai, with the write path held shut.

The token this uses can edit any DNS record in the zone. That is the ceiling
Cloudflare enforces; it is not the policy. A permission model that stops at
"what the credential allows" gives an autonomous system the ability to repoint
`qevik.ai` at nothing and take the business offline in one call — a capability
nothing here needs and no operation has ever asked for.

So the policy lives here, below the credential:

- **Reads are free.** Listing records and reading the zone cannot break
  anything, and being unable to see the current state is what makes DNS
  problems get misdiagnosed as server problems.
- **Writes are refused by default** and permitted only for a narrow shape:
  creating or reclaiming an `A` record for a *new* subdomain that points at this
  server. Everything else — the four production records, `NS`, `MX`, `SOA`,
  DNSSEC, and deletion of anything at all — is refused in code, whatever the
  token permits.
- **A permitted write still needs a human.** It carries `Risk.PUBLIC` and goes
  through the same approval gate as publishing a site, bound to a fingerprint of
  the exact record being changed.

Registrar and delegation settings are not reachable at all: the token carries no
account-level permission, and this module has no code path to them.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

API = "https://api.cloudflare.com/client/v4"

ZONE = "qevik.ai"

#: This server. A record may only be pointed here.
ORIGIN_IP = "2.28.62.83"

#: The records that serve production. Editing one of these takes the site,
#: the control plane or every customer demo offline at once, and no operation
#: needs to: new work creates new subdomains.
PROTECTED = frozenset({ZONE, f"www.{ZONE}", f"app.{ZONE}", f"sites.{ZONE}"})

#: Record types this module will write. Everything else — NS (delegation), MX
#: (mail), SOA (zone authority), DNSKEY/DS (DNSSEC) — is refused regardless of
#: what the token allows.
WRITABLE_TYPES = frozenset({"A"})

#: A subdomain label: what a generated site's hostname may look like.
_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class CloudflareUnavailable(RuntimeError):
    """No token is configured. Not an error — an absent optional credential."""


class CloudflareRefused(PermissionError):
    """The change is outside what this module will do, whatever the token allows."""


class CloudflareError(RuntimeError):
    """Cloudflare rejected the call. Carries its code, never the token."""


def token() -> str:
    value = os.environ.get("QEVIK_CLOUDFLARE_API_TOKEN", "").strip()
    if not value:
        raise CloudflareUnavailable(
            "QEVIK_CLOUDFLARE_API_TOKEN is not set. It belongs in "
            "/opt/qevik/cloudflare.env (0600), loaded with EnvironmentFile=-. "
            "See infra/cloudflare_token.md."
        )
    return value


@dataclass(frozen=True)
class Record:
    id: str
    name: str
    type: str
    content: str
    proxied: bool

    def __str__(self) -> str:
        via = "proxied" if self.proxied else "DNS-only"
        return f"{self.name:<24} {self.type:<6} {self.content:<20} {via}"


def check_writable(name: str, record_type: str, content: str) -> None:
    """Refuse anything outside the one shape this module is allowed to write.

    Separate from the call that performs the write, and importing cleanly, so
    the policy can be tested without a token, a network or a live zone — the
    conditions under which nobody writes the test.
    """
    name = name.strip().lower().rstrip(".")

    if record_type not in WRITABLE_TYPES:
        raise CloudflareRefused(
            f"{record_type} records are never written by Qevik — only "
            f"{'/'.join(sorted(WRITABLE_TYPES))}. NS and MX in particular are "
            "delegation and mail, which are out of scope by decision."
        )

    if name in PROTECTED:
        raise CloudflareRefused(
            f"{name} serves production and is protected. New work gets a new "
            "subdomain; it does not edit an existing one."
        )

    if not name.endswith(f".{ZONE}"):
        raise CloudflareRefused(f"{name} is not in {ZONE}")

    label = name[: -len(f".{ZONE}")]
    if "." in label or not _LABEL.match(label):
        raise CloudflareRefused(
            f"{label!r} is not a single valid subdomain label. Nested names are "
            "refused because they are how a record like a.www.qevik.ai slips "
            "past a check written for one level."
        )

    if content != ORIGIN_IP:
        raise CloudflareRefused(
            f"an A record may only point at {ORIGIN_IP} (this server), not {content}. "
            "Pointing a Qevik hostname somewhere else is not infrastructure "
            "maintenance."
        )


class Cloudflare:
    """A thin client. Reads freely; writes only what `check_writable` permits."""

    def __init__(self, *, api_token: str | None = None, timeout: float = 20.0) -> None:
        self._token = api_token or token()
        self._client = httpx.Client(
            base_url=API,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        self._zone_id: str | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Cloudflare:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, **kwargs)
        try:
            body = response.json()
        except ValueError:
            # The token can appear in neither branch: this reports the status
            # and the body, and the token only ever travels in a header.
            raise CloudflareError(
                f"{method} {path} returned {response.status_code} and no JSON"
            ) from None
        if not body.get("success"):
            errors = "; ".join(
                f"{e.get('code')}: {e.get('message')}" for e in body.get("errors", [])
            )
            raise CloudflareError(f"{method} {path} failed — {errors or response.status_code}")
        return body.get("result")

    # --- reads ---------------------------------------------------------------

    def zone_id(self) -> str:
        if self._zone_id is None:
            result = self._call("GET", "/zones", params={"name": ZONE})
            if not result:
                raise CloudflareError(f"the token cannot see a zone named {ZONE}")
            self._zone_id = result[0]["id"]
        return self._zone_id

    def zone(self) -> dict[str, Any]:
        result = self._call("GET", "/zones", params={"name": ZONE})
        if not result:
            raise CloudflareError(f"the token cannot see a zone named {ZONE}")
        return result[0]

    def records(self) -> list[Record]:
        result = self._call(
            "GET", f"/zones/{self.zone_id()}/dns_records", params={"per_page": 200}
        )
        return [
            Record(
                id=row["id"],
                name=row["name"],
                type=row["type"],
                content=row.get("content", ""),
                proxied=bool(row.get("proxied")),
            )
            for row in result
        ]

    def find(self, name: str) -> Record | None:
        name = name.strip().lower().rstrip(".")
        return next((r for r in self.records() if r.name == name), None)

    # --- the one write --------------------------------------------------------

    def point_subdomain(
        self, name: str, *, approval: Any, proxied: bool = True
    ) -> Record:
        """Create, or reclaim, an A record for a new subdomain pointing here.

        `approval` is the consent object for this specific change. It is checked
        before the policy so an unapproved call is refused even when it happens
        to be a permitted shape — the two are independent gates and the cheaper
        one goes first only when it cannot leak information.
        """
        if approval is None or not getattr(approval, "approved", False):
            raise CloudflareRefused(
                "a DNS change is outward-facing and needs an approval bound to "
                "this exact record. Nothing here creates its own."
            )

        check_writable(name, "A", ORIGIN_IP)
        name = name.strip().lower().rstrip(".")

        payload = {
            "type": "A",
            "name": name,
            "content": ORIGIN_IP,
            "proxied": proxied,
            "ttl": 1,
        }

        existing = self.find(name)
        if existing is None:
            row = self._call("POST", f"/zones/{self.zone_id()}/dns_records", json=payload)
        else:
            # Only reclaim a record that already points at this server. An
            # existing record aimed elsewhere belongs to something else, and
            # taking it over is exactly the hostile act this module refuses.
            if existing.type != "A" or existing.content != ORIGIN_IP:
                raise CloudflareRefused(
                    f"{name} already exists as {existing.type} -> {existing.content}, "
                    f"which is not this server. Repointing an established record "
                    "is not a change Qevik makes on its own."
                )
            row = self._call(
                "PUT",
                f"/zones/{self.zone_id()}/dns_records/{existing.id}",
                json=payload,
            )

        return Record(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            content=row.get("content", ""),
            proxied=bool(row.get("proxied")),
        )

    # Deletion is absent on purpose. No operation needs it, and it is the one
    # DNS mistake with no partial recovery.
