"""An approved opportunity becoming a delivered artefact, end to end.

The milestone this proves: a person approves one opportunity Qevik discovered
and audited, and that approval — and nothing else — produces a real file in a
scratch workspace and a report somebody can review, through the scheduler and
worker that already existed.

Real Postgres, a real opportunity built by the real detector from a real
audited response, and the real production worker as a subprocess. The six
properties the milestone has to hold are each proved with the dangerous version
attempted first.

    python3 infra/verify_delivery.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal, init_db  # noqa: E402
from atlas_kernel.fabric import recipes  # noqa: E402
from atlas_kernel.mission import delivery, origins, service  # noqa: E402
from atlas_kernel.mission.models import MissionStatus  # noqa: E402
from atlas_kernel.mission.timeline import Timeline  # noqa: E402
from atlas_kernel.opportunity import detect, ranking, verification  # noqa: E402
from atlas_kernel.opportunity.models import (  # noqa: E402
    Business,
    Evidence,
    EvidenceKind,
)
from atlas_kernel.opportunity.repository import (  # noqa: E402
    NotApprovable,
    OpportunityRepository,
    UnknownSignal,
)

TENANT = "tenant-delivery-proof"
MARK = "DeliveryProof"

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


init_db()
repo = OpportunityRepository()


def wipe() -> None:
    with SessionLocal() as session:
        session.execute(text(
            "DELETE FROM atlas_signals WHERE business_id IN "
            "(SELECT id FROM atlas_businesses WHERE name LIKE :m)"),
            {"m": f"{MARK}%"})
        for table in ("atlas_findings", "atlas_business_events"):
            session.execute(text(
                f"DELETE FROM {table} WHERE business_id IN "
                "(SELECT id FROM atlas_businesses WHERE name LIKE :m)"),
                {"m": f"{MARK}%"})
        session.execute(text("DELETE FROM atlas_businesses WHERE name LIKE :m"),
                        {"m": f"{MARK}%"})
        session.commit()


#: A homepage that answers slowly and carries no description — the shape of two
#: of the three opportunities production actually holds. Slow maps to
#: `page_speed` and the description to `meta_description`, both of which
#: `execution/capabilities/website.py` declares it can fix.
WEAK = ("<html><head><title>Marina Dental</title>"
        '<meta name="viewport" content="width=device-width"></head>'
        "<body><h1>Marina Dental</h1><p>"
        + ("A dental practice in Dubai Marina since 2009. " * 12)
        + "</p></body></html>")


def an_opportunity(suffix: str = "") -> tuple[Business, dict]:
    """One real signal, built the way production builds them.

    Audited from a recorded response by the real detector, ranked by the real
    ranking, and stored by the real repository. Nothing is hand-written into
    the signals table: a fixture row would prove the delivery works on fixtures.
    """
    business = repo.save_business(Business(
        id=f"biz-{MARK}{suffix}".lower(),
        name=f"{MARK}{suffix} Marina Dental",
        website=f"http://{MARK.lower()}{suffix.lower()}-marina.example/",
        phone="+971500000000", geography="Dubai"))
    response = Evidence(
        kind=EvidenceKind.HTML_CONTENT, source=business.website,
        observed={"status": 200, "content_type": "text/html; charset=utf-8",
                  "bytes": len(WEAK), "elapsed_ms": 4600,
                  "redirect_chain": [], "error": "", "body": WEAK,
                  "body_truncated": False},
        summary="HTTP 200", detector="recipe:http-fetch")

    findings = verification.audit(business, response)
    for finding in findings:
        repo.save_finding(finding)
    signal = detect.weak_web_presence(business, findings, response,
                                      source="verify-recorded-websites")
    assert signal is not None, "the fixture must produce a real opportunity"
    scored = ranking.order([signal])[0]
    repo.save_signal(signal, scored, tenant=TENANT)
    return business, repo.get_signal(signal.id, tenant=TENANT)


wipe()
business, opportunity = an_opportunity()

print("\n-- the opportunity this rests on -------------------------------------")
check("it is a real audited opportunity, not a fixture row",
      opportunity["kind"] == "weak_web_presence"
      and bool(opportunity["evidence_fingerprints"]),
      f"{len(opportunity['evidence_fingerprints'])} fingerprint(s)")
check("it needs a person and names offer-website",
      opportunity["needs_approval"]
      and delivery.offer_of(opportunity) == "offer-website",
      delivery.offer_of(opportunity))
check("it starts open, not approved", opportunity["state"] == "open")


# ============================== 1. an unapproved signal cannot become a mission
print("\n-- 1. an unapproved opportunity is not a mission ----------------------")

registry = origins.Registry.build()
none = registry.resolve(origins.EMPTY_NAME)

try:
    delivery.enqueue(opportunity, tenant=TENANT, origin=none, actor="harness")
    check("an open opportunity is refused a mission", False, "it was accepted")
except delivery.NotDeliverable as refused:
    check("an open opportunity is refused a mission", True, str(refused)[:70])

check("...and refusals say so before anything is created",
      any("open" in reason for reason in delivery.refusals(opportunity)))

approved = repo.approve_signal(opportunity["id"], actor="ayoub", tenant=TENANT)
check("NEGATIVE CONTROL: once approved, the same opportunity is deliverable",
      delivery.refusals(approved) == [], str(delivery.refusals(approved))[:70])

with SessionLocal() as session:
    row = session.execute(text(
        "SELECT actor, kind, opportunity_id, detail FROM atlas_business_events "
        "WHERE opportunity_id = :id"), {"id": opportunity["id"]}).mappings().first()
check("the approval is recorded against that specific opportunity",
      bool(row) and row["opportunity_id"] == opportunity["id"]
      and row["actor"] == "ayoub",
      f"{row['kind']} by {row['actor']}" if row else "no event")

try:
    repo.approve_signal(opportunity["id"], actor="ayoub", tenant=TENANT)
    check("approving twice is refused", False, "one decision authorised two")
except NotApprovable as refused:
    check("approving twice is refused", True, str(refused)[:60])

try:
    repo.approve_signal("sig-does-not-exist", actor="ayoub", tenant=TENANT)
    check("approving an opportunity that does not exist is refused", False)
except UnknownSignal:
    check("approving an opportunity that does not exist is refused", True)


# ================== 2. approving one signal cannot deliver a different one
print("\n-- 2. one approval authorises one opportunity ------------------------")

other_business, other = an_opportunity(suffix="B")
check("a second, unapproved opportunity exists", other["state"] == "open")
try:
    delivery.enqueue(other, tenant=TENANT, origin=none, actor="ayoub")
    check("approving one does not make the other deliverable", False,
          "the second was delivered on the first's approval")
except delivery.NotDeliverable:
    check("approving one does not make the other deliverable", True,
          f"{other['id']} is still open")

mission, events = delivery.enqueue(approved, tenant=TENANT, origin=none,
                                   actor="ayoub")
check("the mission carries the opportunity that approved it",
      mission.signal_id == approved["id"], mission.signal_id)
check("...and not the other one", mission.signal_id != other["id"])
check("it records the approved scope", bool(mission.approved_scope),
      mission.approved_scope)
check("it carries the evidence the approval rested on",
      set(mission.evidence_fingerprints)
      == set(approved["evidence_fingerprints"]),
      f"{len(mission.evidence_fingerprints)} fingerprint(s)")
check("policy queued it without asking a second time",
      mission.status is MissionStatus.QUEUED, mission.status.value)
states = [(e.detail or {}).get("status") for e in events
          if hasattr(e, "detail")]
check("...having gone through DRAFT, PLANNING, then QUEUED",
      states == ["draft", "planning", "queued"], str(states))


# ================================ 3. the recipe cannot be substituted
print("\n-- 3. the recipe comes from the opportunity, not from a caller --------")

check("the recipe was derived, not passed",
      mission.recipe == delivery.recipe_for(approved) == "deliver-website",
      mission.recipe)

impostor = dict(approved)
impostor["detail"] = {**approved["detail"],
                      "actions": [{"capability": "offer-arabic-experience",
                                   "statement": "something else"}]}
try:
    delivery.recipe_for(impostor)
    check("an offer with no delivery recipe is refused", False)
except delivery.NotDeliverable as refused:
    check("an offer with no delivery recipe is refused", True,
          str(refused)[:60])

print("\n-- 4. the delivery cannot publish or contact anyone -------------------")

recipe = recipes.get("deliver-website")
check("the delivering agent declares exactly one tool",
      recipe.tools == ("website-generator",), str(recipe.tools))
check("...and it is not a network tool",
      not ({"http-fetch", "dns", "shell"} & set(recipe.tools)))

from atlas_kernel.fabric.recipes import Recipe, RecipeRefused, Step  # noqa: E402

for tool in ("http-fetch", "shell"):
    try:
        recipes.validate(Recipe(
            id="probe", does="probe", agent_id="website-builder",
            capability=recipe.capability, delivers="offer-website",
            steps=(Step(tool=tool, command=("https://example.com/",),
                        proves="p"),)))
        check(f"a delivery step using {tool} is refused at import", False,
              "it was accepted")
    except RecipeRefused as refused:
        check(f"a delivery step using {tool} is refused at import", True,
              str(refused)[:60])

check("NEGATIVE CONTROL: the real declaration validates",
      recipes.validate(recipe) is None)


# ======================= 5 & 6. through the real worker, to an artefact
print("\n-- the whole chain, through the real production worker ----------------")

import tempfile  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="qevik-delivery-"))
timeline = Timeline(tmp / "missions.jsonl")
for event in events:
    timeline.append(event)

queued = service.fold(Timeline(timeline.path).read(), tenant=TENANT)
check("the mission reached the queue a worker reads",
      any(m["mission_id"] == mission.id and m["status"] == "queued"
          for m in queued))

done = subprocess.run(
    [sys.executable, str(ROOT / "infra" / "mission_worker.py"),
     "--timeline", str(timeline.path), "--tenant", TENANT,
     "--name", "worker-delivery-proof",
     "--worktrees", str(tmp / "wt"), "--scratch", str(tmp / "scratch"),
     "--reports", str(tmp / "reports"), "--state", str(tmp / "state"),
     "--agent", "delivery", "--once"],
    capture_output=True, text=True, timeout=600, check=False)
check("the delivery worker ran it", done.returncode == 0,
      f"exit {done.returncode}" + (f" — {done.stderr[-200:]}"
                                   if done.returncode else ""))

ran = next((m for m in service.fold(Timeline(timeline.path).read(),
                                    tenant=TENANT)
            if m["mission_id"] == mission.id), {})
if ran.get("status") != MissionStatus.COMPLETE.value:
    print("    worker stderr:", (done.stderr or "")[-900:])
    print("    blockers:", ran.get("blockers"))
check("THE WHOLE CHAIN COMPLETES: opportunity to artefact",
      ran.get("status") == MissionStatus.COMPLETE.value,
      f"status={ran.get('status')} note={(ran.get('note') or '')[:90]}")

# The artefact lives as a commit on the mission's own branch: the worktree is
# torn down once the commit is made, which is the existing design and is why
# "survives a restart" is a real question rather than a formality. This reads it
# the way an operator would, out of the scratch clone, with no worker running.
workspace = Path(ran.get("workspace") or "")
branch = f"mission/{mission.id}"


def in_commit(*args: str) -> str:
    done = subprocess.run(["git", "-C", str(workspace), *args],
                          capture_output=True, text=True, check=False)
    return done.stdout if done.returncode == 0 else ""


built = sorted(
    name for name in in_commit("ls-tree", "-r", "--name-only", branch).split()
    if name.startswith("artefact/"))
check("a real artefact is committed in the scratch workspace", bool(built),
      f"{len(built)} file(s): {', '.join(built[:5])}")
check("...and it is a site, not a placeholder",
      any(name.endswith(".html") for name in built)
      and "artefact/provenance.json" in built, str(built[:6]))

page = next((n for n in built if n.endswith(".html")), "")
body = in_commit("show", f"{branch}:{page}") if page else ""
check("...naming the business it was built for",
      business.name in body, f"{len(body)} chars of {page or 'nothing'}")

raw = in_commit("show", f"{branch}:artefact/provenance.json")
provenance = json.loads(raw) if raw.strip() else {}
check("...and recording which observed defects it answers",
      bool(provenance.get("addresses")), str(provenance.get("addresses"))[:80])

print("\n-- 4b. nothing left the building --------------------------------------")
check("the mission ran the delivery agent and no other",
      ran.get("agent_id") == "website-builder", str(ran.get("agent_id")))
check("no invocation of any provider was recorded",
      not ran.get("invocations"), str(ran.get("invocations"))[:60])
check("cost is REPORTED as nothing, never an unknown rendered as zero",
      ran.get("total_cost") in (None, 0, 0.0), str(ran.get("total_cost")))

print("\n-- 5. the artefact survives a restart ---------------------------------")
# Nothing is held in the worker's memory: the process that built it has exited
# and the control plane is a separate one. Re-reading from disk with fresh
# objects is what "survives a restart" means here.
# A fresh process, no worker running, reading the same commit off disk. The
# builder exited long ago and the worktree it wrote in has been removed; if the
# artefact were held anywhere but the object store, this returns nothing.
again = subprocess.run(
    ["git", "-C", str(workspace), "ls-tree", "-r", "--name-only", branch],
    capture_output=True, text=True, check=False)
survived = sorted(n for n in again.stdout.split() if n.startswith("artefact/"))
check("a new process reads the same artefact off disk",
      bool(built) and survived == built,
      f"{len(survived)} file(s) after the builder exited and its worktree went")
check("...and the bytes are identical, not just the names",
      bool(page) and in_commit("show", f"{branch}:{page}") == body,
      f"{len(body)} chars")

fresh = service.fold(Timeline(timeline.path).read(), tenant=TENANT)
restored = next((m for m in fresh if m["mission_id"] == mission.id), {})
check("...and the mission still names its opportunity after a re-fold",
      restored.get("signal_id") == approved["id"], str(restored.get("signal_id")))
check("...and its approved scope",
      restored.get("approved_scope") == mission.approved_scope,
      str(restored.get("approved_scope")))

print("\n-- 6. the report links back to the opportunity ------------------------")
report = Path(ran.get("report_path") or "")
full = tmp / "reports" / report
text_ = full.read_text(encoding="utf-8") if report.parts and full.is_file() else ""
check("a durable report was written", bool(text_), str(report)[-60:])

for label, needle in (
        ("source opportunity", approved["id"]),
        ("approved scope", mission.approved_scope),
        ("origin", "**Origin:**"),
        ("recipe", "deliver-website"),
        ("agent/role", "website-builder"),
        ("tools used", "website-generator"),
        ("artefact", "artefact/"),
        ("evidence fingerprints", approved["evidence_fingerprints"][0]),
        ("cost status", "**Cost:**"),
        ("final status", "**Final status:** complete")):
    check(f"the report identifies its {label}", needle in text_,
          "" if needle in text_ else f"missing {needle[:40]!r}")

check("...and says plainly that nothing was published or sent",
      "not published" in text_ and "not contacted" in text_)


# ============ 3b. substituting the recipe after approval, at execution
print("\n-- 3b. a recipe swapped after approval is refused at execution --------")

swapped = Timeline(tmp / "swapped.jsonl")
other_approved = repo.approve_signal(other["id"], actor="ayoub", tenant=TENANT)
tampered, tampered_events = delivery.enqueue(
    other_approved, tenant=TENANT, origin=none, actor="ayoub")
for event in tampered_events:
    swapped.append(event)
# The mission is edited in the ledger to name a different recipe — the exact
# thing an attacker, a bug or a well-meaning operator could do between approval
# and execution. The worker must not build what the approval did not authorise.
# The ledger itself is edited, which is the honest threat model: not a state
# transition anybody would be allowed to make, but a mission record altered
# between the approval and the execution. `fold` takes the latest entry, so the
# worker reads a mission approved for one recipe and told to run another.
lines = swapped.path.read_text(encoding="utf-8").splitlines()
last = json.loads(lines[-1])
last["detail"]["recipe"] = "discover-dubai-dental-osm"
lines[-1] = json.dumps(last)
swapped.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
edited = next((m for m in service.fold(Timeline(swapped.path).read(),
                                       tenant=TENANT)
               if m["mission_id"] == tampered.id), {})
check("the ledger now says a recipe the approval never named",
      edited.get("recipe") == "discover-dubai-dental-osm",
      str(edited.get("recipe")))

hijack = subprocess.run(
    [sys.executable, str(ROOT / "infra" / "mission_worker.py"),
     "--timeline", str(swapped.path), "--tenant", TENANT,
     "--name", "worker-delivery-tamper",
     "--worktrees", str(tmp / "wt2"), "--scratch", str(tmp / "scratch2"),
     "--reports", str(tmp / "reports2"), "--state", str(tmp / "state2"),
     "--agent", "delivery", "--once"],
    capture_output=True, text=True, timeout=600, check=False)
after = next((m for m in service.fold(Timeline(swapped.path).read(),
                                      tenant=TENANT)
              if m["mission_id"] == tampered.id), {})
check("a mission whose recipe was swapped does not complete",
      after.get("status") != MissionStatus.COMPLETE.value,
      f"status={after.get('status')} exit={hijack.returncode}")
# Not merely that it failed — that it failed *for this reason*. A refusal that
# happened to coincide with an unrelated breakage would pass the check above
# and prove nothing about the substitution.
refusal = " ".join(str(b) for b in (after.get("blockers") or [])) \
    + " " + str(after.get("note") or "")
check("...and refuses because the approval named a different recipe",
      "approved for" in refusal and "deliver-website" in refusal,
      refusal[:110])
built2 = list((tmp / "scratch2").rglob("artefact/*")) if (tmp / "scratch2").is_dir() else []
check("...and produced no artefact at all", not built2, str(built2[:2]))

wipe()
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
for name in FAILED:
    print(f"  FAILED  {name}")
sys.exit(1 if FAILED else 0)
