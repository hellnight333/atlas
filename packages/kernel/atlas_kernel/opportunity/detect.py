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

**`WEAK_WEB_PRESENCE`** — supported since the verification recipe started
fetching the sites memory records. This is the first detector here that says
something about **the business** rather than about a source or about Qevik: a
server answered, the audit read what it returned, and the defects are what that
response contains. It is also the first that can lead to a sale, which is why
its action is `OUTWARD` and needs a person.

The categories that are **not** here, and why:

| not built | why |
|---|---|
| `MISSING_SERVICE` | needs a page read for what the business offers, which the homepage audit does not extract |
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
from .models import (
    SEVERITY_WEIGHT,
    Business,
    Evidence,
    Finding,
    FindingKind,
)
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

#: Which declared opportunity key each audited defect belongs to.
#:
#: The vocabulary is `outreach/opportunity.py`'s and the answering side is
#: `recommendation/offers.py`'s `answers` set — neither is restated here, and
#: `answerable` checks against the real declaration rather than against this
#: table. That is deliberate: the table says *what a defect is*, and the offer
#: says *what it can fix*, and letting one of them imply the other is how a
#: pitch ends up promising work nobody declared.
#:
#: The kinds absent from this table are absent on purpose. A missing viewport,
#: a missing title, a missing meta description, no structured data and plain
#: HTTP are all real, observed and worth showing — and no offer in the
#: catalogue declares that it answers them. They become observations on the
#: signal and never a suggested sale. Widening `offer-website.answers` to cover
#: them is a reviewed decision somebody should make on purpose; inferring it
#: here would make the promise without the review.
ANSWERED_BY: dict[FindingKind, str] = {
    FindingKind.SITE_UNREACHABLE: "broken",
    FindingKind.SLOW_RESPONSE: "performance",
    FindingKind.THIN_CONTENT: "thin_content",
}


def executable(offer_id: str) -> bool:
    """Whether Qevik can actually carry this out today."""
    return offer_id in EXECUTORS


def answerable(findings: list[Finding], *, offer_id: str = WEBSITE_OFFER
               ) -> tuple[str, ...]:
    """The opportunity keys this offer declares it answers, among these findings.

    Empty means the defects are real and nothing in the catalogue claims to fix
    them — which is a state the system is allowed to be in, and says so, rather
    than routing the work to whichever offer is nearest.
    """
    from atlas_kernel.recommendation.offers import BY_ID

    offer = BY_ID.get(offer_id)
    if offer is None:
        return ()
    keys = {ANSWERED_BY[f.kind] for f in findings if f.kind in ANSWERED_BY}
    return tuple(sorted(keys & set(offer.answers)))


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


#: Below this, an audit found nothing worth raising an opportunity over. One
#: missing meta description is a note, not a reason to approach a business.
WORTH_RAISING = 2


def weak_web_presence(business: Business, findings: list[Finding],
                      response: Evidence, *, source: str) -> Signal | None:
    """The site was fetched, audited, and what came back is weak.

    The detector `detect.py` has carried in its own table of things it could
    not build, with the reason: *needs the site fetched and audited*. That is
    what has now happened, so this is the same evidence bar the others hold,
    met rather than waived.

    Three things keep it honest.

    **It rests on a response.** `response` is the evidence a verification
    mission recorded when a guarded fetcher retrieved the page, and every
    observation carries it. Without it the signal would rest only on evidence
    the audit derived from itself, and the chain back to "a server actually
    said this, at this time, to this fetcher" would be missing.

    **It fires on weight, not on existence.** A single low-severity finding is
    a note. `WORTH_RAISING` is what separates an opportunity from a lint
    result, and it is a named constant because it is the part somebody will
    want to move once real reply rates come back.

    **It only offers what an offer declares.** `answerable` decides whether
    there is a sale here at all. When nothing in the catalogue answers these
    defects the signal still exists — the findings are real — and its action
    stays inside Qevik.
    """
    if not findings:
        return None
    weight = sum(SEVERITY_WEIGHT[f.severity] for f in findings)
    if weight < WORTH_RAISING:
        return None

    supporting = [response]
    seen = {response.fingerprint}
    for finding in findings:
        for piece in finding.evidence:
            if piece.fingerprint not in seen:
                seen.add(piece.fingerprint)
                supporting.append(piece)

    observations = [
        Observation(
            statement=finding.statement,
            scope=business.website or response.source,
            counted=1, out_of=1,
            # The audited response first: it is what proves the fetch, and a
            # reader following the first fingerprint should land on the server's
            # actual reply rather than on a summary of it.
            evidence=[response, *finding.evidence])
        for finding in findings
    ]

    keys = answerable(findings)
    worst = max(findings, key=lambda f: SEVERITY_WEIGHT[f.severity])
    # The weakest link in the chain, not the average: a finding read straight
    # out of returned markup is near-certain, and one timing sample is not, and
    # an inference resting on both is only as good as the timing sample.
    confidence = min(0.9, min(f.confidence for f in findings))

    if keys and executable(WEBSITE_OFFER):
        action = SuggestedAction(
            statement=(f"Offer {business.name} a rebuilt website. Qevik's "
                       f"{WEBSITE_OFFER} answers {', '.join(keys)}."),
            # Approaching a business is not undoable, and no audit result may
            # make it automatic.
            reach=Reach.OUTWARD, needs_approval=True,
            capability=WEBSITE_OFFER)
    else:
        action = SuggestedAction(
            statement=(f"Review what {business.name}'s site needs. The defects "
                       "observed are real and no declared offer answers them, "
                       "so there is nothing to propose yet."),
            reach=Reach.INTERNAL, needs_approval=False,
            capability="researcher")

    return Signal(
        kind=SignalKind.WEAK_WEB_PRESENCE,
        business_id=business.id,
        scope=business.website or response.source,
        source=source,
        observations=observations,
        inferences=[Inference(
            statement=(f"{business.name}'s website is losing visitors it "
                       f"already has: {worst.statement.rstrip('.').lower()}."),
            rests_on=tuple(sorted({p.fingerprint for o in observations
                                   for p in o.evidence})),
            confidence=confidence,
            would_be_wrong_if=("the page was having a bad minute, the site "
                               "renders its content in the browser rather than "
                               "in the document, or the business does not care "
                               "what its website does"))],
        actions=[action],
    )


def from_verification(audited: dict[str, list[Finding]],
                      businesses: dict[str, Business],
                      responses: dict[str, Evidence], *,
                      source: str) -> list[Signal]:
    """Every opportunity one verification pass supports, by business id.

    `responses` maps business id to the recorded response that was audited, so
    a signal cannot be built without the evidence that a fetch happened. A
    business whose response is missing is skipped rather than given a signal
    resting on derived evidence alone.
    """
    found: list[Signal] = []
    for business_id, findings in audited.items():
        business = businesses.get(business_id)
        response = responses.get(business_id)
        if business is None or response is None:
            continue
        made = weak_web_presence(business, findings, response, source=source)
        if made is not None:
            found.append(made)
    return found


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
        {"kind": SignalKind.WEAK_WEB_PRESENCE.value,
         "supported_by": "the recorded website was fetched and the response "
                         "audited by the website detector's rules",
         "claims_about_the_world": True,
         "note": ("the only detector here that rests on the business's own "
                  "server answering. Offers only what "
                  f"{WEBSITE_OFFER} declares it answers: "
                  f"{', '.join(sorted(set(ANSWERED_BY.values())))}")},
    ]


__all__ = ["ANSWERED_BY", "WEBSITE_OFFER", "WORTH_RAISING", "answerable",
           "describe", "executable", "from_pass", "from_verification",
           "new_business", "unverified_web_presence", "weak_web_presence"]
