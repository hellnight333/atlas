"""The relationship layer: what stands between a company and revenue.

Deliberately a derivation over what already exists rather than a new store.
See `pipeline` for why a stored stage is the thing that makes every CRM wrong.
"""

from .pipeline import (
    ActionKind,
    NextAction,
    Relationship,
    Stage,
    board,
    next_action,
    relationship,
    stage_of,
)

__all__ = ["ActionKind", "NextAction", "Relationship", "Stage", "board",
           "next_action", "relationship", "stage_of"]
