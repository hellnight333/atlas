"""The product boundary around the execution engine.

Thin by design: `api` establishes the tenant and calls kernel services, `tasks`
records what the customer did with evidence for it, `strategy` assembles the
paragraph they read, and `public` decides what a stranger may see. No business
rule lives here that is not about the customer relationship itself.
"""

from . import api, public, strategy, tasks

__all__ = ["api", "public", "strategy", "tasks"]
