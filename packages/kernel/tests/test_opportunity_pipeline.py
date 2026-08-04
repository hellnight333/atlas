"""Qualification, proposals, the funnel, and the whole pipeline (M014).

Three things are being defended here.

**The qualification bar is real.** Without it, every business with a missing
``<h1>`` becomes a business, and an outreach engine that contacts people over
cosmetic defects is spam no matter how many approval gates sit in front of it.

**Proposals are not templates.** The test that matters is not that the generator
produces text — it is that two different businesses receive materially different
text, because the text is assembled from their own findings.

**The funnel is measured from events, not from current state.** A funnel derived
from where things ended cannot tell you that forty businesses were contacted and
came back to nothing.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_kernel.approval.models import (
    ApprovalDecision,
    ApprovalDecisionType,
    ApprovalRequest,
    ApprovalState,
)
from atlas_kernel.opportunity.detectors.base import DetectorRegistry
from atlas_kernel.opportunity.detectors.website import WebsiteDetector
from atlas_kernel.opportunity.gate import PROPOSAL_FINGERPRINT, OutreachGate
from atlas_kernel.opportunity.metrics import build_report
from atlas_kernel.opportunity.models import (
    Business,
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    NicheProfile,
    Opportunity,
    OpportunityStage,
    OutreachStatus,
    PipelineEvent,
    PipelineEventKind,
    Severity,
)
from atlas_kernel.opportunity.outreach import OutreachService, RecordingChannel
from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE
from atlas_kernel.opportunity.proposals import (
    MAX_CLAIMS_IN_FIRST_CONTACT,
    EvidenceProposalGenerator,
)
from atlas_kernel.opportunity.qualification import qualify, rank, score
from atlas_kernel.opportunity.service import OpportunityService
from atlas_kernel.opportunity.sources import SeedListSource

BARE_PAGE = "<html><body><p>Coming soon</p></body></html>"
GOOD_PAGE = (
    "<!doctype html><html><head><title>Al Noor Dental Clinic</title>"
    '<meta name="description" content="Dental care in Jumeirah.">'
    '<meta name="viewport" content="width=device-width">'
    '<script type="application/ld+json">{"@type":"Dentist"}</script>'
    "</head><body><h1>Al Noor</h1><p>"
    + ("Dental care in Jumeirah since 2009. " * 20)
    + "</p></body></html>"
)

SEED_CSV = """name,website,email
Al Noor Dental Clinic,https://alnoor.test,hello@alnoor.test
Jumeirah Auto Garage,https://garage.test,info@garage.test
"""


def _business(name: str = "Al Noor Dental Clinic") -> Business:
    return Business(
        name=name,
        geography="United Arab Emirates",
        website="https://clinic.test",
        email="hello@clinic.test",
    )


def _finding(business_id: str, kind: FindingKind, severity: Severity, statement: str) -> Finding:
    return Finding(
        business_id=business_id,
        kind=kind,
        severity=severity,
        statement=statement,
        evidence=[
            Evidence(
                kind=EvidenceKind.HTML_CONTENT,
                source="https://clinic.test",
                summary=f"observed: {statement}",
                detector="website",
            )
        ],
    )


class TestQualification:
    def test_cosmetic_defects_alone_do_not_qualify_anyone(self) -> None:
        """The bar that stops this becoming spam."""
        business = _business()
        cosmetic = [
            _finding(business.id, FindingKind.MISSING_H1, Severity.LOW, "No main heading."),
            _finding(
                business.id, FindingKind.NO_STRUCTURED_DATA, Severity.LOW, "No structured data."
            ),
        ]
        opportunity = qualify(business, cosmetic, EXAMPLE_PROFILE)
        assert opportunity.stage is OpportunityStage.DISQUALIFIED
        assert opportunity.score < EXAMPLE_PROFILE.qualify_threshold

    def test_a_serious_defect_qualifies(self) -> None:
        business = _business()
        serious = [
            _finding(
                business.id, FindingKind.NOT_MOBILE_FRIENDLY, Severity.HIGH, "Not usable on mobile."
            ),
            _finding(business.id, FindingKind.MISSING_TITLE, Severity.HIGH, "No title."),
        ]
        assert qualify(business, serious, EXAMPLE_PROFILE).stage is OpportunityStage.QUALIFIED

    def test_a_business_with_nothing_wrong_does_not_qualify(self) -> None:
        assert qualify(_business(), [], EXAMPLE_PROFILE).stage is OpportunityStage.DISQUALIFIED

    def test_a_niche_can_ignore_findings_it_does_not_care_about(self) -> None:
        business = _business()
        profile = EXAMPLE_PROFILE.model_copy(
            update={"ignore_kinds": [FindingKind.NO_STRUCTURED_DATA]}
        )
        findings = [
            _finding(business.id, FindingKind.MISSING_TITLE, Severity.HIGH, "No title."),
            _finding(business.id, FindingKind.NO_STRUCTURED_DATA, Severity.LOW, "No JSON-LD."),
        ]
        opportunity = qualify(business, findings, profile)
        assert [f.kind for f in opportunity.findings] == [FindingKind.MISSING_TITLE]

    def test_disqualified_businesses_are_kept_not_discarded(self) -> None:
        """Knowing how many were looked at and rejected is the difference
        between a funnel and a list of wins."""
        opportunity = qualify(_business(), [], EXAMPLE_PROFILE)
        assert opportunity.business_id
        assert opportunity.stage is OpportunityStage.DISQUALIFIED

    def test_ranking_is_stable_across_runs(self) -> None:
        """An unstable order makes "the top 20 businesses" mean something
        different every run, which ruins any measurement built on it."""
        business = _business()
        tied = [
            qualify(
                business,
                [_finding(business.id, FindingKind.MISSING_TITLE, Severity.HIGH, "No title.")],
                EXAMPLE_PROFILE,
            )
            for _ in range(5)
        ]
        assert [o.id for o in rank(tied)] == [o.id for o in rank(list(reversed(tied)))]

    def test_score_is_the_sum_of_severity_weights(self) -> None:
        business = _business()
        findings = [
            _finding(business.id, FindingKind.MISSING_TITLE, Severity.HIGH, "a"),
            _finding(business.id, FindingKind.MISSING_META_DESCRIPTION, Severity.MEDIUM, "b"),
            _finding(business.id, FindingKind.MISSING_H1, Severity.LOW, "c"),
        ]
        assert score(findings) == pytest.approx(5.0 + 2.5 + 1.0)


class TestProposals:
    def _opportunity(self, business: Business) -> Opportunity:
        return qualify(
            business,
            [
                _finding(
                    business.id,
                    FindingKind.NOT_MOBILE_FRIENDLY,
                    Severity.HIGH,
                    "The site is unusable on a phone.",
                ),
                _finding(
                    business.id, FindingKind.MISSING_TITLE, Severity.HIGH, "The page has no title."
                ),
            ],
            EXAMPLE_PROFILE,
        )

    def test_every_claim_cites_a_finding_that_is_actually_attached(self) -> None:
        business = _business()
        opportunity = self._opportunity(business)
        proposal = EvidenceProposalGenerator().generate(business, opportunity, EXAMPLE_PROFILE)
        attached = {finding.id for finding in opportunity.findings}
        assert {claim.finding_id for claim in proposal.claims} <= attached

    def test_two_businesses_receive_materially_different_text(self) -> None:
        """The test that distinguishes generation from a template with the name
        substituted in."""
        first = _business("Al Noor Dental Clinic")
        second = _business("Jumeirah Auto Garage")
        generator = EvidenceProposalGenerator()

        a = generator.generate(first, self._opportunity(first), EXAMPLE_PROFILE)
        b = generator.generate(
            second,
            qualify(
                second,
                [
                    _finding(
                        second.id,
                        FindingKind.SITE_UNREACHABLE,
                        Severity.HIGH,
                        "The website did not respond.",
                    ),
                    _finding(
                        second.id, FindingKind.NO_HTTPS, Severity.HIGH, "Served over plain HTTP."
                    ),
                ],
                EXAMPLE_PROFILE,
            ),
            EXAMPLE_PROFILE,
        )

        assert a.subject != b.subject
        # Not merely a different name — different observations, different remedies.
        assert "did not respond" in b.body
        assert "did not respond" not in a.body

    def test_the_body_quotes_the_evidence_behind_each_claim(self) -> None:
        """The line that makes a message answerable rather than a sales claim."""
        business = _business()
        opportunity = self._opportunity(business)
        proposal = EvidenceProposalGenerator().generate(business, opportunity, EXAMPLE_PROFILE)
        for finding in opportunity.findings[:MAX_CLAIMS_IN_FIRST_CONTACT]:
            assert finding.evidence[0].summary in proposal.body

    def test_a_first_message_does_not_fire_every_finding_at_once(self) -> None:
        business = _business()
        many = [
            _finding(business.id, kind, Severity.HIGH, f"Problem {index}.")
            for index, kind in enumerate(
                [
                    FindingKind.NOT_MOBILE_FRIENDLY,
                    FindingKind.MISSING_TITLE,
                    FindingKind.NO_HTTPS,
                    FindingKind.SLOW_RESPONSE,
                    FindingKind.THIN_CONTENT,
                ]
            )
        ]
        proposal = EvidenceProposalGenerator().generate(
            business, qualify(business, many, EXAMPLE_PROFILE), EXAMPLE_PROFILE
        )
        assert len(proposal.claims) == MAX_CLAIMS_IN_FIRST_CONTACT

    def test_the_worst_finding_leads(self) -> None:
        business = _business()
        findings = [
            _finding(business.id, FindingKind.MISSING_H1, Severity.LOW, "No heading."),
            _finding(business.id, FindingKind.SITE_UNREACHABLE, Severity.HIGH, "Site is down."),
        ]
        proposal = EvidenceProposalGenerator().generate(
            business, qualify(business, findings, EXAMPLE_PROFILE), EXAMPLE_PROFILE
        )
        assert "isn't loading" in proposal.subject

    def test_it_refuses_to_write_about_a_business_with_no_findings(self) -> None:
        business = _business()
        empty = Opportunity(business_id=business.id, niche=EXAMPLE_PROFILE.id, findings=[])
        with pytest.raises(ValueError, match="no findings to cite"):
            EvidenceProposalGenerator().generate(business, empty, EXAMPLE_PROFILE)

    def test_the_proposal_records_the_facts_it_was_generated_from(self) -> None:
        business = _business()
        opportunity = self._opportunity(business)
        proposal = EvidenceProposalGenerator().generate(business, opportunity, EXAMPLE_PROFILE)
        assert proposal.findings_fingerprint == opportunity.findings_fingerprint
        assert proposal.generator == "evidence-composer"


class TestSeedSource:
    def test_it_reads_a_csv_the_operator_supplied(self) -> None:
        businesses = SeedListSource.from_csv(SEED_CSV).discover(EXAMPLE_PROFILE, limit=10)
        assert [p.name for p in businesses] == ["Al Noor Dental Clinic", "Jumeirah Auto Garage"]
        assert businesses[0].email == "hello@alnoor.test"
        assert businesses[0].sources == ["seed-list"]

    def test_rows_without_a_name_are_skipped_not_invented(self) -> None:
        source = SeedListSource.from_csv(
            "name,website\n,https://nameless.test\nReal,https://r.test\n"
        )
        assert [p.name for p in source.discover(EXAMPLE_PROFILE, 10)] == ["Real"]

    def test_the_limit_is_honoured(self) -> None:
        assert len(SeedListSource.from_csv(SEED_CSV).discover(EXAMPLE_PROFILE, limit=1)) == 1

    def test_unrecognised_columns_are_kept_rather_than_dropped(self) -> None:
        source = SeedListSource.from_csv("name,area\nAl Noor,Jumeirah\n")
        assert source.discover(EXAMPLE_PROFILE, 10)[0].metadata["area"] == "Jumeirah"


class TestMetrics:
    def _event(self, kind: PipelineEventKind, business: str) -> PipelineEvent:
        return PipelineEvent(opportunity_id=f"o-{business}", business_id=business, kind=kind)

    def test_rates_are_none_rather_than_zero_when_there_is_no_data(self) -> None:
        """ "0%" reads as failure; "not enough data yet" is the truth, and the
        two must not render the same way."""
        report = build_report([])
        assert report.close_rate is None
        assert report.reply_rate is None
        assert report.approval_rate is None

    def test_a_business_contacted_three_times_counts_once(self) -> None:
        """Otherwise follow-ups flatter every rate downstream."""
        events = [self._event(PipelineEventKind.SENT, "p1") for _ in range(3)]
        assert build_report(events).counts["sent"] == 1

    def test_the_funnel_reports_each_stage(self) -> None:
        events = [
            self._event(PipelineEventKind.DISCOVERED, "p1"),
            self._event(PipelineEventKind.DISCOVERED, "p2"),
            self._event(PipelineEventKind.QUALIFIED, "p1"),
            self._event(PipelineEventKind.DISQUALIFIED, "p2"),
            self._event(PipelineEventKind.PROPOSAL_GENERATED, "p1"),
            self._event(PipelineEventKind.APPROVED, "p1"),
            self._event(PipelineEventKind.SENT, "p1"),
            self._event(PipelineEventKind.REPLIED, "p1"),
            self._event(PipelineEventKind.MEETING_BOOKED, "p1"),
            self._event(PipelineEventKind.WON, "p1"),
        ]
        report = build_report(events)
        assert report.counts["discovered"] == 2
        assert report.counts["qualified"] == 1
        assert report.disqualified == 1
        assert report.close_rate == 1.0
        assert report.qualification_rate == 0.5

    def test_close_rate_is_measured_against_everyone_contacted(self) -> None:
        """Not against the few who agreed to talk — that flatters itself."""
        events = [self._event(PipelineEventKind.SENT, f"p{i}") for i in range(10)]
        events.append(self._event(PipelineEventKind.MEETING_BOOKED, "p1"))
        events.append(self._event(PipelineEventKind.WON, "p1"))
        assert build_report(events).close_rate == 0.1

    def test_refusals_are_reported_rather_than_hidden(self) -> None:
        events = [
            self._event(PipelineEventKind.SUPPRESSED, "p1"),
            self._event(PipelineEventKind.SEND_FAILED, "p2"),
            self._event(PipelineEventKind.LOST, "p3"),
        ]
        report = build_report(events)
        assert (report.suppressed, report.send_failed, report.lost) == (1, 1, 1)
        assert report.as_dict()["rates"]["close"] is None


class TestWholePipeline:
    """Discovery through to a measured funnel, against the real detector."""

    def _service(self, page: str, channel: RecordingChannel) -> OpportunityService:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, html=page)

        registry = DetectorRegistry()
        registry.register_source(SeedListSource.from_csv(SEED_CSV))
        registry.register_detector(
            WebsiteDetector(
                client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
            )
        )
        return OpportunityService(
            detectors=registry,
            gate=OutreachGate(approvals=None),  # type: ignore[arg-type]
            outreach=OutreachService(channel),
        )

    def test_a_scan_finds_and_ranks_without_contacting_anyone(self) -> None:
        channel = RecordingChannel()
        service = self._service(BARE_PAGE, channel)
        opportunities = service.scan(EXAMPLE_PROFILE, limit=10)

        assert len(opportunities) == 2
        assert all(o.stage is OpportunityStage.QUALIFIED for o in opportunities)
        assert channel.delivered == [], "a scan must never send anything"

    def test_a_healthy_business_is_discovered_and_then_left_alone(self) -> None:
        service = self._service(GOOD_PAGE, RecordingChannel())
        opportunities = service.scan(EXAMPLE_PROFILE, limit=10)
        assert all(o.stage is OpportunityStage.DISQUALIFIED for o in opportunities)

        report = service.report()
        assert report.counts["discovered"] == 2
        assert report.counts["qualified"] == 0
        assert report.disqualified == 2

    def test_preparing_an_unqualified_business_is_refused(self) -> None:
        service = self._service(GOOD_PAGE, RecordingChannel())
        opportunities = service.scan(EXAMPLE_PROFILE, limit=1)
        business = _business()
        with pytest.raises(ValueError, match="did not qualify"):
            service.prepare(business, opportunities[0], EXAMPLE_PROFILE)

    def test_end_to_end_with_a_human_in_the_middle(self) -> None:
        channel = RecordingChannel()
        service = self._service(BARE_PAGE, channel)

        opportunity = service.scan(EXAMPLE_PROFILE, limit=1)[0]
        business = Business(
            id=opportunity.business_id,
            name="Al Noor Dental Clinic",
            geography="United Arab Emirates",
            website="https://alnoor.test",
            email="hello@alnoor.test",
        )

        prepared = service.prepare(business, opportunity, EXAMPLE_PROFILE)
        assert channel.delivered == [], "preparing must not send"

        approval = ApprovalRequest(
            title="Contact Al Noor Dental Clinic",
            state=ApprovalState.APPROVED,
            metadata={PROPOSAL_FINGERPRINT: prepared.proposal.fingerprint},
            decisions=[ApprovalDecision(decision=ApprovalDecisionType.APPROVE, actor="ayoub")],
        )
        sent = service.send(prepared, approval, EXAMPLE_PROFILE)

        assert sent.status is OutreachStatus.SENT
        assert len(channel.delivered) == 1

        service.record_reply(opportunity.id, business.id)
        service.record_meeting(opportunity.id, business.id)
        service.record_won(opportunity.id, business.id, value=6000)

        report = service.report()
        assert report.counts["sent"] == 1
        assert report.reply_rate == 1.0
        assert report.close_rate == 1.0

    def test_every_transition_leaves_an_event(self) -> None:
        """The funnel is only as honest as the log it is derived from."""
        service = self._service(BARE_PAGE, RecordingChannel())
        service.scan(EXAMPLE_PROFILE, limit=1)
        kinds = [event.kind for event in service.events]
        assert PipelineEventKind.DISCOVERED in kinds
        assert PipelineEventKind.QUALIFIED in kinds

    def test_a_profile_with_a_higher_bar_contacts_fewer_people(self) -> None:
        """The threshold is the lever, and it lives in data."""
        service = self._service(BARE_PAGE, RecordingChannel())
        strict: NicheProfile = EXAMPLE_PROFILE.model_copy(update={"qualify_threshold": 999.0})
        assert all(o.stage is OpportunityStage.DISQUALIFIED for o in service.scan(strict, limit=2))
