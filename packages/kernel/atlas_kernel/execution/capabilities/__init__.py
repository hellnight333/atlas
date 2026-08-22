"""Executors, keyed by the offer they fulfil.

One entry. A registry with one member looks like over-engineering and is not:
the lookup is what makes "no executor for that capability" a refusal rather than
a crash, which is one of the negative controls this phase was gated on.
"""

from .portfolio import build_portfolio_index

#: offer id -> executor. An offer with no entry cannot be executed.
EXECUTORS = {
    "offer-portfolio-system": build_portfolio_index,
}

__all__ = ["EXECUTORS", "build_portfolio_index"]
