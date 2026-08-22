"""What an unauthenticated visitor may see, and how that is guaranteed.

The future flow is: enter a website on qevik.ai, get an audit, see the
opportunities, see what Qevik can do, then log in. That flow is not built here —
what is built is the boundary it will sit behind, because the thing that goes
wrong is not the page, it is a field that quietly makes the trip.

The guarantee is **allow-list, not redaction**. A public view is assembled by
naming the fields that may appear, so a field added upstream is invisible here
until somebody adds it deliberately. Redaction is the opposite — a deny-list
that silently passes anything new, and the new thing is exactly the one nobody
thought about.

Never public: evidence text, tenant ids, internal ids, customer tasks,
credentials, research metadata, anything about another business.
"""

from __future__ import annotations

from ..execution.capabilities import EXECUTORS
from ..recommendation.offers import OFFERS

#: Every key a public payload may carry. Anything else is dropped, and a test
#: asserts the finished payload contains nothing outside this set.
PUBLIC_FIELDS: frozenset[str] = frozenset({
    "website", "checked", "summary", "opportunities", "capabilities",
    "readiness", "note", "key", "name", "family", "priority", "confidence",
    "offered", "executable", "state", "headline", "count",
    # Nested counts. Named individually rather than allowing a subtree, so a
    # field added inside one of these blocks is still refused until somebody
    # decides it is public.
    "confirmed", "not_verified", "working", "to_fix",
})

#: Substrings that mean a value is not ours to publish. Not the mechanism — the
#: allow-list is — but a second reading, because the cost of being wrong here is
#: a stranger's private data on a marketing page.
FORBIDDEN_HINTS: tuple[str, ...] = (
    "tenant", "credential", "token", "secret", "connection", "approval",
    "business_id", "recommendation_id", "job_id", "run_id", "asset_id",
    "customer_task", "evidence",
)


class Leak(Exception):
    """A public payload carried something that is not public."""


def audit(*, website: str, observations: list[dict],
          opportunities: tuple = ()) -> dict:
    """The public audit view of one site. No tenant, no ids, no evidence.

    Counts rather than lists for what was found: "four things to fix" is the
    honest public summary, and naming them gives away the work.
    """
    confirmed = [o for o in observations if o.get("status") in ("present", "not_found")]
    absent = [o for o in observations if o.get("status") == "not_found"]
    unverified = [o for o in observations if o.get("status") == "unverified"]

    payload = {
        "website": website,
        "checked": {"confirmed": len(confirmed), "not_verified": len(unverified)},
        "summary": {"working": len(confirmed) - len(absent), "to_fix": len(absent)},
        "opportunities": [
            {"key": o.key, "name": o.name, "family": o.family,
             "priority": o.priority, "confidence": o.confidence}
            for o in opportunities
        ],
        "capabilities": [
            {"name": offer.name, "offered": True,
             "executable": offer.id in EXECUTORS}
            for offer in OFFERS
        ],
        "note": "A public summary. What was not checked is counted, not guessed "
                "at, and nothing here is a claim about the business's results.",
    }
    return guard(payload)


def guard(payload: dict, *, where: str = "public audit") -> dict:
    """Refuse to return a payload carrying anything private.

    Runs on the finished object rather than at each assignment, which is the
    only place the whole shape exists — the same reason the outreach consistency
    check reads the finished message rather than each field.
    """
    def walk(value: object, path: str) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                if key not in PUBLIC_FIELDS:
                    raise Leak(f"{where}: {path}{key} is not a public field")
                if any(hint in key.lower() for hint in FORBIDDEN_HINTS):
                    raise Leak(f"{where}: {path}{key} names something private")
                walk(inner, f"{path}{key}.")
        elif isinstance(value, list):
            for index, inner in enumerate(value):
                walk(inner, f"{path}[{index}].")

    walk(payload, "")
    return payload
