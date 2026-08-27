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
