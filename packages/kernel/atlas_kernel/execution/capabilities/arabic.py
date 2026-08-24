"""Build the Arabic half of a site, from Arabic a person supplied.

`offer-arabic-experience` is the offer this engine recommends most often for UAE
businesses and the one with the highest unit value — and until now it had no
executor, so the roadmap proposed work Qevik could not perform. This is that
executor.

It refuses more than it builds, on purpose. `website/arabic.py` explains why at
length; the short version is that machine-translating a business's description of
itself publishes a claim about them, in their name, in a language the person
approving it usually cannot read. The failure is silent, looks finished, and is
discovered by a customer's customer.

So the executor's contract is: supply Arabic, get an Arabic site. Supply nothing,
get a refusal that names exactly what is missing — which is a task for the
customer, not a smaller job for us.
"""

from __future__ import annotations

from typing import Any

from ...opportunity.models import Business
from ...website.arabic import ArabicContent, NotTranslated, check, pair, translated
from ...website.content import SiteContent
from ...website.generation import generate
from .website import _facts


class NothingToTranslate(Exception):
    """No Arabic was supplied, so there is no Arabic page to build."""


def build_arabic_experience(*, business_name: str = "", research: dict | None = None,
                            strengths: tuple[str, ...] = (),
                            business: Business | None = None,
                            content: SiteContent | None = None,
                            arabic: ArabicContent | dict | None = None,
                            website: str = "", published: bool = False,
                            theme: str = "clean",
                            **_: Any) -> tuple[dict[str, str], dict]:
    """The English site and its Arabic counterpart, as one bundle.

    Takes the same four arguments `execution/service.py` passes every executor —
    `business_name`, `research`, `strengths`, `business` — and derives the
    English content through `website._facts`, exactly as `build_website` does.
    `content` remains accepted so a caller that already has it need not rebuild
    it, but the service's calling convention is the contract.

    Returns both languages together rather than the Arabic alone: they share a
    sitemap, they link to each other, and shipping the Arabic pages separately
    would produce two sites competing for one canonical.

    Raises `NothingToTranslate` when there is nothing to build. The refusal
    carries the report, so the caller can turn it into a customer task naming
    the exact fields rather than a generic "translation needed".
    """
    if content is None:
        content, _missing = _facts(business, business_name, research or {})

    supplied = (ArabicContent.model_validate(arabic) if isinstance(arabic, dict)
                else arabic)
    if supplied is None:
        raise NothingToTranslate(
            "No Arabic was supplied. Qevik does not translate — a machine "
            "translation of a business's own words is a claim about them, "
            "published in their name, in a language the approver usually "
            "cannot read. Ask the customer for the Arabic.")

    report = check(supplied, content)
    if not report["buildable"]:
        raise NothingToTranslate(report["statement"])

    english_files, english_provenance = generate(content, theme=theme,
                                                 website=website,
                                                 published=published)
    try:
        arabic_content = translated(supplied, content)
    except NotTranslated as refusal:             # pragma: no cover - check first
        raise NothingToTranslate(str(refusal)) from refusal

    arabic_files, arabic_provenance = generate(arabic_content, theme=theme,
                                               website=website,
                                               published=published)
    files = pair(english_files, arabic_files)

    provenance = {
        **english_provenance,
        "languages": ["en", "ar"],
        "strengths_noted": list(strengths),
        "arabic": {
            **report,
            "supplied_by": supplied.supplied_by,
            "sections_built": len(report["supplied"]),
            "services_without_arabic": report["missing_services"],
            "arabic_facts": arabic_provenance["facts"],
        },
        # Repeated at the top level, not only nested, because this is the
        # question an approver asks about an Arabic page and it must not be
        # somewhere they have to go looking for.
        "machine_translated": False,
    }
    return files, provenance
