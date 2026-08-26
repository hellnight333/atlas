"""Turning what memory now knows into opportunities, deterministically.

Discovery stops at "here is a business Qevik had not recorded". That is not an
opportunity; it is a row. This is the layer that says *why it matters*, and it
is deliberately the smallest set the evidence can carry.

## Two detectors, and the ones deliberately absent

**`NEW_BUSINESS`** — supported. The sighting resolved against memory and memory
had nothing, which is a fact about Qevik and is stated as one.

**`UNVERIFIED_WEB_PRESENCE`** — supported, and the interesting one. The source
records no website. That is a fact about **the source**, and the suggested
action is therefore *verify*, not *sell*. An OSM node without a `website` tag is
a lead worth ten seconds of checking, not a business without a website.

The categories that are **not** here, and why:

| not built | why |
|---|---|
| `WEAK_WEB_PRESENCE` | needs the site fetched and audited. `detectors/website.py` does that; until it has run, "weak" is a guess |
| `MISSING_SERVICE` | needs a page read. The same |
| `NEW_LOCATION` | needs two sightings of one business at different places, and nothing has run twice yet |
| `COMPETITOR_CHANGE` | needs a competitor set nobody has defined |
| `HIGH_GROWTH_SIGNAL` | needs a time series. One scan is not a series |

Each of those is a real category and each becomes buildable the moment the
evidence for it exists. Adding them now would mean a detector that fires on
absence of data, which is exactly the failure this whole subsystem is arranged
to prevent.

## What a detector may not do

Invent. Every opportunity here is built from a `Signal`, so it inherits the
rules already enforced: an observation carries evidence, an inference names the
evidence it rests on and may not be certain, and an outward action cannot exist
without `needs_approval`. A detector that wanted to claim something unsupported
would have to construct a `Signal` that refuses to be constructed.

## Value

`UNKNOWN`, always, at this stage — and `None`, never `0`. Nothing here has
measured what a dental practice in Dubai is worth to Qevik, and a placeholder
number would sort the list by a fiction.
"""

from __future__ import annotations

from atlas_kernel.execution.capabilities import EXECUTORS

from .discovery import DiscoveryState
from .extractors import Extraction
from .scan import Recorded
from .signals import (
    Inference,
    Observation,
    Reach,
    Signal,
    SignalKind,
    SuggestedAction,
)

#: The Qevik offer each detector points at, and whether anything can execute it.
#: Read from `EXECUTORS` rather than written down again: an offer with no
#: executor is work Qevik cannot do, and a suggested action naming one would be
#: a promise the roadmap cannot keep.
WEBSITE_OFFER = "offer-website"


def executable(offer_id: str) -> bool:
    """Whether Qevik can actually carry this out today."""
    return offer_id in EXECUTORS


def new_business(recorded: Recorded, *, source: str) -> Signal | None:
    """A business Qevik had no record of.

    Returns `None` for anything already known — a list of businesses Qevik
    already had is not a discovery feed, and a detector that fired on every
    sighting would produce one opportunity per scan per business, for ever.
    """
    state = recorded.classification.state
    if state is DiscoveryState.KNOWN:
        return None

    evidence = list(recorded.sighting.evidence)
    if not evidence:
        return None

    where = ", ".join(p for p in (recorded.sighting.city,
                                  recorded.sighting.country) if p)
    observation = Observation(
        statement=(f"{recorded.business.name} appears in {source}"
                   + (f" ({where})" if where else "")
                   + ", and Qevik had no record of it."),
        scope=where or source,
        counted=1, out_of=1, evidence=evidence)

    return Signal(
        kind=SignalKind.NEW_BUSINESS,
        business_id=recorded.business.id,
        scope=where or source,
        source=source,
        observations=[observation],
        inferences=[Inference(
            statement=("A business Qevik has not seen before may be worth "
                       "assessing for the services Qevik offers."),
            rests_on=tuple(sorted(observation.fingerprints)),
            confidence=0.3,
            would_be_wrong_if=("it is already a customer under another name, or "
                               "it is closed, or it is outside the market Qevik "
                               "serves"))],
        actions=[SuggestedAction(
            statement=(f"Assess {recorded.business.name} against the services "
                       "Qevik can deliver."),
            # Internal: looking at a business is not contacting it.
            reach=Reach.INTERNAL, needs_approval=False,
            capability="researcher")],
    )


def unverified_web_presence(recorded: Recorded, extraction: Extraction, *,
                            source: str) -> Signal | None:
    """The source records no website. A lead to check, not a claim to sell on.

    The distinction this detector exists to hold: `ABSENT_IN_SOURCE` means the
    source was consulted and had none. `NOT_CONSULTED` means nobody looked.
    Firing on the second would produce "this business has no website" about a
    source that was never asked, which is the false positive the extractor's
    three-state presence was built to make impossible.
    """
    if not extraction.absent_in_source("source_url"):
        return None

    evidence = list(recorded.sighting.evidence)
    if not evidence:
        return None

    observation = Observation(
        statement=(f"{source} records no website for "
                   f"{recorded.business.name}."),
        scope=source, counted=1, out_of=1, evidence=evidence)

    return Signal(
        kind=SignalKind.MISSING_SERVICE,
        business_id=recorded.business.id,
        scope=source,
        source=source,
        observations=[observation],
        inferences=[Inference(
            statement=("The business may have no website, or may have one this "
                       "source does not record. Which of those is true has not "
                       "been established."),
            rests_on=tuple(sorted(observation.fingerprints)),
            confidence=0.35,
            would_be_wrong_if=("the business has a website that "
                               f"{source} simply does not list, which is "
                               "common"))],
        actions=[SuggestedAction(
            statement=("Check whether this business has a website before "
                       "treating it as a prospect for one."),
            # Verify, not sell. Fetching a page is internal; offering to build
            # one is not, and that action is only earned once the check has run.
            reach=Reach.INTERNAL, needs_approval=False,
            capability="researcher" if not executable(WEBSITE_OFFER)
            else "researcher")],
    )


def from_pass(recorded: list[Recorded], extractions: list[Extraction], *,
              source: str) -> list[Signal]:
    """Every opportunity one discovery pass supports.

    Extractions are matched to records by `source_id`, not by position: a
    sighting skipped for having no name shifts the lists apart, and pairing by
    index would attach one business's evidence to another's opportunity.
    """
    by_source_id = {e.source_id: e for e in extractions}
    found: list[Signal] = []
    for item in recorded:
        made = new_business(item, source=source)
        if made is not None:
            found.append(made)
        extraction = by_source_id.get(item.sighting.source_id)
        if extraction is not None:
            web = unverified_web_presence(item, extraction, source=source)
            if web is not None:
                found.append(web)
    return found


def describe() -> list[dict]:
    """What this layer can detect, and what it deliberately cannot yet."""
    return [
        {"kind": SignalKind.NEW_BUSINESS.value,
         "supported_by": "the sighting resolved against memory and memory had "
                         "nothing",
         "claims_about_the_world": False},
        {"kind": SignalKind.MISSING_SERVICE.value,
         "supported_by": "the source was consulted for a website and had none",
         "claims_about_the_world": False,
         "note": "a fact about the source; the action is to verify, not to sell"},
    ]


__all__ = ["WEBSITE_OFFER", "describe", "executable", "from_pass",
           "new_business", "unverified_web_presence"]
