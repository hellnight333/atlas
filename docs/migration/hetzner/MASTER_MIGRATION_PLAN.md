# MASTER_MIGRATION_PLAN — Qevik production → new Hetzner production host

Phase 0 deliverable 7. Governs the migration of Qevik production from
`qevik-core-01` (2.28.62.83) to a new Hetzner production host.
**Revised 2026-09-03 (D-R-1):** the target is the **existing** Hetzner server
**164307556** (`91.107.244.253`, nbg1-dc3), formerly `qevik-devloop-01`, rebuilt
clean and renamed **`qevik-prod-01`**; no server is purchased
(`DEVLOOP01_SUITABILITY_ASSESSMENT.md`). The pre-2026-09-03 sentence "devloop-01
is never a production target" is withdrawn; what remains binding is that
**DevLoop never runs on the production server** (ADR-0011 amendment).

Companion documents (same directory): `CURRENT_INFRASTRUCTURE_INVENTORY.md`,
`CURRENT_PRODUCTION_SERVICE_GRAPH.md`, `DATA_AND_STATE_INVENTORY.md`,
`SECRET_AND_DEPENDENCY_INVENTORY.md`, `MIGRATION_RISK_REGISTER.md`,
`HETZNER_TARGET_ARCHITECTURE_DRAFT.md`, `EXECUTIVE_MIGRATION_READINESS_REPORT.md`.

## Global rules (apply to every phase)

1. Evidence discipline: every claim about either host is PROVED / OBSERVED / INFERRED / UNKNOWN. UNKNOWN stays UNKNOWN until evidence exists.
2. Secrets never transit the agent, chat, Markdown, git, task DB, logs, or command lines. Owner → target only (secret inventory §5).
3. "Copy succeeded" is never evidence. Every transfer is proven by checksum manifest, row count, restore test, or a functional probe.
4. The old host is **read-only for the agent** until Phase 9's approved stop step, and is never destroyed before Phase 11.
5. Every phase ends with a written evidence record under `docs/migration/hetzner/evidence/phase-N/` (no secret values) and an explicit owner go/no-go where marked.
6. The DevLoop remains paused for the duration; no autonomous tasks are enqueued for migration work.
7. Server 164307556 (`qevik-prod-01`, ex-devloop-01) is changed only by the approved Phase 2+ steps; before its rebuild it is not used for anything else.
8. Verification is done from **two vantage points** before any claim of "reachable" / "unreachable" (feedback_verify_from_second_vantage_point). **U16 (D-R-1):** the second vantage is no longer devloop-01; it is `qevik-core-01` running **read-only** `curl`/`nc`/`dig` (an explicit AR-4 carve-out — reads only, no writes, no installs) plus an external HTTPS checker; the Mac never counts as the sole vantage.

Legend for approval: **OWNER GO REQUIRED** = the phase may not start without an explicit owner message.

---

## Phase 0 — Discovery & Evidence Freeze  *(COMPLETE — this document set)*

- **Objective:** capture the current production environment with evidence and classify every fact.
- **Prerequisites:** existing SSH to both hosts; repo at `6ad8a98`.
- **Allowed:** read-only commands, `dig`, `curl`, `ls`, `stat`, `du`, `journalctl`, `systemctl status/cat`, `psql` read-only catalogue queries, env-file **names** via `cut -d= -f1`.
- **Forbidden:** everything that writes on either host; reading secret values; `cat` of env files; package installs.
- **Evidence required:** the scratchpad captures (`prod-*.txt`, `devloop01.txt`, `dns.txt`, `repo-discovery.md`) — retained outside the repo because they contain redacted argv lines; the eight deliverables in this directory.
- **Success criteria:** all eight deliverables written; UNKNOWN list and owner-decision list enumerated; no secret values in any file (grep-verified).
- **Rollback:** n/a (nothing changed).
- **Stop conditions:** any command that would write to production → abort.
- **Owner approval:** required to proceed to Phase 1 (review of this set). **STOP HERE — current state.**

## Phase 1 — Architecture & Capacity Decision

- **Objective:** turn `HETZNER_TARGET_ARCHITECTURE_DRAFT.md` §10 (T1–T10) and the UNKNOWN list into owner decisions.
- **Prerequisites:** Phase 0 reviewed.
- **Allowed:** owner reads Hetzner console (project, server type list, backup add-on state of 162146484, firewall), Cloudflare zone settings (SSL mode, rules); agent records decisions as text; agent may run additional **read-only** discovery the owner asks for.
- **Forbidden:** creating anything in Hetzner or Cloudflare; repo code changes.
- **Evidence required:** `evidence/phase-1/decisions.md` listing each T-item with the owner's answer; Cloudflare SSL mode recorded (resolves the Full/strict INFERRED); Hetzner backup add-on state recorded (resolves UNKNOWN #1); answers to D2/S1/S6/S11/A6/P2/D6 UNKNOWNs.
- **Success criteria:** every T1–T10 decided; every data UNKNOWN reclassified or explicitly deferred with a named owner decision; sizing chosen.
- **Rollback:** n/a.
- **Stop conditions:** owner declines to decide → plan pauses (DQ-009: agent never decides for the owner).
- **Owner approval:** the decisions **are** the approval; **OWNER GO REQUIRED** to enter Phase 2.
- **Status 2026-09-03:** COMPLETE — decisions D-A/B/C/D/F approved, D-L for Phase 1 only; evidence `evidence/phase-1/`; report `PHASE_1_COMPLETION_REPORT.md`. Console reads U1/U2 remain owner-pending (no API access exists). D-B re-confirmation (CPX32 vs CX43/CX33) at the Phase 2 gate.

## Phase 2 — Target Preparation by Rebuild  **(COMPLETE 2026-09-03 — rebuilt, qevik_prod-only, upgraded+rebooted, backups on, firewall verified U16, Storage Box ordered; evidence in `evidence/phase-2/`)**

*Revised 2026-09-03 under D-R-1: no server is purchased. The existing Hetzner server
**164307556** (`91.107.244.253`, `2a01:4f8:1c1b:1dbe::1`, nbg1-dc3, 8 vCPU / 16 GB /
305 GB, currently named `qevik-devloop-01`) is rebuilt in the console and becomes
**`qevik-prod-01`**. The exact console steps are in `PHASE_2_OWNER_CONSOLE_ACTIONS.md`.*

- **Objective:** server 164307556 is a **freshly rebuilt** Ubuntu 26.04 host named `qevik-prod-01`, with **only** the `qevik_prod` key authorised, image backups enabled, a Cloud Firewall (22/80/443 + ICMP) attached, the same id and IPs, and a Storage Box ordered.
- **Prerequisites:** D-R-1 (given); `qevik_prod` key pair generated and its **public** key registered in the Hetzner project (O2); owner console session.
- **Allowed:** **owner** performs every console action (register `qevik_prod` → rename → rebuild [image only; Hetzner re-injects `devloop_01` at first boot — FAQ] → backups on → firewall attach → Storage Box order); agent, on GO, performs the **key swap under AR-2 as the first action on the fresh host** (add `qevik_prod`, prove session B, reduce `authorized_keys` to one line, prove session C, prove `devloop_01` refused) and verifies over SSH **with `qevik_prod` only**: `os-release`, `hostnamectl`, `nproc`, `free`, `lsblk`, `ufw status`, `sshd -T` subset, `apt list --upgradable | wc -l`, `authorized_keys` = one line = `qevik_prod` fingerprint, journal has exactly one boot; agent may `apt full-upgrade`, `hostnamectl set-hostname qevik-prod-01` and reboot **this host only** if the owner includes that in the GO.
- **Forbidden:** creating, ordering, resizing or deleting any server; touching `qevik-core-01`; any Cloudflare change; installing Qevik components (Phase 4); any use of `devloop_01` after the AR-2 swap (it must not remain authorised — SR-4; it is retired from the project and the Mac in the same phase).
- **Evidence required:** `evidence/phase-2/host-identity.txt` (server id, name, IPv4/IPv6, product name and price as shown in the console, new host-key fingerprint from the console, hardware, disk, region, firewall rule listing, backup state, Storage Box order id — no credentials); first-SSH `known_hosts` fingerprint match recorded.
- **Success criteria:** `ssh -i ~/.ssh/qevik_prod -o IdentitiesOnly=yes root@91.107.244.253` works from the Mac and the host-key fingerprint equals the console value; `devloop_01` refused after the swap; `authorized_keys` one line; all three host-key fingerprints differ from the pre-rebuild values recorded in `PHASE_2_OWNER_CONSOLE_ACTIONS.md` §1; journal shows one boot since rebuild; disk ≤ 2 GB used; second vantage (U16) confirms 22 open, 80/443 closed until Caddy; reboot-required cleared.
- **Rollback:** console rebuild again (free); nothing depends on the host. Deleting the server is **not** a rollback option (D-R-1 item 8).
- **Stop conditions:** console shows a product/price different from CPX42-class ≈ €69.49 (record and continue only if the owner says so); the rebuild dialog offers no Ubuntu 26.04 image; the server sits in a project with unrelated resources the owner did not intend; the console shows an attached Volume, snapshot or firewall nobody expected — stop and report.
- **Owner approval:** each console step is the owner's own action; the agent's post-rebuild SSH verification and optional upgrade/reboot need an explicit GO.

---

## ENABLEMENT — deployment-path fixes  *(inserted 2026-09-03 by owner decision; reviewed code only)*

- **Objective:** the reviewed deployment tooling can address `qevik-prod-01` safely and reproducibly, before any production credential exists. Specification: `MIGRATION_ENABLEMENT_SPEC.md`; findings: `PHASE_4_PRE_EXECUTION_REVIEW.md`.
- **Scope:** six workstreams — deploy target + SSH identity parameterisation (B-3), Caddy installation method (B-1), Caddyfile source of truth (B-2), env/password parsing (B-4), unit/timer/slice inventory and activation guard (B-6), migrated-dump protection (B-5).
- **Allowed:** repository changes with tests, run locally/CI; documentation amendments.
- **Forbidden:** any host change on either server; any secret value; any deploy; DNS; DevLoop.
- **Evidence required:** the reviewed commits with passing tests, including the negative controls (the old shell form fails the metacharacter fixture; the version gate rejects Caddy 2.6.2; an unknown target name refuses instead of falling back).
- **Success criteria:** `--rehearse` resolves the new host with the `qevik_prod` key and `naml_hetzner` appears nowhere in its argv; defaults still point at the old host; the full test suite is green.
- **Rollback:** revert the commits; defaults are unchanged, so the old host stays addressable exactly as today.
- **Owner approval:** approval of `MIGRATION_ENABLEMENT_SPEC.md` and the D-S1…D-S7 answers, then review + push of each commit.
- **Status 2026-09-04: ACCEPTED AND CLOSED.** `3103ced656f6e18acf496591c9abe5e525dbd55b` is the approved repository baseline; the implementation is not modified further unless a later phase reveals a concrete defect.
- **Status 2026-09-03:** IMPLEMENTED, awaiting review. Six reviewed commits (`ac150d1`, `0934ac7`, `2f4659c`, `01db2bf`, `5fa9cc7`, `4a3aa9f`) with 60+ new tests; `MIGRATION_ENABLEMENT_SPEC.md` §13a records what landed and where it differs from the specification. No host was touched, no secret handled, no deploy run. Phase 3 starts only after this is reviewed (D-S7 = all six workstreams first).

## Phase 3 — Security & Access Baseline

- **Objective:** the target's access posture is the hardened one, and the owner has placed the secrets on the target.
- **Execution plan:** `PHASE_3_PRE_EXECUTION_PLAN.md` (2026-09-04) — command-level boundary, AR-2 procedure with dead-man recovery, firewall rules, fail2ban policy, swap, the account and ownership model, validation and rollback per group, and the STOP gates. Written against the approved repository baseline `3103ced` and superseding every earlier Phase 3 sketch.
- **Sequencing change (owner, 2026-09-03):** Phase 3 is now gated on the **ENABLEMENT stage** below — production credentials are created only after the deployment path is proven capable of safely targeting `qevik-prod-01` (`MIGRATION_ENABLEMENT_SPEC.md`). In particular the DB password may not be chosen until B-4 has landed, so its entropy is never traded for shell-safety. The Phase 3 execution plan is written after that work is reviewed and pushed.
- **Prerequisites:** Phase 2.
- **SSH hardening procedure (owner requirement AR-2, mandatory):** two independent sessions — keep session A open; install the `qevik_prod` key; prove a fresh session B with that key (`IdentitiesOnly=yes`); apply sshd changes, `sshd -t`, reload; prove from devloop-01 that password auth is refused; prove reconnect with session C; only then close A. Never a disconnect-and-reconnect gamble.
- **Allowed (agent):** sshd hardening (`PasswordAuthentication no`), ufw 22/80/443 (+ cloud firewall per T3), fail2ban if decided, create `qevik` user, create `/opt/qevik` and `/var/lib/qevik` skeleton with correct ownership, `umask` guidance. **Allowed (owner):** create `/opt/qevik/{atlas,control,worker,brave,places}.env` with new/rotated values (O3–O7), 0600, correct owner per unit `User=`.
- **Forbidden:** agent reading, copying, or generating any secret value; copying env files from the old host; changing anything on the old host (including rotating its DB password — that happens **after** cutover, Phase 10/11).
- **Evidence required:** `sshd -T` effective values; `ufw status numbered`; `stat -c '%U:%G %a %n' /opt/qevik/*.env`; env **names** per file via `cut -d= -f1` compared against secret inventory §1 (K1–K7) — must be a superset of the old host's name set (`ATLAS_DATABASE_URL, QEVIK_ADMIN_PASSWORD, QEVIK_DASHSCOPE_API_KEY, QEVIK_DASHSCOPE_BASE_URL, QEVIK_LEDGER, QEVIK_REPORTS_STORE, QEVIK_SITES_BASE_URL` / `QEVIK_VAULT_MASTER_KEY, QEVIK_CLAIMS_DSN, QEVIK_REQUIRE_ATOMIC_CLAIMS` / `QEVIK_CLAIMS_DSN, QEVIK_REQUIRE_ATOMIC_CLAIMS` / `QEVIK_BRAVE_API_KEY` / `QEVIK_GOOGLE_PLACES_API_KEY`).
- **Success criteria:** password SSH refused (tested from the second vantage, U16); env-file names match; modes 0600; `QEVIK_LEDGER`, `QEVIK_REPORTS_STORE`, `QEVIK_REQUIRE_ATOMIC_CLAIMS`, `QEVIK_SITES_BASE_URL` present (values entered by the owner to match the old host's semantics — S3/S4 note).
- **Rollback:** rebuild the server (Phase 2 rollback).
- **Stop conditions:** any secret value appears in a shell history, transcript, or file the agent can read → stop, owner rotates it.
- **Owner approval:** owner's completion of the env files is the gate; agent may not proceed until the owner says the files are in place. **The exact owner procedure is `PHASE_3C_OWNER_ENV_PROCEDURE.md`** (paths, names, modes, DSN sequencing, a validator that prints digests rather than values, and removal instructions). STOP GATE 3-D is separate and needs its own GO.

- **Status 2026-09-03: COMPLETE.** Executed on the owner's GO per `PHASE_3_PRE_EXECUTION_PLAN.md`: 2 GB swap, key-only sshd (`MaxAuthTries 3`) proved under AR-2, `ufw` mirroring the Cloud Firewall, fail2ban, the `qevik` service account (`nologin`, uid 999), and a reboot test that all of it survived. Two plan corrections the host forced are folded in and owner-accepted: **C-1** the running sshd re-reads its config only on `systemctl reload ssh.service`, and **C-2** fail2ban bans through the distribution's `nftables` action, not `ufw`. Evidence: `evidence/phase-3/execution-2026-09-03.md`. The owner's env files (STOP GATE 3-C) and the GO for Phase 4 (3-D) remain outstanding; no secret was handled.

## Phase 4 — Application Runtime Preparation

- **Objective:** the target runs the same unit set, Caddy config, Postgres version, venv and Playwright as the old host, against an **empty** database, and passes the deploy contract's rehearsal.
- **Prerequisites:** Phase 3 complete (host baseline + owner-typed env files); **the four B-blockers' repo changes reviewed and pushed by the owner** (B-2, B-3, B-4 below — these supersede and widen the original R-12/O10 item); `pip freeze` and `pip show playwright` captured **read-only** from the old host into `evidence/phase-4/old-host-freeze.txt` (already captured 2026-09-03: 52 distributions, `playwright 1.62.0`, Chromium build 1234).
- **Allowed:** on the target: `apt install postgresql-18 python3-venv python3-pip git curl ffmpeg rsync`; **Caddy from the upstream Cloudsmith `caddy/stable` repository, matching production 2.11.4 — never Ubuntu's `caddy` package (B-1)**; create role/db `qevik` (owner supplies the password via `psql` interactively or `\password`); install `qevik-jobs.slice`, `resources.conf`, and the **repository** Caddyfile with the `:8443` block removed (B-2, D-D); `playwright install --with-deps chromium` pinned to the same build; `deploy_control.sh --rehearse` with the target host **and the `qevik_prod` key**, both parameterised (B-3); then the real `deploy_control.sh` with `QEVIK_DEPLOY_SHA` = SHA deployed on the old host or the reviewed successor; `deploy_console.sh`/`deploy_public.sh` equivalents to the target; install both timers by hand (no deploy path ships a `.timer`) and `systemctl enable` the seven services explicitly (the deploy enables nothing).
- **Forbidden:** pointing anything at the old host's DB or state; running `enable_domain.sh` (incompatible, §14.2.4); running `bootstrap_qevik_server.sh` unmodified (installs only `qevik-api`, opens 22 only, `git clone`s on the host, overwrites `atlas.env`); installing **Ubuntu's Caddy 2.6.2** (B-1); copying the old host's **live** `/etc/caddy/Caddyfile` over the newer committed configuration (B-2); using `~/.ssh/naml_hetzner` against the target in any script or by hand (D-F/SR-4, B-3); weakening the DB password's character set or entropy to survive a shell (B-4 — the deploy is fixed instead); **enabling `qevik-backup.timer`** while the migrated dumps sit unprotected in `/opt/qevik/backups` (B-6); any Cloudflare change; LE issuance attempts that need public :80 (no traffic yet) — certs are copied in Phase 6 or issued via a temporary hostname if T5 = re-issue.
- **Evidence required:** `systemctl list-unit-files 'qevik-*'` (7 services enabled + the timer states chosen under B-6); sha256 of each installed unit vs repo; `caddy version` **≥ 2.11** and `caddy validate`; `DEPLOYED_SHA`/`DEPLOYED_MANIFEST` on target; `pip freeze` diff vs old host; `/health` 200 on 8080 and 8081 over loopback; `/api/health` components; `atlas_workers` rows show 5 target workers with the expected version fingerprint; **reboot test** of the target — everything returns (R-14); the migrated dumps still present and byte-identical after every step (B-6).
- **The four blockers (recorded 2026-09-03 from `PHASE_4_PRE_EXECUTION_REVIEW.md`, owner-accepted):**
  - **B-1 Caddy version.** Ubuntu 26.04 ships Caddy **2.6.2**; production runs **2.11.4** from `dl.cloudsmith.io/public/caddy/stable`; `infra/qevik-production.Caddyfile` needs **≥ 2.7** (`handle_errors` + `file_server { status 404 }`). The target installs the upstream package. *Host/runbook change; no repo change required.*
  - **B-2 Configuration source of truth.** The **repository** `infra/qevik-production.Caddyfile` is authoritative, not the older live 225-line file, which still carries the SPA fallback the repo already fixed. The target's config is the repo file **minus the `:8443` block**. *Repo change required (removes the block and one hard-coded IP).*
  - **B-3 Deploy target and identity.** `deploy_control.sh`, `deploy_console.sh` and `deploy_public.sh` hard-code both `2.28.62.83` **and `~/.ssh/naml_hetzner`**. Host **and** key must be parameterised, defaults unchanged until cutover so a rollback needs no commit. *Repo change required — this is R-12/D-H, widened.*
  - **B-4 Secret handling in the deploy.** `deploy_control.sh` sources `/opt/qevik/atlas.env` in a shell (`set -a && . $ENV_FILE`), so a password containing shell metacharacters breaks the schema step. **The parsing is fixed** (systemd's own `EnvironmentFile` semantics, the same parser the units use); the password's entropy and character set are never constrained to work around it. *Repo change required.*
- **Two standing records (2026-09-03):**
  - **B-5 Migrated dumps are protected from local retention pruning.** `/opt/qevik/backups` holds the 11 verified production dumps pulled from the old host; `qevik_backup.sh` prunes to `KEEP=14` newest `qevik-*.dump` in that directory. Before any backup unit runs on the target, those files move to an archive layout outside that glob (e.g. `/opt/qevik/backups/archive/`), which `qevik-offsite.service` still ships off-host.
  - **B-6 `qevik-backup.timer` stays disabled** until the data-migration phase that gives the target a real database (Phase 6), unless the safer archival layout in B-5 is explicitly implemented and verified first.
- **Success criteria:** all of the above; zero differences in unit files; venv diff explained line-by-line.
- **Rollback:** wipe `/opt/qevik/atlas` and re-deploy; or rebuild server.
- **Stop conditions:** `deploy_control.sh` refuses (dirty tree / non-ancestor SHA) → fix in repo under review, never bypass; Playwright cannot be pinned to build 1234 → record and ask the owner.
- **Owner approval:** review + push of the **B-2/B-3/B-4 repo changes** (formerly O10/R-12) is an owner gate inside this phase, and D-E (certs) is decided inside it. No other go required.

## Phase 5 — Data Migration Preparation

- **Objective:** every MIGRATE item has a written, tested transfer + verification procedure; every UNKNOWN in `DATA_AND_STATE_INVENTORY.md` §9 is resolved.
- **Prerequisites:** Phase 4; owner answers to §9 items 1, 2, 4, 6, 7; `QEVIK_REPORTS_STORE` value confirmed by the owner (item 3).
- **Allowed:** read-only on the old host: `pg_dump --schema-only` to compare with the target's schema after `init_db()`; generate sha256 manifests of `/var/lib/qevik/control`, `/var/lib/qevik/evidence`, `/var/lib/qevik/jobs`, `/var/lib/qevik/{prospects,outreach,audits,briefs,workspaces}`, `/srv/sites`, `/opt/qevik/backups` (manifests written to the **Mac/scratchpad**, not to the old host); write the transfer scripts (`rsync -aH --chown=qevik:qevik` with `--dry-run` first; `pg_dump -Fc` → `pg_restore` into a scratch DB on the **target**).
- **Forbidden:** any write on the old host (manifests are generated with output redirected off-host); restoring into the target's live `qevik` DB (scratch DB only in this phase); touching `qevik_test` unless the owner classified it.
- **Evidence required:** `evidence/phase-5/manifests/*.sha256` with file counts and byte totals matching the inventory sizes (±growth); schema diff old vs target-after-init_db (must be empty or every difference explained by a commit between the two SHAs); a **timed dry run** of the full copy set (expected: minutes).
- **Success criteria:** written runbook for Phase 6 and Phase 9 with exact commands; every manifest reproducible twice with identical hashes (proves the source is quiescent enough, or shows which trees change under load).
- **Rollback:** n/a.
- **Stop conditions:** schema diff shows the target kernel is *older* than the source data → stop (R-03); manifests differ between two runs on trees expected to be static → investigate before Phase 6.
- **Owner approval:** owner answers to §9 UNKNOWNs are the gate.

## Phase 6 — Initial Sync (while live)

- **Objective:** the target holds a complete, verified copy of production data as of a timestamp T0, with the old host still serving traffic.
- **Prerequisites:** Phase 5 runbook.
- **Allowed:** `pg_dump -Fc` on the old host **to stdout over SSH** (no new files on the old host) → restore into the target's `qevik` DB (first time: the DB is empty from Phase 4; drop and recreate before restore); `rsync` of the MIGRATE trees from old → target (old host is the rsync **source**, never the destination); copy of `/var/lib/caddy` if T5 = copy; `qevik_backup.sh --verify-only` on the target against the transferred dump.
- **Forbidden:** stopping anything on the old host; writing to the old host; starting the target's workers against the restored DB with **live** external effects (publish worker, delivery, healthcheck outbound) — see Phase 7 gating; changing the target env to point at the old DB.
- **Evidence required:** per-table row counts old vs target (all 75 public tables) at T0; manifest verification on target (`sha256sum -c`) for every tree; `verify_schema()`/`check_integrity()` output on the target; certificate files present with correct ownership; total bytes transferred.
- **Success criteria:** zero manifest mismatches; row counts equal for static tables and explained for hot tables (`atlas_worker_heartbeats`, `atlas_business_events`, `qevik_mission_claim`) by the T0 timestamp; restore test passes.
- **Rollback:** drop target DB / wipe target trees and repeat.
- **Stop conditions:** restore error; any mismatch not explained by post-T0 writes; disk or memory pressure on the old host during dump (monitor `free`/load; dump is ~20 MB compressed so this is unlikely).
- **Owner approval:** not required to run (read-only on old host), but the owner is told when it runs.

## Phase 7 — Shadow Validation

- **Objective:** prove the target is functionally production, using the copied data, **without** public traffic and without side effects on the real world.
- **Prerequisites:** Phase 6.
- **Allowed:** on the target: start all units; `curl --resolve app.qevik.ai:443:127.0.0.1` / `qevik.ai` / `sites.qevik.ai` against the target's Caddy; login with the migrated operator account; read missions/approvals/credential records via the console; run a **self-check** mission (agent `self-check` — no external effect); serve one published site from `/srv/sites` and compare bytes with the old host; `/api/health` all components green; `atlas_workers` shows 5 target workers; **owner-supervised** test of one external integration per key (DashScope, Brave, Places — new keys from Phase 3) using the smallest possible call; reboot test repeated with data present; from devloop-01: `curl --resolve <host>:443:<new-ip>` for the four names (bypassing Cloudflare) to prove the origin serves the correct certificate and content.
- **Forbidden:** any outreach/delivery/publish action with real-world effect; changing Cloudflare; letting the target's workers pick up **real** queued missions that would run twice (the target's DB copy contains the same QUEUED missions as production → **workers on the target must run with an isolated tenant or the mission table quiesced during shadow** — the exact mechanism is a Phase 5 runbook item; if no safe mechanism exists, workers stay stopped during shadow and are validated only by self-check under owner supervision).
- **Evidence required:** `evidence/phase-7/`: probe outputs from loopback and the second vantage (U16); console screenshot(s) without secrets; `/api/health` JSON; worker registry rows; site byte-diff result; reboot log.
- **Success criteria:** every probe in the Phase 9 validation checklist passes on the target **before** cutover; no duplicate mission execution occurred (verified against the old host's ledger by mission id — read-only).
- **Rollback:** stop target units; fix; repeat.
- **Stop conditions:** any evidence of the target acting on real missions/customers; any integration key failing (fix keys before proceeding); reboot leaves any unit down.
- **Owner approval:** owner supervises the integration tests; **OWNER GO REQUIRED** to proceed to Phase 8 runbook sign-off.

## Phase 8 — Cutover Runbook Preparation

- **Objective:** a step-by-step runbook with exact commands, expected outputs, timings, decision points and the rollback procedure, rehearsed as far as possible without touching production.
- **Prerequisites:** Phase 7 passed.
- **Allowed:** write `evidence/phase-8/CUTOVER_RUNBOOK.md`; rehearse the Cloudflare change on a **non-protected test hostname** (e.g. `migrate-test.qevik.ai` → target) if the owner creates it; rehearse the final delta (dump + rsync) against the target with the old host live (identical to Phase 6, timed); rehearse rollback of the DNS on the test hostname.
- **Forbidden:** touching the four protected names; stopping old-host services; any old-host write.
- **RPO / RTO (owner requirement AR-1):** the runbook states the explicit maximum data-loss window and expected rollback time for R0/R1/R2/R3 (proposed in `OWNER_DECISION_AND_FINAL_ARCHITECTURE.md` §7.1); the owner approves those numbers as part of D-M. No cutover on "minutes may be lost" wording.
- **Evidence required:** timed rehearsal results (delta sync duration D, validation duration V); the runbook with a pre-cutover checklist (owner present, Cloudflare dashboard open, Hetzner console open, old-host snapshot taken if T1 backups on, rollback commands pre-typed).
- **Success criteria:** runbook reviewed by the owner; projected downtime = stop + D + V + Cloudflare change ≈ minutes, written down; rollback proven on the test hostname.
- **Rollback:** n/a.
- **Stop conditions:** rehearsal shows D or V unexpectedly large; any step needs a credential the owner has not provided.
- **Owner approval:** **STOP FOR OWNER APPROVAL.** No Phase 9 action without an explicit owner go that names the date/time window.

## STOP FOR OWNER APPROVAL

Cutover is irreversible in effect (public traffic moves; the old host stops
writing). Nothing below may begin without an explicit owner instruction that
references this runbook and a window.

## Phase 9 — Cutover  **(OWNER GO REQUIRED; owner present)**

- **Objective:** traffic and writes move to the target with verified data equality.
- **Prerequisites:** Phase 8 approval; owner online with Cloudflare + Hetzner consoles; old-host snapshot/backup taken (if available) within the last hours; target units stopped (workers) and ready.
- **Allowed sequence (from the runbook):**
  1. Announce start; record T1.
  2. On the old host (**first and only writes to it by the agent, approved**): `systemctl stop qevik-worker qevik-worker-research qevik-worker-delivery qevik-worker-publish qevik-worker-healthcheck qevik-market-scan.timer qevik-backup.timer`, then `qevik-control`, then `qevik-api`. Caddy stays up serving static (or a maintenance page — T-decision) so the site does not vanish. Verify `pg_stat_activity` has no `qevik` backends.
  3. Final delta: `pg_dump -Fc` → target (drop + restore into `qevik`); `rsync` delta of MIGRATE trees with `--delete` **on the target only**; re-run manifests and row counts → must be equal (no explanation allowed this time, source is quiescent).
  4. Start target: `qevik-api`, `qevik-control`, five workers, timers. `/health`, `/api/health`, worker registry (5 fresh heartbeats).
  5. Origin checks from the second vantage (U16) via `--resolve` for the four names.
  6. **Owner** changes the four Cloudflare A/AAAA records to the target IP.
  7. Public checks: `https://qevik.ai`, `https://app.qevik.ai/health`, `https://app.qevik.ai/api/health` (auth), `https://sites.qevik.ai/<slug>/`, `X-Qevik-Host` headers; from the second vantage (U16) and the Mac; `cf-ray` present; login works; one self-check mission completes on the target.
  8. Record T2; downtime = T2 − T1.
- **Forbidden:** deleting or modifying anything on the old host beyond stopping units; starting old-host units again unless rolling back; any step out of order.
- **Evidence required:** `evidence/phase-9/`: timestamps, stop confirmation, row-count equality table, manifest check, health outputs, Cloudflare change confirmation (owner statement + `dig` — note the proxied IPs do not change; verify by origin headers/behaviour), public probe outputs from two vantages.
- **Success criteria:** all probes pass; row counts and manifests equal; no errors in target journals for 15 minutes; a real (owner-chosen, low-risk) mission runs end to end.
- **Rollback (tested in Phase 8):** owner reverts the four Cloudflare records; on the old host `systemctl start` the units in reverse order; target units stopped. Any writes on the target after step 4 are lost or reverse-synced by owner decision. Old host's LE certs untouched, so TLS resumes immediately.
- **Stop conditions:** any equality check fails at step 3 → do **not** proceed to step 6; restart old host units (rollback) and investigate. Any public probe fails at step 7 for > 5 minutes → rollback.
- **Owner approval:** required for the phase and present throughout.

## Phase 10 — Stabilization & Monitoring

- **Objective:** confidence that the target is production for the long term; the old host is retained but idle.
- **Prerequisites:** Phase 9 success.
- **Allowed:** watch target journals, `/api/health`, backup timer's first run (03:30 UTC) and its verify result, market-scan run (06:00) with the new Places key; implement the T9 backup-visibility mechanism (`/api/health` component over `/var/lib/qevik/backup/status.json`; needs its own owner approval as a change to the target) — T2 off-host copy is DONE 2026-09-03 (`OFFSITE_BACKUP.md`, `infra/qevik_offsite.sh`, `qevik-offsite.timer` 04:15 UTC, restic → Storage Box); rotate old-host-exposed credentials that were **not** already replaced (K1/K2 on the old host may be changed now since it no longer serves — owner action); update docs (`00_PROJECT_STATE.md` host section, ADR note, `cloudflare.py` comment) under review.
- **Forbidden:** deleting the old host or its data; re-enabling old-host units; DevLoop un-pause (owner's call, separate).
- **Evidence required:** 7 consecutive days: daily backup VERIFIED on target; no unit restarts (`NRestarts=0`) or each explained; market scan output fresh; public probes green daily from the second vantage (U16); error/warn counts per unit.
- **Success criteria:** 7 clean days (owner may shorten/lengthen); off-host backup copy proven by restoring one dump elsewhere (e.g. on the target into a scratch DB from the off-host copy).
- **Rollback:** still possible (old host intact) but increasingly lossy; after this phase, rollback is no longer a plan item.
- **Stop conditions:** any data-loss signal (missing records reported by the owner, 404 on a site that existed) → freeze, compare with the old host read-only.
- **Owner approval:** **OWNER GO REQUIRED** to enter Phase 11.

## Phase 11 — Decommissioning  **(OWNER GO REQUIRED; destructive)**

- **Objective:** retire `qevik-core-01` without losing anything the owner wants kept.
- **Prerequisites:** Phase 10 success; final full archive of the old host (DB dump + all `/var/lib/qevik`, `/srv`, `/opt/qevik` minus env values, `/etc/caddy`, `/var/lib/caddy`, journal export) stored off-host and restore-tested; owner's written list of what is deliberately discarded (A5, A6, S7, Y4, Y5, `.git` dirty tree — 43 modified + 260 untracked files archived as a tarball first).
- **Allowed (owner-approved, in order):** stop remaining old-host units (Caddy last); revoke/rotate every credential that lived on the old host (K1/K2 DB password on old host is moot once deleted; K5/K6/K7 old keys revoked in provider consoles; old Places key deleted); remove the old host's public key from GitHub if K13 existed; Hetzner snapshot of the old server (owner decision, retention period); delete the server (owner action in console).
- **Forbidden:** deleting before the archive is restore-tested; deleting Cloudflare records (none point at the old IP after cutover; nothing to delete).
- **Evidence required:** archive manifest + restore test result; credential revocation checklist (names only); Hetzner deletion confirmation (owner statement + server list).
- **Success criteria:** old IP no longer answers (second vantage); no repo file references `2.28.62.83` as a live target (grep = 0 or only historical docs); `known_hosts` cleaned.
- **Rollback:** none after deletion — hence the snapshot decision above.
- **Stop conditions:** any doubt about the archive → do not delete.
- **Owner approval:** required for each destructive step.

---

## Validation checklist used by Phases 7 and 9

| # | Probe | Expected | Vantage |
|---|---|---|---|
| V1 | `GET /health` on 127.0.0.1:8080 and :8081 | 200 `{"status":"ok"}` | target loopback |
| V2 | `GET /api/health` on :8081 (authenticated) | all components ok: missions durable, vault sealed, research configured, claiming atomic | target loopback |
| V3 | `SELECT name, version, last_heartbeat FROM atlas_workers` | 5 rows for target hostname, heartbeat < 90 s, expected version | target |
| V4 | `curl --resolve qevik.ai:443:<ip> https://qevik.ai/` | 200, expected `/srv/qevik-public` content, `X-Content-Type-Options` present | second vantage (U16) |
| V5 | `curl --resolve app.qevik.ai:443:<ip> https://app.qevik.ai/api/missions` | 401 (auth required) | second vantage (U16) |
| V6 | `curl --resolve sites.qevik.ai:443:<ip> https://sites.qevik.ai/<slug>/` | 200 + `X-Qevik-Host: sites`; bytes equal to old host | second vantage (U16) |
| V7 | Login + list missions in console | works; counts equal to old host at T0/T1 | owner browser (via `--resolve` or hosts file pre-cutover; public post-cutover) |
| V8 | Row-count table, 75 public tables | equal (Phase 9) / explained (Phase 6) | both hosts |
| V9 | Manifest `sha256sum -c` for each MIGRATE tree | 0 failures | target |
| V10 | Self-check mission | completes with report | target |
| V11 | Reboot target | all units active within 2 min; V1–V3 pass | target |
| V12 | Post-cutover public probes (no `--resolve`) | as V4–V6 with `cf-ray` header | second vantage (U16) + Mac |
| V13 | Backup timer first run | dump VERIFIED, retained | target journal |
| V14 | Market scan first run | `latest.json` updated, no 403 from Places | target journal |

## What this plan deliberately does not do

- Does not re-architect (no DB split, no managed DB, no containers).
- Does not add mail/SMTP (none exists to migrate — O11).
- Does not provision the DevLoop executor host (DQ-011) or un-pause DevLoop.
- Does not decide anything listed under owner decisions.
