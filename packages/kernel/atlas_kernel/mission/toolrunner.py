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

import logging
from dataclasses import dataclass, field
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
DISPATCHABLE: frozenset[str] = frozenset({"http-fetch", "dns"}) | COMMANDS


log = logging.getLogger(__name__)


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
    detail: str = ""

    def summary(self) -> dict:
        return {"tool": self.tool, "invoked": self.invoked,
                "proves": self.proves, "passed": self.passed,
                "evidence": [e.fingerprint for e in self.evidence],
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


def permitted_urls(recipe: Recipe) -> frozenset[str]:
    """Exactly the URLs this recipe names. The fetch allow-list.

    Computed from the declaration rather than passed in, so a caller — a model,
    a mission, an operator in a hurry — cannot widen it. A recipe that wants to
    fetch a second page is a recipe with a second step, reviewed in git.
    """
    return frozenset(
        argument
        for step in recipe.steps if step.tool == "http-fetch"
        for argument in step.command)


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


def run(recipe: Recipe, *, registry: Registry | None = None,
        workspace: Path | None = None,
        client: object | None = None,
        check_addresses: bool = True) -> Result:
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

    allowed = permitted_urls(recipe)
    outcome = Result(recipe=recipe.id, agent_id=agent.id)

    for step in recipe.steps:
        if step.tool == "http-fetch":
            done = _fetch(step, allowed=allowed, client=client,
                          check_addresses=check_addresses)
        elif step.tool == "dns":
            done = _resolve(step)
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

    evidence, refused = crawler.fetch_steps(
        list(step.command), detector=f"recipe:{step.tool}", client=client,
        check_addresses=check_addresses)
    if refused:
        return Step(tool=step.tool, invoked=", ".join(step.command),
                    proves=step.proves, passed=False,
                    evidence=[r.as_evidence(f"recipe:{step.tool}")
                              for r in refused],
                    detail="; ".join(r.because for r in refused)[:300])
    return Step(tool=step.tool, invoked=", ".join(step.command),
                proves=step.proves, passed=bool(evidence), evidence=evidence,
                detail=f"{len(evidence)} response(s) recorded")


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


__all__ = ["COMMANDS", "DISPATCHABLE", "NotDispatchable", "Result", "Step",
           "ToolAgent", "permitted_urls", "refusals", "run"]


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
                 tenant: str | None = None) -> None:
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
        try:
            self.result = run(self._recipe, registry=self._registry,
                              workspace=Path(workspace_root),
                              client=self._client,
                              check_addresses=self._check_addresses)
        except NotDispatchable as refused:
            return AgentOutcome(
                summary=str(refused)[:400], claims_done=False,
                blockers=(Blocker(kind="ARCHITECTURE", detail=str(refused)[:400],
                                  action="fix the recipe or the agent's "
                                         "registry entry; neither is a runtime "
                                         "decision"),))
        found = self.result
        remembered = self._remember(found)
        return AgentOutcome(
            summary=(f"{len(found.evidence)} piece(s) of evidence from "
                     f"{len(found.steps)} step(s) via "
                     f"{', '.join(found.tools_invoked) or 'nothing'}"
                     + (f"; {remembered} sighting(s) recorded" if remembered
                        else "")),
            files=(),
            evidence_count=len(found.evidence),
            claims_done=found.passed,
            notes=_readable(found, self.recorded, self.signals))

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
        if not found.evidence:
            return outcome.model_copy(update={
                "claims_done": False,
                "summary": "every step passed and nothing was recorded, which "
                           "is not a successful research run"})
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
