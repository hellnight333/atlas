"""Organization domain (Milestone 010).

Deliberately free of eager imports, for the same reason as ``approval`` and
``cluster``: ``event_bus`` imports ``organization.events``, so anything this
package pulled in at import time would become a dependency of the event bus
itself. Import the submodules you need directly.
"""

__all__: list[str] = []
