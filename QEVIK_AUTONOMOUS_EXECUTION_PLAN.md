# Plan — Autonomous Execution & Browser Operations

Response to `QEVIK_AUTONOMOUS_EXECUTION_BROWSER_PUBLISHING_ARCHITECTURE.md`,
written after inspecting the repository as §28.1 requires. **Plan only — nothing
implemented.**

The headline: **roughly 60% of what the document asks for already exists and is
running.** The gaps are narrow and specific. What follows separates them from
the parts that are genuinely large, and says plainly which of those should not
be built yet.

---

## 1. What already satisfies the specification

Verified by inspection and by live execution on `qevik-core-01`, not assumed.
§28.2 says reuse these rather than build parallel systems.

| Spec requirement | Status | Where |
|---|---|---|
| §14 Task model (durable, resumable) | **Exists** — workspace → project → run → job, proven live | `orchestrator`, `atlas_runs`, `atlas_jobs` |
| §10 Approval integrated into the engine | **Exists** — policy engine, scopes, fingerprint-bound consent | `approval/` |
| §15 Capability routing, worker advertisement | **Exists** — `WorkerNode.capabilities` is an open `list[str]`, dispatcher, leases, heartbeats | `cluster/` |
| §16 Artifact system with provenance | **Exists** — 335 assets recorded live | `asset_system.py`, `atlas_assets` |
| §22 Observability | **Exists** — journald, `/health`, `/runtime`, `/runs/{id}/jobs`, event bus | `api.py`, `event_bus.py` |
| §12 Long-running, server-side | **Exists** — systemd units + timers; laptop can close | `qevik-api`, two timers |
| §9 Publishing: deploy + verify + rollback | **Exists** — `site.deploy`, 3 targets, post-deploy fetch, rollback from Atlas's own artifact | `website/` |
| §8 Website build from content | **Exists** — deterministic generation, detector gate | `website/generation.py` |
| §6 Research with provenance | **Exists** — evidence, confidence, sources; Places + OSM discovery | `opportunity/` |
| §17 Production verification (partial) | **Exists** — HTTP, TLS, content checks | `website/service.py` |
| §21 Secrets outside repo, redaction | **Exists** — 0600 env files, `repr` redaction, structured-error-only surfacing | throughout |
| §29 Backups | **Exists** — daily, verified by real restore | `qevik_backup.sh` |

**Nothing in this list should be rebuilt.** The document's own §28.3 warns
against parallel orchestration, and the temptation here is real: several spec
sections describe things that exist under different names.

---

## 2. The actual gaps

Five, in dependency order. Everything else in the document is composed from
these.

### Gap 1 — Browser execution (§4, §5) — **the big one**

Nothing exists. No Playwright, no Chromium, no screenshots. Verified: the only
matches in the tree are transitive `package-lock` entries.

This blocks §5 browser jobs, §17 screenshot/console/responsive verification, §6
crawling of JS-rendered sites, and §25 steps 12 and 16.

**Capacity concern, stated early.** `qevik-core-01` is 4 vCPU / 8 GB and already
runs Postgres, the API and two timers. Chromium is ~400 MB resident per context.
Two or three concurrent browser jobs will contend with Postgres for RAM. This is
survivable with a hard concurrency cap of 2 and `--disable-dev-shm-usage`, but it
is the first real capacity constraint the project has hit and it will get worse
with a second workload.

### Gap 2 — Web search (§6, §26)

`web.fetch` exists and is in production. **General web search does not.** Places
finds *businesses*; it cannot answer "research these competitors".

Needs a search API (Brave ~$5/1k, Serper, Tavily). Small, cheap, unblocks §26's
research requests.

### Gap 3 — Coding-agent execution (§11)

`agents/` turns out to be planner *helpers* — cost estimator, context builder,
dependency graph. There is **no executor that writes code in a workspace**.

Also missing: Qevik cannot run git itself. No commit, no branch, no push. §25
steps 9 and 14 both depend on this.

### Gap 4 — Remote UX (§13)

`apps/web` exists but is a Next.js 14 skeleton with three pages (home, runs,
run detail). The API is loopback-only with **no authentication layer** — which is
correct today and is exactly what blocks §13. A phone cannot reach it, and
should not until auth exists.

### Gap 5 — Iran worker (§7)

Needs hardware in Iran that does not exist yet. The *routing* for it already
exists (capability strings, dispatcher); only the endpoint is missing. This is a
procurement question, not an engineering one.

---

## 3. Critical path to §25's Definition of Done

> *Find a local business without a good website. Build them a website, deploy it
> to staging, and send me the result.*

Of its 19 steps, **13 already work**. The missing ones are 4 (browser), 12
(screenshot), 16 (open deployed site) — all Gap 1 — plus 9 and 14 (coding agent,
git) which are Gap 3.

**So the Definition of Done needs Gap 1 and Gap 3 only.** Not the commercial
website, not subscriptions, not GPU workers, not Iran.

That is a much smaller target than the document implies, and it is the one worth
aiming at first.

---

## 4. Sequence

Ordered by dependency, then by what unblocks revenue. Estimates are focused
build-days at the pace M013–M015 actually ran.

### Phase 1 — Browser worker (5–8 days) · *Gap 1*

Playwright + Chromium in a container on `qevik-core-01`, registered as a
`WorkerNode` advertising `browser.operate`. Concurrency capped at 2.

- `BrowserSession` interface **owned by Qevik**, designed against Playwright and
  one other backend so it is substitutable — the rule that produced
  `site.deploy`'s publish-then-promote, and the reason the OpenClaw review said
  design the interface before adopting any runtime.
- `BrowserJob` per §5, reusing the existing job model rather than a new one.
- Two profiles per §4: research (isolated, no credentials) and operational
  (authenticated, approval-gated). **The operational profile stays unbuilt until
  something concrete needs it** — an authenticated browser is the largest
  security surface in the document.
- Screenshots into the existing artifact system.

**Unblocks:** §17 verification, §25 steps 4/12/16, JS-rendered crawling.

### Phase 2 — Web search (1–2 days) · *Gap 2*

A `web.search` capability behind an adapter, one provider, key in the
environment. Same shape as Places: field-limited, spend-reported, cost-capped.

**Unblocks:** §6 research, §26's research requests.

### Phase 3 — Coding agent + git (6–10 days) · *Gap 3*

- Isolated per-task workspace (git worktree; the repo is already the source of
  truth per §28.4).
- A `code.execute` capability that runs tests in a container.
- Git operations as a capability: branch, commit, push — **push behind approval**,
  since it is outward-facing.
- Wire Claude/Codex as the coding engine via API. §20 is right that a
  third-party agent framework is optional; direct API calls are reproducible and
  keep provenance, which an agent loop does not.

**Unblocks:** §25 steps 9 and 14. **§25's Definition of Done is met at the end of
this phase.**

### Phase 4 — Prove the end-to-end workflow (2–3 days)

Run §25 for a real Dubai business end to end, no copy/paste. This is the
milestone that matters; everything before it is enabling work.

### Phase 5 — Auth + remote UX (5–8 days) · *Gap 4*

Authentication on the API, then expose it with TLS. Extend `apps/web` to
projects/tasks/approvals/artifacts.

**Deliberately after Phase 4.** Publishing an unauthenticated control plane is
the single most dangerous thing in this plan, and there is no reason to rush it
before the system does something worth watching from a phone.

### Phase 6 — Approval and security hardening (3–5 days) · *§21*

Per-task authorisation, egress policy for browser jobs, session expiry, secret
redaction in screenshots. Some exists; this closes the browser-specific surface.

### Later, and honestly not soon

- **Iran worker** — blocked on hardware, not code.
- **GPU workers** — blocked on hardware; M013 has been frozen on this for weeks.
- **Commercial website + subscriptions (§18, §19)** — see below.

---

## 5. What I would not build yet, and why

**§18/§19 — the commercial website and subscription system.**

This is the largest single item in the document: marketing site, auth, plans,
checkout, billing portal, usage limits, invoices, customer dashboard. Realistically
20–30 build-days, plus a payment provider and its compliance surface.

It is a **product to sell Qevik**. Qevik has not yet delivered one customer
website. Building the shop before the thing it sells is the exact pattern that
left three factories finished and frozen — and this document's own §24 puts it
last, at Priority 9, which I read as agreement.

**Recommendation: build it after the first paying customer**, when the pricing
page can state what the product actually did rather than what it is intended to
do.

**§4's authenticated operational browser** — deferred within Phase 1 for the same
reason the OpenClaw review refused existing-session mode: a browser acting inside
a signed-in session is the largest blast radius available, and nothing today
needs it.

---

## 6. Risks

| Risk | Reality | Mitigation |
|---|---|---|
| **RAM on an 8 GB box** | Chromium + Postgres + API will contend. This is the project's first genuine capacity limit. | Cap concurrency at 2; measure; a second box is the answer if it binds |
| **Prompt injection into a browser agent** | Not hypothetical — Qevik will visit hostile pages while prospecting | Extracted content is **data, never instruction**; no credentials in the research profile; egress policy |
| **Unauthenticated API exposed early** | Would publish a control plane that can deploy and send email | Phase 5 order is deliberate; loopback until auth ships |
| **Agent loop nesting** | A coding agent that plans its own steps breaks reproducibility and makes cost unbounded | Deterministic tool calls; Qevik stays the only planner |
| **Scope** | This document describes several years of product | Phases 1–4 only, to Definition of Done |
| **Places/search spend** | Small but unbounded if a loop misbehaves | Already: capped pagination, spend reported per run. Add a budget alert |

---

## 7. Decisions needed from you

1. **Search provider** — Brave (~$5/1k, simplest) unless you prefer another.
2. **Coding engine** — Claude API via Qevik (recommended: reproducible, keeps
   provenance) or Claude Code as a subprocess.
3. **Second box for browser work?** Not needed to start; likely needed once
   browser jobs run alongside everything else. Defer until measured.
4. **Confirm §18/19 deferral** — I have assumed it. If Qevik-as-a-product is the
   actual near-term goal rather than Qevik-as-your-agency, the whole sequence
   changes and I should re-plan.

---

## 8. Summary

**~60% exists.** The Definition of Done needs two of five gaps — browser and
coding agent — at roughly **14–23 build-days** across Phases 1–4.

The rest of the document is real and worth building, but not now: auth before
exposure, hardware before workers, and a customer before a shop.
