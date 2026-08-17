"""Research: answering questions from the open web.

Distinct from `opportunity/`, which finds *businesses*. Places and OpenStreetMap
return companies with addresses; neither can answer "what are this company's
competitors charging" or "has this brand name already been taken". That is what
this package is for.

The capability is `web.search`. Callers ask for it by name and never name Brave,
in keeping with the rule that the kernel routes capabilities rather than vendors.
"""

from .brave import BraveSearch, NotConfigured, SearchError
from .models import WEB_SEARCH, SearchQuery, SearchResult, SearchResults

__all__ = [
    "WEB_SEARCH",
    "BraveSearch",
    "NotConfigured",
    "SearchError",
    "SearchQuery",
    "SearchResult",
    "SearchResults",
]
