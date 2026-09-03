# PHASE 4 — PRE-EXECUTION REVIEW

> **Status 2026-09-03:** accepted by the owner **as a reconciliation finding**; Phase 4
> is **not** approved to execute. The four blockers (§15 N-1…N-4) and the two retention
> records are now tracked as B-1…B-6 in `MIGRATION_ENABLEMENT_SPEC.md`, which the
> migration completes — under the normal reviewed-code workflow — **before Phase 3
> creates any production credential**.

**Planning and reconciliation pass only.** Nothing in this document has been
executed. No host, service, database, secret, DNS or Cloudflare setting was
modified while writing it; every host statement below comes from a read-only
command run on 2026-09-03 (target `qevik-prod-01`, and the old host under the
AR-4 read-only carve-out), or from the repository at `3c8310d`.

Evidence tags as in the rest of the set: **PROVED** (observed this session or in
a cited evidence file) · **OBSERVED** · **OWNER-REPORTED** · **INFERRED** ·
**UNKNOWN**. DQ-009 applies throughout: where a choice is genuinely the owner's,
this document states the options and the default, and decides nothing.

Reconciled against: `MASTER_MIGRATION_PLAN.md`, `OWNER_DECISION_AND_FINAL_ARCHITECTURE.md`,
`CURRENT_INFRASTRUCTURE_INVENTORY.md`, `DATA_AND_STATE_INVENTORY.md`,
`SECRET_AND_DEPENDENCY_INVENTORY.md`, `CURRENT_PRODUCTION_SERVICE_GRAPH.md`,
`MIGRATION_RISK_REGISTER.md`, `HETZNER_TARGET_ARCHITECTURE_DRAFT.md`,
`OFFSITE_BACKUP.md`, `docs/qevik-docs/00_PROJECT_STATE.md`,
`PHASE_1_COMPLETION_REPORT.md`, `PHASE_2_OWNER_CONSOLE_ACTIONS.md`,
`evidence/phase-1/`, `evidence/phase-2/`, `evidence/backup/`, and the actual
contents of `infra/`.

---

## 1. Exact Phase 4 objective and boundary

**Objective** (`MASTER_MIGRATION_PLAN.md` Phase 4, unchanged): `qevik-prod-01`
runs the same unit set, Caddy configuration, PostgreSQL major version, virtualenv
and Playwright build as `qevik-core-01`, against an **empty** database, and
passes the ADR-0010 deploy contract's rehearsal and then a real deploy.

**In scope**

| # | Deliverable |
|---|---|
| 4.1 | System packages: PostgreSQL 18 server, Caddy, `python3-venv`, `python3-pip`, `ffmpeg`, Playwright's Chromium apt dependencies |
| 4.2 | PostgreSQL cluster `18-main`, role + database `qevik` (password typed by the owner), loopback-only, `scram-sha-256` |
| 4.3 | Filesystem layout and ownership: `/opt/qevik/**`, `/var/lib/qevik/**`, `/srv/{sites,qevik-public,qevik-control}` |
| 4.4 | Virtualenv at `/opt/qevik/atlas/.venv` matching the old host's 52 installed distributions; Playwright 1.62.0 + Chromium build 1234 under `/opt/qevik/ms-playwright` |
| 4.5 | `qevik-jobs.slice` + `qevik-api.service.d/resources.conf` (neither is installed by any deploy path) |
| 4.6 | Caddy configuration and TLS material (D-E decides copy vs re-issue) |
| 4.7 | The R-12 repo change (owner-reviewed, owner-pushed) so the deploy tooling can address the new host **with the `qevik_prod` key** |
| 4.8 | `deploy_control.sh --rehearse` → real deploy → `deploy_console.sh` / `deploy_public.sh` equivalents |
| 4.9 | Unit enablement (nothing in the deploy path enables anything) and a **reboot test** on an empty host (R-14) |

**Out of scope — explicitly forbidden in Phase 4**

- Any production data: no `pg_dump`/`pg_restore` of the live DB, no `rsync` of `/var/lib/qevik` or `/srv/sites` from the old host (Phases 5/6).
- Any write on `qevik-core-01` (AR-4). Reads only, as used for this review.
- Any Cloudflare or DNS change (Phase 9, owner's browser).
- Any secret value handled by the agent (Phase 3 is the owner's typing; the agent verifies names and modes only).
- `enable_domain.sh` (needs the Caddy admin API; production runs `admin off`) and `bootstrap_qevik_server.sh` unmodified (see §6.4).
- Starting workers with real-world effects, or pointing anything at the old host's database.
- DevLoop: still paused (AR-5); no task is enqueued for any of this.

**Boundary statement.** Phase 4 leaves a host that is *functionally complete and
empty*. It serves nothing publicly (Cloudflare still points at `2.28.62.83`), it
holds no customer data, and every step is undone by a console rebuild.

---

## 2. Exact current state of `qevik-prod-01` (PROVED 2026-09-03 16:41 UTC)

| Dimension | State |
|---|---|
| Identity | Hetzner server 164307556, `91.107.244.253` / `2a01:4f8:1c1b:1dbe::1`, nbg1-dc3, hostname `qevik-prod-01` |
| OS / kernel | Ubuntu 26.04.1 LTS, kernel 7.0.0-30-generic; `apt list --upgradable` = **0**; no `/var/run/reboot-required` |
| Hardware | 8 vCPU · 15 GiB RAM · 305 GB NVMe, **1.8 GB used (1 %)** |
| **Swap** | **none** — D-B requires a 2 GB swap file with `vm.swappiness=10`; current `vm.swappiness=60`. **Not yet done.** |
| Boots | 2 (rebuild boot + the Phase 2 upgrade reboot); uptime 6 h |
| Time | `Etc/UTC`, `NTPSynchronized=yes` |
| Users | **no `qevik`, no `caddy`, no `postgres` user exists.** Only `root` has a shell. |
| SSH | `authorized_keys` = 1 line, `qevik_prod`; `permitrootlogin prohibit-password`; **`passwordauthentication yes`**; `maxauthtries 6`; no `fail2ban` |
| Host firewall | **`ufw` inactive.** Ingress is the Hetzner Cloud Firewall only: 22/80/443 + ICMP, verified from the second vantage (`evidence/phase-2/firewall-and-console.txt`, U16) |
| Listening | `:22` sshd (v4+v6) and `systemd-resolved` on 127.0.0.53/54 — nothing else |
| Packages present | `git 2.53.0`, `curl 8.18.0`, `rsync 3.4.1`, `ufw 0.36.2`, `restic 0.18.1`, `unattended-upgrades 2.12` (enabled), **`postgresql-client-18 18.6`** (installed 2026-09-03 by the dump-verification task, client only) |
| Packages absent | **`postgresql-18` server, `postgresql-common`, `caddy`, `python3-venv`, `python3-pip`, `ffmpeg`, `fail2ban`, `build-essential`, `libpq-dev`, `nodejs`/`npm`** |
| Python | `python3` = **3.14.4** (same as the old host); no `pip3`, no `venv` module package |
| systemd (`qevik-*`) | `qevik-offsite.service` (static), `qevik-offsite.timer` (**enabled**, next 04:15 UTC), `qevik-backup-failed@.service` (static). **No api, control, workers, backup or market-scan units.** |
| `/opt/qevik` | `root:root 0755`; `backup.env` (`root:root 0600`, one key `RESTIC_PASSWORD`); `backups/` (`root:root 0700`) holding the **11 old-host dumps**, `root:root 0600`, original mtimes |
| `/var/lib/qevik` | `root:root 0755`, contains only `backup/` (offsite `status.json`, `env-names.txt`, `units.txt`) |
| `/srv` | **empty** |
| Off-host backup | restic repo `a8dfcaf29daf256b` on Storage Box `u662608-sub1:/qevik-prod-backup/restic`; 2 snapshots (`b5212410` state-only, `ed2b42b1` = the 11 dumps); full `check --read-data` clean; 78.2 MB raw |
| Interim files | `/usr/local/sbin/{qevik_offsite.sh,qevik-backup-set-password}`; `/root/qevik-infra/` (copies of `infra/` at `a4ec57f`, to be deleted after Phase 4 re-runs the installer from `/opt/qevik/atlas/infra/`) |
| journald | no `SystemMaxUse` cap; 16.7 MB used |

**Phase 3 has not been performed.** No `qevik` user, no `/opt/qevik/{atlas,control,worker,brave,places}.env`, sshd still accepts passwords, `ufw` inactive. This is the single largest gate in front of Phase 4 (§11, §12).

---

## 3. Production components that must eventually exist on the target

From the old host, PROVED this session unless stated.

| Component | Old host fact | Target requirement |
|---|---|---|
| Caddy | **2.11.4**, from `dl.cloudsmith.io/public/caddy/stable/deb/debian` (`caddy-stable.list`) — **not** an Ubuntu package | ≥ 2.7 (see §6.2/§9); listens :80 :443 (and :8443, being removed per D-D) |
| `qevik-api` | `uvicorn atlas_kernel.api:app` on 127.0.0.1:**8080**, `User=qevik`, `Requires=postgresql.service` | identical |
| `qevik-control` | `uvicorn --factory atlas_kernel.qevik.app:from_environment` on 127.0.0.1:**8081**, `--workers 1` | identical |
| Workers ×5 | `infra/mission_worker.py`, `--tenant tenant-qevik`, `--interval 10`, names `worker-1`(self-check) · `worker-research` · `worker-delivery` · `worker-publish` · `worker-healthcheck`; publish also sets `QEVIK_SITES_ROOT=/srv/sites` | identical |
| Timers | `qevik-backup.timer` 03:30 (tz-naive) · `qevik-market-scan.timer` 06:00 (tz-naive) | plus `qevik-offsite.timer` 04:15 **UTC** (already installed) |
| Resource limits | `qevik-jobs.slice` (MemoryMax 3500M, TasksMax 384, CPUQuota 300 %) + `qevik-api.service.d/resources.conf` (MemoryMax 1536M, `PLAYWRIGHT_BROWSERS_PATH=/opt/qevik/ms-playwright`, `EnvironmentFile=-` for `brave.env`/`places.env`/`cloudflare.env`, `StartLimit*` in `[Unit]`) | identical — **and installed by no deploy path** (only `recover_qevik_server.sh` installs them) |
| PostgreSQL | 18.6 (`18.6-0ubuntu0.26.04.1`), cluster `18-main`, loopback, `scram-sha-256` | same package version is available on the target (§4) |
| Served trees | `/srv/qevik-public` (public site), `/srv/qevik-control` (console SPA), `/srv/sites` (published customer sites) | same paths |
| State | `/var/lib/qevik/{control,scratch,worktrees,jobs,evidence,prospects,outreach,audits,briefs,workspaces}` | same paths, `qevik:qevik` |
| App | `/opt/qevik/atlas` + `.venv`, `DEPLOYED_SHA` = `346076b…` state=installed, manifest 475 lines | ADR-0010 payload deploy only |

Unit-file drift check (sha256, repo vs installed on the old host): **all installed
`qevik-*` units, the slice and the drop-in match the repo byte-for-byte**, with one
expected exception — `qevik-backup.service` differs because commit `a4ec57f` added
`OnFailure=qevik-backup-failed@%p.service` to the repo copy and that has never been
deployed to the old host. PROVED.

---

## 4. PostgreSQL strategy and compatibility

**Source (PROVED):** server 18.6 `(Ubuntu 18.6-0ubuntu0.26.04.1)`;
`data_directory=/var/lib/postgresql/18/main`; `listen_addresses=localhost`;
`max_connections=100`; **`shared_buffers=16384` (= 128 MB, the packaged default)**;
`password_encryption=scram-sha-256`; `pg_hba` = `local … peer` for `postgres` and
all, `host … 127.0.0.1/32 scram-sha-256`, same for `::1/128`, plus the equivalent
replication lines. Databases: `qevik` 431 MB (**75 public tables**), `qevik_test`
65 MB, `postgres`, templates.

**Target:** `apt-cache policy postgresql-18` on `qevik-prod-01` offers
**`18.6-0ubuntu0.26.04.1` — the identical package version** (PROVED). Installing it
yields byte-identical major *and* minor versions, so `pg_dump -Fc` → `pg_restore`
carries no cross-version risk at all. This is already partly proven: the 11
production dumps restored from the Storage Box were parsed on the target with
`pg_restore --list` (client 18.6), exit 0 on every file, 250→304 TOC entries.

**Plan for Phase 4 (empty database):**

1. `apt-get install -y postgresql-18` (pulls `postgresql-common`, creates cluster `18-main` and the `postgres` OS role).
2. Verify the shipped `pg_hba.conf` already equals the source's shape; do **not** hand-edit unless it differs.
3. `createuser`-equivalent as `postgres`: `CREATE ROLE qevik LOGIN CREATEDB;` then the **owner** sets the password interactively (`\password qevik`) — never on a command line (SR-1), never through the agent.
4. `CREATE DATABASE qevik OWNER qevik;` — **`qevik_test` is not created** (D-G default: not migrated).
5. Schema arrives from `init_db()` during the deploy (`deploy_control.sh:766`), not from a migration tool. In Phase 6 this database is **dropped and recreated** from the production dump, so the Phase 4 schema is scaffolding, not data.
6. `CREATEDB` on the role is required by `qevik_backup.sh`, which verifies each dump by restoring into a throwaway `qevik_verify_$$` database.

**Two deviations to confirm (owner):**

- **`shared_buffers`.** `OWNER_DECISION_AND_FINAL_ARCHITECTURE.md` §1/§4 specifies 512 MB on the target; the old host actually runs the 128 MB default. This is an improvement, not like-for-like. Default under DQ-009: apply 512 MB on a 15 GiB host, recorded as a deliberate change. **Not decided here.**
- **`max_connections`.** Old host 100, 13 backends observed. Keep 100.

---

## 5. Users, directories, ownership, permissions, filesystem layout

Old-host ownership (PROVED this session) and the target requirement:

| Path | Old host | Target (Phase 4) | Note |
|---|---|---|---|
| user `qevik` | uid 1000, home `/home/qevik`, shell `/bin/bash` | create **before** any deploy | §4 architecture says *no login, no `authorized_keys`*; `/bin/bash` vs `/usr/sbin/nologin` is an owner call (see §15 N-6) |
| user `postgres`, `caddy` | created by their packages | created by `apt` | uid parity not required |
| `/opt/qevik` | `qevik:qevik 0750` | same | currently `root:root 0755` on the target |
| `/opt/qevik/atlas` (+`.venv`) | `qevik:qevik` | same; created by the deploy + venv step | never rsync the old tree (A1) |
| `/opt/qevik/backups` | `qevik:qevik 0755` | **must become `qevik:qevik`** | currently `root:root 0700` holding the 11 root-owned dumps → `qevik-backup.service` (User=qevik) cannot write there today. See §11 D-4. |
| `/opt/qevik/market` | `qevik:qevik 0750` | same | market-scan output |
| `/opt/qevik/*.env` | `atlas.env`,`brave.env` `root:root 0600`; `control.env`,`worker.env`,`places.env` `qevik:qevik 0600` | identical (owner creates in Phase 3) | `backup.env` (`root:root 0600`) already present |
| `/var/lib/qevik` | `qevik:qevik 0755` | same | SR-2 wants 0700 dirs / 0600 files under it |
| `/var/lib/qevik/control` | `qevik:qevik 0755` | same; `vault.json` + `credentials.jsonl` **0600** on the target (F-2) | |
| `/var/lib/qevik/backup` | — | `root:root 0755` (offsite status) | already present |
| `/srv/sites` | `qevik:qevik 0755` | same | publish worker writes here |
| `/srv/qevik-control` | `qevik:qevik 0755` | same | deploy payload writes here |
| `/srv/qevik-public` | **uid 501 (the Mac's uid) : staff 0755** | `root:root` or `qevik:qevik` | artefact of an `rsync -a` from the Mac; do not reproduce |
| `/opt/qevik/ms-playwright` | browsers, 656 MB | same path (the API drop-in points at it) | |
| `/opt/qevik/.pgpass` | root 0600 | **not created** (A8 DO_NOT_MIGRATE) | |

Directories that must exist before the first worker start (from the unit
`ExecStart` arguments): `/var/lib/qevik/{control,control/reports,scratch,worktrees,jobs}`,
plus `/opt/qevik/market` for the market-scan timer.

---

## 6. Python / runtime / system dependencies

### 6.1 Python

- Both hosts run **Python 3.14.4** (PROVED). `pyproject.toml:9` only says `>=3.11`; there is **no lock file, no `requirements*.txt`, no `.python-version`** in the repo.
- Old-host venv (PROVED): `pip 26.2.1`, **52 distributions**. Key versions: `fastapi 0.141.1`, `uvicorn 0.52.3`, `pydantic 2.13.4`, `SQLAlchemy 2.0.52`, `psycopg 3.3.4` (+`psycopg-binary`), `httpx 0.28.1`, `pillow 12.3.0`, `PyYAML 6.0.3`, `playwright 1.62.0`, `pytest 9.1.1`, `pytest-cov 7.1.0`, `ruff 0.16.3`, `black 26.5.1`, `mypy 2.3.1`. A full freeze is captured in the scratchpad and becomes `evidence/phase-4/old-host-freeze.txt` when Phase 4 runs (R-16 asks for `pip install -c constraints.txt`).
- **Playwright is not a declared dependency** (`pip install -e .[dev]` will not install it). Old host: `playwright 1.62.0`, browsers `chromium-1234`, `chromium_headless_shell-1234`, `ffmpeg-1011`. U4 is now **resolved** (it was UNKNOWN in Phase 0/1).

### 6.2 apt packages needed on the target

| Package | State on target | Note |
|---|---|---|
| `postgresql-18` | absent | candidate 18.6, identical to source |
| `python3-venv`, `python3-pip` | absent | required for the venv |
| `ffmpeg` | absent | media code + Playwright's bundled ffmpeg is separate; 85 media tests skip without it and the `--cov-fail-under=90` gate then fails |
| Chromium apt deps | absent | `playwright install --with-deps chromium` |
| `git`, `curl`, `rsync` | present | |
| `caddy` | absent — **and the Ubuntu 26.04 candidate is 2.6.2-14** | see below |
| `fail2ban` | absent | Phase 3 item (SR-3), not Phase 4 |
| `build-essential`, `libpq-dev` | absent on **both** hosts | not required (`psycopg[binary]`) |

**Caddy version blocker (new finding).** `MASTER_MIGRATION_PLAN.md:93` lists
`apt install … caddy` among Phase 4's allowed actions. On Ubuntu 26.04 that
installs **Caddy 2.6.2**. The old host runs **2.11.4 from the Cloudsmith `caddy/stable`
repository**, and `infra/qevik-production.Caddyfile` uses `handle_errors` with
`file_server { status 404 }`, which its own comment records as requiring **Caddy ≥ 2.7**.
Installing the distro package would either fail `caddy validate` or serve soft
404s. Phase 4 must add the same Cloudsmith apt source (or pin an equivalent ≥ 2.11
build) — that is a **new trust anchor on the host** and belongs in the step list
explicitly, not as a footnote.

### 6.3 What the deploy contract assumes already exists

`deploy_control.sh` installs **no** packages, creates **no** venv and touches
**no** Caddy config. It requires, before it runs: `$REMOTE_APP/.venv/bin/python`,
a working `/opt/qevik/atlas.env` (line 766 does `set -a && . $ENV_FILE`), the
`qevik` user (it `chown`s to it), a local `postgres` role and a `qevik` database
with `atlas_workers` (worker fingerprint check), and `rsync` + `sha256sum` on the
host.

> **Consequence for the DB password (new finding).** Line 766 *sources* the env
> file in a shell. A password containing shell metacharacters inside
> `ATLAS_DATABASE_URL` will break the schema step and fail the deploy — the same
> class of failure the restic password caused in the off-host backup work. The
> owner should pick a URL-safe, shell-safe password (or the value must be quoted
> in the file).

### 6.4 Provisioning scripts

- `bootstrap_qevik_server.sh` — **not usable unmodified** (already the plan's position, confirmed by reading): installs only `qevik-api`, opens **only :22**, generates a GitHub deploy key and `git clone`s the repo on the host (contradicting ADR-0010), regenerates the Postgres password on every run, and **overwrites `/opt/qevik/atlas.env` wholesale**, discarding `QEVIK_SITES_BASE_URL`, `QEVIK_LEDGER`, `QEVIK_REPORTS_STORE`. It also does not install `caddy` or `rsync`.
- `recover_qevik_server.sh` — the **only** script that installs `qevik-jobs.slice` and `resources.conf`; it also reaps browsers and restarts `qevik-api`. Phase 4 should install those two files directly (`install -m 0644 …`) rather than run an incident-response script on a fresh host.
- Therefore Phase 4 runs from a **written checklist** (R-15), which is §12 below.

---

## 7. Secrets and environment files — names only

No value appears here, and none reaches the agent (SR-9). All five files are
created by the **owner** in Phase 3, with `umask 077`, before Phase 4 can deploy.

| File | Owner:group / mode (old host, PROVED) | Keys (names only) | Consumed by |
|---|---|---|---|
| `/opt/qevik/atlas.env` | `root:root 0600` | `ATLAS_DATABASE_URL`, `QEVIK_DASHSCOPE_API_KEY`, `QEVIK_DASHSCOPE_BASE_URL`, `QEVIK_ADMIN_PASSWORD`, `QEVIK_SITES_BASE_URL`, `QEVIK_LEDGER`, `QEVIK_REPORTS_STORE` | api, control, 5 workers, backup, market-scan, deploy schema step |
| `/opt/qevik/control.env` | `qevik:qevik 0600` | `QEVIK_VAULT_MASTER_KEY`, `QEVIK_CLAIMS_DSN`, `QEVIK_REQUIRE_ATOMIC_CLAIMS` | control, workers |
| `/opt/qevik/worker.env` | `qevik:qevik 0600` | `QEVIK_CLAIMS_DSN`, `QEVIK_REQUIRE_ATOMIC_CLAIMS` | workers |
| `/opt/qevik/brave.env` | `root:root 0600` | `QEVIK_BRAVE_API_KEY` | api (via `resources.conf`) |
| `/opt/qevik/places.env` | `qevik:qevik 0600` | `QEVIK_GOOGLE_PLACES_API_KEY` | api, market-scan |
| `/opt/qevik/backup.env` | `root:root 0600` — **already on the target** | `RESTIC_PASSWORD` | `qevik-offsite.service` |

`cloudflare.env` is referenced with a leading `-` in `resources.conf` and does not
exist on the old host; it must **not** be created (nothing uses it).

Values still owed by the owner (unchanged from the inventory): O3 new DB password
(K1/K2), O4 vault key decision (U9), O5 DashScope + Brave, O6 new IP-restricted
Places key (SR-5 — the current key is pinned to `2.28.62.83` and **will fail** from
the new host), O7 admin password policy. `QEVIK_REPORTS_STORE`'s value (U10) is
still unread and must match the old host's semantics.

---

## 8. systemd units — installed, enabled, deferred

| Unit | Ships in repo | Installed by | Enable in Phase 4? |
|---|---|---|---|
| `qevik-api.service` | yes | `deploy_control.sh` glob `infra/qevik-*.service` | **yes**, explicitly (`WantedBy=multi-user.target`) |
| `qevik-control.service` | yes | deploy glob (also `deploy_console.sh`, which additionally `enable`s it) | yes |
| `qevik-worker{,-research,-delivery,-publish,-healthcheck}.service` | yes | deploy glob | yes (5 units) |
| `qevik-backup.service` | yes | deploy glob | no `[Install]` — timer-driven |
| `qevik-market-scan.service` | yes | deploy glob | no `[Install]` — timer-driven |
| `qevik-offsite.service` | yes | deploy glob **and** already installed on the target | no `[Install]` — timer-driven |
| `qevik-backup-failed@.service` | yes | deploy glob (matches `qevik-*.service`) | template; activated by `OnFailure=` |
| `qevik-backup.timer` | yes | **nothing installs it** | install by hand; **defer enabling** until Phase 6 (see below) |
| `qevik-market-scan.timer` | yes | **nothing installs it** | install by hand; **defer enabling** until Phase 7 (needs the new Places key; running early burns quota and proves nothing) |
| `qevik-offsite.timer` | yes | `install_offsite_backup.sh` | already enabled, next 04:15 UTC |
| `qevik-jobs.slice` | `infra/systemd/` | only `recover_qevik_server.sh` | install by hand; `systemctl start qevik-jobs.slice` |
| `qevik-api.service.d/resources.conf` | `infra/systemd/` | only `recover_qevik_server.sh` | install by hand before the first `qevik-api` start |

Three mechanical facts that shape the step order:

1. **The deploy glob is `*.service` only.** No timer has ever been installed by a deploy; the old host's timers were installed by hand and have simply survived.
2. **`deploy_control.sh` enables nothing.** It `daemon-reload`s and restarts. On a fresh host, "installed" ≠ "starts after reboot" — the reboot test (R-14) will catch this only if enablement is done explicitly.
3. **`deploy_control.sh`'s rollback runs `rm -f $UNIT_DIR/qevik-*.service`** and restores the pre-deploy snapshot. Since `qevik-offsite.service` and `qevik-backup-failed@.service` are in `$UNIT_DIR` *before* the first deploy, they are inside the snapshot and survive; but any unit installed out-of-band **between** the snapshot and a rollback would be deleted. Worth knowing before the first deploy of the working off-host backup's host.

**Backup-timer sequencing (needs a decision, §11 D-4).** `qevik_backup.sh` prunes
to `KEEP=14` newest dumps in `/opt/qevik/backups`. That directory currently holds
the **11 migrated old-host dumps**. Enabling `qevik-backup.timer` on the target
starts adding dumps of an *empty* database and, after four runs, begins deleting
the oldest genuine production dumps from local disk (they remain in the restic
repository, which is the point of §3.5 — but the local copies are the ones a
person reaches for first). Options: (a) move the 11 files to
`/opt/qevik/backups/archive/` (outside the `qevik-*.dump` glob) before enabling
anything; (b) leave the timer disabled until Phase 6; (c) accept the pruning.
Default under DQ-009: **(a) + (b)**.

---

## 9. Caddy and TLS strategy

**Facts**

- Live config on the old host: `/etc/caddy/Caddyfile`, 225 lines, sha256 `38df2a4a…`. Repo config: `infra/qevik-production.Caddyfile`, 290 lines, sha256 `8d879127…`. **They differ** (PROVED diff): the live file still uses the SPA fallback `try_files {path} /index.html` in the `qevik.ai` block and has **no** `handle_errors`; the repo file removed the fallback and added the real 404 handling. In other words the repo is **ahead** of production, and `DATA_AND_STATE_INVENTORY.md` P1 ("MIGRATE the live Caddyfile as the source of truth") would **regress a fix that is already committed**. Correct source for the target is the **repo file**, minus the `:8443` block (D-D).
- Global block: `admin off` (so `caddy reload` and `enable_domain.sh` cannot work — the deploy uses `systemctl restart caddy`), an ACME contact email, and `trusted_proxies static` with the Cloudflare v4+v6 ranges.
- TLS: the `(le)` snippet is `tls { issuer acme { disable_tlsalpn_challenge } }` — Let's Encrypt **HTTP-01 only**. There is no DNS-01 challenge, no Cloudflare API token (the repo has none, `cloudflare.env` does not exist), and no cert-path `tls` directive anywhere.
- Consequence: **the target cannot obtain certificates for the four public names until it is the origin** (HTTP-01 needs :80 reachable through Cloudflare). That is after Phase 9.

**Strategy for Phase 4 (D-E is still open — this is the shape of each option)**

| Option | What Phase 4 does | Consequences |
|---|---|---|
| **D-E = copy** (recommended in the owner doc) | root→root `rsync -a` of `/var/lib/caddy` from old to target, `chown -R caddy:caddy`; Caddy starts with the four certs already valid; renewal happens naturally after cutover | zero cert gap at cutover; no LE rate-limit exposure on rollback (R-09). **Note:** this is a read of `/var/lib/caddy` on the old host — allowed under AR-4 (read-only) — but it copies TLS **private keys** (K9), so the transfer must be host→host over SSH, never via the Mac's disk, and never through the agent's output |
| **D-E = re-issue** | install Caddy with a temporary config (`tls internal` or a throwaway hostname the owner points at the target) so `caddy validate` and startup can be proven; real certs only at/after cutover | cutover then depends on HTTP-01 succeeding at the worst possible moment; LE duplicate-certificate limits could block a rollback |

Either way Phase 4 **must** prove: the correct Caddy version is installed,
`caddy validate --config /etc/caddy/Caddyfile` passes on the target's copy of the
repo file with the `:8443` block removed, and Caddy starts and answers on
loopback. The `:8443` removal also deletes one of the hard-coded `2.28.62.83`
literals (R-12).

---

## 10. Reversible vs destructive actions

Everything in Phase 4 happens on an empty host whose ultimate rollback is a free
console rebuild (Phase 2 rollback). Within that, per step:

| Action | Class | Undo |
|---|---|---|
| `apt install` (postgres, caddy, python3-venv/pip, ffmpeg, Chromium deps) | reversible | `apt purge`; or rebuild |
| Adding the Cloudsmith Caddy apt source + key | reversible, but a **new trust anchor** | remove the `.list`/keyring |
| Create `qevik` user, directories, ownership | reversible | `userdel`, `rm -rf` (nothing else references them yet) |
| Create PG cluster, role, empty `qevik` DB | reversible | `dropdb`/`dropuser`; the DB is empty by definition in Phase 4 |
| venv + `pip install` + `playwright install` | reversible | `rm -rf /opt/qevik/atlas/.venv /opt/qevik/ms-playwright` |
| Install slice + drop-in + timers | reversible | `rm` + `daemon-reload` |
| `deploy_control.sh --rehearse` | **no host writes at all** (dry-run rsyncs + read-only probes) | n/a |
| `deploy_control.sh` real | reversible **by its own snapshot/rollback**; note the kernel rsync uses `--delete` (harmless on a first deploy) and `init_db()` writes schema into the empty DB | its `rollback_and_report`, or wipe `/opt/qevik/atlas` and redeploy |
| `deploy_console.sh` / `deploy_public.sh` | reversible (`.previous` swap kept) | swap back |
| Copying `/var/lib/caddy` (if D-E = copy) | reversible on the target; **read-only on the old host** | delete the directory on the target |
| Enabling `qevik-backup.timer` before Phase 6 | **destructive to local dump history** via `KEEP=14` pruning (§8) | none for the pruned files locally — they survive only in restic |
| **Anything touching the old host beyond reads** | destructive / forbidden | — |
| **DNS / Cloudflare / customer data** | not in Phase 4 | — |

No Phase 4 action is irreversible in the R3 sense. The two that deserve a
conscious "yes" are the Cloudsmith apt source and the backup-timer sequencing.

---

## 11. Dependencies between Phase 4 and later phases

| # | Dependency | Direction |
|---|---|---|
| D-1 | **Phase 3 must complete first.** No `qevik` user → deploy `chown` fails; no `/opt/qevik/atlas.env` → the schema step (`. $ENV_FILE`) fails and the deploy rolls back; no DB password → no role. Phase 3 also owns sshd hardening, ufw, fail2ban and the 2 GB swap. | 3 → 4 |
| D-2 | **R-12 / O10 must be pushed by the owner before the first deploy.** Not only the IP: `deploy_control.sh:68`, `deploy_public.sh:44` and `deploy_console.sh` hard-code **`~/.ssh/naml_hetzner`**, the key D-F forbids on the new host and which is not authorised there — so today all three scripts fail at their access check against `qevik-prod-01`. The change must parameterise **host *and* key** (e.g. `QEVIK_PROD_HOST`, `QEVIK_DEPLOY_KEY`), keeping the old defaults until cutover. Other literals: `cloudflare.py:41 ORIGIN_IP` (its `check_writable` refuses any other A-record), `qevik-production.Caddyfile:230`, `qevik-sites.Caddyfile:20`, `secure_8443.sh`, `devloop/{boundary,gates,inspection}.py`, `run_objective.py`, `resume_objective.py`, `rotate_admin.py`, `prospect_pipeline.py`, two e2e tests. | 4 → 9/10 |
| D-3 | **Deploy SHA (R-03).** The target's kernel must be ≥ the SHA that last wrote the source DB: `346076b`, `state=installed` on the old host. `346076b` **is an ancestor of `main` (`3c8310d`)**; the 15 commits since touch only `infra/` backup files (8 files, +488 lines) and docs — no kernel change. So either SHA is schema-safe; deploying `3c8310d` additionally puts `qevik_offsite.sh`'s source on the host. | 4 → 6 |
| D-4 | **The 11 migrated dumps** live in the directory `qevik-backup.timer` prunes (§8) and that `qevik-offsite.service` backs up. Decide their location before enabling the backup timer. | 4 → 6/10 |
| D-5 | **Phase 5 schema diff** needs the target's `init_db()` result, which only exists after the Phase 4 deploy. | 4 → 5 |
| D-6 | **Phase 6 drops and recreates the `qevik` database** from the production dump; Phase 4's schema is discarded. Do not treat the Phase 4 database as data. | 4 → 6 |
| D-7 | **D-E (certs)** is decided inside Phase 4 and determines the Phase 9 cutover's TLS risk (R-09). | 4 → 9 |
| D-8 | **V15** (restore an off-host dump into a scratch DB) becomes possible only once Postgres exists on the target — i.e. in Phase 4. It is a Phase 7 gate but is cheapest here. | 4 → 7 |
| D-9 | **Playwright/venv parity (R-16)** captured now feeds the `constraints.txt` the owner is asked to review and commit later. | 4 → 10 |
| D-10 | **T9 health component** (`health.py:23 SERVICES`) is Phase 10 code work; §15 N-5 records that the list is already wrong for the current runtime. | 4 → 10 |
| D-11 | `/root/qevik-infra/` is interim; after Phase 4 the off-host installer is re-run from `/opt/qevik/atlas/infra/` and that directory is removed (`OFFSITE_BACKUP.md` §10). | inside 4 |

---

## 12. Step-by-step execution order with STOP/GO gates

Nothing below has been done. Each **GATE** is a hard stop for the owner.

**GATE A — owner GO for Phase 3** (not Phase 4): sshd hardening under AR-2, `ufw`
mirror, fail2ban, 2 GB swap, `qevik` user, directory skeleton, and the owner
typing the five env files. Phase 4 cannot start before "files are in place".

**GATE B — owner reviews and pushes the R-12 change** (D-2). Until then no deploy
script can address `qevik-prod-01` with the correct key.

Then, on the target:

| # | Step | Host-changing? |
|---|---|---|
| 1 | Record the pre-Phase-4 baseline (`systemctl list-unit-files 'qevik-*'`, `dpkg -l`, `ls -l /opt/qevik /var/lib/qevik /srv`, `restic snapshots`) into `evidence/phase-4/` | no |
| 2 | Capture `pip freeze` + `pip show playwright` from the old host (read-only) → `evidence/phase-4/old-host-freeze.txt` | no |
| 3 | `apt-get install postgresql-18 python3-venv python3-pip ffmpeg`; create role/db `qevik` (owner types the password) | yes |
| 4 | Add the Cloudsmith Caddy source; install Caddy ≥ 2.11; **do not** start it with the production Caddyfile yet | yes |
| 5 | Create `/opt/qevik/{market,ms-playwright}`, `/var/lib/qevik/{control,control/reports,scratch,worktrees,jobs}`, `/srv/{sites,qevik-public,qevik-control}` with the §5 ownership; reconcile `/opt/qevik` and `/opt/qevik/backups` ownership; move the 11 dumps per D-4 | yes |
| 6 | Create the venv; `pip install -e .[dev] -c old-host-constraints.txt`; `pip install playwright==1.62.0`; `PLAYWRIGHT_BROWSERS_PATH=/opt/qevik/ms-playwright playwright install --with-deps chromium` (pin build 1234) | yes |
| 7 | Install `qevik-jobs.slice` + `qevik-api.service.d/resources.conf`; `daemon-reload`; `systemctl start qevik-jobs.slice` | yes |
| 8 | **`deploy_control.sh --rehearse root@qevik-prod-01`** — writes nothing; must print `REHEARSED` and exit 0 | no |
| 9 | **GATE C — owner GO for the first real deploy.** Then `QEVIK_DEPLOY_SHA=<346076b or the reviewed successor> deploy_control.sh root@qevik-prod-01` | yes |
| 10 | Install the two timers by hand; `systemctl enable` the 7 services (+ decide backup/market-scan timer enablement per D-4) | yes |
| 11 | Caddy: install the repo Caddyfile minus the `:8443` block; `caddy validate`; **GATE D — D-E decision** (copy `/var/lib/caddy` from the old host, or start with `tls internal`); start Caddy | yes |
| 12 | `deploy_console.sh` / `deploy_public.sh` against the target (post-R-12); note both assert **public** hostnames and will fail their late checks until cutover — run them with that expectation, or run only their install halves | yes |
| 13 | **Reboot test** (R-14): `reboot`, then verify every unit, timer, Caddy and Postgres came back | yes |
| 14 | Optional here, cheapest here: **V15** — restore one dump from the Storage Box into a scratch DB with `pg_restore` and drop it | yes (scratch only) |
| 15 | Re-run `install_offsite_backup.sh` from `/opt/qevik/atlas/infra/`; delete `/root/qevik-infra/` | yes |
| 16 | Write `evidence/phase-4/` (unit sha256 table vs repo, `pip freeze` diff, health outputs, reboot log); **STOP** for the owner before Phase 5 | no |

---

## 13. Validation commands per step

| Step | Validation | Pass criterion |
|---|---|---|
| 3 | `sudo -u postgres psql -tAc "select version()"`; `psql -h 127.0.0.1 -U qevik -d qevik -c '\dt'`; `psql -tAc "show shared_buffers"` | 18.6; connects over loopback with scram; no tables yet |
| 4 | `caddy version` | ≥ 2.11.x (never 2.6.x) |
| 5 | `stat -c '%n %U:%G %a' …` for every path in §5; `find /var/lib/qevik -perm /o+w` | matches the table; no world-writable |
| 6 | `.venv/bin/pip list --format=freeze \| diff - evidence/phase-4/old-host-freeze.txt`; `.venv/bin/python -c "import playwright; print(playwright.__version__)"`; `ls /opt/qevik/ms-playwright` | every difference explained line-by-line; `1.62.0`; `chromium-1234` + `chromium_headless_shell-1234` present |
| 7 | `systemctl show qevik-jobs.slice -p MemoryMax -p TasksMax -p CPUQuotaPerSecUSec`; `systemctl cat qevik-api \| grep PLAYWRIGHT` | limits as in the repo file; browsers path set |
| 8 | exit code of `--rehearse` | 0 with `REHEARSED sha=…` (exit 5 = the host's `sha256sum --check` is unusable → stop) |
| 9 | `cat /opt/qevik/atlas/DEPLOYED_SHA`; `sha256sum --check /opt/qevik/atlas/DEPLOYED_MANIFEST`; `sha256sum /etc/systemd/system/qevik-*.service` vs repo | `state=installed` with the expected sha; manifest clean; unit hashes equal the repo (only `qevik-backup.service` may differ from the *old host*, by design) |
| 10 | `systemctl list-unit-files 'qevik-*'`; `systemctl list-timers` | 7 services enabled; timers in the intended state |
| 11 | `caddy validate --config /etc/caddy/Caddyfile`; `curl -sI --resolve app.qevik.ai:443:127.0.0.1 https://app.qevik.ai/health` | validate OK; loopback answers (401/200 both acceptable per the deploy's own rule) |
| 12 | `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health` and `:8081/health`; `/api/health` components | 200 on both `/health`; `/api/health` reports missions durable, vault sealed, claiming atomic |
| 12 | `psql -d qevik -tAc "select name, version, last_heartbeat from atlas_workers"` | 5 rows for `qevik-prod-01`, heartbeats < 90 s, version = the deploy's fingerprint |
| 13 | after `reboot`: `systemctl is-active` for the 7 services + caddy + postgresql; `systemctl list-timers` | all active within 2 minutes; timers scheduled |
| 14 | `pg_restore --list` then a real restore into `qevik_v15`; row counts; `dropdb` | restores clean; **this is V15** |
| 15 | `/usr/local/sbin/qevik_offsite.sh --status`; `systemctl start qevik-offsite.service` | `result: ok`, `restore_verified` sha256 match |
| all | `grep -RIn 'postgres://\|password=' evidence/phase-4/` ; `ps -eo args \| grep '://'` | zero hits (SR-1, SR-9) |

---

## 14. Rollback per host-changing step

| Step | Rollback |
|---|---|
| 3 apt + PG | `dropdb qevik; dropuser qevik; apt purge postgresql-18 postgresql-common` (nothing depends on it yet) |
| 4 Caddy + Cloudsmith source | `apt purge caddy`; `rm /etc/apt/sources.list.d/caddy-stable.list` + keyring; `apt update` |
| 5 dirs/ownership | `chown` back; `rm -rf` the created directories. **The 11 dumps:** move them back rather than delete; the restic repository is the second copy either way |
| 6 venv / Playwright | `rm -rf /opt/qevik/atlas/.venv /opt/qevik/ms-playwright` and repeat |
| 7 slice/drop-in | `rm /etc/systemd/system/qevik-jobs.slice /etc/systemd/system/qevik-api.service.d/resources.conf; systemctl daemon-reload` |
| 9 deploy | the script's own snapshot rollback (`/opt/qevik/rollback*`, restores kernel/console/infra/units and re-reads the marker; states `rolling-back` → `rolled-back`, exit 4 = **incomplete**, human required). Manual fallback: `rm -rf /opt/qevik/atlas/{packages,infra}` and redeploy |
| 10 timers/enablement | `systemctl disable --now <unit>`; `rm` the timer files |
| 11 Caddy config / certs | keep the previous `/etc/caddy/Caddyfile` (the deploy path writes it wholesale — take a copy first); `rm -rf /var/lib/caddy` and restart if a copied cert set is wrong |
| 12 console/public | both keep a `.previous`; swap back |
| 13 reboot | if the host does not return: Hetzner console → rescue; last resort is a rebuild (Phase 2 rollback), which costs only the Phase 4 work |
| 15 offsite re-install | idempotent; the repository, key and password are untouched by it |
| **whole phase** | console rebuild of server 164307556, then repeat Phases 2–4. The old host is untouched and still production throughout. |

---

## 15. Unresolved assumptions, unknowns and new risks

Items marked **NEW** were found by comparing the plan with the actual repository
and hosts today; they are not in the existing documents.

| # | Item | Class | Consequence / proposed handling (no decision taken) |
|---|---|---|---|
| N-1 | **NEW — Caddy version.** Plan Phase 4 says `apt install … caddy`; Ubuntu 26.04's candidate is **2.6.2**, the old host runs **2.11.4 from Cloudsmith**, and the repo Caddyfile requires ≥ 2.7 | blocker for step 4 | add the Cloudsmith source (or an equivalent pinned ≥ 2.11 build) and record it as a new apt trust anchor |
| N-2 | **NEW — the live Caddyfile is older than the repo's.** Live (225 lines) still has the SPA fallback; the repo (290 lines) has the 404 fix. `DATA_AND_STATE_INVENTORY.md` P1 says to migrate the live file as source of truth | doc drift | target takes the **repo** file minus the `:8443` block; P1's wording should be corrected when the owner approves this review |
| N-3 | **NEW — R-12 is wider than the IP.** All three deploy scripts hard-code `~/.ssh/naml_hetzner`, which D-F/SR-4 forbid on the new host; the parameterisation must cover the key, not just the host | blocker for steps 8/9/12 | fold into the O10 change |
| N-4 | **NEW — the DB password is sourced by a shell** (`deploy_control.sh:766` `set -a && . atlas.env`) | can break the deploy | owner picks a shell-safe/URL-safe password, or the value is quoted in the file |
| N-5 | **NEW — `health.py:23 SERVICES`** lists only `qevik-api`, `postgresql`, `caddy`, and the two old timers; it omits `qevik-control`, all five workers and `qevik-offsite.timer`, and probes `:8080` while the deploy gates on `:8081` | T9 scope | Phase 10 code change, owner-approved |
| N-6 | **NEW — `qevik` account shape.** Old host: `/bin/bash` + home + a GitHub deploy key; the target architecture says no login | small decision | default: create with `nologin` and no `authorized_keys`; note that `bootstrap_qevik_server.sh` would do the opposite |
| N-7 | **NEW — `/opt/qevik/backups` ownership + `KEEP=14` pruning** vs the 11 migrated dumps (§8, D-4) | decision | default: `archive/` subdirectory + backup timer disabled until Phase 6 |
| N-8 | **NEW — `qevik-jobs.slice` is sized for an 8 GB / 4-core host** (MemoryMax 3500M, CPUQuota 300 %); the target has 15 GiB / 8 vCPU | sizing | keep as-is for like-for-like, or raise deliberately; not a Phase 4 blocker |
| N-9 | **NEW — timer timezones.** `qevik-backup.timer` (03:30) and `qevik-market-scan.timer` (06:00) are tz-naive; `qevik-offsite.timer` is explicitly `UTC`. The target is `Etc/UTC`, so today they agree | latent | leave, or make all three explicit |
| N-10 | **NEW — `shared_buffers`** target 512 MB (owner doc) vs 128 MB actual on the old host | deviation | owner confirms; it is an improvement, not parity |
| N-11 | **NEW — `postgresql-client-18` is already installed on the target** (by the dump-verification task on 2026-09-03) | state note | harmless; the server package will align it |
| N-12 | Phase 3 items still open on the target: **no swap** (D-B wants 2 GB), `ufw` inactive (D-D wants a mirror), `passwordauthentication yes`, no fail2ban | prerequisite | all belong to Phase 3, before Phase 4 |
| N-13 | D-E (certs), D-H (retarget strategy), D-I (S1/S6/S11/A6/D6), D-K (operator accounts) still undecided | decisions | D-E and D-H are needed **inside** Phase 4 |
| N-14 | U10 `QEVIK_REPORTS_STORE` value still unread; U9 vault-key decision still open | unknown | both are owner reads/decisions in Phase 3 |
| N-15 | U4 (Playwright install method) is now **RESOLVED**: `playwright 1.62.0`, browsers `chromium-1234`, `chromium_headless_shell-1234`, `ffmpeg-1011` | resolved | record in the inventory when the owner approves |
| N-16 | `deploy_console.sh` also rsyncs the kernel with `--delete` into the directory ADR-0010 manages — a second, provenance-free code path | pre-existing risk | do not run it against the target after a `deploy_control.sh` deploy without knowing this; ideally the R-12 change removes the duplicate |
| N-17 | `deploy_console.sh`/`deploy_public.sh` assert **public** URLs (`https://app.qevik.ai/…`, 401 checks, sitemap fetches) which cannot pass before cutover | expectation | run their install halves in Phase 4; expect the public assertions to fail until Phase 9 |
| N-18 | Doc-path drift: the review request names `docs/migration/hetzner/00_PROJECT_STATE.md`; the file is `docs/qevik-docs/00_PROJECT_STATE.md` | trivial | noted for future references |
| N-19 | `bootstrap_qevik_server.sh` and `recover_qevik_server.sh` remain the only "provisioning" scripts and both are wrong for this host (§6.4) | R-15 | §12 is the checklist; turning it into a script is separate, owner-approved work |
| N-20 | U1 (Hetzner project name, 2FA), U2 (Cloudflare SSL mode) still owner-pending | unchanged | not blocking Phase 4; U2 blocks the D-E reasoning only mildly (copying certs is safe under both Full and Full-strict) |

---

## 16. Stop

This review is presented for approval. Nothing in §12 has been executed, no
package was installed, no service created, no data connected, no secret handled,
no DevLoop task enqueued. The next action is the owner's: approve, correct, or
re-scope — and separately give the Phase 3 GO, which Phase 4 depends on.
