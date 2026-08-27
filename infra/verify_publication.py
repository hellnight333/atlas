"""An authorised publication, and everything it refuses.

The milestone this proves: an accepted artefact reaches the public only when a
person separately says so, and what reaches it is exactly the bytes they named.

Real Postgres, real commits, the real target writing to a real directory served
by a real HTTP server. Every refusal is attempted before it is claimed.

    python3 infra/verify_publication.py
"""

from __future__ import annotations

import http.server
import subprocess
import sys
import tempfile
import threading
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal, init_db  # noqa: E402
from atlas_kernel.fabric import recipes  # noqa: E402
from atlas_kernel.fabric.agents import Registry  # noqa: E402
from atlas_kernel.fabric.recipes import Recipe, RecipeRefused, Step  # noqa: E402
from atlas_kernel.fabric.tools import for_agent  # noqa: E402
from atlas_kernel.mission import artefact, publication  # noqa: E402
from atlas_kernel.opportunity.models import Business  # noqa: E402
from atlas_kernel.opportunity.repository import (  # noqa: E402
    NotApprovable,
    OpportunityRepository,
)

MARK = "PubProof"
TENANT = "tenant-publication-proof"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


init_db()
repo = OpportunityRepository()
scratch = Path(tempfile.mkdtemp(prefix="qevik-pub-"))
sites = Path(tempfile.mkdtemp(prefix="qevik-sites-"))


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


MISSION = "mission-pubproof01"
PAGE = "<!doctype html><html><head><title>PubProof</title></head><body><h1>PubProof</h1></body></html>"


def a_commit(mission_id: str, body: str, *, on: Path | None = None) -> tuple[Path, str]:
    repository = on or (scratch / mission_id / "repo")
    fresh = on is None
    run = lambda *a: subprocess.run(["git", "-C", str(repository), *a],  # noqa: E731
                                    capture_output=True, text=True, check=True)
    # The branch is checked out **before** anything is written. Writing first
    # left untracked files in the way and git refused to switch rather than
    # clobber them — which is git being right and the fixture being wrong.
    if fresh:
        (repository / "artefact").mkdir(parents=True)
        (repository / ".qevik-scratch").write_text("marker\n", encoding="utf-8")
        run("init", "-q", "-b", "base")
        run("config", "user.email", "worker@qevik.local")
        run("config", "user.name", "worker")
        run("add", ".qevik-scratch")
        run("commit", "-q", "-m", "scratch")
        run("checkout", "-q", "-b", artefact.branch_of(mission_id))
    else:
        run("checkout", "-q", artefact.branch_of(mission_id))
    (repository / "artefact").mkdir(parents=True, exist_ok=True)
    (repository / "artefact" / "index.html").write_text(body, encoding="utf-8")
    (repository / "artefact" / "robots.txt").write_text(
        "User-agent: *\nDisallow: /\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "delivery")
    head = artefact.commit_of(mission_id, str(repository), scratch=scratch)
    run("checkout", "-q", "base")
    return repository, head


wipe()
business = repo.save_business(Business(id=f"biz-{MARK}aaaa", name=f"{MARK} Ltd",
                                       website="https://pubproof.example/"))
SIGNAL = f"sig-{MARK}aaaa"
with SessionLocal() as session:
    session.execute(text("""
        INSERT INTO atlas_signals (id, tenant_id, business_id, kind, source,
                                   scope, payload, evidence_fingerprints, score,
                                   value_status, needs_approval, state, detected_at)
        VALUES (:id, :t, :b, 'weak_web_presence', 'probe', 'https://pubproof.example/',
                :payload, '[]', 0.8, 'UNKNOWN', TRUE, 'approved', now())
    """), {"id": SIGNAL, "t": TENANT, "b": business.id,
           "payload": '{"actions": [{"capability": "offer-website", '
                      '"statement": "Offer a rebuilt website."}]}'})
    session.commit()

repository, COMMIT = a_commit(MISSION, PAGE)
SITE = publication.site_for(business.id)

print("\n-- the address is derived, never supplied -----------------------------")
check("a site id is derived from the business", SITE.startswith("site-"), SITE)
check("it is a bare key with no path in it",
      publication.SITE_ID.fullmatch(SITE) is not None)
for hostile in ("../../etc", "site-../../etc", "/srv/sites/other", "site-x/../y"):
    check(f"refused as an address: {hostile[:22]!r}",
          not publication.known(hostile, business_id=business.id))
check("NEGATIVE CONTROL: the derived one is accepted",
      publication.known(SITE, business_id=business.id))
check("the same business always gets the same address",
      publication.site_for(business.id) == SITE,
      "a moving address orphans every published version")

print("\n-- nothing is authorised by acceptance alone --------------------------")
try:
    repo.approve_publication(mission_id=MISSION, business_id=business.id,
                             signal_id=SIGNAL, commit=COMMIT, site_id=SITE,
                             actor="ayoub", tenant=TENANT)
    check("publishing an artefact nobody accepted is refused", False,
          "it was authorised")
except NotApprovable as refused:
    check("publishing an artefact nobody accepted is refused", True,
          str(refused)[:60])

repo.record_review(mission_id=MISSION, business_id=business.id,
                   signal_id=SIGNAL, decision="rejected", actor="ayoub",
                   commit=COMMIT)
try:
    repo.approve_publication(mission_id=MISSION, business_id=business.id,
                             signal_id=SIGNAL, commit=COMMIT, site_id=SITE,
                             actor="ayoub", tenant=TENANT)
    check("publishing a rejected artefact is refused", False)
except NotApprovable as refused:
    check("publishing a rejected artefact is refused", True, str(refused)[:60])

repo.record_review(mission_id=MISSION, business_id=business.id,
                   signal_id=SIGNAL, decision="accepted", actor="ayoub",
                   commit=COMMIT)
try:
    repo.approve_publication(mission_id=MISSION, business_id=business.id,
                             signal_id=SIGNAL, commit="0" * 40, site_id=SITE,
                             actor="ayoub", tenant=TENANT)
    check("publishing a different commit than the accepted one is refused",
          False)
except NotApprovable as refused:
    check("publishing a different commit than the accepted one is refused",
          True, str(refused)[:60])

try:
    repo.approve_publication(mission_id=MISSION, business_id=business.id,
                             signal_id=SIGNAL, commit="", site_id=SITE,
                             actor="ayoub", tenant=TENANT)
    check("an authorisation naming no commit is refused", False)
except NotApprovable as refused:
    check("an authorisation naming no commit is refused", True,
          str(refused)[:60])

approval = repo.approve_publication(
    mission_id=MISSION, business_id=business.id, signal_id=SIGNAL,
    commit=COMMIT, site_id=SITE, actor="ayoub", tenant=TENANT,
    note="reviewed and authorised")
check("NEGATIVE CONTROL: the accepted commit is authorised",
      approval["commit"] == COMMIT, COMMIT[:12])
check("the authorisation binds all five things",
      approval["mission_id"] == MISSION and approval["signal_id"] == SIGNAL
      and approval["commit"] == COMMIT and approval["site_id"] == SITE
      and approval["actor"] == "ayoub")

print("\n-- the publisher's capability ----------------------------------------")
publisher = Registry().get("site-publisher")
builder = Registry().get("website-builder")
check("the publisher holds exactly one tool",
      [t.id for t in for_agent(publisher)] == ["site-publish"])
check("...and it is not a shell",
      "shell" not in {t.id for t in for_agent(publisher)})
check("the builder gained nothing by publishing existing",
      [t.id for t in for_agent(builder)] == ["website-generator"],
      "no network tool reached the build agent")
check("the publish tool is declared irreversible",
      next(t for t in for_agent(publisher)).blast.value == "irreversible",
      "a page a stranger has read cannot be un-read")

for tool in ("shell", "http-fetch", "git-worktree"):
    try:
        recipes.validate(Recipe(id="probe", does="p", agent_id="site-publisher",
                                capability=publisher.capability,
                                publishes="offer-website",
                                steps=(Step(tool=tool, command=("x",),
                                            proves="p"),)))
        check(f"a publication recipe using {tool} is refused", False)
    except RecipeRefused as refused:
        check(f"a publication recipe using {tool} is refused", True,
              str(refused)[:50])

try:
    recipes.validate(Recipe(id="probe", does="p", agent_id="site-publisher",
                            capability=publisher.capability,
                            publishes="offer-website", delivers="offer-website",
                            steps=(Step(tool="site-publish", command=("x",),
                                        proves="p"),)))
    check("a recipe that both builds and publishes is refused", False)
except RecipeRefused as refused:
    check("a recipe that both builds and publishes is refused", True,
          str(refused)[:56])

check("NEGATIVE CONTROL: the real publication recipe validates",
      recipes.validate(recipes.get("publish-website")) is None)

print("\n-- what is published is the authorised commit -------------------------")
names = artefact.files_at(COMMIT, str(repository), scratch=scratch)
check("the authorised commit's files are readable by object id",
      names == ["artefact/index.html", "artefact/robots.txt"], str(names))
check("...and the workspace marker is not among them",
      not any(n.endswith(".qevik-scratch") for n in names))

for bad, why in ((artefact.branch_of(MISSION), "a branch name"),
                 ("HEAD", "a ref"),
                 ("../../etc", "a path")):
    try:
        artefact.files_at(bad, str(repository), scratch=scratch)
        check(f"refused as a commit: {why}", False, f"{bad!r} was accepted")
    except artefact.Unreadable as refused:
        check(f"refused as a commit: {why}", True, str(refused)[:48])

_repo, moved = a_commit(MISSION, "<html><body>rebuilt, nobody looked</body></html>",
                        on=repository)
check("the branch was rebuilt after the authorisation", moved != COMMIT,
      f"{COMMIT[:10]} → {moved[:10]}")
still = artefact.read_at(COMMIT, str(repository), "artefact/index.html",
                         scratch=scratch)
check("the authorised commit still holds the reviewed bytes",
      "PubProof" in still and "rebuilt" not in still)
check("NEGATIVE CONTROL: the branch head holds the new ones",
      "rebuilt" in artefact.read_at(moved, str(repository),
                                    "artefact/index.html", scratch=scratch))

print("\n-- the outward act, against a real server -----------------------------")
server = http.server.ThreadingHTTPServer(
    ("127.0.0.1", 0), partial(http.server.SimpleHTTPRequestHandler,
                              directory=str(sites)))
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_address[1]}"

from atlas_kernel.website.targets.public_host import PublicHostTarget  # noqa: E402

files = {name[len(artefact.PREFIX):]:
         artefact.read_at(COMMIT, str(repository), name, scratch=scratch)
         for name in names}
target = PublicHostTarget(sites, base_url=base, verify_on_promote=False)
version = target.publish(SITE, files)
url = target.promote(SITE, version.id)
check("the bundle was published and promoted", bool(version.id), url)

import urllib.request  # noqa: E402

served = urllib.request.urlopen(f"{base}/{SITE}/current/index.html",
                                timeout=10).read().decode()
check("a real HTTP request returns the published page",
      "PubProof" in served, f"{len(served)} bytes")
check("...and they are the reviewed bytes, not the rebuilt ones",
      "rebuilt" not in served,
      "changing the branch after approval changed nothing that went out")
check("robots.txt went out too, and disallows indexing",
      "Disallow: /" in urllib.request.urlopen(
          f"{base}/{SITE}/current/robots.txt", timeout=10).read().decode())
check("nothing was written outside the site's own directory",
      {p.name for p in sites.iterdir()} == {SITE},
      str(sorted(p.name for p in sites.iterdir())))
server.shutdown()

print("\n-- the source repository is untouched ---------------------------------")
check("the mission branch still points where it did",
      artefact.commit_of(MISSION, str(repository), scratch=scratch) == moved)
check("the repository has no remote, so nothing was pushed",
      subprocess.run(["git", "-C", str(repository), "remote"],
                     capture_output=True, text=True).stdout.strip() == "")
check("the branch is merged into nothing",
      subprocess.run(["git", "-C", str(repository), "branch", "--contains",
                      COMMIT], capture_output=True, text=True)
      .stdout.replace("*", "").split() == [artefact.branch_of(MISSION)])

wipe()
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
for name in FAILED:
    print(f"  FAILED  {name}")
sys.exit(1 if FAILED else 0)
