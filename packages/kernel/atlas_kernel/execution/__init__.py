"""Turning an approved recommendation into a verified artefact.

Deliberately small. One capability runs end to end here, because a framework
with no capability proves nothing and a capability with no framework cannot be
extended. The framework is whatever that one capability actually needed.
"""

from .models import (
    ExecutionOutcome,
    NotApproved,
    PublicationState,
    QAResult,
    QAVerdict,
    UnsupportedCapability,
)
from .qa import GATES, run_gates

__all__ = ["ExecutionOutcome", "GATES", "NotApproved", "PublicationState", "QAResult",
           "QAVerdict", "UnsupportedCapability", "run_gates"]
