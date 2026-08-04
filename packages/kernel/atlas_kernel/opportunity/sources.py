"""Where candidate businesses come from.

The MVP ships one source: a list the operator supplies. That is a scope
decision, **not the architecture**. Producing names is cheap and every market
has a different way of doing it; producing *evidenced findings* about those
names is the hard, defensible part, so that is where this milestone went.

Discovery is built to be autonomous and multi-source. The registry queries every
registered source, resolves the results against one another by identity, and
treats a duplicate across sources as the normal case rather than an anomaly.
Nothing assumes a human supplied the list — ``SeedListSource`` is one
implementation of ``BusinessSource``, privileged nowhere.

Sources that drop in without changing a caller:

* **Google Maps / Places** — businesses by category and area, with the
  ``website`` field often absent, which is itself the strongest finding there is.
* **Business directories** — chambers of commerce, trade bodies, listing sites.
* **Public web** — search results, competitor pages, "our clients" listings.
* **Data APIs** — licensing registries, marketplace seller directories.

Each will need its own rate limiting, its own terms-of-use judgement and its own
reliability rating, and none of that leaks past the protocol.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from .models import Business, NicheProfile


class SeedListSource:
    """Businesss supplied directly by the operator.

    Rows missing a name are skipped rather than fabricated into "Unknown
    business" -- an unnamed business cannot be written to honestly and would
    poison the funnel counts with entries nobody can act on.
    """

    def __init__(self, rows: Iterable[dict[str, str]], *, label: str = "seed-list") -> None:
        self._rows = list(rows)
        self._label = label

    @property
    def name(self) -> str:
        return self._label

    @classmethod
    def from_csv(cls, text: str, *, label: str = "seed-list") -> SeedListSource:
        """Build from CSV with a header row.

        Recognised columns: ``name``, ``website``, ``email``, ``phone``. Anything
        else is carried into metadata rather than discarded, because the operator
        put it there for a reason.
        """
        reader = csv.DictReader(io.StringIO(text))
        return cls([{k: (v or "") for k, v in row.items() if k} for row in reader], label=label)

    def discover(self, profile: NicheProfile, limit: int) -> list[Business]:
        known = {"name", "website", "email", "phone"}
        businesses: list[Business] = []
        for row in self._rows:
            if len(businesses) >= limit:
                break
            normalised = {
                (key or "").strip().lower(): (value or "").strip() for key, value in row.items()
            }
            name = normalised.get("name", "")
            if not name:
                continue
            businesses.append(
                Business(
                    name=name,
                    geography=profile.geography,
                    website=normalised.get("website") or None,
                    email=normalised.get("email") or None,
                    phone=normalised.get("phone") or None,
                    sources=[self._label],
                    metadata={k: v for k, v in normalised.items() if k not in known and v},
                )
            )
        return businesses
