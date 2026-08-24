"""Which addresses Qevik is allowed to fetch from.

Research crawls a URL somebody supplied. That URL comes from a customer form, a
directory listing, or a redirect chain Qevik did not choose — and the fetch runs
*inside the deployment's network*.

Without a check, `http://169.254.169.254/latest/meta-data/iam/security-credentials/`
is a valid "business website". Qevik fetches it, gets the instance's cloud
credentials, and files them as research on the timeline: readable through the
customer API, quoted in a proposal, included in a report. `http://127.0.0.1:5432`
and `http://10.0.0.5/admin` are the same shape with different prizes.

So every fetch resolves the hostname first and refuses any address that is not
public. Three details make this an actual defence rather than a gesture:

**Every resolved address, not the first.** A name resolving to one public and
one private address is the standard way past a check that looks at `[0]`.

**Every redirect hop, not only the first request.** A public URL that 302s to
`http://169.254.169.254` defeats an entry-point-only check completely, which is
why `follow_redirects` is turned off and the chain is walked deliberately.

**Refusal is data, not an exception.** A blocked address is recorded as a
`Page` with a reason, exactly like a timeout or a 404, so research reports
`NOT_VERIFIED` rather than crashing — and a business whose site genuinely lives
on a private network is a business we could not check, not one we lie about.

The residual gap, stated rather than hidden: this resolves, then httpx resolves
again when it connects. A name that changes answer between the two calls — DNS
rebinding — passes. Closing it needs connecting to the checked IP with the
hostname in the Host header, which is a transport-level change to how the client
is built. It is recorded in the security review rather than pretended away.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

#: Schemes worth fetching. `file:`, `ftp:`, `gopher:` and friends are refused —
#: `file:///etc/passwd` is a URL, and a crawler that accepts it reads the disk.
ALLOWED_SCHEMES = frozenset({"http", "https"})

#: The cloud metadata address, named because it is the specific prize. On AWS,
#: GCP and Azure it serves instance credentials to anything that asks from
#: inside, with no authentication at all.
METADATA = frozenset({"169.254.169.254", "fd00:ec2::254", "metadata.google.internal"})


class Blocked(Exception):
    """This address must not be fetched, and why."""


def _addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Every address the name resolves to. Raises `Blocked` if it resolves to
    nothing, because an unresolvable host is not a host we can vouch for."""
    try:
        answers = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as failure:
        raise Blocked(f"{host} does not resolve ({failure.strerror})") from failure
    found = []
    for entry in answers:
        try:
            found.append(ipaddress.ip_address(entry[4][0]))
        except ValueError:                       # pragma: no cover - defensive
            continue
    if not found:
        raise Blocked(f"{host} resolved to no usable address")
    return found


def _why_private(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """The reason this address is off limits, in words worth logging."""
    if address.is_loopback:
        return "loopback: this is the machine Qevik runs on"
    if address.is_link_local:
        return ("link-local: this range holds the cloud metadata service, which "
                "hands out instance credentials to anything inside")
    if address.is_private:
        return "private: this is inside the network Qevik runs in"
    if address.is_reserved or address.is_multicast or address.is_unspecified:
        return "reserved, multicast or unspecified"
    return ""


def check(url: str) -> str:
    """Refuse anything not on the public internet. Returns the hostname.

    Raises `Blocked` with a reason a person can read. Callers turn that into a
    recorded refusal rather than an exception — a site we may not reach is a
    site we could not check, which is a different fact from a site that is
    broken.
    """
    parts = urlsplit(url if "://" in (url or "") else f"https://{url or ''}")
    if parts.scheme not in ALLOWED_SCHEMES:
        raise Blocked(
            f"{parts.scheme or 'no'}: is not a scheme Qevik fetches. Only http "
            "and https — file:// would read this machine's disk.")

    host = (parts.hostname or "").lower()
    if not host:
        raise Blocked("that URL names no host")
    if host in METADATA:
        raise Blocked(f"{host} is the cloud metadata service")

    for address in _addresses(host):
        reason = _why_private(address)
        if reason:
            raise Blocked(f"{host} resolves to {address} — {reason}")
    return host


def safe(url: str) -> bool:
    """Whether `check` would allow this. For places that want a boolean."""
    try:
        check(url)
    except Blocked:
        return False
    return True


def reason(url: str) -> str:
    """Why this URL is refused, or an empty string if it is not."""
    try:
        check(url)
    except Blocked as blocked:
        return str(blocked)
    return ""
