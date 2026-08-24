"""Supporting imagery for a customer's site.

`offer-imagery` answers `unillustrated`, and it had no executor. The reason it
is harder than generation is that an image on a business's own website is a
claim about that business — see `website/imagery.py`, which is where the rule
lives.

This executor's job is to apply that rule to a whole site and produce a *plan*
before anything is generated: what can be made, what the customer has to
photograph, and what it would cost. Generation is deliberately not triggered
here — a capability that spends money the moment it is executed is one nobody
can review beforehand.
"""

from __future__ import annotations

from typing import Any

from ...opportunity.models import Business
from ...website import imagery
from ...website.content import SiteContent
from ...website.generation import generate
from .website import _facts


class NothingToIllustrate(Exception):
    """No image may be placed on this site, and why."""


#: What a site gets when nobody has asked for anything specific. Decorative
#: only: the documentary slots are things the customer must photograph, and
#: proposing them here would read as an offer to produce them.
DEFAULT_SLOTS: tuple[str, ...] = ("header_texture", "divider")


def build_imagery(*, business_name: str = "", research: dict | None = None,
                  strengths: tuple[str, ...] = (),
                  business: Business | None = None,
                  content: SiteContent | None = None,
                  requests: tuple[imagery.ImageRequest, ...] | None = None,
                  resolve_url: Any = None, website: str = "",
                  published: bool = False, theme: str = "clean",
                  **_: Any) -> tuple[dict[str, str], dict]:
    """The site with decorative imagery applied, and the plan behind it.

    `resolve_url` is where an image actually comes from — a generation
    provider, an asset store, a URL the customer supplied. Injected, because
    this module's concern is what an image claims rather than who made it.

    With no resolver, nothing is placed and the plan still says what *would*
    be. That is the useful output before anybody spends money.
    """
    if content is None:
        content, _missing = _facts(business, business_name, research or {})

    wanted = requests or tuple(
        imagery.ImageRequest(
            slot=slot, prompt=f"an abstract {slot.replace('_', ' ')}",
            alt=f"Decorative {slot.replace('_', ' ')}")
        for slot in DEFAULT_SLOTS)

    # No resolver means nothing can be fetched or generated. The plan is still
    # produced — and it is the thing worth showing first.
    resolver = resolve_url or (lambda request: "")
    proposed = imagery.plan(wanted, resolve_url=resolver)

    files, provenance = generate(content, theme=theme, website=website,
                                 published=published)
    placeable = tuple(i for i in proposed.allowed if i.url)
    if placeable:
        files = imagery.apply(files, placeable)

    provenance["imagery"] = {
        **proposed.summary(),
        "placed": [i.slot for i in placeable],
        "generated_now": bool(placeable),
        "strengths_noted": list(strengths),
        "note": ("A plan, not a purchase. Nothing was generated unless a "
                 "resolver produced it, so this can be reviewed before it "
                 "costs anything."),
    }
    return files, provenance
