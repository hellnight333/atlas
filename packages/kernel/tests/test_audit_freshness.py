"""The nightly pass refreshes the observations, not only the defects.

`website_audited` last ran on 2026-08-19. Everything that reads observations —
the health check most of all — was reading a twelve-day-old record while the
findings beside it refreshed every night, so one commercial decision was being
made from two vintages of evidence.

Nothing had stopped: **nothing had ever started.** The only producers were
`infra/audit_discovered.py` (336 events, one day, a Playwright script) and
`infra/import_audits.py` reading a JSON file (60 more). Neither is in
`RECURRENCES` and neither has a timer. The nightly recurrence ran
`verify-recorded-websites`, which calls `verification.audit_pass` — and that
returns `Finding`s, which are absences only.

So the tests here are mostly about two things:

* that the producer now has a path something actually calls, checked
  structurally rather than by trusting a comment; and
* that a fresh reading never *invents* an absence. A truncated body, an error
  page, a refusal and a non-HTML document are each a way to report a business
  as lacking something it has, and each has its own test.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from atlas_kernel import db
from atlas_kernel.db import SessionLocal
from atlas_kernel.fabric import recipes
from atlas_kernel.mission import recurrence
from atlas_kernel.mission.toolrunner import ToolAgent
from atlas_kernel.opportunity.crawler import BODY_KEPT
from atlas_kernel.opportunity.models import Business, Evidence, EvidenceKind
from atlas_kernel.opportunity.repository import OpportunityRepository
from atlas_kernel.opportunity.website_audit import audit_html

TENANT = "tenant-audit-freshness"

#: A homepage with a phone link and a form, and no viewport or booking path.
#: Real enough for `audit_html` to produce all three states.
PAGE = """<!doctype html><html><head><title>Al Waha Dental</title>
<meta name="description" content="A dental clinic in Dubai."></head>
<body><h1>Al Waha Dental</h1>
<a href="tel:+971501234567">Call us</a>
<form><input name="name"><textarea name="message"></textarea></form>
<p>We have been caring for families in Jumeirah since 2004, and our surgery
offers general dentistry, hygiene appointments and emergency care.</p>
</body></html>"""


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


@pytest.fixture
def repo() -> OpportunityRepository:
    return OpportunityRepository()


def _evidence(body: str, *, url: str, status: int = 200, truncated: bool = False,
              error: str = "", content_type: str = "text/html") -> Evidence:
    return Evidence(
        kind=EvidenceKind.HTML_CONTENT, source=url,
        observed={"status": status, "content_type": content_type,
                  "bytes": len(body), "elapsed_ms": 240, "redirect_chain": [],
                  "error": error, "body": body, "body_truncated": truncated,
                  "url": url},
        summary=f"HTTP {status}", detector="website")


def _runner(repo: OpportunityRepository, business: Business,
            evidence: Evidence) -> ToolAgent:
    """An agent holding exactly what a real verification pass holds."""
    agent = ToolAgent(recipes.get("verify-recorded-websites"),
                      repository=repo, tenant=TENANT)
    agent._targets = {business.website: business}
    return agent


def _run_audit(repo, business, evidence) -> tuple[int, int]:
    runner = _runner(repo, business, evidence)
    return runner._record_audit({business.id: business}, {business.id: evidence})


def _business(repo: OpportunityRepository) -> Business:
    return repo.save_business(Business(
        name="Al Waha Dental", geography="United Arab Emirates",
        website="https://alwaha.test", sources=["seed"]))


def _clean(business_id: str) -> None:
    with SessionLocal() as session:
        for table, column in (("atlas_business_events", "business_id"),
                              ("atlas_findings", "business_id"),
                              ("atlas_businesses", "id")):
            session.execute(text(f"DELETE FROM {table} WHERE {column} = :b"),
                            {"b": business_id})
        session.commit()


# ------------------------------------------------- the path exists at all


def test_the_observation_producer_is_reached_from_the_scheduled_recipe():
    """Structural, and the whole point of the slice.

    Parsed rather than grepped, so this cannot pass on the strength of its own
    prose — and asserted through the recurrence, so a recipe that stops being
    scheduled fails here rather than silently going quiet for twelve days.
    """
    scheduled = {r.recipe for r in recurrence.declared()}
    auditing = {r.id for r in recipes.all_recipes() if r.audit}
    assert auditing & scheduled, (
        "no recipe that audits is on any schedule, so nothing refreshes what "
        f"Qevik has observed. Auditing: {sorted(auditing)}; "
        f"scheduled: {sorted(scheduled)}")

    source = Path("packages/kernel/atlas_kernel/mission/toolrunner.py").read_text()
    tree = ast.parse(source)
    called: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        called[node.name] = {
            inner.func.attr for inner in ast.walk(node)
            if isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)}
    assert "_record_audit" in called["_audit"], (
        "the audit step does not record observations, so only findings refresh")
    assert "audit_html" in {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}, (
        "observations are produced by something other than `website_audit`. "
        "There is one audit implementation and this must be it")


def test_nothing_schedules_the_scripts_that_used_to_write_them():
    """The finding, kept as a guard.

    Both historical producers are hand-run scripts. If one is ever wired into
    the recurrences it should be a reviewed decision, not a surprise — and if
    somebody re-adds a second scheduled audit path, one business gets two
    audits a night from two engines and the comparison between them becomes
    noise.
    """
    scheduled = {r.recipe for r in recurrence.declared()}
    assert not scheduled & {"audit_discovered", "import_audits"}
    for script in ("infra/audit_discovered.py", "infra/import_audits.py"):
        assert Path(script).exists(), f"{script} was removed; update this test"


# ------------------------------------- a fresh reading, and what it refuses


def test_a_pass_records_what_the_page_demonstrably_has(repo):
    business = _business(repo)
    try:
        written, compared = _run_audit(
            repo, business, _evidence(PAGE, url=business.website))
        assert written == 1
        assert compared == 0, "there was nothing to compare against"

        audit = repo.latest_audit(business.id)
        observations = audit["observations"]
        assert len(observations) >= 15
        by_feature = {o["feature"]: o["status"] for o in observations}
        # All three states, from one real page.
        assert by_feature["click_to_call"] == "present"
        assert by_feature["viewport_meta"] == "not_found"
        assert "unverified" in set(by_feature.values())
        # Every observation carries the evidence for it, which is what makes
        # the health check checkable by the person receiving it.
        assert all(o["evidence"] for o in observations
                   if o["status"] != "unverified")
        assert audit["read_by"].endswith("/http-fetch"), (
            "an absence from an unrendered read is not the same claim as one "
            "from a browser, and the record has to say which it is")
    finally:
        _clean(business.id)


@pytest.mark.parametrize("evidence,why", [
    (lambda url: _evidence(PAGE[:400], url=url, truncated=True),
     "a truncated body would report everything below the cut as absent"),
    (lambda url: _evidence("<html><body>Server Error</body></html>", url=url,
                           status=500),
     "an error page says nothing about the homepage"),
    (lambda url: _evidence("", url=url, status=0, error="robots.txt disallows"),
     "a refusal is not a response; nobody saw the site"),
    (lambda url: _evidence("%PDF-1.4 ...", url=url,
                           content_type="application/pdf"),
     "a PDF with no <title> is not a defect"),
])
def test_it_refuses_to_audit_what_cannot_support_an_absence(repo, evidence, why):
    business = _business(repo)
    try:
        written, _ = _run_audit(repo, business, evidence(business.website))
        assert written == 0, why
        assert repo.latest_audit(business.id) == {}, (
            "a business it refuses keeps the audit it had; nothing false is "
            "written in its place")

        # Negative control: the same runner on a complete page does write one,
        # so the refusals above are the guard and not a broken fixture.
        assert _run_audit(repo, business,
                          _evidence(PAGE, url=business.website))[0] == 1
    finally:
        _clean(business.id)


def test_a_body_at_the_keep_limit_is_still_treated_as_truncated(repo):
    """The flag is the authority, not the length.

    `crawler.evidence_from` sets `body_truncated` by comparing against
    `BODY_KEPT`, and a reader that re-derived it from the string would disagree
    the first time that constant moved.
    """
    business = _business(repo)
    try:
        assert BODY_KEPT > 0
        long_page = PAGE + "<p>" + ("x" * 200) + "</p>"
        assert _run_audit(repo, business,
                          _evidence(long_page, url=business.website,
                                    truncated=True))[0] == 0
        assert _run_audit(repo, business,
                          _evidence(long_page, url=business.website))[0] == 1
    finally:
        _clean(business.id)


# ------------------------------------------- what changes, and what does not


def test_a_second_reading_records_the_difference_and_overwrites_nothing(repo):
    business = _business(repo)
    try:
        _run_audit(repo, business, _evidence(PAGE, url=business.website))
        first = repo.latest_audit(business.id)
        assert {o["feature"]: o["status"]
                for o in first["observations"]}["click_to_call"] == "present"

        # They removed the phone link. A fact about their site.
        without = PAGE.replace('<a href="tel:+971501234567">Call us</a>', "")
        written, compared = _run_audit(
            repo, business, _evidence(without, url=business.website))
        assert (written, compared) == (1, 1)

        with SessionLocal() as session:
            audits = session.execute(
                text("""SELECT count(*) FROM atlas_business_events
                        WHERE business_id = :b AND kind = 'website_audited'"""),
                {"b": business.id}).scalar()
            delta = session.execute(
                text("""SELECT detail FROM atlas_business_events
                        WHERE business_id = :b AND kind = 'business_reevaluated'
                        ORDER BY at DESC LIMIT 1"""),
                {"b": business.id}).scalar()
        assert audits == 2, "history is appended, never rewritten"

        import json
        summary = json.loads(delta) if isinstance(delta, str) else delta
        changed = {c["feature"]: c["change"] for c in summary["changes"]}
        assert changed["click_to_call"] == "contradicted"
        assert summary["counts"]["about_the_business"] >= 1
        # The pair a naive diff gets wrong. Nothing here may be reported as
        # their site declining when it is our own coverage.
        assert "about_our_checking" in summary["counts"]
    finally:
        _clean(business.id)


def test_an_unchanged_site_records_no_delta(repo):
    """Silence means nothing moved, and must not mean nothing was checked."""
    business = _business(repo)
    try:
        _run_audit(repo, business, _evidence(PAGE, url=business.website))
        written, compared = _run_audit(
            repo, business, _evidence(PAGE, url=business.website))
        assert (written, compared) == (1, 0)
        with SessionLocal() as session:
            deltas = session.execute(
                text("""SELECT count(*) FROM atlas_business_events
                        WHERE business_id = :b AND kind = 'business_reevaluated'"""),
                {"b": business.id}).scalar()
        assert deltas == 0
    finally:
        _clean(business.id)


def test_a_refreshed_audit_invalidates_no_commercial_record(repo):
    """The rule the whole slice is bounded by.

    A message somebody approved, an artefact that is published and an approval
    that was recorded all stand after the evidence under them moves. The delta
    is recorded so a person can see it; acting on it is their decision, and a
    nightly pass that withdrew an approval would be making it for them.
    """
    from atlas_kernel.opportunity.models import OutreachMessage, OutreachStatus

    business = _business(repo)
    try:
        _run_audit(repo, business, _evidence(PAGE, url=business.website))
        repo.record_publication(
            mission_id="m-1", business_id=business.id, signal_id="sig-x",
            commit="abc123", site_id="s", url="https://sites.test/s",
            files=["index.html"], actor="worker",
            offer="offer-health-check", tenant=TENANT)
        approved = repo.save_message(OutreachMessage(
            proposal_id="", mission_id="m-1", business_id=business.id,
            channel="email", recipient="hello@alwaha.test",
            subject="What I found", body="...",
            status=OutreachStatus.APPROVED, approved_fingerprint="fp-1"))

        without = PAGE.replace('<a href="tel:+971501234567">Call us</a>', "")
        _run_audit(repo, business, _evidence(without, url=business.website))

        after = repo.messages_for(business.id)[-1]
        assert after.status is OutreachStatus.APPROVED
        assert after.approved_fingerprint == approved.approved_fingerprint
        assert after.subject == approved.subject and after.body == approved.body
        assert repo.publications_of(business.id), "the publication still stands"
    finally:
        _clean(business.id)
        with SessionLocal() as session:
            session.execute(
                text("DELETE FROM atlas_outreach_messages WHERE business_id = :b"),
                {"b": business.id})
            session.commit()


# ------------------------------------------------------ the cadence is visible


def test_freshness_is_a_measurement_not_a_claim_about_the_schedule(repo):
    """The number that would have surfaced this in a day rather than twelve.

    A recurrence saying "nightly" is a declaration. This counts what is
    actually on the timeline, and reports a distribution because "the newest
    audit is from today" is true of a population whose median is a fortnight
    old.
    """
    business = _business(repo)
    try:
        before = repo.audit_freshness()
        _run_audit(repo, business, _evidence(PAGE, url=business.website))
        after = repo.audit_freshness()

        assert after["with_observations"] == before["with_observations"] + 1
        assert after["fresh_within_two_days"] == before["fresh_within_two_days"] + 1
        assert after["read_method_recorded"] == before["read_method_recorded"] + 1
        assert after["never_observed"] == max(0, before["never_observed"] - 1)
        # The distinction the whole finding turned on, said in the payload.
        assert "website_verified" in after["note"]
    finally:
        _clean(business.id)


def test_verification_is_never_counted_as_an_observation(repo):
    """`website_verified` must not be able to look like a fresh audit.

    It is what the nightly pass wrote for twelve days while nothing refreshed
    the observations, and the failure mode is a screen reporting today's date
    for evidence nobody re-read.
    """
    from atlas_kernel.opportunity.models import BusinessEvent

    business = _business(repo)
    try:
        before = repo.audit_freshness()
        repo.record_event(BusinessEvent(
            business_id=business.id, kind="website_verified",
            actor="recipe:verify-recorded-websites",
            detail={"answered": True, "findings": 0}))
        # Counted as a delta: this reads the whole population, and an absolute
        # figure would be an assertion about every other test's fixtures.
        after_verified = repo.audit_freshness()
        assert after_verified["with_observations"] == before["with_observations"]
        assert after_verified["fresh_within_two_days"] == \
               before["fresh_within_two_days"]
        assert repo.latest_audit(business.id) == {}

        # Negative control: a real audit does count, so the unchanged figures
        # above are the distinction and not a reader that counts nothing.
        _run_audit(repo, business, _evidence(PAGE, url=business.website))
        assert repo.audit_freshness()["with_observations"] == \
               before["with_observations"] + 1
    finally:
        _clean(business.id)


def test_an_audit_with_no_timestamp_is_unknown_age_not_ancient(repo):
    """`None`, never a large number.

    Reporting an undated record as very old is a claim about the record rather
    than a reading of it, and the console draws anything over a week as a
    warning.
    """
    from atlas_kernel.opportunity.dossier import _age

    assert _age("") is None
    assert _age("not a date") is None
    assert _age(datetime.now(UTC).isoformat()) == 0


# ------------------------------------- an absence a better reading contradicts


def test_a_plain_fetch_does_not_contradict_a_rendered_reading(repo):
    """The defect the first real production pass produced.

    One business went from `present` to `not_found` on five features in a
    single night — `booking_link`, `contact_form`, `meta_description`,
    `services_navigation` and `viewport_meta`. A site does not lose its
    `<head>` overnight; the earlier reading was Playwright and this one a plain
    fetch, and a page assembled client-side is nearly empty to the second.

    Five false claims, on their way to a health check that would have shown the
    business each of them.
    """
    from atlas_kernel.opportunity.website_audit import Status, reconcile

    previous = [{"feature": "viewport_meta", "status": "present"},
                {"feature": "contact_form", "status": "present"},
                {"feature": "structured_data", "status": "not_found"}]
    current = audit_html(
        "<html><head></head><body><p>rendered client-side</p></body></html>",
        url="https://alwaha.test", page_bytes=60)
    by_feature = {f.feature: f for f in current}
    assert by_feature["viewport_meta"].status is Status.NOT_FOUND, "fixture"

    reconciled = {f.feature: f for f in reconcile(
        current, previous=previous,
        previous_read_by="audit_discovered.py/browser",
        current_read_by="recipe:verify-recorded-websites/http-fetch")}
    assert reconciled["viewport_meta"].status is Status.UNVERIFIED
    assert reconciled["contact_form"].status is Status.UNVERIFIED
    assert "not made the same way" in reconciled["viewport_meta"].evidence
    # One-directional. A reading that *sees* something is confirming it, and a
    # feature the old reading missed stays exactly as this one found it.
    assert reconciled["structured_data"].status is by_feature[
        "structured_data"].status


def test_two_readings_of_the_same_kind_still_contradict_each_other(repo):
    """The negative control, and the reason this is not a blanket demotion.

    A business that genuinely removes its contact form must still be recorded
    as having removed it, or the audit can never report a real regression.
    """
    from atlas_kernel.opportunity.website_audit import Status, reconcile

    same = "recipe:verify-recorded-websites/http-fetch"
    previous = [{"feature": "viewport_meta", "status": "present"}]
    current = audit_html("<html><head></head><body>x</body></html>",
                         url="https://alwaha.test", page_bytes=40)
    reconciled = {f.feature: f for f in reconcile(
        current, previous=previous, previous_read_by=same, current_read_by=same)}
    assert reconciled["viewport_meta"].status is Status.NOT_FOUND


def test_a_previous_reading_of_unrecorded_method_is_not_assumed_comparable(repo):
    """Every audit written before `read_by` existed says nothing about method.

    Treating unknown provenance as "probably the same" is exactly how the false
    absence gets through — all 396 historical rows are in that state.
    """
    from atlas_kernel.opportunity.website_audit import Status, reconcile

    reconciled = {f.feature: f for f in reconcile(
        audit_html("<html><head></head><body>x</body></html>",
                   url="https://alwaha.test", page_bytes=40),
        previous=[{"feature": "viewport_meta", "status": "present"}],
        previous_read_by="",
        current_read_by="recipe:verify-recorded-websites/http-fetch")}
    assert reconciled["viewport_meta"].status is Status.UNVERIFIED
    assert "method not recorded" in reconciled["viewport_meta"].evidence


def test_the_pass_writes_the_reconciled_record_not_the_raw_one(repo):
    """End to end: what lands on the timeline is what a health check reports."""
    from atlas_kernel.opportunity.models import BusinessEvent

    business = _business(repo)
    try:
        repo.record_event(BusinessEvent(
            business_id=business.id, factory="website", kind="website_audited",
            actor="audit_discovered.py",
            detail={"url": business.website, "audited_at": "2026-08-19T20:00:00Z",
                    "observations": [{"feature": "viewport_meta",
                                      "status": "present",
                                      "evidence": "<meta name=viewport>"}]}))
        # A shell page: everything the browser saw is invisible to a fetch.
        _run_audit(repo, business,
                   _evidence("<html><head></head><body>loading</body></html>",
                             url=business.website))
        fresh = {o["feature"]: o["status"]
                 for o in repo.latest_audit(business.id)["observations"]}
        assert fresh["viewport_meta"] == "unverified", (
            "a claim the previous rendered reading contradicts reached the "
            "timeline, and the health check reports from exactly this record")
    finally:
        _clean(business.id)
