# Qevik master state

**This file is the single durable answer to "what is built and what is not".**
It supersedes the status tables in `STATE.md` and `MASTER_EXECUTION_STATE.md`,
which now point here. `ROADMAP_RECONCILIATION.md` remains the map between the
three document sets and is not restated.

Last reconciled: **25 August 2026**, at `c943d31`.

Architecture review (design; the operating fabric below is now implemented):
`MUNDER_DIFFLIN_REVIEW.md` · `QEVIK_AGENT_FABRIC_ARCHITECTURE.md` ·
`CURRENT_VS_TARGET_ARCHITECTURE.md`. Its governing finding: **orchestration is
not intelligence** — policy stays deterministic code, a model proposes and never
authorises. P1–P8 is unchanged by it.

Companion documents: `SECURITY_REVIEW_2026_08_24.md` (every §18 item, with the check that established it) and `COMMERCIAL_REVIEW_2026_08_24.md` (what can be sold, NOW/NEXT/LATER/REJECT).

## The three programmes, kept apart

| | Programme | Source | Authority |
|---|---|---|---|
| **A** | Evidence engine — research → evidence → opportunity → recommendation → roadmap → execution → QA → approval → publication → measurement → re-evaluation | `01_QEVIK_PHASE_ROADMAP.md`, P1–P8 | **Authoritative.** Substantially built. |
| **B** | Execution platform / control plane — chat, planning, missions, coding agent, browser worker, credential centre | `QEVIK_MASTER_AUTONOMOUS_EXECUTION_V2.md`, `QEVIK_AUTONOMOUS_CONTROL_PLANE_PB1.md` | Supplements A. Does **not** renumber it. |
| **C** | Media/growth business — YouTube, game factory, app factory | docs 11 / 11A (absorbed into the reconciliation) | **Separate business line.** Not a Qevik layer. |

Product C stays separate. Nothing in the repository documentation requires
otherwise, and its own gap analysis lists legal entity, developer accounts and
IP rights as Tier 1 — none of which is code.

## Status vocabulary

`COMPLETE` · `PARTIAL` · `IN_PROGRESS` · `PENDING_CREDENTIAL` ·
`PENDING_INFRASTRUCTURE` · `NOT_STARTED` · `DEFERRED` · `REJECTED`

Two of these are frequently confused and must not be:

- **PENDING_CREDENTIAL** — every line of code exists, is tested against a fake
  provider, and refuses honestly. One secret, entered once, activates it.
- **PENDING_INFRASTRUCTURE** — a machine, a database or a DNS record does not
  exist. No amount of code closes it.

Neither means "unbuilt". `NOT_STARTED` means unbuilt.

---

## The finding that governed this session — now closed

**Nothing composed the surfaces into a running application.**

`customer/api.py`, `mission/api.py`, `credentials/api.py`, `control/api.py` and
`control/sales.py` each expose `install(app)`. Grepping the whole kernel for
call sites outside tests returns **nothing**. `atlas_kernel/api.py` — the module
`launcher.py` actually serves — contains zero `include_router` calls.

So every route built across P2.4, P-B1 and this session has only ever been
reached through a `TestClient` inside a fixture. The suite proves the handlers
are correct. It proves nothing about the product existing.

This is the same shape as the `.gitignore` finding: every local signal green,
the artefact absent. It is why §6 of the directive ("move toward the actual
product") is the first engineering task rather than a later one, and why
`test_app_composition.py` now asserts that every router module in the kernel is
mounted by `create_app()`.

**Closed at `30fd2d0`.** `qevik/app.py::create_app()` serves 54 paths, and two
bugs surfaced the moment something built the whole application: `ScopeChange`
declared inside a route factory made OpenAPI generation raise for the *entire*
app, so `/docs` returned 500 everywhere; and `Timeline.__len__` made a new empty
timeline falsy, so `timeline if timeline else []` silently replaced the durable
store with a list on exactly the first run that needed it.

---

## Product A — evidence engine

| Phase | Status | Why / files | Next action | Acceptance |
|---|---|---|---|---|
| P1.2–P1.6 tenancy, evidence, opportunity, recommendation, roadmap, execution | COMPLETE | `opportunity/`, `recommendation/`, `roadmap/`, `execution/` | — | Met |
| P1.7 credits & plans | COMPLETE | `credits/`, reserves against `quota.QuotaLedger` | — | Met |
| P2 website generation | COMPLETE | `website/`, `themes/clean.py` | — | Met |
| P2 multi-page + navigation | COMPLETE | `themes/clean.py::pages` — split derived from `THIN_CONTENT_CHARS` | — | Met: no generated page is thinner than the threshold Atlas sells against |
| P2 editorial content | COMPLETE | `website/content.py` | — | Met |
| P2 imagery | COMPLETE (architecture) / PENDING_CREDENTIAL (generation) | `website/imagery.py` + executor. Documentary slots take only supplied photographs; decorative ones may be generated and are labelled `data-provenance` on the element | A generation provider credential, and photographs from the customer | Met for the rule and the plan; a live generated image needs a provider |
| P2 Arabic / RTL | COMPLETE | `website/arabic.py` + executor. Qevik does not translate; Arabic is customer-supplied and attributed | — | Met: an Arabic page renders RTL, drops anything untranslated, and no module reaches for a model |
| P2 enquiry | COMPLETE | `website/enquiry.py` + executor. mailto/WhatsApp, no server | — | Met: works with scripting off; a business with no channel gets no form |
| P2.1 publication foundation | COMPLETE | `publication/`, `execution/artefacts.bundle_hash` | — | Met |
| P3 technical SEO | COMPLETE | `website/seo.py` — sitemap, robots, canonicals, link audit, merged before hashing | — | Met |
| P3 Search Console | PENDING_CREDENTIAL | `measurement/providers.py` — protocol, fixture provider, `SearchConsoleProvider`, comparison rules. Live call deliberately unwritten | Enter `QEVIK_SEARCH_CONSOLE_REFRESH_TOKEN` | A reading with a real window and sample |
| P3 Analytics | PENDING_CREDENTIAL | Same module and shape | Enter `QEVIK_ANALYTICS_REFRESH_TOKEN` | As above |
| P3 AI visibility | PENDING_CREDENTIAL | `aivisibility/` — adapter, fake provider, `PendingCredentialProvider`, measurement, `mention ≠ rank` all built | Enter a provider key in the Credential Centre | A live observation with `position_available` honoured |
| P4 public audit | COMPLETE | `customer/public.py`, allow-listed | — | Met |
| P4 plans surface | COMPLETE | `/api/customer/plan` | — | Met |
| P4 customer write routes | COMPLETE | Complete-a-task-with-proof, decide-an-approval | — | Met |
| P4 recurring measurement | PARTIAL | `measurement/schedule.py` exists; nothing runs it | Wire to the scheduler | A measurement is taken without a human |
| P5 marketplaces (Amazon, Noon) | NOT_STARTED | Registered in the integration catalogue as `adapter_ready=False`, so they read NOT_IMPLEMENTED rather than asking for a key | Connection + product + listing + inventory + order abstractions, fake providers | Fake provider round-trips a listing |
| P6 CRM / leads / email | PARTIAL | `outreach/` has drafting, contactability, do-not-say rules; no CRM entities, no SMTP boundary | Contact/Lead/Activity/Campaign over the one `Business` id | A campaign drafts and audits without sending |
| P7 social / video | NOT_STARTED | YouTube and Instagram registered as `adapter_ready=False`; both can publish under the customer's name, so neither gets an adapter before an approval gate exists | Provider-neutral content + approval + scheduling | Scheduled post reaches READY_TO_PUBLISH and stops |
| P8 agency / white label | NOT_STARTED | — | — | — |

## Product B — execution platform

| Item | Status | Why / files | Next action | Acceptance |
|---|---|---|---|---|
| Mission model, lifecycle, transitions | COMPLETE | `mission/models.py`, `service.py` | — | Met |
| Worker, retry, acceptance, git isolation | COMPLETE | `mission/worker.py`, `gitspace.py` | — | Met |
| Mission Control HTTP (§12) | COMPLETE | `mission/api.py` | — | Met |
| Worker as its own process | COMPLETE | `infra/mission_worker.py` — proven by subprocess with the app destroyed | — | Met |
| Durable timeline shared by processes | COMPLETE | `mission/timeline.py` — atomic line appends, fsync, corrupt-line tolerance | — | Met |
| **Cross-process atomic claim** | COMPLETE (implementation) / NOT_DEPLOYED | Superseded by the operating-fabric row below and `POSTGRES_CLAIMS.md`. Demonstrated 25 August 2026 against PostgreSQL 18.6 | Set `QEVIK_CLAIMS_DSN`, call `register()` from the worker, start a second worker | Two workers, one mission, exactly one claim — proven for the implementation, not yet for the deployment |
| Credential vault (§17) | COMPLETE | `credentials/vault.py` — sealed rather than degrading | — | Met |
| Credential Centre HTTP | COMPLETE | `credentials/api.py` — no route returns a secret | — | Met |
| Live credential probes | PENDING_CREDENTIAL | `/test` returns 501 for every provider, deliberately | Enter one key | A stored credential reaches CONNECTED |
| §18 re-evaluation | COMPLETE | `mission/reevaluation.py`, run as a real mission on AHS | — | Met |
| **Chat intake → plan → approval → mission** | COMPLETE | `chat/` — nothing in it executes, asserted by an AST walk | — | Met: `test_chat_to_commit.py` types a sentence, destroys the app, and a separate process commits |
| **App composition** | COMPLETE | `qevik/app.py::create_app` — 54 paths, every router asserted mounted via the OpenAPI document | — | Met |
| Model selection per role | COMPLETE | `modelchoice/` over the existing registry; no second registry, asserted | — | Met |
| SSRF guard on research | COMPLETE | `research/addresses.py` — every resolved address, every redirect hop | — | Met: a real loopback server is refused |
| Coding-agent sandbox | COMPLETE (implementation) / NOT_WIRED | Superseded by the operating-fabric row below and `SANDBOX.md`. bubblewrap, demonstrated 25 August 2026 | Wire `Bubblewrap.run()` to the worker's agent invocation | 16 escape attempts refused |
| Browser worker | PENDING_INFRASTRUCTURE | `browser/` is an interface | — | — |
| Iran-origin worker | PENDING_INFRASTRUCTURE | Needs an Iran-resident host; cannot be faked, and the doc says so | — | — |
| Publication boundary | COMPLETE | `publication/targets.py` — target protocol, real `LocalTarget` with atomic replace and rollback, domain verification, `NOT_AUTHORISED` distinct from `FAILED` | — | Met: Qevik's own site publishes for real to the local target |
| Cloudflare target | PENDING_CREDENTIAL | Adapter, manifest and refusals built; only the HTTP call is unwritten, deliberately | Enter `QEVIK_CLOUDFLARE_API_TOKEN` + `QEVIK_CLOUDFLARE_ACCOUNT_ID` | A bundle reaches a public URL |
| Public deploy target | PENDING_INFRASTRUCTURE | A verified domain. The TXT record only its owner can create is generated per tenant | Point a domain at Qevik and create the record | A published site answers on a public URL over HTTPS |
| Billing | DEFERRED | Plans, credits and quota exist and are enforced; money does not, deliberately | — | A price is agreed by a person first |

## Operational state

| Item | Status | Evidence |
|---|---|---|
| **Self-improvement: "add this feature"** | OPERATIONAL (deterministic agent) | `SELF_IMPROVEMENT.md`. Phone → request → conversation → plan **or** explicit blocker → policy → approval → mission → worker → report, on the existing pipeline with no second orchestrator. 26/26 acceptance with real processes and real restarts; both screens read at 390×844 and 1280×900. A model-backed plan needs a working provider and no architectural change |
| **`BLOCKED_EXTERNAL_PROVIDER`** | OPERATIONAL | A rejected credential reported as `PENDING_CREDENTIAL` — *"add a model credential"* — which is useless advice to somebody who already added one. Now classified honestly and drawn differently from a local failure, because a provider refusing is not the deployment's fault |

| Item | Status | Evidence |
|---|---|---|
| **Mobile control experience** | PARTIAL — dashboard done | `MOBILE_CONSOLE.md`. Answer-first lead in the display face, four thumb-reachable destinations, brand teal replacing a generic admin blue. Verified by reading screenshots at 390×844 and 1280×900. Found three real defects including `COST` rendering `undefined` — and worse, `0` where nothing was priced, which reads as *free*. Mission detail, Chat and Credentials render acceptably but have not had the same pass |
| **Test feedback loop** | IMPROVED | `pytest -n 6` runs the suite in **2:15** against 7:00 serial. Seven tests fail under parallelism from shared state and pass serially, so `-n` is for iteration and the serial run remains the gate. The isolation issue is recorded, not fixed |

| Item | Status | Evidence |
|---|---|---|
| **Qevik does not authorise Qevik** | OPERATIONAL | The production worker's repository *is* Qevik's own source, so every mission edits the system deciding whether to allow it — and a cheap docs-only plan reached the queue unattended. Now checked above every other rule, defaulting to require approval. This is the precondition for self-improvement, not an obstacle to it |
| **Deterministic policy above the planner** | OPERATIONAL | `POLICY_ABOVE_THE_PLANNER.md`. `attach_plan` routed on `Plan.approval_required` — a field the *planner* sets, and `FakeCodingAgent` sets it to `False`, so its plans reached QUEUED with nobody asked. `mission/policy.py` decides now: deny by default, three requirements (NONE / EXECUTION / ARTEFACT), and the planner may only raise the bar. A source test forbids it importing a model, a network client, `random` or `time` |
| **Business memory is durable** | OPERATIONAL | `businesses.jsonl`. `business_events` was a plain list in production, so a restart erased the entire history of every business while the businesses remained |
| **Provider-backed missions** | BLOCKED_EXTERNAL_PROVIDER | Not a project blocker. Wired and proven to the provider's auth boundary; the single configured DashScope key is rejected by the provider. No further capacity spent on it |

| Item | Status | Evidence |
|---|---|---|
| **One credential boundary** | OPERATIONAL | `CREDENTIAL_BOUNDARY.md`. `credentials/location.py` is the only module that names a credential file; `QEVIK_VAULT` and `--vault` are gone. A source-reading test fails on any literal elsewhere **and** on any caller that stops asking. 16/16 live with both processes restarted, no second store, no secret on disk |
| **Agent-to-agent conversation persistence** | NOT_REQUIRED (guarded) | Nothing on the live path constructs an `Exchange` — a mission runs single-agent through registry → adapter → tools → sandbox. `test_agent_conversation_persistence.py` fails the moment a producer appears and names the fold to use. Distinct from user chat, which **is** persisted in `chat.jsonl` |
| **Second worker** | NOT ADDED, deliberately | One worker, empty queue, no throughput requirement. Two workers racing one mission is already proven 7/7; adding a permanent second would be a number, not a capability |

| Item | Status | Evidence |
|---|---|---|
| **Atomic claims in production** | OPERATIONAL | `qevik-worker.service` active with `QEVIK_REQUIRE_ATOMIC_CLAIMS=1`; `/api/health` reports `PostgresClaims · COMPLETE`. 10/10 claim-safety (both processes refuse with no database and with an unreachable one, each with its negative control), 7/7 two workers racing one mission |
| **Budgets charged at execution** | OPERATIONAL | Persistence went into `QuotaLedger` itself, so `credits` and `fabric.budgets` became durable at once and the worker and control plane share `quota.jsonl`. The worker calls `reserve()` after the work; an unknown cost is recorded as UNKNOWN, never as zero |
| **Conversation persistence** | OPERATIONAL | `chat.jsonl`. A conversation survives a real server restart with the person's words intact; the console acceptance proves it still references its mission |
| **Model-backed mission** | WIRED / BLOCKED_ON_PROVIDER | The worker reads the Centre's credential, the registry refuses to turn a rejected key into a model, and the worker refuses rather than faking. The configured DashScope key is rejected by DashScope at all three endpoints — not a region mismatch. Needs a key the provider accepts; nothing else |

Detail: `OPERATIONAL.md`.

## The fabric, connected to the running system

The operating fabric below was built and connected to nothing. Two gates closed
that, both verified against the live host rather than a TestClient.

| Item | Status | Why / files | Acceptance |
|---|---|---|---|
| **Credential Centre** | COMPLETE | `CREDENTIAL_CENTRE_FIX.md`. Two defects: records lived in an in-memory dict while the vault persisted the secret, so a saved key read back as NOT_CONFIGURED after any restart with its value orphaned in the vault; and **no probes were registered at all**, so `/test` answered 501 for every provider and nothing could leave PENDING_CREDENTIAL. Records now fold from `credentials.jsonl` like every sibling module; real probes ship for anthropic, qwen, openai, deepseek, stripe, cloudflare | Met, **live on tenant-qevik**: 20/20 through save → restart → test → restart → forget → restart. Anthropic and DashScope both reached for real and both rejected a deliberately fake key. `grep -cE 'sk-…'` over the live timeline returns 0 |
| **End-to-end execution** | COMPLETE | `FABRIC_WIRED.md`. The scheduler now decides dispatch order, `PostgresClaims` decides who, `mission/adapter.py` joins the registry to the tool contract and the sandbox, and `POST /api/missions/{id}/plan` gives the control plane the planning step it never had | Met, **on qevik-core-01**: 27/27 with a real server process, a real worker process, real PostgreSQL, real bubblewrap, and the control plane killed mid-flight. Mission still complete after two restarts |
| **Multi-worker safety, in the worker** | COMPLETE (worker) / NOT_DEPLOYED (service) | `--claims-dsn` plus `--require-atomic-claims`, which **refuses to start** rather than falling back — a silent fallback means two workers run one mission and two commits appear with no error | Met: 7/7 with two workers racing one mission — exactly one claim, one `processing` transition, one commit. The *service* still runs `LocalClaims`; `/api/health` says `SINGLE_WORKER_ONLY` until `QEVIK_CLAIMS_DSN` is set |
| Budgets charged at execution | NOT_STARTED | The scheduler consults the tenant balance before dispatch; `reserve()` is still not called from the worker | Per-mission and per-agent allowances drawn down by a real run |

## The autonomous operating fabric

Built after the Munder-Difflin review named orchestration, not intelligence, as
the governing gap. The ordering is the operator's: live status, then the
registry, then the scheduler, then the protocol, then budgets.

| Item | Status | Why / files | Acceptance |
|---|---|---|---|
| **Live status** | COMPLETE | `qevik/live.py`, `GET /api/status` — one fold of both timelines, a `blake2b` version digest over `(mission, updated_at, status)` sorted so arrival order is not a change. Console polls every 4s and pauses on `visibilitychange`. Polling, not SSE: Cloudflare buffers streaming responses | Met. `{"changed": false}` when nothing moved; the poll loop contains no approve/decide/plan/POST |
| **Agent registry** | COMPLETE | `fabric/agents.py` — 17 declarative records, 11 ready. `Blast` → `APPROVAL_FOR` decides which approval applies. An agent is a record: no `run`, no `spawn`, no `delegates_to` | Met. AST tests assert the registry never imports `EXECUTORS`, `REQUIRES_CUSTOMER_INPUT`, `owns(`, `QuotaLedger` or `ALLOWED` |
| **Scheduler** | COMPLETE | `fabric/scheduler.py`, `SCHEDULER.md` — five queues; `WAITING` and `BLOCKED` never merge, and a missing credential is BLOCKED (nothing resolves it but a person). Priced and unpriced work judged separately, so UNKNOWN cost is neither free nor a wall. Deferral is durable (`Mission.not_before`) and **enforced in `claim()`**, not advisory | Met. A deferral written in one interpreter is read by a `subprocess` that never saw it, with a negative control proving the same process would otherwise have run it |
| **Message protocol** | COMPLETE | `fabric/protocol.py` — an agent addresses a *capability*, never an agent, so every edge in the graph is one the registry declared. Hop, message and budget caps **escalate to a person with the chain attached**; they never truncate | Met. A cycle is caught by "who is still waiting", so a second question to the same specialist after an answer is still ordinary work |
| **Budgets** | COMPLETE | `fabric/budgets.py` — tenant ⊃ mission ⊃ agent ⊃ conversation on the existing `QuotaLedger`. Check-all-then-commit-all; a refusal charges nothing. An unmetered *tenant* refuses (`Unmetered`), an unmetered mission is ordinary | Met. Two tenants with the same `mission-1` never share an allowance |
| **Multi-worker claiming** | COMPLETE (implementation) / NOT_DEPLOYED | `POSTGRES_CLAIMS.md`. The blocker had already lifted and nobody had noticed: PostgreSQL 18.6 and psycopg 3.3.4 were already on qevik-core-01. `infra/verify_postgres_claims.py` raced **8 OS processes** at a shared start instant for one mission — exactly one claimed it. The run found a real bug: an autocommit connection releases the row lock before the claim is recorded, so two workers would claim one mission with no error. Now refused in the constructor | Met for the implementation: 13 checks, 0 failures, output recorded in `reports/postgres_claims_verification.txt`. **Not met for the deployment** — `QEVIK_CLAIMS_DSN` is unset, `/api/health` says `SINGLE_WORKER_ONLY`, and no second worker is running |
| **Sandbox for coding agents** | COMPLETE (implementation) / NOT_WIRED | `SANDBOX.md`. The blocker had already lifted here too: bubblewrap 0.11.1 with unprivileged user namespaces was already on qevik-core-01. `fabric/sandbox.py` enforces filesystem, network, environment and wall clock; `NoSandbox` **refuses to run** rather than executing unconfined. `Agent.ready` is now derived from a structured `blocked_by`, so a host lifts exactly `Need.SANDBOX` and leaves `browser`'s browser worker and `administrator`'s approval policy alone | Met for the implementation: 16 real escape attempts refused, 0 failures, recorded in `reports/sandbox_verification.txt`. **Not wired**: nothing runs a coding agent through it yet, and `cli-implementer` is now blocked on `CREDENTIAL` rather than on the sandbox |
| **Tool-agent contract** | COMPLETE (contract) / NOT_WIRED | `TOOL_AGENTS.md`. `Agent.tools` was free-form strings; `fabric/tools.py` makes each a record with blast radius, credentials, network need and whether a sandbox contains it. Found two real errors: `shell` covered both a sandboxed worktree shell and a live-host shell (now `shell` and `host-shell`), and `browser` declared REVERSIBLE while a browser that can navigate can submit a form — it was routed to execution approval instead of artefact approval by one wrong word | Met for the contract: a dangling tool name fails the build, no agent may understate its tools, `needs_network()` feeds `sandbox.Isolation`. **Not wired**: nothing dispatches through a tool yet. **No CRM/marketplace/social/media feature was started** |
| Provider rate limits as a scheduling input | NOT_STARTED | Named in `SCHEDULER.md` and `TOOL_AGENTS.md` as a stated gap | — |

## Product C

| Item | Status |
|---|---|
| Media/growth business (docs 11/11A) | REJECTED as a Qevik layer — see the reconciliation |

---

## Blocker policy in force

A blocker on one capability never stops unrelated work. For every integration:
the abstraction, the credential entry, the validation, the fake provider, the
tests, the cost model and the documentation are built; only the live call waits.
Exactly that capability is marked `PENDING_CREDENTIAL` and appears as a
`HumanAction` in the Credential Centre.

## The control panel

`apps/control/src/index.html` — one file, no build step, served either by Caddy
from `/srv/qevik-control` or by the composed app itself. Dashboard, Roadmap,
Mission Control, Chat, Human Actions, Credentials, Models, Businesses,
Publications, Measurements, Reports, History, Settings. Responsive; the
navigation becomes a scrolling strip under 820px.

**Status: LIVE at https://app.qevik.ai**, verified from outside. See
`DEPLOY_APP_QEVIK_AI.md`.

`infra/run_console_acceptance.py` runs it against a real uvicorn over real HTTP:
33 checks, all passing, including killing the server mid-flight, running the
worker as a separate process with nothing serving, and starting a *new* server
to confirm the mission, its full lifecycle history and its report survived.

| | |
|---|---|
| app.qevik.ai | **Serving the Qevik Control panel** |
| control plane | **Reachable** — `/api/*` on `qevik-control` (:8081), 401 JSON unauthenticated |
| Caddyfile | Fixed: `/api/*` now proxies to the control plane |
| Remaining | One operator needs a tenant — an auth change on a live system, so it is the user's to make |

`infra/deploy_console.sh` copies the console, installs the Caddyfile, validates
it, reloads Caddy and verifies over HTTPS.

**Correction to an earlier report:** SSH access exists.
`ssh -i ~/.ssh/naml_hetzner -o IdentitiesOnly=yes root@2.28.62.83` works; the
earlier check let SSH pick a default identity and failed before reaching that
key. The real obstacle is that the server runs `atlas_kernel.api:app`, not the
composed app, and mounting the control plane onto the monolith made
`/api/missions` answer **200 with HTML** instead of 401 with JSON — an
unauthenticated 200 where an authenticated API belongs. Reverted rather than
shipped. `DEPLOY_APP_QEVIK_AI.md` has the exact remaining work.

## Capability delivery, as distinct from capability existence

`EXECUTORS` says what can run. `REQUIRES_CUSTOMER_INPUT` says what still needs
something only the customer has. **Both are consulted before a roadmap presents
a task as executable**, because two separate corrections were needed to get
here: an offer existing did not imply an executor, and an executor existing did
not imply it could ever receive its input.

| Offer | Executor | Runnable today |
|---|---|---|
| `offer-website` | yes | yes |
| `offer-portfolio-system` | yes | yes |
| `offer-editorial` | yes | yes |
| `offer-arabic-experience` | yes | **no — needs Arabic copy from the customer** |
| `offer-enquiry-builder` | yes | **no — needs an email address or WhatsApp number** |
| `offer-imagery` | yes | decorative only — **documentary slots need photographs** |
| `offer-one-tap-contact` | no | the theme already renders `tel:`; the fix is inside `offer-website` |
| `offer-imagery` | yes | decorative slots yes; **documentary slots need the customer's photographs** |

## The five businesses Qevik contacted

Re-evaluated on 24 August 2026 —
`reports/2026-08-24_business_reevaluation.md`. Nothing was re-crawled, so every
difference is a change in Qevik. **Three of the five were contacted about a
missing Arabic version at a time when nothing could build one.** All five now
correctly read "nothing yet" with the Arabic offer shown as needing them first.

## Qevik as its own customer

Run on 24 August 2026 — `reports/2026-08-24_qevik_self_assessment.md`. Three of
eight readiness dimensions returned **no score at all** rather than zero, because
nothing in them was ever checked; six confirmed absences produced three
opportunities and two recommendations; and no unverified feature reached the
opportunity list, asserted programmatically rather than reviewed. Our own
generated site passes our own audit and is `indexable: False`, because no domain
is agreed.

The finding: the engine is honest and nearly blind about us, and the gap is data
rather than model. It closes with a crawl and a Search Console credential.

## What a person has to do that no code can

0. **Nothing.** The console runs today with `python3 infra/serve_console.py`.
   Putting it on app.qevik.ai needs one routing conflict resolved — engineering,
   not a credential. See `DEPLOY_APP_QEVIK_AI.md`.
1. Enter provider keys once in the Credential Centre — nothing is asked for in
   chat, and no key is ever needed to build the integration.
2. Provision Postgres, if multi-worker missions are wanted.
3. Provide a host and a DNS record for real publication.
4. Agree a price before any billing exists.
