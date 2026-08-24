"""The enquiry form, tested on the defect it exists to avoid becoming.

A contact form that silently discards what a visitor writes is the single most
expensive defect a small business site can carry: the visitor believes they made
contact, and the business never learns they existed. It is worse than having no
form at all, and it is what "build the form and wire it up later" ships.

Qevik has no SMTP credential, no host that runs code, and no database a stranger
may write to. So the form here is delivered by `mailto:` and WhatsApp deep links
composed on the visitor's own device — nothing passes through us, and nothing we
own can drop it.

The tests are mostly about the refusals and about the honesty of the trade: a
business with no channel gets no form, both channels are emitted when both
exist, and the cost of the eventual posted form is written into the provenance
rather than discovered later.
"""

from __future__ import annotations

import pytest

from atlas_kernel.execution.capabilities import (
    EXECUTORS,
    NowhereToSend,
    build_enquiry_capability,
)
from atlas_kernel.website import enquiry, seo
from atlas_kernel.website.content import (
    ContactDetails,
    Fact,
    FactSource,
    SiteContent,
)


def _f(value: str) -> Fact:
    return Fact(value=value, source=FactSource.OPERATOR)


@pytest.fixture
def both() -> SiteContent:
    return SiteContent(business_name=_f("Al Hamra"),
                       contact=ContactDetails(email=_f("hello@alhamra.ae"),
                                              whatsapp=_f("+971 50 555 0100")),
                       location=_f("Dubai"))


# ============================================ no form without a destination

def test_a_business_with_no_channel_gets_no_form() -> None:
    """Rendering one anyway would fill the section and discard every enquiry."""
    with pytest.raises(NowhereToSend) as refused:
        build_enquiry_capability(content=SiteContent(business_name=_f("X")))
    assert "nowhere to deliver" in str(refused.value)
    assert "worse than no form" in str(refused.value)


def test_the_block_itself_returns_nothing_rather_than_an_empty_form() -> None:
    """Empty is the honest answer, and it is the answer a caller can act on."""
    assert enquiry.form(SiteContent(business_name=_f("X"))) == ""


def test_the_refusal_names_what_the_customer_must_supply() -> None:
    with pytest.raises(NowhereToSend, match="Ask the customer"):
        build_enquiry_capability(content=SiteContent(business_name=_f("X")))


# ============================================ it works with no server

def test_both_channels_are_emitted_when_both_exist(both) -> None:
    """A mailto form fails for a visitor with no mail client configured, and
    that is the mitigation available without a server."""
    files, provenance = build_enquiry_capability(content=both)
    page = files["index.html"]

    assert "mailto:hello@alhamra.ae" in page
    assert "wa.me/971505550100" in page
    assert provenance["enquiry"]["channels"] == ["mailto", "whatsapp"]


def test_a_whatsapp_link_carries_digits_only() -> None:
    """`https://wa.me/+971 50 …` is a broken link, and it looks correct."""
    content = SiteContent(business_name=_f("X"),
                          contact=ContactDetails(whatsapp=_f("+971 50 555 0100")))
    assert "wa.me/971505550100" in enquiry.form(content)
    assert "wa.me/+971" not in enquiry.form(content)


def test_email_only_produces_only_the_email_route(both) -> None:
    content = both.model_copy(update={
        "contact": ContactDetails(email=_f("hello@alhamra.ae"))})
    page = enquiry.form(content)
    # The rendered *links*, not the whole page: the inline script carries both
    # branches whatever the business has, and matching on raw text tests the
    # script rather than the form.
    assert 'href="mailto:' in page
    assert 'href="https://wa.me/' not in page
    assert 'data-channel="whatsapp"' not in page


def test_nothing_is_posted_anywhere(both) -> None:
    """No endpoint means no enquiry Qevik can lose, and none that becomes
    personal data we hold."""
    files, provenance = build_enquiry_capability(content=both)
    page = files["index.html"]

    assert 'action=' not in page, "a form with an action posts somewhere"
    assert 'method="post"' not in page.lower()
    assert provenance["enquiry"]["server_required"] is False


def test_the_form_still_works_with_scripting_off(both) -> None:
    """Progressive enhancement over a working link, not a link that needs
    JavaScript to work at all."""
    page = enquiry.form(both)
    # The href is complete before any script touches it.
    assert 'href="mailto:hello%40alhamra.ae?subject=' in page
    assert 'href="https://wa.me/971505550100"' in page


def test_the_visitor_is_told_where_their_message_goes(both) -> None:
    """A button that opens their mail client without warning reads as broken."""
    assert "opens your own email app" in enquiry.form(both)


# ============================================ the cost of the real form

def test_the_upgrade_to_a_posted_form_is_costed_rather_than_promised(both
                                                                     ) -> None:
    """"We'll wire it up later" is how a dead form ships."""
    _, provenance = build_enquiry_capability(content=both)
    gap = provenance["enquiry"]["hosted_form"]

    assert gap["status"] == "PENDING_INFRASTRUCTURE"
    kinds = {need["kind"] for need in gap["needs"]}
    assert "PENDING_CREDENTIAL" in kinds
    assert "PENDING_INFRASTRUCTURE" in kinds
    # Spam and retention are named, because both are how a posted form becomes
    # a liability rather than a feature.
    detail = " ".join(need["item"] for need in gap["needs"])
    assert "spam" in detail.lower() and "personal data" in detail.lower()


def test_the_trade_is_stated_not_hidden(both) -> None:
    _, provenance = build_enquiry_capability(content=both)
    assert "converts worse" in provenance["enquiry"]["hosted_form"]["trade"]


def test_the_smtp_credential_is_named_by_the_name_the_centre_uses(both) -> None:
    """So the gap and the Credential Centre are talking about one thing."""
    from atlas_kernel.integrations import BY_ID

    _, provenance = build_enquiry_capability(content=both)
    needed = {need.get("credential") for need in
              provenance["enquiry"]["hosted_form"]["needs"]}
    assert BY_ID["smtp"].credential in needed


# ============================================ it does not break the bundle

def test_the_bundle_still_passes_our_own_audit(both) -> None:
    files, _ = build_enquiry_capability(content=both)
    assert seo.audit(files)["findings"] == []


def test_the_form_lands_beside_the_contact_details(both) -> None:
    """Separated from the phone number, it makes a visitor choose between two
    things that are the same thing."""
    files, _ = build_enquiry_capability(content=both)
    page = files["index.html"]
    assert page.index("<h2>Contact</h2>") < page.index("Send an enquiry")


def test_generation_stays_deterministic(both) -> None:
    first, _ = build_enquiry_capability(content=both)
    second, _ = build_enquiry_capability(content=both)
    assert first == second


def test_the_inline_script_carries_no_control_byte_class() -> None:
    """A literal NUL inside a `<script>` block kills the whole block silently,
    so the sanitising is a length cap rather than a control-character strip."""
    script = enquiry._script()
    assert "\\x00" not in script and "\x00" not in script
    assert "slice(0,1500)" in script, "a length cap, not a character class"


def test_an_arabic_form_is_labelled_in_arabic(both) -> None:
    """An Arabic page with an English form is the mixed artefact the Arabic
    capability exists to prevent."""
    page = enquiry.form(both, arabic=True)
    assert "أرسل استفسارًا" in page
    assert "Send an enquiry" not in page


# ============================================ the offer can now be performed

def test_the_offer_has_an_executor() -> None:
    """`offer-enquiry-builder`, which answers `enquiry`.

    Not `offer-one-tap-contact`: that answers `reachability` and `whatsapp` and
    is the simpler thing the theme's `tel:` link already does. Registering this
    against it made a business with a phone number and no email look unable to
    do the one thing it could.
    """
    assert "offer-enquiry-builder" in EXECUTORS
    assert EXECUTORS["offer-enquiry-builder"] is build_enquiry_capability


def test_the_offer_declares_that_it_needs_a_channel_from_the_customer() -> None:
    """Executable-in-principle is not executable-for-this-business.

    An executor that refuses at execution time is correct; a roadmap that
    promised the work beforehand is not, and the customer read the promise.
    """
    from atlas_kernel.execution.capabilities import REQUIRES_CUSTOMER_INPUT

    assert "offer-enquiry-builder" in REQUIRES_CUSTOMER_INPUT
    assert "nowhere to deliver" in REQUIRES_CUSTOMER_INPUT["offer-enquiry-builder"]


def test_escaping_survives(both) -> None:
    hostile = both.model_copy(update={
        "business_name": _f('</script><script>alert(1)</script>')})
    assert "<script>alert(1)</script>" not in enquiry.form(hostile)
