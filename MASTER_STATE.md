# MASTER_STATE

The single reconciliation point for Qevik. Read this before starting a
workstream; update it when one lands. Everything here is meant to be checkable
against the repository — if a line cannot be verified, it does not belong.

**Last reconciled:** 2026-08-27 (opportunity engine: extract, detect, rank)

---

## Hard architectural constraints

These are not preferences. A change that breaks one does not land.

1. Policy is deterministic and sits **above** the planner.
2. The planner proposes; it never authorises.
3. Approval is a real boundary, not a flag on a plan.
4. Evidence and provenance are first-class.
5. Credentials live behind the vault boundary only.
6. Workers are disposable and independently recoverable.
7. Agents are declarative records, not permanent processes.
8. The scheduler is the only component that dispatches.
9. No agent recruits another agent.
10. No LLM becomes an orchestrator with authority.
11. Chat never executes anything directly.
12. Self-modification always requires human approval.
13. Unknown cost is never rendered as zero.
14. **Tests passing is not completion.** The live operational path is verified.

---

## Operational now

| Capability | Evidence |
|---|---|
| Mission lifecycle, event-sourced | `mission/service.py`, `ALLOWED` table |
| Deterministic policy above the planner | `mission/policy.py` |
| Atomic multi-worker claims | `mission/claims.py`, `verify_two_workers` 7/7 on the real DB |
| Isolated git workspace per mission | `mission/gitspace.py` |
| **Scratch clone; production read-only** | `mission/scratch.py`, `verify_scratch_isolation` 34/34 |
| Sandboxed deterministic agents | `mission/adapter.py`, `fabric/sandbox.py` |
| Chat → plan → approval → mission → worker | `verify_self_improvement` 29/29 |
| Credential vault, one boundary | `credentials/location.py`, `verify_vault_boundary` |
| Recurrence → missions | `mission/recurrence.py`, `verify_recurrence` 10/10 |
| **Per-mission origin allow-list** | `mission/origins.py`, `test_origins.py` 31 |
| **Unattended nightly recurrence** | `rec-execution-canary`, `verify_recurrence` 19/19 |
| **Budgets + credentials checked before dispatch** | `tenant_headroom`, `usable_for`, `test_worker_dispatch.py` 14 |
| Provable branch cleanup | `infra/prune_mission_branches.py`, 17 tests |
| Console, mobile-first | `apps/control/src/index.html`, `verify_console_logic` 27/27 |
| Backups, verified by restore | `qevik-backup.service`, nightly |

Full suite: **3208 passed, 33 skipped**.

---

## Roadmap components — verified, not assumed

Checked what is **wired**, not what exists. Three of the four first items were
built and only partly connected, which is a different problem from missing.

| Component | Module | Status |
|---|---|---|
| Agent registry | `fabric/agents.py` | **now wired into dispatch.** Was consulted by policy and the adapter, but not by the scheduler: `demands_from` got no `agent_for`, so every mission looked like it needed no credentials and had `placement=EITHER` |
| Scheduler | `fabric/scheduler.py` | wired (worker + control plane) |
| Budgets | `fabric/budgets.py` | **now checked before dispatch.** `assess()` exists so "the scheduler can decline to start work it cannot finish" and nothing called it — the budget was consulted only *after* the work, by `_charge` |
| Message protocol | `fabric/protocol.py` | **built, imported by nothing.** Its consumer is agent-to-agent capability routing, which needs the CLI/tool agents. Not wired speculatively |
| Tools | `fabric/tools.py` | wired, **and now enforced per step** |
| Recipes | `fabric/recipes.py` | `execution-canary`, `discover-uae-dental` |
| **Discovery states + signals** | `opportunity/discovery.py`, `signals.py` |
| **Tool-executing worker role** | `mission/toolrunner.py`, `verify_tool_role` 35/35 on the server |
| **Extract → sighting → opportunity → rank** | `opportunity/extractors.py`, `detect.py`, `ranking.py`, `verify_opportunity_engine` 49/49 |
| **Sighting memory** | `atlas_sightings`, `verify_discovery` 25/25 |
| Sandbox | `fabric/sandbox.py` | wired, `verify_sandbox` |

### What the two dispatch gaps cost

A mission whose agent needs a model credential nobody had configured was
**dispatched, reported as running, and failed at the provider** — exactly what
`usable_credentials`'s own docstring warns about. Demonstrated:

    no agent_for (how it ran)      dispatchable=['m-1']  missing=()
    with agent_for, no creds       dispatchable=[]       missing=('qwen','anthropic','openai')
    with agent_for, qwen present   dispatchable=['m-1']  missing=()

`Mission.agent_id` is now recorded when the plan is attached, from the same
value `policy.decide` was given — so the blast radius a person approved and the
one read at dispatch are the same value, and the control plane's schedule view
stops showing a mission as dispatchable that the worker would hold.

## Closed since

**Origin surface.** `GET /api/missions/origins` lists what a mission may be
pointed at — names and kinds, **no filesystem paths**. (Declared above
`/{mission_id}`: it was first written below it, where every request for it was
answered by the detail handler looking for a mission called "origins". Pinned by
a test that reads the route table, because a 404 from either reads the same.) `QEVIK_ORIGINS` is the
single declaration the control plane *and* the worker read, so a customer origin
configured once is one the console can offer and the worker can serve; a name
given both by env and `--origin` is refused rather than one silently winning.
Both `POST /api/missions` and chat `/decide` validate the key server-side (400
on unknown) and the worker re-checks at dispatch. The approval screen offers
radio options — a name and a sentence each, Qevik preselected and marked before
it is chosen. Verified at 390×844: `doc.scrollWidth 390`, no overflow.

**No silent fallback.** Three refusals now sit together in the worker, all
before any agent runs:

| substitution | refusal |
|---|---|
| a worker running an agent the plan was not approved with | `policy.refuse_agent_substitution` |
| a repository the mission did not name | `origins.UnknownOrigin` → BLOCKED |
| work an allowance cannot carry | `refuse_over_budget`, via `budgets.assess` across every scope |

`infra/verify_no_fallback.py` — 23 checks against **real worker processes**,
each with a paired positive control.

## Known gap, found by looking

*(The previous gap — the console could only create Qevik-origin missions — is
closed above.)*

## Agents, tools, recipes — the 300-assistant infrastructure

An agent is a **record**, not a process. There are no 300 daemons; there is a
registry of declarations and a scheduler that dispatches against them.

| | |
|---|---|
| `fabric/agents.py` | who does it, and the worst it can do |
| `fabric/tools.py` | what it may reach — **now enforced per step** |
| `fabric/recipes.py` | how one job is done, versioned, in git |
| `fabric/sandbox.py` | the containment those steps run inside |

**The tool contract was consulted only in aggregate** — to decide network and
sandbox needs — and never per step, so an agent declaring `("filesystem",)`
could run any command including one reaching the network, under isolation
derived from a declaration that no longer described the work. `Step.tool` closes
it, and the *whole sequence* is refused before the first step runs.

**Recipes** are the primitive `CLAUDE.md` names: a model's only job is choosing
one by name. Not a plan (cannot authorise itself), not a workflow engine (no
conditionals, loops or variables), not runtime-configurable (the agent is
declared, because a runtime agent choice is a runtime blast radius). Validated
at **import**, so a bad declaration is a failing build rather than a blocked
mission at 3am.

`SELF_CHECK_STEPS` is now derived from the `execution-canary` recipe rather than
being a second copy of the same three commands.

## Deployed and running — 2026-08-27

The opportunity engine is **live on `qevik-core-01`**. Both nightly recurrences
executed on the deployed system, on their own workers:

    execution-canary            complete
    discover-dubai-dental-osm   complete
    120 sightings · 59 businesses · 53 opportunities

A second worker unit was needed: `policy.refuse_agent_substitution` refuses a
mission whose plan named a different agent, so the canary (`self-check`) and
discovery (`researcher`) cannot share one. `qevik-worker-research.service` is
that second worker; atomic claims already made it safe.

**Website verification runs on real data.** `verify-recorded-websites` fetched
40 recorded sites: 37 answered, 3 did not, with status, protocol and timing
recorded for each. Its targets come from Qevik's own memory rather than from any
proposal — a model cannot add a URL because a model cannot write a sighting.

### Four production faults this deploy found

None of these appear without two real workers and a real filesystem.

1. **Running a script as `root` against a service-owned state directory** left
   `missions.jsonl` root-owned. Both workers then failed to append; one crashed
   mid-claim.
2. **A refusal that could not write its event stranded its claim.** The refusal
   paths released on the normal path and not on an exception, so a
   `PermissionError` one line earlier left the mission held for the full
   fifteen-minute staleness window with both workers reporting "went to another
   worker". A refusal that leaks a claim is worse than the thing it refuses.
3. **Each worker claimed the other's mission and blocked it.** The agent guard
   is correct but runs *after* the claim, and the claim is a race — so both
   recurrences were BLOCKED within a minute. A worker now filters its own queue,
   and the backstop **releases instead of blocking**: "not by me" is not a defect
   in the mission.
4. **A retried mission could never run again.** `scratch.prepare` and
   `GitWorkspace.create` both refused to reuse a directory, reasoning about two
   *different* missions — which the mission id already prevents. A retry now
   gets a fresh directory beside the previous attempt, which is kept as evidence.

## Business discovery — built

**The sentence this exists to make unsayable:** *Qevik found it, therefore it is
new to Google Maps.* Qevik's memory being empty is a fact about Qevik.

Four states; exactly one claims anything about the world, and it says
`TO_SOURCE` so nobody can round it up. `PROVEN_NEW_TO_SOURCE` is unreachable
without a `Novelty`, which cannot be constructed without naming the source, the
field read and the value read — so the strong state requires having looked
something up, and a reviewer can check the same field.

**Observation / evidence / inference / action are four types, not four fields.**
Prose cannot be validated, so the rules are structural: an observation has no
confidence field; an inference names the evidence it rests on by fingerprint and
may not be certain; an outward action cannot be constructed without
`needs_approval`. A test asserts the label agrees with `mission/policy.py`,
which is the actual boundary.

Memory extends the existing `OpportunityRepository` — `resolve_business` already
resolves on strong keys only. `atlas_sightings` is one row per *observation*,
with a unique index so a replayed scan is safe, and a sighting keeps the state it
had at the time rather than being rewritten to agree with the present.

`rec-daily-business-discovery` at 04:15 UTC, origin `none`, reaches the queue
with nobody asked. Discovery running unattended and contacting nobody unattended
are both true at once.

`GET /api/discovery` only — the surface offers no way to execute anything, and a
test asserts every route is GET.

### Now executed — the tool-executing role

`mission/toolrunner.py` carries out a declared recipe through the tools its
agent is registered for, satisfying the same `CodingAgent` protocol every other
role does. The worker is unmodified and does not know it is different: a
non-coding agent is a **role**, not a second worker. `--agent research`.

**Not a model with tools.** A model may propose `recipe = "..."` — a key that
resolves or is refused. It may not propose a tool (the recipe declares them,
the registry bounds them), a URL (`permitted_urls()` comes from the recipe; a
fetch of anything else is refused before a socket opens), a step (recipes have
no variables) or an interpretation (the runner returns what the server said).

**Proven on `qevik-core-01`: 35/35, nothing unverified.** Including the whole
chain in one test — `rec-daily-business-discovery` → tick → mission → research
role → `discover-uae-dental` → `http-fetch` → evidence → durable report, with an
assertion that the report claims nothing about any business. The real production worker dispatched the
role, fetched a public URL through the address guard, recorded evidence and
completed with a durable report naming the recipe, the agent, the tools actually
invoked and each evidence fingerprint. Cost reported honestly absent.

Local runs report the fetch step as **NOT VERIFIED**: a controlled fixture is on
loopback and the guard refuses loopback — correctly, and that refusal is itself
under test, so the two requirements are mutually exclusive. This machine's
resolver also answers made-up names.

`rec-daily-business-discovery` now names `discover-uae-dental`, so the recurring
entry invokes the role through the ordinary scheduler path.

### Two code-writing assumptions it exposed

Both in the worker, both right for coding roles, both failing every successful
research run:

- *"reported success but changed no files"* — a research role leaves the
  repository as it found it. `AgentOutcome.produced_nothing` asks the outcome
  its currency; a coding agent is judged on files exactly as before.
- *committing* — `GitWorkspace.commit` refuses an unchanged tree. A role writing
  no files returns no commit. Not an escape for coding roles: one that claimed
  success and produced nothing was already refused upstream.

## The opportunity engine — built

The whole chain now runs: scheduler → mission → research role → recipe →
http-fetch → guard → Evidence → **extractor → Sighting → memory → detect →
rank** → persist → report → API.

**The extractor is a declaration, not a parser.** It declares which `Sighting`
fields it can produce — validated against the model at import — and a field it
does not declare cannot appear. OpenStreetMap first: public, free, no
credential, and **structured JSON**, so extraction is a mapping from named keys
rather than a model deciding what looks like a business name.

**Absence has three answers.** `OBSERVED` / `ABSENT_IN_SOURCE` /
`NOT_CONSULTED`. The last is the one that matters: a field nobody looked for is
not a field that is missing. The whole "no website recorded" detector rests on
it, which is why its suggested action is *verify*, not *sell*.

**Two detectors, and the absent ones are the point.** New business, and
no-website-recorded-by-the-source. `WEAK_WEB_PRESENCE`, `NEW_LOCATION`,
`COMPETITOR_CHANGE` and `HIGH_GROWTH_SIGNAL` are all left unbuilt with the
evidence each would need written down — adding them now would be detectors that
fire on absence of data.

**Ranking is deterministic and revenue is not scored.** Five weighted components
each carrying its own explanation. `value` is `UNKNOWN` with no amount, and the
column is nullable so a `DEFAULT 0` cannot undo the rule from a schema
definition.

### Proven on real data

A real production worker run on `qevik-core-01`, against the real Overpass API:

    mission: complete
    59 sightings recorded    (real Dubai dental practices, several Arabic-named)
    112 opportunities        (59 new_business + 53 no-website-recorded)
    every one with evidence fingerprints and worth UNKNOWN

That is the milestone: Qevik discovered real businesses, remembered them, and
produced an actionable next step for each, backed by evidence.

### Three bugs it found

- **Every website-less business was recreated on every scan.**
  `resolve_business` matches on strong keys only, and a business with no domain,
  email or phone has none. A nightly run would have produced one duplicate per
  night, for ever. The source's stable id is now a namespaced **`source:`** key — not
  `place:`, which means "a different physical location, overriding every
  other agreement" and would stop two mapping providers ever agreeing on
  one business. The first attempt used `place:` and broke exactly that,
  caught by the discovery harness. Found by scanning one fixture twice.
- **`atlas_opportunities` already existed** — the findings-based funnel table.
  `CREATE TABLE IF NOT EXISTS` silently did nothing and the index failed on a
  missing column. The new table is `atlas_signals`, named after its model.
- **The crawler impersonated a browser.** `USER_AGENT` was
  `Mozilla/5.0 (compatible; QevikResearch/1.0; +https://qevik.ai/crawler)`, and
  Overpass answers that with **406**. The first real run failed on it — and the
  extractor correctly refused the HTML error page rather than reading it. Two
  guesses were wrong before varying one token at a time isolated it: the word
  **`crawler`** in the URL. `/bot` and `/research` both pass. Now
  `QevikResearch/1.0 (+https://qevik.ai/research; research@qevik.ai)`, which is
  also the courtesy every crawling policy asks for.

## Superseded — the link that was missing

The seven steps the brief names are: fetch, extract declared fields, create
evidence, create sighting, compare with memory, classify, produce an opportunity
only when evidence supports it.

**1–3 are the tool role** (proven on the server). **4–7 are
`opportunity/scan.py`, `discovery.py` and `signals.py`** (proven in
`verify_discovery`, 25/25). What does not exist is the join: turning a fetched
page into a `Sighting` needs a **source-specific extractor** — which fields, in
which markup, mean which business.

That is deliberately not built. It is source-specific work, and the brief was
explicit that the goal is not to make dental discovery work but to prove the
generic primitive. Building an extractor now would be picking a source before
reassessing the architecture, which is the step the brief asks for next.

## Blocked, precisely

**Verifying that a business has no website needs a search provider.** 53 of the
59 discovered businesses have no website recorded by OpenStreetMap. That is a
fact about OpenStreetMap, and upgrading it to a fact about the business means
looking for one — which needs a search API. Brave was approved and never
supplied. Until then those 53 stay honestly labelled "the source records none",
with a suggested action of *verify*, and the 6 with recorded sites are verified
for real.

This is an external dependency, not a design problem, and nothing downstream is
waiting on it: the six verified sites already produce evidenced opportunities.

## Next — chosen on dependency, not roadmap order

The three candidates were: (A) a mobile opportunity surface, (B) CLI/tool
agents, (C) the flagship site.

*(Superseded — that shipped. See "Deployed and running".)*

*(Superseded — the evidenced `WEAK_WEB_PRESENCE` detector shipped. See
"Evidenced weak web presence" below.)*

*(Superseded — that shipped and was proven on a real production opportunity.
See "Approved opportunity to delivered artefact".)*

*(Superseded — that shipped and was proven against `mission-821a8e7d171d`. See
"Artefact review".)*

*(Superseded — the queue shipped and was proven on production. See "Accepted
artefacts awaiting publication".)*

*(Superseded — the first real publication is live. See "First real
publication".)*

The chain is complete end to end: discovery → verification → evidenced audit →
ranked opportunity → approval → delivery → artefact → review → accepted queue →
publication authorisation → policy → publication → a live page.

**The next milestone is telling the business it exists** — the first act that
reaches a person rather than a server. It is externally blocked on a sending
identity, and it is a larger boundary than publishing: a page nobody visits
harms nobody, and an email does. Do not start it without a sending identity and
an explicit decision about approaching businesses who have not asked.

*(That prerequisite shipped — see "Publication state, closed from the
timeline".)*

Nothing unblocked remains before outreach. The chain is complete and every state
in it is derived from the timeline.

**Previously: B, narrowed to a worker role that executes tool-step recipes.**

The reasoning is a dependency chain, not a preference. Discovery's
`http-fetch` recipe is declared and nothing runs it, because every worker role
is code-writing shaped — plan, implement in a worktree, review a diff. A fetch
recipe has no diff. Until that role exists:

- **A has nothing to show.** The opportunity surface is built and returns real
  rows, but the only rows are ones a test or a script put there. Making it
  prettier before discovery can fill it is decorating an empty room.
- **C is furthest from evidence.** A flagship site whose headline capability
  cannot run unattended is a claim rather than a product.
- **B unblocks both**, and it is the generic piece: the same role that runs a
  fetch recipe runs a research, media or publishing recipe. That is what makes
  the agent abstraction infrastructure for 300 assistants rather than a coding
  tool with general-sounding names.

Scope it as: a `Roles` variant whose implementer interprets a recipe's steps by
tool — `crawler.fetch_steps` for `http-fetch`, the adapter for `shell` — and
returns `Evidence` rather than a commit. The acceptance is `discover-uae-dental`
running through the real worker and leaving sightings in the database.

`fabric/protocol.py` remains built and unconsumed. Its consumer is agent-to-agent
capability routing; a single recipe execution does not need it, and wiring it
speculatively would be architecture for its own sake.

## Completed and in progress

### 1. Origin as a per-mission property — **DONE**
`--repository` is gone; the worker refuses it rather than ignoring it. A mission
declares `origin_name` (a **key**, never a path) and the worker resolves it
against `mission/origins.py` at dispatch. Built-ins `qevik` (derived from
`__file__`) and `none`; customer repositories come from `--origin NAME=PATH` and
a entry pointing at Qevik's own repository is **refused at start-up**. An
unregistered name blocks the mission — never falls back to the default, because
the default is Qevik. `test_origins.py` 31 tests; `verify_scratch_isolation`
38/38 including the unregistered-name path end to end.

### 2. First real unattended recurrence — **DONE**
`rec-execution-canary`, nightly at 02:30 UTC. Runs the self-check agent end to
end so a broken execution path is found by a failed mission on the phone rather
than when somebody needs the path. Reaches the queue with nobody asked, and only
because its origin is `none` — the identical plan against `qevik` waits for a
person. `Recurrence.modifies_qevik_itself` (a field that could lie) is replaced
by `origin_name` (resolved). `verify_recurrence` 19/19 including the canary run
through the real worker.

### 3. Production leftovers — **mechanism DONE, cleanup correctly refused**
`infra/prune_mission_branches.py`, dry run by default, 17 tests. Inspected
production 2026-08-26: **0 provably stale, 13 protected** — the control plane has
no `missions.jsonl`, so nothing can be checked against and the tool refuses.
Three branches carry corroborating evidence of harness origin (`/tmp/qevik-e2e-*`
worktrees), reported and deliberately not treated as proof. Re-run once the
worker has recorded missions.

---

## Evidenced weak web presence — built

The verification recipe had been fetching real homepages and recording what each
server said, and **nothing read any of it**. Genuine evidence, with provenance,
that produced no conclusion. That is now joined.

### What the join actually is

Not a second auditor. `detectors/website.py` already held the rules — what
counts as slow, what counts as thin, what a missing viewport means — and the
temptation was to write a second set that reads stored evidence. Two
implementations agree on the day they are written and diverge the first time
somebody moves `SLOW_RESPONSE_SECONDS`.

So the rules were lifted onto a neutral `PageObservation`: the requested URL,
the answering URL, status, content type, elapsed time, bytes, body, and whether
the body is complete. A live inspection builds one from an httpx response; the
verification join builds one from `Evidence.observed`. Both then call the same
`findings_from`. An audit of stored evidence produces exactly what a live
inspection would have produced from the same page, and that is proven rather
than asserted.

### What the evidence is not allowed to support

Three refusals, each one a false finding that would otherwise have shipped, and
each with a negative control proving the dangerous version fires:

- **A refusal is not a response.** `fetch_steps` records a blocked address, a
  robots exclusion and a dead host as evidence too — status 0 with an error.
  Auditing those would report a business whose homepage Qevik's own guard
  refused to fetch as a business with a broken homepage. They are `NOT_VERIFIED`
  and produce nothing. The negative control: the same address answering does
  produce findings, so the silence is the refusal and not a broken auditor.
- **A truncated body is not a short page.** A body cut at 256 KB, or dropped for
  being enormous, cannot support "this page has no h1" — the h1 may be in the
  part that is missing. Head-derived findings survive truncation only when
  `</head>` was actually reached inside the bytes that arrived; whole-document
  findings are suppressed entirely. The negative control: the same bytes marked
  complete support them.
- **Evidence of the wrong kind is not weak evidence.** A DNS record carries no
  status and no markup, and is refused rather than read with defaults. Defaults
  are how a missing field becomes a confirmed absence.

### The offer connection, and the gap it exposes

`ANSWERED_BY` maps an audited defect to a declared opportunity key, and
`answerable()` intersects that with what `offer-website` **declares** it
answers. Three map: `site_unreachable → broken`, `slow_response → performance`,
`thin_content → thin_content`.

Six do not. A missing viewport, a missing title, a missing meta description, no
structured data and plain HTTP are all real, observed, and answered by no offer
in the catalogue. Those still become observations on the signal — they were seen
— and the signal's action stays **inside Qevik** rather than becoming a sale.
Widening `offer-website.answers` to cover them is a reviewed decision somebody
should make deliberately; inferring it in the detector would make the promise
without the review. **Recorded as an open product decision, not as a defect.**

### Why a second recurrence

`rec-nightly-website-verification` at 05:00 UTC, after the 04:15 discovery, so a
business found tonight is audited tonight. It is a separate recurrence rather
than a second half of discovery because the two are bounded by unrelated numbers
— what a source returns, versus how many of somebody else's servers Qevik will
touch in one night — and because they fail differently. Overpass being down must
not stop Qevik auditing the sites it already knows.

Without this the milestone would have been code that nothing runs. The last
session found exactly that fault in the discovery recurrence, which had been
pointed at a placeholder recipe with no extractor.

### Drift closed while here

`recorded_websites()` and the attribution lookup were about to become two
bounded reads of a table that changes — one to decide what to fetch, one to
decide whose site it was. They are one query now, `businesses_by_website()`,
with the URL list derived from it. The two-query version would have audited
forty sites and attributed thirty-eight, silently.

### Three faults the deploy found, and one of them mattered

The suite was green and the harness passed 43 checks. Deploying found three
things none of them could.

**1. The worker opened business memory only for a recipe with an `extractor`.**
This recipe declares `audit` and `targets_from` and no extractor, so it ran with
no repository, computed no targets, and failed. The condition lived in the
worker while the fields that decide it live on the recipe. `Recipe.needs_memory`
derives it in one place now.

**2. A targets recipe with no targets fell back to the URLs in its steps** —
which is the literal word `TARGETS`. The fetcher tried to resolve it as a
hostname, and the mission failed with what read like a DNS problem. This is the
worse of the two, because it is what made the first invisible: a silent fallback
from "what Qevik knows" to "whatever the placeholder happens to say". An empty
backlog is a normal night and now says so.

**3. Being blocked was recorded as a broken website. This is the one that
mattered.** The first real pass fetched twelve UAE dental clinics and filed
three as having broken homepages, each with an **outward action attached** —
ready for somebody to approach a business and tell them their site returns an
error. All three were `403`, which is a bot policy, not a defect: the page a
human visits is almost certainly fine.

Two of the four opportunities that first pass produced were false, and they were
false in the only direction that reaches a stranger. `401/403/407/429` now
establish nothing — NOT_VERIFIED, in the same sense as everywhere else. A `404`
is a homepage that is not there and a `5xx` is a server failing for everybody;
both stay findings. The two false signals were deleted from production.

The evidence was never wrong. It still records exactly what each server replied.
What changed is only what may be concluded from it.

### Acceptance

`infra/verify_weak_web_presence.py` — **61 checks, 0 failed**, ending with the
whole chain through the real production `ToolAgent`, and six proving the backlog
rotation against real Postgres with the pre-fix query as the negative control.

Gate: **3470 passed, 33 skipped, 0 failed.**

Measured on production, two real passes of twelve sites each:

| | |
|---|---|
| sites fetched | 24 of 359 recorded |
| opportunities raised | 5 |
| **sellable** — `offer-website`, needs a person | **3** — one 404 homepage, two answering in 3.0s |
| real but unsellable — no offer declares an answer | 2 — missing meta description |
| businesses marked verified, rotating the backlog | 24 |

The harness also found one wrong assertion of mine: I had claimed a truncated
body supports *nothing*, when the URL's scheme is a fact that does not live in
the body at all. Transport findings legitimately survive truncation.

## Next — the first customer-deliverable workflow

**An approved opportunity becomes a mission.**

The chain now runs: recurrence → mission → tool agent → recipe → guarded fetch →
evidence → audit → finding → ranked signal → console, with an OUTWARD action
naming `offer-website` and marked `needs_approval`. A person can see it on a
phone.

And approving it does nothing. `atlas_signals` is read by the console and by
nothing else; `policy.decide` gates *missions*, and a signal is not one. That is
the whole remaining structural gap between "Qevik knows what to sell" and "Qevik
does the work", and it is the correct next milestone for three reasons:

1. **It is deterministic.** No provider credential. The blocked search provider
   and the blocked model provider are both irrelevant to it.
2. **It creates no second orchestration path.** An approved signal produces a
   mission with a declared recipe, and the existing scheduler, policy layer,
   claims, budgets, scratch isolation and worker run it unchanged.
3. **Everything downstream of it is externally blocked.** Outreach needs a
   sending identity; publishing needs hosting. Building either before this one
   would stall on a dependency this one does not have.

Scope, deliberately ending inside the building:

- An operator approval on a signal, recorded against the signal, by a person.
- A declared delivery recipe — `offer-website` has an executor; it needs a
  recipe declaration so a mission can name it as a key like every other.
- Dispatch through the existing scheduler into a scratch workspace.
- An artefact and a mission report a person reviews.

**It stops there on purpose.** Publishing the site and contacting the business
are separate OUTWARD acts, each gated, and both currently blocked externally.
The first customer-deliverable workflow ends at *a reviewed draft exists*, which
is a real deliverable and an honest one.

## Approved opportunity to delivered artefact — built and proven on production

The edge that did not exist. `atlas_signals` was read by the console and nobody
else, so approving an opportunity changed nothing.

A signal still never becomes a mission. `mission/delivery.py` creates one that
**references** it, through the three calls `recurrence.enqueue` already used —
`service.create`, a transition to PLANNING, then `attach_plan`, which runs
`policy.decide`. No route reaches the queue that a person's own request could
not.

The approval decides *that* the work happens, not what it is: the recipe comes
from `OFFER_RECIPES`, keyed by the capability the opportunity's own suggested
action named. `enqueue` takes a signal **id** and reads the record itself,
because a caller that could pass the record could pass one it had edited.

### Proven on a real production opportunity, 2026-08-27

| | |
|---|---|
| opportunity | `sig-20260827054352236624`, Julian's Barber Shop, score 0.802 |
| findings | `missing_h1`, `slow_response` — both in `BUILDABLE` |
| approval | `opportunity_approved` by an operator through `POST /api/missions/deliver` |
| mission | `mission-821a8e7d171d` |
| policy | queued without asking again: cheap, reversible, confined |
| recipe / agent | `deliver-website` / `website-builder`, origin `none` |
| artefact | `index.html`, `robots.txt`, `sitemap.xml`, `provenance.json` — committed to `mission/mission-821a8e7d171d` |
| report | `2026-08-27_deliver-deliver-website-for-http-www-julianhaird_mission-821a8e7d171d.md` |
| outward acts | none. Not published, nobody contacted |

The provenance records `mode: modify`, `site_state: weak`, and the two defects
it answers — and `not_published_for_want_of_a_source: [email]`, which is the
build declining to invent a contact detail nobody recorded.

### The approval is bound to the action

Four corruptions of the mission record between approval and execution, each run
through the real worker against the real approved opportunity, in an isolated
timeline. All four refused, with a positive control proving the same path
completes untampered — **11 checks, 0 failed**.

| changed after approval | outcome |
|---|---|
| recipe → `discover-dubai-dental-osm` | BLOCKED: *approved for `deliver-website`* |
| `signal_id` → a different, unapproved opportunity | BLOCKED: *that opportunity is `open`* |
| agent → `researcher` | not run by this worker; nothing built |
| origin → `qevik` | BLOCKED: *would run against Qevik's own repository* |

### Faults the run found

Five in the build, and two in the gate itself.

- `--agent` choices were hand-written beside `REGISTERED_AS`; the worker knew
  the role and its own command line rejected it.
- `needs_memory` did not count `delivers`, so every delivery blocked itself for
  having no approval it could read.
- `DISPATCHABLE` did not include `website-generator`.
- `get_business` is tenant-scoped and a discovered business belongs to nobody by
  design — every production opportunity was unreadable. Read with `ALL_TENANTS`
  as `scan.py` documents, with an explicit ownership check.
- **The recipe guard keyed on the recipe declaring `delivers`**, so substituting
  a *research* recipe bypassed it entirely and the mission ran whatever it had
  been changed to. Found only by checking the tamper failed for the *right
  reason*. The invariant is on the mission naming an approval now.

In the gate: a check ran unconditionally and *performed* the approval it was
meant to find already done, dirtying production — reverted, since no operator
had decided anything. And the first tamper run reported four clean refusals
while the worker had never started, because `--require-atomic-claims` correctly
refused a blanked DSN. Only the positive control caught it. Silence is not
success.

### Where it stops

At a file and a report. `website-builder` declares one tool and it is not a
network tool, so a delivery recipe naming an HTTP or shell step is refused by
`recipes.validate` at import. Publishing and outreach are separate outward acts
with no route from here, and both remain externally blocked.

## Artefact review — built and proven on the real delivered mission

The artefact was a commit on a mission branch and the only way to see it was a
`git show` printed in the report. The workflow's last step was a person with
SSH.

**Smallest slice.** No new page, no nav entry, no parallel store. The card
extends the mission detail page a reviewer already opens, and the decision lands
on `atlas_business_events` beside `opportunity_approved`.

`mission/artefact.py` reads and only reads — `ls-tree` and `show`, nothing else.
`GitWorkspace` is deliberately not reused: a reader that can commit is one
somebody eventually commits with.

### Proven against `mission-821a8e7d171d`, 2026-08-27 — 31 checks, 0 failed

Everything read over HTTP from the running control plane. No SSH and no git in
the review path.

| | |
|---|---|
| artefact | `index.html` (1,967 B), `provenance.json`, `robots.txt`, `sitemap.xml` |
| commit | `2d77a5f27c684b39297a0ad9b359d38e621eb331` |
| chain on screen | opportunity, scope, approver, evidence ×3, recipe, agent, tool, origin, workspace, branch, report |
| decision | `accepted`, by `review-operator`, naming that commit |
| durability | survived a `systemctl restart qevik-control` |

### The three boundaries, each attempted

| attempted | result |
|---|---|
| `../../../../etc/passwd` | 404 |
| `artefact/../../../etc/passwd` | 404 |
| `.qevik-scratch` — in the commit, not the delivery | 404 |
| a file not in the commit | 404 |
| a repository outside the scratch root | refused |
| `git fetch` through the reader | refused |
| an unauthenticated read | 401 |
| a decision nobody declared | 422 |

### Nothing left the building

The artefact commit is unchanged by the review; the repository has no remote;
the mission branch is merged into nothing; no branch was created or moved; the
mission was not transitioned and recorded no new commit. Reading needs READ and
deciding needs EXECUTE, because the next boundary reads the decision.

### The commit is what was reviewed

A mission branch can be rebuilt. If a review named only the branch, "accepted"
would silently come to mean whatever is on it now — an acceptance inherited by
an artefact nobody saw. The record stores the commit id, proved by moving the
branch after a review and checking the record still names the old one.

### Customer markup cannot execute in the operator's session

Proved with a pane that records which DOM property is written, not by grepping
for `textContent`: a grep passes when somebody leaves the word in a comment and
assigns `innerHTML`. The body arrives via `textContent`, `innerHTML` is never
touched, and the injected script does not run.

### Found while building

- The control unit did not declare `QEVIK_SCRATCH`; it worked only because the
  reader's default and the workers' `--scratch` happened to be the same string.
  Now declared, with a test that fails if they diverge — a disagreement there is
  a review surface reporting every artefact as missing while every mission looks
  fine.
- The artefact card rendered **below** the plan, commits, model calls and
  history. On a mission whose purpose is to be reviewed, a reviewer had to
  scroll past four cards about how it ran to reach the thing they came to judge.
  Found by screenshotting and looking, not by a test. It leads now.
- Two of my own assertions were wrong: `esc` leaves `onerror=alert(1)` as
  harmless literal text, so asserting its absence failed a correctly escaped
  payload; and `API` is a top-level `const`, so stubbing it from outside the
  sandbox never took and the handler had been falling back to an error message.

### Operational finding

`QEVIK_ADMIN_PASSWORD` in `/opt/qevik/atlas.env` **does not match** the stored
hash for `admin`. Both production gates needed a purpose-made operator, created
and removed each time, because resetting a live operator's password to run a
test would lock out the person who uses it. **Nothing in the review surface is
usable until `admin`'s password is re-established.** Not fixed here: it is a
credential decision, not a defect in this milestone.

Three identical `accepted` decisions are on the timeline, one per gate run. They
are kept. Deleting rows from an append-only record to tidy a test would
undermine the property this milestone exists to establish.

## Accepted artefacts awaiting publication — built and proven on production

An acceptance existed only as an entry on a timeline nothing queried. It is now
work that is visibly waiting.

**Derived, not stored.** No `awaiting_publication` table, and there must not be
one: acceptance is a decision somebody made, the timeline holds it, and a second
copy is a second thing that can disagree with the first.

One query gives four properties rather than enforcing them separately.
`DISTINCT ON (mission_id) ORDER BY at DESC` takes the latest decision and the
`accepted` filter runs **after** that fold — so a withdrawn acceptance is absent
rather than present, and several identical acceptances are one row. The commit
comes from the decision's own record, never from `mission/<id>`. Tenancy runs
through the opportunity the review names, because `atlas_business_events` has no
tenant column: it is one shared timeline per business, by design.

Nothing is inferred from mission status or branch state, and a test asserts
`atlas_missions`, `ls-tree` and `rev-parse` appear nowhere in the query.

### Production evidence — 2026-08-27, 23 checks, 0 failed

Read over HTTP by a **READ-only** operator; looking is not deciding.

| | |
|---|---|
| queue row | `mission-821a8e7d171d`, Julian's Barber Shop |
| reviewed commit | `2d77a5f27c684b39297a0ad9b359d38e621eb331` |
| opportunity | `sig-20260827054352236624` |
| accepted | `2026-08-27T06:29:42Z` by `review-operator` |
| state | `AWAITING_PUBLICATION` |
| timeline | **3 identical acceptances → 1 queue entry** |

Unauthenticated read → 401. `POST`, `PUT`, `DELETE`, `PATCH` → 405. Reading it
twice recorded no decision, left the artefact commit unchanged, added no remote,
merged the branch into nothing and did not transition the mission. No filesystem
path appears anywhere in the response: where an artefact sits on a host is not a
fact this queue is about.

### The seam left for publishing

Nothing is "not yet acted on" in an *enforced* sense, because no outward act
exists to record. When publishing lands it records its own event and the filter
for it is one clause in the `WHERE` beside the one already there. Written down
rather than built: a `NOT EXISTS` against an event kind nothing writes is dead
code with a fixture-only test.

### Found by looking, not by testing

- A five-column table at 390px wrapped the commit id **one character per line**
  and repeated a caveat in every row — a table squeezed onto a phone rather than
  a design for one. It is a card list now.
- The card claimed *"waiting for publication"* unconditionally instead of
  rendering the state the API returned. That is the console answering a question
  the kernel already answers, which is what `test_the_console_carries_no_secret_and_no_business_logic`
  exists to prevent. It renders `r.state` now, and an unrecognised state shows as
  itself rather than as a guess.
- The screenshot fixture showed `scope` as `offer-website: performance`. The
  real field is the business's **website**; the approved scope lives on the
  mission and is not in this response. A picture of data that cannot occur.

The console size cap moved 88k → 92k for two genuine surfaces — the review card
and this queue — with the stricter rule its own comment requires: the
`[data-artefact]` pane must be written with `textContent`, asserted directly and
not only behaviourally.

## First real publication — live, 2026-08-27

**https://sites.qevik.ai/site-4acac34467c34f17/** serves the artefact a person
reviewed and separately authorised. HTTP/2 200, `x-qevik-host: sites`, 1,945
bytes, `robots.txt` disallowing indexing.

### The architecture already existed

`sites.qevik.ai` has served `/srv/sites/<slug>/current/` for 56 sites, and
`website/targets/public_host.py` publishes, promotes by symlink, and **fetches
the public URL and fails the deployment if a visitor would not get the page**.
The publication root came from that, not from a new invention. No publisher was
written; what was missing was the edge to it.

| added | why |
|---|---|
| `publication_approved` | a **third** decision, binding opportunity + mission + commit + site + person |
| `site-publish` tool | IRREVERSIBLE, network, the only capability that can make anything public |
| `site-publisher` agent | holds that one tool; not a shell |
| `publish-website` recipe | `publishes="offer-website"`; a recipe that both builds and publishes is refused |
| `artefact.files_at` / `read_at` | commit-addressed; a branch name, a ref or a path is refused |
| `mission.publishes` | one field; commit and address are re-read from the authorisation at execution |
| `qevik-worker-publish` | `ReadWritePaths=/var/lib/qevik /srv/sites`; `/opt/qevik/atlas` absent |

**The builder gained nothing.** `website-builder` still holds only
`website-generator`. A publication recipe naming `shell`, `http-fetch` or
`git-worktree` is refused at import.

**The address is derived, never requested.** `site_for(business_id)` produces it
and `known()` *is* that derivation, so "publishing to an unregistered target" is
not expressible rather than merely refused — there is no list to add to.

### Two approvals, because policy is above the planner

The publication authorisation binds *what* may go out. `policy.decide` then
independently held the mission at `AWAITING_APPROVAL` — *"site-publisher cannot
be undone, so a person approves the exact output"* — and was **not** weakened to
accommodate the first one. An irreversible act takes two operator decisions, and
nothing was published between them.

### Production evidence — 31 checks, 0 failed

| | |
|---|---|
| source mission | `mission-821a8e7d171d` |
| commit | `2d77a5f27c684b39297a0ad9b359d38e621eb331` |
| published | `index.html`, `provenance.json`, `robots.txt`, `sitemap.xml` |
| authorisation | `publish-operator`, that commit, that site |

Refused: unauthenticated (401), a commit nobody accepted (409), a commit that is
a path (422), a commit that is a branch name (422). Nothing existed on disk
before either approval. Afterwards: the mission branch still at the reviewed
commit, no remote, merged into nothing, source mission not transitioned, 57
sites, nothing written outside the site's own directory.

**The Qevik checkout is unchanged** at `ce4ffaa`, owned `501:staff`, while the
site is owned `qevik:qevik` — independently permissioned, as required.

### Five defects, all found by publishing for real

The suite was green before each one.

1. The **delivery** guard judged publication missions — *"approved for
   `deliver-website` and this mission runs `publish-website`"*. Both kinds name
   the same opportunity and deliberately run different recipes. Neither guard
   was weakened; a publishing recipe meets its own six checks, and one smuggled
   into a delivery mission is refused for naming no publication.
2. Published filenames reported as `outcome.files` made the committer try to
   commit an unchanged tree. A publication writes to the host, not its
   workspace. `published` is now separate from `artefact`.
3. With that fixed the run had nothing to show for itself. What a publication
   produces is a page on the internet, and the proof is the verification fetch —
   already happening and being discarded, now recorded as `Evidence`.
4. The acceptance check asks *"did this write files"*, which the module already
   knew is wrong for research and branched for. There was no branch for
   publishing, so every successful publication failed.
5. My own gate split headers from body on the first blank line, which with a
   redirect is the boundary between two header blocks — the page read as empty
   while the site served it.

The common shape: the worker knew two kinds of work — writes-a-diff and
records-evidence. Publishing is a third that produces neither and proves itself
by fetching what it made, and every layer assuming the first two had to learn
about it.

### What is deliberately not built

No customer domain, no DNS automation, no SSL beyond what Caddy already does for
`sites.qevik.ai`, no multi-host publishing. The artefact ships `Disallow: /` from
the generator, which is the right posture for a preview about a business that
has not asked for one.

## Publication state, closed from the timeline — 2026-08-27

The queue query carried a documented seam: *"when publishing lands it records
its own event, and the filter for it belongs in the `WHERE` below"*. Publishing
landed and nothing wrote the event, so a live site stayed on the list of work
waiting to go out.

### What already existed

The authorisation event (`publication_approved`), the whole approval chain, the
publish path, and the queue query with its seam. Proven, not rebuilt.

### What was missing

`publication_completed`, nothing to write it, no clause to read it, and no
published state on the API or console.

| file | change |
|---|---|
| `opportunity/repository.py` | `PUBLISHED_EVENT`, `record_publication`, `publications_for`, the `NOT EXISTS` clause |
| `mission/toolrunner.py` | `_record_publication`, written after the address answered |
| `mission/api.py` | `publication_state`, `published`, `authorised` on the artefact endpoint |
| `apps/control/src/index.html` | the `published` pill; the publish control disappears once live |
| `infra/mission_worker.py` | passes the mission id so "which run put this live" has an answer |

### Three states, from the timeline alone

`ACCEPTED → AWAITING_PUBLICATION → PUBLISHED`. Nothing consults a directory, a
symlink, an HTTP status or a branch — each is a fact about a machine at the
moment somebody looked, and a queue derived from them empties itself when a web
server is misconfigured and refills when a disk is restored.

**An authorisation is not a publication.** Somebody saying it may happen and it
having happened are different states, and treating the first as the second
reports work as done because permission for it was given.

### Production evidence — 27 checks, 0 failed

`mission-821a8e7d171d` at `2d77a5f27c684b39297a0ad9b359d38e621eb331`,
`site-4acac34467c34f17`. A genuine before and after: that page went live before
the completion event existed, so it was **serving and still queued**.

| | |
|---|---|
| before | on the queue, nothing recorded, 1,945 bytes already serving |
| unauthenticated | 401 · read-only operator 403 · unaccepted commit 409 |
| authorised | still queued — permission is not the act |
| after | recorded with commit, site, opportunity and the run that did it; **0 waiting** |
| console | reads `PUBLISHED` without inspecting a filesystem |
| the page | HTTP/2 200, and the served bytes are byte-identical to the committed artefact — 1,945 vs 1,945 |
| duplicates | two records, one state |
| branch | still at the reviewed commit; no remote |

Production timeline now: 3 `artefact_reviewed`, 2 `publication_approved`,
2 `publication_completed`.

### A test defect worth recording

The "does not consult a machine" scan flagged this function's own docstring —
which says it consults no symlink — and the `min(int(limit), 200)` row cap. The
same trap as the keyword scan that flagged its own caveat two milestones ago. It
parses the function and checks the **calls** it makes now, with a negative
control proving the scan can still see the calls that are there.

## Reserved milestone: Agent Compute Fabric

Qevik must eventually register and dispatch to external machines — the HP and
the Lenovo — as execution nodes: capabilities (CPU/GPU/RAM), heartbeat and
health, workload dispatch, agent isolation, per-node execution policy.

**Not started, and the dependency analysis says not yet.** What it needs, and
where each stands:

| needs | state |
|---|---|
| agents as declarative records, not processes | **done** — `fabric/agents.py` |
| the scheduler as the only dispatcher | **done** |
| atomic claims across processes | **done** — Postgres, proven by two real workers today |
| worker independence and disposability | **done** — two units, each refusing the other's work |
| execution isolation per unit of work | **done** — scratch clone, origin allow-list, sandbox |
| budgets bounding a unit of work | **done** — `budgets.assess` before dispatch |
| dispatch through the scheduler and nothing else | **done** — and it stays that way; a node runs what it is given and never queues for itself |
| **a network-reachable mission ledger** | **missing, and this is the blocker** |
| node identity and registration | missing |
| capability advertisement — CPU, GPU, RAM **and which tools the node has** | missing |
| heartbeat / liveness, distinct from mission-claim staleness | missing |
| per-node execution policy | missing |

The last five are the requirement, kept verbatim so a later session cannot
quietly narrow it: **a network-reachable mission ledger, node identity and
registration, capability advertisement (CPU/GPU/RAM/tools), a heartbeat that is
separate from mission-claim staleness, per-node execution policy,
scheduler-based dispatch, and no second orchestration system.** The physical
machines this must eventually carry are the **HP** and the **Lenovo**, as Qevik
execution nodes.

A heartbeat is not a claim, and conflating them is the mistake to avoid at the
start. A claim going stale means *this mission needs re-dispatching*; a node
going quiet means *this machine is gone*. One node can hold a healthy claim on
a mission that is making no progress, and a healthy node can hold no claims at
all. Two signals, two timeouts, two responses.

### The one real blocker

**The mission ledger is a local JSONL file.** `/var/lib/qevik/control/missions.jsonl`
is what every worker folds to find work, and two workers share it today only
because they share a filesystem. A machine in another building cannot read it.

Claims already crossed that line — they are Postgres-backed and proven — so the
pattern exists and the timeline has simply not followed it. Until it does, no
off-host node can exist, and every other item above is unreachable.

Note what is *not* blocking: isolation, policy, budgets, claims and worker
independence are all done and were exercised in production today. The fabric is
closer than it looks, and it is gated on one thing.

### OpenJarvis, evaluated

[OpenJarvis](https://scalingintelligence.stanford.edu/blogs/openjarvis/)
(Stanford Scaling Intelligence Lab) is a framework for personal AI on personal
devices: composable agent roles under bounded context and memory, with energy,
FLOPs, latency and cost treated as first-class constraints.

**Its Orchestrator role decomposes tasks and delegates them.** That is Qevik's
scheduler, policy layer and mission ledger, and adopting it wholesale would be
the second orchestration system this architecture refuses. It is not a candidate
for the control plane.

It *is* a credible reference for the layer below: what runs **on** a node once
Qevik has dispatched to it, and how to run agents well on constrained local
hardware. Its cost-as-a-constraint framing maps directly onto `fabric/budgets`
and onto the `cost_status` rule.

Two caveats before treating it as more than a reference:

- It is built around **LLM agents** reasoning under bounded context. Qevik's
  fabric today executes **deterministic declared recipes** and needs no model,
  so most of what OpenJarvis solves is not yet a problem Qevik has.
- Its value is therefore contingent on model-backed agents, which remain
  `BLOCKED_EXTERNAL_PROVIDER`.

Position: **reference for the node runtime, never for orchestration.** Qevik
remains the control plane, the policy and approval layer, the scheduler, the
evidence and memory, and the mission ledger.

## Reserved milestone: voice as a first-class interface

Voice is an interface requirement across desktop and mobile, both directions:
voice command → mission, and mission result → text **and optional** audio.

The deterministic half already exists — `chat → plan → policy → approval →
mission → worker → report` is proven, and a transcript entering it is just text.
What is missing is transcription and speech, both of which are provider
dependencies. Recorded here so the interface is designed for rather than
retrofitted: a mission result must remain readable as text, with audio as an
addition and never the only form.

## Roadmap, in dependency order

agent registry → scheduler → message protocol → budgets → CLI/tool agents →
business discovery / opportunity engine → **evidenced audit → approved
opportunity → delivery mission** → outreach *(blocked: sending identity)* →
publishing *(blocked: hosting)* → Agent Compute Fabric → voice → flagship
`qevik.ai`

The first four exist as modules (`fabric/agents.py`, `fabric/scheduler.py`,
`fabric/protocol.py`, `fabric/budgets.py`). **Verify before treating any as
missing.**

---

## A regression this session introduced and caught

Removing the `report_root or repository` fallback (which used to write reports
*into* the origin repository) left `run_console_acceptance` with no `--reports`
at all, so the worker wrote to a temp directory the API could not look in and
the console correctly said "no report". Both sides now name the same directory
explicitly, rather than agreeing by both defaulting to the repository.

**Production was never affected** — its worker unit passes
`--reports /var/lib/qevik/control/reports` and `QEVIK_STATE` gives the control
plane the same path. Checked rather than assumed.

Found by running the acceptance harness, not by any unit test. It is the
standing reason for constraint 14.

## Production impact of this session

The checkout is untouched — none of `extractors.py`, `detect.py` or
`ranking.py` is in `/opt/qevik/atlas`, and all three services stayed active.

**One thing did change on the server: the database schema.** The real-data run
called `init_db()` against the production database, which created
`atlas_signals` and `atlas_sightings`. Both are additive, both are **empty**
(the run cleaned its own rows), and `init_db()` is what the services run at
start-up anyway — so the schema is now what a deploy would produce. Nothing
deployed reads either table. Recorded because "I did not touch production" would
otherwise be not quite true.

## Deployment state

`qevik-core-01` runs the current code as of **2026-08-27**, at commit
`13de630`. `qevik-api`, `qevik-control`, `qevik-worker` and
`qevik-worker-research` are all active and the control plane answers `200` on
`/health`.

Deployed this session: the evidenced audit, the backlog rotation, the
`needs_memory` derivation, the empty-targets refusal, and the refusal-status
rule. `rec-nightly-website-verification` is live and fires daily at 05:00 UTC.

Production memory: **412 businesses, 359 with a website recorded, 24 verified so
far, 5 open `weak_web_presence` signals** alongside 53 `missing_service`.

Deploying is what found all three faults above. The suite was green and the
harness passed before every one of them.

### Deploying the kernel

1. `rsync packages/kernel/atlas_kernel/` to `/opt/qevik/atlas/packages/kernel/`
2. `scp infra/mission_worker.py` if it changed
3. `systemctl restart qevik-api qevik-control qevik-worker qevik-worker-research`
   — **all four**. Each loads the kernel, and restarting only the one that
   looks relevant leaves the others running last week's declarations.
4. confirm all four `active` and `/health` is `200`

## Externally blocked

- **`BLOCKED_EXTERNAL_PROVIDER`** — no provider accepts the configured model
  credential. Test credentials, deliberately in use for provider-boundary
  testing. **Not a project blocker. Do not raise rotation.**
- **No search provider.** **53 of 412** known businesses have no website
  recorded by any source *(measured on production, 2026-08-27)*. Proving a
  business has *no* site — as opposed to one this source does not list — needs a
  search provider, which is a real external dependency. Until then those stay
  `MISSING_SERVICE` with a *verify* action, and the audit cannot reach them:
  there is no address to fetch.

  This shrank from "53 of 59" by the nightly discovery running, not by anything
  being fixed: the same 53 businesses, against a memory that grew to 412. The
  ratio moved and the blocker did not.
- **No sending identity.** Outreach cannot start. This is what makes "approved
  opportunity → delivery mission" the right next milestone and outreach the
  wrong one.
- **No hosting for delivered artefacts.** Publishing a built site is an OUTWARD
  act with nowhere to publish to yet.

## Open findings

- **F-001** — `/tmp/db.bak` on `qevik-core-01`. Not read, not deleted, `0600`.
  Awaiting an explicit operational decision. `docs/SECURITY_FINDINGS.md`.

## Open product decisions

- **Six audited defects no offer answers.** A missing viewport, title, meta
  description, structured data, or plain HTTP are observed and real, and
  `offer-website.answers` does not claim to fix them, so no sale is proposed
  from them. Either widen the offer's declaration or accept that they are
  context on a signal rather than a reason to approach anybody. A decision to
  make on purpose; the detector will not make it quietly.

---

## Product direction (not permission to bypass the architecture)

Qevik should behave like a 300-person digital operations team run from a phone:
"add this feature", "find businesses in Dubai today", "investigate this
traffic", "what needs my approval". The phone is a serious control plane —
voice, status, approvals, reports, notifications, scheduling, asset requests.

The flagship surface must be mobile-first, visual and operational — live mission
activity, opportunity maps, asset generation, actionable recommendations. **Not
another generic admin panel, and not more dashboard surfaces for their own
sake.** Preserve the architecture that makes it possible; do not build it yet.
