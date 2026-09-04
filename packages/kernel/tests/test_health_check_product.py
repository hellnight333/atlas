"""The digital product: a website health check a business owner can open.

What is at stake in each rule below is a real business's name on a document.
Qevik holds 396 audits and the person each one is about has never seen it, so
this artefact is sent to strangers — an unevidenced claim in it is not a bug,
it is an accusation nobody can check.
"""

from __future__ import annotations

import pytest

from atlas_kernel.execution.capabilities import EXECUTORS, REQUIRES_CUSTOMER_INPUT
from atlas_kernel.execution.capabilities.healthcheck import (
    Check,
    NothingObserved,
    Unevidenced,
    Verdict,
    build_health_check,
    render,
    validate,
)

#: Shaped exactly like a row from `website_audited` in production.
REAL = {
    "url": "https://example-clinic.test/",
    "observations": [
        {"feature": "click_to_call", "status": "not_found", "category": "conversion",
         "evidence": "no tel: link in the homepage HTML",
         "note": "A patient in pain phones. Without a tel: link they must copy "
                 "a number by hand."},
        {"feature": "whatsapp", "status": "not_found", "category": "contact",
         "evidence": "no wa.me or api.whatsapp.com link",
         "note": "In the UAE most clinic enquiries arrive on WhatsApp."},
        {"feature": "opening_hours", "status": "present", "category": "content",
         "evidence": "day/time pattern found in the homepage text",
         "note": "Hours are the most-checked fact on a clinic site."},
        {"feature": "page_speed", "status": "timeout", "category": "performance",
         "evidence": "", "note": "A slow page loses visitors on mobile data."},
    ],
}


def _build(research=None):
    return build_health_check(business_name="Example Clinic",
                              research=research if research is not None else REAL)


class TestWhatTheOwnerActuallyGets:
    def test_it_produces_one_page_they_can_open(self) -> None:
        files, provenance = _build()

        assert set(files) == {"index.html"}
        assert files["index.html"].startswith("<!doctype html>")
        assert provenance["checks"] == 4

    def test_every_finding_appears_with_the_evidence_behind_it(self) -> None:
        """The difference between an audit and a sales pitch. The recipient is
        entitled to check, and cannot if the page only asserts."""
        page = _build()[0]["index.html"]

        assert "no tel: link in the homepage HTML" in page
        assert "no wa.me or api.whatsapp.com link" in page

    def test_it_says_what_each_finding_costs_them(self) -> None:
        """From the current note table, not from the stored event — see
        `test_a_stored_note_from_another_vertical_is_not_replayed`."""
        page = _build()[0]["index.html"]

        assert "copy the number by hand" in page
        assert "WhatsApp" in page

    def test_a_stored_note_from_another_vertical_is_not_replayed(self) -> None:
        """396 stored audits carry notes written for dental clinics, 40 of them
        about retail businesses. Correcting the table fixed future audits and
        could not fix what was already recorded, so the consequence is looked
        up now rather than read out of the event."""
        page = build_health_check(business_name="Sony | Dubai Mall", research={
            "observations": [{
                "feature": "click_to_call", "status": "not_found",
                "category": "conversion",
                "evidence": "no tel: link in the homepage HTML",
                "note": "A patient in pain phones. Without a tel: link they "
                        "must copy a number by hand."}]})[0]["index.html"]

        assert "patient" not in page.lower()
        # The evidence is an observation about their site and is kept exactly.
        assert "no tel: link in the homepage HTML" in page

    def test_an_unrecognised_feature_gets_no_borrowed_consequence(self) -> None:
        """Falling back to the stored note would reintroduce the whole problem
        for exactly the features this build knows least about."""
        page = build_health_check(business_name="X", research={
            "observations": [{
                "feature": "some_new_check", "status": "not_found",
                "category": "seo", "evidence": "looked and did not find it",
                "note": "A patient in pain phones."}]})[0]["index.html"]

        assert "patient" not in page.lower()
        assert "looked and did not find it" in page

    def test_it_reports_what_is_already_working(self) -> None:
        """A page listing only faults reads as a pitch. It is also less useful:
        the owner cannot tell what they should not change."""
        page = _build()[0]["index.html"]

        assert "already working" in page
        assert "opening hours" in page

    def test_a_check_that_did_not_complete_is_not_drawn_as_a_fault(self) -> None:
        """`page_speed` timed out. Presenting that as "your site is slow" puts
        an invented finding about a real business in writing, in their name."""
        page = _build()[0]["index.html"]
        provenance = _build()[1]

        assert "Could not check" in page
        assert provenance["not_verified"] == 1
        assert provenance["confirmed_absent"] == 2
        # And the page says the distinction out loud, because a reader who does
        # not notice it reads three states as two.
        assert "not a fault we found" in page

    def test_the_three_states_are_drawn_three_ways(self) -> None:
        page = _build()[0]["index.html"]

        for tone in ('class="check good"', 'class="check missing"',
                     'class="check unknown"'):
            assert tone in page, tone

    def test_it_needs_no_network_to_render_its_own_findings(self) -> None:
        """Opened from a file, an attachment, or a phone on bad mobile data. A
        page that needs a CDN to show its findings fails exactly when it is
        being read."""
        page = _build()[0]["index.html"]

        for external in ("<script src", "<link rel=\"stylesheet\"", "https://fonts.",
                         "cdn.", "//unpkg", "@import"):
            assert external not in page, external

    def test_the_business_name_is_escaped(self) -> None:
        """It comes from a third-party listing and is rendered into HTML."""
        page = build_health_check(
            business_name='Bob\'s <script>alert(1)</script> Clinic',
            research=REAL)[0]["index.html"]

        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page

    def test_evidence_text_is_escaped_too(self) -> None:
        page = build_health_check(business_name="X", research={"observations": [
            {"feature": "f", "status": "not_found", "category": "contact",
             "evidence": "<img src=x onerror=alert(1)>"}]})[0]["index.html"]

        assert "<img src=x" not in page


class TestValidationRefusesAnUnusableArtefact:
    def test_a_confirmed_claim_with_no_evidence_is_refused(self) -> None:
        """This is the rule the product exists to keep. A finding nobody can
        check is an assertion about a business that Qevik cannot defend."""
        with pytest.raises(Unevidenced) as refused:
            validate((Check(feature="booking_link", category="booking",
                            verdict=Verdict.MISSING, evidence=""),))

        assert "booking_link" in str(refused.value)

    def test_an_unfinished_check_needs_no_evidence(self) -> None:
        """It claims nothing, so there is nothing to evidence. Requiring it
        would force the artefact to drop the honest third state."""
        validate((Check(feature="page_speed", category="performance",
                        verdict=Verdict.UNKNOWN, evidence=""),))

    def test_an_audit_that_observed_nothing_produces_no_product(self) -> None:
        """A page saying a business is fine because nothing was examined is
        worse than no page."""
        with pytest.raises(NothingObserved):
            _build({"observations": []})

    def test_the_executor_validates_before_it_returns(self) -> None:
        """A generated file nobody validated is not a product. Without this the
        rule above is advice."""
        with pytest.raises(Unevidenced):
            _build({"observations": [
                {"feature": "h1", "status": "not_found", "category": "seo"}]})

    def test_a_nameless_business_is_refused(self) -> None:
        with pytest.raises(NothingObserved):
            build_health_check(business_name="  ", research=REAL)

    def test_provenance_lists_every_claim_for_a_reviewer(self) -> None:
        """A person approving this should not have to open the HTML to see what
        it asserts about somebody."""
        claims = _build()[1]["claims"]

        assert len(claims) == 4
        assert {c["feature"] for c in claims} == {
            "click_to_call", "whatsapp", "opening_hours", "page_speed"}
        assert all("verdict" in c and "evidence" in c for c in claims)


class TestItFitsTheExecutionArchitecture:
    def test_it_is_registered_and_executable(self) -> None:
        assert EXECUTORS["offer-health-check"] is build_health_check

    def test_it_needs_nothing_from_the_customer(self) -> None:
        """The reason this product was chosen over a calculator or a booking
        tool: those need prices or a calendar, would sit in the map below, and
        could never execute through the roadmap."""
        assert "offer-health-check" not in REQUIRES_CUSTOMER_INPUT

    def test_it_accepts_the_calling_convention_exactly(self) -> None:
        """Two executors were once registered with an incompatible signature
        and failed after a customer had approved the work."""
        import inspect

        from atlas_kernel.execution.capabilities import CALLING_CONVENTION

        parameters = inspect.signature(build_health_check).parameters
        for name in CALLING_CONVENTION:
            assert name in parameters, name

    def test_it_has_an_agent_and_a_measurable_dimension(self) -> None:
        from atlas_kernel.fabric.agents import AGENTS
        from atlas_kernel.roadmap.service import OFFER_DIMENSION

        agent = next(a for a in AGENTS
                     if a.offer_id == "offer-health-check")
        assert "website-generator" in agent.tools
        assert "offer-health-check" in OFFER_DIMENSION


def test_an_unknown_status_is_never_silently_dropped() -> None:
    """Dropping it would turn "we could not tell" into "we did not look", and
    the count at the top of the page would then be wrong about how much was
    examined."""
    _, provenance = build_health_check(business_name="X", research={
        "observations": [
            {"feature": "a", "status": "not_found", "category": "seo",
             "evidence": "looked"},
            {"feature": "b", "status": "who knows", "category": "seo"},
        ]})

    assert provenance["checks"] == 2
    assert provenance["not_verified"] == 1


class TestItNeverSaysSomethingFalseAboutTheBusiness:
    """The artefact goes to the business it is about, over Qevik's name.

    It ran against 40 real retail businesses and told Sony at the Dubai Mall
    that "a patient in pain phones" and that emergency patients convert
    immediately. The audit's notes had been written for dental clinics and
    applied to everything.
    """

    def test_no_audit_note_assumes_a_dental_clinic(self) -> None:
        from atlas_kernel.opportunity.website_audit import FEATURE_NOTES

        assuming = {feature: note for feature, (_, note) in FEATURE_NOTES.items()
                    if any(word in note.lower()
                           for word in ("patient", "clinic", "dental", "dentist"))}

        assert not assuming, (
            "these notes describe a dental clinic and are shown to whatever "
            f"business was audited: {sorted(assuming)}")

    def test_every_category_the_auditor_emits_has_a_sentence(self) -> None:
        """Three did not, and rendered as raw slugs — "accessibility",
        "mobile", "multilingual" — at the bottom of a page sent to a business."""
        from atlas_kernel.execution.capabilities.healthcheck import CATEGORY_MEANING
        from atlas_kernel.opportunity.website_audit import FEATURE_NOTES

        emitted = {category.value for category, _ in FEATURE_NOTES.values()}
        missing = emitted - set(CATEGORY_MEANING)

        assert not missing, (
            f"the auditor emits categories this page cannot name: {sorted(missing)}")

    def test_every_category_is_also_ordered(self) -> None:
        """An unordered category sorts to the end regardless of importance."""
        from atlas_kernel.execution.capabilities.healthcheck import CATEGORY_ORDER
        from atlas_kernel.opportunity.website_audit import FEATURE_NOTES

        emitted = {category.value for category, _ in FEATURE_NOTES.values()}

        assert not emitted - set(CATEGORY_ORDER), sorted(emitted - set(CATEGORY_ORDER))

    def test_a_retail_business_is_not_told_about_patients(self) -> None:
        """End to end, through the real note table."""
        from atlas_kernel.opportunity.website_audit import FEATURE_NOTES

        research = {"observations": [
            {"feature": feature, "status": "not_found",
             "category": category.value, "evidence": "checked the homepage",
             "note": note}
            for feature, (category, note) in FEATURE_NOTES.items()]}

        page = build_health_check(business_name="Sony | Dubai Mall",
                                  research=research)[0]["index.html"]

        for word in ("patient", "clinic", "dental", "dentist"):
            assert word not in page.lower(), word


class TestItCanActuallyBeDelivered:
    """An executor nothing routes to is a capability the fabric cannot reach.

    Mission -> Recipe -> Agent -> Tool -> Worker, and every link checked
    against the declarations rather than assumed.
    """

    def test_a_recipe_delivers_it(self) -> None:
        from atlas_kernel.fabric import recipes

        recipe = recipes.get("deliver-health-check")

        assert recipe.delivers == "offer-health-check"
        assert recipe.agent_id == "health-check"
        assert recipe.tools == ("website-generator",)

    def test_the_recipe_names_the_offer_the_executor_is_keyed_on(self) -> None:
        """The step's command is how the tool runner finds the executor. A
        mismatch here fails at execution, after an approval."""
        from atlas_kernel.execution.capabilities import EXECUTORS
        from atlas_kernel.fabric import recipes

        step = recipes.get("deliver-health-check").steps[0]

        assert step.command[0] in EXECUTORS

    def test_an_approved_opportunity_maps_to_it(self) -> None:
        from atlas_kernel.mission.delivery import OFFER_RECIPES

        assert OFFER_RECIPES["offer-health-check"] == "deliver-health-check"

    def test_it_cannot_publish_or_contact_anybody(self) -> None:
        """The structural guarantee: the agent declares one tool and it is not
        a network tool, so a step naming http-fetch or shell is refused at
        import rather than discovered at three in the morning."""
        from atlas_kernel.fabric.tools import for_agent
        from atlas_kernel.fabric.agents import AGENTS

        agent = next(a for a in AGENTS if a.id == "health-check")
        tools = {t.id: t for t in for_agent(agent)}

        assert set(tools) == {"website-generator"}
        assert not tools["website-generator"].network

    def test_a_worker_role_serves_it(self) -> None:
        """A recipe whose agent no worker serves produces missions nothing can
        claim — approved, queued, and never run."""
        import sys
        from pathlib import Path as _Path

        root = str(_Path(__file__).resolve().parents[3] / "infra")
        if root not in sys.path:
            sys.path.insert(0, root)
        import mission_worker

        assert mission_worker._serves("healthcheck") == "health-check"
        assert "healthcheck" in mission_worker.AGENT_CHOICES
        assert mission_worker.PLACEHOLDERS["healthcheck"] == "deliver-health-check"

    def test_the_unit_file_matches_the_role(self) -> None:
        """A unit naming a role the worker does not accept fails at start-up,
        on the host, after a deploy reported success."""
        import sys
        from pathlib import Path as _Path

        infra = _Path(__file__).resolve().parents[3] / "infra"
        unit = (infra / "qevik-worker-healthcheck.service").read_text()

        if str(infra) not in sys.path:
            sys.path.insert(0, str(infra))
        import mission_worker

        assert "--agent healthcheck" in unit
        assert "--name worker-healthcheck" in unit
        role = unit.split("--agent ")[1].split()[0]
        assert role in mission_worker.AGENT_CHOICES

    def test_the_deploy_restarts_it(self) -> None:
        """A worker the deploy does not restart runs yesterday's code, which is
        the failure the fingerprint check exists to catch."""
        from pathlib import Path as _Path

        root = _Path(__file__).resolve().parents[3]
        script = (root / "infra" / "deploy_control.sh").read_text()

        # Derived. This named one unit and the deploy named five in a variable;
        # neither noticed when a sixth worker was added. The deploy now builds
        # its list from the unit files, so the check is that it still does.
        assert "ls qevik-worker*.service" in script, (
            "the deploy writes its worker list out again, so the next worker "
            "added will run stale code after every deploy")
        assert (root / "infra" / "qevik-worker-healthcheck.service").is_file(), (
            "there is no health-check worker unit for the deploy to pick up")


class TestTheResearchAHealthCheckIsGiven:
    """The toolrunner builds a synthetic research shape for the capability that
    *fixes* defects: feature names and statuses, no evidence. A health check
    built from that refused every real business — correctly — for asserting
    findings with nothing behind them.

    A capability that reports observations needs the observations.
    """

    def test_a_report_gets_the_audit_and_a_build_gets_the_summary(self) -> None:
        """Structural, because the two shapes are indistinguishable at runtime
        until the validator refuses one of them in production."""
        import inspect

        from atlas_kernel.mission import toolrunner

        source = inspect.getsource(toolrunner)

        assert 'self._recipe.delivers == "offer-health-check"' in source
        assert "latest_audit(business.id)" in source

    def test_an_audit_with_no_observations_refuses_rather_than_reports(
            self) -> None:
        """A health check built from nothing tells a business their site is
        fine because nobody looked."""
        from atlas_kernel.execution.capabilities.healthcheck import NothingObserved

        try:
            build_health_check(business_name="X", research={"observations": []})
        except NothingObserved as refused:
            assert "nothing to report" in str(refused)
        else:
            raise AssertionError("an empty audit produced a health check")

    def test_the_synthetic_shape_would_still_be_refused(self) -> None:
        """The exact research the fix-building path builds. Kept as a test so
        that if the two paths are ever merged, this fails rather than a real
        business receiving unevidenced claims."""
        from atlas_kernel.execution.capabilities.healthcheck import Unevidenced

        synthetic = {"observations": [
            {"feature": "website", "status": "present"},
            {"feature": "page_title", "status": "not_found"},
            {"feature": "meta_description", "status": "not_found"},
        ]}

        try:
            build_health_check(business_name="Real Business", research=synthetic)
        except Unevidenced as refused:
            assert "page_title" in str(refused)
        else:
            raise AssertionError(
                "unevidenced claims about a real business were not refused")


def test_it_publishes_through_the_existing_mechanism() -> None:
    """Publishing is putting a directory of files at an address; what the files
    say is the artefact's business, not the publisher's. A health-check-specific
    hosting path would be a second thing to keep in step."""
    from atlas_kernel.mission.publication import OFFER_RECIPES

    assert OFFER_RECIPES["offer-health-check"] == "publish-website"
    assert OFFER_RECIPES["offer-website"] == "publish-website", (
        "the website offer must still use the recipe this one now shares")
