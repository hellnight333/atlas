"""The multi-industry renderer, held to the same rules as the dental one.

Broadening the product is where honesty guarantees usually get lost: the rules
were written for clinics, a restaurant template is added, and nobody re-checks
that a reservation form still refuses to claim it booked a table.

So these are the dental rules restated against `business.py`, plus the one that
only exists here — a wrong `schema.org` type tells Google the business is
something it is not, which is worse than declaring nothing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "infra"))

from samples import SAMPLES  # noqa: E402

from atlas_kernel.website.verticals.business import (  # noqa: E402
    Business,
    Group,
    Item,
    Text,
    render,
    render_site,
    whatsapp_number,
)


def minimal(**overrides) -> Business:
    base = {
        "name": "Test Business",
        "schema_type": "LocalBusiness",
        "tagline": Text("A tagline", "شعار"),
        "intro": Text("An introduction.", "مقدمة."),
        "phone": "050 102 9104",
        "address": "Somewhere, Dubai",
    }
    base.update(overrides)
    return Business(**base)


class TestWhatsAppIsOnlyOfferedWhereItWorks:
    """`wa.me` on a landline is a dead end the business gets blamed for."""

    @pytest.mark.parametrize("number", ["050 102 9104", "0521514300", "971582256900"])
    def test_a_mobile_gets_a_link(self, number: str) -> None:
        assert whatsapp_number(number)
        assert "wa.me/" in render(minimal(phone=number))

    @pytest.mark.parametrize("number", ["04 355 8808", "800 37569", "043987075"])
    def test_a_landline_or_toll_free_does_not(self, number: str) -> None:
        assert whatsapp_number(number) == ""
        assert "wa.me/" not in render(minimal(phone=number))


class TestNothingBooks:
    @pytest.mark.parametrize("slug", list(SAMPLES))
    def test_every_sample_offers_a_contact_path_that_delivers(self, slug: str) -> None:
        """The contract this replaced said the form announced it was *not*
        connected -- true until M1 wired the enquiry block, and a false
        statement the moment it did.

        What has not changed is the thing that mattered: the page must not let a
        visitor believe more happened than did. That is asserted here as
        delivery, and below as the promise not made.
        """
        biz, palette = SAMPLES[slug]
        files = render_site(biz, base_url=f"https://x/{slug}", **palette)
        for page in ("index.html", "ar/index.html"):
            html = files[page]
            assert "request-form" not in html, f"{slug} {page}: the dead form is back"
            assert "not connected" not in html, (
                f"{slug} {page}: the page says it cannot deliver, and it can")
            delivers = "mailto:" in html or "wa.me/" in html
            assert delivers or 'class="enquiry"' not in html, (
                f"{slug} {page}: an enquiry form with nowhere to send")

    @pytest.mark.parametrize("slug", list(SAMPLES))
    def test_every_sample_states_what_a_request_does_not_do(self, slug: str) -> None:
        """The safety half, now for every sample rather than the two below.

        A visitor who presses send has made a request. A page that lets them
        believe a table or a chair is held has cost them an evening.
        """
        biz, palette = SAMPLES[slug]
        html = render_site(biz, base_url=f"https://x/{slug}", **palette)["index.html"]
        assert "not a confirmed booking" in html.lower(), slug
        assert "only held once" in html.lower(), slug

    def test_the_restaurant_does_not_claim_to_hold_a_table(self) -> None:
        biz, palette = SAMPLES["sample-restaurant"]
        english = render_site(biz, base_url="https://x/y", **palette)["index.html"].lower()
        assert "booking system" not in english
        assert "only held once" in english, "the limit of a table request must be stated"

    def test_the_salon_does_not_claim_a_confirmed_appointment(self) -> None:
        biz, palette = SAMPLES["sample-salon"]
        english = render_site(biz, base_url="https://x/y", **palette)["index.html"].lower()
        assert "not a confirmed booking" in english


class TestSchemaTypes:
    """A wrong type is worse than none — it misfiles the business in local search."""

    def test_each_sample_declares_a_type_that_matches_what_it_is(self) -> None:
        expected = {
            "sample-restaurant": "Restaurant",
            "sample-cafe": "CafeOrCoffeeShop",
            "sample-detailing": "AutoWash",
            "sample-property": "RealEstateAgent",
            "sample-salon": "BeautySalon",
        }
        for slug, schema_type in expected.items():
            biz, _ = SAMPLES[slug]
            assert biz.schema_type == schema_type, slug

    def test_the_type_reaches_the_page(self) -> None:
        html = render(minimal(schema_type="Bakery"))
        assert '"@type": "Bakery"' in html


class TestBothLanguagesAreReal:
    @pytest.mark.parametrize("slug", list(SAMPLES))
    def test_the_arabic_page_is_rtl_and_actually_arabic(self, slug: str) -> None:
        biz, palette = SAMPLES[slug]
        arabic = render_site(biz, base_url=f"https://x/{slug}", **palette)["ar/index.html"]
        assert 'dir="rtl"' in arabic and 'lang="ar"' in arabic
        heading = re.search(r"<h1>([^<]*)</h1>", arabic).group(1)
        assert re.search(r"[؀-ۿ]", heading), f"{slug}: headline is not Arabic"

    @pytest.mark.parametrize("slug", list(SAMPLES))
    def test_each_language_is_canonical_for_itself(self, slug: str) -> None:
        biz, palette = SAMPLES[slug]
        files = render_site(biz, base_url=f"https://x/{slug}", **palette)
        assert f'rel="canonical" href="https://x/{slug}/"' in files["index.html"]
        assert f'rel="canonical" href="https://x/{slug}/ar/"' in files["ar/index.html"]

    def test_arabic_times_use_arabic_meridiem_markers(self) -> None:
        biz = minimal(hours=((Text("Monday", "الاثنين"), Text("9:00 AM – 5:00 PM", "9:00 AM – 5:00 PM")),))
        arabic = render(biz, lang="ar")
        assert "ص" in arabic and "م" in arabic
        # The digits themselves are untouched.
        assert "9:00" in arabic and "5:00" in arabic


class TestNothingIsInvented:
    def test_a_price_that_was_not_given_is_not_shown(self) -> None:
        biz = minimal(groups=(Group(Text("G", "ج"), (Item(Text("A", "أ"), Text("B", "ب")),)),))
        assert 'class="price"' not in render(biz)

    def test_sections_the_caller_omitted_do_not_appear(self) -> None:
        """An empty FAQ must produce no FAQ heading, not an empty one."""
        html = render(minimal())
        assert "Common questions" not in html
        assert "Why choose us" not in html

    @pytest.mark.parametrize("slug", list(SAMPLES))
    def test_every_sample_is_flagged_as_a_sample(self, slug: str) -> None:
        """These are ours. A visitor must not mistake one for a real business."""
        biz, palette = SAMPLES[slug]
        files = render_site(biz, base_url=f"https://x/{slug}", **palette)
        assert "Not a real business" in files["index.html"]
        assert "ليس نشاطاً تجارياً حقيقياً" in files["ar/index.html"]

    @pytest.mark.parametrize("slug", list(SAMPLES))
    def test_no_sample_invents_a_review_or_a_rating(self, slug: str) -> None:
        biz, palette = SAMPLES[slug]
        for html in render_site(biz, base_url=f"https://x/{slug}", **palette).values():
            body = html.lower()
            for invented in ("aggregaterating", "reviewcount", "★", "testimonial"):
                assert invented not in body, f"{slug}: {invented}"


def test_html_is_escaped_so_a_business_name_cannot_inject_markup() -> None:
    html = render(minimal(name='Bad <script>alert(1)</script> Co'))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
