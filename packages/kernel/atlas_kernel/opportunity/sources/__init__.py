"""Where candidate businesses come from.

Discovery is multi-source by construction. The registry queries every registered
source, resolves the results against one another by identity, and treats a
duplicate across sources as the normal case — so adding a source is a
registration, not a change to any caller.

* ``SeedListSource``  — a list the operator supplies. Useful well past the MVP:
  a conference list, a CRM export, a hand-picked set to test a new niche.
* ``OverpassSource``  — real businesses from OpenStreetMap. Free, no API key, no
  credential to protect, which is why it comes first.
* ``GooglePlacesSource`` — real businesses *with contact details*. Costs money,
  and exists because the market scan measured reachability at 2–17% on OSM and
  found that to be the binding constraint rather than defect rate.

Re-exported here so ``from .sources import SeedListSource`` keeps working: this
was a module before it was a package, and turning it into one should not have
been visible to anything that imported it.
"""

from .google_places import (
    GooglePlacesSource,
    NotConfigured,
    PlacesError,
    opening_hours_for,
)
from .overpass import AREAS, NICHES, OverpassError, OverpassSource
from .seed import SeedListSource

__all__ = [
    "AREAS",
    "NICHES",
    "GooglePlacesSource",
    "opening_hours_for",
    "NotConfigured",
    "OverpassError",
    "OverpassSource",
    "PlacesError",
    "SeedListSource",
]
