from __future__ import annotations

import argparse
import logging
import sys
import time

from packages.kernel.atlas_kernel.db import init_db
from packages.kernel.atlas_kernel.models import ProviderSpec
from packages.kernel.atlas_kernel.providers import LocalFluxProvider, LocalTextProvider, ProviderManager
from packages.kernel.atlas_kernel.registry import Registry
from packages.kernel.atlas_kernel.router import ProviderRouter
from packages.kernel.atlas_kernel.repository import AtlasRepository
from packages.kernel.atlas_kernel.worker import Worker


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("atlas-gpu-worker")


def build_router_and_providers() -> tuple[ProviderRouter, ProviderManager]:
    registry = Registry()
    registry.register_provider(ProviderSpec(name=LocalFluxProvider.name, kind="image", is_local=True, vram_gb=24))
    registry.register_provider(ProviderSpec(name=LocalTextProvider.name, kind="llm", is_local=True, vram_gb=0))

    provider_manager = ProviderManager()
    provider_manager.register_adapter(LocalFluxProvider.name, LocalFluxProvider())
    provider_manager.register_adapter(LocalTextProvider.name, LocalTextProvider())

    return ProviderRouter(registry), provider_manager


def main() -> int:
    parser = argparse.ArgumentParser(description="Atlas GPU worker process")
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds")
    parser.add_argument("--stop-after", type=int, default=0, help="Stop after this many polling iterations (0 means run forever)")
    args = parser.parse_args()

    init_db()
    repository = AtlasRepository()
    router, provider_manager = build_router_and_providers()
    worker = Worker(repository=repository, router=router, provider_manager=provider_manager)

    logger.info("Starting Atlas GPU worker")
    iteration = 0
    try:
        while True:
            job = worker.poll_once()
            if job is None:
                logger.debug("No queued jobs. Sleeping for %s seconds.", args.interval)
                time.sleep(args.interval)
            else:
                logger.info("Picked up job %s (action=%s)", job.id, job.action)
                result = worker.execute_job(job)
                logger.info("Job %s finished: %s", job.id, result)

            iteration += 1
            if args.stop_after and iteration >= args.stop_after:
                logger.info("Reached stop-after limit (%s). Exiting.", args.stop_after)
                break
    except KeyboardInterrupt:
        logger.info("Worker interrupted, exiting.")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
