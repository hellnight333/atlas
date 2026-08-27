"""Accepted artefacts, as a queue derived from the decisions that made them.

The milestone this proves: an acceptance stops being an entry in a timeline
nobody reads and becomes work that is visibly waiting — without a second store,
a second approval, or any inference from mission status or branch state.

Real Postgres, real review records, the real query.

    python3 infra/verify_awaiting_publication.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal, init_db  # noqa: E402
from atlas_kernel.mission import artefact  # noqa: E402
from atlas_kernel.opportunity.models import Business  # noqa: E402
from atlas_kernel.opportunity.repository import (  # noqa: E402
    NotApprovable,
    OpportunityRepository,
)

MARK = "AwaitProof"
MINE = "tenant-awaiting-proof"
THEIRS = "tenant-somebody-else"

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


init_db()
repo = OpportunityRepository()
scratch = Path(tempfile.mkdtemp(prefix="qevik-await-"))


def wipe() -> None:
    with SessionLocal() as session:
        session.execute(text(
            "DELETE FROM atlas_business_events WHERE business_id LIKE :m"),
            {"m": f"biz-{MARK}%"})
        session.execute(text("DELETE FROM atlas_signals WHERE id LIKE :m"),
                        {"m": f"sig-{MARK}%"})
        session.execute(text("DELETE FROM atlas_businesses WHERE id LIKE :m"),
                        {"m": f"biz-{MARK}%"})
        session.commit()


def a_signal(suffix: str, tenant: str) -> tuple[str, str]:
    """A business and an opportunity, written the way the engine writes them."""
    business_id = f"biz-{MARK}{suffix}"
    signal_id = f"sig-{MARK}{suffix}"
    repo.save_business(Business(id=business_id, name=f"{MARK}{suffix} Ltd",
                                website=f"https://{MARK.lower()}{suffix.lower()}.example/"))
    with SessionLocal() as session:
        session.execute(text("""
            INSERT INTO atlas_signals (id, tenant_id, business_id, kind, source,
                                       scope, payload, evidence_fingerprints,
                                       score, value_status, needs_approval,
                                       state, detected_at)
            VALUES (:id, :tenant, :business, 'weak_web_presence', 'probe',
                    'offer-website: performance', '{}', '[]', 0.8, 'UNKNOWN',
                    TRUE, 'approved', now())
        """), {"id": signal_id, "tenant": tenant, "business": business_id})
        session.commit()
    return business_id, signal_id


def a_commit(mission_id: str, body: str) -> tuple[Path, str]:
    repository = scratch / mission_id / "repo"
    (repository / "artefact").mkdir(parents=True)
    (repository / "artefact" / "index.html").write_text(body, encoding="utf-8")
    (repository / ".qevik-scratch").write_text("marker\n", encoding="utf-8")
    run = lambda *a: subprocess.run(["git", "-C", str(repository), *a],  # noqa: E731
                                    capture_output=True, text=True, check=True)
    run("init", "-q", "-b", "base")
    run("config", "user.email", "worker@qevik.local")
    run("config", "user.name", "worker")
    run("add", ".qevik-scratch")
    run("commit", "-q", "-m", "scratch")
    run("checkout", "-q", "-b", artefact.branch_of(mission_id))
    run("add", "-A")
    run("commit", "-q", "-m", "delivery")
    run("checkout", "-q", "base")
    return repository, artefact.commit_of(mission_id, str(repository),
                                          scratch=scratch)


wipe()

# -- the cast ---------------------------------------------------------------
ACCEPTED = "mission-awaitproof-a"
REJECTED = "mission-awaitproof-b"
UNREVIEWED = "mission-awaitproof-c"
REVERSED = "mission-awaitproof-d"
OTHER_TENANT = "mission-awaitproof-e"

biz_a, sig_a = a_signal("A", MINE)
biz_b, sig_b = a_signal("B", MINE)
biz_c, sig_c = a_signal("C", MINE)
biz_d, sig_d = a_signal("D", MINE)
biz_e, sig_e = a_signal("E", THEIRS)

repo_a, commit_a = a_commit(ACCEPTED, "<html><body>accepted</body></html>")
repo_d, commit_d = a_commit(REVERSED, "<html><body>reversed</body></html>")

repo.record_review(mission_id=ACCEPTED, business_id=biz_a, signal_id=sig_a,
                   decision="accepted", actor="ayoub", commit=commit_a)
repo.record_review(mission_id=REJECTED, business_id=biz_b, signal_id=sig_b,
                   decision="rejected", actor="ayoub", commit="deadbeef" * 5)
# UNREVIEWED gets no decision at all.
repo.record_review(mission_id=REVERSED, business_id=biz_d, signal_id=sig_d,
                   decision="accepted", actor="ayoub", commit=commit_d)
repo.record_review(mission_id=REVERSED, business_id=biz_d, signal_id=sig_d,
                   decision="rejected", actor="ayoub", commit=commit_d,
                   note="looked again")
repo.record_review(mission_id=OTHER_TENANT, business_id=biz_e, signal_id=sig_e,
                   decision="accepted", actor="someone", commit="cafe" * 10)

print("\n-- what belongs in the queue ----------------------------------------")
queue = repo.awaiting_publication(tenant=MINE)
missions = [row["mission_id"] for row in queue]

check("an accepted artefact appears", ACCEPTED in missions, str(missions))
check("an artefact nobody reviewed does not", UNREVIEWED not in missions)
check("a rejected artefact does not", REJECTED not in missions)
check("an acceptance somebody later withdrew does not",
      REVERSED not in missions,
      "the latest decision wins, and it was rejected")
check("another tenant's accepted artefact is not visible",
      OTHER_TENANT not in missions, str(missions))
check("NEGATIVE CONTROL: it is visible to the tenant it belongs to",
      OTHER_TENANT in [r["mission_id"]
                       for r in repo.awaiting_publication(tenant=THEIRS)])
check("...and unscoped, the operator console sees both",
      {ACCEPTED, OTHER_TENANT} <= {r["mission_id"]
                                   for r in repo.awaiting_publication()})

row = next(r for r in queue if r["mission_id"] == ACCEPTED)
check("the row names the commit that was reviewed",
      row["commit"] == commit_a, commit_a[:12])
check("...the opportunity it came from", row["signal_id"] == sig_a)
check("...who accepted it and when",
      row["accepted_by"] == "ayoub" and bool(row["accepted_at"]))
check("...the business by name, not only by id",
      row["business_name"].startswith(MARK), row["business_name"])
check("it says plainly that nothing has happened to it yet",
      row["state"] == "AWAITING_PUBLICATION", row["state"])
check("no filesystem path is in the row",
      not any(isinstance(v, str) and v.startswith("/") for v in row.values()),
      "an operator deciding what goes out next does not need one")

print("\n-- reading it twice does not make it two ------------------------------")
again = repo.awaiting_publication(tenant=MINE)
check("a second read returns the same rows",
      [r["mission_id"] for r in again] == missions)
check("...and no entry was created by reading",
      len(again) == len(queue), f"{len(queue)} then {len(again)}")

# The real production case: three identical acceptances from three gate runs.
for _ in range(3):
    repo.record_review(mission_id=ACCEPTED, business_id=biz_a, signal_id=sig_a,
                       decision="accepted", actor="ayoub", commit=commit_a)
duplicated = repo.awaiting_publication(tenant=MINE)
check("four identical acceptances are one queue entry",
      [r["mission_id"] for r in duplicated].count(ACCEPTED) == 1,
      f"{len(repo.reviews_for(ACCEPTED))} decisions on the timeline")

print("\n-- the branch moves; the queue does not -------------------------------")
subprocess.run(["git", "-C", str(repo_a), "checkout", "-q",
                artefact.branch_of(ACCEPTED)], check=True)
(repo_a / "artefact" / "index.html").write_text(
    "<html><body>rebuilt, and nobody looked</body></html>", encoding="utf-8")
subprocess.run(["git", "-C", str(repo_a), "add", "-A"], check=True)
subprocess.run(["git", "-C", str(repo_a), "commit", "-q", "-m", "rebuilt"],
               check=True)
subprocess.run(["git", "-C", str(repo_a), "checkout", "-q", "base"], check=True)
moved = artefact.commit_of(ACCEPTED, str(repo_a), scratch=scratch)
check("the branch now points somewhere else", moved != commit_a,
      f"{commit_a[:10]} → {moved[:10]}")
after = next(r for r in repo.awaiting_publication(tenant=MINE)
             if r["mission_id"] == ACCEPTED)
check("the queue still presents the reviewed commit",
      after["commit"] == commit_a, commit_a[:12])
check("...not the one on the branch",
      after["commit"] != moved,
      "an acceptance cannot be inherited by an artefact nobody saw")

print("\n-- acceptance is read from decisions, never inferred ------------------")
source = (ROOT / "packages/kernel/atlas_kernel/opportunity/repository.py") \
    .read_text()
body = source[source.index("def awaiting_publication"):
              source.index("def reviews_for")]
for forbidden, why in (("atlas_missions", "mission status"),
                       ("ls-tree", "branch state"),
                       ("rev-parse", "branch state")):
    check(f"the queue does not consult {why}", forbidden not in body)
check("it reads the review events", "REVIEWED_EVENT" in body)
check("...and takes the latest per mission", "DISTINCT ON" in body)

print("\n-- ACCEPTED -> AWAITING_PUBLICATION -> PUBLISHED ----------------------")
# The three states, told apart from the timeline alone. Nothing below inspects a
# directory, a symlink, an HTTP status or a branch.
PUBLISHED_M = "mission-awaitproof-p"
biz_p, sig_p = a_signal("P", MINE)
repo_p, commit_p = a_commit(PUBLISHED_M, "<html><body>published</body></html>")
repo.record_review(mission_id=PUBLISHED_M, business_id=biz_p, signal_id=sig_p,
                   decision="accepted", actor="ayoub", commit=commit_p)

waiting = {r["mission_id"] for r in repo.awaiting_publication(tenant=MINE)}
check("accepted but not published: it waits", PUBLISHED_M in waiting)
check("...and says so", next(r["state"] for r in repo.awaiting_publication(
    tenant=MINE) if r["mission_id"] == PUBLISHED_M) == "AWAITING_PUBLICATION")

# An *authorisation* is not a publication. This is the distinction that decides
# whether the queue reports work as done because permission for it was given.
repo.approve_publication(mission_id=PUBLISHED_M, business_id=biz_p,
                         signal_id=sig_p, commit=commit_p,
                         site_id="site-probe", actor="ayoub", tenant=MINE)
check("authorised but not yet published: it still waits",
      PUBLISHED_M in {r["mission_id"]
                      for r in repo.awaiting_publication(tenant=MINE)},
      "permission to publish is not a publication")

recorded = repo.record_publication(
    mission_id=PUBLISHED_M, business_id=biz_p, signal_id=sig_p,
    commit=commit_p, site_id="site-probe",
    url="https://sites.qevik.ai/site-probe/", files=["index.html"],
    actor="recipe:publish-website", publication_mission="mission-pub-run-1",
    tenant=MINE)
check("the record binds the mission, opportunity, commit and site",
      recorded["mission_id"] == PUBLISHED_M
      and recorded["signal_id"] == sig_p
      and recorded["commit"] == commit_p
      and recorded["site_id"] == "site-probe")
check("...and which run put it there",
      recorded["publication_mission"] == "mission-pub-run-1")

after = {r["mission_id"] for r in repo.awaiting_publication(tenant=MINE)}
check("PUBLISHED: it leaves the queue", PUBLISHED_M not in after, str(sorted(after)))
check("NEGATIVE CONTROL: the accepted-only one is still there",
      ACCEPTED in after,
      "the filter removed the published one, not the queue")

for _ in range(3):
    repo.record_publication(
        mission_id=PUBLISHED_M, business_id=biz_p, signal_id=sig_p,
        commit=commit_p, site_id="site-probe",
        url="https://sites.qevik.ai/site-probe/", files=["index.html"],
        actor="recipe:publish-website", tenant=MINE)
check("duplicate publication records still mean one state",
      PUBLISHED_M not in {r["mission_id"]
                          for r in repo.awaiting_publication(tenant=MINE)}
      and len(repo.publications_for(PUBLISHED_M)) == 4,
      f"{len(repo.publications_for(PUBLISHED_M))} records, still absent once")

# A publication recorded against a *different* mission must not close this one.
repo.record_publication(mission_id="mission-somebody-else", business_id=biz_a,
                        signal_id=sig_a, commit=commit_a, site_id="site-other",
                        url="https://sites.qevik.ai/site-other/",
                        files=["index.html"], actor="probe", tenant=MINE)
check("a publication of another mission does not close this one",
      ACCEPTED in {r["mission_id"]
                   for r in repo.awaiting_publication(tenant=MINE)},
      "the queue is keyed on the mission whose artefact went out")

try:
    repo.record_publication(mission_id=PUBLISHED_M, business_id=biz_p,
                            signal_id=sig_p, commit="", site_id="site-probe",
                            url="u", files=[], actor="probe", tenant=MINE)
    check("a publication record naming no commit is refused", False)
except NotApprovable as refused:
    check("a publication record naming no commit is refused", True,
          str(refused)[:56])

print("\n-- the branch moves; the state does not -------------------------------")
subprocess.run(["git", "-C", str(repo_p), "checkout", "-q",
                artefact.branch_of(PUBLISHED_M)], check=True)
(repo_p / "artefact" / "index.html").write_text("<html>rebuilt</html>",
                                                encoding="utf-8")
subprocess.run(["git", "-C", str(repo_p), "add", "-A"], check=True)
subprocess.run(["git", "-C", str(repo_p), "commit", "-q", "-m", "rebuilt"],
               check=True)
subprocess.run(["git", "-C", str(repo_p), "checkout", "-q", "base"], check=True)
check("the branch moved after publication",
      artefact.commit_of(PUBLISHED_M, str(repo_p), scratch=scratch) != commit_p)
check("...and the mission is still published, not back in the queue",
      PUBLISHED_M not in {r["mission_id"]
                          for r in repo.awaiting_publication(tenant=MINE)})
check("...still naming the commit that actually went out",
      all(r["commit"] == commit_p for r in repo.publications_for(PUBLISHED_M)),
      commit_p[:12])

print("\n-- the state comes from the timeline, not from a machine --------------")
# The **calls it makes**, not the words it contains. Scanning for vocabulary
# flagged this function's own docstring — which says it consults no symlink —
# and the `min(int(limit), 200)` row cap. A checker that fails on a caveat
# explaining the property is a checker measuring prose.
import ast  # noqa: E402

tree = ast.parse(source)
function = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
                and node.name == "awaiting_publication")
code = ast.unparse(function)
if ast.get_docstring(function):
    code = code.replace(ast.get_docstring(function), "")

for forbidden, why in (("Path(", "the filesystem"), ("open(", "a file"),
                       ("subprocess", "a subprocess"), ("httpx", "HTTP"),
                       ("urllib", "HTTP"), ("os.", "the operating system"),
                       ("exists(", "whether something is on disk"),
                       ("readlink", "a symlink"), ("is_dir", "a directory")):
    check(f"the queue does not reach for {why}", forbidden not in code,
          "" if forbidden not in code else f"{forbidden!r} is called in it")
check("it reads the publication event", "PUBLISHED_EVENT" in code)
check("NEGATIVE CONTROL: the scan can see the calls it does make",
      "SessionLocal" in code and "get_business" in code,
      "so the absences above are absences and not a broken scan")

print("\n-- nothing leaves the system -----------------------------------------")
before_events = repo.reviews_for(ACCEPTED)
repo.awaiting_publication(tenant=MINE)
check("reading the queue writes no decision",
      len(repo.reviews_for(ACCEPTED)) == len(before_events),
      f"{len(before_events)} before and after")
check("the artefact commit is untouched by reading the queue",
      artefact.commit_of(ACCEPTED, str(repo_a), scratch=scratch) == moved)
remotes = subprocess.run(["git", "-C", str(repo_a), "remote"],
                         capture_output=True, text=True, check=False)
check("the repository still has no remote to push to",
      remotes.stdout.strip() == "", remotes.stdout.strip() or "none")

wipe()
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
for name in FAILED:
    print(f"  FAILED  {name}")
sys.exit(1 if FAILED else 0)
