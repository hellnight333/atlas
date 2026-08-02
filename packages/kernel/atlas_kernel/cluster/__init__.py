"""Cluster domain (Milestone 009).

Deliberately free of eager imports, for the same reason as ``approval``:
``event_bus`` imports ``cluster.events``, so anything this package pulled in at
import time would become a dependency of the event bus itself. Import the
submodules you need directly.
"""

__all__: list[str] = []
