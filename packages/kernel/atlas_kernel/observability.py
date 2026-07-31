from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


class Observability:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("atlas")

    def emit(self, event: str, **data: Any) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **data,
        }
        self.logger.info(json.dumps(payload, default=str))
