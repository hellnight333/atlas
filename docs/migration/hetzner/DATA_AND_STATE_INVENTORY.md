# DATA_AND_STATE_INVENTORY

Phase 0 deliverable 2. Every persistent data source on `qevik-core-01`, with
the classification the migration plan will act on. Sizes are from `du`/`ls`/
`pg_database_size` at 2026-09-02 23:44–2026-09-03 00:15 UTC (PROVED unless
tagged). Classification rules:

- **MIGRATE** — copy with integrity proof (checksum / row count / restore test) and a final delta sync.
- **REGENERATE** — rebuild on the target from source (git, apt, pip, ACME); do not copy.
- **DO_NOT_MIGRATE** — leave behind; retained on the old host until decommission per plan.
- **UNKNOWN** — role or dependency not established with evidence; **must be resolved before Phase 5**. Never classified by guessing.

"Write activity" is the most recent evidence of writes. "Backup" is the
current state on the old host, not a recommendation.

## 1. Database

| # | Source | Location | Format | Size | Owner / writer | Write activity | Criticality | Backup today | Classification |
|---|---|---|---|---|---|---|---|---|---|
| D1 | `qevik` database | PostgreSQL 18.6 cluster `18-main`, `/var/lib/postgresql/18/main` | PG 18 on-disk; 75 public tables listed (74 created by repo code + `atlas_quarantined_fixtures`, origin: 2026-08-19 quarantine per `db_safety.py` docstring — INFERRED), `plpgsql` only | 418 MB (`pg_database_size`); 589 MB cluster dir | role `qevik`; written by qevik-api, qevik-control, 5 workers (13 live backends) | **continuous** — `atlas_worker_heartbeats` and `atlas_workers` written every worker interval (10 s); mission tables written by missions (newest scratch 2026-09-02 05:00) | **CRITICAL** — system of record for missions, approvals, credentials records, sites, businesses, users (`qevik_users` 2 rows, `qevik_sessions`) | daily `pg_dump -Fc`, restore-verified, 10 retained, **same disk, no off-host copy** | **MIGRATE** (logical: `pg_dump`/`pg_restore` or `pg_basebackup`; same major version 18 available on Ubuntu 26.04) |
| D2 | `qevik_test` database | same cluster | PG | 65 MB | 0 backends now; 249 k historical commits | none current | LOW — purpose INFERRED: local test/acceptance runs. **No production unit references it** (PROVED: not in any unit/env NAME) | not backed up (`qevik_backup.sh` dumps only `qevik`) | **UNKNOWN** → owner to confirm it is disposable; default recommendation REGENERATE (empty DB created by test tooling) |
| D3 | `postgres` maintenance DB | same cluster | PG | 7.7 MB | postgres | — | none | — | REGENERATE (created by `initdb`) |
| D4 | PG roles `postgres`, `qevik` (+ password of `qevik`) | cluster globals | — | — | — | — | CRITICAL (credentials) | in `pg_dumpall --globals-only`? **not taken today** | REGENERATE on target with a **new password** (see `SECRET_AND_DEPENDENCY_INVENTORY.md` — the current password is exposed in stale process argv) |
| D5 | PG configuration (`postgresql.conf`, `pg_hba.conf`) | `/etc/postgresql/18/main/` | text | small | root | static | MEDIUM | none | REGENERATE (defaults + local-only `pg_hba`; capture as reference in Phase 4) |
| D6 | Heartbeat telemetry `atlas_worker_heartbeats` | inside D1 | table | 72 MB / ~210 k rows, growing ~hourly | workers | continuous | LOW (telemetry) | inside D1 dumps | **MIGRATE with D1** (or truncate on target after owner decision — flagged as DQ, not assumed) |

## 2. Application state under `/var/lib/qevik` (258 MB, owner `qevik`)

| # | Source | Location | Format | Size | Writer | Write activity | Criticality | Backup today | Classification |
|---|---|---|---|---|---|---|---|---|---|
| S1 | Credential vault | `control/vault.json` (0600, **2 bytes**) | sealed JSON (`credentials/location.py`) | 2 B | qevik-control | mtime 2026-08-26 | HIGH by role, but **effectively empty** (OBSERVED size) — whether real customer credentials were ever sealed here: UNKNOWN | none | **MIGRATE** (tiny; copy byte-exact with sha256; requires the same `QEVIK_VAULT_MASTER_KEY` on target or it is unreadable — owner decision) |
| S2 | Credential records | `control/credentials.jsonl` (**0644**) | JSONL: fingerprint, hint, verification (per `location.py` docstring — no secret values by design, INFERRED not verified by reading) | 15.7 KB | qevik-control | mtime 2026-08-26 | MEDIUM | none | **MIGRATE** with sha256; tighten to 0600 on target |
| S3 | Mission timeline (legacy file ledger) | `control/missions.jsonl` | JSONL | 344 KB | workers/control **until 2026-08-27**; ledger is now Postgres (journal: "watching the postgres ledger"; `QEVIK_LEDGER` is set in `atlas.env`; repo `mission/timeline.py:50-90` — postgres backend appends to `atlas_business_events`) | **none since 2026-08-27** | MEDIUM (history) | none | **MIGRATE** as archive (read-only copy, sha256). PROVED inert while `QEVIK_LEDGER=postgres` is set on the target; the worker units still pass `--timeline …/missions.jsonl`, so the path must exist |
| S4 | Mission reports (file store) | `control/reports/docs/` (11 files) | files | 6.2 MB | workers `--reports` | mtime 2026-08-26 | MEDIUM | none | **MIGRATE** (rsync + checksum manifest). `QEVIK_REPORTS_STORE` is set in `atlas.env` (name PROVED, value not read); repo `mission/reports.py:24-29` selects `file`/`postgres`, postgres path uses `atlas_mission_reports` (17 MB / 27 rows on host) — store = postgres is INFERRED; verify value in Phase 5 |
| S5 | Mission evidence | `evidence/` — 354 mission UUID dirs | files | 165 MB | control/workers | last 2026-08-21 | MEDIUM (audit trail; referenced from DB rows — INFERRED) | none | **MIGRATE** (rsync + manifest); cold data |
| S6 | Mission scratch | `scratch/mission-*/` (42 dirs) | per-mission clones/work | 45 MB | workers `--scratch` | active (2026-09-02 05:00) | LOW (regenerable per `project_qevik_scratch_isolation`: never discarded on success, but not needed to run) | none | **MIGRATE** for audit continuity **or** DO_NOT_MIGRATE — owner decision; default MIGRATE (small) |
| S7 | Mission worktrees | `worktrees/mission/` | git worktrees | 14 MB | workers | active (2026-09-02 05:01) | LOW | none | **DO_NOT_MIGRATE** (tied to the old checkout's `.git`; regenerated per mission) — INFERRED, verify in Phase 5 |
| S8 | Jobs | `jobs/` (68 dirs) | files | 3.9 MB | qevik-api (INFERRED, `QEVIK_JOB_ARTIFACTS`) | last 2026-08-20 | LOW–MEDIUM | none | **MIGRATE** (small; keep continuity) |
| S9 | Prospects / audits / briefs / outreach | `prospects/` 2 MB, `audits/` 208 KB, `briefs/` 24 KB, `outreach/` 44 KB | files | ~2.3 MB | hand scripts + api (INFERRED) | Aug 18–20 | MEDIUM (sales pipeline artefacts) | none | **MIGRATE** |
| S10 | Workspaces | `workspaces/` | files | 348 KB | api | Aug 18 | LOW | none | **MIGRATE** |
| S11 | Ad-hoc SQL dumps | `backups/pre-multiindustry-20260819.sql` 22 MB, `pre-quarantine-20260819.sql` 0.6 MB | plain SQL | 22 MB | operator | 2026-08-19 | LOW (historical) | — | **MIGRATE to archive** (or DO_NOT_MIGRATE — owner) |

## 3. Served content

| # | Source | Location | Format | Size | Writer | Write activity | Criticality | Backup today | Classification |
|---|---|---|---|---|---|---|---|---|---|
| W1 | Published customer/demo/sample sites | `/srv/sites/` — 59 dirs, each `versions/` + `current` symlink | static files | 18 MB | publish worker (`QEVIK_SITES_ROOT`), qevik-control (`ReadWritePaths`) | last 2026-08-30 20:42 | **HIGH** — publicly served, referenced in DB (`atlas_sites`, `atlas_site_deployments`) and in outreach | none | **MIGRATE** with `rsync -aH` (preserve symlinks) + manifest; final delta at cutover |
| W2 | Public marketing site | `/srv/qevik-public/` | static | 2.1 MB | operator (uid 501 — rsynced from Mac) | 2026-08-21 | HIGH (public) | source is in repo: `infra/deploy_public.sh:201` builds with `python3 apps/public/build.py --out $DIST` and swaps `.incoming` (PROVED) | **REGENERATE from repo** preferred; MIGRATE copy as fallback — verify build reproducibility in Phase 4 |
| W3 | Control console SPA | `/srv/qevik-control/` (+`.previous`) | static build | 148 KB | ADR-0010 deploy (`rollback-console`) | 2026-09-02 | HIGH | part of deploy payload | **REGENERATE** (deploy payload installs it) |

## 4. Application tree and runtime

| # | Source | Location | Size | Classification | Notes |
|---|---|---|---|---|---|
| A1 | Atlas application tree | `/opt/qevik/atlas` (git checkout `ce4ffaa` + rsynced payload `346076b`, 306 dirty) | 4.8 GB incl. `.venv` 371 MB, `.mypy_cache`, `.git` | **REGENERATE** via ADR-0010 deploy of the chosen SHA; **never rsync the dirty tree** | the on-host `.git` is not authoritative; GitHub/Mac is |
| A2 | Python venv | `/opt/qevik/atlas/.venv` | 371 MB | REGENERATE (`pip install -e .[dev]` per `infra/bootstrap_qevik_server.sh`; **no lock file in repo** — `pyproject.toml` ranges only, so the target may resolve newer versions: record `pip freeze` from the old host in Phase 4 and compare) | Python 3.14.4 |
| A3 | Playwright browsers | `/opt/qevik/ms-playwright` (+ `/root/.cache/ms-playwright` duplicate) | 656 MB ×2 | REGENERATE (`playwright install chromium`) | pin same browser build 1234. `playwright` is **not** in `pyproject.toml` (PROVED repo) — installed out-of-band; the install command and pip version used are UNKNOWN → record in Phase 4 |
| A4 | Deploy markers | `/opt/qevik/atlas/DEPLOYED_SHA`, `DEPLOYED_MANIFEST` | 60 KB | REGENERATE (written by deploy) | |
| A5 | Rollback snapshots | `/opt/qevik/rollback*` | 74 MB | DO_NOT_MIGRATE (old-host rollback only) | |
| A6 | Hand-copied helper scripts | `/opt/qevik/*.py`, `*.sh`, `index.html`, `__pycache__`, `verification-scratch/` | 19 MB | **UNKNOWN** → owner: are `prospect_pipeline.py`, `audit_prospects.py`, `enable_domain.sh`, `workflow_job.sh`, `verify_*.py` still used by hand? Default DO_NOT_MIGRATE (archive tarball kept) | not in any unit |
| A7 | Market scan output | `/opt/qevik/market/latest.json` | 1.8 MB | REGENERATE (next 06:00 run) or MIGRATE (trivial) | |
| A8 | `.pgpass` | `/opt/qevik/.pgpass` (root 0600) | 40 B | **DO_NOT_MIGRATE** (contains old password; recreate on target with new password if hand tooling needs it) | |
| A9 | Atlas asset bytes | `$TMPDIR/atlas-assets` under `PrivateTmp=true` of `qevik-api` (repo `composition_root.py:116`, `storage.py:32` — `LocalFileStorageBackend()` with no root) | not measured (private tmp) | **DO_NOT_MIGRATE — cannot be**: bytes live in a per-boot private tmp and do not survive a restart; `docs/DEPLOYMENT.md:105-106` confirms backups carry asset metadata only | If any `atlas_assets` rows are expected to resolve to bytes on the target, that is a pre-existing data loss, not a migration loss — record in risk register |
| A10 | Kernel telemetry / data dir | `config.data_dir` default `./.atlas` relative to WorkingDirectory `/opt/qevik/atlas` (repo `config.py:67`, `composition_root.py:222`) | inside A1 tree | DO_NOT_MIGRATE (local telemetry JSONL, consent-gated) | UNKNOWN whether `/opt/qevik/atlas/.atlas` exists on host — not listed in `ls` capture |

## 5. Backups

| # | Source | Location | Size | Classification | Notes |
|---|---|---|---|---|---|
| B1 | Verified daily dumps | `/opt/qevik/backups/qevik-*.dump` ×**11** (17 Aug → 3 Sep) | 106 MB | **DONE 2026-09-03**: all 11 copied read-only to `qevik-prod-01` and into the Storage Box restic repository (snapshot `ed2b42b1`; `OFFSITE_BACKUP.md` §10.1). **Retention rule (B-5 / R-31):** they move to `/opt/qevik/backups/archive/old-host/` (`0400`, outside the `qevik-*.dump` prune glob, inside the off-host set) before any backup unit runs on the target; `qevik_backup.sh` retention owns only dumps the target itself produces; the archive is deleted only at Phase 11 by owner decision | custom format, `pg_restore --list` verified on the target |
| B2 | Backup script + timer | `infra/qevik_backup.sh`, unit + timer | — | REGENERATE (deploy payload) | KEEP=14, 03:30 Z |

## 6. Proxy and TLS

| # | Source | Location | Classification | Notes |
|---|---|---|---|---|
| P1 | Live Caddyfile | `/etc/caddy/Caddyfile` (7.8 KB, 225 lines, sha256 `38df2a4a…`) | **CORRECTED 2026-09-03 (B-2 / R-28): DO_NOT_MIGRATE as source of truth.** The repository's `infra/qevik-production.Caddyfile` (290 lines, sha256 `8d879127…`) is **newer** — the live file still carries the SPA fallback (`try_files {path} /index.html`) that the repo already replaced with real 404 handling. Target artifact = the **repository** file minus the `:8443` block (D-D). The live file is kept only as a reconciliation input (`evidence/phase-4/caddyfile-reconciliation.md`) | five historical copies beside it: DO_NOT_MIGRATE |
| P2 | Let's Encrypt certificates + ACME account | `/var/lib/caddy/.local/share/caddy/` (236 KB) | **REGENERATE** on target (HTTP-01 through Cloudflare needs the origin to receive :80 for the new host — see cutover sequencing) or MIGRATE the directory to avoid a cert gap at cutover — **owner decision** (both are valid; copying avoids rate-limit and first-request latency) | |
| P3 | Internal CA (8443, 127.0.0.1) | same dir | REGENERATE | |

## 7. System-level

| # | Source | Classification | Notes |
|---|---|---|---|
| Y1 | systemd units + drop-in + slice | REGENERATE. All seven `qevik-*.service` + both timers are in `infra/` and installed by `deploy_control.sh:804-810` (PROVED). `infra/systemd/qevik-jobs.slice` and `infra/systemd/qevik-api.service.d/resources.conf` are in the repo but are installed only by `recover_qevik_server.sh:42-43,72-74`, **not** by `deploy_control.sh` (PROVED repo) → Phase 4 must install them explicitly | |
| Y2 | Env files `/opt/qevik/*.env` | **DO NOT COPY BY AUTOMATION** — recreated by the owner on the target from the secret inventory (see `SECRET_AND_DEPENDENCY_INVENTORY.md`) | |
| Y3 | `ufw` rules, sshd config, unattended-upgrades | REGENERATE (Phase 3 hardening; do not replicate `passwordauthentication yes`) | |
| Y4 | journald logs (648 MB) | DO_NOT_MIGRATE (export a filtered slice if the owner wants history) | |
| Y5 | pip/playwright caches (`/root/.cache`, `/home/qevik/.cache`, 1.4 GB) | DO_NOT_MIGRATE | |
| Y6 | Users `qevik` (uid 1000), `caddy`, `postgres` | REGENERATE (same names; uid parity not required unless rsynced files rely on it — `/srv/sites` is `qevik:qevik`, so create `qevik` before rsync) | |

## 8. Totals and windows

- Must-copy data (D1 + S1–S11 + W1 + B1): ≈ 418 MB DB (19.6 MB compressed dump) + 258 MB state + 18 MB sites + 80 MB dumps ≈ **0.8 GB**. Initial sync is minutes; final delta is seconds — the cutover window is dominated by service stop/start and validation, not by transfer.
- Continuous writers that define the delta: D1 (all services), W1 (publish worker), S6/S7 (workers). All stop when the seven units stop.
- Everything else is REGENERATE or DO_NOT_MIGRATE.
- **Not on the host but load-bearing for operations:** the DevLoop queue `~/atlas/.qevik/devloop/state.db` on the operator Mac (repo `infra/devloop/driver.py:1226`; ADR-0011:25). Out of scope for the production migration; it moves only under DQ-011 (DevLoop host), which this plan does not execute.

## 9. UNKNOWN items to resolve before Phase 5

1. D2 `qevik_test` — disposable? (owner)
2. S1 — was the vault ever used for real credentials (2-byte file suggests not)? Same master key on target, or start empty? (owner)
3. S4 — `QEVIK_REPORTS_STORE` value (file vs postgres) — read on the target-prep host from the env file NAME list is insufficient; resolve in Phase 5 by reading the value with the owner present (S3 is resolved: PROVED postgres).
4. S6/S7/S11/A6 — keep or archive? (owner)
5. W2 — build reproducibility from repo (Phase 4 test: `apps/public/build.py` output vs `/srv/qevik-public` diff).
8. A2/A3 — no lock file, playwright out-of-band: capture `pip freeze` + playwright version from the old host before building the target (Phase 4).
6. P2 — copy certificates or re-issue (owner).
7. D6 — keep full heartbeat history or truncate on target (owner).
