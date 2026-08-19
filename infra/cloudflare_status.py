#!/usr/bin/env python3
"""Report the qevik.ai zone as Cloudflare currently holds it. Reads only.

Exists because the alternative is guessing. A DNS record flipped to DNS-only
exposes the origin; a record repointed elsewhere looks exactly like the server
being down, and this project has already misdiagnosed one outage that way. Being
able to *look* is what keeps the next one from costing a day.

Writes nothing, and prints no credential. If no token is configured it says so
and exits 0 — an absent optional credential is a state, not a failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.infra import (  # noqa: E402
    ORIGIN_IP,
    PROTECTED,
    Cloudflare,
    CloudflareError,
    CloudflareUnavailable,
)


def main() -> int:
    try:
        client = Cloudflare()
    except CloudflareUnavailable as absent:
        print(f"no Cloudflare token configured — {absent}")
        return 0

    try:
        zone = client.zone()
        print(f"zone        : {zone['name']}  ({zone['status']})")
        print(f"nameservers : {', '.join(zone.get('name_servers', []))}")
        print()

        records = sorted(client.records(), key=lambda r: (r.type, r.name))
        print(f"records     : {len(records)}")
        for record in records:
            flags = []
            if record.name in PROTECTED:
                flags.append("protected")
            if record.type == "A" and record.content != ORIGIN_IP:
                flags.append("NOT this server")
            if record.type == "A" and not record.proxied:
                flags.append("origin IP exposed")
            note = f"   <- {', '.join(flags)}" if flags else ""
            print(f"  {record}{note}")
    except CloudflareError as failure:
        print(f"cloudflare: {failure}", file=sys.stderr)
        return 1
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
