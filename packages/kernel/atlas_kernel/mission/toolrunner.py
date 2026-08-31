"""Carry out a recipe's steps through the tool each one declares.

The missing link. `fabric/recipes.py` declares what to do, `fabric/tools.py`
says what an agent may reach, `fabric/sandbox.py` contains what can be
contained — and nothing turned a declared step into an actual invocation unless
it happened to be a shell command. So the only executable recipes were the ones
that ran programs, which is why a discovery recipe existed and could not run.

## This is a dispatch table, not an engine

Sixteen lines of "which adapter handles this tool". There are no conditionals,
no retries, no branching and no ordering beyond the recipe's own. A step
succeeds or the sequence stops, exactly as `Adapter.run` already does for
commands. Anything more would be a workflow engine, and a workflow engine that a
model can aim is the thing the whole architecture refuses.

## What a model may and may not propose

A model may eventually say `recipe = "discover-uae-dental"`. That is a **key**,
and `recipes.get` either finds it or refuses. It may not say:

- a tool — the recipe's steps declare those, and the agent's registry entry
  bounds which are permitted at all;
- a URL — `permitted_urls()` is computed from the recipe, and a fetch of
  anything else is refused before a socket is opened;
- a step — recipes have no variables and are not assembled at runtime;
- an interpretation — this returns what the server said and nothing about what
  it means.

The refusals are here rather than in the caller because a caller can be
replaced by a model and this cannot.

## Evidence, not prose

Every step yields an `Evidence` record: the URL, the status, what was retrieved,
when, and a fingerprint. "This business is new" and "this is a good sales
opportunity" are downstream classifications made by
`opportunity/discovery.py` and `opportunity/signals.py` against Qevik's own
memory — neither of which this file can see, deliberately.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..fabric.agents import Agent, Registry, UnknownAgent
from ..fabric.recipes import Recipe
from ..fabric.tools import for_agent
from ..opportunity import crawler
from ..opportunity.models import Evidence, EvidenceKind
from .agents import AgentOutcome
from .models import Blocker, Plan, PlanStep

#: Tools carried out by running a command in the sandbox, via `Adapter`.
COMMANDS: frozenset[str] = frozenset({"shell", "filesystem", "git-worktree"})

#: Tools this runner knows how to invoke. A recipe naming anything else is
#: refused **before** the first step runs, rather than failing partway with a
#: sequence half-carried-out.
#:
#: **Derived** from `COMMANDS` rather than listed again. The two were written
#: out separately and disagreed: `git-worktree` was a command and not
#: dispatchable, so `_command` had a branch nothing could reach and a recipe
#: declaring it was refused for the wrong reason — "nothing knows how to invoke
#: it" when something did. Two hand-maintained sets that must agree are two sets
#: that will not.
#:
#: Deliberately short. A tool joins this when the adapter for it has been
#: written — not because the contract mentions it.
#: Tools invoked by something that understands them rather than by a process
#: launcher. Each name here has a branch in `run`, and adding a branch without
#: adding the name is how a delivery blocked itself for "nothing knows how to
#: invoke `website-generator`" while `_generate` sat directly below, waiting.
FETCHERS: frozenset[str] = frozenset({"http-fetch", "dns"})
GENERATORS: frozenset[str] = frozenset({"website-generator"})
#: The tools that make something public. One, and it is the only branch in
#: `run` that reaches the outside world on purpose.
PUBLISHERS: frozenset[str] = frozenset({"site-publish"})

#: Where sites live and what address serves them. Read from the environment so
#: the deployment configures them once, beside the worker's own paths.
SITES_ROOT_ENV = "QEVIK_SITES_ROOT"
SITES_BASE_URL_ENV = "QEVIK_SITES_BASE_URL"
DEFAULT_SITES_ROOT = "/srv/sites"

DISPATCHABLE: frozenset[str] = FETCHERS | GENERATORS | PUBLISHERS | COMMANDS


log = logging.getLogger(__name__)


class DeliveryRefused(RuntimeError):
    """This mission may not build what it says it will, and why."""


class NotDispatchable(RuntimeError):
    """A recipe this runner cannot carry out. Raised before anything runs."""


@dataclass
class Step:
    """One step's outcome: what was invoked, and what came back."""

    tool: str
    invoked: str
    proves: str
    passed: bool
    evidence: list[Evidence] = field(default_factory=list)
    #: Paths this step wrote, relative to the workspace. Empty for every step
    #: that observes rather than produces, which is most of them.
    files: tuple[str, ...] = ()
    detail: str = ""

    def summary(self) -> dict:
        return {"tool": self.tool, "invoked": self.invoked,
                "proves": self.proves, "passed": self.passed,
                "evidence": [e.fingerprint for e in self.evidence],
                "files": list(self.files),
                "detail": self.detail}


@dataclass
class Result:
    """Everything one recipe produced. Facts only."""

    recipe: str
    agent_id: str
    steps: list[Step] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.steps) and all(s.passed for s in self.steps)

    @property
    def evidence(self) -> list[Evidence]:
        return [piece for step in self.steps for piece in step.evidence]

    @property
    def tools_invoked(self) -> tuple[str, ...]:
        """Which tools were **actually** used, not which were permitted.

        The mission records this: "the role could have fetched" and "the role
        fetched" are different facts, and an audit wants the second.
        """
        return tuple(sorted({s.tool for s in self.steps}))

    def summary(self) -> dict:
        return {"recipe": self.recipe, "agent_id": self.agent_id,
                "passed": self.passed,
                "tools_invoked": list(self.tools_invoked),
                "evidence_count": len(self.evidence),
                "steps": [s.summary() for s in self.steps]}


def permitted_urls(recipe: Recipe, *, targets: list[str] | None = None
                   ) -> frozenset[str]:
    """Exactly the URLs this recipe may fetch. The allow-list.

    Computed from the declaration rather than passed in, so a caller — a model,
    a mission, an operator in a hurry — cannot widen it. A recipe that wants to
    fetch a second page is a recipe with a second step, reviewed in git.

    A recipe that declares `targets_from` gets those as well. They are not a
    parameter: they come from Qevik's **own memory**, so the only addresses
    reachable are ones an earlier evidenced sighting recorded. A model cannot
    widen the list because a model cannot write a sighting.
    """
    declared = frozenset(
        argument
        for step in recipe.steps if step.tool == "http-fetch"
        for argument in step.command)
    if recipe.targets_from and targets:
        return declared | frozenset(targets)
    return declared


def targets_map_for(recipe: Recipe, *, repository: object,
                    tenant: str | None = None,
                    limit: int | None = None) -> dict:
    """The addresses this recipe will fetch, and which business owns each.

    One call, so the set that is fetched and the set that can be attributed are
    the same set. Asking twice would be two bounded reads of a table that
    changes, and an audit that could not say whose site it had just read.

    Bounded. A verification recipe over a market that grows to ten thousand
    businesses would otherwise fetch ten thousand sites in one mission, which is
    neither polite to them nor recoverable for us.

    The bound is `SITES_A_NIGHT`, taken from where the queue is served rather
    than repeated here. This is the call that decides how much a production
    pass actually does — nothing passes `limit` — so a literal that merely
    happened to agree with the repository's was one edit away from moving the
    freshness report while the nightly pass carried on at the old rate.

    `None` rather than the constant itself as the default, because it is
    resolved inside: this package reaches the database lazily throughout, and a
    default evaluated at import time would pull the engine into every import of
    `mission`.
    """
    if recipe.targets_from != "business_websites" or repository is None:
        return {}
    from ..opportunity.repository import SITES_A_NIGHT

    found = repository.businesses_by_website(
        limit=SITES_A_NIGHT if limit is None else limit, tenant=tenant)
    log.info("%s: %d recorded website(s) to verify", recipe.id, len(found))
    return found


def targets_for(recipe: Recipe, *, repository: object,
                tenant: str | None = None,
                limit: int | None = None) -> list[str]:
    """Just the addresses, for a caller that does not need the owners."""
    return list(targets_map_for(recipe, repository=repository, tenant=tenant,
                                limit=limit))


def refusals(recipe: Recipe, agent: Agent) -> list[str]:
    """Every reason this recipe may not run, checked before it starts.

    All of them, not the first: an operator fixing one and rediscovering the
    next is a slow way to learn what a recipe needs.
    """
    found: list[str] = []
    declared = {tool.id for tool in for_agent(agent)}
    for tool in recipe.tools:
        if tool not in declared:
            found.append(
                f"{agent.id} does not declare {tool!r}, so this recipe may not "
                f"use it. Tool access comes from the registered role, never "
                f"from what an adapter happens to support.")
        elif tool not in DISPATCHABLE:
            found.append(
                f"{tool!r} is declared but nothing here knows how to invoke it. "
                f"Dispatchable: {', '.join(sorted(DISPATCHABLE))}.")
    return found


def run(recipe: Recipe, *, delivery: Delivery | None = None,
        publication: "Publication | None" = None,
        registry: Registry | None = None,
        workspace: Path | None = None,
        client: object | None = None,
        check_addresses: bool = True,
        targets: list[str] | None = None) -> Result:
    """Carry out every step, stopping at the first failure.

    Stopping matters for the same reason it does in `Adapter.run`: a later step
    run against the state a failed step left behind produces evidence about a
    situation that was never meant to exist.
    """
    try:
        agent = (registry or Registry()).get(recipe.agent_id)
    except UnknownAgent as unknown:
        raise NotDispatchable(
            f"{recipe.id} names agent {recipe.agent_id!r}, which no registry "
            "entry declares.") from unknown

    refused = refusals(recipe, agent)
    if refused:
        raise NotDispatchable(" ".join(refused))

    allowed = permitted_urls(recipe, targets=targets)
    outcome = Result(recipe=recipe.id, agent_id=agent.id)

    for step in recipe.steps:
        if step.tool == "http-fetch":
            # A targets step fetches what memory holds; a declared step fetches
            # what it names. Either way the allow-list decides, and it was
            # computed before the first request.
            placeholder = "TARGETS" in step.command
            if recipe.targets_from and placeholder and not targets:
                # Found in production the first night this ran. With no targets
                # the old expression fell through to `step.command` and the
                # fetcher was handed the literal word `TARGETS`, which it dutifully
                # tried to resolve as a hostname — a silent fallback from "what
                # memory holds" to "whatever the placeholder happens to say".
                #
                # A recipe whose targets come from memory and whose memory is
                # empty has nothing to do, and saying so is the only honest
                # answer. Not an error: an empty backlog is a normal night.
                outcome.steps.append(Step(
                    tool=step.tool, invoked=recipe.targets_from,
                    proves=step.proves, passed=False,
                    detail=(f"nothing to fetch: {recipe.targets_from} yielded no "
                            "addresses. A recipe that takes its targets from "
                            "memory does not fall back to the ones written in "
                            "its steps.")))
                continue
            wanted = (list(targets) if recipe.targets_from and targets
                      and placeholder else list(step.command))
            done = _fetch(step.model_copy(update={"command": tuple(wanted)}),
                          allowed=allowed, client=client,
                          check_addresses=check_addresses)
        elif step.tool == "dns":
            done = _resolve(step)
        elif step.tool == "website-generator":
            done = _generate(step, delivery=delivery, workspace=workspace)
        elif step.tool == "site-publish":
            done = _publish(step, publication=publication)
        elif step.tool in COMMANDS:
            done = _command(step, agent=agent, workspace=workspace,
                            registry=registry)
        else:                                     # pragma: no cover - refused above
            done = Step(tool=step.tool, invoked="", proves=step.proves,
                        passed=False, detail="not dispatchable")
        outcome.steps.append(done)
        if not done.passed:
            break
    return outcome


def _fetch(step, *, allowed: frozenset[str], client: object | None,
           check_addresses: bool) -> Step:
    """Fetch the URLs this step names, through the guarded fetcher.

    The allow-list check is first and is not a formality: it is what makes "a
    model proposed a recipe" safe. Everything after it is
    `opportunity/crawler.py`, which is `research/net.Fetcher` — budget, robots,
    and every resolved address on every redirect hop.
    """
    outside = [url for url in step.command if url not in allowed]
    if outside:
        return Step(tool=step.tool, invoked=", ".join(step.command),
                    proves=step.proves, passed=False,
                    detail=(f"refused: {', '.join(outside)} is not named by this "
                            "recipe. A fetch target comes from the declaration, "
                            "not from whatever asked for the run."))

    many = len(step.command) > 1
    evidence, refused = crawler.fetch_steps(
        list(step.command), detector=f"recipe:{step.tool}", client=client,
        check_addresses=check_addresses, per_target=many)

    # A refusal is evidence too — "this address was refused" is a fact. What it
    # does to the *step* depends on which kind it is.
    #
    # An address-guard refusal always fails the step: it means the recipe was
    # pointed somewhere it must not go, and that is worth stopping for. Anything
    # else — a site that would not answer, a robots policy — is one target out
    # of many, and failing the whole pass because the fortieth site was down
    # would throw away thirty-nine real results.
    blocked = [r for r in refused if crawler.was_refused_by_the_guard(r)]
    recorded = evidence + [r.as_evidence(f"recipe:{step.tool}") for r in refused]
    passed = bool(evidence) and not blocked
    detail = f"{len(evidence)} response(s) recorded"
    if refused:
        detail += f"; {len(refused)} not fetched"
    if blocked:
        detail = "; ".join(r.because for r in blocked)[:300]
    return Step(tool=step.tool, invoked=", ".join(step.command)[:200],
                proves=step.proves, passed=passed, evidence=recorded,
                detail=detail)


@dataclass(frozen=True)
class Publication:
    """One authorised publication, assembled before the recipe runs.

    The bytes are already here. They were read from the commit the
    authorisation named, by the read-only artefact reader, before anything
    outward could happen — so the tool that publishes has nothing to decide and
    no way to reach a different version.
    """

    site_id: str
    commit: str
    source_mission: str
    #: Relative path -> contents, exactly as the reviewed commit holds them.
    files: dict


@dataclass(frozen=True)
class Delivery:
    """Everything a build needs, assembled before the recipe runs.

    Assembled by `ToolAgent` from the approved opportunity and Qevik's own
    memory, and handed in — rather than looked up inside the step — so a
    delivery cannot reach for a business or a finding that the approval did not
    rest on. The step gets facts; it does not get a database.
    """

    offer_id: str
    business: object
    #: Observations in `execution/capabilities/website.py`'s own vocabulary.
    #: Only `not_found` for defects actually observed, and `present` for the
    #: site itself — which was fetched, or there would be no opportunity.
    research: dict


def _generate(step, *, delivery: Delivery | None, workspace: Path | None) -> Step:
    """Run the declared executor and write what it produced into the workspace.

    Refuses rather than improvises. No delivery context, no workspace, an offer
    the step names that the approval did not, or an executor nobody registered
    — each is a refusal with the reason, because every one of them is a way for
    a build to happen that nobody authorised in those terms.
    """
    from ..execution.capabilities import EXECUTORS, NothingToBuild

    wanted = step.command[0] if step.command else ""
    if delivery is None or workspace is None:
        return Step(tool=step.tool, invoked=wanted, proves=step.proves,
                    passed=False,
                    detail=("no approved opportunity and no workspace. A build "
                            "happens for somebody, on the strength of something "
                            "a person agreed to."))
    if wanted != delivery.offer_id:
        # The mission was approved to deliver one offer and its recipe names
        # another. Refused rather than reconciled: one of the two is wrong and
        # picking either would be choosing what somebody approved.
        return Step(tool=step.tool, invoked=wanted, proves=step.proves,
                    passed=False,
                    detail=(f"this step builds {wanted!r} and the approval was "
                            f"for {delivery.offer_id!r}."))
    executor = EXECUTORS.get(wanted)
    if executor is None:
        return Step(tool=step.tool, invoked=wanted, proves=step.proves,
                    passed=False,
                    detail=f"nothing is registered to execute {wanted!r}.")

    business = delivery.business
    try:
        files, provenance = executor(
            business_name=getattr(business, "name", ""),
            research=delivery.research, strengths=(), business=business)
    except NothingToBuild as nothing:
        # A finding, not a failure — and specifically not an artefact. The
        # executor refusing to build for a site that already does everything it
        # could add is the behaviour that makes its output mean something.
        return Step(tool=step.tool, invoked=wanted, proves=step.proves,
                    passed=False, detail=f"nothing to build: {nothing}"[:400])

    bundle = Path(workspace) / "artefact"
    bundle.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, body in sorted((files if isinstance(files, dict)
                              else {"index.html": files}).items()):
        target = bundle / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        written.append(str(target.relative_to(workspace)))

    (bundle / "provenance.json").write_text(
        json.dumps(provenance, indent=2, default=str), encoding="utf-8")
    written.append(str((bundle / "provenance.json").relative_to(workspace)))

    return Step(tool=step.tool, invoked=wanted, proves=step.proves, passed=True,
                files=tuple(written),
                detail=(f"{len(written)} file(s): {', '.join(written[:6])}"
                        + ("…" if len(written) > 6 else "")))


def _publish(step, *, publication: "Publication | None") -> Step:
    """Put an authorised bundle on the public host and prove it serves.

    The only outward act in this module. Everything it needs was decided
    before it ran: which bytes, which address, on whose authority. It has no
    parameters of its own and no way to reach a bundle, a version or a
    destination that an approval did not name.

    Publish and promote are separate calls because the target separates them,
    and the verification after promotion is what makes the outcome honest — a
    symlink swap is invisible from here and a 404 is what a visitor gets.
    """
    from ..website.targets.public_host import (
        DeploymentUnreachable,
        PublicHostTarget,
    )

    if publication is None:
        return Step(tool=step.tool, invoked="", proves=step.proves, passed=False,
                    detail=("nothing authorised a publication. An accepted "
                            "artefact is not an instruction to publish it."))
    if not publication.files:
        return Step(tool=step.tool, invoked=publication.site_id,
                    proves=step.proves, passed=False,
                    detail="the authorised commit holds no publishable files")

    base = os.environ.get(SITES_BASE_URL_ENV, "")
    root = os.environ.get(SITES_ROOT_ENV, DEFAULT_SITES_ROOT)
    if not base:
        return Step(tool=step.tool, invoked=publication.site_id,
                    proves=step.proves, passed=False,
                    detail=(f"{SITES_BASE_URL_ENV} is not configured, so there "
                            "is no address to publish to and no address to "
                            "check afterwards."))

    target = PublicHostTarget(root, base_url=base)
    try:
        version = target.publish(publication.site_id, publication.files)
        url = target.promote(publication.site_id, version.id)
        # Inside the `try`, because the client is closed in the `finally` and a
        # verification that ran after it would be fetching through a shut
        # connection pool.
        served = target.verify(url)
    except DeploymentUnreachable as unreachable:
        # The files are in place and the address does not serve them. Reported
        # as the failure it is: retrying the upload achieves nothing, and
        # claiming success here is the exact lie the target exists to prevent.
        return Step(tool=step.tool, invoked=publication.site_id,
                    proves=step.proves, passed=False,
                    detail=str(unreachable)[:300])
    except Exception as failure:              # noqa: BLE001 - recorded, not raised
        log.exception("publication of %s failed", publication.site_id)
        return Step(tool=step.tool, invoked=publication.site_id,
                    proves=step.proves, passed=False,
                    detail=f"{type(failure).__name__}: {failure}"[:300])
    finally:
        close = getattr(target, "close", None)
        if callable(close):
            close()

    # The verification fetch, recorded as the observation it is.
    #
    # Not decoration. A publication produces no workspace files and no diff, so
    # without this the run has nothing to show for itself and the worker's
    # acceptance check correctly reports that the agent claimed success and
    # produced nothing — which is what happened to the first real publication,
    # while the page was serving perfectly. What it produced is a page on the
    # internet, and the proof of that is what came back when it was fetched.
    evidence = [Evidence(
        kind=EvidenceKind.HTTP_RESPONSE, source=url,
        observed={"site_id": publication.site_id,
                  "commit": publication.commit,
                  "published_from": publication.source_mission,
                  "files": sorted(publication.files),
                  "status": served.get("status"),
                  "reachable": served.get("reachable"),
                  "error": served.get("error", "")},
        summary=(f"{len(publication.files)} file(s) live at {url} from "
                 f"{publication.commit[:12]}"),
        detector="tool:site-publish")]

    return Step(tool=step.tool, invoked=publication.site_id, proves=step.proves,
                passed=True, files=tuple(sorted(publication.files)),
                evidence=evidence,
                detail=(f"{len(publication.files)} file(s) at {url} from "
                        f"{publication.commit[:12]}; the address was fetched "
                        f"and answered {served.get('status', '?')}"))


def _resolve(step) -> Step:
    """Ask DNS about each host, recording only what it answered.

    An inconclusive lookup produces **no evidence** and does not fail the step.
    A name server that says *no such host* has answered; one that times out has
    not, and treating the second as the first is how a business gets reported as
    having no website because a resolver was slow for a second.
    """
    from ..research.net import Resolution, resolution

    collected: list[Evidence] = []
    for host in step.command:
        answer = resolution(host)
        if answer is Resolution.UNKNOWN:
            continue
        collected.append(Evidence(
            kind=EvidenceKind.DNS_RECORD, source=host,
            observed={"host": host, "resolution": answer.value},
            summary=f"DNS: {answer.value}", detector="recipe:dns"))
    return Step(tool=step.tool, invoked=", ".join(step.command),
                proves=step.proves, passed=True, evidence=collected,
                detail=(f"{len(collected)} conclusive answer(s); "
                        f"{len(step.command) - len(collected)} inconclusive and "
                        "therefore not recorded"))


def _command(step, *, agent: Agent, workspace: Path | None,
             registry: Registry | None) -> Step:
    """Run a command step through the existing sandboxed adapter.

    Not reimplemented: `Adapter` already derives isolation from the agent's
    declaration, refuses to run an agent that needs a sandbox the host does not
    have, and enforces the per-step tool contract. This hands the step over.
    """
    from .adapter import Adapter, NotRunnable
    from .adapter import Step as RunStep

    if workspace is None:
        return Step(tool=step.tool, invoked=" ".join(step.command),
                    proves=step.proves, passed=False,
                    detail="a command step needs a workspace and none was given")
    fitted = Adapter.for_id(agent.id, registry=registry)
    try:
        evidence = fitted.run(
            [RunStep(command=list(step.command), proves=step.proves,
                     tool=step.tool)],
            workspace=workspace)
    except NotRunnable as refused:
        return Step(tool=step.tool, invoked=" ".join(step.command),
                    proves=step.proves, passed=False, detail=str(refused)[:300])
    first = evidence[0] if evidence else None
    return Step(
        tool=step.tool, invoked=" ".join(step.command), proves=step.proves,
        passed=bool(first and first.passed),
        evidence=[Evidence(
            kind=EvidenceKind.ASSERTED, source=" ".join(step.command),
            observed={"exit_code": first.exit_code, "output": first.output[:2000],
                      "confinement": first.confinement},
            summary=first.proves, detector=f"recipe:{step.tool}")]
        if first else [],
        detail=(first.output[:300] if first else "nothing ran"))


__all__ = ["COMMANDS", "DISPATCHABLE", "Delivery", "DeliveryRefused",
           "NotDispatchable", "Result", "Step",
           "ToolAgent", "permitted_urls", "refusals", "run", "targets_for"]


# ============================================================ the worker role


class ToolAgent:
    """A worker role that carries out a recipe and returns evidence.

    Satisfies the same `CodingAgent` protocol every other role does — the worker
    is not modified and does not know this is different. That is the point: a
    non-coding agent is a role, not a second worker.

    It is **not a model with tools**. There is no prompt, no provider and no
    credential; `implement` looks the recipe up by name and runs its declared
    steps. A model may eventually choose the name and can change nothing else.

    ## What it produces

    `AgentOutcome.files` is empty and always will be: a research role writes no
    files, and the worker's acceptance check ("did it write something") is not
    the right question for it. The worker is given an acceptance that asks
    whether evidence was produced instead — chosen by whoever builds the roles,
    which is where that decision belongs.
    """

    def __init__(self, recipe: Recipe, *, registry: Registry | None = None,
                 client: object | None = None,
                 check_addresses: bool = True,
                 repository: object | None = None,
                 tenant: str | None = None,
                 signal_id: str = "", publishes: str = "",
                 publishes_offer: str = "",
                 scratch_root: str = "", source_workspace: str = "",
                 mission_id: str = "") -> None:
        self._recipe = recipe
        self._registry = registry
        self._client = client
        self._check_addresses = check_addresses
        #: Where sightings are remembered. `None` means this run produces
        #: evidence and a report and nothing durable — which is the right
        #: behaviour for a recipe with no extractor, and for a test that does
        #: not want a database.
        self._repository = repository
        self._tenant = tenant
        #: The last run, so the worker's committer and reporter can read what
        #: was actually invoked rather than parsing it back out of prose.
        self.result: Result | None = None
        #: What the extractor read and what memory made of it. Empty when the
        #: recipe declares no extractor.
        self.recorded: list = []
        #: Opportunities detected from this run, best first.
        self.signals: list = []
        #: Which business owns each address this run fetched. Read once, before
        #: the fetch, and reused by the audit — see `targets_map_for`.
        self._targets: dict = {}
        #: Findings the audit read out of what came back, by business id.
        self.audited: dict = {}
        #: The opportunity a person approved, when this is a delivery. A key,
        #: read from Qevik's own memory — never a record a caller supplied.
        self._signal_id = signal_id
        #: What the mission being published was delivering. Supplied by the
        #: worker, which is where the source mission is in hand.
        self._publishes_offer = publishes_offer
        #: What the delivery step wrote, relative to the workspace.
        self.artefact: tuple[str, ...] = ()
        #: What the publication step put on the site host. Not workspace files,
        #: and deliberately not `artefact`: nothing here is committable.
        self.published: tuple[str, ...] = ()
        #: The mission whose artefact this one publishes, when it publishes.
        self._publishes = publishes
        #: Where scratch clones live, so the reviewed commit can be read.
        self._scratch_root = scratch_root
        #: The workspace of the mission being published. Resolved by the worker,
        #: which owns the ledger, and passed in — this must not guess a path.
        self._source_workspace = source_workspace
        #: This mission's own id, recorded beside a publication so "which run
        #: put this live" has an answer.
        self._mission_id = mission_id

    @property
    def name(self) -> str:
        return f"{self._recipe.agent_id}:{self._recipe.id}"

    @property
    def recipe(self) -> Recipe:
        return self._recipe

    def plan(self, request: str, *, context: str = "") -> Plan:
        """The recipe, as a plan. Nothing is generated.

        A plan is what a person approves, and for a declared recipe the steps
        were approved when the recipe was merged. This renders them; it does
        not decide them.
        """
        return Plan(
            goal=self._recipe.does,
            why=f"recipe {self._recipe.id} v{self._recipe.version}",
            steps=tuple(
                PlanStep(order=n, title=step.proves,
                         why=f"{step.tool}: {' '.join(step.command)}")
                for n, step in enumerate(self._recipe.steps, start=1)),
            test_plan="each step records what the tool actually returned",
            estimated_cost=0.0, cost_status="REPORTED",
            approval_required=False)

    def implement(self, plan: Plan, *, workspace_root: str,
                  context: str = "") -> AgentOutcome:
        self._targets = targets_map_for(self._recipe,
                                        repository=self._repository,
                                        tenant=self._tenant)
        try:
            delivery = self._delivery()
            publication = self._publication()
        except DeliveryRefused as refused:
            return AgentOutcome(
                summary=str(refused)[:400], claims_done=False,
                blockers=(Blocker(kind="APPROVAL", detail=str(refused)[:400],
                                  action="the mission names an approved "
                                         "opportunity that does not authorise "
                                         "this work; neither is a runtime "
                                         "decision"),))
        try:
            self.result = run(self._recipe, delivery=delivery,
                              publication=publication,
                              registry=self._registry,
                              workspace=Path(workspace_root),
                              client=self._client,
                              check_addresses=self._check_addresses,
                              targets=list(self._targets))
        except NotDispatchable as refused:
            return AgentOutcome(
                summary=str(refused)[:400], claims_done=False,
                blockers=(Blocker(kind="ARCHITECTURE", detail=str(refused)[:400],
                                  action="fix the recipe or the agent's "
                                         "registry entry; neither is a runtime "
                                         "decision"),))
        found = self.result
        # Files written **into the workspace**, which is what a committer can
        # commit. A publication writes to the site host and changes nothing
        # here, so its names go to `published` instead — reported as
        # `outcome.files` they made the committer try to commit an unchanged
        # tree, and a publication that had genuinely gone live was recorded as
        # a failed mission.
        self.artefact = tuple(f for step in found.steps for f in step.files
                              if step.tool not in PUBLISHERS)
        self.published = tuple(f for step in found.steps for f in step.files
                               if step.tool in PUBLISHERS)
        remembered = self._remember(found)
        judged = self._audit(found)
        self._record_publication(found)
        return AgentOutcome(
            summary=(f"{len(found.evidence)} piece(s) of evidence from "
                     f"{len(found.steps)} step(s) via "
                     f"{', '.join(found.tools_invoked) or 'nothing'}"
                     + (f"; {remembered} sighting(s) recorded" if remembered
                        else "")
                     + (f"; {judged} site(s) with evidenced defects" if judged
                        else "")
                     + (f"; artefact: {len(self.artefact)} file(s)"
                        if self.artefact else "")
                     + (f"; published {len(self.published)} file(s)"
                        if self.published else "")),
            # What this run produced. Empty for a research pass, which is why
            # `evidence_count` exists beside it; a delivery produces no evidence
            # and a file, and the acceptance check needs to see one or the
            # other or it correctly reports that nothing happened.
            files=self.artefact,
            evidence_count=len(found.evidence),
            claims_done=found.passed,
            notes=_readable(found, self.recorded, self.signals))

    def _delivery(self) -> Delivery | None:
        """The approved opportunity this delivery rests on, or nothing.

        `None` for every recipe that does not deliver, which is most of them.
        A refusal — never a build against a default — for one that does and
        cannot be justified, because a delivery whose authorisation cannot be
        found is a delivery nobody authorised.

        The signal is read from memory by id. Nothing here accepts a
        signal-shaped argument: a caller that could pass the record could pass
        one it had edited, and the approval would then say whatever the caller
        wanted it to.
        """
        if self._recipe.publishes:
            # A publication names the same opportunity a delivery did, and runs
            # a different recipe on purpose. `_publication` owns every check for
            # it — including its own recipe check against
            # `publication.recipe_for` — so applying the delivery rule here
            # would refuse the publication for not being a delivery.
            #
            # This does not open the delivery guard. A recipe substituted into a
            # delivery mission still lands below unless it publishes, and one
            # that publishes is refused by `_publication` for naming no
            # authorisation: a delivery mission has no `publishes`.
            return None

        if not self._signal_id:
            # No approval referenced. Only a *delivering* recipe is a problem
            # here: everything else is ordinary work nobody claimed an
            # opportunity authorised.
            if self._recipe.delivers:
                raise DeliveryRefused(
                    f"{self._recipe.id} delivers {self._recipe.delivers} and "
                    "this mission names no approved opportunity. A delivery is "
                    "carried out because somebody agreed to it.")
            return None

        # From here the mission *does* name an approval, and that is what makes
        # the recipe check mandatory rather than delivery-specific.
        #
        # It was written the other way round — keyed on the recipe declaring
        # `delivers` — and that left the hole this exists to close: editing an
        # approved mission's recipe to a *research* recipe skipped the check
        # entirely, because the substituted recipe delivers nothing. The mission
        # then quietly ran whatever it had been changed to, on the strength of
        # an approval given for something else.
        if self._repository is None:
            raise DeliveryRefused(
                f"this mission names opportunity {self._signal_id} and has no "
                "business memory to read it from. An approval that cannot be "
                "checked is one that cannot be relied on.")

        from ..opportunity.detectors.website import FindingKind
        from . import delivery as bridge

        signal = self._repository.get_signal(self._signal_id,
                                             tenant=self._tenant)
        if signal is None:
            raise DeliveryRefused(
                f"no opportunity {self._signal_id!r}. The mission references an "
                "approval that is not there.")
        # Re-checked here, not trusted from mission creation. This is what
        # protects execution: creation's check answers the operator, and a
        # mission that sat in a queue while its opportunity was withdrawn must
        # not run on the strength of a state that has since changed.
        stop = bridge.refusals(signal)
        if stop:
            raise DeliveryRefused(" ".join(stop))
        # The recipe is derived from the opportunity a second time and compared.
        # A mission whose recipe was edited after approval names work the
        # approval never mentioned, and this is where that stops.
        expected = bridge.recipe_for(signal)
        if expected != self._recipe.id:
            raise DeliveryRefused(
                f"{self._signal_id} was approved for {expected!r} and this "
                f"mission runs {self._recipe.id!r}. A recipe substituted after "
                "approval is work nobody agreed to wearing an authorisation "
                "that was given for something else.")
        if not self._recipe.delivers:
            # Reachable only if a delivery recipe stops delivering, which would
            # be a declaration somebody changed under an approval that had
            # already been given.
            raise DeliveryRefused(
                f"{self._recipe.id} was approved as a delivery and no longer "
                "declares one.")

        # `ALL_TENANTS`, and deliberately — see the note in `opportunity/scan.py`.
        # A business Qevik discovered belongs to **nobody** until somebody
        # qualifies it: `save_business` writes no tenant on purpose, because
        # assigning a clinic to a customer at the moment a scanner noticed it
        # would decide a commercial question with a scanner. Reading it with
        # this mission's tenant returns `None` for every discovered business
        # there is, which blocked every delivery in production.
        #
        # The tenant boundary is not weakened by this: the *signal* was read
        # with this mission's tenant a few lines above, and it is the signal
        # that carries the approval. The ownership check below is what keeps a
        # delivery from reaching another tenant's qualified customer.
        from ..opportunity.tenancy import ALL_TENANTS, owns

        business = self._repository.get_business(signal["business_id"],
                                                 tenant=ALL_TENANTS)
        if business is None:
            raise DeliveryRefused(
                f"no business {signal['business_id']!r}; an artefact built for "
                "nobody cannot be reviewed or sent.")
        owner = getattr(business, "tenant_id", "") or ""
        if owner and not owns(owner, self._tenant):
            raise DeliveryRefused(
                f"{signal['business_id']} belongs to another tenant. An "
                "opportunity in one tenant does not authorise building for a "
                "customer in another.")

        findings = self._repository.list_findings(business.id)
        # A capability that *reports* what was observed needs the observations,
        # with the evidence each one carries. The synthetic shape below is
        # built for a capability that *fixes* defects and needs only their
        # names, and a health check built from it refused every real business —
        # correctly — for asserting findings with no evidence behind them.
        if self._recipe.delivers == "offer-health-check":
            audit = self._repository.latest_audit(business.id) if self._repository else {}
            if not (audit.get("observations") or []):
                raise DeliveryRefused(
                    f"{business.name} has no recorded website audit, so there "
                    "is nothing to report. A health check built from nothing "
                    "would tell a business their site is fine because nobody "
                    "looked.")
            log.info("%s: delivering %s for %s (%d observations)",
                     self._signal_id, self._recipe.delivers, business.name,
                     len(audit["observations"]))
            return Delivery(offer_id=self._recipe.delivers, business=business,
                            research=audit)

        # Everything below is the fix-building path. `BUILDABLE` asks which
        # observed defect a *build* can address, which is not a question a
        # report has to answer.
        observed = {bridge.BUILDABLE[f.kind] for f in findings
                    if f.kind in bridge.BUILDABLE}
        if not observed:
            raise DeliveryRefused(
                f"{business.name} has no defect this capability can build a "
                "fix for. Observed: "
                f"{', '.join(sorted({f.kind.value for f in findings})) or 'none'}"
                ". Building anyway would be inventing the weakness.")

        # `website` present because a response was fetched and audited — which
        # is the only way this opportunity could exist. Every other entry is a
        # defect actually observed, so `improvable()` sees confirmed absences
        # and nothing that was merely not checked.
        research = {"observations": (
            [{"feature": "website", "status": "present"}]
            + [{"feature": feature, "status": "not_found"}
               for feature in sorted(observed)])}
        log.info("%s: delivering %s for %s (%s)", self._signal_id,
                 self._recipe.delivers, business.name, ", ".join(sorted(observed)))
        return Delivery(offer_id=self._recipe.delivers, business=business,
                        research=research)

    def _record_publication(self, found: Result) -> None:
        """Write the timeline entry that makes this artefact published.

        **After the fact, and only on the fact.** The step it reads has already
        put the files on the host and fetched the address; a record written on
        intent would say a business has a website because Qevik meant to give
        them one.

        It carries the same `mission_id` the review and the authorisation carry
        — the mission whose artefact went out — so the three read as one story
        rather than three about different keys. Which run did the publishing is
        a separate field, because "what is live" and "which attempt put it
        there" are different questions.

        A failure to record does not fail the run: the page is live either way,
        and the honest response to a database that was briefly away is to say so
        rather than to claim the publication did not happen.
        """
        if not self._recipe.publishes or self._repository is None:
            return
        published = [step for step in found.steps
                     if step.tool in PUBLISHERS and step.passed]
        if not published:
            return

        signal = self._repository.get_signal(self._signal_id,
                                             tenant=self._tenant)
        for step in published:
            observed = (step.evidence[0].observed if step.evidence else {})
            try:
                self._repository.record_publication(
                    mission_id=self._publishes,
                    business_id=(signal or {}).get("business_id", ""),
                    signal_id=self._signal_id,
                    commit=observed.get("commit", ""),
                    site_id=observed.get("site_id", step.invoked),
                    url=(step.evidence[0].source if step.evidence else ""),
                    files=list(step.files),
                    actor=f"recipe:{self._recipe.id}",
                    publication_mission=self._mission_id,
                    # What was published, from the delivering mission's own
                    # recipe. Not from this one: `publish-website` publishes
                    # every artefact type and knows only that it published
                    # files. Empty when the source could not be read, which
                    # stays unknown rather than becoming a guess.
                    offer=self._publishes_offer,
                    tenant=self._tenant)
            except Exception:                     # noqa: BLE001 - reported
                log.exception(
                    "published %s but could not record it; the page is live and "
                    "the queue will still show it as waiting", step.invoked)
                found.steps.append(Step(
                    tool="record", invoked=step.invoked,
                    proves="the publication was written to the timeline",
                    passed=False,
                    detail=("the page is live and the record was not written. "
                            "The queue will still show this as awaiting "
                            "publication, which is the safe direction.")))

    def _publication(self) -> "Publication | None":
        """The bundle a person authorised, read from the commit they named.

        `None` for every recipe that publishes nothing. A refusal — never a
        publication of something else — for one that does and cannot be
        justified, because the failure mode here is a page in front of
        strangers and there is no undoing that.

        Six things are re-checked rather than trusted from the mission record.
        The authorisation is read from the timeline by the mission it names; the
        opportunity must match; the recipe must be the one that opportunity's
        offer publishes; the artefact must still be accepted; the accepted
        commit must be the authorised one; and the address must be the one
        derived from the business. A mission can sit in a queue while any of
        those changes.
        """
        if not self._recipe.publishes:
            return None
        from ..opportunity.tenancy import ALL_TENANTS, owns
        from . import artefact as reader
        from . import publication as bridge

        if self._repository is None or not self._publishes:
            raise DeliveryRefused(
                f"{self._recipe.id} publishes {self._recipe.publishes} and this "
                "mission names no authorised publication.")

        approvals = self._repository.publication_approvals_for(
            self._publishes, tenant=self._tenant)
        if not approvals:
            raise DeliveryRefused(
                f"nothing authorised publishing {self._publishes}. An accepted "
                "artefact is not an instruction to publish it.")
        approval = approvals[-1]

        signal = self._repository.get_signal(approval["signal_id"],
                                             tenant=self._tenant)
        if signal is None:
            raise DeliveryRefused(
                f"the authorisation names opportunity {approval['signal_id']}, "
                "which is not there.")
        if signal.get("id") != self._signal_id:
            raise DeliveryRefused(
                f"this mission names opportunity {self._signal_id} and the "
                f"authorisation is for {signal.get('id')}.")

        expected = bridge.recipe_for(signal)
        if expected != self._recipe.id:
            raise DeliveryRefused(
                f"{approval['signal_id']} publishes through {expected!r} and "
                f"this mission runs {self._recipe.id!r}.")

        business = self._repository.get_business(signal["business_id"],
                                                 tenant=ALL_TENANTS)
        if business is None:
            raise DeliveryRefused(
                f"no business {signal['business_id']!r} to publish for.")
        owner = getattr(business, "tenant_id", "") or ""
        if owner and not owns(owner, self._tenant):
            raise DeliveryRefused(
                f"{signal['business_id']} belongs to another tenant.")

        stop = bridge.refusals(approval, signal, business_id=business.id)
        if stop:
            raise DeliveryRefused(" ".join(stop))

        # Still accepted, and still accepted *at this commit*. Both, because a
        # review can be superseded and a branch can be rebuilt, and either one
        # alone would let the wrong bytes out.
        reviews = self._repository.reviews_for(self._publishes,
                                               tenant=self._tenant)
        if not reviews or reviews[-1]["decision"] != "accepted":
            raise DeliveryRefused(
                f"{self._publishes} is not accepted"
                + (f" — the last decision was {reviews[-1]['decision']!r}"
                   if reviews else "") + ".")
        if reviews[-1]["commit"] != approval["commit"]:
            raise DeliveryRefused(
                f"the accepted artefact is {reviews[-1]['commit'][:12]} and the "
                f"authorisation names {approval['commit'][:12]}.")

        source = self._source_workspace
        if not source:
            raise DeliveryRefused(
                f"the workspace of {self._publishes} is not known to this "
                "mission, so the approved commit cannot be read.")
        scratch = Path(self._scratch_root) if self._scratch_root else None
        # **The authorised commit, not the branch.** This is the line that makes
        # rebuilding a branch after approval change nothing about what is
        # published.
        names = reader.files_at(approval["commit"], source, scratch=scratch)
        files = {name[len(reader.PREFIX):]:
                 reader.read_at(approval["commit"], source, name,
                                scratch=scratch)
                 for name in names}
        log.info("publishing %s of %s to %s (%d file(s))",
                 approval["commit"][:12], self._publishes, approval["site_id"],
                 len(files))
        return Publication(site_id=approval["site_id"],
                           commit=approval["commit"],
                           source_mission=self._publishes, files=files)

    def _remember(self, found: Result) -> int:
        """Extract, identify, classify and persist. Returns how many were new.

        Runs inside `implement` so one mission is one chain: fetch, extract,
        resolve against memory, classify, remember. Splitting it across two
        missions would mean evidence with no sighting whenever the second never
        ran, which is the state discovery spent three sessions not being in.

        Nothing here decides anything about a business. `scan.record` resolves
        identity on strong keys and `discovery.classify` decides what kind of
        new it is, both against Qevik's own memory, and both were already
        proven. This is the join.

        A failure to remember does not fail the run: the evidence is real and
        already recorded, and losing it because the database was briefly away
        would be the worse outcome. It is reported instead.
        """
        if not self._recipe.extractor or self._repository is None:
            return 0
        from ..opportunity import scan
        from ..opportunity.extractors import (
            ExtractionError,
            extract_overpass,
            sighting_from,
        )
        from ..opportunity.extractors import (
            get as extractor_for,
        )

        extractor = extractor_for(self._recipe.extractor)
        sightings = []
        extractions: list = []
        for piece in found.evidence:
            try:
                for extraction in extract_overpass(piece, extractor=extractor):
                    extractions.append(extraction)
                    sightings.append(
                        sighting_from(extraction, piece, source=extractor.source))
            except ExtractionError as refused:
                log.warning("%s could not read %s: %s", extractor.id,
                            piece.source, refused)
                found.steps.append(Step(
                    tool="extract", invoked=extractor.id,
                    proves="what the source stated, by declared rules",
                    passed=False, detail=str(refused)[:300]))
        if not sightings:
            return 0

        try:
            pass_ = scan.record(sightings, repository=self._repository,
                                tenant=self._tenant)
        except Exception:                         # noqa: BLE001 - reported, not fatal
            log.exception("could not record %d sighting(s); the evidence "
                          "stands and is in the report", len(sightings))
            found.steps.append(Step(
                tool="extract", invoked=extractor.id, proves="sightings recorded",
                passed=False,
                detail="the evidence was read and memory could not be written"))
            return 0

        self.recorded = pass_.recorded
        found.steps.append(Step(
            tool="extract", invoked=extractor.id,
            proves="what the source stated, by declared rules", passed=True,
            detail=(f"{pass_.seen} extracted, {len(pass_.new_to_qevik)} new to "
                    f"Qevik, {len(pass_.proven_new)} evidenced as new by the "
                    "source")))
        self._detect(found, extractions, source=extractor.source)
        return len(pass_.recorded)

    def _audit(self, found: Result) -> int:
        """Read this run's responses into findings, and findings into signals.

        The other half of `_remember`, for the other kind of recipe. Discovery
        reads what a *source* said about a business; verification reads what
        the *business's own server* said, which is the first evidence here that
        can support approaching somebody.

        In the same mission, for the reason extraction is: a pass that fetched
        forty homepages and concluded nothing because a second mission never
        ran is exactly the state this milestone existed to leave.

        Failing to store does not fail the run. The responses are real and
        already in the report, and losing them because the database was
        briefly away would be the worse outcome.
        """
        if not self._recipe.audit or self._repository is None:
            return 0
        if not self._targets:
            return 0
        from ..opportunity import detect, ranking, verification

        audited = verification.audit_pass(self._targets, found.evidence)
        self.audited = audited
        # Persisted, not only summarised into a signal. A `Finding` names the
        # kind of defect; a signal's observations carry the sentence a person
        # reads. Delivery needs the kind — "this is a `page_speed` problem" —
        # and reading it back out of prose is how a build ends up guessing what
        # it was asked to fix. The rows were being computed and thrown away.
        for findings in audited.values():
            for finding in findings:
                try:
                    self._repository.save_finding(finding)
                except Exception:                 # noqa: BLE001 - reported
                    log.exception("could not store finding %s", finding.id)
        # Which recorded response each business's findings came out of, so a
        # signal cannot be built from derived evidence alone. Matched the same
        # way the audit matched them, rather than by re-deriving it.
        index = verification.owner_index(self._targets)
        responses: dict = {}
        for piece in found.evidence:
            owner = verification.owner_of(piece, index)
            if owner is not None and owner.id not in responses:
                responses[owner.id] = piece

        businesses = {b.id: b for b in self._targets.values()}
        # Every site this pass reached for, marked before anything else can go
        # wrong. The backlog is ordered by this event, so a business left
        # unmarked is one the next run picks first and the run after that picks
        # again — a queue that never advances past whatever fails.
        self._mark_verified(businesses, audited, responses)
        # The addresses these pages published, from the responses this pass
        # already holds. **This is the path that actually runs nightly.**
        # Contact discovery was first wired into `infra/audit_discovered.py`,
        # which ran once on 2026-08-19 and is scheduled by nothing — so it was
        # deployed into code nobody executes, and `Business.email` stayed empty
        # while the capability looked shipped.
        self._remember_contacts(businesses, responses)
        # What each page demonstrably has, in all three states. `audit_pass`
        # above produces `Finding`s, which are absences only — so until this
        # existed the nightly pass refreshed the defects and never refreshed
        # the observations, and every consumer that reads observations was
        # reading `infra/audit_discovered.py`'s output from 2026-08-19.
        recorded, compared = self._record_audit(businesses, responses)
        signals = detect.from_verification(audited, businesses, responses,
                                           source=self._recipe.id)
        found.steps.append(Step(
            tool="audit", invoked=self._recipe.audit,
            proves="what the returned pages support saying about these sites",
            passed=True,
            detail=(f"{len(found.evidence)} response(s) read, "
                    f"{sum(len(f) for f in audited.values())} finding(s) on "
                    f"{len(audited)} site(s), {len(signals)} opportunity(ies), "
                    f"{recorded} observation record(s), "
                    f"{compared} compared with a previous one")))
        if not signals:
            return len(audited)

        ranked = ranking.order(signals)
        self.signals = list(self.signals) + list(ranked)
        by_id = {s.id: s for s in signals}
        for scored in ranked:
            try:
                self._repository.save_signal(by_id[scored.signal_id], scored,
                                             tenant=self._tenant)
            except Exception:                     # noqa: BLE001 - reported
                log.exception("could not store signal %s", scored.signal_id)
        return len(audited)

    def _record_audit(self, businesses: dict, responses: dict) -> tuple[int, int]:
        """Write what each page demonstrably has, and how it differs from before.

        `audit_pass` produces `Finding`s, and a finding is an *absence*. The
        record a health check reports from — what was checked, what was there,
        and what could not be told either way — comes from `website_audit`,
        and nothing scheduled had ever called it: `infra/audit_discovered.py`
        wrote 336 of these on 2026-08-19 and `infra/import_audits.py` 60 more
        from a JSON file, and neither is in `RECURRENCES` or in any timer. So
        the defects refreshed nightly while the observations behind every
        health check stayed twelve days old.

        The same engine, on this pass's own bodies. No second audit
        implementation, no second fetch and no new schedule — the cadence is
        the recurrence that already runs.

        ## What it refuses to audit

        Three, and each would put a false claim in front of a business:

        **A truncated body.** `crawler.evidence_from` keeps the first
        `BODY_KEPT` bytes, and `audit_html` has no notion of a document that
        stopped early — it would report everything below the cut as absent.
        `WebsiteDetector` guards this with `body_complete`; this is the same
        rule for the same reason.

        **An error page.** A 500 says nothing about the homepage's booking
        link. **And a refusal is not a response**: status 0 with an error is
        our own guard or a dead host, and auditing it would report a business
        Qevik was not allowed to fetch as a business with a broken site.

        **Anything that is not HTML.** A PDF with no `<title>` is not a defect.

        A business it refuses keeps the audit it already had, which is the safe
        direction: stale and true beats fresh and invented.
        """
        from ..opportunity.audit_import import audit_event
        from ..opportunity.website_audit import audit_html, reconcile

        record = getattr(self._repository, "record_event", None)
        latest = getattr(self._repository, "latest_audit", None)
        if not (callable(record) and callable(latest)):
            return 0, 0

        written = compared = 0
        for business_id, piece in responses.items():
            if business_id not in businesses:
                continue
            observed = piece.observed or {}
            body = observed.get("body")
            status = observed.get("status") or 0
            if (not isinstance(body, str) or not body
                    or observed.get("body_truncated")
                    or observed.get("error")
                    or not (200 <= int(status) < 400)):
                continue
            content_type = str(observed.get("content_type") or "")
            if content_type and "html" not in content_type.lower():
                continue
            try:
                findings = audit_html(
                    body, url=str(observed.get("url") or piece.source or ""),
                    page_bytes=int(observed.get("bytes") or len(body)))
                if not findings:
                    continue
                # Read before the new one is written, or the comparison is
                # against itself. The previous audit stays exactly where it is:
                # history is immutable and the delta is worthless if the
                # baseline moves.
                before = latest(business_id) or {}
                # An absence a better reading contradicts is not an absence.
                # The first real pass produced five of them on one site in a
                # night, because the reading it was compared against was a
                # rendered browser and this one is a plain fetch.
                read_by = f"recipe:{self._recipe.id}/http-fetch"
                findings = reconcile(
                    findings, previous=before.get("observations") or [],
                    previous_read_by=str(before.get("read_by") or ""),
                    current_read_by=read_by)
                audit = {
                    "url": str(observed.get("url") or piece.source or ""),
                    "http_status": int(status),
                    "load_ms": observed.get("elapsed_ms"),
                    "page_bytes": int(observed.get("bytes") or len(body)),
                    "audited_at": datetime.now(UTC).isoformat(),
                    "findings": [f.model_dump(mode="json") for f in findings],
                }
                record(audit_event(business_id, audit, read_by=read_by))
                written += 1
                if self._compare_audit(business_id, before, audit):
                    compared += 1
            except Exception:                     # noqa: BLE001 - reported
                # One site's audit is not worth the pass. It keeps the record
                # it had and is offered again on the next run.
                log.exception("could not record the audit for %s", business_id)
        return written, compared

    def _compare_audit(self, business_id: str, before: dict,
                       audit: dict) -> bool:
        """Record how this reading differs from the last one. Overwrites nothing.

        `reevaluation.compare` is the existing policy and it is the right one:
        a feature confirmed before and absent now is a fact about their site, a
        feature confirmed before and unverifiable now is a fact about **our**
        checking, and the two must never be summed. It has existed since M-13
        and was reachable only from two hand-run scripts.

        Nothing downstream is invalidated by this. An approved message, a
        published artefact and a recorded approval all stand — what the delta
        does is make it possible to see that the evidence under one has moved,
        which is a decision for a person and not for a nightly pass.
        """
        previous = before.get("observations") or []
        if not previous:
            return False
        from . import reevaluation

        comparison = reevaluation.compare(
            business_id=business_id, tenant=self._tenant,
            previous=previous, current=audit["findings"])
        if not comparison.anything_changed:
            return False
        record = getattr(self._repository, "record_event", None)
        if callable(record):
            record(reevaluation.to_event(
                comparison, actor=f"recipe:{self._recipe.id}"))
        return True

    def _remember_contacts(self, businesses: dict, responses: dict) -> None:
        """Record the addresses each page published, from this pass's own bodies.

        No second fetch: `audit_pass` already read these responses to produce
        findings, and the body is on the evidence. Reading contacts here costs
        one pass over a string that is already in memory.

        Discovery, not authorisation. An address becoming a business's
        contactability makes it *reachable*; suppression, cooldown, approval
        and the sending identity all still sit between that and a message.
        """
        from ..opportunity.contacts import contactable_at, observed

        for business_id, piece in responses.items():
            business = businesses.get(business_id)
            if business is None:
                continue
            body = (piece.observed or {}).get("body")
            if not isinstance(body, str) or not body:
                continue
            url = str((piece.observed or {}).get("url") or piece.source or "")
            try:
                found = observed(body, url=url,
                                 at=getattr(piece, "observed_at", "") and
                                 str(piece.observed_at))
                address = contactable_at(found)
                if address:
                    self._repository.record_contactability(
                        business_id, address=address, source_url=url)
            except Exception:                     # noqa: BLE001 - reported
                # A business left without an address is one the next pass picks
                # up again. Failing the run over it would lose the findings too.
                log.exception("could not read contacts from %s", url)

    def _mark_verified(self, businesses: dict, audited: dict,
                       responses: dict) -> None:
        """Record that each of these sites has had its turn.

        For every business the pass *attempted*, not only for those that
        answered. A site behind a robots exclusion has been looked at, and
        recording only successes would let it sit at the head of the queue for
        ever while three hundred others waited.

        Best-effort by design: a timeline that could not be written is worth
        reporting and is not worth losing an audit over. The cost of failing is
        that the site is offered again tomorrow, which is the safe direction.
        """
        from ..opportunity.models import BusinessEvent
        from ..opportunity.repository import VERIFIED_EVENT

        record = getattr(self._repository, "record_event", None)
        if not callable(record):
            return
        for business_id in businesses:
            try:
                record(BusinessEvent(
                    business_id=business_id, kind=VERIFIED_EVENT,
                    actor=f"recipe:{self._recipe.id}",
                    detail={"findings": len(audited.get(business_id, [])),
                            "answered": business_id in responses}))
            except Exception:                     # noqa: BLE001 - reported
                log.exception("could not mark %s verified; it will be offered "
                              "again on the next pass", business_id)

    def _detect(self, found: Result, extractions: list, *, source: str) -> None:
        """Turn what memory now knows into ranked opportunities.

        In the same mission for the same reason extraction is: a pass that
        found forty businesses and detected nothing because a second mission
        never ran is the state this was built to leave.

        Detection is deterministic and so is the ranking — both before any
        model, so "why is this first" has an answer somebody can disagree with
        six weeks later.
        """
        from ..opportunity import detect, ranking

        signals = detect.from_pass(self.recorded, extractions, source=source)
        if not signals:
            return
        self.signals = ranking.order(signals)

        stored = 0
        by_id = {s.id: s for s in signals}
        for scored in self.signals:
            try:
                if self._repository.save_signal(by_id[scored.signal_id], scored,
                                                tenant=self._tenant):
                    stored += 1
            except Exception:                     # noqa: BLE001 - reported
                log.exception("could not store signal %s", scored.signal_id)
        found.steps.append(Step(
            tool="detect", invoked="opportunity detection",
            proves="what the evidence supports saying about these businesses",
            passed=True,
            detail=(f"{len(signals)} detected, {stored} new; "
                    f"{len(signals) - stored} already on the list")))

    def review(self, plan: Plan, outcome: AgentOutcome, *,
               context: str = "") -> AgentOutcome:
        """Whether the evidence supports saying the recipe ran.

        Deliberately weak, and honest about it: this checks that every step
        passed and that something was recorded. It does **not** judge whether
        the evidence means anything — that is `opportunity/`'s work, against
        Qevik's own memory, which this cannot see.
        """
        found = self.result
        if found is None or not found.steps:
            return outcome.model_copy(update={
                "claims_done": False, "summary": "nothing ran"})
        # A run has to leave something behind, and there are two shapes of
        # something. A research pass leaves evidence; a delivery leaves an
        # artefact and no evidence at all — it observed nothing, it built. This
        # asked only for evidence, so a delivery that wrote a real site was
        # rejected for having recorded no observations.
        if not found.evidence and not self.artefact and not self.published:
            produced = ("an artefact" if self._recipe.delivers
                        else "a publication" if self._recipe.publishes
                        else "any evidence")
            return outcome.model_copy(update={
                "claims_done": False,
                "summary": f"every step passed and nothing was recorded — no "
                           f"{produced}, which is not a successful run"})
        return outcome.model_copy(update={"claims_done": found.passed})

    def summarize(self, plan: Plan, outcome: AgentOutcome) -> str:
        return (_readable(self.result, self.recorded, self.signals)
                if self.result else "nothing ran")


def _readable(found: Result | None, extra: list | None = None,
              signals: list | None = None) -> str:
    """The run as text for a report. Facts, in the order they happened."""
    if found is None:
        return "nothing ran"
    lines = [f"recipe: {found.recipe}", f"agent: {found.agent_id}",
             f"tools invoked: {', '.join(found.tools_invoked) or 'none'}", ""]
    if signals:
        lines.append("opportunities, best first")
        for scored in signals:
            lines.append(f"  {scored.score:.3f}  {scored.kind}  "
                         f"{scored.business_id}")
            lines.append(f"      value: {scored.value_status}"
                         + (f" {scored.value_amount:g}"
                            if scored.value_amount is not None else ""))
            for part in scored.components:
                lines.append(f"      {part.name}={part.raw:.2f}  {part.because}")
        lines.append("")
    if extra:
        lines.append("sightings")
        for item in extra:
            lines.append(f"  {item.classification.state.value}  "
                         f"{item.business.name}  ({item.business.id})")
            lines.append(f"      {item.classification.because}")
            for piece in item.sighting.evidence:
                lines.append(f"      evidence {piece.fingerprint[:12]} "
                             f"{piece.source}")
        lines.append("")
    for step in found.steps:
        lines.append(f"{'ok' if step.passed else 'FAILED'}  {step.tool}  "
                     f"{step.invoked}")
        lines.append(f"    proves: {step.proves}")
        if step.detail:
            lines.append(f"    {step.detail}")
        for piece in step.evidence:
            lines.append(f"    evidence {piece.fingerprint[:12]} "
                         f"{piece.kind.value} {piece.source}")
            lines.append(f"      {piece.observed}")
    return "\n".join(lines)
