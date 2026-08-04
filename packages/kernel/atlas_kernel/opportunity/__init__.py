"""Opportunity Factory (M014).

Finds businesses with a specific, provable commercial defect and produces a
proposal built from those findings, approval-gated end to end.

Deliberately free of eager imports, matching ``media`` and ``approval``: import
the submodule you need. Read ``docs/OPPORTUNITY_FACTORY.md`` first — the two
invariants there (no finding without evidence, no proposal without findings) are
enforced by construction and are the reason this package is shaped the way it is.
"""

__all__: list[str] = []
