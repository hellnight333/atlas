"""Could a machine anywhere but this host join the fleet?

A Qevik worker connects straight to Postgres — there is no worker API, and
adding one would be a second way in for no gain. So a second machine can only
join if the ledger is reachable from somewhere other than the control-plane
host.

Measured on 2026-08-30: Postgres listened on `127.0.0.1` only and Tailscale was
not installed, so a fully provisioned Z8 with an approved Tailscale login had
nothing to connect to. The provisioning actions were written as though a tailnet
existed. This is why the check exists rather than a comment saying it should.

Reads the configured DSN and the host's own interfaces. Opens no socket to
anywhere, and never reports the DSN itself — it carries a password.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urlparse

#: Where the ledger lives, by the same variable the worker would read.
DSN_VARIABLE = "ATLAS_DATABASE_URL"


@dataclass(frozen=True)
class Reachability:
    """Whether another machine could connect, and what stops it.

    `reachable is None` means it could not be determined. That is distinct from
    `False`: asking somebody to open a database to a network because a check
    failed is worse than saying nothing.
    """

    reachable: bool | None
    #: Never the DSN. Just the part that decides the answer.
    host: str = ""
    because: str = ""

    def summary(self) -> dict:
        return {"reachable": self.reachable, "host": self.host,
                "because": self.because}


def _host_of(dsn: str) -> str:
    """The host a DSN points at, without the credentials in it."""
    try:
        parsed = urlparse(dsn)
    except ValueError:
        return ""
    return (parsed.hostname or "").strip()


def measure(dsn: str | None = None) -> Reachability:
    """Whether a worker on another machine could reach the ledger.

    Deliberately conservative and deliberately cheap: this answers from the
    address the ledger is configured on, not by trying to connect from
    somewhere else — which is not a thing this process can do.

    A loopback address is a definite no: nothing outside the host can route to
    it. Anything else is *not* a yes — the address may be firewalled, or
    `pg_hba.conf` may refuse the user — so it is reported as undetermined rather
    than as working. The failure that matters here is a false "yes" telling
    somebody the fleet is ready when the first real worker will fail to connect.
    """
    raw = dsn if dsn is not None else os.environ.get(DSN_VARIABLE, "")
    if not raw:
        return Reachability(
            reachable=None,
            because=f"{DSN_VARIABLE} is not set in this process, so where the "
                    "ledger lives is unknown here.")
    host = _host_of(raw)
    if not host:
        return Reachability(
            reachable=None,
            because="the configured ledger address named no host.")
    if host in {"localhost", "localhost.localdomain"}:
        return Reachability(
            reachable=False, host=host,
            because="the ledger is configured as localhost, which no other "
                    "machine can route to.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # A name. It may well resolve to something routable, and resolving it
        # here would be measuring this host's resolver rather than the fleet's.
        return Reachability(
            reachable=None, host=host,
            because=f"the ledger is configured at {host}, a name this check "
                    "does not resolve. Whether a worker elsewhere can reach it "
                    "is answered by a worker elsewhere.")
    if address.is_loopback:
        return Reachability(
            reachable=False, host=host,
            because=f"the ledger is on {host}, a loopback address. Nothing "
                    "outside this machine can route to it.")
    return Reachability(
        reachable=None, host=host,
        because=f"the ledger is on {host}, which is not loopback. Whether a "
                "worker elsewhere can actually connect depends on the firewall "
                "and on pg_hba.conf, neither of which this reads.")


__all__ = ["DSN_VARIABLE", "Reachability", "measure"]
