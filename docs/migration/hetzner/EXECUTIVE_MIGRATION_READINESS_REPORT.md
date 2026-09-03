# EXECUTIVE_MIGRATION_READINESS_REPORT

> **Owner review:** the consolidated decision package is `OWNER_DECISION_AND_FINAL_ARCHITECTURE.md` (design review, supersedes §5 here for decision wording).

**Mission:** Phase Hetzner / Infrastructure Migration — Phase 0 (Discovery & Evidence Freeze).
**Date:** 2026-09-03. **Repo:** `~/atlas` @ `6ad8a98` (docs added in this directory only).
**State of the world after this report:** nothing provisioned, nothing migrated, nothing changed on any host, no DNS touched, no task enqueued, DevLoop still paused.

## 1. Verdict

**Phase 0 is complete. The migration is plannable and low-volume, but it is NOT ready to execute** until the owner makes the decisions listed in §5 and supplies the inputs in §6. The blocking items are decisions and credentials, not technical unknowns: the data set to move is ≈ 0.8 GB, the cutover lever is a single manual Cloudflare origin change on four records, and the old host stays intact as the rollback path until an owner-approved decommission.

Readiness by area:

| Area | Status | Why |
|---|---|---|
| Understanding of current production | **READY** — PROVED from host + repo + second vantage | 3 inventories + service graph; 14 cross-checked contradictions resolved |
| Data set and integrity method | **READY** — every source classified | 0.8 GB MIGRATE; 8 UNKNOWNs need owner answers, none technical |
| Secrets | **BLOCKED on owner** | 7 host secrets (names only) must be re-entered/rotated by the owner on the target; none may transit the agent |
| Target design | **DRAFT — 10 owner decisions (T1–T10)** | like-for-like single host recommended |
| Provisioning tooling | **GAP** | no script provisions the current unit set; hard-coded origin IP in ≥ 12 repo files needs a reviewed code change before deploy tooling can target a new host |
| Cutover / rollback | **PLANNED, not rehearsed** | Phases 8–9 define rehearsal on a test hostname; Cloudflare access is the owner's |
| Monitoring / backups | **REGRESSION RISK if copied as-is** | local-only backups, no alerting; target design adds off-host copy + failure visibility (owner decisions T2/T9) |

## 2. What was proved (highlights)

- One Hetzner host `qevik-core-01` (2.28.62.83, nbg1-dc3, 4 vCPU / 7.6 GiB / 150 GB, Ubuntu 26.04, PG 18.6, Caddy 2.11.4, Python 3.14.4) runs everything: Caddy, `qevik-api` :8080, `qevik-control` :8081, five mission workers, daily backup and market-scan timers, local Postgres. Load is light (1.7 GiB used, load 0.25).
- Cloudflare is authoritative DNS and proxy for `qevik.ai`, `www`, `app`, `sites` (verified from the host via 1.1.1.1 and from `qevik-devloop-01`). No `api`/`webhook`/`mail` records; no MX/SPF/DMARC. The Mac's resolver is unreliable (VPN fake IPs) and was excluded as evidence.
- Emergency door `:8443` is **unreachable** (ufw); documentation calling it "the way back in" is wrong. Only SSH is an origin-direct admin path.
- ADR-0010 deploy is in force: `DEPLOYED_SHA` = `346076b`, `DEPLOYED_MANIFEST` present, four rollback dirs. The host `.git` checkout is dirty (43 modified / 260 untracked) and is **not** authoritative.
- Mission ledger is Postgres (`QEVIK_LEDGER` set; journal "watching the postgres ledger"); `missions.jsonl` is a frozen archive since 2026-08-27.
- Backups: `pg_dump -Fc` daily, restore-verified, last VERIFIED 2026-09-02 03:34, retained locally only. Nothing backs up `/var/lib/qevik/control` (vault, credential records), `/srv/sites`, evidence, or env files.
- No monitoring/alerting exists anywhere (host or code). No SMTP is configured anywhere; mail has never been proven to send.
- `qevik-devloop-01` (91.107.244.253) is bare (no Qevik files, no PG, no Caddy) and reachable; it served as the second vantage point and remains DevLoop-only.
- Security findings: DSN visible in `ps` argv of stale root processes; `credentials.jsonl` world-readable; password SSH enabled, fail2ban inactive; SSH key shared with Naml's host; Google Places key IP-pinned to the old host and previously exposed.

## 3. Deliverables

| # | File | Size |
|---|---|---|
| 1 | `CURRENT_INFRASTRUCTURE_INVENTORY.md` (14 sections incl. repo cross-check) | ~31 KB |
| 2 | `DATA_AND_STATE_INVENTORY.md` (D1–D6, S1–S11, W1–W3, A1–A10, B1–B2, P1–P3, Y1–Y6) | ~14 KB |
| 3 | `SECRET_AND_DEPENDENCY_INVENTORY.md` (K1–K13, M1–M7, N1–N11, O1–O12; names only) | ~14 KB |
| 4 | `CURRENT_PRODUCTION_SERVICE_GRAPH.md` | ~10 KB |
| 5 | `MIGRATION_RISK_REGISTER.md` (R-01–R-26, F-1–F-7) | ~14 KB |
| 6 | `HETZNER_TARGET_ARCHITECTURE_DRAFT.md` (T1–T10 decisions) | ~11 KB |
| 7 | `MASTER_MIGRATION_PLAN.md` (Phases 0–11, STOP before 9, V1–V14 checklist) | ~26 KB |
| 8 | this report | — |

Raw evidence captures (`prod-*.txt`, `devloop01.txt`, `dns.txt`, `repo-discovery.md`) are kept in the session scratchpad, **not** in the repo, because some lines contain redacted process argv. All eight deliverables were grep-checked for DSN/password patterns: none present.

## 4. All UNKNOWN items (must remain UNKNOWN until evidence)

| # | Item | Resolves in | Who |
|---|---|---|---|
| U1 | Hetzner project, Cloud Firewall, snapshot/backup add-on state for vServer 162146484, API token ownership | Phase 1 | owner (console) |
| U2 | Cloudflare zone settings: SSL mode (Full/strict is INFERRED), WAF, cache/page/origin rules, any non-public records; whether an API token exists today | Phase 1 | owner (dashboard) |
| U3 | Any external uptime/alerting outside the host | Phase 1 | owner |
| U4 | Playwright install method and pip version on the host | Phase 4 (read-only `pip show`) | agent |
| U5 | Purpose/users of `qevik_test` DB (65 MB) | Phase 1/5 | owner |
| U6 | Content of the 7 err / 21 warn journal lines per worker unit (last 7 d) | Phase 5 (read-only) | agent |
| U7 | Relationship of legacy Caddyfiles (3 in `/opt/qevik`, 5 `/etc/caddy/Caddyfile.*`) to the live config | Phase 5 | agent + owner |
| U8 | Peak resource usage (no metrics history) | never fully; Phase 10 observes the target | — |
| U9 | Whether the credential vault (`vault.json`, 2 B) ever held real credentials; keep or regenerate master key | Phase 1 | owner |
| U10 | `QEVIK_REPORTS_STORE` value (file vs postgres) | Phase 5 (owner reads value) | owner |
| U11 | Whether hand-copied `/opt/qevik/*.py`/`*.sh` scripts, `S6` scratch, `S11` ad-hoc dumps are still wanted | Phase 1 | owner |
| U12 | Origin/necessity of `atlas_quarantined_fixtures` table (not created by repo code) | Phase 5 | owner |
| U13 | Whether **all** `/control/*` routes on 8080 are auth-gated (product finding, not migration) | out of scope | product |
| U14 | Whether on-host git access (`qevik` deploy key) is still used by any hand workflow | Phase 1 | owner |
| U15 | Exact public table count (75 listed; earlier note of 78 not reproducible from capture) | Phase 5 | agent |

## 5. Owner decisions required (nothing proceeds without them)

| # | Decision | Where documented |
|---|---|---|
| D-A | Approve Phase 0 deliverables and authorise Phase 1 | this report |
| D-B | Target sizing/region/disk/backup add-on (T1), swap (T7) | Architecture §2, §10 |
| D-C | Off-host backup mechanism (T2) and backup-failure visibility (T9) | Architecture §5 |
| D-D | Cloud Firewall on 22/80/443 (T3); fate of `:8443` (T4) | Architecture §6 |
| D-E | LE certs copy vs re-issue (T5) | Architecture §10; secret inventory K9 |
| D-F | Dedicated production SSH key (T6) | secret inventory O2 |
| D-G | `qevik_test` on target (T8) | data inventory D2 |
| D-H | Retarget strategy for the hard-coded IP (T10) — a **code change under review**, owner-pushed | inventory §14.2.1; risk R-12 |
| D-I | Data UNKNOWN classifications: S1 vault key, S6 scratch, S11 dumps, A6 scripts, D6 heartbeat history | data inventory §9 |
| D-J | Rotate vs re-enter each provider key (DashScope, Brave; Places must rotate) | secret inventory K5–K7 |
| D-K | Admin account policy: migrate `qevik_users` rows vs re-bootstrap | secret inventory K4/O7 |
| D-L | **Go for Phase 2 provisioning** (first cost-incurring action) | plan Phase 2 |
| D-M | **Go for Phase 9 cutover** with a named window (after Phase 8 runbook) | plan STOP section |
| D-N | **Go for Phase 11 decommission** | plan Phase 11 |
| D-O | SMTP/mail: explicitly out of scope unless the owner opens it as a new capability | secret inventory O11 |

## 6. OWNER_INPUT_REQUIRED (credentials/access — never via chat, docs, git, or tasks)

See `SECRET_AND_DEPENDENCY_INVENTORY.md` §4, O1–O12. In one line each: Hetzner console access; new production SSH key; new DB password on target; vault master key (keep/regenerate); DashScope + Brave keys; new IP-restricted Places key; admin password policy; Cloudflare dashboard at cutover/rollback; cert decision; push of the retarget commit; (mail — out of scope); answers to the classification questions.

## 7. Top risks (from the register)

1. **R-12 hard-coded origin IP** — certain; blocks deploy tooling until fixed under review.
2. **R-11 Places key IP-pinned** — certain failure on the target unless rotated.
3. **R-08/R-09 cutover lever + origin TLS** — manual, single path; mitigated by rehearsal on a test hostname and copying certs.
4. **R-14 reboot survival never exercised** — target must pass a reboot test before cutover.
5. **R-15/R-16 provisioning + dependency drift** — no complete provisioning script, no lock file, playwright undeclared.
6. **R-19/F-1..F-5 security posture** — must not be replicated; rotation is part of the plan.
7. **R-24 premature decommission** — gated by 7 clean days and an owner go.

## 8. Internal consistency check (performed)

- Every R-, F-, T-, O-, K-, U-, D-, V- identifier referenced across the seven documents resolves to a defined row (checked by grep).
- Table count reconciled to the captured listing (75) — the earlier "78" was corrected in three files and flagged as U15.
- Ledger backend (S3) upgraded from INFERRED to PROVED after the repo cross-check; reports store (S4) stays INFERRED/U10.
- `qevik-jobs.slice` and `resources.conf` found to be **outside** the ADR-0010 payload install path → added to Phase 4 as explicit steps (Y1).
- Playwright/asset-bytes/lock-file facts from the repo added as A2/A3/A9/A10 and R-06/R-16.
- No document states a Hetzner product name, price, or Cloudflare setting as fact; all are marked ASSUMPTION/UNKNOWN.

## 9. Stop

Per the mission's STOP CONDITION: Phase 0 deliverables are complete; UNKNOWNs and owner decisions are enumerated above. **No provisioning, no migration, no production change, no DNS change, no task enqueued.** Waiting for owner review.
