"""Executors, keyed by the offer they fulfil.

Six entries. The lookup is what makes "no executor for that capability" a
refusal rather than a crash, and it is the authority the roadmap consults before
telling a customer that Qevik can do something — an offer existing is not the
same as something being able to perform it.
"""

from collections.abc import Callable
from typing import Any

from .arabic import NothingToTranslate, build_arabic_experience
from .editorial import build_editorial_hub
from .enquiry import NowhereToSend, build_enquiry_capability
from .healthcheck import NothingObserved, Unevidenced, build_health_check
from .imagery import NothingToIllustrate, build_imagery
from .portfolio import build_portfolio_index
from .website import NothingToBuild, WebsiteMode, build_website

#: What every executor is. A capability produces one document or a bundle of
#: files, plus the provenance saying what it was built from.
#:
#: `Callable[..., ...]` says nothing about the arguments, which is how two
#: executors were registered with an incompatible signature and failed at
#: execution rather than at import — the roadmap offered the work, the approval
#: was granted, and the job failed inside `execute()` with a TypeError. So the
#: contract is also stated as data below and checked by a test.
Executor = Callable[..., tuple[str | dict[str, str], dict[str, Any]]]

#: Exactly what `execution/service.py` passes every executor. An executor that
#: cannot accept all four is one that will fail after a customer has approved
#: the work, which is the worst moment to discover it.
CALLING_CONVENTION: tuple[str, ...] = ("business_name", "research", "strengths",
                                       "business")

#: Offers that need something only the customer can supply, and what that is.
#:
#: An executor existing is not sufficient for a task to be executable — the
#: execution service passes only `business_name`, `research`, `strengths` and
#: `business`, so a capability needing anything else can *never* succeed through
#: the roadmap path. `offer-arabic-experience` is the case that showed this: the
#: executor was registered, the roadmap promised the work, the approval was
#: granted, and execution refused because nobody had supplied any Arabic.
#:
#: The refusal was correct. Presenting the task as "Qevik can do this" was not.
#: So an offer listed here is presented as needing the customer first, and the
#: roadmap turns the requirement into a customer task rather than a promise.
REQUIRES_CUSTOMER_INPUT: dict[str, str] = {
    "offer-arabic-experience":
        "Arabic copy written by a person — Qevik does not translate, because a "
        "machine translation of a business's own words is a claim about them "
        "in a language the approver usually cannot read.",
    "offer-enquiry-builder":
        "An email address or a WhatsApp number for enquiries to reach. A form "
        "with nowhere to deliver discards what a visitor writes while they "
        "believe they made contact, which is worse than having no form.",
    # Decorative imagery needs nothing from the customer, but the documentary
    # slots — premises, team, product, work — take only photographs they
    # supply. Listed because the *valuable* half of this offer is theirs to
    # unblock, and promising it without saying so is promising their photos.
    "offer-imagery":
        "Photographs of the premises, team, product or work. Qevik will not "
        "generate these: an invented photograph on a business's own site is a "
        "false statement about them, published in their name.",
}

#: offer id -> executor. An offer with no entry cannot be executed.
EXECUTORS: dict[str, Executor] = {
    "offer-portfolio-system": build_portfolio_index,
    "offer-website": build_website,
    "offer-editorial": build_editorial_hub,
    # The offer this engine recommends most often for UAE businesses, and the
    # one that had no executor — so the roadmap proposed work Qevik could not do.
    "offer-arabic-experience": build_arabic_experience,
    # The enquiry *form*, which is `offer-enquiry-builder` — not
    # `offer-one-tap-contact`, which answers `reachability` and `whatsapp` and
    # is the simpler thing the theme's `tel:` link already does.
    "offer-enquiry-builder": build_enquiry_capability,
    "offer-imagery": build_imagery,
    # The digital product. Needs nothing from the customer -- it is built from
    # the audit Qevik already holds about them, which is why it is absent from
    # REQUIRES_CUSTOMER_INPUT while a price calculator or a booking tool could
    # never be.
    "offer-health-check": build_health_check,
}

__all__ = ["CALLING_CONVENTION", "EXECUTORS", "REQUIRES_CUSTOMER_INPUT",
           "Executor", "NothingObserved", "NothingToBuild",
           "NothingToTranslate", "NothingToIllustrate", "NowhereToSend",
           "Unevidenced", "WebsiteMode",
           "build_arabic_experience", "build_editorial_hub",
           "build_enquiry_capability", "build_health_check", "build_imagery",
           "build_portfolio_index", "build_website"]
