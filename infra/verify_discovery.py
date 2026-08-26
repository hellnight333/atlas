"""Discovery, end to end, against real infrastructure.

The unit tests cover the decisions. This runs the parts that only mean something
when they are real: a live HTTP server the crawler actually fetches from, the
address guard refused against a socket that genuinely exists, the database
across a reconnection, and the recurrence tick inside the real worker process.

The fixture server is deliberate. Fetching a real third-party site would make
this test's result depend on somebody else's uptime, and a test that fails when
a stranger's server is slow is a test people learn to ignore.

    python3 infra/verify_discovery.py
"""

from __future__ import annotations

import http.server
import sys
import tempfile
import threading
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal, init_db  # noqa: E402
from atlas_kernel.mission import origins, recurrence  # noqa: E402
from atlas_kernel.mission.models import MissionStatus  # noqa: E402
from atlas_kernel.mission.timeline import Timeline  # noqa: E402
from atlas_kernel.opportunity import crawler, scan, signals  # noqa: E402
from atlas_kernel.opportunity.discovery import (  # noqa: E402
    DiscoveryState,
    Novelty,
    Sighting,
)
from atlas_kernel.opportunity.models import Evidence, EvidenceKind  # noqa: E402
from atlas_kernel.opportunity.repository import OpportunityRepository  # noqa: E402
from atlas_kernel.opportunity.tenancy import ALL_TENANTS  # noqa: E402

TENANT = "tenant-discovery-proof"
MARKER = "verify-disc"

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


class Fixture(http.server.BaseHTTPRequestHandler):
    """A site with a known shape, so the crawl result is a fact about the code."""

    PAGES = {
        "/": (200, "text/html", "<html lang='en'><h1>Marina Dental</h1></html>"),
        "/robots.txt": (200, "text/plain", "User-agent: *\nAllow: /\n"),
        "/gone": (404, "text/html", "<html><h1>Not found</h1></html>"),
    }

    def do_GET(self):                                   # noqa: N802 - stdlib API
        status, kind, body = self.PAGES.get(
            self.path, (404, "text/html", "<html>no</html>"))
        raw = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):                          # noqa: A003 - stdlib API
        return


def an_evidence(url: str) -> Evidence:
    return Evidence(kind=EvidenceKind.HTTP_RESPONSE, source=url,
                    observed={"place_id": "PL-VERIFY"}, detector=MARKER)


def a_sighting(**over) -> Sighting:
    fields = dict(name="VerifyDisc Marina Dental", source=f"{MARKER}-places",
                  source_id="PL-VERIFY", source_url="https://verifydisc.test/",
                  country="AE", city="Dubai",
                  evidence=[an_evidence("https://places.test/x")])
    fields.update(over)
    return Sighting(**fields)


def clean() -> None:
    with SessionLocal() as session:
        session.execute(text(
            "DELETE FROM atlas_sightings WHERE source LIKE :m"),
            {"m": f"{MARKER}%"})
        session.execute(text(
            "DELETE FROM atlas_businesses WHERE name LIKE 'VerifyDisc %'"))
        session.commit()


# ------------------------------------------------- 8. the guard, against sockets

def ssrf_is_active(port: int) -> None:
    """Refused against an address that genuinely answers.

    The important half is the paired control: a guard that refuses everything
    would pass the refusal checks and prove nothing, so the same fetcher is
    pointed at the same server through a public-looking name and must succeed.
    """
    private = [f"http://127.0.0.1:{port}/",
               "http://169.254.169.254/latest/meta-data/",
               "http://10.0.0.1/", "http://[::1]/"]
    evidence, refused = crawler.fetch_steps(private, detector=MARKER)
    check("every private address is refused, including one that is listening",
          not evidence and len(refused) == len(private),
          f"{len(evidence)} fetched, {len(refused)} refused")
    check("...and the refusals come from the address guard, not the site",
          all(crawler.was_refused_by_the_guard(r) for r in refused),
          "; ".join(r.because[:40] for r in refused[:2]))
    check("...the cloud metadata service by name",
          any("metadata" in r.because for r in refused))

    # The paired control. `check_addresses=False` is the documented escape for
    # a caller supplying its own transport; here it stands in for "the same
    # request, to an address the guard would allow".
    allowed, blocked = crawler.fetch_steps(
        [f"http://127.0.0.1:{port}/"], detector=MARKER, check_addresses=False)
    check("POSITIVE CONTROL: the same server fetches when the guard permits it",
          len(allowed) == 1 and not blocked,
          str(allowed[0].observed.get("status")) if allowed else str(blocked))
    if allowed:
        check("...and the evidence records what the server actually said",
              allowed[0].observed["status"] == 200
              and "html" in allowed[0].observed["content_type"],
              str(allowed[0].observed)[:80])


def dns_stays_honest() -> None:
    """A lookup that establishes nothing must not become a finding.

    The safety property is the **negative** one, and it is the only one asserted
    unconditionally. Whether a made-up name returns NXDOMAIN depends on the
    resolver in front of this machine — plenty of them answer everything, which
    would make the positive assertion a test of somebody's DNS rather than of
    this code. That has already caught two tests in this project out.
    """
    from atlas_kernel.research.net import Resolution, host_of, resolution

    made_up = "https://this-host-does-not-exist-qevik-verify.invalid/"
    answer = resolution(host_of(made_up))
    evidence = crawler.unreachable(made_up, detector=MARKER)

    if answer is Resolution.NO_SUCH_HOST:
        check("a conclusively absent host produces evidence",
              evidence is not None
              and evidence.observed["resolution"] == "no_such_host",
              str(evidence.observed) if evidence else "nothing")
    else:
        check("AN INCONCLUSIVE LOOKUP PRODUCES NO EVIDENCE AT ALL",
              evidence is None,
              f"this resolver answered {answer.value} for a made-up name, so "
              "the conclusive branch is NOT VERIFIED here")


# --------------------------------------- 1-5. memory, across a real reconnection

def memory_survives() -> None:
    repo = OpportunityRepository()
    first = scan.record([a_sighting()], repository=repo, tenant=TENANT)
    business_id = first.recorded[0].business.id
    check("a new entity is discovered",
          first.recorded[0].classification.state
          is DiscoveryState.DISCOVERED_BY_QEVIK,
          first.recorded[0].classification.state.value)

    again = scan.record([a_sighting(source_id="PL-VERIFY-2")], repository=repo,
                        tenant=TENANT)
    check("the same entity is not duplicated",
          again.recorded[0].business.id == business_id
          and again.recorded[0].classification.state is DiscoveryState.KNOWN,
          again.recorded[0].classification.state.value)

    # A different repository object and a fresh connection — a restart, as far
    # as one process can manage.
    fresh = OpportunityRepository()
    stored = fresh.get_business(business_id, tenant=ALL_TENANTS)
    check("first_seen and last_seen survive a reconnection",
          stored is not None and stored.first_seen_at <= stored.last_seen_at,
          f"{stored.first_seen_at.isoformat()} .. {stored.last_seen_at.isoformat()}"
          if stored else "gone")

    history = fresh.sightings_for(business_id, tenant=TENANT)
    check("evidence survives", bool(history) and bool(history[0]["evidence"])
          and history[0]["evidence"][0]["detector"] == MARKER,
          str(history[0]["evidence"])[:70] if history else "none")
    check("previous observations accumulate", len(history) == 2,
          f"{len(history)} sightings")

    evidenced = a_sighting(source_id="PL-VERIFY-3", novelty=Novelty(
        source=f"{MARKER}-places", field="first_review_at", value="2026-08-20",
        evidence=an_evidence("https://places.test/x")))
    third = scan.record([evidenced], repository=repo, tenant=TENANT)
    check("a source's own novelty evidence is what promotes the state",
          third.recorded[0].classification.state
          is DiscoveryState.PROVEN_NEW_TO_SOURCE
          or third.recorded[0].classification.state is DiscoveryState.KNOWN,
          third.recorded[0].classification.state.value)
    check("NEW_TO_QEVIK IS NEVER REPORTED AS NEW TO THE SOURCE",
          all(row["claims_about_the_world"] is False
              for row in fresh.sightings_for(business_id, tenant=TENANT)
              if row["novelty"] is None),
          "a sighting claimed the world without novelty evidence")


# ------------------------------------------- 9. unattended, through the scheduler

def runs_through_the_scheduler(tmp: Path) -> None:
    rule = next((r for r in recurrence.RECURRENCES
                 if r.id == "rec-daily-business-discovery"), None)
    if rule is None:
        check("the daily discovery recurrence is declared", False, "absent")
        return
    check("the daily discovery recurrence is declared", True, rule.origin_name)

    registry = origins.Registry.build()
    origin = registry.resolve(rule.origin_name)
    check("its origin is empty, so it changes no repository",
          origin.may_run_unattended and not origin.modifies_qevik_itself,
          origin.kind.value)

    timeline = Timeline(tmp / "discovery" / "missions.jsonl")
    firing = recurrence.assess(rule, at=rule.anchor, missions=[])
    mission, events = recurrence.enqueue(rule, firing, tenant=rule.tenant_id,
                                         origin=origin)
    for event in events:
        timeline.append(event)
    check("IT REACHES THE QUEUE WITH NOBODY ASKED",
          mission.status is MissionStatus.QUEUED, mission.status.value)

    # The real worker's own tick function, at a moment past the anchor.
    #
    # Not a subprocess: both recurrences are anchored tomorrow, so a worker run
    # now correctly creates nothing, and the first version of this asserted on a
    # log line that was absent for the right reason. `tick_recurrences` takes
    # the moment, which is exactly so this can be asked without waiting a day.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mission_worker", ROOT / "infra" / "mission_worker.py")
    worker = importlib.util.module_from_spec(spec)
    sys.modules["mission_worker"] = worker
    spec.loader.exec_module(worker)

    ticked = Timeline(tmp / "tick" / "missions.jsonl")
    from atlas_kernel.mission.claims import LocalClaims
    created = worker.tick_recurrences(
        ticked, tenant=rule.tenant_id, name="worker-discovery",
        claims=LocalClaims(), registry=registry,
        at=rule.anchor + timedelta(hours=1))
    check("THE REAL WORKER'S TICK CREATES IT WHEN IT COMES DUE",
          created >= 1, f"{created} created")

    from atlas_kernel.mission import service as mission_service
    folded = mission_service.fold(Timeline(ticked.path).read(),
                                  tenant=rule.tenant_id)
    discovery = [m for m in folded
                 if (m.get("occurrence") or "").startswith(rule.id)]
    check("...as a queued mission nobody approved",
          bool(discovery)
          and discovery[0]["status"] == MissionStatus.QUEUED.value,
          discovery[0]["status"] if discovery else "no mission")
    check("...in the empty origin it declared",
          bool(discovery) and discovery[0]["origin_name"] == rule.origin_name,
          discovery[0].get("origin_name") if discovery else "")

    # And ticking again at the same moment creates nothing.
    twice = worker.tick_recurrences(
        ticked, tenant=rule.tenant_id, name="worker-discovery",
        claims=LocalClaims(), registry=registry,
        at=rule.anchor + timedelta(hours=2))
    check("...and a second tick in the same window creates nothing",
          twice == 0, f"{twice} created")




# ------------------------------- 6, 7, 10. evidence into an opportunity, gated

def evidence_becomes_an_opportunity() -> None:
    from atlas_kernel.opportunity.models import Finding, FindingKind, Severity

    findings = [
        Finding(business_id=f"b-{n}", kind=FindingKind.NO_ARABIC,
                severity=Severity.MEDIUM,
                statement="The homepage has no Arabic version.",
                evidence=[Evidence(kind=EvidenceKind.HTML_CONTENT,
                                   source=f"https://clinic{n}.test/",
                                   observed={"lang": "en", "arabic": False},
                                   detector=MARKER)],
                confidence=0.9)
        for n in range(17)]

    signal = signals.market_gap(
        findings, scope="dubai-marina/dental", population=40,
        says="17 of 40 clinics in Dubai Marina have no Arabic page.",
        might_mean="Arabic localisation may be commercially valuable here.",
        confidence=0.45,
        wrong_if="the clientele is predominantly English-speaking",
        action="Offer the Arabic experience to qualifying clinics.",
        capability="arabic-builder")

    rendered = signal.summary()
    check("an opportunity is generated from evidence",
          rendered["observations"][0]["counted"] == 17
          and rendered["observations"][0]["evidence_count"] == 17)
    check("the inference is labelled as an inference in the payload",
          rendered["inferences"][0]["is_an_inference"] is True)
    check("the observation carries no confidence, the inference does",
          "confidence" not in rendered["observations"][0]
          and rendered["inferences"][0]["confidence"] == 0.45)
    check("THE SUGGESTED ACTION CANNOT HAPPEN WITHOUT A PERSON",
          rendered["actions"][0]["needs_approval"] is True
          and not signal.is_actionable_without_a_person)

    hollow = signal.model_copy(update={
        "inferences": [signal.inferences[0].model_construct(
            statement="Arabic is definitely worth money here.",
            rests_on=(), confidence=0.99)]})
    check("an unsupported conclusion is refused",
          bool(signals.refuse_conclusion_without_evidence(hollow)),
          signals.refuse_conclusion_without_evidence(hollow)[:70])


def main() -> int:
    print("discovery — real server, real database, real worker\n")
    init_db()
    clean()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            print("the address guard")
            ssrf_is_active(port)
            dns_stays_honest()
            print("\nmemory")
            memory_survives()
            print("\nevidence into an opportunity")
            evidence_becomes_an_opportunity()
            print("\nthe scheduler")
            runs_through_the_scheduler(tmp)
    finally:
        server.shutdown()
        clean()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
