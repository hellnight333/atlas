"""Phase B: content, theme and generation (M015).

Three properties, in order of how much they matter.

**No fabricated business facts.** Publishing *as* a business is worse than making
a claim about one: an invented opening time is wrong in the customer's own voice,
on their own domain, and they carry the consequences. Facts carry a source, and
absent facts are absent from the page rather than replaced with filler.

**Deterministic rendering.** Same content in, same bytes out — which is what
makes rebuild-from-Business-memory a fingerprint comparison instead of a person
looking at two pages.

**Atlas's own detector passes it.** The theme has to earn what the gate checks,
so the detector is run against real generated output here rather than only at
deploy time.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_kernel.opportunity.detectors.website import WebsiteDetector
from atlas_kernel.opportunity.models import Business
from atlas_kernel.website.content import (
    ContactDetails,
    Fact,
    FactSource,
    OpeningHours,
    Prose,
    Service,
    SiteContent,
)
from atlas_kernel.website.generation import generate, get_theme, seed_content
from atlas_kernel.website.themes import clean

OPERATOR = FactSource.OPERATOR
CUSTOMER = FactSource.CUSTOMER


def _fact(value: str, source: FactSource = CUSTOMER) -> Fact:
    return Fact(value=value, source=source, note="supplied by the customer")


def _full() -> SiteContent:
    """What a properly-briefed customer supplies."""
    return SiteContent(
        business_name=_fact("Teqtronix"),
        tagline=_fact("Electronics trading and distribution across the UAE"),
        about=Prose(
            text=(
                "Teqtronix has supplied consumer electronics to retailers and "
                "corporate buyers across the United Arab Emirates since 2016. We "
                "hold stock locally in Dubai and deliver across the Emirates, and "
                "we handle warranty and returns directly rather than sending "
                "customers back to the manufacturer."
            ),
            written_by="operator",
        ),
        services=[
            Service(
                name=_fact("Wholesale distribution"),
                description=Prose(text="Bulk supply to retailers across the Emirates."),
            ),
            Service(name=_fact("Corporate procurement")),
            Service(
                name=_fact("Warranty and returns"),
                description=Prose(text="Handled in Dubai, without a manufacturer round trip."),
            ),
        ],
        hours=OpeningHours(
            days={
                "Monday": _fact("9:00 – 18:00"),
                "Tuesday": _fact("9:00 – 18:00"),
                "Saturday": _fact("10:00 – 14:00"),
            }
        ),
        contact=ContactDetails(
            phone=_fact("+971 4 123 4567"),
            email=_fact("hello@teqtronix.ae"),
            address=_fact("Warehouse 12, Al Quoz Industrial 3, Dubai"),
        ),
        location=_fact("Dubai"),
        extras={"Founded": _fact("2016"), "Trade licence": _fact("DED-000000")},
    )


def _bare() -> SiteContent:
    """A business that supplied almost nothing."""
    return SiteContent(business_name=_fact("Nameless Trading"))


def _render(content: SiteContent) -> str:
    return generate(content)[0]["index.html"]


class TestNoFabricatedFacts:
    def test_there_is_no_source_meaning_a_model_wrote_it(self) -> None:
        """The absence is the point: there is nothing to select when the honest
        answer is that Atlas made it up."""
        assert "generated" not in {source.value for source in FactSource}
        assert "ai" not in {source.value for source in FactSource}

    def test_a_missing_phone_number_leaves_no_trace_on_the_page(self) -> None:
        """The tempting failure is not inventing an address — it is padding a
        thin page with confident copy that asserts nothing anyone supplied."""
        page = _render(_bare())
        for tell in ("Call us", "Contact us today", "Coming soon", "Lorem", "TBD", "XXX"):
            assert tell.lower() not in page.lower(), f"placeholder copy on the page: {tell}"

    def test_sections_with_no_facts_do_not_appear(self) -> None:
        page = _render(_bare())
        assert "Opening hours" not in page
        assert "What we do" not in page
        assert "About" not in page

    def test_supplied_sections_do_appear(self) -> None:
        page = _render(_full())
        for heading in ("About", "What we do", "Opening hours", "Contact"):
            assert heading in page

    def test_only_the_days_supplied_are_published(self) -> None:
        """Guessing the weekend is the exact shape of the harm: a customer
        drives across town on a Sunday."""
        page = _render(_full())
        assert "Monday" in page and "Saturday" in page
        assert "Sunday" not in page
        assert "Closed" not in page, "a day nobody supplied was rendered as closed"

    def test_a_fact_must_say_something(self) -> None:
        with pytest.raises(ValueError, match="must say something"):
            Fact(value="   ", source=OPERATOR)

    def test_a_fact_cannot_be_edited_after_its_source_is_recorded(self) -> None:
        fact = _fact("+971 4 123 4567")
        with pytest.raises(ValueError):
            fact.value = "+971 4 000 0000"  # type: ignore[misc]

    def test_every_fact_is_attributable(self) -> None:
        """A wrong fact should lead back to whoever supplied it rather than
        dissolving into the output."""
        content = _full()
        assert content.facts
        assert all(fact.source in FactSource for fact in content.facts)
        assert all(fact.note for fact in content.facts)

    def test_prose_and_facts_are_different_types(self) -> None:
        """So the two can never be confused at a call site — a paragraph cannot
        become the opening hours by being written confidently."""
        with pytest.raises(ValueError):
            Service(name=Prose(text="Wholesale"))  # type: ignore[arg-type]

    def test_the_meta_description_is_built_from_supplied_content_only(self) -> None:
        """It is the one place search engines quote verbatim, so an unsourced
        claim here travels furthest."""
        page = _render(_bare())
        assert 'content="Nameless Trading"' in page

    def test_structured_data_contains_no_invented_fields(self) -> None:
        import json
        import re

        page = _render(_bare())
        block = re.search(r'application/ld\+json">(.*?)</script>', page, re.S)
        assert block is not None
        payload = json.loads(block.group(1))
        assert payload["name"] == "Nameless Trading"
        for invented in ("telephone", "email", "address", "openingHours"):
            assert invented not in payload


class TestSeedingFromWhatAtlasKnows:
    def test_recorded_business_facts_become_sourced_content(self) -> None:
        business = Business(
            name="Teqtronix",
            geography="United Arab Emirates",
            phone="+97141234567",
            email="hello@teqtronix.ae",
        )
        content = seed_content(business)
        assert content.business_name.value == "Teqtronix"
        assert content.contact.phone is not None
        assert all(fact.source is FactSource.BUSINESS_RECORD for fact in content.facts)
        assert all(business.id in fact.note for fact in content.facts)

    def test_nothing_absent_from_the_record_is_invented(self) -> None:
        content = seed_content(Business(name="Sparse Co"))
        assert content.contact.is_empty
        assert content.location is None
        assert content.hours.is_empty
        assert content.services == []

    def test_a_domain_does_not_become_an_email_address(self) -> None:
        """A plausible inference is still an invention."""
        content = seed_content(Business(name="Teqtronix", website="https://teqtronix.ae"))
        assert content.contact.email is None


class TestDeterminism:
    def test_the_same_content_renders_to_the_same_bytes(self) -> None:
        assert _render(_full()) == _render(_full())

    def test_nothing_records_when_it_was_built(self) -> None:
        page = _render(_full())
        for tell in ("generated on", "built at", "202", "timestamp"):
            if tell == "202":
                # "2016" is real content; a build year would appear in a footer.
                assert "<footer>" in page and "2026" not in page
                continue
            assert tell.lower() not in page.lower()

    def test_extras_render_in_a_stable_order(self) -> None:
        first = SiteContent(
            business_name=_fact("X"),
            extras={"Founded": _fact("2016"), "Licence": _fact("A"), "VAT": _fact("B")},
        )
        second = SiteContent(
            business_name=_fact("X"),
            extras={"VAT": _fact("B"), "Founded": _fact("2016"), "Licence": _fact("A")},
        )
        assert _render(first) == _render(second)

    def test_days_render_in_week_order_not_dictionary_order(self) -> None:
        content = SiteContent(
            business_name=_fact("X"),
            hours=OpeningHours(
                days={"Wednesday": _fact("9-5"), "Monday": _fact("9-5"), "Friday": _fact("9-5")}
            ),
        )
        page = _render(content)
        assert page.index("Monday") < page.index("Wednesday") < page.index("Friday")

    def test_an_unexpected_day_is_rendered_rather_than_dropped(self) -> None:
        content = SiteContent(
            business_name=_fact("X"),
            hours=OpeningHours(days={"Public holidays": _fact("Closed")}),
        )
        assert "Public holidays" in _render(content)

    def test_provenance_records_what_produced_the_artifact(self) -> None:
        _, provenance = generate(_full())
        assert provenance["theme"] == "clean-v1"
        assert provenance["facts"] == len(_full().facts)
        assert provenance["sections"]["services"] == 3


class TestEscaping:
    def test_content_cannot_inject_markup(self) -> None:
        """Content arrives from operators, customers and models. All three can
        contain an ampersand; none should be able to contain a script tag."""
        content = SiteContent(
            business_name=_fact("<script>alert(1)</script>"),
            tagline=_fact('Ben & Jerry"s "quoted"'),
        )
        page = _render(content)
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page
        assert "&amp;" in page

    def test_structured_data_survives_quotes(self) -> None:
        content = SiteContent(business_name=_fact('Ben & Jerry"s'))
        page = _render(content)
        assert "application/ld+json" in page

    def test_a_business_name_cannot_close_the_json_ld_block(self) -> None:
        """A real hole this test found, not a hypothetical one.

        JSON escaping does not escape ``</script>``. A business name containing
        one closed the structured-data block and everything after it became
        markup — cross-site scripting on the customer's own domain, published by
        Atlas, in their name. ``html.escape`` is not the fix: script contents are
        not parsed as HTML and would arrive as a literal ``&lt;``.
        """
        hostile = "</script><script>alert(document.domain)</script>"
        page = _render(SiteContent(business_name=_fact(hostile)))
        assert "</script><script>" not in page
        assert "\\u003c" in page or "\\u003C" in page

    def test_the_escaped_structured_data_is_still_valid_json(self) -> None:
        """Escaping that broke the payload would trade one defect for another —
        search engines would silently ignore it, which is the feature being sold."""
        import json
        import re

        page = _render(SiteContent(business_name=_fact("A & B <inc>")))
        block = re.search(r'application/ld\+json">(.*?)</script>', page, re.S)
        assert block is not None
        payload = json.loads(block.group(1))
        assert payload["name"] == "A & B <inc>"


class TestAtlasPassesItsOwnDetector:
    """The theme earns what the gate checks."""

    def _findings(self, content: SiteContent):
        page = _render(content)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, html=page)

        from atlas_kernel.website.gate import GATE_PROFILE

        detector = WebsiteDetector(
            client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
        )
        return detector.inspect(
            Business(name="under test", website="https://generated.test"), GATE_PROFILE
        )

    def test_a_properly_briefed_site_has_no_defects_at_all(self) -> None:
        findings = self._findings(_full())
        assert findings == [], [f"{f.kind.value}: {f.statement}" for f in findings]

    def test_a_bare_site_is_correctly_judged_too_thin_to_publish(self) -> None:
        """Not a bug in the theme — a real constraint, and worth stating.

        A page carrying one fact will not rank, and Atlas refuses to deploy it
        rather than padding it with copy nobody supplied. The remedy is to get
        more content from the customer, which is a conversation rather than a
        code change.
        """
        kinds = {finding.kind.value for finding in self._findings(_bare())}
        assert "thin_content" in kinds
        assert "missing_title" not in kinds
        assert "not_mobile_friendly" not in kinds
        assert "no_structured_data" not in kinds


class TestThemes:
    def test_one_theme_family_is_registered(self) -> None:
        assert get_theme().name == "clean-v1"
        assert get_theme(clean.NAME) is get_theme()

    def test_an_unknown_theme_says_which_exist(self) -> None:
        with pytest.raises(KeyError, match="known:"):
            get_theme("does-not-exist")

    def test_the_theme_produces_a_loadable_artifact(self) -> None:
        files, _ = generate(_full())
        assert "index.html" in files
        assert files["index.html"].startswith("<!doctype html>")

    def test_the_page_needs_no_second_request_to_render(self) -> None:
        """ "Slow homepage" is a finding on the proposal. Atlas cannot sell a
        speed fix and ship a render-blocking request it did not need."""
        page = _render(_full())
        assert "<style>" in page
        assert "<link" not in page
