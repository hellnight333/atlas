"""One pass of discovery: see, resolve, classify, remember.

The whole commercial loop is

    discover -> compare with memory -> verify -> score -> report -> approve -> mission

and this file is the first four. It deliberately stops before *report*: turning
a signal into something a person is asked to approve is `mission/policy.py`'s
job, and a discovery pass that could queue its own work would be a scanner with
authority.

## Nothing here fetches anything

`record()` takes sightings that somebody else obtained. The sources
(`sources/google_places.py`, `sources/overpass.py`) and the guarded fetcher
(`research/net.py`) already exist and already enforce the budget, the robots
policy and the SSRF refusal. A scan that did its own fetching would be a second
place where those limits are decided, and the second place is always the one
that forgets.

## Memory is the existing business memory

`OpportunityRepository.resolve_business` already answers "have we seen this
company", by strong keys only — domain, email, phone — because a shared name
and city is not enough and a wrong merge attaches one company's findings to
another's proposal. That is reused rather than reimplemented; this adds the
sighting record beside it, which is the part that was missing.

The single most important line in this file is that `resolve_business` is
called **before** `classify`, and its answer is what `known_to_qevik` carries.
A scan that classified first and resolved afterwards would report every
sighting as new on every run.

## A discovered business belongs to nobody yet

`save_business` writes no tenant, and `tenancy.owns` returns a row with no
tenant to nobody — "legacy residue and the unresolved business are invisible to
every tenant, and visible only to the operator console". That is the existing
design and it is right: a clinic Qevik noticed in Dubai is not yet anybody's
customer, and assigning it to a tenant at the moment of *sighting* would decide
a commercial question with a scanner.

So a business is read back with `ALL_TENANTS`, which is the operator console's
view. The **sighting** does carry a tenant, because a scan is always run on
somebody's behalf and their budget paid for it. Tenant assignment happens later,
at qualification, and is a separate act.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .discovery import Classification, Sighting, classify
from .models import Business
from .repository import OpportunityRepository
from .tenancy import TenantId


@dataclass
class Recorded:
    """What one sighting turned into."""

    sighting: Sighting
    business: Business
    classification: Classification
    #: False when this exact sighting was already stored — a replayed scan.
    stored: bool = True

    def summary(self) -> dict:
        return {"business_id": self.business.id, "name": self.business.name,
                "source": self.sighting.source,
                "stored": self.stored, **self.classification.summary()}


@dataclass
class Pass:
    """The result of one discovery pass. Counts, and the records behind them."""

    recorded: list[Recorded] = field(default_factory=list)

    @property
    def seen(self) -> int:
        return len(self.recorded)

    @property
    def new_to_qevik(self) -> list[Recorded]:
        from .discovery import DiscoveryState
        return [r for r in self.recorded
                if r.classification.state is not DiscoveryState.KNOWN]

    @property
    def proven_new(self) -> list[Recorded]:
        """Only those a source actually evidenced. Almost always empty, and
        that is the honest answer rather than a disappointing one."""
        from .discovery import DiscoveryState
        return [r for r in self.recorded
                if r.classification.state
                is DiscoveryState.PROVEN_NEW_TO_SOURCE]

    def summary(self) -> dict:
        return {"seen": self.seen,
                "new_to_qevik": len(self.new_to_qevik),
                "proven_new_to_source": len(self.proven_new),
                "records": [r.summary() for r in self.recorded]}


def business_from(sighting: Sighting) -> Business:
    """The company a sighting is about, in the shape memory stores.

    `source_id` and `source_url` go into `metadata` under the source's own name
    rather than into a column: the stable identifier means something different
    to Places than to Overpass, and one column called `source_id` holding both
    is a column nobody can join on.
    """
    return Business(
        name=sighting.name,
        geography=", ".join(p for p in (sighting.city, sighting.country) if p),
        website=sighting.source_url or None,
        sources=[sighting.source],
        metadata={sighting.source: {"source_id": sighting.source_id,
                                    "source_url": sighting.source_url,
                                    "country": sighting.country,
                                    "city": sighting.city}},
    )


def record(sightings: list[Sighting], *, repository: OpportunityRepository,
           tenant: TenantId | None = None) -> Pass:
    """Resolve each sighting against memory, classify it, and remember it.

    Order matters and is the point: **resolve, then classify**. The repository
    answers whether this company was already known; that answer is what
    separates "new to Qevik" from "seen again", and computing the state before
    asking would report everything as new on every run.
    """
    outcome = Pass()
    for sighting in sightings:
        business, created = repository.resolve_business(business_from(sighting))
        # `created` is True when the repository had no record. That is exactly
        # "not known to Qevik", and it is the only input to the state that is
        # about Qevik rather than about the world.
        found = classify(sighting, known_to_qevik=not created)
        placed = sighting.model_copy(update={"business_id": business.id})
        stored = repository.record_sighting(placed, found, tenant=tenant)
        outcome.recorded.append(
            Recorded(sighting=placed, business=business, classification=found,
                     stored=stored))
    return outcome


__all__ = ["Pass", "Recorded", "business_from", "record"]
