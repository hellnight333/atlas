"""Add a working way to be contacted, to a site that has none.

`offer-one-tap-contact` and the enquiry opportunity are the second-most-common
recommendation this engine makes, and neither had an executor.

The refusal that shapes this: **a business with no email and no WhatsApp gets no
form.** Rendering one anyway would fill the section and discard every enquiry —
worse than nothing, because the visitor believes they made contact. Instead the
executor raises, naming the fact the customer must supply, which becomes a task
for them rather than a smaller job for us.
"""

from __future__ import annotations

from typing import Any

from ...opportunity.models import Business
from ...website import enquiry as enquiry_block
from ...website.content import SiteContent
from ...website.generation import generate
from .website import _facts


class NowhereToSend(Exception):
    """The business has no channel an enquiry could reach it through."""


def build_enquiry_capability(*, business_name: str = "",
                             research: dict | None = None,
                             strengths: tuple[str, ...] = (),
                             business: Business | None = None,
                             content: SiteContent | None = None,
                             website: str = "", published: bool = False,
                             theme: str = "clean",
                             **_: Any) -> tuple[dict[str, str], dict]:
    """The site, with an enquiry form that works with no server behind it.

    Takes the four arguments `execution/service.py` passes every executor and
    derives content through `website._facts`, the same as `build_website`.

    Delivered through `mailto:` and WhatsApp deep links composed on the
    visitor's own device. `hosted_form_gap()` travels in the provenance so the
    upgrade to a posted form is a costed, known step rather than something
    discovered when somebody asks why enquiries are not arriving in a database.
    """
    if content is None:
        content, _missing = _facts(business, business_name, research or {})

    available = enquiry_block.channels(content)
    if not available:
        raise NowhereToSend(
            "This business has no email address and no WhatsApp number, so an "
            "enquiry form would have nowhere to deliver to. A form that "
            "discards what a visitor writes is worse than no form: they believe "
            "they made contact. Ask the customer for one of the two.")

    files, provenance = generate(content, theme=theme, website=website,
                                 published=published)

    block = enquiry_block.form(content)
    styles = enquiry_block.styles()
    changed = []
    for name, markup in list(files.items()):
        if not name.endswith(".html"):
            continue
        # On the page that already carries contact details, immediately after
        # them. A form separated from the phone number makes a visitor choose
        # between two things that are the same thing.
        if "<h2>Contact</h2>" not in markup:
            continue
        updated = markup.replace("</style>", styles + "</style>", 1)
        updated = updated.replace("<footer>", block + "\n<footer>", 1)
        files[name] = updated
        changed.append(name)

    if not changed:
        # Every page lacked a contact section, so the form has no home. Adding
        # it to an arbitrary page would put it somewhere nobody is looking.
        raise NowhereToSend(
            "No page carries contact details, so there is nowhere on this site "
            "an enquiry form belongs. Generate the contact section first.")

    # The sitemap and robots were built from the pages before the form was
    # inserted, and neither depends on page content — but the *bundle hash*
    # does, and the caller hashes after this returns.
    provenance["strengths_noted"] = list(strengths)
    provenance["enquiry"] = {
        "channels": list(available),
        "pages": changed,
        "server_required": False,
        "hosted_form": enquiry_block.hosted_form_gap(),
        "note": ("Delivered by the visitor's own mail client or WhatsApp. "
                 "Nothing is posted to Qevik, so no enquiry can be lost by us "
                 "and none becomes personal data we hold."),
    }
    return files, provenance
