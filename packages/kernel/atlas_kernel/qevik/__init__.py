"""Qevik as an application, rather than as a collection of routers.

Every surface in this kernel exposes `install(app)`. Until this module existed,
nothing called any of them outside a test fixture: `atlas_kernel/api.py` — the
module `launcher.py` actually serves — contains no `include_router` call at all.
The handlers were correct and the product did not exist.

That is the same failure as a source file the tests import and git does not
track: every local signal green, the artefact absent. So the composition is one
function that mounts everything, and `test_app_composition.py` asserts that
every router module in the kernel appears in it — a new surface that nobody
mounts fails the suite rather than shipping unreachable.
"""

from .app import SURFACES, Wiring, create_app, health

__all__ = ["SURFACES", "Wiring", "create_app", "health"]
