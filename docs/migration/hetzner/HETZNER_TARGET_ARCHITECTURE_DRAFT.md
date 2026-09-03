# HETZNER_TARGET_ARCHITECTURE_DRAFT

Phase 0 deliverable 6. A **draft** for the Phase 1 owner decision. Every
statement is one of:

- **PROVED REQUIREMENT** — follows from evidence in the inventories; the target cannot work without it.
- **RECOMMENDATION** — the author's proposal; the owner may reject it.
- **ASSUMPTION — OWNER CONFIRMATION REQUIRED** — cannot be settled by evidence available in Phase 0.

Nothing here is provisioned. Hetzner product names, sizes and prices are
**not verified in this session** (no Hetzner console/API access was used) and
must be checked by the owner in the console before Phase 2.

## 1. Topology

```
                     Cloudflare (unchanged: authoritative DNS + proxy for qevik.ai)
                                           │  origin = NEW production IP (cutover lever)
                                           ▼
   ┌──────────────── qevik-prod-01 (NEW Hetzner Cloud server, same region nbg1 or fsn1) ─────────────┐
   │  Caddy 2.x  :80 :443           LE certs (copied or re-issued)                                    │
   │  qevik-api :8080 · qevik-control :8081 · 5 × mission workers · backup + market-scan timers        │
   │  PostgreSQL 18.x (local, loopback)                                                                │
   │  /opt/qevik (app, env)  /var/lib/qevik (state)  /srv/sites (published)  /opt/qevik/backups        │
   │  [RECOMMENDED] Hetzner Volume or Storage Box mount for off-host backup copies                    │
   └───────────────────────────────────────────────────────────────────────────────────────────────────┘

   qevik-core-01   (2.28.62.83)  — CURRENT production; untouched until Phase 11; rollback target.
   qevik-devloop-01 (91.107.244.253) — DevLoop executor only (ADR-0011 / DQ-011). NOT production.
                                       Used in this plan purely as a second vantage point.
   Operator Mac    — deploy origin (ADR-0010), DevLoop driver, Cloudflare/Hetzner consoles.
```

**PROVED REQUIREMENTS**
- A single-host topology reproduces what exists (one Caddy, two uvicorn apps, five workers, one local Postgres, three file trees). Splitting DB or workers onto other hosts changes the deploy contract, unit files and loopback assumptions (`127.0.0.1:5432`, `127.0.0.1:808x`) and is **not** required by any evidence.
- Cloudflare stays authoritative and proxied; the public hostnames do not change; the cutover is an origin-IP change on four records.
- `qevik-devloop-01` carries no production workload (spec).

**RECOMMENDATION**
- Keep single-host for the migration (like-for-like), then treat any split as a later ADR. Migrating and re-architecting at once doubles the unknowns.

## 2. Sizing

| | Old host (PROVED) | Minimum viable (RECOMMENDATION) | Recommended (RECOMMENDATION) |
|---|---|---|---|
| vCPU | 4 (AMD EPYC Genoa, shared) | 4 | 4–8 |
| RAM | 7.6 GiB, no swap; 1.7 GiB used + 4.5 GiB cache (single sample) | 8 GiB | 16 GiB (headroom for 2 Chromium + uncapped workers + PG cache) |
| Disk | 150 GB, 12 GB used | 80 GB | 160 GB (journald, backups, evidence growth; matches old host) |
| Swap | none | 2 GB (RECOMMENDATION — avoids OOM kills of uncapped workers) | 2–4 GB |
| Region | nbg1-dc3 | any EU | nbg1 or fsn1 (latency to Cloudflare EU irrelevant; same legal region) |

ASSUMPTION — OWNER CONFIRMATION REQUIRED: peak usage is UNKNOWN (no metrics history). If the owner expects more concurrent missions or browsers than today, size up; the plan does not assume growth.

ADR-0011 chose CX53-class for DevLoop; the production server does **not** have to match it. Type/price to be read from the Hetzner console by the owner (ASSUMPTION).

## 3. Storage layout

**PROVED REQUIREMENT** (paths are baked into unit files, Caddyfile and code): `/opt/qevik/atlas` (+ `.venv`), `/opt/qevik/*.env`, `/opt/qevik/ms-playwright`, `/opt/qevik/backups`, `/opt/qevik/market`, `/var/lib/qevik/{control,scratch,worktrees,jobs,evidence,prospects,outreach,audits,briefs,workspaces}`, `/srv/qevik-public`, `/srv/qevik-control`, `/srv/sites`, `/etc/caddy/Caddyfile`, `/var/lib/caddy`, `/var/lib/postgresql/18/main`. Same paths on the target; do not relocate.

**RECOMMENDATION**
- Root volume holds everything (as today). Add **one** of: a Hetzner Volume mounted at `/mnt/backup`, or a Hetzner Storage Box via rclone/sftp, and extend `qevik_backup.sh` (or a second unit) to copy each verified dump plus a tar of `/var/lib/qevik/control`, `/srv/sites`, and env-file **names** (never values) off the root disk. This closes F-6.
- Ownership: `qevik:qevik` for app state and sites (as today); env files root 0600 or qevik 0600 exactly as the unit's `User=` requires (today `atlas.env` is root 0600 and readable by the units via `EnvironmentFile=` — keep).

## 4. Database placement

**PROVED REQUIREMENT**: PostgreSQL ≥ 18 (source is 18.6; `pg_dump -Fc` from 18.6), local, loopback, role and database `qevik`, `scram-sha-256` (PROVED `pg_hba`), `max_connections ≥ 100` (13 backends observed; 26/100 per ADR-0011).

**RECOMMENDATION**: local Postgres on the same host (like-for-like); `shared_buffers` 512 MB–1 GB on a 16 GiB host; keep `qevik_test` **off** the production host unless the owner says it is used (D2 UNKNOWN).

**Not recommended now**: Hetzner managed DB or a separate DB host — no evidence of need; changes `ATLAS_DATABASE_URL` network path and the atomic-claims assumptions.

## 5. Backup and restore model

**PROVED REQUIREMENT**: keep `qevik-backup.timer` (03:30 UTC daily, `pg_dump -Fc`, restore-verified into a throwaway DB, keep 14). It is the only proven backup mechanism.

**RECOMMENDATION**
1. Off-host copy of every verified dump (see §3).
2. Add the non-Postgres state (`/var/lib/qevik/control`, `/srv/sites`, `/var/lib/qevik/evidence`) to a daily tar with a manifest.
3. Enable the Hetzner server backup add-on (image-level, 7 rotations) for the production server — the cheapest whole-box rollback. ASSUMPTION: available and acceptable in cost.
4. A failure of the backup unit must be **visible**: at minimum `OnFailure=` to a unit that writes a marker checked by `/api/health`, or the Telegram health push proposed in ADR-0011 §5. Which one is a product decision (ASSUMPTION).

## 6. Network and security

**PROVED REQUIREMENT**: inbound 80/443 from Cloudflare (HTTP-01 needs :80 reachable through Cloudflare); inbound 22 for the operator; outbound HTTPS to the endpoints in secret inventory N8; Caddy `trusted_proxies` list stays the Cloudflare ranges.

**RECOMMENDATION**
- Hetzner Cloud Firewall in front of the server: 22 from owner IP(s) only (or from `qevik-devloop-01` as a jump — ASSUMPTION), 80/443 from Cloudflare IP ranges only (removes the origin-IP exposure that `cloudflare_status.py` warns about), everything else denied; ufw kept as a second layer with the same rules.
- sshd: `PasswordAuthentication no`, `PermitRootLogin prohibit-password` (already), key-only, dedicated production key (O2). fail2ban optional if the cloud firewall restricts 22.
- Drop the `:8443 tls internal` block from the target Caddyfile (it is unreachable today and its IP is hard-coded) **or** keep it and open 8443 only from owner IPs — owner decision (R-20).
- `credentials.jsonl` 0600; no DSNs on argv; `QEVIK_ALLOW_PRODUCTION_DB_IN_TESTS` never set.
- unattended-upgrades on (as today); plan a maintenance reboot cadence since the reboot-required state was never acted on.

## 7. DevLoop / Production separation

**PROVED REQUIREMENT** (spec + ADR-0011): production and DevLoop are separate servers. DevLoop's executor host provisioning (DQ-011 Phase 0) is **not part of this plan**.

**RECOMMENDATION**: after cutover, the DevLoop deploy gates (`infra/devloop/gates.py`, `boundary.py`, `inspection.py`) must point at the new production host — that is the same repo change as R-12 and lands under owner review in Phase 4; DevLoop stays paused until the owner un-pauses it.

## 8. Service account model

**PROVED REQUIREMENT**: system users `qevik` (uid 1000 today; uid parity not required but `/srv/sites` and `/var/lib/qevik` are `qevik:qevik` so the user must exist **before** rsync with `--chown=qevik:qevik`), `postgres`, `caddy`; root for sshd/deploy (ADR-0010 deploys as `root@` and `chown -R qevik:qevik` after rsync — `deploy_control.sh:772`).

**RECOMMENDATION**: keep root-over-SSH for deploys (changing it changes ADR-0010); no additional human accounts; the Postgres `qevik` role with a **new** password; a separate read-only Postgres role for hand queries so the DSN never needs to be typed on a command line (ASSUMPTION: owner wants hand access).

## 9. Deployment model on the target

**PROVED REQUIREMENT**: ADR-0010 immutable payload deploy from the operator Mac (`deploy_control.sh`) remains the only sanctioned way to put application code on a host; `DEPLOYED_SHA`/`DEPLOYED_MANIFEST` provenance; five-worker fingerprint check.

**RECOMMENDATION**
1. Phase 4 creates the target's base layout by a **reviewed provisioning checklist** derived from the union of `bootstrap_qevik_server.sh` + `recover_qevik_server.sh` + `deploy_console.sh` (Caddy) + `resources.conf`/`qevik-jobs.slice` — because no single script provisions the current unit set (R-15). Turning that checklist into an updated `bootstrap_qevik_server.sh` is implementation work and needs owner approval.
2. First application deploy to the target = `deploy_control.sh` with `TARGET=root@<new-ip>` and `QEVIK_DEPLOY_SHA` = the SHA currently deployed on the old host (`346076b` or the SHA of a reviewed later `main` that includes the R-12 change). Run `--rehearse` first.
3. Console and public site via `deploy_console.sh`/`deploy_public.sh` with the same `TARGET` mechanism (requires the R-12 repo change; today `deploy_console.sh:21` hard-codes the IP).

## 10. Items requiring owner confirmation before Phase 2 (summary)

| # | Decision | Default if the owner says "your call" |
|---|---|---|
| T1 | Server type / region / disk / backups add-on | 4 vCPU / 16 GiB / 160 GB / nbg1 / backups on — after reading the console |
| T2 | Off-host backup target (Volume vs Storage Box vs none) | Storage Box + rclone (smallest blast radius) — but "none" is a regression to keep only if the owner explicitly accepts it |
| T3 | Cloud Firewall restricting 22 and 80/443 | yes |
| T4 | Fate of `:8443` door | remove from Caddyfile |
| T5 | LE certs copy vs re-issue | copy (`/var/lib/caddy`), re-issue happens naturally at renewal |
| T6 | Dedicated SSH key for production | yes |
| T7 | Swap | 2 GB |
| T8 | `qevik_test` on target | no, unless the owner names a user |
| T9 | Backup failure visibility mechanism | `OnFailure=` marker + `/api/health` component (no new external dependency) |
| T10 | Retarget strategy for the hard-coded IP (parameterise vs replace) | parameterise via existing `TARGET`/env, one default constant per file |

Nothing in this table is decided by this document. DQ-009 applies: the agent
does not choose on the owner's behalf; defaults are listed only so that "your
call" has a defined meaning.
