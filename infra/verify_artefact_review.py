"""A delivered artefact, reviewed from the control plane. No SSH, no git.

The milestone this proves: everything a person needs to judge a delivery — the
files, what they answer, what authorised them, what carried them out — reaches
a browser, and the decision they make is durable.

Real Postgres, a real commit made by the real worker, the real FastAPI app.
Each boundary is attempted before it is claimed.

    python3 infra/verify_artefact_review.py
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
from atlas_kernel.opportunity.repository import (  # noqa: E402
    REVIEW_DECISIONS,
    NotApprovable,
    OpportunityRepository,
)

MARK = "ReviewProof"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


init_db()
repo = OpportunityRepository()
scratch = Path(tempfile.mkdtemp(prefix="qevik-review-"))


def a_commit(mission_id: str, files: dict[str, str]) -> Path:
    """A scratch clone holding one mission's delivery, the way the worker leaves
    it: committed to the mission branch, with no worktree."""
    repository = scratch / mission_id / "repo"
    (repository / "artefact").mkdir(parents=True)
    for name, body in files.items():
        (repository / "artefact" / name).write_text(body, encoding="utf-8")
    (repository / ".qevik-scratch").write_text("marker\n", encoding="utf-8")
    run = lambda *a: subprocess.run(["git", "-C", str(repository), *a],  # noqa: E731
                                    capture_output=True, text=True, check=True)
    run("init", "-q", "-b", "base")
    run("config", "user.email", "worker@qevik.local")
    run("config", "user.name", "worker")
    # A base commit first, so `base` is a real branch to return to. Without one
    # it is unborn and the checkout at the end fails — which is also why the
    # real scratch clone always has the origin's history behind it.
    run("add", ".qevik-scratch")
    run("commit", "-q", "-m", "scratch")
    run("checkout", "-q", "-b", artefact.branch_of(mission_id))
    run("add", "-A")
    run("commit", "-q", "-m", f"delivery for {mission_id}")
    run("checkout", "-q", "base")
    # `git checkout base` already removed the artefact from the working tree —
    # it belongs to the other branch. That is exactly the state the worker
    # leaves behind, and the reason this reads from the commit at all.
    assert not (repository / "artefact").exists(), (
        "the fixture must reproduce the real state: artefact in the commit, "
        "not in the working tree")
    return repository


MISSION = "mission-reviewproof01"
PAGE = "<!doctype html><html><head><title>Probe Dental</title></head><body><h1>Probe Dental</h1></body></html>"
repository = a_commit(MISSION, {
    "index.html": PAGE,
    "provenance.json": '{"mode":"modify","addresses":["a page that loads quickly"],'
                       '"not_published_for_want_of_a_source":["email"]}',
})

print("\n-- reading the artefact out of the commit ----------------------------")
found = artefact.files(MISSION, str(repository), scratch=scratch)
check("the delivered files are listed", len(found) == 2,
      ", ".join(e.path for e in found))
check("...and the workspace's own marker is not among them",
      not any(e.path.endswith(".qevik-scratch") for e in found),
      "only what the delivery produced is artefact")
check("...each carrying the object id it was read at",
      all(len(e.blob) >= 7 for e in found))
check("a file reads back byte for byte",
      artefact.read(MISSION, str(repository), "artefact/index.html",
                    scratch=scratch) == PAGE)
check("the provenance is parsed",
      artefact.provenance(MISSION, str(repository),
                          scratch=scratch).get("mode") == "modify")
check("the commit is identified",
      len(artefact.commit_of(MISSION, str(repository), scratch=scratch)) == 40)
check("...and it is read with no artefact in the working tree",
      not (repository / "artefact").exists(),
      "the object store, not the directory — which is all the worker leaves")

print("\n-- what the reader refuses ------------------------------------------")
for path, why in (
        ("../../etc/passwd", "a traversal"),
        (".qevik-scratch", "a file outside the artefact"),
        ("artefact/../../../etc/passwd", "a traversal wearing the prefix"),
        ("artefact/nothing.html", "a file not in the commit")):
    try:
        artefact.read(MISSION, str(repository), path, scratch=scratch)
        check(f"refused: {why}", False, f"{path!r} was returned")
    except artefact.Unreadable as refused:
        check(f"refused: {why}", True, str(refused)[:56])

check("NEGATIVE CONTROL: the real path is returned",
      artefact.read(MISSION, str(repository), "artefact/index.html",
                    scratch=scratch).startswith("<!doctype"))

outside = Path(tempfile.mkdtemp(prefix="qevik-elsewhere-"))
try:
    artefact.files(MISSION, str(outside), scratch=scratch)
    check("a repository outside the scratch root is refused", False)
except artefact.Unreadable as refused:
    check("a repository outside the scratch root is refused", True,
          str(refused)[:56])

try:
    artefact._git(repository, "fetch", "origin")
    check("a git subcommand that is not read-only is refused", False)
except artefact.Unreadable as refused:
    check("a git subcommand that is not read-only is refused", True,
          str(refused)[:56])
check("NEGATIVE CONTROL: the two read-only ones are permitted",
      artefact.READABLE == {"ls-tree", "show"}, str(sorted(artefact.READABLE)))

big = a_commit("mission-reviewbig01", {"huge.html": "x" * (artefact.MAX_BYTES + 10)})
try:
    artefact.read("mission-reviewbig01", str(big), "artefact/huge.html",
                  scratch=scratch)
    check("a file over the cap is refused rather than truncated", False)
except artefact.Unreadable as refused:
    check("a file over the cap is refused rather than truncated", True,
          str(refused)[:60])

print("\n-- the decision is durable -------------------------------------------")
with SessionLocal() as session:
    session.execute(text("DELETE FROM atlas_business_events "
                         "WHERE detail->>'mission_id' LIKE :m"),
                    {"m": "mission-reviewproof%"})
    session.commit()

commit = artefact.commit_of(MISSION, str(repository), scratch=scratch)
recorded = repo.record_review(mission_id=MISSION, business_id=f"biz-{MARK}",
                              signal_id="sig-reviewproof", decision="accepted",
                              actor="ayoub", note="reads well", commit=commit)
check("a decision is recorded", recorded["decision"] == "accepted")
check("...naming who made it", recorded["actor"] == "ayoub")
check("...and the exact artefact they were looking at",
      recorded["commit"] == commit, commit[:12])

for bad, why in (("maybe", "a decision nobody declared"),
                 ("accepted", "a decision nobody signed")):
    try:
        repo.record_review(mission_id=MISSION, business_id="b",
                           signal_id="s", decision=bad,
                           actor="" if bad == "accepted" else "ayoub")
        check(f"refused: {why}", False, "it was accepted")
    except NotApprovable as refused:
        check(f"refused: {why}", True, str(refused)[:56])

check("the decisions are a closed set",
      REVIEW_DECISIONS == {"accepted", "rejected"}, str(sorted(REVIEW_DECISIONS)))

repo.record_review(mission_id=MISSION, business_id=f"biz-{MARK}",
                   signal_id="sig-reviewproof", decision="rejected",
                   actor="ayoub", note="changed my mind", commit=commit)
history = repo.reviews_for(MISSION)
check("changing your mind is two decisions, not one rewritten",
      [r["decision"] for r in history] == ["accepted", "rejected"],
      str([r["decision"] for r in history]))
check("...oldest first, so the sequence reads as it happened",
      history[0]["at"] <= history[1]["at"])

fresh = OpportunityRepository().reviews_for(MISSION)
check("a new process reads the same decisions", len(fresh) == 2,
      "durable, not held in the surface that made them")

print("\n-- the branch moves; the decision does not ----------------------------")
# A mission branch can be rebuilt — a retry, a re-run, somebody committing by
# hand. If a review named only the branch, "accepted" would silently come to
# mean whatever is on it now, and the acceptance of one artefact would be
# carried over to a different one nobody looked at.
(repository / "artefact").mkdir(exist_ok=True)
subprocess.run(["git", "-C", str(repository), "checkout", "-q",
                artefact.branch_of(MISSION)], check=True)
(repository / "artefact" / "index.html").write_text(
    "<html><body>something else entirely</body></html>", encoding="utf-8")
subprocess.run(["git", "-C", str(repository), "add", "-A"], check=True)
subprocess.run(["git", "-C", str(repository), "commit", "-q", "-m", "rebuilt"],
               check=True)
subprocess.run(["git", "-C", str(repository), "checkout", "-q", "base"],
               check=True)

moved = artefact.commit_of(MISSION, str(repository), scratch=scratch)
check("the branch now points somewhere else", moved != commit,
      f"{commit[:10]} → {moved[:10]}")
after = OpportunityRepository().reviews_for(MISSION)
check("the recorded decisions still name the commit that was inspected",
      all(r["commit"] == commit for r in after),
      f"all {len(after)} still at {commit[:10]}")
check("...so an acceptance cannot be inherited by an artefact nobody saw",
      after[0]["commit"] != moved)
check("NEGATIVE CONTROL: the new commit really does hold different bytes",
      "something else entirely" in artefact.read(
          MISSION, str(repository), "artefact/index.html", scratch=scratch))

print("\n-- customer markup is handed back as data ---------------------------")
# Whether it can *execute* is a property of the surface, not of this reader, and
# is proved where it lives: `verify_console_logic.mjs` records which DOM
# property the console writes it to. What is provable here is that the reader
# returns it verbatim as a string, for something else to render as text.
hostile = a_commit("mission-reviewxss01", {
    "index.html": "<script>window.__ran = true</script><img src=x onerror=alert(1)>",
})
body = artefact.read("mission-reviewxss01", str(hostile), "artefact/index.html",
                     scratch=scratch)
check("hostile markup is returned verbatim, not sanitised into a lie",
      body.startswith("<script>"),
      "a reviewer judging a page must see what it actually contains")
check("...and it is a value the route serialises into JSON, never a document",
      isinstance(body, str))

with SessionLocal() as session:
    session.execute(text("DELETE FROM atlas_business_events "
                         "WHERE detail->>'mission_id' LIKE :m"),
                    {"m": "mission-reviewproof%"})
    session.commit()

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
for name in FAILED:
    print(f"  FAILED  {name}")
sys.exit(1 if FAILED else 0)
