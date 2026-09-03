# ADR-0011 — Where the DevLoop executor runs

**Status:** **Accepted** — owner's approval, 2026-09-02, of Option C with the recommended specification (CX53-class, 16 vCPU / 32 GB RAM, Ubuntu 26.04 LTS matching production, no GPU). Nothing has been provisioned, installed, or cut over; provisioning and environment preparation may begin only after ADR-0010 T2b + T3 land, `--rehearse` succeeds against the real host, and the first human-watched production deployment is verified. Cutover additionally requires parallel validation on at least five real tasks (Phase 5). The parked production security findings in §3 stay separate from this migration. Phase 0 approved and executed in the owner's order — see the Implementation record.

**Amendment 2026-09-03 (owner decision D-R-1, `docs/migration/hetzner/DEVLOOP01_SUITABILITY_ASSESSMENT.md`):** the Hetzner server bought on 2026-09-02 as `qevik-devloop-01` (id 164307556, 91.107.244.253, CPX42-shape 8 vCPU / 16 GB / 320 GB — not the CX43/CX53 this ADR named) is **retargeted to production**: it will be rebuilt clean and become `qevik-prod-01` under DQ-014. The DevLoop executor host under Option C is therefore a **future, separate Hetzner server**, to be provisioned only when DevLoop is un-paused and the gates in §9 are met; **DevLoop must never run on the production server** (Option B stays rejected). Everything else in this ADR stands. No DevLoop provisioning is authorised.

**Owner's OS choice (revised 2026-09-02):** Ubuntu 26.04 LTS is the governing environment because production (qevik-core-01) runs 26.04; the earlier 24.04 choice is withdrawn and is not kept as a baseline unless a specific compatibility requirement emerges, in which case it is recorded here as its own decision. Phase 3 therefore compares suite results against production on the same OS version; a divergence there is a finding, not an OS artefact.
**Date:** 2026-09-02
**Decision owner:** Ayoub
**Assessment basis:** read-only inspection of the Mac (2026-09-02), read-only inspection of qevik-core-01 over SSH (2026-09-02), Hetzner public pricing after the 15 June 2026 adjustment, Anthropic and OpenAI documentation for headless authentication. Every claim below is one of CONFIRMED (measured), ESTIMATE (derived from measurements, method stated) or NOT_VERIFIED (not checked; treat as unknown, not as absent).

---

## 1. Decision in one paragraph

Move the DevLoop executor (driver, queue, Claude builder/fixer sessions, Codex reviewer, test suite, deploy client) from the operator's MacBook Air to a **dedicated Hetzner Cloud server that is not qevik-core-01** — Option C — through a seven-phase plan in which the Mac keeps running the real loop until the new host has reproduced identical outcomes on real tasks in parallel. Do not share the production host (Option B). Do not stay on the Mac beyond the gates already set for DQ-011 (Option A). Defer the local HP/Lenovo hardware (Option D) to a later GPU decision; it is not attached, not networked, and its location is unstated.

Nothing starts until the DQ-011 gate is met: ADR-0010 T2 and T3 landed, real-host `--rehearse` passed, the first human-watched deploy done, production verification recorded — *and* the go/no-go criteria in §9 are met.

---

## 2. Current architecture (CONFIRMED unless marked)

### 2.1 Where things are

| Thing | Location today | If the Mac disappears |
|---|---|---|
| DevLoop driver (`infra/devloop/driver.py`) | Mac, hand-launched `nohup … run --once` per task (31 launches so far, `/tmp/task2..32.log`); no launchd, no cron, no supervisor | Loop stops; in-flight task's lease expires; nothing restarts it |
| Queue + state (`~/atlas/.qevik/devloop/state.db`, SQLite WAL, 373 KB) | Mac only; no copy anywhere | **Lost.** 34 tasks, all transitions, reviews, findings, scope checks, runs |
| Driver log (775 KB) + 53 review artefacts | Mac only | Lost |
| Repository `~/atlas` (4.4 GB, `.git` 41 MB) | Mac; `origin` = github.com/hellnight333/atlas; **main is 212 commits ahead of origin/main; last contact with GitHub 2026-08-23**; 36 local branches (16 `devloop/*`, incl. contested branches kept unmerged) | **212 commits of landed work and every contested branch lost** |
| Claude Code auth | claude.ai Max subscription, macOS Keychain (no `.credentials.json`, no `ANTHROPIC_API_KEY`) | Cannot be copied; re-authenticate elsewhere |
| Claude settings | `~/.claude/settings.json` (`effortLevel=high`, `model=opus[1m]`), `settings.local.json` with 679 permission allows; MCP servers `searchapi` (`~/.claude/.mcp.json`) and `higgsfield` (`~/.claude.json`) load into every `claude -p` today | Settings copyable; permission allows and MCP config must **not** be copied blindly |
| Codex auth | `~/.codex/auth.json` 0600 (2026-08-30), `model=gpt-5.6-sol`, `model_reasoning_effort=xhigh` | Re-login elsewhere (device-auth); do not copy the file |
| SSH to production | one key `~/.ssh/naml_hetzner`, used for **both** Naml's and Qevik's hosts, path hard-coded in `infra/devloop/gates.py:350,392` and `infra/deploy_control.sh:68-69` | Key must be replaced, not copied |
| Test database | Homebrew PostgreSQL 16, `atlas_test` via `conftest` / `DEFAULT_DATABASE_URL` in `atlas_kernel/db_safety.py:35` | Recreate on the new host |
| Scratchpad / task briefs | this session's scratchpad under `/private/tmp/claude-501/…` | Lost (briefs for T3, option 1, hardening, requeue guard are here — copy into `.qevik/` or the ADR before migrating) |

### 2.2 The machine

MacBook Air M2, 8 cores (4P+4E), **8 GB RAM**, macOS 26.3.1, 460 GB disk (17 GB used). At inspection: **swap 7.9 GB of 9.2 GB used, load ≈ 8**, `pmset` sleep = 1 min held off only by application power assertions (Claude, V2Box, WhatsApp), hibernatemode 3, on AC. Python for the driver is python.org 3.13.7 (the repo `.venv` is Homebrew 3.14.5 — two interpreters). No Docker, no Redis.

### 2.3 What has to keep running for unattended multi-day operation

1. `driver.py run` (one process; today one task per launch).
2. `claude -p` builder/fixer sessions — ~40 min each, network-bound, must survive sleep and Wi-Fi changes.
3. `codex exec review` — 2–5 min per round.
4. `python3 -m pytest` — full suite 671–855 s serial (4,266–4,285 tests); `-n 4` 308 s but 12 failures from the shared test DB (ESTIMATE of usable parallelism: none until the DB fixture is per-worker).
5. PostgreSQL 16 for the suite.
6. Outbound SSH to qevik-core-01 (`gates.host_reachable`, deploy, provenance gate).
7. Outbound HTTPS to api.anthropic.com, the OpenAI/Codex endpoint, github.com.

### 2.4 Current-state diagram

```
            ┌──────────────────────────── MacBook Air M2, 8 GB ────────────────────────────┐
            │  driver.py (nohup, hand-launched)  ──►  state.db (only copy)                   │
            │        │                                driver.log, 53 reviews (only copy)      │
            │        ├─► claude -p  (Keychain OAuth, Max plan; MCP servers load)              │
            │        ├─► codex exec review (~/.codex/auth.json)                               │
            │        ├─► pytest ──► Postgres 16 (Homebrew)                                    │
            │        └─► ssh -i ~/.ssh/naml_hetzner ─────────────────────────────┐            │
            │  ~/atlas  main = origin/main + 212  (last push 2026-08-23)         │            │
            └────────────────────┬───────────────────────────────────────────────┼────────────┘
                                 │ (stale)                                       │
                     github.com/hellnight333/atlas                     qevik-core-01 (production)
                                                                       2.28.62.83 · 4 vCPU · 7.6 GiB · no swap
                                                                       caddy · qevik-api/control · 5 workers · PG 18
```

Single point of failure: the laptop. Single point of failure for auth: one Keychain, one `auth.json`, one SSH key shared by two companies' hosts.

---

## 3. Existing Hetzner infrastructure: qevik-core-01 (CONFIRMED, 2026-09-02)

| Item | Measured |
|---|---|
| Instance | Hetzner vServer 162146484, nbg1-dc3, Ubuntu 26.04, kernel 7.0, up 15 d, **reboot-required pending**, 54 upgradable packages |
| CPU / RAM / disk | 4 vCPU AMD EPYC Genoa · 7.6 GiB RAM · **no swap** · 150 GB disk, 12 GB used |
| Utilisation | load 0.16–0.26, ≈95 % idle; 0 OOM kills; NRestarts 0 on all units |
| Services | caddy (qevik.ai, www, app., sites.; :8443 tls-internal back-door blocked by ufw) · postgresql@18 loopback (qevik 411 MB, qevik_test 65 MB, 26/100 conns, shared_buffers 128 MB) · qevik-api :8080 (MemoryMax 1536M) · qevik-control :8081 · five mission workers (self-check, research — 235 MB peak, delivery, healthcheck, publish; **uncapped**, system.slice) · `qevik-jobs.slice` MemoryMax 3.5G / CPUQuota 300 % / TasksMax 384, **peak observed 2.45 G** · Playwright browsers 656 MB |
| Repo on host | `/opt/qevik/atlas` 4.8 GB **with `.git`**, HEAD ce4ffaa (Aug 17), 43 modified + 260 untracked files — the running production is not reproducible from any commit; `DEPLOYED_SHA` absent (ADR-0010 fixes this) |
| Secrets | `/opt/qevik/*.env` 0600 (atlas, brave, control, places, worker, .pgpass); `/var/lib/qevik/credentials.jsonl` **0644** (world-readable on the host); many files owned uid 501:staff (copied from the Mac) |
| Backups | `qevik_backup.sh` daily 03:30 pg_dump + verified restore, KEEP=14, newest 19.6 MB, growing 3–4 MB/day; **local disk only, no off-site**; Hetzner snapshot/backup add-on NOT_VERIFIED |
| Access | ufw 22/80/443; sshd `PasswordAuthentication yes` globally (root prohibit-password); one authorized key (no comment); ≈6.2 k brute-force attempts/day; fail2ban inactive |
| Tooling absent | claude, codex, node, npm, uv |
| Logs | journald 631 MB |

### 3.1 Should the DevLoop ever share this host? **No.**

- **Memory.** 7.6 GiB, no swap, with the jobs slice alone already peaking at 2.45 G and the API capped at 1.5 G. A builder session (node), a Codex session, a pytest run and a second Postgres need an ESTIMATE of 4–6 GB together (method: sum of typical RSS for `claude` CLI ~0.5–1.5 GB, `codex` ~0.3–0.6 GB, pytest for this suite ~1–2 GB, PG ~0.3 GB; the Mac's swap figure shows the same shape). The first OOM would be decided by the kernel between a mission worker and the reviewer.
- **Blast radius.** A builder runs arbitrary tests. Today the allow-list stops it from mutating git, but it can run any pytest, and the suite talks to a Postgres. On the same host as production PG 18 and the workers' filesystem, one misconfigured `DATABASE_URL` is a production incident. (On the Mac the worst case is the laptop.)
- **Deployer ≠ deployed.** ADR-0010's whole point is that the deployer measures the host from outside and can roll it back. A deployer that lives on the host it deploys cannot survive the host's failure, cannot rehearse against "the real host" as a separate party, and its rollback dies with the process it is rolling back.
- **Security posture.** The host already accepts password auth globally, has no fail2ban, a pending reboot, and world-readable `credentials.jsonl`. Adding a second set of long-lived AI-provider tokens to it widens what one compromise yields.
- **It is the CTO's laptop problem moved, not solved:** one box would then hold production, its only backups, and the only copy of the development state.

Capacity-wise the host is idle; that is exactly why it is tempting, and exactly what §3.1 argues against. A **separate server is recommended.**

---

## 4. Options

Ratings: ● good · ◐ acceptable with work · ○ poor · ◌ NOT_VERIFIED.

| Criterion | A · Stay on Mac | B · Share qevik-core-01 | C · Dedicated Hetzner Cloud server | D · HP Z8 / Lenovo at home |
|---|---|---|---|---|
| 24/7 reliability | ○ 8 GB, 7.9 GB swap, sleep=1 min held by app assertions, no supervisor | ◐ host is stable but shared | ● always-on, no sleep, systemd | ◌ hardware not attached; power/ISP at home; location unstated |
| Isolation from production | ● physically separate | ○ same kernel, same RAM, same disk, same PG | ● separate VM; only outbound SSH to prod | ● separate |
| Headless Claude / Codex | ◐ works, but inherits interactive settings and MCP servers | ◐ | ● bare-mode, pinned settings, no interactive contamination | ◐ same as A unless set up as a server |
| Auth persistence | ○ Keychain; re-login prompts; tied to the operator's GUI session | ◐ setup-token | ● `setup-token` (1 y) or API key in a systemd credential | ◐ |
| Restart / recovery | ○ manual | ◐ systemd, but competes with prod units | ● systemd `Restart=on-failure`, lease-based reclaim, snapshot restore | ◐ |
| Test / agent performance | ◐ M2 fast; suite 671–855 s serial; heavy swap | ○ steals from prod during a 12-min suite | ● 8–16 vCPU, 16–32 GB; suite ESTIMATE 8–15 min serial (x86 vs M2 unknown until Phase 4) | ● Xeon/i9, lots of RAM |
| Network dependence | ○ operator's Wi-Fi; Iranian-IP TCP loss seen before | ● datacentre | ● datacentre | ○ home ISP; Tailscale currently stopped |
| Secrets | ○ one shared SSH key for two companies; 679 permission allows | ○ adds AI tokens to prod | ● fresh per-host key, tokens as root-only systemd credentials | ◐ |
| Cost | € 0 marginal | € 0 marginal | **€ 16–30 / month** net (see §8) | € 0 marginal + power; hardware exists |
| Maintenance | ○ every run hand-launched | ○ prod change control applies to every dev tweak | ◐ one more Ubuntu host to patch | ○ physical |
| Future local AI / GPU | ○ none | ○ none | ○ none (cloud GPU is a separate decision) | ● RTX 3090 + A4000 exist — but that is the *GPU worker* decision, not the executor decision |

**Recommendation: C.** D remains the right answer for GPU inference later; it is the wrong answer for the executor now because it is not attached, has no network path (Tailscale stopped), and would inherit A's home-network and physical-presence dependencies. A is unacceptable as a multi-day executor on the measured numbers alone. B is rejected on isolation, not capacity.

---

## 5. Specification for the dedicated server (Option C)

Based on the measured workload (one task at a time, CPU-light except during the ~12 min suite; RAM ESTIMATE 4–6 GB per concurrent task).

| | Minimum | Recommended |
|---|---|---|
| Plan | **CX43** — 8 vCPU shared Intel/AMD, 16 GB, 160 GB NVMe, 20 TB traffic · **€ 15.99 / mo net** | **CX53** — 16 vCPU, 32 GB, 320 GB NVMe · **€ 29.49 / mo net** (room for two concurrent tasks, Playwright, and a warm second checkout); or **CCX23** (4 dedicated vCPU, 16 GB, € 85.99) only if CPU steal is measured to hurt the suite in Phase 4 |
| Arm alternative | CAX31 (8 Arm, 16 GB, € 20.99) — NOT recommended: the production host is x86 and the suite's native wheels (Playwright, psycopg) should match prod |
| OS | Ubuntu 26.04 LTS — same as production, so test results transfer |
| Location | nbg1 or fsn1 (same region as qevik-core-01: lowest SSH latency for gates and deploy) |
| Disk layout | root 160/320 GB NVMe; `/srv/devloop` holds repo, `.venv`, state; `/var/backups/devloop` for local SQLite copies |
| Backups | Hetzner backup add-on (daily, 7 slots; priced as a percentage of the plan — NOT_VERIFIED after the June adjustment, historically 20 %) **plus** hourly `sqlite3 state.db ".backup"` + nightly `git push` of every branch to GitHub (this alone fixes today's 212-commit exposure) |
| Networking | Hetzner Cloud Firewall: inbound **22 only**, restricted to the operator's addresses — or, preferred, **no public inbound at all** and Tailscale for SSH; outbound unrestricted (api.anthropic.com, OpenAI, github.com, qevik-core-01:22) |
| SSH | key-only, `PasswordAuthentication no`, `PermitRootLogin no`, non-root user `devloop` with sudo only for `systemctl … devloop-*`; fail2ban |
| Users | `devloop` (runs driver, owns repo), `postgres` (suite DB), root (patching only) |
| Monitoring | node health (`systemd` unit state, disk, RAM) + DevLoop health (`driver.py health`, queue age, last RUN_END) pushed to Telegram on a timer; Hetzner's own server graphs for CPU/network |

Why not a dedicated root server (AX42, ≈ € 46.52 / mo + € 39 setup): the workload is bursty and network-bound; dedicated hardware buys nothing measurable until parallel suites run, and it removes the ability to resize in minutes. It also has **no discrete GPU** — the future-GPU argument does not apply to it either.

---

## 6. Target operating model

```
                     ┌────────────── devloop-01 (Hetzner Cloud, CX43/CX53) ──────────────┐
  Mac / phone ─ssh─► │ systemd: devloop-driver.service  (Restart=on-failure, flock lock)   │
  (Tailscale)        │          devloop-health.timer    (→ Telegram: state, last RUN_END)  │
                     │          devloop-backup.timer    (state.db .backup, git push --all) │
                     │ /srv/devloop/atlas   (repo; branches; driver-owned tree)           │
                     │ /srv/devloop/state   (state.db WAL, driver.log, reviews)           │
                     │ postgres@16 (atlas_test, loopback)                                 │
                     │ credentials: /etc/devloop/*.cred (root:root 0600, LoadCredential=)  │
                     │   CLAUDE_CODE_OAUTH_TOKEN · OPENAI/Codex auth · ssh key devloop-01 │
                     └───────┬──────────────────────┬─────────────────────┬────────────────┘
                             │ https                │ https               │ ssh (new key, its own authorized_keys line)
                     api.anthropic.com        OpenAI / Codex        qevik-core-01 (prod) · github.com (push after every landing)
```

- **Persistent execution.** `devloop-driver.service`, `Type=simple`, `ExecStart=flock -n /run/devloop/driver.lock python3 infra/devloop/driver.py run --max-tasks N`, `Restart=on-failure`, `RestartSec=60`, `KillSignal=SIGTERM`, `TimeoutStopSec=` long enough for a Claude session to finish or the lease to be handed back. **NOT_VERIFIED:** whether `driver.py` handles SIGTERM by releasing the lease; Phase 4 must test a `systemctl stop` mid-build and confirm the task returns to QUEUED (or stays BUILDING with an expired lease that the next start reclaims) rather than becoming a zombie.
- **Single instance.** `flock` on the unit *and* the queue's existing lease (`q.renew`) — two mechanisms, either sufficient. Never run `driver.py run` by hand on the server; `driver.py status/inspect/enqueue` remain hand tools.
- **Durable state.** `state.db` stays SQLite WAL; hourly `.backup` to `/var/backups/devloop/state-<ts>.db` (keep 48) + daily to the Hetzner backup; `driver.log` under logrotate (weekly, keep 8, compress); stdout/stderr to journald with `SystemMaxUse=1G`.
- **Alerts.** Timer every 10 min: unit active? last transition age? any task in FAILED/BLOCKED/CONTESTED since last alert? disk < 20 %? RAM pressure? Each new terminal state → one Telegram message (the same vocabulary the driver log uses: LANDED, DONE, CONTESTED, FAILED, BLOCKED). Which bot/channel is a decision for Ayoub (NOT_VERIFIED that a Qevik-side bot exists; Naml's `@naml88_bot` must not be reused without a decision).
- **Remote observation.** From the Mac or a phone over Tailscale: `ssh devloop-01 'cd /srv/devloop/atlas && python3 infra/devloop/driver.py status'`; `journalctl -u devloop-driver -f`; the projection files `EXECUTION_STATE.md` / `DECISION_QUEUE.md` are pushed to GitHub with every landing and readable there.
- **Safe stop.** `systemctl stop devloop-driver` (SIGTERM, waits); `driver.py` gets a `--drain` flag *or* the unit is stopped only between tasks via a `stop-after-current` marker file — one of these must exist before cutover (Phase 4 verifies).
- **Workspace isolation.** Keep today's model (one driver-owned tree, `devloop/<id>` branches) — it is what the scope contract and `clean_tree` assume. Do not introduce worktrees or bare mirrors in the migration; that would be a DevLoop change, not an infrastructure change.
- **Backup / recovery.** Loss of the server = restore from Hetzner backup (≤ 24 h old) + latest GitHub push (≤ 1 landing old) + latest `state.db` copy (≤ 1 h old). Recovery drill is a Phase 5 gate.

---

## 7. Claude / Codex migration constraints

| Question | Answer (source: Anthropic / OpenAI docs, verified 2026-09-02) |
|---|---|
| Can the Mac's Claude login be moved? | **No, and it must not be attempted.** It lives in the macOS Keychain; Linux uses `~/.claude/.credentials.json`, which the docs manage only through `/login` / `/logout`. Copying the file is unsupported and refresh-token rotation is NOT_VERIFIED (a copy could invalidate the Mac's session). |
| Supported headless auth | (1) `claude setup-token` on any machine with a browser → long-lived OAuth token (**1 year**, needs Pro/Max/Team/Enterprise) → `CLAUDE_CODE_OAUTH_TOKEN` in the service's environment; cannot use Remote Control or claude.ai connectors. (2) `ANTHROPIC_API_KEY` (Console, pay-as-you-go), takes precedence, always used in `-p` mode. |
| Terms | Subscription usage limits "assume ordinary, individual usage"; Pro/Max OAuth may not be used with the Agent SDK or third-party services; Anthropic's documented recommendation for automation is the API key. Which model of billing the executor runs under is **a decision for Ayoub (DQ-011a)**, not something to migrate silently. Per-task token cost is NOT_VERIFIED — the driver does not record usage today (the hardening task adds `agent_runs`; add `usage` to it before Phase 5 so the API-key cost can be measured on real tasks). |
| Codex | `codex login --device-auth` on the server (one-time code entered from a browser elsewhere) or `OPENAI_API_KEY`. Do not copy `~/.codex/auth.json` (docs: "treat like a password"; rotation NOT_VERIFIED). Whether ChatGPT-plan auth is permitted for long-running `codex exec` is NOT_VERIFIED — same decision as above, for the reviewer. |
| MCP / connectors | Today's `claude -p` loads user-scope MCP servers (searchapi, higgsfield) and claude.ai connectors into every builder session. On the server none of these should exist: run bare (`--bare`, or `--mcp-config '{}'` + `ENABLE_CLAUDEAI_MCP_SERVERS=false`). `_claude_argv` does not pass these today — that is a one-line DevLoop change to fold into the hardening task (t-94bb2a86a33a) or its successor, not into the migration. |
| Settings | Copy nothing from `~/.claude/settings.local.json` (679 interactive allows — the allow-list task replaces them structurally). `settings.json` model/effort are being pinned in argv anyway. |
| Credential storage | systemd `LoadCredential=` from `/etc/devloop/` (root:root 0600); the service user cannot read the files, only the running process sees them; never in the repo, the DB, logs, prompts, or Telegram. Rotation: setup-token yearly (put the expiry in the health timer so the alert fires 30 days before); SSH key per host, revoked by deleting one `authorized_keys` line. |
| Detecting auth expiry unattended | non-zero exit + stderr `Login expired` / `OAuth session expired and could not be refreshed` / `401`; the driver's `_infra` path should classify that as BLOCKED-tooling with an alert, not requeue forever (NOT_VERIFIED how `_infra` behaves on repeated identical failures; check in Phase 4). |
| Never copy | Keychain, `.credentials.json`, `~/.codex/auth.json`, `~/.ssh/naml_hetzner`, `settings.local.json`, `~/.claude.json`, any `.env`, the scratchpad. |

---

## 8. Cost (net €/month, Hetzner DE/FI, post-2026-06-15; VAT depends on the billing entity)

| Configuration | Server | Backup add-on (NOT_VERIFIED %, shown at 20 %) | Total |
|---|---|---|---|
| Minimum CX43 | 15.99 | ≈ 3.20 | **≈ 19.2** |
| Recommended CX53 | 29.49 | ≈ 5.90 | **≈ 35.4** |
| Dedicated-CPU fallback CCX23 | 85.99 | ≈ 17.20 | ≈ 103 |
| Root server AX42 | 46.52 + 39 setup | — | ≈ 46.5 (+ one-off) |

One-off: none beyond ~2–3 operator hours per phase. Not included: any change from subscription to API-key billing for Claude or Codex, which could dominate the server cost and must be measured (§7) before it is decided.

---

## 9. Migration plan (reversible at every phase; the Mac stays live through Phase 5)

| Phase | What happens | Reversible? | Go/no-go to leave the phase |
|---|---|---|---|
| **0 · Now, no server** (no-regret, still needs approval because each is an outward action) | `git push --all` to GitHub from the Mac; copy `state.db` and the four pending briefs into `.qevik/` or a backed-up place; `caffeinate`/`pmset` so the Mac stops sleeping mid-build | trivially | pushed refs == local refs; state.db copy restores and `driver.py status` reads it |
| **1 · Provision** | Create devloop-01 (CX43 or CX53), Ubuntu 26.04, firewall inbound 22 only from operator IPs or none + Tailscale, backups on, `devloop` user, sshd hardened, unattended-upgrades security-only | delete server | `ssh devloop@devloop-01` works with a new key; password auth refused (tested); Hetzner backup enabled |
| **2 · Configure** | Python ≥3.11, PostgreSQL 16 loopback, ffmpeg, Node (for claude), `claude` + `codex` CLIs, Tailscale; generate the server's own SSH key; **ask** to add it to qevik-core-01's `authorized_keys` (a production change — human, not automation); `claude setup-token` (from the Mac's browser) → root-only credential file; `codex login --device-auth` | delete server | `claude -p 'say ok' --bare` and `codex exec 'say ok'` succeed as the `devloop` user; `ssh qevik-core-01 true` succeeds; no credential readable by `devloop` |
| **3 · Clone** | `git clone` from GitHub (after Phase 0) — **not** `rsync ~/atlas`; `.venv`; run the full suite on the server against its own `atlas_test`; copy a `state.db` snapshot (read-only use) | delete server | full suite passes on the server (count and duration recorded, compared with the Mac's 671–855 s / 4,266–4,285) |
| **4 · Dry run** | systemd unit installed but pointed at a **copy** of state.db in a scratch dir; enqueue a synthetic docs-only task; observe build → gates → review → land into the *server's* clone (not pushed); test `systemctl stop` mid-build, crash (`kill -9`), reboot; test the auth-expiry path with a deliberately wrong token; test alerts | delete server | one synthetic task DONE end-to-end; stop/crash/reboot each recover without a duplicate driver or a stuck lease; alert received on the phone |
| **5 · Parallel validation** | Mac remains the live executor. The server runs the **same** real task briefs against the **same** base sha in its own clone (results not landed, branches not pushed), ≥ 5 tasks; compare gates, scope verdicts, review verdicts and durations | delete server | ≥ 5 tasks with equivalent outcomes; suite time ≤ 2× Mac; no auth failure in the window; recovery drill (restore from backup) done once |
| **6 · Cutover** | Stop the Mac driver between tasks; `git push`; copy the live `state.db` (WAL checkpointed) to the server; start `devloop-driver.service`; first task on the server is a trivial, reviewed, non-deploy task and is **watched** | yes: stop the unit, copy state.db back, restart on the Mac | one real task LANDED/DONE from the server; projection pushed; Mac driver not started since |
| **7 · Mac becomes non-critical** | Remove the shared key from qevik-core-01's `authorized_keys` (human action), keep the Mac as an observer (`status`, enqueue), record in ADR-0011 Implementation record; DQ-011 → RESOLVED | — | one unattended week: no manual launch, backups verified, alert path exercised at least once |

Deploy work (ADR-0010 real deploys) does **not** move until Phase 7 is complete and observed; until then deploys stay human-watched from wherever the human is.

---

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Subscription-token automation conflicts with Anthropic's terms or gets rate-limited mid-task | Decide billing model before Phase 5 (DQ-011a); measure tokens per task in Phase 5; keep the API-key path ready (env var swap, no code) |
| Token expiry after a year, silently | health timer knows the issue date; alert 30 days out; `_infra` classifies auth failure as tooling-BLOCKED with alert (verify Phase 4) |
| Two drivers (Mac + server) on the same queue | state.db is never shared over the network; the server gets a copy; `flock` + lease; Phase 6 stops the Mac first |
| Server compromise yields prod SSH + AI tokens | inbound closed; per-host SSH key with its own `authorized_keys` line (revocable in one edit); credentials root-only via `LoadCredential`; builder allow-list already forbids shell mutation |
| Suite slower on shared vCPU | measure in Phase 3; rescale to CX53 or CCX23 without re-provisioning |
| Losing contested branches / unpushed work during the move | Phase 0 push of *all* branches is the first gate; Phase 3 clones from GitHub, never from the Mac |
| The driver does not survive SIGTERM/reboot cleanly | Phase 4 tests each; if the driver needs a `--drain`, that is a small DevLoop task enqueued by priority — not hand-patched on the server |
| Hetzner region/network incident | the Mac remains capable of running the loop from a fresh clone + state.db backup (that is the Phase 6 rollback); production is on a different VM in the same region — accept |
| Cost creep to dedicated CPU | only on a measured steal problem; the decision is recorded |

---

## 11. Go / no-go for DQ-011 (all must hold before Phase 1)

1. ADR-0010 T2 and T3 landed on main.
2. `QEVIK_DEPLOY_SHA=<main tip> ./infra/deploy_control.sh --rehearse` passed against qevik-core-01 from a clean checkout.
3. First real deployment done, human-watched, on a trivial reviewed commit; production verification recorded (marker + manifest + fingerprint agree).
4. Billing model for headless Claude and Codex chosen and recorded (DQ-011a).
5. Alerting channel for the executor chosen (which Telegram bot/chat).
6. Phase 0 completed: all branches pushed; state.db backed up off the Mac.
7. Ayoub's explicit approval of this ADR's Option C and spec.

No-go if any of: T2/T3 still open; a production deploy has not been observed; the billing decision is unmade; or the migration would be run by the DevLoop itself (it is operator work, human-executed, at every phase).

---

## 12. What this ADR does not decide

- The GPU worker (HP Z8 / RTX 3090) — separate decision; unaffected by where the executor runs.
- ADR-0010 Step 2 (release directories, atomic switching).
- Any change to DevLoop rounds, gates, or scope rules.
- Any production-host hardening found in §3 (password auth, fail2ban, `credentials.jsonl` 0644, pending reboot, off-site DB backups) — these are **reported here and parked**; each is a production change that needs its own approval.


---

## Implementation record

- **2026-09-02 — decision.** Owner approved DQ-011 Option C (dedicated Hetzner Cloud VM, CX53-class 16 vCPU / 32 GB, no GPU; OS first stated as Ubuntu 24.04 LTS, revised the same day to 26.04 LTS to match production); ADR committed as documentation; Phase 0 approved in the order: (1) verify remote and that no secrets are pushed, (2) push all branches/tags, (3) verify the remote holds current main and the DevLoop history, (4) back up `state.db` + WAL/SHM, driver log and pending briefs to an independent backed-up location, (5) prevent sleep while the Mac remains the executor. No provisioning or cutover yet.
- **2026-09-02 — Phase 0 step 1 (CONFIRMED).** Remote is `origin = github.com/hellnight333/atlas`; main was 213 commits ahead of `origin/main`, 36 of 37 local branches had no upstream. All 1,303 blobs reachable only from local refs were scanned for secret-shaped content (provider keys, GitHub tokens, private keys, DSNs with passwords, generic `token=`/`password=` assignments): every hit is a synthetic test fixture or the literal `screenshot-session-not-a-real-token` in `infra/screenshot_console.py`; no `.env`, key, or credential file is tracked; `.qevik/devloop/` is untracked.
- **2026-09-02 — Phase 0 step 4 (CONFIRMED).** Consistent `sqlite3 .backup` of `state.db` (integrity_check ok, 35 tasks, 373 transitions) plus raw `state.db`/`-wal`/`-shm`, `driver.log`, 53 review artefacts, `DECISION_QUEUE.md`, `EXECUTION_STATE.md`, the five pending briefs, the T2b diagnosis and this ADR, with a SHA-256 manifest (70 files, 2.2 MB), written to iCloud Drive `QevikDevLoopBackup/20260902T121657Z/` (iCloud status: full-sync, caught-up). Sources were grepped for secret patterns before copying: none.
- **2026-09-02 — Phase 0 step 5 (CONFIRMED).** `caffeinate -dimsu` running (pid 53360; `PreventSystemSleep 1`). Not persistent across reboot; a closed lid on battery still sleeps.
- **2026-09-02 — Phase 0 steps 2–3.** `git push --all origin` was refused by the operator's tool-permission layer in this session; the push must be run by the owner (or the permission granted) before step 3 can be verified. Until then the 213 commits and the kept contested branches still exist only on the Mac.
- **2026-09-02 — Phase 0 steps 2–3 (CONFIRMED).** The owner ran the push. Verified afterwards from the Mac: `origin/main == main` (235579d), all 37 local branches (17 `devloop/*`, including every kept contested branch and `devloop/t-03e23ee8f736`) have an identical-named remote ref, 14 tags on the remote, remote tip dated 2026-09-02 16:59 +0330. A complete off-laptop copy of the repository history now exists; `.qevik/devloop/` (state.db, logs) is still local-only by design and is covered by step 4.
- **2026-09-03 — server retargeted (owner decision D-R-1).** A server named `qevik-devloop-01` (id 164307556, 91.107.244.253, nbg1-dc3, CPX42-shape) was created by the owner on 2026-09-02 12:18 UTC ahead of this ADR's Phase 1 gates; a read-only assessment found it bare, idle, patched and referenced by no code. The owner decided to reuse it as the **production** migration target (`qevik-prod-01`, DQ-014) after a clean console rebuild followed by an AR-2 key swap to `qevik_prod` only (Hetzner re-injects the creation key at rebuild, so the swap is the first action on the fresh host). Consequences for this ADR: Phase 1 "Provision" has not happened; the executor host will be a different, future server; DevLoop stays paused; the `devloop_01` key will have no host and should be deleted from the Mac and the Hetzner project once the swap is proven (owner actions).
