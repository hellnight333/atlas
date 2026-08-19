"""The template that gets sold.

Two things are defended here, and they are commercial rather than technical.

**Nothing is invented about a real business.** A dentist who finds a made-up
principal, a made-up founding year or a made-up testimonial on a page about
their own clinic stops reading, and the sale is over. Those are the first things
anybody checks.

**The call-to-action actually works.** In the UAE an enquiry arrives by phone or
WhatsApp, so a tel: link that will not dial is not a cosmetic flaw — it is the
whole page failing for the one visitor who most wanted to get in touch.
"""

from __future__ import annotations

import re

import pytest

from atlas_kernel.website.verticals import dental

REAL = {
    "name": "NOA Dental Clinic",
    "phone": "04 398 7075",
    "address": "Unit 109, Al Hanaa Centre Mall, Mankhool Road, Dubai",
    "area": "Mankhool",
}


@pytest.fixture
def page() -> str:
    return dental.render(**REAL)


class TestNothingIsInvented:
    def test_no_fabricated_credentials(self, page: str) -> None:
        """The claims a prospect would immediately know to be false."""
        for phrase in (
            "years of experience",
            "award-winning",
            "voted best",
            "founded in",
            "since 19",
            "since 20",
            "board certified",
            "our team of specialists",
        ):
            assert phrase not in page.lower(), f"invented claim: {phrase}"

    def test_no_invented_people(self, page: str) -> None:
        """A named dentist who does not work there is the fastest possible way
        to lose the room."""
        assert not re.search(r"\bDr\.?\s+[A-Z][a-z]+", page.replace(REAL["name"], ""))

    def test_no_testimonials_or_ratings(self, page: str) -> None:
        for phrase in ("testimonial", "★", "5 stars", "patients say", "reviews say"):
            assert phrase not in page.lower()

    def test_no_placeholder_text_reaches_a_prospect(self, page: str) -> None:
        for phrase in ("lorem", "example.com", "123 main", "your name here", "tbd", "xxx"):
            assert phrase not in page.lower()

    def test_absent_facts_are_omitted_not_faked(self) -> None:
        """A clinic whose listing has no address gets no address block — not an
        invented one."""
        sparse = dental.render(name="Some Clinic", phone="04 111 2222")
        assert "Address" not in sparse
        assert "Directions" not in sparse, "a map link with nothing to point at"

    def test_hours_are_never_guessed(self, page: str) -> None:
        """Guessing opening hours sends a patient to a locked door."""
        assert "Opening hours" not in page
        with_hours = dental.render(**REAL, hours=[("Sat-Thu", "9:00 - 21:00")])
        assert "Opening hours" in with_hours


class TestTheCallToActionWorks:
    def test_the_phone_number_dials(self, page: str) -> None:
        """Spaces in a tel: href silently fail to dial on some Android
        browsers."""
        assert 'href="tel:043987075"' in page
        assert 'href="tel:04 398 7075"' not in page

    def test_a_landline_gets_no_whatsapp_link(self, page: str) -> None:
        """This test previously asserted the opposite and was wrong. The fixture
        number is an 04 landline, and WhatsApp runs on mobiles — generating
        wa.me/043987075 put a dead button on the one channel UAE patients
        actually use, on seventeen of twenty demos."""
        assert "wa.me" not in page

    def test_a_mobile_number_does_get_one(self) -> None:
        page = dental.render(name="Mobile Clinic", phone="054 475 2767", address="Dubai")
        assert "https://wa.me/971544752767" in page

    def test_a_toll_free_number_gets_none(self) -> None:
        page = dental.render(name="Toll Free Clinic", phone="800 732757", address="Dubai")
        assert "wa.me" not in page
        assert 'href="tel:800732757"' in page, "it can still be phoned"

    def test_capability_is_reported_as_three_states(self) -> None:
        """Never a guess: a number we cannot classify is unverified, not absent."""
        assert dental.whatsapp_status("054 475 2767").startswith("CONFIRMED_PRESENT")
        assert dental.whatsapp_status("04 398 7075").startswith("CONFIRMED_ABSENT")
        assert dental.whatsapp_status("").startswith("NOT_VERIFIED")
        assert dental.whatsapp_status("+44 20 7946 0000").startswith("NOT_VERIFIED")

    def test_a_clinic_without_a_phone_gets_no_dead_buttons(self) -> None:
        """A 'Call now' that dials nothing is worse than no button."""
        page = dental.render(name="No Phone Clinic", address="Al Barsha, Dubai")
        assert "tel:" not in page
        assert "wa.me" not in page
        assert "Get in touch" in page, "it should still say how to proceed"

    def test_an_international_format_number_is_normalised_for_dialling(self) -> None:
        page = dental.render(name="C", phone="00971 4 398 7075")
        assert 'href="tel:+97143987075"' in page
        assert "wa.me" not in page, "still a landline, however it is written"


class TestItIsFindable:
    def test_structured_data_describes_a_dentist(self, page: str) -> None:
        """What puts a small clinic into a local search at all."""
        assert '"@type": "Dentist"' in page
        assert '"telephone"' in page
        assert '"areaServed": "Dubai"' in page

    def test_the_title_and_description_carry_the_area(self, page: str) -> None:
        assert "Mankhool" in page
        assert '<meta name="description"' in page

    def test_structured_data_cannot_break_out_of_its_script_block(self) -> None:
        """JSON encoding does not escape </script>."""
        page = dental.render(name="Evil</script><script>alert(1)</script> Clinic", phone="0412345")
        assert "</script><script>alert(1)" not in page

    def test_the_clinic_name_is_escaped_everywhere(self) -> None:
        page = dental.render(name='Smile & "Care" <Clinic>', phone="0412345")
        assert "<Clinic>" not in page
        assert "&lt;Clinic&gt;" in page


class TestItIsClientReady:
    def test_it_has_the_sections_a_paid_site_has(self, page: str) -> None:
        for marker in ("Our services", "Why patients choose us", "Visit us", "Book an appointment"):
            assert marker in page, marker

    def test_it_works_on_a_phone(self, page: str) -> None:
        assert "@media (max-width:760px)" in page
        assert 'name="viewport"' in page

    def test_it_makes_no_third_party_requests(self, page: str) -> None:
        """No fonts, no analytics, no CDN: it loads instantly on a Dubai mobile
        connection, survives the host's strict CSP, and gives a prospect's IT
        person nothing to object to."""
        external = re.findall(r'(?:src|href)="(https?://[^"]+)"', page)
        allowed = ("https://wa.me/", "https://www.google.com/maps")
        assert all(u.startswith(allowed) for u in external), external

    def test_icons_are_drawn_not_emoji(self, page: str) -> None:
        """Emoji render differently on every platform and read as placeholder."""
        assert "<svg" in page
        assert not re.search(r"[\U0001F300-\U0001FAFF]", page)

    def test_it_is_substantially_more_than_a_stub(self, page: str) -> None:
        """The placeholder this replaced was 800 bytes: one headline, one line
        and three bullets. Nobody pays for that."""
        assert len(page) > 8000


def test_each_language_page_is_canonical_for_itself() -> None:
    """The Arabic page must not declare itself a duplicate of the English one.

    A canonical pointing at the other language tells Google the page is a copy,
    and copies are dropped from the index — which would remove the Arabic page
    from precisely the searches it exists to win. hreflang is what expresses
    "these are translations"; canonical is not.
    """
    files = dental.render_site(
        name="NOA Dental Clinic",
        phone="0501234567",
        address="Mankhool Road, Dubai",
        area="Mankhool",
        base_url="https://sites.qevik.ai/demo-noa",
    )
    english = re.search(r'rel="canonical" href="([^"]*)"', files["index.html"]).group(1)
    arabic = re.search(r'rel="canonical" href="([^"]*)"', files["ar/index.html"]).group(1)

    assert english == "https://sites.qevik.ai/demo-noa/"
    assert arabic == "https://sites.qevik.ai/demo-noa/ar/"

    # The structured data agrees with the page it is on, rather than pointing
    # every translation at one URL.
    assert '"url": "https://sites.qevik.ai/demo-noa/ar/"' in files["ar/index.html"]

    # And they still declare each other as alternates, in both directions.
    for page in (files["index.html"], files["ar/index.html"]):
        assert 'hreflang="en" href="https://sites.qevik.ai/demo-noa/"' in page
        assert 'hreflang="ar" href="https://sites.qevik.ai/demo-noa/ar/"' in page


def test_the_arabic_headline_carries_no_latin_district() -> None:
    """Bidi reorders a Latin district out of an Arabic sentence onto its own line.

    The area names come from an English Google listing. Rendering one inside the
    Arabic headline reads as pasted-in, and inventing an Arabic spelling of a
    Dubai district would be the same fabrication this template refuses about
    doctors and insurers. The address block still carries the real location.
    """
    files = dental.render_site(
        name="NOA Dental Clinic",
        phone="0501234567",
        address="Mankhool Road, Dubai",
        area="Mankhool",
        base_url="https://sites.qevik.ai/demo-noa",
    )
    arabic_h1 = re.search(r'<h1[^>]*>([^<]*)</h1>', files["ar/index.html"]).group(1)
    assert "Mankhool" not in arabic_h1
    assert not re.search(r"[A-Za-z]", arabic_h1)

    # The English page is unaffected — it still names the district, which is the
    # local-SEO term the page is trying to rank for.
    english_h1 = re.search(r'<h1[^>]*>([^<]*)</h1>', files["index.html"]).group(1)
    assert "Mankhool" in english_h1

    # The location is not lost, only moved off the headline.
    assert "Mankhool" in files["ar/index.html"]


def test_book_is_only_said_when_a_real_provider_is_wired() -> None:
    """The placeholder form takes a request. It must not be labelled "Book".

    Every call to action pointing at `#request` reaches a form with no backend.
    Calling that "Book an appointment" promises a booking nothing can make, and
    the person who believes it is a patient, not a prospect. "Book" becomes
    truthful the moment a real provider URL is supplied, and only then.
    """
    placeholder = dental.render_site(
        name="Test Dental", phone="0501234567", address="A", area="Dubai",
        base_url="https://x/y",
    )
    for page in ("index.html", "ar/index.html"):
        html = placeholder[page]
        labels = re.findall(r'href="#request"[^>]*>([^<]*)<', html)
        assert labels, "the placeholder form should still be reachable"
        assert all("Book" not in label for label in labels), labels
        assert all("احجز" not in label for label in labels), labels

    wired = dental.render_site(
        name="Test Dental", phone="0501234567", address="A", area="Dubai",
        base_url="https://x/y", booking_url="https://provider.example/book",
    )
    external = re.findall(r'href="https://provider.example/book"[^>]*>([^<]*)<', wired["index.html"])
    assert external and all("Book" in label for label in external), external
