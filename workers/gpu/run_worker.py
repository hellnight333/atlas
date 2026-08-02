from __future__ import annotations

import argparse
import logging
import time

from packages.kernel.atlas_kernel.composition_root import create_runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("atlas-gpu-worker")


def main() -> int:
    parser = argparse.ArgumentParser(description="Atlas GPU worker process")
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds")
    parser.add_argument(
        "--stop-after",
        type=int,
        default=0,
        help="Stop after this many polling iterations (0 means run forever)",
    )
    args = parser.parse_args()

    runtime = create_runtime()
    worker = runtime.worker

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
