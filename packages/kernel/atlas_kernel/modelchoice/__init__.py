"""Which model does which job, chosen by a person and recorded per invocation.

Thin on purpose. `credentials/models.py` already turns stored credentials into a
`ModelRegistry` and answers "which model for this role, and was that a choice or
a default" — this package adds a place to persist the choice and a surface to
make it, and adds no second registry. Two systems that both believe they decide
which model runs is how an invocation gets recorded against a model that never
saw the request.
"""

from .api import build_router, install
from .store import SelectionStore, available, chosen

__all__ = ["SelectionStore", "available", "build_router", "chosen", "install"]
