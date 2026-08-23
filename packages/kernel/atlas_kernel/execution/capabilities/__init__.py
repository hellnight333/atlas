"""Executors, keyed by the offer they fulfil.

Three entries. The lookup is what makes "no executor for that capability" a
refusal rather than a crash, and it is the authority the roadmap consults before
telling a customer that Qevik can do something — an offer existing is not the
same as something being able to perform it.
"""

from collections.abc import Callable
from typing import Any

from .editorial import build_editorial_hub
from .portfolio import build_portfolio_index
from .website import NothingToBuild, WebsiteMode, build_website

#: What every executor is. A capability produces one document or a bundle of
#: files, plus the provenance saying what it was built from — declared once so a
#: new executor with a different shape is a type error rather than a surprise at
#: the point of execution.
Executor = Callable[..., tuple[str | dict[str, str], dict[str, Any]]]

#: offer id -> executor. An offer with no entry cannot be executed.
EXECUTORS: dict[str, Executor] = {
    "offer-portfolio-system": build_portfolio_index,
    "offer-website": build_website,
    "offer-editorial": build_editorial_hub,
}

__all__ = ["EXECUTORS", "Executor", "NothingToBuild", "WebsiteMode",
           "build_editorial_hub", "build_portfolio_index", "build_website"]
