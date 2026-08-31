"""How much of the discovered population Qevik can see, and whose fault the rest is.

A business Qevik cannot fetch produces no observations, so no findings, so no
opportunity, so no artefact and no outreach. It leaves the funnel without
appearing anywhere as a loss.

Measured in production on 2026-08-31: 43 of 352 audited businesses were marked
as having a dead website by a defect that was ours, and businesses whose latest
audit says unreachable carry a signal 6.6% of the time against 22.4% for the
rest.
"""

from __future__ import annotations

from atlas_kernel.opportunity.coverage import Coverage, measure, ours


def _audit(**detail) -> dict:
    return {"detail": detail}


class TestWhoseFailureItWas:
    def test_a_site_that_answered_is_counted_as_seen(self) -> None:
        found = measure(latest_audits=[
            _audit(reachable=True, observations=[{"feature": "h1"}])],
            with_a_website=1)

        assert found.answered == 1
        assert found.we_failed == 0 and found.did_not_answer == 0

    def test_our_own_failure_is_not_counted_against_the_business(self) -> None:
        """The number this whole module exists for."""
        found = measure(latest_audits=[
            _audit(reachable=None, observations=[],
                   check_failed_because="our browser navigated elsewhere")],
            with_a_website=1)

        assert found.we_failed == 1
        assert found.did_not_answer == 0, (
            "a check we did not complete is not a finding about their site")

    def test_a_site_that_genuinely_did_not_answer_is_theirs(self) -> None:
        found = measure(latest_audits=[
            _audit(reachable=False, observations=[],
                   error="net::ERR_NAME_NOT_RESOLVED")],
            with_a_website=1)

        assert found.did_not_answer == 1
        assert found.we_failed == 0

    def test_history_written_before_the_field_existed_still_reads_correctly(
            self) -> None:
        """43 production rows carry only the error text. Counting them against
        the businesses would keep the false claim alive in the report."""
        found = measure(latest_audits=[
            _audit(reachable=False, observations=[],
                   error='Navigation to "x" is interrupted by another '
                         'navigation to "y"')],
            with_a_website=1)

        assert found.we_failed == 1
        assert found.did_not_answer == 0

    def test_the_older_audit_format_is_not_read_as_a_failure(self) -> None:
        """60 production rows from an earlier producer never wrote `reachable`
        at all. They carry twenty observations and are fine."""
        found = measure(latest_audits=[
            _audit(observations=[{"feature": "h1"}] * 20, http_status=200)],
            with_a_website=1)

        assert found.answered == 1
        assert found.we_failed == 0 and found.did_not_answer == 0

    def test_nothing_at_all_is_theirs_rather_than_ours(self) -> None:
        """Conservative in the same direction as the classifier: claiming a
        failure was ours without evidence would hide a real site problem."""
        found = measure(latest_audits=[_audit(reachable=None, observations=[])],
                        with_a_website=1)

        assert found.did_not_answer == 1
        assert found.we_failed == 0


class TestTheQueue:
    def test_a_business_never_audited_is_a_queue_position_not_a_loss(self) -> None:
        found = measure(latest_audits=[_audit(reachable=True, observations=[{}])],
                        with_a_website=10)

        assert found.never_audited == 9
        assert found.did_not_answer == 0

    def test_more_audits_than_websites_never_reports_a_negative_queue(self) -> None:
        """Reads as a bug in the reader rather than in the data."""
        found = measure(
            latest_audits=[_audit(reachable=True, observations=[{}])] * 5,
            with_a_website=2)

        assert found.never_audited == 0

    def test_the_latest_audit_is_the_one_that_counts(self) -> None:
        """A business audited badly on Monday and well on Tuesday is visible.
        The repository passes one row per business; this asserts the shape the
        reader depends on."""
        found = measure(latest_audits=[
            _audit(reachable=True, observations=[{}]),
            _audit(reachable=False, error="net::ERR_CONNECTION_REFUSED"),
        ], with_a_website=2)

        assert found.answered == 1 and found.did_not_answer == 1


class TestWhatTheOperatorIsTold:
    def test_the_number_that_should_reach_zero_is_named(self) -> None:
        found = measure(latest_audits=[
            _audit(reachable=None, check_failed_because="ours")],
            with_a_website=1)

        assert found.blocked_by_us == 1
        assert "should fall to zero" in found.summary()["note"]

    def test_it_says_what_a_failure_to_fetch_costs(self) -> None:
        note = Coverage(0, 0, 0, 0, 0).summary()["note"]

        assert "no evidence" in note
        assert "without appearing as a loss" in note

    def test_ours_recognises_both_the_field_and_the_legacy_error(self) -> None:
        assert ours({"check_failed_because": "our browser closed the page"})
        assert ours({"error": "is interrupted by another navigation to"})
        assert not ours({"error": "net::ERR_CERT_DATE_INVALID"})
        assert not ours({})


def test_it_re_audits_nothing() -> None:
    """Structural. The nightly verification already revisits these, and
    duplicating it to produce a number would spend somebody else's bandwidth to
    make a report look complete."""
    import ast
    import inspect

    from atlas_kernel.opportunity import coverage

    tree = ast.parse(inspect.getsource(coverage))
    imported = {alias.name.split(".")[0]
                for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {(node.module or "").split(".")[0]
                 for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not imported & {"httpx", "requests", "playwright", "socket",
                           "subprocess"}, imported


class TestTheDiscoveryFeedExplainsItsOwnEmptiness:
    """`recent_discoveries` excludes KNOWN, which is right — a list of things
    Qevik already had is not a discovery feed. But an empty feed then reads as
    "the scan ran and found nothing", and in production it means something else:
    352 of 412 businesses arrived through a path that records no sighting, and
    every sighting that does exist is KNOWN.
    """

    def test_the_repository_reports_how_many_were_never_sighted(self) -> None:
        import inspect

        from atlas_kernel.opportunity.repository import OpportunityRepository

        source = inspect.getsource(OpportunityRepository.sighting_coverage)

        assert "without_a_sighting" in source
        assert "atlas_sightings" in source
        # It counts; it must not create a sighting to make the number look good.
        assert "INSERT" not in source.upper()

    def test_the_route_carries_it(self) -> None:
        import inspect

        from atlas_kernel.opportunity import api

        source = inspect.getsource(api.build_router)

        assert "sighting_coverage()" in source
        assert '"coverage": coverage' in source

    def test_a_failure_to_read_it_does_not_take_down_the_feed(self) -> None:
        """The discoveries are the point of the route; the explanation is not
        worth failing them for."""
        import inspect

        from atlas_kernel.opportunity import api

        source = inspect.getsource(api.build_router)
        after = source[source.index("sighting_coverage()"):][:200]

        assert "except Exception" in after
        assert "coverage = {}" in after

    def test_the_console_says_it_rather_than_implying_a_clean_scan(self) -> None:
        from pathlib import Path

        console = (Path(__file__).resolve().parents[3]
                   / "apps" / "control" / "src" / "index.html").read_text()

        assert "have no sighting" in console
        assert "not evidence that nothing was found" in console


class TestWhoCanActuallyBeWrittenTo:
    """412 businesses and not one email address. Completing DNS and SMTP would
    enable email to nobody, and nothing else in the system says so: outreach
    reports `NO_SENDING_IDENTITY`, which reads as "the sender is missing"
    rather than "there is no recipient either"."""

    def test_a_population_with_no_email_is_not_addressable(self) -> None:
        from atlas_kernel.opportunity.coverage import reachable

        found = reachable(businesses=412, with_email=0, with_phone=349,
                          with_neither=63)

        assert found.email_is_addressable is False
        assert found.by_phone == 349, "the other channel is counted separately"

    def test_one_email_makes_it_addressable(self) -> None:
        """The negative control. A measure that always said 'no' would pass the
        test above and be useless."""
        from atlas_kernel.opportunity.coverage import reachable

        assert reachable(businesses=1, with_email=1, with_phone=0,
                         with_neither=0).email_is_addressable is True

    def test_the_channels_are_not_added_together(self) -> None:
        """Only one of them is automated. A single 'reachable' number would
        report the pipeline as ready to send when every recipient is a phone
        and WhatsApp is manual by standing instruction."""
        from atlas_kernel.opportunity.coverage import reachable

        summary = reachable(businesses=10, with_email=0, with_phone=8,
                            with_neither=2).summary()

        assert summary["by_email"] == 0 and summary["by_phone"] == 8
        assert "reachable" not in summary, "no combined figure"

    def test_the_dns_action_says_what_it_does_not_unblock(self) -> None:
        from atlas_kernel.controlplane.actions import sending_identity_actions
        from atlas_kernel.outreach.deliverability import Record, State

        measured = type("M", (), {
            "unreadable": False, "missing": ("MX",), "domain": "qevik.ai",
            "records": (Record(name="MX", matters_because="replies bounce" * 4,
                               state=State.ABSENT),)})()

        blocked = sending_identity_actions(measured, tenant="t",
                                           addressable=False)[0]
        fine = sending_identity_actions(measured, tenant="t",
                                        addressable=True)[0]

        assert "enables email to nobody" in blocked.reason
        assert "enables email to nobody" not in fine.reason

    def test_an_unknown_addressability_makes_no_claim(self) -> None:
        """The read can fail. Saying nothing beats saying the wrong thing to
        somebody about to spend an afternoon on DNS."""
        from atlas_kernel.controlplane.actions import sending_identity_actions
        from atlas_kernel.outreach.deliverability import Record, State

        measured = type("M", (), {
            "unreadable": False, "missing": ("MX",), "domain": "qevik.ai",
            "records": (Record(name="MX", matters_because="replies bounce" * 4,
                               state=State.ABSENT),)})()

        action = sending_identity_actions(measured, tenant="t",
                                          addressable=None)[0]

        assert "enables email to nobody" not in action.reason
