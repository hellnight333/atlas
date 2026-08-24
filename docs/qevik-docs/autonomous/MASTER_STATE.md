# Qevik master state

**This file is the single durable answer to "what is built and what is not".**
It supersedes the status tables in `STATE.md` and `MASTER_EXECUTION_STATE.md`,
which now point here. `ROADMAP_RECONCILIATION.md` remains the map between the
three document sets and is not restated.

Last reconciled: **25 August 2026**, at `c943d31`.

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
| **Cross-process atomic claim** | PENDING_INFRASTRUCTURE | `mission/claims.py`. `LocalClaims` correct for one process and says so; `PostgresClaims` written with `FOR UPDATE SKIP LOCKED` and **refuses to construct unverified** | Provision Postgres, then pass `i_have_a_database=True` and prove it | Two workers, one mission, exactly one claim |
| Credential vault (§17) | COMPLETE | `credentials/vault.py` — sealed rather than degrading | — | Met |
| Credential Centre HTTP | COMPLETE | `credentials/api.py` — no route returns a secret | — | Met |
| Live credential probes | PENDING_CREDENTIAL | `/test` returns 501 for every provider, deliberately | Enter one key | A stored credential reaches CONNECTED |
| §18 re-evaluation | COMPLETE | `mission/reevaluation.py`, run as a real mission on AHS | — | Met |
| **Chat intake → plan → approval → mission** | COMPLETE | `chat/` — nothing in it executes, asserted by an AST walk | — | Met: `test_chat_to_commit.py` types a sentence, destroys the app, and a separate process commits |
| **App composition** | COMPLETE | `qevik/app.py::create_app` — 54 paths, every router asserted mounted via the OpenAPI document | — | Met |
| Model selection per role | COMPLETE | `modelchoice/` over the existing registry; no second registry, asserted | — | Met |
| SSRF guard on research | COMPLETE | `research/addresses.py` — every resolved address, every redirect hop | — | Met: a real loopback server is refused |
| Coding-agent sandbox | PENDING_INFRASTRUCTURE | Needs a host | — | — |
| Browser worker | PENDING_INFRASTRUCTURE | `browser/` is an interface | — | — |
| Iran-origin worker | PENDING_INFRASTRUCTURE | Needs an Iran-resident host; cannot be faked, and the doc says so | — | — |
| Publication boundary | COMPLETE | `publication/targets.py` — target protocol, real `LocalTarget` with atomic replace and rollback, domain verification, `NOT_AUTHORISED` distinct from `FAILED` | — | Met: Qevik's own site publishes for real to the local target |
| Cloudflare target | PENDING_CREDENTIAL | Adapter, manifest and refusals built; only the HTTP call is unwritten, deliberately | Enter `QEVIK_CLOUDFLARE_API_TOKEN` + `QEVIK_CLOUDFLARE_ACCOUNT_ID` | A bundle reaches a public URL |
| Public deploy target | PENDING_INFRASTRUCTURE | A verified domain. The TXT record only its owner can create is generated per tenant | Point a domain at Qevik and create the record | A published site answers on a public URL over HTTPS |
| Billing | DEFERRED | Plans, credits and quota exist and are enforced; money does not, deliberately | — | A price is agreed by a person first |

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

**Status: built and acceptance-tested locally. NOT deployed.**

`infra/run_console_acceptance.py` runs it against a real uvicorn over real HTTP:
33 checks, all passing, including killing the server mid-flight, running the
worker as a separate process with nothing serving, and starting a *new* server
to confirm the mission, its full lifecycle history and its report survived.

| | |
|---|---|
| app.qevik.ai reachable | **Yes** — real Cloudflare IPs, serving the older *sales* interface |
| control plane reachable there | **No** — `/api/*` fell through to the static handler and returned `index.html` with a 200 |
| Caddyfile | Fixed: `/api/*` now proxies to the control plane |
| Deploying it | **NOT BLOCKED ON ACCESS** — the `naml_hetzner` key opens the host. Blocked on one routing conflict; see `DEPLOY_APP_QEVIK_AI.md` |

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
