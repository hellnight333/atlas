"""Approval domain (Milestone 008).

Deliberately free of eager imports: ``event_bus`` imports ``approval.events``,
so anything this package pulls in at import time would become a dependency of
the event bus itself. Import the submodules you need directly.
"""

__all__: list[str] = []
