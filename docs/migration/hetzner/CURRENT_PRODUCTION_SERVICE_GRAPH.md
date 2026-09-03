# CURRENT_PRODUCTION_SERVICE_GRAPH

Phase 0 deliverable 4. Evidence-supported only; every edge carries its tag
(PROVED / OBSERVED / INFERRED / UNKNOWN). Evidence files are those listed in
`CURRENT_INFRASTRUCTURE_INVENTORY.md`.

## 1. Request path (Internet → data)

```
                     Internet clients / crawlers
                               │
                               ▼
      ┌──────────────── Cloudflare (authoritative DNS + proxy) ─────────────┐
      │  zone qevik.ai  NS elliot/perla.ns.cloudflare.com           PROVED  │
      │  A/AAAA qevik.ai · www · app · sites → CF anycast (proxied)  PROVED  │
      │  client TLS terminated at edge (cf-ray, server: cloudflare)  PROVED  │
      │  origin dial: https://2.28.62.83:443 with SNI (Full/strict) INFERRED │
      │  WAF / cache / SSL-mode settings                             UNKNOWN │
      └──────────────────────────────┬──────────────────────────────────────┘
                                     │ 80/443 (ufw allows; 8443 blocked)  PROVED
                                     ▼
  ┌───────────────────── qevik-core-01  2.28.62.83  (Hetzner nbg1-dc3) ─────────────────────┐
  │                                                                                          │
  │  Caddy 2.11.4  (:80 :443 :8443)   LE HTTP-01 certs for 4 names          PROVED          │
  │   ├─ qevik.ai        → file_server /srv/qevik-public                    PROVED          │
  │   ├─ www.qevik.ai    → 301 https://qevik.ai                             PROVED          │
  │   ├─ sites.qevik.ai  → file_server /srv/sites/{slug}/current/…          PROVED          │
  │   ├─ :80 (bare IP)   → same as sites (X-Qevik-Host: sites-origin)       PROVED          │
  │   ├─ :8443 (bare IP) → same as app (tls internal)  — unreachable (ufw)  PROVED          │
  │   └─ app.qevik.ai                                                       PROVED          │
  │        ├─ /api/* /auth/* /health → 127.0.0.1:8081  qevik-control                       │
  │        ├─ /control/*             → 127.0.0.1:8080  qevik-api                           │
  │        └─ /*                     → file_server /srv/qevik-control (console SPA)        │
  │                                                                                          │
  │  qevik-api      uvicorn atlas_kernel.api:app                :8080  (user qevik) PROVED  │
  │  qevik-control  uvicorn atlas_kernel.qevik.app (workers=1)  :8081  (user qevik) PROVED  │
  │        │ ATLAS_DATABASE_URL / QEVIK_CLAIMS_DSN                                          │
  │        ▼                                                                                 │
  │  PostgreSQL 18.6  127.0.0.1:5432  db qevik (418 MB, 75 tables)              PROVED       │
  │        ▲                                                                                 │
  │        │ "watching the postgres ledger for tenant-qevik" (journal)          PROVED       │
  │  5 × infra/mission_worker.py (systemd, user qevik, --interval 10)           PROVED       │
  │     worker-1(self-check) · research · delivery · publish · healthcheck                   │
  │        │ writes /var/lib/qevik/{scratch,worktrees,control/reports,evidence?}  PROVED*    │
  │        │ publish worker → /srv/sites (QEVIK_SITES_ROOT)                     PROVED       │
  │        │                                                                                 │
  │  timers: qevik-backup 03:30Z (pg_dump→/opt/qevik/backups, restore-verified) PROVED       │
  │          qevik-market-scan 06:00Z (Google Places → /opt/qevik/market)        PROVED       │
  │  stale root processes: verify_recurrence.py ×2 + 7 watcher loops            PROVED       │
  └──────────────────────────────────────────────────────────────────────────────────────────┘
                 │ outbound (allow all)                       PROVED (ufw policy)
                 ▼
   External services (from env-file NAMES and unit files; no live socket seen)
   ├─ DashScope LLM API      (QEVIK_DASHSCOPE_API_KEY/_BASE_URL in atlas.env → api, control, workers)  PROVED(config)
   ├─ Brave Search API       (QEVIK_BRAVE_API_KEY in brave.env → qevik-api only)                        PROVED(config)
   ├─ Google Places API      (QEVIK_GOOGLE_PLACES_API_KEY in places.env → qevik-api, market-scan)       PROVED(config)
   ├─ Let's Encrypt ACME     (Caddy, HTTP-01 via Cloudflare :80)                                        PROVED
   ├─ Cloudflare API         (cloudflare.env referenced by qevik-api drop-in — FILE ABSENT)              OBSERVED absent
   ├─ GitHub                 (git remote of /opt/qevik/atlas; not used by any unit)                     PROVED(config)
   ├─ Ubuntu archive         (unattended-upgrades)                                                      PROVED
   └─ SMTP / mailbox         (code has QEVIK_SMTP_*; no env file sets them; no MX/SPF in DNS)           OBSERVED absent → UNKNOWN whether any mail is sent
```

`*` The workers' `ReadWritePaths=/var/lib/qevik` proves *permission* to write
those directories; which subdirectory each worker actually writes is INFERRED
from unit arguments (`--scratch`, `--worktrees`, `--reports`, `--state`) and
mtimes (newest `scratch/mission-…` 2026-09-02 05:00).

## 2. Control / operator path

```
  Operator Mac  ──ssh root@2.28.62.83 (key naml_hetzner)──▶  qevik-core-01        PROVED
        │  ADR-0010 deploy_control.sh: rsync payload → /opt/qevik/atlas,
        │  snapshot rollback*, install units, restart 7 units, probe /health,
        │  write DEPLOYED_SHA/DEPLOYED_MANIFEST                                     PROVED (this session)
        │
        └──ssh root@91.107.244.253 (key devloop_01)──▶  qevik-devloop-01 (bare)     PROVED

  Operator browser ──▶ https://app.qevik.ai ──▶ Caddy ──▶ :8081 /auth/* (login,
        QEVIK_ADMIN_PASSWORD) ──▶ :8081 /api/* (missions, approvals, credentials
        vault sealed with QEVIK_VAULT_MASTER_KEY)                                   PROVED(config) — auth mechanics INFERRED from env names

  Emergency door https://2.28.62.83:8443  ──▶  BLOCKED by ufw                       PROVED (second vantage)
```

## 3. Data-flow edges with classification

| # | From | To | Channel | Tag | Evidence |
|---|---|---|---|---|---|
| 1 | Cloudflare edge | Caddy :443 | HTTPS, SNI per hostname | PROVED (works end-to-end from devloop-01) | `devloop01.txt` |
| 2 | Caddy | qevik-control :8081 | HTTP loopback, paths `/api/* /auth/* /health` | PROVED | Caddyfile |
| 3 | Caddy | qevik-api :8080 | HTTP loopback, `/control/*` | PROVED | Caddyfile |
| 4 | qevik-api, qevik-control, 5 workers | PostgreSQL `qevik` | loopback 5432, scram; 13 backends | PROVED | `pg_stat_activity` backends, `ps` |
| 5 | workers | ledger (missions) | **Postgres** (log line "watching the postgres ledger"); `missions.jsonl` argument still passed but file last written 2026-08-27 | PROVED (postgres) / INFERRED (jsonl is legacy) | journal, mtime |
| 6 | workers | reports | `--reports /var/lib/qevik/control/reports` and `QEVIK_REPORTS_STORE` env; table `atlas_mission_reports` 17 MB/27 rows exists | INFERRED store = postgres with file dir as legacy | env name, table, `migrate_reports.py` |
| 7 | publish worker | `/srv/sites/{slug}/versions/…` + `current` symlink | filesystem | PROVED (unit `ReadWritePaths`, Caddy rewrite comment) | unit, Caddyfile |
| 8 | qevik-control | credential vault `/var/lib/qevik/control/vault.json` (2 B) + `credentials.jsonl` | filesystem, sealed with `QEVIK_VAULT_MASTER_KEY` | PROVED (paths from `credentials/location.py`; sizes from `ls`) | repo + host |
| 9 | qevik-backup | `/opt/qevik/backups/*.dump` | pg_dump over loopback, restore-verified | PROVED | journal 2026-09-02 |
| 10 | qevik-market-scan | Google Places → `/opt/qevik/market/latest.json` | HTTPS out | PROVED (journal "raw rows -> …latest.json") | journal |
| 11 | qevik-api | Brave / Places / DashScope | HTTPS out | PROVED(config) — live calls not observed | env files |
| 12 | qevik-api | Cloudflare API | HTTPS out | NOT CONFIGURED (env file absent) | `ls` |
| 13 | any service | SMTP | — | UNKNOWN (no config on host; code paths exist) | grep + env names |
| 14 | Caddy | Let's Encrypt | ACME HTTP-01 via Cloudflare-proxied :80 | PROVED (certs present, `disable_tlsalpn_challenge`) | cert dirs |
| 15 | root shell (stale) | PostgreSQL | DSN on argv | PROVED | `ps` (redacted) |
| 16 | backups | off-host | — | **NONE OBSERVED** | script head, no unit |
| 17 | host | monitoring/alerting | — | **NONE OBSERVED** | `pgrep`, unit list |

## 4. Single points of failure (INFERRED from the graph)

1. One host holds proxy, app, control plane, workers, database, served sites, backups. Loss of the disk loses everything including the backups.
2. Cloudflare zone is the only public entry; origin IP is not in DNS — a cutover is a Cloudflare origin change, which is fast but is also the only lever (no DNS TTL games needed; no alternative path if Cloudflare access is unavailable).
3. SSH key on the operator Mac is the only proven admin path (8443 door blocked).
4. No replication, no standby, no off-host backup, no metrics/alerts.
