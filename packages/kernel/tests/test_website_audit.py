"""Reading a clinic's homepage honestly.

Every sales claim traces back to this function, so the tests are mostly about
what it refuses to conclude.
"""

from __future__ import annotations

from atlas_kernel.opportunity.website_audit import Status, audit_html

MINIMAL = "<html><head><title>A Clinic</title></head><body><h1>Hi</h1></body></html>"


def _status(html: str, feature: str) -> Status:
    findings = audit_html(html, url="https://clinic.example", page_bytes=len(html))
    return next(f.status for f in findings if f.feature == feature)


class TestItFindsWhatIsThere:
    def test_a_tel_link(self) -> None:
        assert _status('<a href="tel:043987075">Call</a>', "click_to_call") is Status.PRESENT

    def test_a_whatsapp_link(self) -> None:
        assert (
            _status('<a href="https://wa.me/971501234567">Chat</a>', "whatsapp") is Status.PRESENT
        )

    def test_a_booking_link_by_its_text(self) -> None:
        assert _status('<a href="/x">Book an appointment</a>', "booking_link") is Status.PRESENT

    def test_a_booking_link_by_its_target(self) -> None:
        assert _status('<a href="/appointment">Go</a>', "booking_link") is Status.PRESENT

    def test_a_maps_embed(self) -> None:
        html = '<iframe src="https://www.google.com/maps/embed?pb=x"></iframe>'
        assert _status(html, "google_maps") is Status.PRESENT

    def test_a_contact_form(self) -> None:
        assert _status("<form><input name=a></form>", "contact_form") is Status.PRESENT

    def test_opening_hours_in_the_text(self) -> None:
        assert _status("<p>Sat - Thu 9:00 - 21:00</p>", "opening_hours") is Status.PRESENT

    def test_arabic_content(self) -> None:
        assert _status("<p>عيادة أسنان</p>", "arabic") is Status.PRESENT

    def test_an_arabic_language_route(self) -> None:
        assert _status('<a href="/ar/">AR</a>', "arabic") is Status.PRESENT


class TestItDoesNotOverclaim:
    def test_a_form_without_inputs_is_not_a_contact_form(self) -> None:
        assert _status("<form></form>", "contact_form") is Status.NOT_FOUND

    def test_structured_data_must_actually_describe_a_clinic(self) -> None:
        """An ld+json block for a breadcrumb is not a local-search signal."""
        html = '<script type="application/ld+json">{"@type":"BreadcrumbList"}</script>'
        assert _status(html, "structured_data") is Status.NOT_FOUND

    def test_dentist_schema_counts(self) -> None:
        html = '<script type="application/ld+json">{"@type":"Dentist"}</script>'
        assert _status(html, "structured_data") is Status.PRESENT

    def test_features_that_live_on_subpages_are_unverified_not_missing(self) -> None:
        """The property the whole pipeline rests on."""
        for feature in ("doctors_team", "insurance_info", "emergency_info", "social_proof"):
            assert _status(MINIMAL, feature) is Status.UNVERIFIED, feature

    def test_a_page_with_no_images_cannot_be_judged_on_alt_text(self) -> None:
        assert _status(MINIMAL, "image_alt_text") is Status.UNVERIFIED

    def test_mostly_missing_alt_text_is_a_confirmed_gap(self) -> None:
        html = "<img src=a><img src=b><img src=c alt='x'>"
        assert _status(html, "image_alt_text") is Status.NOT_FOUND

    def test_mostly_present_alt_text_passes(self) -> None:
        html = "<img src=a alt='a'><img src=b alt='b'><img src=c>"
        assert _status(html, "image_alt_text") is Status.PRESENT


class TestTechnicalChecks:
    def test_http_is_recorded_as_a_confirmed_gap(self) -> None:
        findings = audit_html(MINIMAL, url="http://clinic.example", page_bytes=100)
        assert next(f.status for f in findings if f.feature == "https") is Status.NOT_FOUND

    def test_https_passes(self) -> None:
        assert _status(MINIMAL, "https") is Status.PRESENT

    def test_a_missing_viewport_is_a_mobile_finding(self) -> None:
        assert _status(MINIMAL, "viewport_meta") is Status.NOT_FOUND

    def test_every_finding_carries_its_evidence(self) -> None:
        for finding in audit_html(MINIMAL, url="https://c.example", page_bytes=len(MINIMAL)):
            assert finding.evidence, finding.feature

    def test_only_a_confirmed_absence_counts_against_a_site(self) -> None:
        for finding in audit_html(MINIMAL, url="https://c.example", page_bytes=len(MINIMAL)):
            assert finding.counts_against is (finding.status is Status.NOT_FOUND)
