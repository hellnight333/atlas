"""Where candidate prospects come from.

The MVP ships one source: a list the operator supplies. That is a deliberate
scope decision rather than a stub. Producing names is cheap and every market has
a different way of doing it; producing *evidenced findings* about those names is
the part that is hard, defensible and worth building, so that is where the
milestone went.

A directory-backed or search-backed source implements the same protocol and
registers alongside this one. Nothing else in the package changes when it does.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from .models import NicheProfile, Prospect


class SeedListSource:
    """Prospects supplied directly by the operator.

    Rows missing a name are skipped rather than fabricated into "Unknown
    business" -- an unnamed prospect cannot be written to honestly and would
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

    def discover(self, profile: NicheProfile, limit: int) -> list[Prospect]:
        known = {"name", "website", "email", "phone"}
        prospects: list[Prospect] = []
        for row in self._rows:
            if len(prospects) >= limit:
                break
            normalised = {
                (key or "").strip().lower(): (value or "").strip() for key, value in row.items()
            }
            name = normalised.get("name", "")
            if not name:
                continue
            prospects.append(
                Prospect(
                    name=name,
                    niche=profile.id,
                    geography=profile.geography,
                    website=normalised.get("website") or None,
                    email=normalised.get("email") or None,
                    phone=normalised.get("phone") or None,
                    source=self._label,
                    metadata={k: v for k, v in normalised.items() if k not in known and v},
                )
            )
        return prospects
