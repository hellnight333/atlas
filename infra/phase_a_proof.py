"""Phase A end-to-end proof against a real remote host.

Six criteria, each checked against reality rather than a mock:

1. Atlas builds an artifact
2. Atlas stores the artifact permanently
3. Atlas deploys it
4. Atlas promotes it
5. Atlas can redeploy it
6. Atlas can roll back from its own stored artifact without provider history

Criterion 6 is the one worth watching: the previous version is *deleted from the
server* before the rollback, so a rollback that leaned on provider history would
fail here.
"""

from __future__ import annotations

import subprocess
import sys

import httpx

sys.path.insert(0, "/Users/salmansheraf/atlas/packages/kernel")

from atlas_kernel.db import init_db  # noqa: E402
from atlas_kernel.opportunity.models import Business  # noqa: E402
from atlas_kernel.opportunity.repository import OpportunityRepository  # noqa: E402
from atlas_kernel.website.gate import OutputGate  # noqa: E402
from atlas_kernel.website.models import DeploymentStatus, Site  # noqa: E402
from atlas_kernel.website.repository import WebsiteRepository  # noqa: E402
from atlas_kernel.website.service import WebsiteService  # noqa: E402
from atlas_kernel.website.targets.base import (  # noqa: E402
    DeploymentTargetRegistry,
    TargetRegistration,
)
from atlas_kernel.website.targets.ssh import SshDirectoryTarget  # noqa: E402

CA = "/private/tmp/claude-501/-Users-salmansheraf/cedd70e3-ce10-46ad-bd33-f2592cb8e8a0/scratchpad/atlas-ca.crt"
KEY = "/Users/salmansheraf/.ssh/naml_hetzner"
HOST = "204.168.249.69"
REMOTE_ROOT = "/opt/atlas-sites/root"


def page(heading: str, body: str) -> str:
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        f"<title>{heading} — Electronics Trading, Dubai</title>"
        '<meta name="description" content="Electronics trading and distribution across the UAE.">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Organization","name":"Teqtronix"}'
        "</script></head><body>"
        f"<h1>{heading}</h1><p>{body}</p></body></html>"
    )


V1 = {
    "index.html": page(
        "Teqtronix",
        "Electronics trading and distribution across the United Arab Emirates since 2016. " * 6,
    ),
    "styles.css": "body{font-family:system-ui;max-width:44rem;margin:3rem auto;padding:0 1rem}",
}
V2 = {
    "index.html": page(
        "Teqtronix Trading",
        "Consumer electronics distribution across the UAE and Saudi Arabia since 2016. " * 6,
    ),
    "styles.css": "body{font-family:system-ui;max-width:48rem;margin:3rem auto;padding:0 1rem}",
}


def ssh(command: str) -> str:
    result = subprocess.run(
        ["ssh", "-i", KEY, "-o", "BatchMode=yes", f"root@{HOST}", command],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result.stdout.strip()


def check(number: int, name: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {number}. {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    init_db()
    client = httpx.Client(verify=CA, timeout=30.0, follow_redirects=True)

    target = SshDirectoryTarget(
        host=HOST,
        root=REMOTE_ROOT,
        base_url="https://127.0.0.1:8791",
        key_path=KEY,
        name="hetzner",
    )
    registry = DeploymentTargetRegistry()
    registry.register(TargetRegistration(target=target, is_local=False))

    repo = WebsiteRepository()
    service = WebsiteService(
        repository=repo, targets=registry, gate=OutputGate(client=client), verifier=client
    )

    # A real Business record — the same customer entity every factory uses.
    businesses = OpportunityRepository()
    business, _ = businesses.resolve_business(
        Business(name="Teqtronix", geography="United Arab Emirates", website="https://teqtronix.ae")
    )
    site = repo.save_site(Site(business_id=business.id, name="Teqtronix", domain="teqtronix.ae"))
    slug = f"site-{site.id[:12]}"
    print(f"\nBusiness {business.id}\nSite     {site.id}  (slug {slug})\n")

    results: list[bool] = []

    # 1 — build
    build_v1 = service.record_build(site, V1, provenance={"phase": "A", "author": "atlas"})
    results.append(
        check(
            1,
            "Atlas builds an artifact",
            bool(build_v1.files),
            f"fingerprint {build_v1.fingerprint}",
        )
    )

    # 2 — stored permanently (read back from Postgres, not from memory)
    reloaded = WebsiteRepository().get_build(build_v1.id)
    stored_ok = (
        reloaded is not None
        and reloaded.files == V1
        and reloaded.fingerprint == build_v1.fingerprint
    )
    results.append(
        check(2, "Atlas stores the artifact permanently", stored_ok, "read back from Postgres")
    )

    # 3 + 4 — deploy and promote (publish -> gate -> promote -> verify)
    live_v1 = service.deploy(site, build_v1)
    results.append(
        check(3, "Atlas deploys it", live_v1.remote_id is not None, f"version {live_v1.remote_id}")
    )
    results.append(
        check(
            4,
            "Atlas promotes it",
            live_v1.status is DeploymentStatus.LIVE,
            f"live at {live_v1.live_url}",
        )
    )

    served = client.get(live_v1.live_url).text
    results.append(
        check(
            4, "  serving the promoted version", "<h1>Teqtronix</h1>" in served, "fetched over TLS"
        )
    )

    # 5 — redeploy
    build_v2 = service.record_build(site, V2)
    live_v2 = service.deploy(site, build_v2)
    served_v2 = client.get(live_v2.live_url).text
    results.append(
        check(
            5,
            "Atlas can redeploy it",
            live_v2.status is DeploymentStatus.LIVE and "Teqtronix Trading" in served_v2,
            f"fingerprint {live_v2.build_fingerprint}",
        )
    )

    # 6 — rollback WITHOUT provider history: delete v1 from the server first.
    ssh(f"rm -rf {REMOTE_ROOT}/{slug}/versions/{live_v1.remote_id}")
    gone = ssh(
        f"test -d {REMOTE_ROOT}/{slug}/versions/{live_v1.remote_id} && echo present || echo gone"
    )
    print(f"\n  (deleted v1 from the server: {gone})")

    restored = service.rollback(site)
    served_back = client.get(restored.live_url).text
    rollback_ok = (
        restored.status is DeploymentStatus.LIVE
        and restored.build_fingerprint == build_v1.fingerprint
        and "<h1>Teqtronix</h1>" in served_back
        and "Teqtronix Trading" not in served_back
    )
    results.append(
        check(
            6,
            "Atlas rolls back from its own stored artifact",
            rollback_ok,
            "server copy was deleted first",
        )
    )

    # Extra evidence: the timeline, and rebuild-from-memory.
    rebuilt = service.rebuild_from_memory(build_v1.id)
    print(
        f"\n  rebuild_from_memory: fingerprint {rebuilt.fingerprint} "
        f"({'matches' if rebuilt.fingerprint == build_v1.fingerprint else 'MISMATCH'})"
    )

    timeline = repo.timeline(business.id, factory="website")
    print(
        f"  business timeline ({len(timeline)} entries): "
        f"{' -> '.join(event.kind for event in timeline)}"
    )

    remote_live = target.live_version(slug)
    print(f"  server current -> {remote_live}")

    print()
    passed = sum(results)
    print(f"{passed}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
