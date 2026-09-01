"""The tool-executing role: what it may reach, and what it may not.

A tool-executing agent is **not a model with tools**. A model may eventually
propose `recipe = "discover-uae-dental"` — a key, which resolves or is refused.
It may not propose a tool, a URL, a step, or an interpretation. These tests are
each one of those refusals.
"""

from __future__ import annotations

import json

import pytest

from atlas_kernel.fabric import recipes
from atlas_kernel.fabric.agents import Registry
from atlas_kernel.mission import toolrunner
from atlas_kernel.mission.agents import AgentOutcome, CodingAgent
from atlas_kernel.mission.toolrunner import ToolAgent
from atlas_kernel.opportunity.models import Business, Evidence, EvidenceKind

RESEARCHER = "researcher"
RECIPE = "discover-uae-dental"

#: The discovery recipe that declares an extractor. `RECIPE` above declares
#: none, so `_remember` returns before reading anything — which is correct for
#: it and useless for testing what a pass records.
DISCOVER = "discover-dubai-dental-osm"


def a_recipe(tool: str, *command: str, agent: str = RESEARCHER) -> recipes.Recipe:
    return recipes.Recipe(
        id="probe", does="probe", agent_id=agent,
        capability=Registry().get(agent).capability,
        steps=(recipes.Step(tool=tool, command=command or ("x",),
                            proves="probes"),))


# ------------------------------------------- tool access comes from the role

def test_the_research_role_declares_only_network_research_tools():
    assert set(Registry().get(RESEARCHER).tools) == {"http-fetch", "dns"}


@pytest.mark.parametrize("tool,capability", [
    ("shell", "arbitrary shell"),
    ("filesystem", "filesystem write"),
    ("git-worktree", "git"),
    ("browser", "browser automation"),
    ("smtp", "email"),
    ("publish", "publication"),
    ("amazon", "marketplace side effects"),
])
def test_a_research_recipe_cannot_obtain(tool, capability):
    """Not given generic shell access merely because the adapter exists."""
    refused = toolrunner.refusals(a_recipe(tool), Registry().get(RESEARCHER))
    assert refused, f"{capability} was permitted"
    assert tool in refused[0]
    assert "comes from the registered role" in refused[0]


def test_a_tool_nobody_declared_anywhere_is_refused():
    """A typo is not permission."""
    assert toolrunner.refusals(a_recipe("htp-fetch"), Registry().get(RESEARCHER))


def test_a_declared_tool_with_no_adapter_is_refused_before_it_runs():
    """`browser` is a real tool in the contract that nothing here can invoke.
    Refused up front rather than failing partway through a sequence."""
    browsing = Registry().get("browser")
    assert "browser" in browsing.tools
    refused = toolrunner.refusals(
        a_recipe("browser", agent="browser"), browsing)
    assert refused and "nothing here knows how to invoke it" in refused[0]


def test_the_declared_recipe_is_runnable_by_its_agent():
    assert toolrunner.refusals(recipes.get(RECIPE),
                               Registry().get(RESEARCHER)) == []


# ------------------------------------------------ a URL comes from the recipe

def test_the_allow_list_is_exactly_what_the_recipe_names():
    assert toolrunner.permitted_urls(recipes.get(RECIPE)) == {
        "https://www.dha.gov.ae/"}


def test_a_url_outside_the_recipe_is_refused_before_a_socket_opens():
    """What makes "a model proposed a recipe" safe."""
    step = toolrunner._fetch(
        recipes.Step(tool="http-fetch",
                     command=("https://attacker.example/exfil",),
                     proves="p"),
        allowed=frozenset({"https://allowed.example/"}), client=None,
        check_addresses=True)
    assert not step.passed
    assert "not named by this recipe" in step.detail
    assert not step.evidence, "evidence was produced for a refused URL"


def test_a_recipe_naming_an_undeclared_agent_is_not_dispatchable():
    orphan = recipes.Recipe(
        id="orphan", does="p", agent_id="nobody",
        capability=recipes.Capability.RESEARCH,
        steps=(recipes.Step(tool="http-fetch", command=("https://x.test/",),
                            proves="p"),))
    with pytest.raises(toolrunner.NotDispatchable, match="no registry entry"):
        toolrunner.run(orphan)


def test_running_a_recipe_the_agent_cannot_use_refuses_before_any_step():
    with pytest.raises(toolrunner.NotDispatchable, match="does not declare"):
        toolrunner.run(a_recipe("shell", "echo", "hello"))


# ----------------------------------------------------------- the role itself

def test_the_role_satisfies_the_same_protocol_every_other_role_does():
    """A non-coding agent is a role, not a second worker."""
    assert isinstance(ToolAgent(recipes.get(RECIPE)), CodingAgent)


def test_the_role_needs_no_model_credential():
    """No prompt, no provider, no key."""
    agent = ToolAgent(recipes.get(RECIPE))
    assert not hasattr(agent, "provider")
    plan = agent.plan("anything")
    assert plan.goal == recipes.get(RECIPE).does
    assert len(plan.steps) == len(recipes.get(RECIPE).steps)


def test_the_plan_is_the_recipe_and_nothing_is_generated():
    """A plan is what a person approves; for a declared recipe the steps were
    approved when it merged."""
    plan = ToolAgent(recipes.get(RECIPE)).plan("ignored request text")
    assert RECIPE in plan.why
    assert plan.estimated_cost == 0.0 and plan.cost_status == "REPORTED"


def test_an_undispatchable_recipe_becomes_a_blocker_not_a_crash():
    agent = ToolAgent(a_recipe("shell", "echo", "hi"))
    outcome = agent.implement(agent.plan("x"), workspace_root="/tmp")
    assert not outcome.claims_done
    assert outcome.blockers and outcome.blockers[0].kind == "ARCHITECTURE"


def test_a_research_outcome_writes_no_files_and_says_so():
    """Its currency is evidence. Judging it on files failed every successful
    run before `produced_nothing` learned to ask the outcome."""
    empty = AgentOutcome(claims_done=True, files=(), evidence_count=0)
    assert empty.produced_nothing

    researched = AgentOutcome(claims_done=True, files=(), evidence_count=3)
    assert not researched.produced_nothing

    coded = AgentOutcome(claims_done=True, files=("a.py",))
    assert not coded.produced_nothing


def test_a_coding_agent_is_held_to_exactly_the_same_standard_as_before():
    """The guard was generalised, not weakened."""
    assert AgentOutcome(claims_done=True, files=()).produced_nothing


# ------------------------------------------------------- the evidence boundary

def test_the_runner_records_which_tools_were_actually_invoked():
    """"could have fetched" and "fetched" are different facts."""
    found = toolrunner.Result(recipe="r", agent_id="a", steps=[
        toolrunner.Step(tool="dns", invoked="x", proves="p", passed=True)])
    assert found.tools_invoked == ("dns",)


def test_the_result_summary_carries_identity_and_counts_not_conclusions():
    rendered = toolrunner.Result(recipe=RECIPE, agent_id=RESEARCHER).summary()
    assert rendered["recipe"] == RECIPE and rendered["agent_id"] == RESEARCHER
    assert set(rendered) == {"recipe", "agent_id", "passed", "tools_invoked",
                             "evidence_count", "steps"}
    words = str(rendered).lower()
    assert "opportunity" not in words and "is new" not in words


def test_an_inconclusive_dns_answer_records_nothing_and_does_not_fail():
    """A name server that says no such host has answered; one that times out
    has not."""
    step = toolrunner._resolve(
        recipes.Step(tool="dns", command=("localhost",), proves="p"))
    assert step.passed
    assert all(e.observed["resolution"] != "unknown" for e in step.evidence)


# -------------------------------------------------- the recurrence names it

def test_the_daily_discovery_recurrence_names_its_recipe():
    """Asserts that it names *a* recipe and which agent runs it — deliberately
    not a specific id. The earlier version pinned the placeholder's name, which
    is how the recurrence went on pointing at a recipe with no extractor while
    the suite stayed green."""
    from atlas_kernel.mission import recurrence

    daily = next(r for r in recurrence.RECURRENCES
                 if r.id == "rec-daily-business-discovery")
    assert daily.recipe
    assert recipes.get(daily.recipe).agent_id == RESEARCHER
    assert daily.agent_id == RESEARCHER


def test_every_recurrence_that_names_a_recipe_names_a_real_one():
    from atlas_kernel.mission import recurrence

    for rule in recurrence.RECURRENCES:
        if rule.recipe:
            assert recipes.get(rule.recipe).agent_id == rule.agent_id, rule.id


def test_the_mission_a_recurrence_creates_carries_the_recipe():
    from atlas_kernel.mission import origins, recurrence

    daily = next(r for r in recurrence.RECURRENCES
                 if r.id == "rec-daily-business-discovery")
    registry = origins.Registry.build()
    firing = recurrence.assess(daily, at=daily.anchor, missions=[])
    mission, _ = recurrence.enqueue(daily, firing, tenant=daily.tenant_id,
                                    origin=registry.resolve(daily.origin_name))
    assert mission.recipe == daily.recipe
    assert mission.agent_id == RESEARCHER


# --------------------------------------- the tests measure the declaration

@pytest.mark.parametrize("tool", ["shell", "filesystem", "git-worktree"])
def test_the_refusals_follow_the_declaration_and_not_a_hardcoded_list(tool):
    """A negative control on the permission tests themselves.

    Every "cannot obtain X" test above passes if the refusal is hardcoded
    rather than derived from the role's entry. This widens a *copy* of the role
    and asserts the refusal disappears — so the tests are measuring the
    declaration.

    It caught a real inconsistency: `git-worktree` was refused even when
    declared, because `COMMANDS` and `DISPATCHABLE` were written out separately
    and disagreed. `_command` had a branch nothing could reach, and a recipe
    declaring it was refused for the wrong reason.
    """
    registry = Registry()
    real = registry.get(RESEARCHER)
    widened = real.model_copy(update={
        "tools": ("http-fetch", "dns", "shell", "filesystem", "git-worktree")})

    assert toolrunner.refusals(a_recipe(tool), real), (
        f"{tool} was permitted to the real role")
    assert not toolrunner.refusals(a_recipe(tool), widened), (
        f"{tool} stayed refused after being declared, so the refusal is not "
        "coming from the declaration")


def test_dispatchable_is_derived_so_the_two_sets_cannot_drift():
    assert toolrunner.COMMANDS <= toolrunner.DISPATCHABLE
    assert {"http-fetch", "dns"} <= toolrunner.DISPATCHABLE


def test_a_recurrence_that_should_produce_sightings_names_a_recipe_that_can():
    """The nightly discovery entry pointed at a recipe with **no extractor**,
    so it would have fetched a page, extracted nothing and recorded no business
    — night after night, reporting success each time.

    A recurrence whose whole purpose is to remember businesses must name a
    recipe that can produce them.
    """
    from atlas_kernel.mission import recurrence

    daily = next(r for r in recurrence.RECURRENCES
                 if r.id == "rec-daily-business-discovery")
    assert daily.recipe, "the discovery recurrence names no recipe"
    assert recipes.get(daily.recipe).extractor, (
        f"{daily.recipe} declares no extractor, so it produces evidence and "
        "never a sighting")


# ------------------------------------- targets from memory, not from a proposal

def test_a_recipe_without_a_target_source_ignores_offered_targets():
    """The ordinary case: the steps name every URL, and nothing widens that."""
    declared = recipes.get(RECIPE)
    assert not declared.targets_from
    assert toolrunner.permitted_urls(
        declared, targets=["https://attacker.example/"]) == \
        toolrunner.permitted_urls(declared)


def test_a_verification_recipe_may_fetch_what_memory_holds():
    verify = recipes.get("verify-recorded-websites")
    assert verify.targets_from == "business_websites"
    allowed = toolrunner.permitted_urls(
        verify, targets=["https://clinic.example/"])
    assert "https://clinic.example/" in allowed


def test_a_target_source_nobody_declared_is_refused():
    with pytest.raises(recipes.RecipeRefused, match="not a declared source"):
        recipes.validate(recipes.Recipe(
            id="invented", does="x", agent_id=RESEARCHER,
            capability=recipes.Capability.RESEARCH, targets_from="anywhere",
            steps=(recipes.Step(tool="http-fetch",
                                command=("https://x.test/",), proves="p"),)))


def test_targets_are_bounded():
    """A market that grows to ten thousand businesses must not become ten
    thousand fetches in one mission."""
    class Everything:
        def businesses_by_website(self, *, limit, tenant=None):
            assert limit <= 200, "the repository was asked for an unbounded list"
            from atlas_kernel.opportunity.models import Business
            return {f"https://s{n}.example/":
                    Business(id=f"b-{n}", name=f"S{n}",
                             website=f"https://s{n}.example/")
                    for n in range(limit)}

    found = toolrunner.targets_for(recipes.get("verify-recorded-websites"),
                                   repository=Everything(), limit=10)
    assert len(found) == 10


def test_no_repository_means_no_targets():
    """A verification run with nowhere to read from fetches nothing rather than
    falling back to something."""
    assert toolrunner.targets_for(recipes.get("verify-recorded-websites"),
                                  repository=None) == []


def test_an_address_guard_refusal_still_fails_a_multi_target_step():
    """One site being down is one target out of many. Being pointed at an
    address the guard refuses is worth stopping for."""
    step = toolrunner._fetch(
        recipes.Step(tool="http-fetch",
                     command=("http://169.254.169.254/", "http://10.0.0.1/"),
                     proves="p"),
        allowed=frozenset({"http://169.254.169.254/", "http://10.0.0.1/"}),
        client=None, check_addresses=True)
    assert not step.passed
    assert step.evidence, "the refusals were not recorded as evidence"


# ------------------------------------ a failed run has to say what failed
#
# `mission-9403ed56cc88` recorded 40 responses, wrote 7 observation records and
# 3 comparisons, raised signals for 10 sites — and was recorded as `failed`
# with the note "review rejected the change: 40 piece(s) of evidence from 2
# step(s) via audit, http-fetch; 10 site(s) with evidenced defects". That
# restates what the run produced and never says what went wrong.

VERIFY = "verify-recorded-websites"

#: The two failures that used to read identically in the record: a pass where
#: nothing came back at all, and one where the sites answered and a single
#: address tripped the address guard.
GUARDED = "address refused: 169.254.169.254 is not a public address"
FETCHED_NOTHING = "0 response(s) recorded; 40 not fetched"

#: What the implementer reported, word for word from the production mission.
PRODUCED = AgentOutcome(
    summary=("40 piece(s) of evidence from 2 step(s) via audit, http-fetch; "
             "10 site(s) with evidenced defects"),
    claims_done=True, evidence_count=40)

#: A homepage with real content, so `audit_html` has something to observe.
HOMEPAGE = """<!doctype html><html><head><title>Al Waha Dental</title>
<meta name="description" content="A dental clinic in Dubai."></head>
<body><h1>Al Waha Dental</h1>
<a href="tel:+971501234567">Call us</a>
<form><input name="name"><textarea name="message"></textarea></form>
<p>We have cared for families in Jumeirah since 2004, offering general
dentistry, hygiene appointments and emergency care.</p>
</body></html>"""


#: The same page, publishing a role address, so contact discovery has one to
#: read. Whether that address is *written* is the repository's answer.
PUBLISHES_AN_ADDRESS = HOMEPAGE.replace(
    "<h1>Al Waha Dental</h1>",
    '<h1>Al Waha Dental</h1><p>Contact us: '
    '<a href="mailto:info@alwaha.ae">info@alwaha.ae</a></p>')

#: One Overpass response, in the shape the fetcher records it, carrying one
#: clinic the declared extractor can read.
OVERPASS = Evidence(
    kind=EvidenceKind.HTTP_RESPONSE,
    source="https://overpass-api.de/api/interpreter",
    observed={"status": 200, "content_type": "application/json",
              "body": json.dumps({"elements": [
                  {"type": "node", "id": 11, "tags": {
                      "name": "Al Waha Dental",
                      "addr:city": "Dubai",
                      "addr:country": "AE",
                      "website": "https://alwaha.test"}}]}),
              "body_truncated": False},
    summary="HTTP 200", detector="recipe:http-fetch")


def _response(url: str, *, body: str = "<html></html>") -> Evidence:
    """One recorded response, in the shape `crawler.evidence_from` writes."""
    return Evidence(
        kind=EvidenceKind.HTML_CONTENT, source=url,
        observed={"status": 200, "content_type": "text/html",
                  "bytes": len(body), "elapsed_ms": 210, "redirect_chain": [],
                  "error": "", "body": body, "body_truncated": False,
                  "url": url},
        summary="HTTP 200", detector="recipe:http-fetch")


def _fetch_failed(detail: str, evidence: list | None = None) -> toolrunner.Step:
    return toolrunner.Step(
        tool="http-fetch", invoked="40 recorded websites",
        proves="whether each recorded website answers", passed=False,
        evidence=(evidence if evidence is not None
                  else [_response("https://alwaha.test")]),
        detail=detail)


def _reviewed(detail: str) -> AgentOutcome:
    """The production shape: a fetch step that failed, an audit that ran."""
    agent = ToolAgent(recipes.get(VERIFY))
    agent.result = toolrunner.Result(recipe=VERIFY, agent_id=RESEARCHER, steps=[
        _fetch_failed(detail),
        toolrunner.Step(tool="audit", invoked="website", passed=True,
                        proves="what the returned pages support saying",
                        detail="40 response(s) read, 22 finding(s) on 10 site(s)"),
    ])
    return agent.review(agent.plan("ignored"), PRODUCED)


def test_a_rejected_run_records_the_cause_and_not_its_own_output():
    """The failing step's `detail` already said what happened. Nothing carried
    it to the record."""
    reviewed = _reviewed(GUARDED)

    assert not reviewed.claims_done
    assert "http-fetch" in reviewed.summary, "the record does not say which step"
    assert GUARDED in reviewed.summary
    assert "piece(s) of evidence" not in reviewed.summary, (
        "the rejection restates what the run produced instead of naming the "
        "failure, which is the defect")


def test_fetching_nothing_and_tripping_one_guard_do_not_read_alike():
    """An operator has to be able to tell them apart, and could not: both were
    recorded with the same sentence, because the sentence came from the
    implementer's summary rather than from the step."""
    guarded, empty = _reviewed(GUARDED), _reviewed(FETCHED_NOTHING)

    assert GUARDED in guarded.summary
    assert FETCHED_NOTHING in empty.summary
    assert guarded.summary != empty.summary


def test_a_step_that_failed_without_saying_why_is_recorded_as_such():
    """Silence is reported as silence. A blank detail must not read as a run
    that had no failure."""
    reviewed = _reviewed("")
    assert not reviewed.claims_done
    assert "recorded no reason" in reviewed.summary


# ----------------------------------------- and whether its output is live


class RecordingMemory:
    """Just enough repository for one audit pass, remembering what was written.

    No database on purpose: every method here is one `_audit` actually calls,
    and what is under test is what the run reports having written — not how the
    rows are stored, which `test_audit_freshness` covers against the real one.
    """

    def __init__(self, *, already_contactable: tuple[str, ...] = ()) -> None:
        self.findings: list = []
        self.events: list = []
        self.signals: list = []
        self.contacts: list = []
        self._contactable = set(already_contactable)

    def save_finding(self, finding) -> None:
        self.findings.append(finding)

    def record_event(self, event) -> None:
        self.events.append(event)

    def latest_audit(self, business_id: str) -> dict:
        return {}

    def record_contactability(self, business_id: str, *, address: str,
                              source_url: str) -> bool:
        """Fills an absent address only, and says whether it did.

        The real repository's contract: `UPDATE ... WHERE email IS NULL OR
        email = ''`, returning whether the row changed. A business that already
        carries an address is left exactly as it was.
        """
        if business_id in self._contactable:
            return False
        self._contactable.add(business_id)
        self.contacts.append((business_id, address))
        return True

    def save_signal(self, signal, ranked, *, tenant=None) -> bool:
        self.signals.append(signal)
        return True


def test_a_failed_run_says_that_its_output_is_already_in_production():
    """`_audit` persists before anything reviews the run — deliberately, and
    unchanged here. What was missing is a record that says so, so that "failed"
    and "its results are live" are readable in one place."""
    memory = RecordingMemory()
    business = Business(id="b-live", name="Al Waha Dental",
                        website="https://alwaha.test")
    agent = ToolAgent(recipes.get(VERIFY), repository=memory,
                      tenant="tenant-toolrunner")
    agent._targets = {business.website: business}
    agent.result = toolrunner.Result(
        recipe=VERIFY, agent_id=RESEARCHER,
        steps=[_fetch_failed(GUARDED,
                             [_response(business.website, body=HOMEPAGE)])])

    agent._audit(agent.result)

    assert memory.events, "the pass wrote nothing, so there is nothing to tell"
    assert "site(s) marked verified" in agent.live
    assert "observation record(s)" in agent.live

    reviewed = agent.review(agent.plan("ignored"), PRODUCED)
    assert not reviewed.claims_done
    assert GUARDED in reviewed.summary
    assert reviewed.live_outputs == agent.live, (
        "the mission record cannot tell whether this run's output is live")


def test_a_run_that_wrote_nothing_claims_nothing_is_live():
    """The clause has to be absent when it would be false."""
    assert ToolAgent(recipes.get(VERIFY)).live == ""
    assert _reviewed(GUARDED).live_outputs == ""


# --------------------------------- a claim of live output is a claim of a write


def _contacts_pass(memory, business: Business, body: str) -> ToolAgent:
    """One `_remember_contacts` over a page that publishes an address."""
    agent = ToolAgent(recipes.get(VERIFY), repository=memory,
                      tenant="tenant-toolrunner")
    agent._remember_contacts(
        {business.id: business},
        {business.id: _response(str(business.website), body=body)})
    return agent


def test_an_address_a_page_states_is_only_live_output_if_it_was_written():
    """`record_contactability` fills an absent address and nothing else, so a
    business that already had one is unchanged by this pass. Counting the page
    rather than the repository's answer would have a failed mission claim it
    made that business reachable when it changed no row at all."""
    memory = RecordingMemory(already_contactable=("b-has-one",))
    business = Business(id="b-has-one", name="Al Waha Dental",
                        website="https://alwaha.test",
                        email="hello@alwaha.ae")

    agent = _contacts_pass(memory, business, PUBLISHES_AN_ADDRESS)

    assert memory.contacts == [], "the address already on the record was kept"
    assert "made contactable" not in agent.live, (
        "the run claims it made a business reachable and wrote nothing")


def test_an_address_this_run_did_write_is_reported_as_live():
    """The other direction, so the fix is not simply silence."""
    memory = RecordingMemory()
    business = Business(id="b-reachable", name="Al Waha Dental",
                        website="https://alwaha.test")

    agent = _contacts_pass(memory, business, PUBLISHES_AN_ADDRESS)

    assert memory.contacts == [("b-reachable", "info@alwaha.ae")]
    assert "1 business(es) made contactable" in agent.live


class DiscoveryMemory:
    """Just enough repository for one discovery pass.

    `first_pass` is the whole difference between the two states under test. On
    a first pass the repository has no record, so `resolve_business` reports it
    created one and `record_sighting` takes the insert. On a replay — the same
    business, source and instant, which is every acceptance retry — it resolves
    the existing record and the unique index refuses the insert, so a re-run
    after a crash is safe. Both answers come from the same fact, which is why
    they are one argument.
    """

    def __init__(self, *, first_pass: bool) -> None:
        self._first_pass = first_pass
        self.sightings: list = []
        self.signals: list = []

    def resolve_business(self, business) -> tuple[Business, bool]:
        return business.model_copy(update={"id": "b-osm"}), self._first_pass

    def record_sighting(self, sighting, classification, *, tenant=None) -> bool:
        if self._first_pass:
            self.sightings.append(sighting)
        return self._first_pass

    def save_signal(self, signal, ranked, *, tenant=None) -> bool:
        self.signals.append(signal)
        return True


def test_the_discovery_pass_under_test_declares_an_extractor():
    """The property the two tests below rest on, asserted where it can be read.

    `_remember` returns before reading anything when the recipe names no
    extractor — correct for such a recipe, and it empties every assertion about
    what a pass recorded. Naming the extractor here means a recipe that loses
    it fails as itself, rather than as two tests that quietly pass over nothing.
    """
    assert recipes.get(DISCOVER).extractor == "openstreetmap"


def _discovery_pass(memory) -> ToolAgent:
    """One `_remember` over an Overpass response the extractor can read."""
    agent = ToolAgent(recipes.get(DISCOVER), repository=memory,
                      tenant="tenant-toolrunner")
    agent.result = toolrunner.Result(
        recipe=DISCOVER, agent_id=RESEARCHER,
        steps=[toolrunner.Step(
            tool="http-fetch", invoked="overpass", passed=True,
            proves="what the source stated", evidence=[OVERPASS])])
    agent._remember(agent.result)
    return agent


def test_a_replayed_sighting_is_not_reported_as_a_row_this_run_wrote():
    """`scan.record` returns a `Recorded` for every sighting it resolved,
    stored or not — `stored` is False when the insert was refused as a
    duplicate. Counting the list rather than the flag makes every acceptance
    retry of a discovery pass claim it wrote the same rows again."""
    memory = DiscoveryMemory(first_pass=False)

    agent = _discovery_pass(memory)

    assert agent.recorded, "nothing was extracted, so nothing is under test"
    assert not any(r.stored for r in agent.recorded)
    assert memory.sightings == []
    assert "sighting(s) recorded" not in agent.live, (
        "a replayed scan claims it wrote sightings it did not write")


def test_a_sighting_this_run_did_store_is_reported_as_live():
    """The first pass writes, and says so."""
    memory = DiscoveryMemory(first_pass=True)

    agent = _discovery_pass(memory)

    assert len(memory.sightings) == len(agent.recorded) == 1
    assert "1 sighting(s) recorded" in agent.live


@pytest.mark.parametrize("first_pass", [True, False])
def test_the_summary_and_the_live_record_count_sightings_the_same_way(first_pass):
    """`implement` writes "N sighting(s) recorded" into the summary from
    `_remember`'s return, and `live` reports it under the same words. One
    outcome saying "1 sighting(s) recorded" while its live record says nothing
    was written is the contradiction, not a smaller version of the fix."""
    memory = DiscoveryMemory(first_pass=first_pass)
    agent = ToolAgent(recipes.get(DISCOVER), repository=memory,
                      tenant="tenant-toolrunner")
    result = toolrunner.Result(
        recipe=DISCOVER, agent_id=RESEARCHER,
        steps=[toolrunner.Step(
            tool="http-fetch", invoked="overpass", passed=True,
            proves="what the source stated", evidence=[OVERPASS])])

    stored = agent._remember(result)

    assert stored == len(memory.sightings)
    assert (f"{stored} sighting(s) recorded" in agent.live) is bool(stored), (
        "the summary would claim a write the live record does not")
