"""Images on a customer's website, and the claim each one makes.

`offer-imagery` had no executor, and the reason it is harder than it looks is not
generation. It is that **an image on a business's own website is a claim about
that business.**

A photograph of a kitchen on a caterer's site says: this is our kitchen. A team
photo says: these are our people. A product shot says: this is what you receive.
Put a generated or stock image in any of those places and the site is making a
false statement in the customer's name, to their customers — and unlike invented
copy, nobody reads an image sceptically. It is the most convincing lie a
generated site can tell, and it is the one a reviewer is least likely to catch.

So this module is mostly a refusal, organised around one distinction:

**Documentary slots** show what the business actually is — premises, team,
product, work, equipment, certificates. Only a photograph the business supplied
may go there. Nothing generated, ever, whatever the prompt.

**Decorative slots** carry no factual claim — an abstract header texture, a
pattern behind a section heading, a geometric divider. A generated image is
honest there because it asserts nothing, and it is labelled anyway.

That distinction is not a setting. `SLOTS` is a registry, `documentary` is a
property of the slot rather than of the request, and a caller cannot pass a flag
that turns one into the other.

Everything carries provenance to the rendered page: an `alt` a person can read,
and a `data-provenance` attribute naming what produced the image. A generated
image that is indistinguishable from a photograph in the markup is one nobody can
audit later.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

#: Where an image can go, and whether being there is a factual claim.
#:
#: One registry rather than a flag on the request. A caller cannot mark a
#: premises photograph "decorative" to get a generated one past the check,
#: because the slot decides and the slot is named in the offer.
SLOTS: dict[str, bool] = {
    # Documentary — only a supplied photograph belongs here.
    "premises": True,
    "team": True,
    "product": True,
    "work": True,
    "equipment": True,
    "certificate": True,
    "food": True,
    # Decorative — carries no claim about the business.
    "header_texture": False,
    "section_pattern": False,
    "divider": False,
    "background": False,
}


class Origin(StrEnum):
    """Where an image came from. Recorded on the page, not only in a database."""

    SUPPLIED = "supplied"          # the business gave us this file
    GENERATED = "generated"        # a model made it
    STOCK = "stock"                # licensed from a library


class ImageryRefused(Exception):
    """This image must not go in this slot, and why."""


class ImageRequest(BaseModel):
    """One image somebody wants on the site."""

    model_config = ConfigDict(frozen=True)

    slot: str
    #: What it should look like. Only meaningful for a generated image.
    prompt: str = ""
    #: Set for a supplied or stock image.
    source_url: str = ""
    #: What a screen reader says, and what a person reads when it fails to load.
    #: Required: an image with no alt is invisible to part of the audience and
    #: is an accessibility defect Qevik detects on other people's sites.
    alt: str
    origin: Origin = Origin.GENERATED
    #: Who supplied it, for a photograph. A supplied image with nobody behind it
    #: cannot be queried when it turns out to be the wrong building.
    supplied_by: str = ""
    #: What the provider actually charged, when it said. `None` is UNKNOWN and
    #: is never rendered as zero.
    cost: float | None = None
    provider: str = ""
    model: str = ""


class Image(BaseModel):
    """An image that has been allowed, with everything needed to audit it."""

    model_config = ConfigDict(frozen=True)

    slot: str
    alt: str
    origin: Origin
    url: str = ""
    provider: str = ""
    model: str = ""
    supplied_by: str = ""
    cost: float | None = None
    documentary: bool = False

    def markup(self) -> str:
        """The `<img>`, carrying its own provenance.

        `data-provenance` is on the element rather than only in a report,
        because the question "is this photograph real" is asked while looking at
        the page, usually by somebody who has never seen the report.
        """
        origin = html.escape(self.origin.value, quote=True)
        made_by = f"{self.provider}/{self.model}".strip("/")
        provenance = origin if not made_by else f"{origin}:{html.escape(made_by, quote=True)}"
        return (f'<img src="{html.escape(self.url, quote=True)}" '
                f'alt="{html.escape(self.alt, quote=True)}" '
                f'loading="lazy" decoding="async" '
                f'data-provenance="{provenance}">')


def documentary(slot: str) -> bool:
    """Whether being in this slot is a claim about the business.

    An unknown slot is treated as documentary. That is the safe direction: a
    slot nobody has classified might be a premises photograph, and the failure
    of guessing wrong is a false claim on a customer's site rather than a
    missing decoration.
    """
    return SLOTS.get(slot, True)


def check(request: ImageRequest) -> dict:
    """Whether this image may be used, and why not. Never raises."""
    problems: list[str] = []
    is_documentary = documentary(request.slot)

    if is_documentary and request.origin is not Origin.SUPPLIED:
        problems.append(
            f"a {request.slot} image says 'this is ours'. "
            f"A {request.origin.value} image there is a false statement about "
            "the business, published in their name — and nobody reads an image "
            "sceptically. Ask the customer for a photograph.")
    if request.origin is Origin.SUPPLIED and not request.supplied_by.strip():
        problems.append(
            "nobody is recorded as having supplied this photograph, so it "
            "cannot be queried when it turns out to be the wrong building")
    if request.origin is not Origin.SUPPLIED and not request.prompt.strip():
        problems.append("a generated image with no prompt has no provenance")
    if not request.alt.strip():
        problems.append(
            "an image with no alt text is invisible to part of the audience, "
            "and a missing alt is a defect Qevik detects on other people's sites")
    if request.slot not in SLOTS:
        problems.append(
            f"{request.slot!r} is not a slot this theme has. Unknown slots are "
            "treated as documentary, so nothing generated may go there.")

    return {
        "usable": not problems,
        "slot": request.slot,
        "documentary": is_documentary,
        "origin": request.origin.value,
        "problems": problems,
        "statement": ("Allowed." if not problems
                      else f"{len(problems)} thing(s) stop this image: "
                           + "; ".join(problems)),
    }


def allow(request: ImageRequest, *, url: str) -> Image:
    """Turn a checked request into an image, or refuse it."""
    report = check(request)
    if not report["usable"]:
        raise ImageryRefused(report["statement"])
    return Image(slot=request.slot, alt=request.alt, origin=request.origin,
                 url=url, provider=request.provider, model=request.model,
                 supplied_by=request.supplied_by, cost=request.cost,
                 documentary=report["documentary"])


class Plan(BaseModel):
    """What imagery a site would use, before anything is generated.

    Produced first and shown, because generation costs money and a customer
    should see what is about to be made — and because the documentary slots
    resolve to *requests for a photograph*, which is a task for them rather than
    a job for us.
    """

    model_config = ConfigDict(frozen=True)

    allowed: tuple[Image, ...] = ()
    #: Slots that need a photograph the customer has not supplied.
    needs_photograph: tuple[str, ...] = ()
    refused: tuple[dict, ...] = ()

    @property
    def cost(self) -> float | None:
        """Summed over images whose provider reported one.

        `None` when none did — not zero, for the same reason a missing
        measurement is not zero.
        """
        known = [i.cost for i in self.allowed if i.cost is not None]
        return round(sum(known), 6) if known else None

    def summary(self) -> dict:
        return {
            "images": [i.model_dump(mode="json") for i in self.allowed],
            "needs_photograph": list(self.needs_photograph),
            "refused": list(self.refused),
            "cost": self.cost,
            "cost_state": "MEASURED" if self.cost is not None else "UNKNOWN",
            "note": ("Documentary slots — premises, team, product, work — take "
                     "only photographs the business supplied. Nothing generated "
                     "goes there, whatever the prompt."),
        }


def plan(requests: tuple[ImageRequest, ...], *,
         resolve_url: Callable[[ImageRequest], str]) -> Plan:
    """Decide what may be used, what is refused, and what the customer must send.

    `resolve_url` is injected: it is where an image actually comes from — a
    generation provider, an asset store, a URL the customer gave us — and this
    module does not care which. What it cares about is what the image claims.
    """
    allowed: list[Image] = []
    refused: list[dict] = []
    wanted: list[str] = []

    for request in requests:
        report = check(request)
        if report["usable"]:
            allowed.append(allow(request, url=resolve_url(request)))
            continue
        refused.append(report)
        if report["documentary"] and request.origin is not Origin.SUPPLIED:
            wanted.append(request.slot)

    return Plan(allowed=tuple(allowed),
                needs_photograph=tuple(sorted(set(wanted))),
                refused=tuple(refused))


#: Where decorative imagery is inserted, keyed by the marker it goes before.
#: Only decorative slots appear here — a documentary image has no automatic
#: position, because where a premises photograph belongs is a decision about
#: the business rather than about the template.
PLACEMENT: dict[str, str] = {
    "header_texture": "</header>",
    "section_pattern": "<footer>",
    "divider": "<footer>",
    "background": "</header>",
}


def apply(files: dict[str, str], images: tuple[Image, ...]) -> dict[str, str]:
    """Put the allowed decorative images into the rendered pages.

    Documentary images are returned in the plan and **not** placed
    automatically. Where a photograph of the premises belongs is a decision
    about the business, and a template that drops one into a header has decided
    something nobody asked it to.
    """
    updated = dict(files)
    for image in images:
        if image.documentary:
            continue
        marker = PLACEMENT.get(image.slot)
        if marker is None:
            continue
        for name, markup in list(updated.items()):
            if name.endswith(".html") and marker in markup:
                updated[name] = markup.replace(
                    marker, f'<p class="art">{image.markup()}</p>\n{marker}', 1)
    return updated
