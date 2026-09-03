# QEVIK DECISION QUEUE

Only decisions that genuinely require the owner. A decision already resolved in
`QEVIK_HISTORICAL_DECISIONS.md` is not a question.

| ID | Decision | Options | Recommendation | Owner decision | Source | Date | Status |
|---|---|---|---|---|---|---|---|
| DQ-001 | YouMind | Define it, or drop it | None. The definition is not recoverable from any surviving document and inventing one would be inventing product | — | HISTORICAL_DECISIONS §24 | — | UNKNOWN |
| DQ-002 | Computer-use lineage | Which substrate carries it | None yet. Grok Bot is DROPPED and must not return as the answer | — | ROADMAP §02 unknown list | — | OPEN |
| DQ-003 | Dormant Atlas surfaces | Revive / retire / leave parked | Leave parked. `apps/desktop`, `apps/web`, `apps/prototype` have no Qevik wiring and no deploy path; parked is recorded in `apps/STATUS.md`, and retiring would be inventing a decision nobody made | — | ROADMAP §02; `apps/STATUS.md` | 2026-08-30 | OPEN |
| DQ-004 | Media provider / local-vs-cloud policy | Provider choice, and whether media runs local or cloud | None yet. It gates C-30 and, through it, the GPU machines' first genuine workload | — | ROADMAP §02 unknown list | — | OPEN |
| DQ-006 | What allowance does Qevik's own operating tenant have? | Put `tenant-qevik` on a customer plan / define an internal tenant kind that is metered differently / leave it unmetered and accept that metered work refuses | Do **not** put it on a customer plan. LIST/PRO/ADVANCED/ENTERPRISE are commercial plans with included units and an essential floor; assigning one to Qevik's own operating tenant would record Qevik as a customer of itself and make its own consumption look like a customer's. An internal tenant kind is the honest shape, and what it is allowed is a decision nobody has made | — | `credits/models.py`; production shows no tenant on a plan | 2026-08-31 | OPEN |
| ~~DQ-007~~ | ~~Where do email addresses come from?~~ **RESOLVED 2026-08-31** — read them from the pages the audit already fetches. Contact discovery, not permission to send | — | — | Owner | Owner, this session | 2026-08-31 | RESOLVED |
| DQ-007-old | Where do email addresses come from? | Read `mailto:` from the audited homepage / buy a data source / stay on WhatsApp only / do not do email outreach | None. 412 businesses carry 0 email addresses and no source collects one, so the email channel has no recipients at all. Reading contacts off a business's own website is technically deterministic — the audit already has the HTML — but it is collecting contact details for unsolicited outreach, which is the substance of DQ-005 and not mine to decide | — | Measured 2026-08-31 | 2026-08-31 | OPEN |
| DQ-005 | Outreach policy for businesses that did not request contact | How Qevik approaches strangers | Partly answered in practice: the health check is now the first action, it asserts only what was observed, and it claims no prior relationship. The remaining question is cadence and scale, not truthfulness | — | ROADMAP §02 unknown list | — | OPEN |
| DQ-010 | Which write boundary owns an outreach decision | (1) compound repository operations only · (3) wire the Opportunity pipeline's approval decisions back with a subscriber + reconciler · (4) one state machine on the live mission path (message row + event are the approval record). Session-passing / unit of work is analysed and not recommended | Do (1) first regardless; then the owner chooses (3) vs (4). (4) fits what production runs, but it decides that outreach approval is a mission decision and not a kernel approval — which is DQ-005's territory | — | `docs/decisions/ADR-0009-Outreach-Approval-Atomicity.md` | 2026-09-02 | OPEN |
| DQ-011 | Move the DevLoop executor off the operator's Mac | Dedicated server / cloud executor / stay on the Mac | Prepare the migration decision only after ADR-0010 T2 and T3 land, a real-host `--rehearse` succeeds, the first human-watched production deployment completes, and production verification is read back. Do not mix infrastructure migration with deployment hardening | Deferred by the owner (decision 6, 2026-09-02) until those four gates are met | DevLoop throughput analysis 2026-09-02 §6 item 8; ADR-0011 | 2026-09-02 | DECIDED 2026-09-02 — Option C (dedicated Hetzner Cloud VM, CX53-class 16 vCPU / 32 GB, Ubuntu 26.04 LTS matching production, no GPU; ADR-0011). Phase 0 approved and run; provisioning after ADR-0010 T2b + T3 land, rehearse and the first human-watched deploy are verified; cutover after ≥5 real tasks validated in parallel **2026-09-03:** the server bought as `qevik-devloop-01` is retargeted to production by D-R-1 (DQ-014); the executor host becomes a future separate server; DevLoop never on production; no provisioning authorised. |
| DQ-012 | DevLoop review round / severity policy (`Limits.review_rounds` 3→2; whether `major` blocks) | Keep 3 rounds + major blocks / 2 rounds / major-only round → WAITING_FOR_HUMAN | Do not change yet. Collect ≥15 more completed task runs after 2026-09-02, then classify every blocking finding on five axes: (1) severity as recorded, (2) reproducible or not, (3) affected production correctness/safety or not, (4) catchable by an objective test or not, (5) recurred after the fix landed or not. The throughput analysis wrote "routes through DQ-010" for this; DQ-010 is the outreach write boundary, so this is its own item | Frozen by the owner (decision 5, 2026-09-02): current blocking semantics stay | DevLoop throughput analysis 2026-09-02 §5 | 2026-09-02 | OPEN — MEASURING (2/15 runs since 2026-09-02). DQ-012 run 1/15: t-e44a121a65b1 (ADR-0010 T2) CONTESTED after 3 rounds; findings r1 blocking ×2, r2 blocking + major, r3 major; reproducible; production correctness-safety (DEPLOYED_SHA provenance); catchable by objective tests; recurred as a CLASS (unchecked provenance write inside rollback, two sites) not as independent findings — owner approved successor t-9f3ecb58b4ad on that basis, route (a), same three-path contract · DQ-012 run 2/15: t-03e23ee8f736 (ADR-0010 T3) CONTESTED after 3 rounds; findings r1 blocking, r2 major, r3 blocking + major; reproducible; the r1→r3 chain is a design escalation on ONE failed-shipping path (failed squash commit on main: cleanup absent → destructive → racy), NOT the class-level pattern of run 1 — each round objected to the previous round's fix, and the third asked for a repository lock outside the execution model; the r3 gates.py finding (duplicate marker fields last-win) is independent, narrow, production-safety, catchable by an objective test. Owner route: decision-first (DQ-013) then a successor with structured diagnosis, equal scope, brief reviewed by the owner before enqueue |
| DQ-013 | DevLoop shipping-path failure policy: what `_ship` may do to `main` after a squash merge or squash commit fails | Destructive reset of main / repository lock around the landing sequence / preserve-and-BLOCK unless cleanup is provably limited to squash state | Preserve-and-BLOCK: the DevLoop is a single-driver serial executor; a lock defends against a hypothetical second driver and not against a human edit; unknown work outranks loop liveness | **DECIDED 2026-09-02 (owner):** (1) single-driver, serial executor stays; no repository lock merely against a hypothetical second driver. (2) The shipping path never automatically runs `git reset --hard` (or any equivalent destructive reset) against `main` to recover from a failed squash/commit. (3) Preservation of unknown work takes priority over automatic loop liveness: if the post-failure state cannot be PROVEN to contain only DevLoop-generated squash state, no destructive cleanup — preserve, move to BLOCKED, emit explicit evidence of what remains and why a person is needed. (4) A non-destructive cleanup proven safe and limited strictly to DevLoop-generated squash state may be used; otherwise BLOCKED is the correct terminal outcome. (5) The successor also fixes the provenance parser: duplicate authoritative marker fields (`sha`, `state`, any repeated key) fail closed, never last-value-wins. (6) Recorded as DQ-012 run 2/15 as a chained design escalation on one path, not T2b's class-level pattern | T3 t-03e23ee8f736 review rounds 1–3; owner decision after the CONTESTED report | 2026-09-02 | DECIDED 2026-09-02 — governs the T3 successor; recorded in ADR-0010 implementation record |
| DQ-014 | Hetzner production migration `qevik-core-01` → `qevik-prod-01`: architecture, sizing, backups, firewall, SSH key, phase gating | Harden in place / migrate to a fresh single host (Phase 0 design) / larger or multi-host designs | Fresh single host, like-for-like size + swap, Cloud Firewall 22/80/443 key-only, dedicated key, Storage Box + image backups, old host frozen-intact for a 14-day observation, F-1…F-7 as pass/fail gates (`docs/migration/hetzner/OWNER_DECISION_AND_FINAL_ARCHITECTURE.md`) | **DECIDED 2026-09-03 (owner):** D-A approved (architecture governs); D-B approved (4 vCPU / 8 GB / ~160 GB + 2 GB swap, exact product name and price confirmed in console before provisioning, no larger class without load evidence); D-C approved (Storage Box sub-account + image backup add-on; a Volume never the only backup); D-D approved (Cloud Firewall + ufw, ingress 22/80/443 only, no `:8443`, key-only SSH, Cloudflare origin restriction deferred to hardening); D-F approved (dedicated `qevik_prod` key; `naml_hetzner` never on the new host); D-L approved for Phase 1 only — not for provisioning. Binding requirements: AR-1 explicit RPO/RTO approved before cutover; AR-2 two-session SSH hardening; AR-3 single host, no Docker/K8s/replicas/managed DB/Prometheus without a concrete requirement; AR-4 old host untouched and rollback-capable through observation; AR-5 DevLoop paused, no provisioning/DNS/data/secret action without the next gate | `docs/migration/hetzner/` (8 Phase 0 docs + decision package + `PHASE_1_COMPLETION_REPORT.md`, `evidence/phase-1/`) | 2026-09-03 | DECIDED 2026-09-03 for D-A/B/C/D/F + Phase 1; **Phase 2 provisioning gate OPEN** — pending owner console reads (U1/U2), D-B re-confirmation (nbg1 product is CPX32 ≈ €35.49/mo after the 2026-06-15 price change; CX43/CX33 cheaper if orderable) and an explicit Phase 2 GO. **2026-09-03 (later): owner halted Phase 2 before any order; existing `qevik-devloop-01` (CPX42-shape, idle, bought 2026-09-02) assessed read-only as the target — suitable; Option A reuse recommended; **D-R-1 APPROVED 2026-09-03 (owner):** reuse server 164307556 after a clean console rebuild (Ubuntu 26.04, same id/IPs) + AR-2 swap to `qevik_prod` only (rebuild re-injects the creation key — Hetzner FAQ), no purchase/replacement/extra compute of any kind, DevLoop never on production, old host untouched; ADR-0011 amended (executor host → a future server). Phase 2 = `docs/migration/hetzner/PHASE_2_OWNER_CONSOLE_ACTIONS.md`; **execution still gated on the owner's explicit per-step GO** (`DEVLOOP01_SUITABILITY_ASSESSMENT.md`).** D-E/G/H/I/J/K/M/N/O/P/Q still open |

## Resolved, recorded here so they are not asked again

| Decision | Outcome | Source | Date |
|---|---|---|---|
| Creative Blueprint, Grok Bot, Shopify, Facebook | DROPPED | HISTORICAL_DECISIONS §24 | — |
| Audiobook, Character Sheet, TikTok, Steam | DEFERRED | HISTORICAL_DECISIONS §24 | — |
| Atlas vs Qevik orchestration | Reuse the Atlas substrate; no second orchestrator or registry | HISTORICAL_DECISIONS §25 | — |
| Health check as the first action for an evidenced weak web presence | Approved. A first action, not a replacement for the website offer | Owner, this session | 2026-08-30 |
| Publication records carry the offer; missing stays unknown | Approved | Owner, this session | 2026-08-31 |
| Health-check outreach copy | Approved in principle, with the prohibitions held by tests | Owner, this session | 2026-08-31 |
| Contact cooldown | 14 days, an initial commercial decision rather than a technical default | Owner | 2026-08-30 |
| DevLoop builder/fixer reasoning effort | Pinned to `high` explicitly on every run; never inherited from `~/.claude/settings.json` or any interactive setting; `xhigh` not restored by inheritance; reviewer unchanged; effective effort recorded per invocation in the queue DB. Task `t-94bb2a86a33a` | Owner, decision 1 | 2026-09-02 |
| DevLoop builder/fixer Bash permissions | Strict enumerated read-only allow-list (per git subcommand; never `Bash(git:*)`; no interpreters, no `sed`/`tee`/`xargs`); git mutation unavailable; the permission model is a structural boundary, not a prompt convention. Task `t-94bb2a86a33a` | Owner, decision 2 | 2026-09-02 |
| DevLoop full suite ownership (throughput option 1) | After ADR-0010 T3 lands: builders/fixers run targeted tests; the driver owns and records one un-narrowed full-suite run on the final reviewed branch HEAD before squash-merge for every task; no LANDED/DONE without that recorded pass; existing gates preserved. Brief prepared, enqueued only after T3 | Owner, decision 3 | 2026-09-02 |
| Requeue after CONTESTED | Structural guard in `Queue.add`: a CONTESTED task never retries as the same task; only an explicit human decision (`--decision DQ-nnn`), an architecture decision (`--decision ADR-nnnn`), an explicit successor with narrower-or-equal scope (`narrower_or_equal()` is the single enforcement point; equal kept on the owner's instruction, T1 attempt 2 being the evidence) plus a structured four-field diagnosis — predecessor id, exact prior failure mechanism, material change, why addressable now — with generic wording ('retry', 'attempt 2', 'fix findings') refused and the pair recorded in a `successions` table (`--supersedes --diagnosis JSON`), or abandonment (`abandon`) proceeds; brief or wording changes alone never bypass. Task `t-482d5c2e25db` | Owner, decision 4 | 2026-09-02 |
| DevLoop round/severity policy | Not changed; current blocking semantics kept; see DQ-012 for the 15-run evidence rubric | Owner, decision 5 | 2026-09-02 |
| DevLoop executor location | Stays on the Mac until ADR-0010 T2+T3, real-host rehearse, first human-watched deploy and production verification are complete; see DQ-011 | Owner, decision 6 | 2026-09-02 |
| T2 (t-e44a121a65b1) route after CONTESTED | Route (a): successor t-9f3ecb58b4ad enqueued with a structured diagnosis (predecessor, prior failure, material change, why addressable now) and the same three-path contract; the recurrence is class-level — a centralised checked provenance-write contract is required on every install/rollback/restore/rollback-incomplete/failure path, no outcome finalised before its provenance write succeeds, objective tests for failure at every marker-write site; all five prior findings restated as requirements | Owner | 2026-09-02 |
| DevLoop executor host (DQ-011) | Option C accepted — dedicated Hetzner Cloud VM, CX53-class, Ubuntu 26.04 LTS matching production, no GPU; ADR-0011 committed; Phase 0 approved in order (verify remote/no secrets → push all → verify remote → back up state.db/WAL/SHM/log/briefs → prevent sleep); no provisioning or cutover yet; parked production security findings kept separate | Owner | 2026-09-02 |
| T3 (t-03e23ee8f736) route after CONTESTED | Not abandoned. Decision-first: DQ-013 fixes the shipping-path failure policy (no destructive reset of main, no repository lock, preserve-and-BLOCK unless cleanup is provably limited to squash state, duplicate marker fields fail closed); then a successor with a structured diagnosis, equal three-path scope, all four attempt-1 findings addressed explicitly; the brief is reviewed by the owner before it is enqueued | Owner | 2026-09-02 |
| Hetzner production migration design (DQ-014) | Approved as the governing design; sizing/backup/firewall/key decisions taken; Phase 1 run; provisioning gated on console reads + D-B re-confirmation + explicit GO; five binding requirements AR-1…AR-5 | Owner | 2026-09-03 |
| Production target host (DQ-014, D-R) | D-R-1: reuse existing Hetzner server 164307556 (ex-`qevik-devloop-01`) after a clean console rebuild, `qevik_prod` key only, same id/IPs; no new/replacement server; DevLoop never on production; ADR-0011 amended | Owner | 2026-09-03 |

## DQ-008 — approvals that predate the opportunity model, and one that predates its own evidence

**Open. Nothing has been changed, withdrawn or re-approved.**

Two outreach messages carry `approved_fingerprint` and have never been sent.
Both were approved by hand on 2026-08-19, before missions, signals and
publications existed as records:

* **Malabar Dental Clinic** — 20 observations, 17 findings, HTTP 200. The
  evidence is sound; there is simply no `Signal` naming the business, so the
  dossier says "no opportunity names this business" beside an approved message.
* **Kings — Dental Center Karama Dubai** — latest audit **0 observations, HTTP
  status 0**. The fetch never completed. `73_FIRST_COMMERCIAL_TEST.md` recorded
  on the day that the approved message claims the site "did not finish loading
  within 30 seconds" and that a live check found it loads in 15.8 seconds.

So one approved message contains a claim already known to be inaccurate, and
neither is reachable through the model the rest of the system reasons in.

**Why this is not being decided here.** An approval is a person's act. The
standing instruction is not to reinterpret these five manual approvals, and
withdrawing one, re-approving it against fresh evidence, or attaching it to a
manufactured `Signal` would each be a decision about what somebody meant.

**What is needed:** whether these two are (a) withdrawn, (b) re-approved after
a fresh audit, or (c) left exactly as they are and excluded from any future
automated send. Until then they sit approved and unsent, which is where they
have been since 2026-08-19 and is the safe direction.

<!-- devloop:contested:t-9c7566206741 -->
## Contested — Most observation records are more than a week old

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `packages/kernel/atlas_kernel/opportunity/repository.py:1004-1006` [blocking] Base sweep claims on completed verification passes
  - `packages/kernel/atlas_kernel/opportunity/repository.py:121-129` [major] Share the nightly limit with the actual runner
  - `packages/kernel/atlas_kernel/opportunity/coverage.py:338-341` [major] Stop explaining ages when the pass is below its promised rate
  - `packages/kernel/atlas_kernel/opportunity/repository.py:989-996` [major] Discard observations for a business's previous website
  - `packages/kernel/atlas_kernel/opportunity/repository.py:1018-1021` [major] Measure throughput only for sites in the current queue
  - `/private/var/folders/k4/1yd9slj94ts6fnsn8l1h8p2r0000gn/T/devloop-review-sbp4lv_u/wt/infra/devloop/agents.py:344-347` [blocking] Normalize findings against the review worktree
  - `/private/var/folders/k4/1yd9slj94ts6fnsn8l1h8p2r0000gn/T/devloop-review-sbp4lv_u/wt/packages/kernel/atlas_kernel/mission/api.py:775-777` [major] Read freshness and backlog in the same transaction
  - `/private/var/folders/k4/1yd9slj94ts6fnsn8l1h8p2r0000gn/T/devloop-review-3p4ne2hh/wt/packages/kernel/atlas_kernel/opportunity/coverage.py:368-369` [major] Bound the stale count the cadence can explain
  - `/private/var/folders/k4/1yd9slj94ts6fnsn8l1h8p2r0000gn/T/devloop-review-3p4ne2hh/wt/apps/control/src/index.html:1618-1619` [major] Render unreachable records when the rotation is empty

- **Driver task:** `t-9c7566206741`
- **Review unit:** `a42cd63f8e1e..fb1b2ac25ca2`

<!-- human-decision:cadence-verdict -->
## DQ-009 — what the cadence verdict may claim about stale observations

**Open, and answerable in app.qevik.ai** — Human Actions →
"When should Qevik say the audit schedule explains a stale record?"
This file is the projection; the request is the record, and it carries the
four options with their consequences.

346 of 353 businesses carry observations more than a week old, and the coverage
screen says the schedule explains it. A reviewer showed the test is
magnitude-blind: it says the same thing whether 39 records are stale or 358.

Two things make this a person's call rather than an engineer's.

The docstring's arithmetic is provably false — 359 sites at 40 a night leaves
**39** of 359 past the eight-night line, not "the majority" — but that falsehood
has two repairs producing opposite code, and which is right turns on whether
`per_night` means the declared limit (40) or measured throughput (**7**, on the
one real pass). The repository has visited that question three times and
settled it none.

And no available input distinguishes "the pass is running and not reaching
these sites" from "the pass is draining a backlog after a gap". Qevik's only
production population is the second, so a bound would turn it red.

Blocks devloop task `t-9c7566206741`, which is parked and resumes on the
answer. The loop continues with independent work meanwhile.

## DQ-010 — which write boundary owns an outreach decision

**Open. Not raised as a production decision record.** The analysis is
`docs/decisions/ADR-0009-Outreach-Approval-Atomicity.md` (Status: Proposed —
a decision input, not an implementation approval). When the owner wants this
answerable in app.qevik.ai, the mechanism is `human.raise_request(kind=DECISION)`
on the production host with the ADR's options 1/3/4 as the keys; that has not
been done, on purpose — the instruction was analysis only.

Two development-loop tasks on this line ended CONTESTED after three review
rounds each: `t-b0dfd18dd170` and `t-6057acdb0b35`. **Both are frozen.** They
are not retried, and no unit of work, transaction coordinator or repository
redesign is built without an explicit answer here.

What the ADR establishes from `main` at `28edb9c`:

- Every repository method owns its own session; a service that calls two of
  them has two transactions with a gap. That is the codebase's convention, not
  a defect in one module.
- The one window that cannot be repaired from Qevik's records is on the
  **production** send route — SMTP delivered, message row not yet `sent`; a
  retry passes every guard and delivers again. It is closed by a guarded
  claim-before-send using the conditional write that already exists
  (`b1ee024`), not by any transaction change.
- A message's status change and the business event attributing it must be one
  commit — the shape `approve_signal` already uses. Approval ↔ message across
  the two services is application consistency with a persisted link and an
  idempotent, guarded follower; today the link is one-directional.
- On `main` nothing subscribes to `ApprovalRejected` for outreach, and
  `OpportunityService` is constructed nowhere in production.

The decision: after the compound repository operations (which every option
needs), does Qevik **bridge** the kernel approval system to the message
(option 3: subscriber + reconciler, keeps policy/expiry/approver-count) or
**collapse** it (option 4: the mission route's event + row become the
approval record, one writer, no seam)? Option 4 fits what production runs;
it also decides that outreach approval is governed by the mission and not by
the kernel's approval policies, which is the substance of DQ-005.

<!-- devloop:contested:t-0f8d6a74729c -->
## Contested — A mission that did its work is recorded as failed, with no cause

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `packages/kernel/atlas_kernel/mission/toolrunner.py:1213-1213` [major] Count only sightings actually stored
  - `packages/kernel/atlas_kernel/mission/toolrunner.py:1479-1481` [major] Honor the contactability write result
  - `packages/kernel/atlas_kernel/mission/worker.py:303-303` [major] Preserve live-output data when implementation crashes

- **Driver task:** `t-0f8d6a74729c`
- **Review unit:** `..`

<!-- devloop:contested:t-f81e4bf36fe4 -->
## Contested — Drafted outreach that has never been reviewed

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `packages/kernel/atlas_kernel/opportunity/repository.py:1893-1895` [major] Apply the limit after identifying undecided messages
  - `packages/kernel/atlas_kernel/opportunity/repository.py:1912-1914` [major] Batch evidence-change lookups for the queue
  - `packages/kernel/atlas_kernel/opportunity/repository.py:1930-1932` [major] Apply the limit to messages, not businesses

- **Driver task:** `t-f81e4bf36fe4`
- **Review unit:** `59b97edbc08b..`

<!-- devloop:contested:t-c61027684e89 -->
## Contested — Every page on qevik.ai serves the homepage, and no URL 404s

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `infra/qevik-production.Caddyfile:106-106` [major] Deploy the new 404 artifacts with the Caddyfile
  - `infra/deploy_public.sh:253-258` [blocking] Install the Caddyfile atomically before validating it
  - `infra/deploy_control.sh:281-283` [blocking] Restore Caddy when the control-plane probe fails
  - `infra/deploy_control.sh:265-269` [blocking] Restore the config when public verification fails
  - `infra/deploy_control.sh:283-284` [blocking] Avoid making control deploys depend on untracked assets
  - `infra/deploy_control.sh:85-85` [major] Limit shipped prefixes to files the builder consumes
  - `infra/deploy_control.sh:306-312` [blocking] Verify the API backend, not just its content type
  - `infra/deploy_public.sh:594-597` [major] Do not ignore a restart that may never execute

- **Driver task:** `t-c61027684e89`
- **Review unit:** `5cdbc4e8da18..db29c4ac3d07`

<!-- devloop:contested:t-422b20848039 -->
## Contested — Say why one outreach draft is unreviewed

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `packages/kernel/atlas_kernel/outreach/unreviewed.py:324-330` [blocking] Account for approval-request events
  - `packages/kernel/atlas_kernel/outreach/unreviewed.py:427-429` [major] Require a provably later timestamp for supersession
  - `packages/kernel/atlas_kernel/opportunity/service.py:192-194` [major] Synchronize terminal approval decisions with the message
  - `packages/kernel/atlas_kernel/opportunity/service.py:218-218` [blocking] Wire terminal approval events back to persisted messages
  - `packages/kernel/atlas_kernel/opportunity/gate.py:208-212` [major] Verify the rejection belongs to this message
  - `packages/kernel/atlas_kernel/opportunity/service.py:202-206` [major] Clear awaiting status after an approved send is refused

- **Driver task:** `t-422b20848039`
- **Review unit:** `7a899cd2c6b8..484ed2a33fac`

<!-- devloop:contested:t-b0dfd18dd170 -->
## Contested — Wire terminal approval decisions back to the persisted message

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `packages/kernel/atlas_kernel/opportunity/service.py:255-255` [blocking] Wire terminal approval events into record_decision
  - `packages/kernel/atlas_kernel/opportunity/service.py:239-243` [major] Refuse approval requests for already-decided messages
  - `packages/kernel/atlas_kernel/opportunity/gate.py:278-280` [major] Do not treat non-unique fields as an exact rejection binding
  - `packages/kernel/atlas_kernel/opportunity/service.py:267-274` [blocking] Validate the persisted row before requesting approval
  - `packages/kernel/atlas_kernel/opportunity/service.py:282-290` [major] Avoid leaving an approval behind when message persistence fails
  - `packages/kernel/atlas_kernel/opportunity/service.py:359-361` [major] Make decision writeback conditional on the row remaining open
  - `packages/kernel/atlas_kernel/opportunity/service.py:316-318` [blocking] Claim the message atomically before creating an approval
  - `packages/kernel/atlas_kernel/opportunity/service.py:410-412` [blocking] Persist the refusal only while the message remains open

- **Driver task:** `t-b0dfd18dd170`
- **Review unit:** `..`

<!-- devloop:contested:t-6057acdb0b35 -->
## Contested — Wire approval decisions back to the message, without racing

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `packages/kernel/atlas_kernel/opportunity/service.py:130-144` [blocking] Register the foreclosure handler in the API runtime
  - `packages/kernel/atlas_kernel/opportunity/service.py:453-458` [blocking] Find decisions by the approval's bound message id
  - `packages/kernel/atlas_kernel/opportunity/service.py:590-599` [major] Record suppression only when its guarded write lands
  - `packages/kernel/atlas_kernel/opportunity/gate.py:228-232` [major] Validate that outreach approvals originated from the gate
  - `packages/kernel/atlas_kernel/opportunity/service.py:335-350` [major] Handle a concurrently completed request before withdrawing it
  - `packages/kernel/atlas_kernel/opportunity/service.py:417-423` [major] Keep failed decision audits retryable
  - `packages/kernel/atlas_kernel/opportunity/service.py:742-744` [blocking] Commit suppression and its timeline event atomically
  - `packages/kernel/atlas_kernel/opportunity/service.py:342-348` [major] Preserve claims when request creation persisted before raising

- **Driver task:** `t-6057acdb0b35`
- **Review unit:** `..`

<!-- devloop:contested:t-17a8c4e3e8d4 -->
## Contested — Deploy what main already carries when a deploy task has no diff

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `infra/devloop/driver.py:331-334` [blocking] Require an explicit deploy-only task classification
  - `infra/devloop/queue.py:600-603` [blocking] Requeue failed tasks after declaring deploy-only
  - `infra/devloop/driver.py:687-689` [major] Record only gates that the deploy-only path ran
  - `infra/devloop/queue.py:659-660` [blocking] Refuse requeue after work has already landed

- **Driver task:** `t-17a8c4e3e8d4`
- **Review unit:** `..`

<!-- devloop:contested:t-17fc65e5c5b9 -->
## Contested — Deploy what main already carries when a deploy task has no diff (second attempt)

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `infra/devloop/queue.py:789-792` [blocking] Preserve committed branch work when requeuing
  - `infra/devloop/queue.py:428-430` [major] Check whether the landing is still present
  - `infra/devloop/driver.py:368-370` [major] Isolate prior findings when reviewing unchanged requeued work

- **Driver task:** `t-17fc65e5c5b9`
- **Review unit:** `..`

<!-- devloop:contested:t-8214147cda91 -->
## Contested — Land the deploy-only path without a requeue

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `infra/devloop/driver.py:642-644` [blocking] Revalidate the gated SHA before deploying
  - `infra/devloop/queue.py:597-602` [major] Reject previously attempted QUEUED rows
  - `infra/devloop/driver.py:687-689` [blocking] Deploy the tested commit rather than the mutable tree

- **Driver task:** `t-8214147cda91`
- **Review unit:** `..`

<!-- devloop:contested:t-2825280a3415 -->
## Contested — Do not let a failing test gate spend a review round

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `infra/devloop/driver.py:382-386` [blocking] Keep final failed fixes off main
  - `infra/devloop/driver.py:333-334` [major] Preserve cap counters when resuming a task
  - `infra/devloop/driver.py:360-362` [blocking] Enforce the persisted attempt cap before running gates
  - `infra/devloop/driver.py:425-428` [major] Persist the actual review count on attempt exhaustion

- **Driver task:** `t-2825280a3415`
- **Review unit:** `..`

<!-- devloop:contested:t-18c738db28b4 -->
## Contested — The deploy payload comes from the commit, not the tree (ADR-0010 Step 1, task 1 of 3)

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `infra/deploy_control.sh:185-189` [blocking] Pass the landed SHA from the automated deploy gate
  - `infra/deploy_control.sh:103-105` [major] Guard worker polling from `set -e`
  - `infra/deploy_control.sh:227-227` [major] Verify symlink blobs without rejecting the export
  - `infra/deploy_control.sh:65-65` [blocking] Reject a lone test-host marker before using production defaults

- **Driver task:** `t-18c738db28b4`
- **Review unit:** `..`

<!-- devloop:contested:t-e44a121a65b1 -->
## Contested — ADR-0010 Step 1 / T2: host manifest check, DEPLOYED_SHA provenance marker, rollback hygiene

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `infra/deploy_control.sh:564-566` [blocking] Clear stale snapshots when a target is absent
  - `infra/deploy_control.sh:287-290` [blocking] Treat a failed rollback-marker write as incomplete
  - `infra/deploy_control.sh:707-708` [blocking] Fail the deploy when manifest promotion fails
  - `infra/deploy_control.sh:171-176` [major] Include shipped symlinks in host verification
  - `infra/deploy_control.sh:303-306` [major] Avoid retaining an installed marker when rollback marking fails

- **Driver task:** `t-e44a121a65b1`
- **Review unit:** `..`

<!-- devloop:contested:t-03e23ee8f736 -->
## Contested — ADR-0010 Step 1 / T3: the driver captures S, checks the tree before and after the suite, passes S into the deploy and reads the host's provenance back

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `infra/devloop/driver.py:525-530` [blocking] Clean up the failed squash before returning
  - `infra/devloop/driver.py:657-657` [major] Preserve unrelated edits before resetting the squash
  - `infra/devloop/driver.py:546-547` [blocking] Lock the repository before destructive squash cleanup
  - `infra/devloop/gates.py:443-447` [major] Reject duplicate provenance fields

- **Driver task:** `t-03e23ee8f736`
- **Review unit:** `..`
