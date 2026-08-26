"""Discovery to opportunity, end to end, against real infrastructure.

The milestone this proves: Qevik discovers a real business, remembers it,
understands why it matters, and produces an actionable next step backed by
evidence — with every claim traceable to the bytes that support it.

A controlled Overpass response is served from a local fixture so the *shape* of
the result is a fact about the code rather than about OpenStreetMap's uptime.
The address guard is exercised separately against real addresses, because a
fixture on loopback is exactly what the guard refuses.

    python3 infra/verify_opportunity_engine.py
"""

from __future__ import annotations

import http.server
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal, init_db  # noqa: E402
from atlas_kernel.fabric import recipes  # noqa: E402
from atlas_kernel.opportunity import (  # noqa: E402
    detect,
    extractors,
    ranking,
    scan,
)
from atlas_kernel.opportunity.discovery import DiscoveryState  # noqa: E402
from atlas_kernel.opportunity.models import Evidence, EvidenceKind  # noqa: E402
from atlas_kernel.opportunity.repository import OpportunityRepository  # noqa: E402

TENANT = "tenant-opportunity-proof"
MARK = "OppProof"

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


#: Two dentists: one OSM records a website for, one it does not. The second is
#: the interesting case — "no website in OSM" is a fact about OSM.
OVERPASS = {"elements": [
    {"type": "node", "id": 9001, "tags": {
        "name": f"{MARK} Marina Dental", "amenity": "dentist",
        "addr:city": "Dubai", "contact:website": "https://oppproof-marina.example"}},
    {"type": "node", "id": 9002, "tags": {
        "name": f"{MARK} Jumeirah Smile", "healthcare": "dentist",
        "addr:city": "Dubai"}},
    # Unnamed: cannot be written to or researched, must be skipped.
    {"type": "node", "id": 9003, "tags": {"amenity": "dentist"}},
]}


class Fixture(http.server.BaseHTTPRequestHandler):
    def do_GET(self):                                   # noqa: N802 - stdlib
        raw = json.dumps(OVERPASS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):                          # noqa: A003 - stdlib
        return


def clean() -> None:
    with SessionLocal() as session:
        session.execute(text(
            "DELETE FROM atlas_signals WHERE business_id IN "
            "(SELECT id FROM atlas_businesses WHERE name LIKE :m)"),
            {"m": f"{MARK} %"})
        session.execute(text(
            "DELETE FROM atlas_sightings WHERE name LIKE :m"), {"m": f"{MARK} %"})
        session.execute(text(
            "DELETE FROM atlas_businesses WHERE name LIKE :m"), {"m": f"{MARK} %"})
        session.commit()


def an_evidence(port: int) -> Evidence:
    """What the fetch step records, in the shape the crawler produces."""
    from atlas_kernel.opportunity.crawler import evidence_from
    from atlas_kernel.research.net import Fetcher

    url = f"http://127.0.0.1:{port}/api/interpreter"
    # `check_addresses=False` is the documented escape for a caller supplying
    # its own target: a loopback fixture is precisely what the guard refuses,
    # and the guard is exercised for real below.
    fetcher = Fetcher(f"http://127.0.0.1:{port}", check_addresses=False)
    page = fetcher.get(url, enforce_robots=False)
    return evidence_from(page, detector="recipe:http-fetch")


# ------------------------------------------------------ extract and remember

def the_chain(port: int) -> tuple[list, list]:
    evidence = an_evidence(port)
    check("the fetch recorded a body extraction can read",
          bool(evidence.observed.get("body"))
          and not evidence.observed.get("body_truncated"),
          f"{len(evidence.observed.get('body', ''))} bytes")

    found = extractors.extract_overpass(evidence)
    check("EXTRACT: every named element, and only the named ones",
          len(found) == 2, f"{len(found)} of 3 elements")
    check("...an unnamed element is skipped rather than given a blank name",
          all(e.fields.get("name") for e in found))
    check("...each extraction is traceable to the evidence it came from",
          all(e.evidence_fingerprint == evidence.fingerprint for e in found))
    check("...and only declared fields appear",
          all(set(e.fields) <= set(extractors.OPENSTREETMAP.produces)
              for e in found),
          str(extractors.OPENSTREETMAP.produces))

    with_site = next(e for e in found if "Marina" in e.fields["name"])
    without = next(e for e in found if "Jumeirah" in e.fields["name"])
    check("A MISSING TAG IS 'ABSENT IN SOURCE', NOT 'HAS NO WEBSITE'",
          without.absent_in_source("source_url")
          and not with_site.absent_in_source("source_url"))
    check("...and a field nobody looked for is NOT_CONSULTED, not absent",
          without.presence["business_id"] is extractors.Presence.NOT_CONSULTED,
          without.presence["business_id"].value)

    sightings = [extractors.sighting_from(e, evidence, source="openstreetmap")
                 for e in found]
    check("...and extraction cannot manufacture novelty",
          all(s.novelty is None for s in sightings))

    repo = OpportunityRepository()
    first = scan.record(sightings, repository=repo, tenant=TENANT)
    check("IDENTIFY + CLASSIFY + REMEMBER: both are new to Qevik",
          len(first.new_to_qevik) == 2, f"{len(first.new_to_qevik)}")
    check("...and neither claims to be new to the world",
          all(not r.classification.claims_about_the_world
              for r in first.recorded))

    again = scan.record(sightings, repository=repo, tenant=TENANT)
    check("...a second scan creates no second business",
          {r.business.id for r in again.recorded}
          == {r.business.id for r in first.recorded})
    check("...and reports them KNOWN the second time",
          all(r.classification.state is DiscoveryState.KNOWN
              for r in again.recorded))
    return first.recorded, found


# ------------------------------------------------------ detect, rank, persist

def opportunities(recorded: list, extractions: list) -> list:
    signals = detect.from_pass(recorded, extractions, source="openstreetmap")
    kinds = {s.kind.value for s in signals}
    check("DETECT: a new business is an opportunity",
          "new_business" in kinds, str(sorted(kinds)))
    check("...and the one OSM records no website for is a second",
          "missing_service" in kinds)
    check("...but only for the business the source was silent about",
          sum(1 for s in signals if s.kind.value == "missing_service") == 1)

    for signal in signals:
        check(f"...{signal.kind.value} rests on evidence",
              all(o.evidence for o in signal.observations))
        check(f"...{signal.kind.value} keeps inference apart from observation",
              bool(signal.inferences)
              and all(i.confidence < 1.0 for i in signal.inferences))
        check(f"...{signal.kind.value} names the evidence its inference rests on",
              all(set(i.rests_on) <= {f for o in signal.observations
                                      for f in o.fingerprints}
                  for i in signal.inferences))

    web = next(s for s in signals if s.kind.value == "missing_service")
    check("THE SUGGESTED ACTION IS TO VERIFY, NOT TO SELL",
          "check whether" in web.actions[0].statement.lower(),
          web.actions[0].statement[:60])
    check("...and its inference admits the source may simply not list it",
          "does not list" in (web.inferences[0].would_be_wrong_if or ""),
          web.inferences[0].would_be_wrong_if[:60])

    scored = ranking.order(signals)
    check("RANK: deterministic and repeatable",
          [r.signal_id for r in scored]
          == [r.signal_id for r in ranking.order(list(reversed(signals)))],
          "two orderings of the same data differ")
    check("...every score shows its working",
          all(r.components and all(c.because for c in r.components)
              for r in scored))
    check("VALUE IS UNKNOWN AND CARRIES NO NUMBER",
          all(r.value_status == "UNKNOWN" and r.value_amount is None
              for r in scored))
    check("...and UNKNOWN is never rendered as zero",
          all(r.summary()["value"]["amount"] is None for r in scored))

    repo = OpportunityRepository()
    stored = sum(1 for r in scored
                 if repo.save_signal(next(s for s in signals
                                          if s.id == r.signal_id), r,
                                     tenant=TENANT))
    check("...and they persist", stored == len(scored), f"{stored} stored")
    return scored


def survives_restart(scored: list) -> None:
    """A new repository object over the same database."""
    fresh = OpportunityRepository()
    listed = fresh.open_signals(tenant=TENANT)
    check("OPPORTUNITIES SURVIVE A RECONNECTION",
          len(listed) >= len(scored), f"{len(listed)} listed")
    check("...best first", [row["score"] for row in listed]
          == sorted((row["score"] for row in listed), reverse=True))

    one = fresh.get_signal(listed[0]["id"], tenant=TENANT)
    check("...and each carries the evidence fingerprints it rests on",
          bool(one and one["evidence_fingerprints"]),
          str(one["evidence_fingerprints"])[:40] if one else "none")
    check("...with observation, inference and action still apart",
          bool(one) and {"observations", "inferences", "actions"}
          <= set(one["detail"]))
    check("...and the inference still labelled as one",
          one["detail"]["inferences"][0]["is_an_inference"] is True)
    check("...and the value still UNKNOWN with no amount",
          one["value"] == {"amount": None, "status": "UNKNOWN"},
          str(one["value"]))

    # Traceable all the way back to the bytes.
    business_id = listed[0]["business_id"]
    trail = fresh.sightings_for(business_id, tenant=TENANT)
    check("TRACEABLE: the opportunity's evidence is in the sighting trail",
          bool(trail) and any(
              piece["source"] for row in trail for piece in row["evidence"]),
          f"{len(trail)} sighting(s)")

    fingerprints = set(listed[0]["evidence_fingerprints"])
    from atlas_kernel.opportunity.models import Evidence as E
    stored_prints = {E.model_validate(piece).fingerprint
                     for row in trail for piece in row["evidence"]}
    check("...and the fingerprints match the stored evidence exactly",
          fingerprints <= stored_prints,
          f"{sorted(fingerprints)} vs {sorted(stored_prints)}")


# --------------------------------------------------------- negative controls

def the_dangerous_versions_fail() -> None:
    """Each of these is the version that would be wrong, asserted to fail."""
    from atlas_kernel.opportunity.signals import Inference, Observation, Signal

    ev = Evidence(kind=EvidenceKind.HTTP_RESPONSE, source="https://x.test/",
                  observed={"status": 200}, detector="control")
    observation = Observation(statement="one thing", scope="x", evidence=[ev])

    try:
        Signal(kind=detect.SignalKind.NEW_BUSINESS, observations=[observation],
               inferences=[Inference(statement="made up",
                                     rests_on=("no-such-print",),
                                     confidence=0.9)])
        check("an inference on evidence the signal lacks is refused", False,
              "it was accepted")
    except ValueError:
        check("an inference on evidence the signal lacks is refused", True)

    try:
        Signal(kind=detect.SignalKind.NEW_BUSINESS, observations=[observation],
               estimated_value=5000.0, value_status="UNKNOWN")
        check("a number labelled UNKNOWN is refused", False, "it was accepted")
    except ValueError:
        check("a number labelled UNKNOWN is refused", True)

    try:
        Signal(kind=detect.SignalKind.NEW_BUSINESS, observations=[observation],
               value_status="REPORTED")
        check("a status with no number is refused", False, "it was accepted")
    except ValueError:
        check("a status with no number is refused", True)

    # The extractor pointed at the wrong shape.
    html = Evidence(kind=EvidenceKind.HTML_CONTENT, source="https://x.test/",
                    observed={"content_type": "text/html", "body": "<html/>"},
                    detector="control")
    try:
        extractors.extract_overpass(html)
        check("a JSON extractor pointed at HTML refuses", False, "it read it")
    except extractors.ExtractionError:
        check("a JSON extractor pointed at HTML refuses", True)

    truncated = Evidence(
        kind=EvidenceKind.HTTP_RESPONSE, source="https://x.test/",
        observed={"content_type": "application/json", "body": "{}",
                  "body_truncated": True}, detector="control")
    try:
        extractors.extract_overpass(truncated)
        check("A TRUNCATED BODY IS REFUSED, NOT PARTIALLY READ", False,
              "it read the part that fitted")
    except extractors.ExtractionError:
        check("A TRUNCATED BODY IS REFUSED, NOT PARTIALLY READ", True)


def the_guard_is_still_enforced() -> None:
    from atlas_kernel.opportunity import crawler

    private = ["http://169.254.169.254/latest/meta-data/", "http://10.0.0.1/"]
    evidence, refused = crawler.fetch_steps(private, detector="control")
    check("SSRF protection is unweakened", not evidence and len(refused) == 2,
          f"{len(refused)} refused")
    check("...by the address guard",
          all(crawler.was_refused_by_the_guard(r) for r in refused))


def the_recipe_declares_the_extractor() -> None:
    found = recipes.get("discover-dubai-dental-osm")
    check("the discovery recipe names its extractor",
          found.extractor == "openstreetmap", found.extractor)
    check("...and the extractor is declared",
          extractors.get(found.extractor).source == "openstreetmap")
    check("...and a recipe naming an undeclared extractor is refused at import",
          _refuses_unknown_extractor())


def _refuses_unknown_extractor() -> bool:
    from atlas_kernel.fabric.agents import Capability
    try:
        recipes.validate(recipes.Recipe(
            id="bad", does="x", agent_id="researcher",
            capability=Capability.RESEARCH, extractor="invented",
            steps=(recipes.Step(tool="http-fetch",
                                command=("https://x.test/",), proves="p"),)))
    except recipes.RecipeRefused:
        return True
    return False


def main() -> int:
    print("opportunity engine — real database, controlled source\n")
    init_db()
    clean()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        print("the chain")
        recorded, extractions = the_chain(port)
        print("\nopportunity")
        scored = opportunities(recorded, extractions)
        print("\npersistence")
        survives_restart(scored)
        print("\nnegative controls")
        the_dangerous_versions_fail()
        the_guard_is_still_enforced()
        the_recipe_declares_the_extractor()
    finally:
        server.shutdown()
        clean()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
