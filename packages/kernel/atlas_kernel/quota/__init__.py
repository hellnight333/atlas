"""Quota: what the accounts can actually spend today.

Doc 11 specifies a daily production loop and a twelve-a-day target without any
concept of a limit. The binding one is not money — YouTube grants a fixed daily
allowance of units and an upload costs a large share of it — so a production
plan has to be computed from what is left rather than from an ambition.

The rule this package encodes: **a limit reduces the day's output, it does not
cancel it.** `plan()` returns what fits and says why it is not more.
"""

from .ledger import Plan, QuotaLedger
from .models import (
    LimitKind,
    QuotaExhausted,
    QuotaPolicy,
    QuotaSpend,
    QuotaStatus,
    QuotaWindow,
)
from .policies import default_policies

__all__ = [
    "LimitKind",
    "Plan",
    "QuotaExhausted",
    "QuotaLedger",
    "QuotaPolicy",
    "QuotaSpend",
    "QuotaStatus",
    "QuotaWindow",
    "default_policies",
]
