#!/usr/bin/env python3
"""Call every registered model once and record what happened.

    ./infra/benchmark_models.py                 # every model this deployment has
    ./infra/benchmark_models.py --provider nvidia
    ./infra/benchmark_models.py --dry-run       # list what would be called

Reads the registry the way the control plane does — from the credential vault,
through the same adapters production uses. A separate HTTP client here would be
a second answer to "does this work": the one that benchmarks well while the one
that runs fails, or the reverse.

It costs money, in the sense that every call is billed. Twenty-four tokens per
model, so the whole run is a fraction of a cent, but it is not free and it is
not a health check to put on a timer without deciding to.

Politeness is not optional with some providers. NVIDIA's edge blocked the
calling *address* after a concurrent burst — `403 Forbidden` as an nginx HTML
page for every request, from every model, with a key that worked fine
elsewhere. So this is serial, with a pause.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.credentials.location import paths_for  # noqa: E402
from atlas_kernel.credentials.service import FACTORY as CREDENTIAL_FACTORY  # noqa: E402
from atlas_kernel.credentials.service import CredentialService  # noqa: E402
from atlas_kernel.credentials.vault import FileSecretStore, Vault  # noqa: E402
from atlas_kernel.llm import benchmark  # noqa: E402
from atlas_kernel.mission.timeline import Timeline  # noqa: E402

log = logging.getLogger("benchmark")


def registry_for_tenant(tenant: str):
    """The same registry a worker builds, from the same vault."""
    from atlas_kernel.credentials.models import registry_for

    where = paths_for(os.environ.get("QEVIK_STATE") or None)
    records = Timeline(where.records, factory=CREDENTIAL_FACTORY)
    service = CredentialService(Vault(FileSecretStore(where.vault)),
                                events=records.read(), sink=records.append)
    return registry_for(service, tenant=tenant), where


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="tenant-qevik")
    parser.add_argument("--provider", default="",
                        help="only models served by this provider")
    parser.add_argument("--pause", type=float, default=1.0,
                        help="seconds between calls (see the module docstring)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    registry, where = registry_for_tenant(args.tenant)
    registrations = [r for r in registry.models
                     if not args.provider or r.spec.provider == args.provider]

    if not registrations:
        # Not an error, and not silence. A deployment with no model credential
        # has nothing to measure, and saying so is the useful output.
        print("no models are registered for this tenant. Add a model "
              "credential in the Credential Centre first.", file=sys.stderr)
        return 1

    if args.dry_run:
        for registration in registrations:
            print(f"  would call {registration.spec.provider:10} {registration.name}")
        return 0

    store = benchmark.Store(where.state / benchmark.FILE)
    done = benchmark.run(registrations, store, pause_seconds=args.pause)

    for measurement in done:
        latency = f"{measurement.latency_ms} ms" if measurement.latency_ms else "—"
        print(f"  {measurement.state.value:13} {measurement.model:44} "
              f"{latency:>9}  {measurement.reason[:60]}")

    counts = {state.value: sum(1 for m in done if m.state is state)
              for state in benchmark.State}
    print(f"\n{counts}  ->  {store.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
