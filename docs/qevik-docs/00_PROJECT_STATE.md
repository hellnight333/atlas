# Qevik — Current Project State

**Last consolidated: 2026-08-17**

## Canonical execution environment

**`qevik-core-01` — Hetzner, 2.28.62.83.** Ubuntu 26.04 LTS, 4 vCPU AMD EPYC
Genoa, 8 GB RAM, 150 GB disk. Python 3.14.4.

This is the authoritative server for Qevik Core / control plane / development.
Personal machines are clients.

- Qevik lives at `/opt/qevik/atlas`, owned by a non-root `qevik` user (§28).
- PostgreSQL 16 native, loopback only. Role and database `qevik`.
- Config at `/opt/qevik/atlas.env` (0600, `qevik`). The password exists only
  there and in `/opt/qevik/.pgpass`; it is not in Git and is never printed.
- GitHub access is a **read-only deploy key** — the server can pull, not push.
- `ufw` active, port 22 only.

Reproduce the whole thing with `infra/bootstrap_qevik_server.sh`, which is
idempotent and has been re-run against a live install to prove it. It installs
the service too, so bare server → running system is one script.

### Scheduled, running on their own

- `qevik-market-scan.timer` — 06:00 daily. Answers "which niche, which
  geography" from live data, so nobody has to be asked. Research only: reads
  public pages and Places, contacts nobody, produces no proposals.
- `qevik-backup.timer` — 03:30 daily. Takes a dump **and restores it into a
  scratch database to prove it works**, per §29: a backup that has never been
  restored is not a verified backup. Unverified dumps are kept with an
  `.UNVERIFIED` suffix rather than deleted.

### Google Places

Configured, IP-restricted to the server, key in `/opt/qevik/places.env` (0600,
outside the repo). The client is pinned to IPv4 — a dual-stack host prefers IPv6
and Google then answers `API_KEY_IP_ADDRESS_BLOCKED`, which reads like a wrong
key and is not.

**It was worth paying for, and the numbers say why.** Reachability went from
2–17% on OpenStreetMap to 83–100% on Places. Reachability, not defect rate, was
the constraint that made every market unworkable. A full six-niche scan costs
about $0.58.

### Running services

- `qevik-api` — systemd, enabled at boot, restarts on failure (verified by
  SIGKILL, not by reading the config). `127.0.0.1:8080`, health returns 200.
- `postgresql` — systemd, enabled at boot.
- Only port 22 is publicly reachable. `ufw` active.

**The API is bound to loopback because it has no authentication layer.** Reach
it from a laptop with an SSH tunnel:

```
ssh -N -L 8080:127.0.0.1:8080 root@2.28.62.83
# then http://127.0.0.1:8080/health on the laptop
```

Do not change the bind address without adding auth first — that would publish an
unauthenticated control plane.

### Proven working on the server (not asserted)

LEVEL 3 and LEVEL 4 of the roadmap were driven against the live API:
workspace → project → run → auto-created job → worker polled it → executed →
completed with a provider recorded. Artifacts persist (assets table populated).

This closes these §39 items: Hetzner canonical · Qevik starts reliably ·
PostgreSQL starts reliably · clean DB init · full suite green · Claude Code can
work on the repo · a tracked job can be created · an agent can execute a task ·
logs persisted · artifacts persisted.

**Not yet verified:** survival of an actual reboot. The service is `enabled`, so
the mechanism is right, but nobody has rebooted the box to watch it come back.

**Not** the Naml automation box at 204.168.249.69. That runs 50 production
containers at load ~12 and is a different system.

## Current identity
Working product/brand: **Qevik**.

## Current technical milestone
Google OAuth/Gmail integration has reached a real end-to-end test.

Reported by Claude:
- A real Gmail message was sent through the complete M014 path.
- Approval gate, fingerprint verification, suppression and cooldown executed.
- Duplicate outreach was blocked by a 90-day cooldown.
- Editing a proposal after approval was blocked by fingerprint mismatch.
- Suppressed addresses were blocked.
- Secrets were kept outside the repository and logging was hardened.

## P1 execution & growth layer — P1.1 through P1.6 complete (2026-08-22)

Five phases, each gated on review, all in `packages/kernel/atlas_kernel/`:

| Phase | Module | What it establishes |
|---|---|---|
| P1.1 | `opportunity/tenancy.py`, `db_safety.py` | Tenant isolation at the repository layer; 352 real businesses migrated to the Qevik house org; 1,683 fixture rows quarantined reversibly; the test suite can no longer write to production |
| P1.2 | `recommendation/` | `Recommendation` + `CapabilityOffer` bridging Opportunity → Job without a sixth job-state registry |
| P1.3 | `execution/` | One complete vertical slice ending at `READY_TO_PUBLISH`; six QA gates; `publish()` deliberately raises |
| P1.4 | `measurement/` | Attribution scale (UNKNOWN/OBSERVED/ASSOCIATED/ATTRIBUTED) where the level licenses the permitted language |
| P1.5 | `roadmap/` | 0→100 readiness + the plan derived from it — see [`P1_5_ROADMAP_ENGINE.md`](P1_5_ROADMAP_ENGINE.md) |
| P1.6 | `roadmap/{lifecycle,gate,crossing,presentation}.py` | The plan crosses into work through the existing approval and job machinery — see [`P1_6_ROADMAP_TO_EXECUTION.md`](P1_6_ROADMAP_TO_EXECUTION.md) |

**P1.5 in one line:** two real businesses put through the same code path share
exactly one task, and it is a measurement task true of both.

**P1.6 in one line:** the loop closes — Research → … → Roadmap → Task →
Approval → Job → Execution → Asset → QA → READY_TO_PUBLISH → Measurement →
Re-evaluation — with the task's state derived from states that already exist
rather than stored in a tenth place.

Nothing in P1 publishes, sends, bills or connects a provider.

## P2.1 — Publication Foundation (2026-08-22)

`READY_TO_PUBLISH` now becomes `PUBLISHED` through a **second approval** — see
[`P2_1_PUBLICATION_FOUNDATION.md`](P2_1_PUBLICATION_FOUNDATION.md).

The execution approval asks *"should Qevik perform this work?"*; the artefact
approval asks *"may this exact output go to this exact destination?"* Somebody
can want a portfolio system and reject the one that was built, so the two
decisions stay separate and are fingerprinted differently.

One real target is connected: a local directory a web server serves, reusing
`website/targets/` publish-then-promote. Credentials are held as **references**
— an environment variable name, a vault key — never as secrets; construction
refuses a reference that looks like a token, and `resolve()` re-checks tenant
ownership because a `Connection` is a value that can be passed anywhere.

`execution.service.publish()` still refuses, and now says where publication
actually lives.

## P2.2 — Website creation / modification (2026-08-22)

The first capability to run the **whole loop** — research to a published page —
see [`P2_2_WEBSITE_CAPABILITY.md`](P2_2_WEBSITE_CAPABILITY.md). One executor and
one offer; every other stage already existed.

`offer-website` answers `performance`, `broken` and `thin_content`, the three
website opportunities that previously had no offer at all. Two modes, neither
chosen by a caller: CREATE when research could not read a site, MODIFY when one
exists — and MODIFY adds only what research **confirmed absent**.

`build_website` raises rather than producing an artefact when a site already
does everything it could add. That is STRONG WEBSITE + LIMITED OPPORTUNITY where
it cannot be argued with: nothing exists to approve, publish or bill for.

Generation reuses the M015 Website Factory whole, including its rule that there
is no `FactSource` meaning "a model wrote it".

## P2.3 — the Website vertical, complete (2026-08-22)

No new capability; the loop closes — see
[`P2_3_WEBSITE_VERTICAL.md`](P2_3_WEBSITE_VERTICAL.md).

**Four website states, not two.** Research now emits a `website` finding, and
DNS separates "no such host" (conclusive) from "did not answer" (establishes
nothing). ABSENT enters through a `no_website` opportunity; UNVERIFIED produces
no opportunity at all and the capability refuses to build against it.

**Staging is wired into approval.** GENERATED / READY_TO_STAGE / STAGED /
APPROVED / PUBLISHED are distinct and derived, an approver gets the preview URL
of the real page, and `is_live()` asks the target whether anybody is being
served it. Staging before QA passes is refused.

**Publication is an intervention.** `from_publication()` makes the record's
completion time the measurement's `intervention_at`, and `Progress` gives the
five honest answers to "what do you know yet".

**Re-evaluation is classified** — improved, worsened, resolved, no longer
required — with the historical plan left untouched.

**Offered ≠ executable** is now visible: two offers have executors, five do not,
and the customer view says so.

## P2.4 — the customer boundary (2026-08-23)

Nine read routes under `/api/customer`, four small kernel modules, one field on
`User` — see [`P2_4_CUSTOMER_WORKFLOW.md`](P2_4_CUSTOMER_WORKFLOW.md).

**One schema change**, genuinely required: `qevik_users.tenant_id`. Nothing else
could turn an authenticated request into a `TenantId`. Empty means *not
established*, so operator accounts keep the internal surfaces and reach none of
the customer ones.

The tenant is resolved from the user and never from the request — no route takes
one in a path, query or header. Another tenant's resource is **absent, not
forbidden**: identical 404 and identical body, because 403-vs-404 tells an
attacker which ids exist.

**A checkbox is not proof.** Customer task completion records how it was
established — observed, an approval, an artefact, or a signed attestation — and
`complete()` refuses a Qevik task outright.

`strategy.summarise()` produces the paragraph a customer reads, derived from
their own evidence and passed through the claim gate. `public.py` is an
allow-list, not a redaction. `measurement/schedule.py` answers "what is due"
without being a scheduler.

**Two real bugs P1.6 surfaced**, both documented in
[`P1_6_ROADMAP_TO_EXECUTION.md`](P1_6_ROADMAP_TO_EXECUTION.md) §10: five
capabilities were being presented as executable that no executor exists for, and
`portfolio_depth` — a *defect* signal everywhere else in the codebase — was
being scored as a strength, which suppressed AHS's biggest opportunity.

## Capabilities added since the Gmail milestone

**Browser operation** — `packages/kernel/atlas_kernel/browser/`. A `BrowserSession`
interface owned by Qevik with a Playwright backend behind it, so the runtime is
substitutable. Two profiles are declared: research (isolated, no credentials) and
operational (authenticated, approval-gated). **The operational profile is deliberately
unbuilt** — a browser acting inside a signed-in session is the largest blast radius in
the whole system and nothing needs it yet.

Callers never write CSS selectors; `_elements()` generates refs. Proven live against a
real Dubai business site: 200, 120 elements, screenshot at 1440x900, 2.5s, 998 MB of
7740 MB used.

**Multi-provider LLM routing** — `packages/kernel/atlas_kernel/llm/`. Callers state what
a job needs (context, tools, vision); the registry resolves the cheapest model meeting
it. Qwen's hosted API (`qwen-turbo`/`plus`/`max`, international DashScope host) is
registered alongside Claude. A 20k-token draft costs **$0.0018 on qwen-turbo against
$0.60 on claude-opus-5**, so routine drafting, extraction and classification route to
Qwen and only harder work reaches Claude. `qwen3-72b` is declared at zero cost per token
for when the Z8 becomes a worker; local-first ordering will take that traffic with no
other change.

A provider registers only when its credential is present. Registering one without a key
would turn a clear `NotConfigured` at call time into a silent selection of a model that
cannot run. Env vars: `QEVIK_DASHSCOPE_API_KEY`, `QEVIK_ANTHROPIC_API_KEY`.
**No Qwen key has been supplied yet.**

## Test state
**Full suite is GREEN as of 2026-08-23 on the Mac: 2261 passed, 25 skipped**,
ruff 22 (down from 43) and mypy 135 — P1.5 through P2.4 add none of either.
- The 25 skips include 6 in `test_production_is_not_a_test_fixture.py`, which
  read production read-only and skip when no production URL is configured. They
  were verified to still **fail** when one is, so the detector is live rather
  than quietly disabled.
- Two unrelated blockers were fixed to get here, both documented in
  [`P1_5_ROADMAP_ENGINE.md`](P1_5_ROADMAP_ENGINE.md) §8: the conftest database
  redirect did not cover the case where `ATLAS_DATABASE_URL` is unset, and the
  demo-registry guard knew two of the three ways a demo can be built.

**Earlier baseline — 2026-08-17: 1136 passed, 4 skipped, 91.88% coverage**
(gate 90%), ruff clean.
- Earlier in the same day, on `qevik-core-01`: 1040 passed, coverage 92.16%.
- On the Mac the two agreed to within 0.03%.
- The 4 skips are demo-installer tests that skip once demos exist.

One environment blocker was found and fixed: without `ffmpeg`/`ffprobe`, 85
media tests skip and coverage falls to 88.22% — a red build caused by a missing
binary rather than by any code being wrong. `ffmpeg` is now installed and is in
the bootstrap script.
- Verified twice; the second run shows 1040 passed + 4 skipped, which are
  demo-installer tests that skip once demos exist ("already installed by an
  earlier run"). Benign and expected.
- ruff, tsc, oxlint, rustfmt and clippy all clean.

PostgreSQL was not actually down. The server was running; the role `atlas` and
database `atlas` did not exist, so every connection failed with
`role "atlas" does not exist`. Both were created.

Creating them then exposed a real bug: `init_db()` could not build the schema
from nothing. An `ALTER TABLE atlas_scene_renders` ran before that table's
`CREATE TABLE`, and because the whole of `init_db()` is one transaction, the
failure rolled everything back and left zero tables. Invisible on any database
that already had the table — which was every database anyone had used. Fixed by
moving the ALTER after the CREATE.

## Google credentials
Desktop/installed OAuth client.
Local path:
`~/.qevik/credentials/google_client_secret.json`
Permissions: `600`
First scope:
`https://www.googleapis.com/auth/gmail.send`
Google app remains in Testing.

## Immediate priorities
1. ~~Restore PostgreSQL and run the complete test suite.~~ **Done.**
2. ~~Make Hetzner the canonical environment.~~ **Done 2026-08-17 — `qevik-core-01`.**
3. ~~Answer niche + geography + offer from data rather than opinion.~~ **Done** — the
   daily market scan answers it and keeps the answer current. See below.
4. **Next, and explicitly requested:** review
   `QEVIK_PENDING_IMPLEMENTATION_DOCS/11_QEVIK_AUTONOMOUS_MEDIA_GROWTH_BUSINESS_ENGINE.md`
   (1710 lines, 46 sections) for gaps against a real business operation loop. Ayoub
   named Google Play (§15) and Apple (§16) publishing as needing to be more
   professional, and asked it to "go far enough into the actual business operation
   loop". Nothing has been implemented from doc 11.
5. Build §18/§19 of the browser/publishing architecture — commercial website and
   subscriptions. **Ayoub has explicitly asked for these** after reading the
   recommendation to defer them until the first paying customer. That recommendation
   still stands on the merits; the decision is his and it is made.
6. Run a small, manually approved Opportunity Factory pilot.
7. Keep broad Atlas → Qevik internal refactoring deferred.

### What the market scan actually found
**Contactability, not defect rate, is the binding constraint.** OpenStreetMap yielded
2–17% reachable businesses across every Dubai niche; Google Places 83–100%. That is the
whole reason Places costs money and is worth it.

The best market moved car-repair → dental → beauty across runs. That instability is the
argument for a scheduled daily scan rather than a decision taken once and written down.

### Open, waiting on you
- **Qwen API key** — set `QEVIK_DASHSCOPE_API_KEY` on the server and Qwen starts taking
  the routine jobs immediately. Nothing else changes.
- **Brave search key** — approved, not yet supplied. Blocks general web research;
  Places finds *businesses* and cannot answer "research these competitors".
- **Places key rotation** — the current key was shown in a screenshot. It is now IP
  restricted to `2.28.62.83`, which contains the damage, but rotating it is still the
  right move.

## Portfolio — FROZEN 2026-08-21

Thirteen showcase entries, twelve of them hand-built single files plus the
bilingual clinic site from the vertical renderer. **No further samples.** The
portfolio phase is closed; the next work is commercial validation, not more
product.

The last two additions were chosen for what the portfolio could not yet prove:

- **Word Rush** (`sample-wordrush`) — bilingual Arabic/English vocabulary
  trainer. Carrot Dash already proved a real-time physics loop; this proves
  persistent state, a review surface, and an entire interface that switches
  language and direction at runtime rather than at build time.
- **Kilo** (`sample-kilo`) — mobile-first gym member app. Pulse already covered
  fitness as a dark analytics dashboard; this is the operational half, where a
  booking takes a seat and a set tick moves the week's volume.

A third commercial website was **deliberately not built**. Luxury salon
(Atelier), fine dining (NAR) and premium real estate (Meridian) already cover
that ground, and a fourth website-shaped sample would have reintroduced the
exact "one template in different colours" problem the differentiation checker
exists to prevent.

All twelve hand-built samples are structurally distinct: closest pair 0.45
against a 0.62 threshold (`infra/differentiation.py`).

### Guards added because this phase found the gaps
- `apps/public/build.py` derives the asset copy list from `SHOWCASE` and
  **refuses to build** if any page references an asset it did not copy. The
  hand-maintained list drifted the moment SHOWCASE grew, and shipped two cards
  whose `<img>` pointed at nothing.
- `test_public_site.py` now checks that every showcase entry has its thumbnail,
  is actually in `deploy_samples.PORTFOLIO`, and that a `bilingual: True` flag
  (which emits a `/ar/` link) is only claimed by a site that has one.


## Scheduled work — 2026-08-26

The database backup had failed on every run since **2026-08-18**: eight days, no
verified backup, and no signal in the console, on the phone, or in any report.
The unit ran as `User=qevik` and its script sourced a root-owned `0600` env file
itself; the other four units use `EnvironmentFile=`, which systemd reads as root
before the privilege drop. Fixed there rather than by loosening the file.

That nothing reported it is the finding. **Recurring work is now expressed as
missions** (`mission/recurrence.py`), so a scheduled failure appears where every
other mission failure appears. It creates missions and stops — it does not
claim, dispatch or run, and `AutomationEngine` was deliberately not used because
it feeds a different execution path than the one in production.

`RECURRENCES` is empty on purpose. The production worker runs
`--repository /opt/qevik/atlas` and commits into a worktree of it, so nothing
can honestly claim `modifies_qevik_itself=False`. **The next architectural
dependency is an execution workspace that is not Qevik's repository**, and it is
the precondition for unattended overnight work and autonomous discovery.

See `docs/RECURRENCE.md`.

## Workspace isolation — 2026-08-26

Missions no longer run inside the production checkout. `/opt/qevik/atlas` is the
**origin**, read once per mission and never written; each mission gets its own
`git clone --no-hardlinks` and the worktree is created inside that. The
promotion boundary — getting a mission's branch into production — is unchanged
and still an explicit human act, now with the guarantee that *not* performing it
leaves production untouched.

Self-modification policy is unchanged. A clone of Qevik is still Qevik, decided
from the origin rather than the workspace, derived from `__file__` so no
configuration disables it. A second guard in the worker refuses a Qevik-origin
mission that reached the queue without a person.

`Origin.EMPTY` (`--repository none`) is what unattended recurring work was
waiting for: work with no source repository can now honestly declare it does not
modify Qevik, and an autonomous mission has been run end to end on that path.

The worker's `--repository` is still a *worker* flag, so one worker serves one
origin. Making it a per-mission property with an allow-list is the next step.

See `docs/WORKSPACE_ISOLATION.md`. Open security findings are recorded in
`docs/SECURITY_FINDINGS.md`.

## Deferred
- Broad package/schema/database rename.
- High-volume autonomous prospecting.
- Adding every Google API scope at once.
- Giving agents unrestricted access to personal browser accounts.
