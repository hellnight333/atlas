"""Infrastructure Qevik maintains for itself — DNS today, nothing else yet.

Kept apart from `website/targets/`, which publishes *content*. This publishes
*addresses*, and the blast radius is different in kind: a bad deploy serves the
wrong page at one URL, a bad DNS change takes every hostname in the zone with it.
"""

from .cloudflare import (
    ORIGIN_IP,
    PROTECTED,
    ZONE,
    Cloudflare,
    CloudflareError,
    CloudflareRefused,
    CloudflareUnavailable,
    Record,
    check_writable,
)

__all__ = [
    "ORIGIN_IP",
    "PROTECTED",
    "ZONE",
    "Cloudflare",
    "CloudflareError",
    "CloudflareRefused",
    "CloudflareUnavailable",
    "Record",
    "check_writable",
]
