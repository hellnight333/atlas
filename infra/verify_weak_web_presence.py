"""Website verification evidence into evidenced opportunities, end to end.

The milestone this proves: a verification mission fetched real homepages and
recorded what each server said; those recordings are now read by the same rules
a live inspection uses, and the defects they support become opportunities the
website offer can execute.

The interesting half is what the evidence is **not** allowed to support. Every
check below has a paired negative control, because "the audit refused to
conclude anything from a truncated body" is only worth reading next to proof
that the un-truncated version concludes plenty.

    python3 infra/verify_weak_web_presence.py
"""

from __future__ import annotations

import http.server
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from atlas_kernel.fabric import recipes  # noqa: E402
from atlas_kernel.fabric.recipes import Recipe, RecipeRefused, Step  # noqa: E402
from atlas_kernel.mission import toolrunner  # noqa: E402
from atlas_kernel.opportunity import detect, verification  # noqa: E402
from atlas_kernel.opportunity.crawler import BODY_KEPT  # noqa: E402
from atlas_kernel.opportunity.detectors.website import (  # noqa: E402
    SLOW_RESPONSE_SECONDS,
    THIN_CONTENT_CHARS,
    PageObservation,
    WebsiteDetector,
)
from atlas_kernel.opportunity.models import (  # noqa: E402
    Business,
    Evidence,
    EvidenceKind,
    FindingKind,
)
from atlas_kernel.opportunity.signals import Reach, SignalKind  # noqa: E402
from atlas_kernel.recommendation.offers import BY_ID  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


BUSINESS = Business(id="b-marina", name="Marina Dental",
                    website="http://marina-dental.example/")

#: A page with real defects: served over plain HTTP, no viewport, no
#: description, no structured data, and almost no text.
WEAK = ("<html><head><title>Marina Dental</title></head>"
        "<body><p>Call us.</p></body></html>")

#: The same page done properly. Used as the negative control for every content
#: finding: if the auditor reports defects on this, it is inventing them.
STRONG = (
    "<html><head><title>Marina Dental</title>"
    '<meta name="viewport" content="width=device-width">'
    '<meta name="description" content="A dental practice in Dubai Marina.">'
    '<script type="application/ld+json">{"@type":"Dentist"}</script>'
    "</head><body><h1>Marina Dental</h1><p>"
    + ("We have been treating patients in Dubai Marina since 2009. " * 20)
    + "</p></body></html>")


def http_evidence(*, url="http://marina-dental.example/", status=200,
                  body=WEAK, elapsed_ms=200, error="", truncated=False,
                  content_type="text/html; charset=utf-8", chain=(),
                  size=None, kind=EvidenceKind.HTML_CONTENT) -> Evidence:
    """Evidence shaped exactly as `crawler.evidence_from` writes it."""
    return Evidence(
        kind=kind, source=url,
        observed={"status": status, "content_type": content_type,
                  "bytes": len(body) if size is None else size,
                  "elapsed_ms": elapsed_ms, "redirect_chain": list(chain),
                  "error": error, "body": body, "body_truncated": truncated},
        summary=f"HTTP {status}" if not error else f"failed: {error}",
        detector="recipe:http-fetch")


def kinds(findings) -> set[str]:
    return {f.kind.value for f in findings}


# ===================================================== 1. the rules are shared
print("\n-- one set of rules, two ways in ------------------------------------")

class _Explodes:
    """A client that fails the test if the auditor ever tries to fetch."""

    def get(self, *a, **k):                       # pragma: no cover - must not run
        raise AssertionError("the audit fetched; it must only read evidence")

    def close(self):
        pass


audited = verification.audit(BUSINESS, http_evidence(),
                             detector=WebsiteDetector(client=_Explodes()))
check("the audit reads evidence and never fetches", bool(audited),
      f"{len(audited)} finding(s) with a client that would have raised")

live = WebsiteDetector().findings_from(BUSINESS, PageObservation(
    requested_url=BUSINESS.website, final_url=BUSINESS.website, status=200,
    content_type="text/html; charset=utf-8", elapsed_seconds=0.2,
    bytes=len(WEAK), body=WEAK, body_complete=True))
check("a stored response yields what a live inspection would",
      kinds(audited) == kinds(live), f"{sorted(kinds(audited))}")

check("the well-built page yields no content findings",
      not (kinds(verification.audit(BUSINESS, http_evidence(
          body=STRONG, url="https://marina-dental.example/")))
           & {"not_mobile_friendly", "missing_title",
              "missing_meta_description", "missing_h1",
              "no_structured_data", "thin_content"}),
      "negative control for every content rule")


# ============================================ 2. what evidence cannot support
print("\n-- a refusal is not a response --------------------------------------")

for why in ("address refused: 10.0.0.1 is private",
            "disallowed by robots.txt",
            "ConnectTimeout: timed out"):
    refused = http_evidence(status=0, body="", error=why)
    check(f"no finding from a fetch that did not happen: {why[:28]}",
          verification.audit(BUSINESS, refused) == [])

check("NEGATIVE CONTROL: the same address answering does produce findings",
      bool(verification.audit(BUSINESS, http_evidence(status=200))),
      "so the silence above is the refusal, not a broken auditor")

check("a 500 that really happened is a finding",
      "site_unreachable" in kinds(verification.audit(
          BUSINESS, http_evidence(status=500, body=""))))

print("\n-- a truncated body is not a short page ------------------------------")

long_body = ("<html><head><title>Marina</title>"
             '<meta name="viewport" content="width=device-width">'
             '<meta name="description" content="d">'
             "</head><body>" + ("x" * (BODY_KEPT)) + "</body></html>")
cut = verification.audit(BUSINESS, http_evidence(
    body=long_body[:BODY_KEPT], truncated=True, size=len(long_body)))
whole = verification.audit(BUSINESS, http_evidence(body=long_body[:BODY_KEPT],
                                                   truncated=False))
absent_rules = {"missing_h1", "no_structured_data", "thin_content"}
check("a truncated body supports no whole-document finding",
      not (kinds(cut) & absent_rules), f"{sorted(kinds(cut))}")
check("NEGATIVE CONTROL: the same bytes, marked complete, support them",
      bool(kinds(whole) & absent_rules), f"{sorted(kinds(whole) & absent_rules)}")

CONTENT_RULES = {"not_mobile_friendly", "missing_title",
                 "missing_meta_description", "missing_h1",
                 "no_structured_data", "thin_content"}

headless = "<div>no head here at all, and cut off mid-" + "y" * 500
check("a truncated body whose <head> never closed supports no content finding",
      not (kinds(verification.audit(BUSINESS, http_evidence(
          body=headless, truncated=True, size=999999))) & CONTENT_RULES),
      "the transport facts still hold: the scheme is not in the body")
check("NEGATIVE CONTROL: the same fragment, complete, is read",
      bool(kinds(verification.audit(BUSINESS, http_evidence(
          body=headless, truncated=False))) & CONTENT_RULES))

dropped = http_evidence(body="", size=9_000_000)
check("a body dropped for being enormous is not an empty page",
      not (kinds(verification.audit(BUSINESS, dropped)) & absent_rules),
      "bytes>0 with no body means unread, not blank")

print("\n-- evidence of the wrong kind ----------------------------------------")

check("DNS evidence supports no website finding",
      verification.audit(BUSINESS, Evidence(
          kind=EvidenceKind.DNS_RECORD, source="marina-dental.example",
          observed={"host": "marina-dental.example", "resolution": "resolved"},
          summary="resolved", detector="recipe:dns")) == [])
check("evidence with no status at all supports nothing",
      verification.audit(BUSINESS, Evidence(
          kind=EvidenceKind.HTTP_RESPONSE, source="http://x.example/",
          observed={"body": WEAK}, summary="?", detector="t")) == [])


# ================================================== 3. attribution and HTTPS
print("\n-- whose site was that -----------------------------------------------")

owners = {"http://marina-dental.example/": BUSINESS}
found = verification.audit_pass(owners, [http_evidence(
    url="http://someone-else.example/")])
check("a response no business claims is attributed to nobody", found == {},
      "an unmatched URL is not given to the nearest business")

redirected = verification.audit_pass(owners, [http_evidence(
    url="https://www.marina-dental.example/",
    chain=("http://marina-dental.example/",))])
check("a redirect still reaches the business that owns the address",
      list(redirected) == [BUSINESS.id])
check("and a site that redirects to https is not reported as plain HTTP",
      "no_https" not in kinds(redirected[BUSINESS.id]))
check("NEGATIVE CONTROL: one that stays on http is",
      "no_https" in kinds(verification.audit(BUSINESS, http_evidence())))


# ======================================================= 4. signals and offers
print("\n-- from findings to something sellable -------------------------------")

response = http_evidence(elapsed_ms=int(SLOW_RESPONSE_SECONDS * 1000) + 1500)
slow = verification.audit(BUSINESS, response)
signal = detect.weak_web_presence(BUSINESS, slow, response,
                                  source="verify-recorded-websites")
check("a slow, weak site becomes an opportunity", signal is not None)
check("filed as weak_web_presence", signal.kind is SignalKind.WEAK_WEB_PRESENCE)
check("every observation reaches back to the recorded response",
      all(response.fingerprint in o.fingerprints for o in signal.observations))
check("the inference is hedged and says what would refute it",
      signal.inferences[0].confidence < 1.0
      and bool(signal.inferences[0].would_be_wrong_if))
check("worth is UNKNOWN, not zero",
      signal.estimated_value is None and signal.value_status == "UNKNOWN")

action = signal.actions[0]
check("the action names offer-website", action.capability == "offer-website",
      action.capability)
check("and it needs a person because it leaves the building",
      action.reach is Reach.OUTWARD and action.needs_approval)

check("only what the offer declares it answers is claimed",
      set(detect.answerable(slow)) <= set(BY_ID["offer-website"].answers),
      f"{detect.answerable(slow)}")

cosmetic = [f for f in verification.audit(BUSINESS, http_evidence())
            if f.kind in {FindingKind.NO_STRUCTURED_DATA,
                          FindingKind.MISSING_META_DESCRIPTION}]
check("NEGATIVE CONTROL: defects no offer answers claim no offer",
      detect.answerable(cosmetic) == (),
      "a missing meta description is not a website sale")
quiet = detect.weak_web_presence(BUSINESS, cosmetic, response,
                                 source="verify-recorded-websites")
check("and their signal keeps its action inside Qevik",
      quiet is not None and quiet.actions[0].reach is Reach.INTERNAL)

one_note = [f for f in cosmetic if f.kind is FindingKind.NO_STRUCTURED_DATA]
check("a single low-severity finding raises no opportunity at all",
      detect.weak_web_presence(BUSINESS, one_note, response,
                               source="verify-recorded-websites") is None,
      f"below WORTH_RAISING={detect.WORTH_RAISING}")
check("no findings, no signal",
      detect.weak_web_presence(BUSINESS, [], response, source="s") is None)


# ============================================== 5. the declaration is enforced
print("\n-- the audit is a key, not a decision --------------------------------")

recipe = recipes.get("verify-recorded-websites")
check("the verification recipe declares an audit", recipe.audit == "website")
check("and it appears in what the recipe reports about itself",
      recipe.summary().get("audit") == "website")

for bad, why in ((dict(audit="whatever-i-like",
                       targets_from="business_websites"),
                  "an audit nobody declared"),
                 (dict(audit="website", targets_from=""),
                  "an audit with no business to attribute to")):
    try:
        recipes.validate(Recipe(
            id="probe", does="probe", agent_id="researcher",
            capability=recipe.capability,
            steps=(Step(tool="http-fetch", command=("TARGETS",),
                        proves="p"),), **bad))
        check(f"refused: {why}", False, "it was accepted")
    except RecipeRefused as refusal:
        check(f"refused: {why}", True, str(refusal)[:60])

check("NEGATIVE CONTROL: the real declaration validates",
      recipes.validate(recipe) is None)


# =================================================== 6. through the real agent
print("\n-- the whole chain, through the production tool agent -----------------")

class _Site(http.server.BaseHTTPRequestHandler):
    def do_GET(self):                              # noqa: N802
        body = WEAK.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):                     # noqa: A003
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), _Site)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_address[1]}/"
served = Business(id="b-local", name="Local Dental", website=url)


class _Memory:
    """A repository that answers the two questions verification asks."""

    def __init__(self):
        self.saved = []

    def businesses_by_website(self, *, limit, tenant=None):
        return {url: served}

    def save_signal(self, signal, scored, *, tenant=None):
        self.saved.append((signal, scored))
        return True


memory = _Memory()
agent = toolrunner.ToolAgent(recipe, repository=memory,
                             # loopback is exactly what the address guard
                             # refuses, and this fixture is the reason to say so
                             # out loud rather than to reach past it silently.
                             check_addresses=False)
outcome = agent.implement(agent.plan("verify"), workspace_root=str(ROOT))
check("the mission fetched the site", outcome.evidence_count >= 1,
      outcome.summary)
check("the audit ran as a recorded step",
      any(s.tool == "audit" for s in agent.result.steps),
      next((s.detail for s in agent.result.steps if s.tool == "audit"), ""))
check("findings were attributed to the right business",
      list(agent.audited) == [served.id], str(list(agent.audited)))
check("an opportunity was ranked and stored", len(memory.saved) == 1)
if memory.saved:
    stored, scored = memory.saved[0]
    check("stored as weak_web_presence",
          stored.kind is SignalKind.WEAK_WEB_PRESENCE)
    check("its score is a number somebody can argue with",
          0.0 <= scored.score <= 1.0, f"score {scored.score:.3f}")
    check("it carries the fetch this mission actually made",
          any(p.detector == "recipe:http-fetch"
              for o in stored.observations for p in o.evidence))
server.shutdown()

# ================================================ 7. the backlog actually moves
print("\n-- the rotation, against real SQL -------------------------------------")

from atlas_kernel.db import SessionLocal, init_db  # noqa: E402
from atlas_kernel.opportunity.models import BusinessEvent  # noqa: E402
from atlas_kernel.opportunity.repository import (  # noqa: E402
    VERIFIED_EVENT,
    OpportunityRepository,
)
from sqlalchemy import text  # noqa: E402

MARK = "WeakWebRotation"
init_db()
repo = OpportunityRepository()


def wipe():
    with SessionLocal() as session:
        session.execute(text(
            "DELETE FROM atlas_business_events WHERE business_id IN "
            "(SELECT id FROM atlas_businesses WHERE name LIKE :m)"),
            {"m": f"{MARK}%"})
        session.execute(text("DELETE FROM atlas_businesses WHERE name LIKE :m"),
                        {"m": f"{MARK}%"})
        session.commit()


wipe()
# This database holds hundreds of real rows, so the probe anchors itself to the
# front of the backlog rather than pretending to be alone in it: five sites,
# stamped as first seen in 2000, so they lead every never-verified row. Named
# so alphabetical and chronological order disagree — if the query still sorts by
# `website`, `vvv` leads and `zzz` is unreachable.
made = []
for offset, letter in enumerate("zyxwv"):
    made.append(repo.save_business(Business(
        id=f"rot-{letter}", name=f"{MARK} {letter}",
        website=f"https://{letter}{letter}{letter}-rot.example/")))
with SessionLocal() as session:
    session.execute(text(
        "UPDATE atlas_businesses SET first_seen_at = :t WHERE name LIKE :m"),
        {"t": "2000-01-01T00:00:00+00:00", "m": f"{MARK}%"})
    session.commit()

MINE = {b.website for b in made}


def offered(limit=5):
    """Just the probe's own sites, in the order the real method returned them."""
    return [u for u in repo.businesses_by_website(limit=limit) if u in MINE]


first = offered()
check("all five never-verified sites are offered", len(first) == 5, str(first))
check("NEGATIVE CONTROL: alphabetical order would have led with vvv",
      bool(first) and not first[0].startswith("https://vvv"),
      f"led with {first[0]}" if first
      else "nothing was offered — the old query sorted by website and these "
           "sites sit behind every other row in the table")

for business in made[:3]:
    repo.record_event(BusinessEvent(business_id=business.id,
                                    kind=VERIFIED_EVENT, actor="probe"))

after = offered()
check("a verified site drops behind every site never tried",
      set(after) == {b.website for b in made[3:]},
      f"still offered: {sorted(after)}")
check("the backlog advanced rather than repeating itself",
      set(after) != set(first), "the bug this replaced re-read the same set")

for business in made[3:]:
    repo.record_event(BusinessEvent(business_id=business.id,
                                    kind=VERIFIED_EVENT, actor="probe"))
check("with every site verified, none is stuck at the head of the queue",
      offered() == [], "all five have had their turn")
third = repo.businesses_by_website(limit=5)
check("and the query still returns a full page of work",
      len(third) == 5, str(len(third)))
wipe()

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
for name in FAILED:
    print(f"  FAILED  {name}")
sys.exit(1 if FAILED else 0)
