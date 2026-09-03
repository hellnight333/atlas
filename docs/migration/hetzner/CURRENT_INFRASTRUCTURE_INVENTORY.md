# CURRENT_INFRASTRUCTURE_INVENTORY

Phase 0 deliverable 1 of the Hetzner / Infrastructure Migration mission.
Read-only discovery. Nothing on any host was changed.

## Evidence classification

Every statement about the current environment carries one tag:

| Tag | Meaning |
|---|---|
| **PROVED** | Read directly from the live system (command output, file content, DNS answer from an authoritative path) during this discovery, with the evidence file named. |
| **OBSERVED** | Seen in the live system but as a side-effect or absence (e.g. "no such file", "no process matched"), or seen once without a second confirming path. |
| **INFERRED** | A conclusion drawn from PROVED/OBSERVED facts. Not itself verified. |
| **UNKNOWN** | Not obtainable with read-only access from the vantage points used. Stays UNKNOWN until evidence is obtained. |

Evidence files (scratchpad, session `cedd70e3`, path `scratchpad/discovery/`):
`prod-identity.txt`, `prod-services.txt`, `prod-postgres.txt`, `prod-storage.txt`,
`prod-caddy-units.txt`, `prod-security-misc.txt`, `prod-dns-net-misc.txt`,
`prod-ops-activity.txt`, `dns.txt`, `devloop01.txt`. All were captured
2026-09-02 23:44 UTC – 2026-09-03 00:15 UTC over SSH as root with existing keys.
Credential-bearing lines were redacted in the files (`<REDACTED>`); no secret
value appears in this document or in any deliverable.

Vantage points used: the operator Mac (SSH origin), the production host
itself, and `qevik-devloop-01` as an independent second network vantage point.

---

## 1. Hosts

### 1.1 `qevik-core-01` — current production (PROVED unless tagged)

| Attribute | Value | Evidence |
|---|---|---|
| Provider / product | Hetzner Cloud, "vServer" (KVM), **already on Hetzner** | `hostnamectl`, metadata endpoint — `prod-identity.txt` |
| Instance id | 162146484 | metadata |
| Region / AZ | `eu-central` / `nbg1-dc3` (Nuremberg) | metadata |
| OS / kernel | Ubuntu 26.04 LTS, Linux 7.0.0-29-generic | `os-release`, `uname` |
| CPU | 4 vCPU, AMD EPYC-Genoa | `nproc`, `/proc/cpuinfo` |
| RAM | 7.6 GiB total; 1.7 GiB used, 4.5 GiB cache at capture; **no swap** | `free -h` |
| Disk | 150 GB ext4 on `/dev/sda1`; 12 GB used (9 %); 256 MB EFI | `df`, `lsblk` |
| Block devices | single QEMU virtual disk (`scsi-0QEMU_QEMU_HARDDISK_125129364`); **no Hetzner Volume attached** | `/dev/disk/by-id` — `prod-ops-activity.txt` |
| IPv4 | 2.28.62.83/32 (DHCP), gateway 172.31.1.1 | `ip addr`, `ip route` |
| IPv6 | 2a01:4f8:1c19:1d03::1/64 (static, gw fe80::1) | metadata network-config |
| Private network | none (`local-ipv4: ""`) | metadata |
| Reverse DNS | `static.83.62.28.2.clients.your-server.de` (Hetzner default) | `dig -x` from Mac — `dns.txt` |
| Hostname | `qevik-core-01` | `hostname`, `/etc/hosts` |
| Timezone / NTP | Etc/UTC, NTP active | `timedatectl` |
| Uptime at capture | 16 days 3 h; load 0.25 | `uptime` |
| Uptime of Caddy | ~9 days (ELAPSED 779788 s) | `ps` |
| Users with shell | root, postgres (uid 100), qevik (uid 1000) | `/etc/passwd` filter |
| Sudo | `/etc/sudoers.d/90-cloud-init-users`: root NOPASSWD ALL only | file read |

### 1.2 `qevik-devloop-01` — reserved for DevLoop execution (PROVED)

| Attribute | Value | Evidence |
|---|---|---|
| Provider | Hetzner Cloud, instance 164307556, `eu-central` / `nbg1-dc3` | metadata — `devloop01.txt` |
| OS / kernel | Ubuntu 26.04.1 LTS, Linux 7.0.0-30-generic | `os-release` |
| CPU / RAM / disk | 8 vCPU, 15 GiB, 301 GB (1.7 GB used) | `nproc`, `free`, `df` |
| IPv4 | 91.107.244.253 (reverse `static.253.244.107.91.clients.your-server.de`) | `dig -x` |
| Uptime at capture | 11 h 26 min (created/rebooted 2026-09-02 ~12:24 UTC — `/` mtime) | `uptime`, `ls -la /` |
| State | **Bare image.** Only sshd listening (22/tcp). `/opt`, `/srv`, `/home` empty. No caddy, postgresql, docker, node, python venv, or Atlas checkout. Only `git 2.53`, `rsync 3.4.1`, system `python3`. | `ss -tlnp`, `dpkg -l`, `ls` |
| Access | root via SSH key `~/.ssh/devloop_01` (1 authorized key) — access **works** | this session |
| sshd | `permitrootlogin prohibit-password`, **`passwordauthentication yes`** | `sshd -T` |
| Firewall | `ufw` **inactive**; Hetzner Cloud Firewall: UNKNOWN (not visible from inside) | `ufw status` |
| Same AZ as production | yes (`nbg1-dc3`) — INFERRED implication: a Hetzner private network between them is possible; none exists today (PROVED: no private IP on either host) | metadata |

Per the owner's architectural decision this host receives **no production
workload**. It is inventoried here only as the DevLoop/Prod separation
boundary and as a second vantage point.

### 1.3 Operator workstation (OBSERVED)

The Mac at `/Users/salmansheraf` holds the Atlas checkout (`~/atlas`, main
`6ad8a98`, unpushed), the DevLoop driver, and the SSH keys `~/.ssh/naml_hetzner`
(root@2.28.62.83) and `~/.ssh/devloop_01` (root@91.107.244.253). ADR-0010
deployments are executed from this Mac over SSH (OBSERVED in the DevLoop runs
r-974f37a63d and r-de832730ac earlier this session). Its resolver returns
`198.18.0.x` addresses for every `qevik.ai` name (`dns.txt`) — a local
VPN/fake-IP layer — so **DNS must never be judged from the Mac**; authoritative
answers in this document come from the production host querying `1.1.1.1`.

---

## 2. Network, DNS and edge

### 2.1 DNS (PROVED via `dig @1.1.1.1` from qevik-core-01 — `prod-dns-net-misc.txt`)

| Name | Answer | Classification |
|---|---|---|
| `qevik.ai` NS | `elliot.ns.cloudflare.com`, `perla.ns.cloudflare.com` | PROVED — zone is hosted at **Cloudflare** |
| `qevik.ai` A/AAAA | 104.21.30.175, 172.67.173.123 / 2606:4700:3037::ac43:ad7b, 2606:4700:3034::6815:1eaf | PROVED — Cloudflare anycast, i.e. **proxied (orange-cloud)** |
| `www.qevik.ai` | same four Cloudflare addresses | PROVED proxied |
| `app.qevik.ai` | same | PROVED proxied |
| `sites.qevik.ai` | same | PROVED proxied |
| `api.qevik.ai`, `webhook.qevik.ai`, `mail.qevik.ai` | **no record** | PROVED absent at query time |
| `MX qevik.ai` | **none** | PROVED absent |
| `TXT qevik.ai`, `TXT _dmarc.qevik.ai` | **none** (no SPF, no DMARC) | PROVED absent |
| `caddy` global `email qevikos@gmail.com` | ACME contact only | PROVED (Caddyfile) |

Consequences (INFERRED): the origin IP 2.28.62.83 is not published in DNS;
Cloudflare terminates client TLS and dials the origin on 443 with a real
certificate ("Full/Full strict", per the Caddyfile header comment which itself
records this as *observed*). There is **no email sending or receiving
infrastructure declared at the DNS level** for `qevik.ai`.

UNKNOWN: Cloudflare account owner, zone settings (SSL mode, WAF, page rules,
DNS-only records not resolvable from outside), API tokens, whether other zones
exist. Read-only Cloudflare API access was not available and was not requested.

### 2.2 Edge behaviour (PROVED — `dns.txt`, `devloop01.txt`)

- `https://app.qevik.ai/` → HTTP 200, `server: cloudflare`, `cf-cache-status: DYNAMIC`, `cf-ray …-CDG`.
- `https://qevik.ai/` → 200 via Cloudflare. `https://sites.qevik.ai/` → 404 (no site at root — expected; `/sample/` → 200).
- From `qevik-devloop-01`: `app.qevik.ai/health` 200 (1.5 s), `qevik.ai/` 200, `sites.qevik.ai/sample/` 200.
- Direct origin `http://2.28.62.83/` → **308** (from devloop-01).
- Direct origin on the loopback with SNI: `app.qevik.ai` 200, `qevik.ai` 200, `sites.qevik.ai` 404 (from the host itself).

### 2.3 Host firewall and exposure (PROVED)

`ufw` active, default deny incoming / allow outgoing; allowed **22, 80, 443**
(v4+v6). `fail2ban`: **not installed/inactive**. Hetzner Cloud Firewall:
**UNKNOWN**.

Second-vantage port test from `qevik-devloop-01` (`devloop01.txt`):
`8443` **closed/filtered**, `5432` closed/filtered, `8080` closed/filtered.

> **Contradiction recorded.** `/etc/caddy/Caddyfile` defines
> `https://2.28.62.83:8443` as "the operator's way back in if DNS or Cloudflare
> breaks", and Caddy listens on `*:8443` (PROVED `ss`). But `ufw` does not allow
> 8443 and the port is unreachable from a second host (PROVED). The documented
> emergency door **does not exist in practice**; the only emergency access path
> today is SSH.

### 2.4 sshd (PROVED — `prod-security-misc.txt`)

`port 22`, `permitrootlogin prohibit-password`, `pubkeyauthentication yes`,
**`passwordauthentication yes`**, `kbdinteractiveauthentication no`,
`maxauthtries 6`. One ED25519 key in `/root/.ssh/authorized_keys`
(SHA256:VI9xBRcQw69kudOCQQg/1BewuhAu+K/d89tHUtJJD4s). The `qevik` user has
no `authorized_keys` file (OBSERVED).

---

## 3. Runtime and packages (PROVED — `prod-security-misc.txt`, `prod-services.txt`)

| Component | Version / location |
|---|---|
| Caddy | 2.11.4, `/usr/bin/caddy run --environ --config /etc/caddy/Caddyfile`, `User=caddy`, admin API **off** |
| PostgreSQL | 18.6 (Ubuntu package `postgresql-18`), cluster `18-main`, data `/var/lib/postgresql/18/main` (589 MB) |
| Python | 3.14.4 in `/opt/qevik/atlas/.venv` (371 MB) |
| Playwright browsers | `/opt/qevik/ms-playwright` (chromium-1234, chromium_headless_shell-1234, ffmpeg-1011) — 656 MB; duplicate copy in `/root/.cache/ms-playwright` 656 MB |
| ffmpeg | 8.0.1 (apt) |
| rsync 3.4.1, curl 8.18, ufw, unattended-upgrades (security origin enabled) | apt |
| **Absent**: node, claude, codex, docker, nginx, fail2ban, any metrics agent | `which`/`dpkg`/`pgrep` |

---

## 4. Services (systemd) — PROVED from unit files (`prod-caddy-units.txt`)

All application units run as `User=qevik`, `WorkingDirectory=/opt/qevik/atlas`,
with `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome`.
All were (re)started 2026-09-02 23:08–23:09 UTC by the ADR-0010 deployment of
`346076b` (PROVED: `ps ELAPSED`, journal "last" timestamps).

| Unit | Role | ExecStart (abridged) | Listens | Env files | Writable paths | Notes |
|---|---|---|---|---|---|---|
| `qevik-api.service` | Atlas kernel API + sales console API | `.venv/bin/python -m uvicorn atlas_kernel.api:app --host 127.0.0.1 --port 8080` | 127.0.0.1:8080 | `atlas.env`; drop-in `resources.conf` adds `-brave.env`, `-places.env`, `-cloudflare.env` (**cloudflare.env does not exist** — OBSERVED) | `/opt/qevik`, `/var/lib/qevik`, `/srv/sites` | `Requires=postgresql`; MemoryHigh 1200M / MemoryMax 1536M, TasksMax 192; `PLAYWRIGHT_BROWSERS_PATH=/opt/qevik/ms-playwright` |
| `qevik-control.service` | Qevik control plane (auth, `/api/*`, missions, credentials vault) | `uvicorn --factory atlas_kernel.qevik.app:from_environment --host 127.0.0.1 --port 8081 --workers 1` | 127.0.0.1:8081 | `atlas.env`, `-control.env` | `/var/lib/qevik`, `/srv/sites`; `StateDirectory=qevik` | `QEVIK_STATE=/var/lib/qevik/control`, `QEVIK_SCRATCH=/var/lib/qevik/scratch`, `PYTHONPATH=packages/kernel` |
| `qevik-worker.service` | mission worker `worker-1`, agent `self-check` | `infra/mission_worker.py --timeline …/missions.jsonl --reports …/control/reports --worktrees …/worktrees --scratch …/scratch --state …/control --tenant tenant-qevik --interval 10` | — | `atlas.env`, `-control.env`, `-worker.env` | `/var/lib/qevik` | `StartLimitBurst=5/300s` |
| `qevik-worker-research.service` | agent `research` (declared recipes, no model) | same shape, `--name worker-research --agent research` | — | same | `/var/lib/qevik` | registers "capabilities dns, http-fetch" (journal) |
| `qevik-worker-delivery.service` | agent `delivery` (approved opportunities) | `--name worker-delivery --agent delivery` | — | same | `/var/lib/qevik` | |
| `qevik-worker-publish.service` | agent `publish` (authorised publications) | `--name worker-publish --agent publish` | — | same | `/var/lib/qevik`, **`/srv/sites`**; `QEVIK_SITES_ROOT=/srv/sites` | the only worker that writes the served sites |
| `qevik-worker-healthcheck.service` | agent `healthcheck` (audit reports) | `--name worker-healthcheck --agent healthcheck` | — | same | `/var/lib/qevik` | |
| `qevik-backup.service` + `.timer` | daily pg_dump, restore-verified, prune | `infra/qevik_backup.sh`; `OnCalendar 03:30 UTC`, `Persistent`, jitter 300 s | — | `atlas.env` | `/opt/qevik` | last run 2026-09-02 03:34: "VERIFIED — restores cleanly", "retained 10" (PROVED journal) |
| `qevik-market-scan.service` + `.timer` | daily Google Places sample (Dubai) → `/opt/qevik/market/latest.json` | `infra/market_scan.py --area dubai --source places --sample 10`; `OnCalendar 06:00 UTC`, jitter 900 s | — | `atlas.env`, `-places.env` | `/opt/qevik` | last run 2026-09-02 06:09 OK |
| `qevik-jobs.slice` | cgroup for generated workloads (browsers, builds) | MemoryHigh 3G / MemoryMax 3500M, TasksMax 384, CPUQuota 300 %, CPU/IO weight 50 | — | — | — | who places work in it: see repo inventory |
| `caddy.service` | reverse proxy + static hosting + TLS | see §5 | *:80, *:443, *:8443 | — | `/var/lib/caddy` | |
| `postgresql@18-main.service` | database | | 127.0.0.1:5432, [::1]:5432 | | | local-only |

Other enabled units of note: `ssh`, `cron` (no user crontabs; only
`e2scrub_all` in `/etc/cron.d`), `unattended-upgrades`, `atd`, `vgauth`,
`gpu-manager`, `netplan-configure`. `systemctl --failed`: **none**.

Journal health, last 7 days (PROVED — `prod-ops-activity.txt`): `qevik-api`,
`qevik-control`, `caddy`, `postgresql`, `qevik-backup`, `qevik-market-scan`
0 errors; each `qevik-worker*` unit 7 errors / 21 warnings (healthcheck 1/8) —
content not classified here; INFERRED to be restart-window noise from the two
deployments in that window, **not verified**.

### 4.1 Stale, non-unit processes (PROVED — `prod-services.txt`)

Running as **root**, outside systemd, for ~7.5 days at capture:
two `infra/verify_recurrence.py --dsn postgresql+psycopg://…` processes with
their forkserver/resource-tracker children, plus seven `bash -c until ! pgrep …`
watcher loops (`verify_tool_role`, `verify_two_workers`,
`verify_scratch_isolation`, `real_run.py`) tailing `/tmp/*.log`. These were
started by hand (`nohup bash -c "set -a; . /opt/qevik/atlas.env; …"`).

> **Security finding.** The database DSN **including the password** is present
> in the argv of those root processes and is therefore readable via `ps` /
> `/proc/<pid>/cmdline` by any local user. It was exposed to this session's
> `ps` output and immediately redacted from the evidence file; it is reproduced
> nowhere. Owner action is listed in `SECRET_AND_DEPENDENCY_INVENTORY.md`
> (rotate at migration; never pass DSNs on the command line).

---

## 5. Reverse proxy, TLS and static roots (PROVED — `/etc/caddy/Caddyfile`)

Global: `admin off`; `email qevikos@gmail.com`; `trusted_proxies static` =
Cloudflare IPv4/IPv6 ranges (so `CF-Connecting-IP` is honoured). Snippets:
`security` (nosniff, DENY framing, no-referrer, `-Server`), `le` (ACME with
`disable_tlsalpn_challenge`, i.e. **HTTP-01 only**, which requires port 80
reachable through Cloudflare).

| Site block | Behaviour | Root / upstream |
|---|---|---|
| `qevik.ai` | public marketing site, SPA fallback, console log | `/srv/qevik-public` (2.1 MB: `index.html`, `about`, `ar`, `assets`, `contact`, `services`, `work`, `robots.txt`, `sitemap.xml`) |
| `www.qevik.ai` | 301 → `https://qevik.ai{uri}` | — |
| `app.qevik.ai` | `/api/*`, `/auth/*`, `/health` → 127.0.0.1:**8081**; `/control/*` → 127.0.0.1:**8080**; everything else = static console SPA; strict CSP (`default-src 'self'`) | `/srv/qevik-control` (148 KB; previous build kept in `/srv/qevik-control.previous`) |
| `sites.qevik.ai` | customer/demo sites; `/{slug}/…` rewritten through `/{slug}/current/…` (publish-then-promote symlink model); header `X-Qevik-Host: sites` | `/srv/sites` (18 MB, **59 site directories** incl. `_preview`, 24 `demo-*`, 20 `sample-*`, 3 `site-<hex>`, games, `qevik-proof`) |
| `https://2.28.62.83:8443` | `tls internal` mirror of the `app` block (emergency door — **unreachable**, see §2.3) | same |
| `:80` | bare-IP sites origin, header `X-Qevik-Host: sites-origin` | `/srv/sites` |

Certificates (PROVED — `/var/lib/caddy/.local/share/caddy/certificates/`):
Let's Encrypt for `app.qevik.ai`, `qevik.ai`, `sites.qevik.ai`, `www.qevik.ai`;
internal CA for `127.0.0.1` and `2.28.62.83`. Caddy state total 236 KB.
Caddyfile history kept beside it: `.before-control-plane`, `.pre-8443-lockdown`,
`.pre-domain`, `.pre-noindex`, `.pre-site-rebuild`; `/etc/caddy/sites.d/` is
empty. `/opt/qevik/` also holds three older Caddyfile variants
(`qevik-control.Caddyfile`, `qevik-production.Caddyfile`, `qevik-sites.Caddyfile`)
— relationship to the live file UNKNOWN (not diffed).

Access logs: `format console` to journald (no file logging; no logrotate entry
for caddy — PROVED). Journal on disk: 648 MB; `journald.conf` has no `SystemMaxUse`/`MaxRetentionSec` override, so **default retention** (10 % of FS, capped 4 GB) applies (PROVED).

---

## 6. Database (PROVED — `prod-postgres.txt`, `prod-ops-activity.txt`)

| Attribute | Value |
|---|---|
| Server | PostgreSQL 18.6, `max_connections=100`, `shared_buffers=128MB` (defaults), `wal_level=replica`, port 5432 |
| Listen | `127.0.0.1` and `::1` only; `pg_hba`: `local` peer; `host 127.0.0.1/32` + `::1/128` scram-sha-256; replication rows local-only |
| Databases | `qevik` **418 MB** (75 public tables in the captured listing; an earlier count of 78 could not be reproduced from the capture — exact count to be re-read in Phase 5), `qevik_test` 65 MB, `postgres` 7.7 MB |
| Roles | `postgres` (superuser), `qevik` (login, non-superuser) |
| Extensions | `plpgsql` only, both DBs |
| Largest tables | `atlas_worker_heartbeats` 72 MB / ~210 k rows (grows continuously), `atlas_mission_reports` 17 MB / 27 rows, `atlas_assets` 4.3 MB, `atlas_business_events` 3.5 MB, `atlas_roles` 3.4 MB |
| Active connections | 13 backends on `qevik` (5 workers ×2, control ×2, api ×1 — matches process list); `qevik_test` 0 backends, `xact_commit` 249 388 historically |
| Write activity | `atlas_workers` and `atlas_worker_heartbeats` are the hot tables (216 k / 211 k tuple writes); most other tables last autovacuumed 18–21 Aug → INFERRED low write rate outside worker telemetry |
| Data dir size | 589 MB |
| Replication | none configured (no standby, no slots seen; logical replication launcher idle) — OBSERVED |

`qevik_test`: no backends; purpose INFERRED (test suite / acceptance runs on the
host); whether anything in production depends on it: **UNKNOWN**.

---

## 7. Storage layout (PROVED — `prod-storage.txt`)

| Path | Size | Owner | Content |
|---|---|---|---|
| `/opt/qevik/atlas` | 4.8 GB | uid 501 (Mac uid; rsynced) | Application tree — a **git checkout** of `https://github.com/hellnight333/atlas.git` at `ce4ffaa` (main) with **306 dirty entries** (OBSERVED): the ADR-0010 payload is rsynced over it, so the working tree is the deployed export, not the checkout's HEAD. Includes `.venv` 371 MB and `.mypy_cache`. |
| `/opt/qevik/atlas/DEPLOYED_SHA`, `DEPLOYED_MANIFEST` | 176 B / 60 KB | — | `state=installed sha=346076b… installed_at=2026-09-02T23:08:52Z manifest_sha256=0716c415…`; manifest = per-file sha256 of the payload |
| `/opt/qevik/rollback`, `rollback-infra`, `rollback-console`, `rollback-units` | 11 MB / 63 MB / 140 KB / 56 KB | qevik / root | ADR-0010 pre-deploy snapshots (only these four exist — PROVED `ls -d`) |
| `/opt/qevik/backups` | 80 MB | qevik | 10 verified `pg_dump` custom-format files, 2026-08-17 → 2026-09-02, newest 19.6 MB; KEEP=14 |
| `/opt/qevik/ms-playwright` | 656 MB | root | browsers |
| `/opt/qevik/market` | 1.8 MB | qevik | `latest.json` from market scan |
| `/opt/qevik/verification-scratch` | 19 MB | qevik | hand-run verification residue |
| `/opt/qevik/*.env` | 5 files | see §8 | environment files |
| `/opt/qevik/.pgpass` | 40 B, root 0600 | root | Postgres password file (used by hand-run tooling; INFERRED) |
| `/opt/qevik/*.py`, `*.sh`, `index.html` | ~20 files | mixed | hand-copied helper scripts (Aug 17–25): `audit_prospects.py`, `prospect_pipeline.py`, `verify_*.py`, `enable_domain.sh`, `workflow_job.sh` … — not part of the deploy payload (INFERRED from ownership/mtimes) |
| `/var/lib/qevik` | 258 MB | qevik | application state: `control/` 6.6 MB (`missions.jsonl` 344 KB last written **2026-08-27**, `credentials.jsonl` 15.7 KB **0644**, `vault.json` 2 B 0600, `reports/docs/` 11 files 6.2 MB), `evidence/` 165 MB (354 mission dirs, last 2026-08-21), `scratch/` 45 MB (per-mission, newest 2026-09-02 05:00), `worktrees/mission/` 14 MB (newest 2026-09-02 05:01), `jobs/` 3.9 MB, `backups/` 22 MB (two ad-hoc `.sql` dumps from 2026-08-19), `prospects/` 2 MB, `audits/`, `briefs/`, `outreach/` 44 KB, `workspaces/` 348 KB |
| `/srv/sites` | 18 MB | qevik | 59 published site directories (served) |
| `/srv/qevik-public` | 2.1 MB | uid 501 | marketing site (served) |
| `/srv/qevik-control` (+`.previous`) | 148 KB | qevik | console SPA build (served) |
| `/var/lib/postgresql/18/main` | 589 MB | postgres | database cluster |
| `/var/lib/caddy` | 236 KB | caddy | certificates, ACME account |
| `/var/log/journal` | 657 MB | | journald |
| `/home/qevik/.cache`, `/root/.cache` | 771 MB / 667 MB | | pip/playwright caches |

Total used: 12 GB of 150 GB.

---

## 8. Configuration files carrying secrets (NAMES ONLY — PROVED `prod-storage.txt`, `prod-caddy-units.txt`)

| File | Owner / mode | Variable names |
|---|---|---|
| `/opt/qevik/atlas.env` | root 0600 (mtime 2026-08-27) | `ATLAS_DATABASE_URL`, `QEVIK_ADMIN_PASSWORD`, `QEVIK_DASHSCOPE_API_KEY`, `QEVIK_DASHSCOPE_BASE_URL`, `QEVIK_LEDGER`, `QEVIK_REPORTS_STORE`, `QEVIK_SITES_BASE_URL` |
| `/opt/qevik/control.env` | qevik 0600 | `QEVIK_VAULT_MASTER_KEY`, `QEVIK_CLAIMS_DSN`, `QEVIK_REQUIRE_ATOMIC_CLAIMS` |
| `/opt/qevik/worker.env` | qevik 0600 | `QEVIK_CLAIMS_DSN`, `QEVIK_REQUIRE_ATOMIC_CLAIMS` |
| `/opt/qevik/brave.env` | root 0600 | `QEVIK_BRAVE_API_KEY` |
| `/opt/qevik/places.env` | qevik 0600 | `QEVIK_GOOGLE_PLACES_API_KEY` |
| `/opt/qevik/cloudflare.env` | **does not exist** (referenced optionally by `resources.conf`) | — |
| `/opt/qevik/.pgpass` | root 0600 | (Postgres password file) |
| `/var/lib/qevik/control/vault.json` | qevik 0600, 2 bytes | sealed credential vault (effectively empty — OBSERVED size) |

Values were not read. Full analysis in `SECRET_AND_DEPENDENCY_INVENTORY.md`.

---

## 9. Scheduled work, backups, monitoring

- **Backups (PROVED):** daily 03:30 UTC `pg_dump` of `qevik`, restore-verified into a scratch DB, pruned to 14, stored in `/opt/qevik/backups` **on the same virtual disk as the database**. **No off-host copy observed** (no rsync/scp/S3 step in the script head, no other unit). Hetzner server snapshots/backups add-on: **UNKNOWN** (not visible from inside).
- **Filesystem state (`/var/lib/qevik`, `/srv/sites`) backups:** **none observed** (OBSERVED).
- **Market scan (PROVED):** daily 06:00 UTC, calls Google Places.
- **Monitoring / alerting (OBSERVED absence):** no node_exporter, netdata, telegraf, datadog, prometheus, grafana, uptime agents; no alerting units; no external uptime monitor visible from inside. Backup script's own comment records a **5-day silent backup failure (2026-08-22 → 08-26)** that nothing detected. External monitoring configured elsewhere (e.g. Cloudflare, a SaaS pinger): **UNKNOWN**.
- **Log retention:** journald only; 648 MB; retention policy UNKNOWN.
- **OS patching:** unattended-upgrades enabled for security origin (PROVED).

---

## 10. Deployment model in force (OBSERVED this session, PROVED on host)

ADR-0010 immutable deploy payload: driver on the Mac exports a git archive of
the target SHA, rsyncs it to `/opt/qevik/atlas` over SSH as root, snapshots
rollback dirs, installs units from `infra/`, restarts the seven application
units, probes `/health` and the public sha256 marker, and writes
`DEPLOYED_SHA` / `DEPLOYED_MANIFEST`. Last deployment: `346076b`,
2026-09-02 23:08:52 Z, all units healthy afterwards (PROVED). There is no
container runtime, no CI-driven deploy, and no blue/green (single-host,
restart-in-place).

---

## 11. Outbound dependencies observed from the host

`ss` at capture showed only Cloudflare-sourced inbound connections and the SSH
session (PROVED). Outbound API endpoints are therefore taken from **configuration
and code**, not from live sockets: DashScope (`QEVIK_DASHSCOPE_BASE_URL`),
Brave Search, Google Places, Let's Encrypt (ACME), GitHub (git remote; only used
by hand), Ubuntu apt mirrors. The many `http://www.google.com`, `openai.com`
etc. strings in the last-24 h journal are **inbound crawler referers/user-agents
in Caddy access logs, not outbound calls** (OBSERVED, INFERRED). Full list with
consuming service in `SECRET_AND_DEPENDENCY_INVENTORY.md`.

---

## 12. Resource utilisation snapshot (PROVED, single sample)

CPU load 0.25 on 4 vCPU; RAM 1.7 GiB used + 4.5 GiB cache of 7.6 GiB (no swap);
disk 12 GB / 150 GB; per-process RSS: uvicorn 8080 110 MB, 8081 114 MB, each
worker ~105 MB, Postgres backends 18–150 MB, Caddy 51 MB. Peak/95th-percentile
figures: **UNKNOWN** (no metrics history exists).

---

## 13. Summary of UNKNOWNs raised by this inventory

1. Hetzner Cloud project, Cloud Firewall rules, snapshot/backup add-on state, and API token ownership (needs Hetzner console/API — owner).
2. Cloudflare zone settings (SSL mode, WAF, cache rules, any DNS-only or non-public records), account ownership and token scope (owner).
3. Whether any external uptime/alerting exists outside the host.
4. Playwright install method/version on the host (not in `pyproject.toml`).
5. Purpose and dependence on `qevik_test`.
6. Content of the 7 errors/21 warnings per worker unit in the last 7 days.
7. Relationship of the three legacy Caddyfiles in `/opt/qevik` and the five `/etc/caddy/Caddyfile.*` backups to the live config.
8. `qevik` user has no `~/.ssh/authorized_keys` (OBSERVED: file absent) — resolved, not unknown.
9. Peak resource usage (no history).

---

## 14. Repository cross-check (PROVED from `~/atlas` at `6ad8a98`; read-only)

The repo report (`scratchpad/repo-discovery.md`, 292 PROVED / 28 INFERRED / 9
UNKNOWN tags) was reconciled against the host observations above. Items that
change the migration are listed; the rest agree.

### 14.1 Host facts the repo confirms or contradicts

| Topic | Repo says | Host shows | Resolution |
|---|---|---|---|
| PostgreSQL major | `00_PROJECT_STATE.md:14` "16"; ADR-0011:80 "18" | **18.6** (PROVED `SELECT version()`) | 18.6. PROJECT_STATE is stale. |
| `:8443` reachability | `secure_8443.sh` "PROPOSAL — NOT YET APPLIED"; ADR-0011:80 "blocked by ufw" | unreachable from devloop-01; ufw has no 8443 rule (PROVED) | Blocked. Repo UNKNOWN #5 resolved. |
| `DEPLOYED_SHA` present | ADR-0011:81 "absent 2026-09-02" | present, payload `346076b` (PROVED this session) | A real ADR-0010 deploy has run since the ADR. Repo UNKNOWN #4 resolved. |
| Mission ledger backend | default `file` (`timeline.py:50-53`); production value UNKNOWN | `QEVIK_LEDGER` set in `atlas.env`; journal "watching the postgres ledger" | **postgres** (PROVED). |
| `credentials.jsonl` mode | ADR-0011:82 "0644 world-readable" | `-rw-r--r--` (PROVED `ls`) | Confirmed finding; tighten on target. |
| `cloudflare.env` / API token | `cloudflare_token.md`: "NOT YET CREATED" (2026-08-19) | file absent (OBSERVED) | Consistent: **no Cloudflare API automation exists**; every DNS/origin change is a manual Cloudflare-dashboard action by the owner. |
| `/etc/caddy/sites.d` | only the abandoned `qevik-sites.Caddyfile` imports it | directory exists, empty (PROVED) | Dead layout; not part of the target. |
| ufw | bootstrap opens 22 only; later docs 22/80/443 | 22/80/443 v4+v6 (PROVED) | bootstrap script is stale. |
| Uptime/reboot | ADR-0011: 15 d uptime, reboot pending, 54 upgradable | reboot pending still (PROVED `/var/run/reboot-required`) | **Reboot survival of the full unit set has never been exercised** (PROJECT_STATE:74-76). Risk R-14. |

### 14.2 Facts only the repo could supply (all PROVED at the cited lines)

1. **The origin IP `2.28.62.83` is a literal in ≥ 12 repo files:** `infra/deploy_control.sh:67`, `deploy_console.sh:21`, `devloop/boundary.py:32`, `devloop/gates.py:413-537` (×3), `devloop/inspection.py:32`, `atlas_kernel/infra/cloudflare.py:41` (`ORIGIN_IP`, and `check_writable` refuses any other A-record content), `cloudflare_token.md`, `secure_8443.sh`, `qevik-sites.Caddyfile` (`default_sni`), `qevik-production.Caddyfile:230` (`https://2.28.62.83:8443`), `qevik-control.Caddyfile`. A new production host requires a **code change** in the repo before the deploy tooling and the Cloudflare helper can target it — that is implementation work and is **not** performed in Phase 0.
2. **Deploy = `infra/deploy_control.sh` (ADR-0010)**: refuses unless on clean `main`; `git archive` of `QEVIK_DEPLOY_SHA`; ships only `packages/kernel/atlas_kernel/`, `infra/`, `apps/control/src/`; rsync kernel `--delete`, infra without `--delete`; runs `init_db()`; installs `infra/qevik-*.service`; writes `DEPLOYED_MANIFEST` (per-file sha256) and `DEPLOYED_SHA`; restarts and fingerprints the five workers via `atlas_workers.version`. It does **not** install `qevik-jobs.slice`, `resources.conf`, or the Caddyfile (`deploy_console.sh:104-110` installs the Caddyfile and `restart`s Caddy; `recover_qevik_server.sh` installs slice + drop-in).
3. **`infra/bootstrap_qevik_server.sh` (2026-08-17) installs only `qevik-api`** and opens only port 22. It is not a provisioning script for the current unit set; Phase 2/4 must not rely on it as-is.
4. **`infra/enable_domain.sh` is incompatible with production Caddy** (`caddy reload` needs the admin API; production has `admin off`). Not usable on the target.
5. **Schema management is `init_db()` on every boot** — raw `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` / `DO $$` renames (`db.py`), no migration tool, no down-migrations. Restoring a dump into an *older* kernel is not covered by anything. The deployed SHA on the target must be ≥ the SHA that last wrote the source database.
6. **Startup coupling:** only `qevik-api` has `Requires=postgresql.service`; control and workers `After=` only, and with `QEVIK_REQUIRE_ATOMIC_CLAIMS` set they die at start if Postgres is unreachable (`mission_worker.py:393-429`) and rely on `Restart=on-failure` (15 s, burst 5/300 s) to recover.
7. **No Hetzner Cloud API usage anywhere in the repo**; no `HETZNER_*`, `TELEGRAM_*`, `GITHUB_TOKEN`, `SENTRY_*` env names in non-test code.
8. **SMTP:** `outreach/channels.py:252-259` needs all of `QEVIK_SMTP_HOST/PORT/USER/PASSWORD/FROM` or the channel refuses; none is set on the host; `70_EMAIL_INFRASTRUCTURE.md` records no MX/SPF/DKIM/DMARC and recommends Google Workspace. **Mail is not configured and has never been proven to send from this host.**
9. **Google Places key is IP-restricted to `2.28.62.83`** and documented as once exposed in a screenshot with rotation open (`00_PROJECT_STATE.md:36, 390-391`). The restriction must be changed (or the key rotated) for the new origin — owner action.
10. **Brave key** documented as "approved, not yet supplied" (`00_PROJECT_STATE.md:388`) while `brave.env` exists on host with `QEVIK_BRAVE_API_KEY` — doc stale or key present: value not read; treat as present (env file PROVED).
11. **`playwright` is not a declared dependency**; `pip install -e .[dev]` will not install it. Chromium 1234 lives in `/opt/qevik/ms-playwright`.
12. **Atlas asset bytes** are written to `$TMPDIR/atlas-assets` under `PrivateTmp=true` — ephemeral by construction (`composition_root.py:116`, `storage.py:32`).
13. **Health endpoints:** `/health` on 8080 and 8081 (liveness, no DB), `/api/health` on 8081 (posture: missions durable, vault sealed, research configured, claiming mode), `/health/report`, `/diagnostics*`, `/recovery/report` on 8080. These are the validation probes for Phases 7 and 9.
14. **Repo docs that are stale for migration purposes:** `41_CLOUD.md`, `42_DATABASE.md`, `43_SECURITY.md` (early placeholders), `docs/DEPLOYMENT.md` (Atlas desktop product, :8000, PG16), `00_PROJECT_STATE.md` §host (PG16, ufw 22-only, "one script bootstrap"). ADR-0011 §3 is the most recent documented baseline and agrees with this inventory.
