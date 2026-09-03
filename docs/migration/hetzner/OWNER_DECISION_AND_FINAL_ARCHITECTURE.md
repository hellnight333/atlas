# OWNER_DECISION_AND_FINAL_ARCHITECTURE — Qevik production → `qevik-prod-01`

**The single owner-review document for the Hetzner production migration.**
Consolidates the eight Phase 0 deliverables in this directory, reviews the
draft architecture critically, and asks for the decisions that gate execution.

Status: **design review only.** Nothing provisioned, no Hetzner or Cloudflare
action, no data moved, no production change, no secret rotated, no DevLoop
task. Repo `~/atlas` main `ddfbbc1` + this document.

> **Decision record 2026-09-03 (owner):** D-A, D-B, D-C, D-D, D-F **APPROVED**; D-L **approved
> for Phase 1 only** (read-only console checks + non-destructive preparation; no provisioning or
> cost-incurring action). Five additional requirements AR-1…AR-5 are binding (see
> `evidence/phase-1/decisions.md`). Phase 1 outcome: `PHASE_1_COMPLETION_REPORT.md` — including a
> D-B re-confirmation item: the nbg1 product is named **CPX32** and Hetzner's 2026-06-15 price
> change (CPX32 ≈ €35.49/mo) makes CX43/CX33 cheaper *if orderable*; owner re-confirms the type at
> the Phase 2 gate. Sections below keep the original review text; status lines mark what is decided.

Evidence tags are inherited from the inventories (PROVED / OBSERVED /
INFERRED / UNKNOWN). Where this document *recommends*, it says so; where it
*assumes*, it says so. Hetzner product names and prices below are quoted from
memory of the public catalogue and are **NOT verified this session** — confirm
every one in the Hetzner console before ordering (U1).

---

## 1. Architecture summary — CURRENT vs TARGET

| Dimension | CURRENT `qevik-core-01` (PROVED) | TARGET `qevik-prod-01` (proposed) |
|---|---|---|
| Hosts | 1 Hetzner Cloud vServer, nbg1-dc3, 4 vCPU AMD / 7.6 GiB / 150 GB, no swap | 1 Hetzner Cloud server, nbg1, same class or one up, 2 GB swap. Still one host — by design (§3.1). |
| Edge | Cloudflare authoritative DNS + proxy on `qevik.ai`, `www`, `app`, `sites`; origin IP unpublished | Unchanged. Cutover = owner changes the origin on 4 records. |
| Proxy / TLS | Caddy 2.11.4, LE HTTP-01, `admin off`, Cloudflare `trusted_proxies`; `:8443` "emergency door" **blocked by ufw** | Caddy 2.x, same Caddyfile minus the `:8443` block; LE certs copied then renewed naturally. Emergency access = SSH + Hetzner console. |
| Application | `qevik-api` :8080, `qevik-control` :8081, 5 mission workers, 2 timers — all systemd, user `qevik`, ADR-0010 immutable deploy from the Mac | Identical unit set installed from the repo (including the two files `deploy_control.sh` does not install: `qevik-jobs.slice`, `resources.conf`). Same deploy contract, `TARGET` parameterised (R-12). |
| Database | PostgreSQL 18.6 local loopback, `qevik` 418 MB (75 tables), `qevik_test` 65 MB; no replication | PostgreSQL 18.x local loopback, `qevik` only, **new role password**, `shared_buffers` 512 MB. No managed DB, no replica. |
| State on disk | `/var/lib/qevik` 258 MB, `/srv/sites` 18 MB, `/srv/qevik-public`, `/srv/qevik-control` — backed up by nothing | Same paths (baked into units/Caddyfile/code). Included in the daily backup bundle (§3.5). |
| Backups | daily `pg_dump -Fc`, restore-verified, **local disk only**, 8-day silent-failure history | Same verified dump **plus** file-state tar, pushed off-host to a Hetzner Storage Box; Hetzner image backups on; failure visible in `/api/health`. |
| Security | root SSH key shared with Naml; `PasswordAuthentication yes`; fail2ban off; `credentials.jsonl` 0644; DB DSN on root argv; Places key IP-pinned + once exposed | Dedicated key; key-only sshd; Hetzner Cloud Firewall + ufw; 0600 state files; no DSN on argv; every old-host credential rotated (§9). |
| Monitoring | none (no agent, no external check, no alert) | Minimal: unit `OnFailure=` markers surfaced in `/api/health`; one external uptime check owned by the owner (§3.6). No Prometheus/Grafana. |
| Deploy origin | operator Mac (`deploy_control.sh`), hard-coded `2.28.62.83` in ≥ 12 files | operator Mac, `TARGET`/`ORIGIN_IP` parameterised — a reviewed code change the owner pushes (D-H). |
| DevLoop | paused; `qevik-devloop-01` bare, reserved | unchanged; devloop-01 stays a read-only vantage point. |
| Rollback | n/a | old host frozen-but-intact for a defined observation period (§7). |

Data to move: ≈ 0.8 GB (PROVED sizes). Transfer is seconds; the cutover
window is dominated by stop → final delta → verify → start → origin change.

---

## 2. Owner decisions — complete list, grouped by when they are needed

Format per decision: **what** · recommended · alternatives · consequences ·
**why**. "Default" is what "your call" means under DQ-009; nothing is decided
here.

### 2.1 MUST decide before provisioning (gate Phase 2)

**D-A — Approve Phase 0 and this design; authorise Phase 1 (read-only console checks).**  
*Status 2026-09-03: **APPROVED.***
- Recommended: approve, with any corrections to §4/§6 noted inline.
- Alternatives: reject and re-scope (e.g. migrate in place, or stay on the current host and only harden it).
- Consequences: approve → Phase 1 owner console reads (U1, U2) then Phase 2 gate. Harden-in-place → cheaper, no cutover, but keeps the pending-reboot/never-rebooted unknown, the shared key, and a host whose secrets are already exposed; rotation would then have to happen *on* production.
- Why: the target is small and the old host's posture is the reason to move; a fresh host is the cleanest way to rotate everything at once with a rollback path.

**D-B — Server size, region, disk (T1, T7).**  
*Status 2026-09-03: **APPROVED** (4 vCPU / 8 GB / ~160 GB + 2 GB swap, nbg1) subject to console confirmation of exact product name and price; no larger class without load evidence. Re-confirmation item at the Phase 2 gate: nbg1 name is CPX32 at ≈ €35.49/mo; CX43 (8/16/160, ≈ €15.99) or CX33 (4/8/80, ≈ €8.49) if orderable — see `PHASE_1_COMPLETION_REPORT.md` §6.*
- Recommended: **CPX31-class** (4 vCPU AMD, 8 GB, 160 GB NVMe) — INFERRED to be the same class as today (4 vCPU Genoa / 8 GB / 150 GiB ≈ 160 GB) — in **nbg1**, **+ 2 GB swap file**. Confirm type/price in console.
- Alternatives: (a) CPX41-class (8 vCPU / 16 GB / 240 GB) for headroom; (b) CX-line Intel shared; (c) fsn1/hel1.
- Consequences: CPX31 = like-for-like cost, proven sufficient (1.7 GiB used, load 0.25 — single sample, peak UNKNOWN U8); Hetzner allows a **reversible CPU/RAM-only upscale** later, so under-sizing is recoverable without reinstall. CPX41 ≈ 2× cost for headroom that no evidence requires. nbg1 keeps the same legal region as today and devloop-01, enabling a Hetzner private network later; other locations only matter if you want DC diversity from the old host (irrelevant after decommission).
- Why: SHIP_RULE — no capacity we cannot justify; the resize path is the expansion design.

**D-D — Firewall model and fate of `:8443` (T3, T4).**  
*Status 2026-09-03: **APPROVED** as recommended (22/80/443 only, no `:8443`, key-only SSH, origin-IP restriction deferred to D-Q).*
- Recommended: Hetzner **Cloud Firewall** as the authoritative layer (inbound 22 from anywhere, 80/443 from anywhere; all else denied; ICMP allowed) + ufw mirroring it; **remove the `:8443` block** from the Caddyfile. Tighten 80/443 to Cloudflare ranges only in Phase 10 (§3.3), not at cutover.
- Alternatives: (a) 22 restricted to owner IPs — **not recommended**: your egress IP is not stable (VPN/Iranian connectivity, see `feedback_verify_from_second_vantage_point`); a lockout is recovered only via the Hetzner web console. (b) Keep 8443 open to owner IPs — same lockout problem, plus the hard-coded IP. (c) Origin-lock 80/443 to Cloudflare ranges from day 1 — adds a cutover failure mode (526/521 on a range mistake) for a benefit that can be taken a week later.
- Consequences: recommended = simplest cutover, key-only SSH + fail2ban carries the brute-force load (~6.2k attempts/day today, all failing); origin exposure persists until Phase 10 (same as today).
- Why: safety of the cutover outranks hardening that can be staged.

**D-F — Dedicated production SSH key (T6, O2).**  
*Status 2026-09-03: **APPROVED**; `naml_hetzner` never authorised on the new host.*
- Recommended: yes — new ed25519 pair `qevik_prod` generated on the Mac; only its public key on the target; `naml_hetzner` **not** authorised there.
- Alternatives: reuse `naml_hetzner`.
- Consequences: reuse keeps one key covering Naml + Qevik + (if ever) devloop — one leak = every host. Dedicated key costs one `~/.ssh/config` entry and one `TARGET`-side change in ADR-0010 tooling (already needed for R-12).
- Why: F-4.

**D-C — Off-host backup destination and failure visibility (T2, T9).** *(Decide now so the Storage Box is ordered with the server; the implementation itself lands in Phase 4/10.)*  
*Status 2026-09-03: **APPROVED** (Storage Box sub-account = independent target; image backup add-on on; a Volume is never the only mechanism).*
- Recommended: **Hetzner Storage Box** (smallest tier) reached by SFTP/rsync with a **sub-account** whose credential lives only on the target (root 0600); + **Hetzner server backup add-on** (image-level, 7 rotations, +20 % of server price); + `OnFailure=` marker read by `/api/health`.
- Alternatives: (a) Hetzner Object Storage (S3) via rclone — fine, one more tool; (b) Hetzner Volume mounted at `/mnt/backup` — **not off-host** in the sense that matters (same project, same account, attached to the same server); (c) none — an explicit regression of F-6.
- Consequences: Storage Box = separate product, separate credential, its own snapshot feature (protects against overwrite of the copies), a few € / month. Backup add-on = fastest whole-box rollback for the *new* host. "None" leaves the only backups on the disk they protect.
- Why: F-6 is the one finding that can lose everything.

**D-L — GO for Phase 2 (first cost-incurring, owner-executed action).**  
*Status 2026-09-03: **APPROVED FOR PHASE 1 ONLY** — read-only checks and non-destructive preparation. Phase 2 GO still required; see `PHASE_1_COMPLETION_REPORT.md` §8 for the exact first cost-incurring actions.*
- Recommended: give it together with D-A–D-F once Phase 1 console reads are recorded.
- Alternatives: stage (order Storage Box first, server later).
- Consequences: Phase 2 creates the server and firewall in your console; deleting it is the rollback.

### 2.2 CAN decide during provisioning (gates inside Phases 3–8)

**D-H — Retarget strategy for the hard-coded `2.28.62.83` (T10, R-12, O10).** Needed before Phase 4.
- Recommended: **parameterise**, not swap: one constant per subsystem sourced from env (`QEVIK_PROD_HOST` / `QEVIK_ORIGIN_IP`) with the *old* IP as the default until cutover, then a second one-line change after cutover. Reviewed by you, pushed by you.
- Alternatives: (a) hard-swap the literal in all 12 files in one commit — rollback then needs another commit; (b) leave DevLoop gates pointing at the old host until DevLoop is un-paused.
- Consequences: parameterise = both hosts addressable during Phases 4–10 with no code churn; the DevLoop deploy gates (`gates.py`, `boundary.py`, `inspection.py`) follow the same variable.
- Why: rollback must not require a code change.

**D-E — LE certificates: copy vs re-issue (T5, O9, K9).** Needed in Phase 4.
- Recommended: **copy** `/var/lib/caddy` (account + 4 certs) root→root, chown `caddy`; Caddy renews on schedule after cutover.
- Alternatives: re-issue on the target via a temporary hostname pointed at it, or at cutover.
- Consequences: copy = zero cert gap, no LE rate-limit exposure on rollback (R-09), works under Cloudflare Full (strict) regardless of U2. Re-issue = cleaner but introduces a cutover-time dependency on HTTP-01 through Cloudflare.
- Why: R-09.

**D-J — Provider keys: rotate vs re-enter (K5 DashScope, K6 Brave, K7 Places; O5, O6).** Needed for Phase 3 env files.
- Recommended: **rotate all three** — new DashScope + Brave keys entered on the target; **new** Places key restricted to the target IP *and* to the Places API; old keys revoked at Phase 11 (Places old key: immediately after cutover).
- Alternatives: re-enter the same DashScope/Brave values (Places must rotate regardless — it is IP-pinned).
- Consequences: re-entering means the old host's exposed copies stay valid through decommission.
- Why: every credential that lived on the old host is treated as exposed (secret inventory §5.4).

**D-K — Operator accounts: migrate `qevik_users` rows vs re-bootstrap (K4, O7).** Needed in Phase 3.
- Recommended: migrate the rows with the DB (they come with the dump); set a **new** `QEVIK_ADMIN_PASSWORD` on the target anyway; rotate your login after cutover via `infra/rotate_admin.py`.
- Alternatives: re-bootstrap from an empty user table.
- Consequences: migrating keeps sessions/roles continuity (2 rows); re-bootstrap forces re-creation of any second operator.

**D-G — `qevik_test` on the target (T8, D2, U5).** Needed in Phase 5.
- Recommended: **do not migrate**; the test tooling recreates an empty DB when it needs one.
- Alternatives: migrate it (65 MB, no backends, no unit references it).
- Consequences: none known; if some hand workflow depends on its contents, it is in the Phase 11 archive.

**D-I — Data UNKNOWN classifications (data inventory §9): S1 vault key, S6 scratch, S11 ad-hoc dumps, A6 hand scripts, D6 heartbeat history.** Needed in Phase 5.
- Recommended: S1 **regenerate** the vault master key and start empty (2-byte vault; U9 — confirm nothing was ever sealed); S6 migrate (45 MB, audit continuity); S11 archive-only; A6 tarball archive, not installed; D6 migrate as-is (72 MB, no truncation — avoid touching data at migration time).
- Alternatives: keep the master key (needed only if the vault ever held a real credential); truncate heartbeats.
- Consequences: regenerating the key makes any sealed record unreadable — hence U9 must be answered first.

**D-M — GO for Phase 9 cutover with a named window (after the Phase 8 runbook).**
- Recommended: a weekday morning UTC, you online for ~60 min, Cloudflare + Hetzner consoles open, old-host snapshot taken in the preceding hours.
- Alternatives: none — this gate is mandatory.
- Consequences: expected downtime ≈ 10–15 min (stop + delta + verify + start + origin change); the site keeps serving static from the old Caddy during it.

**D-P — Monitoring minimum (new, from §3.6).** Needed in Phase 10; can be decided any time.
- Recommended: (1) `OnFailure=` marker for every `qevik-*` unit and both timers, surfaced by `/api/health`; (2) **one external uptime check** on `https://app.qevik.ai/health` and `https://qevik.ai/` from a free SaaS monitor that you own, alerting to your Telegram/email; (3) journald cap `SystemMaxUse=1G`.
- Alternatives: (a) a probe timer on `qevik-devloop-01` — **not recommended**: it is a production dependency on the DevLoop host, which the spec forbids; (b) Telegram health push from the app (ADR-0011 §5) — a product feature, later; (c) nothing.
- Consequences: (1)+(2) cost nothing, need one owner sign-up; without (2) a dead host is discovered by a customer.

### 2.3 CAN defer until after migration

**D-N — GO for Phase 11 decommission + observation period + old-host snapshot retention.**
- Recommended: observation period **14 days** (two backup cycles, two weekly patterns; the plan's "7 days" is the minimum); before deletion take a Hetzner snapshot of the old server and keep it **30 days**; then delete.
- Alternatives: 7 days; keep the old server running longer (costs the full server price per month).
- Consequences: see §7 for what rollback means at each point in the window.

**D-Q — Phase 10 hardening set (new, from §3).** After stabilisation: origin-lock 80/443 to Cloudflare ranges (or Authenticated Origin Pulls), `hidepid=invisible` on `/proc`, `UMask=0077` in units, read-only Postgres role for hand queries.
- Recommended: yes, each as its own small reviewed change after 14 clean days.
- Consequences: each is reversible and independent; none is needed for cutover.

**D-O — SMTP / mail: explicitly out of scope.**
- Recommended: leave out; nothing exists to migrate (PROVED). If wanted later it is a new capability (provider, SPF/DKIM/DMARC, `QEVIK_SMTP_*`).

---

## 3. Critical review of the draft target architecture

The draft (`HETZNER_TARGET_ARCHITECTURE_DRAFT.md`) is directionally right —
single host, like-for-like, Cloudflare unchanged. These are the corrections.

### 3.1 Overengineering / unnecessary complexity — removed or deferred
| Draft item | Verdict | Reason |
|---|---|---|
| Three backup mechanisms described separately (off-host copy, daily tar, backup add-on) plus a fourth visibility mechanism | **Collapse to one script + one add-on.** `qevik_backup.sh` grows one step: tar the file state and push dump + tar off-host; one unit, one `OnFailure=`. The image add-on is a console toggle, not a mechanism to operate. | Four moving parts on a one-person team means the failure nobody notices — exactly F-6. |
| 16 GiB "recommended" | **Not justified by evidence.** 8 GB + swap + resize path. | 1.7 GiB in use; workers ~105 MB each; Chromium capped at 2; jobs slice capped at 3.5 GB. |
| Cloud Firewall *and* ufw with 22 restricted to owner IPs, 80/443 to Cloudflare ranges, from day 1 | **Stage it.** Open-but-key-only at cutover; origin-lock in Phase 10. | Owner egress IP instability + cutover failure modes (§2.1 D-D). |
| Keep `:8443` "emergency door" | **Remove.** | It has never worked (PROVED blocked); it hard-codes an IP; the Hetzner web console is the real break-glass. |
| Separate read-only Postgres role, Hetzner private network, Telegram push | **Defer to D-Q / product.** | Nice, not needed for a correct migration. |
| Hetzner Volume for backups | **Reject.** | Same account, same server, same blast radius. Storage Box instead. |

Not proposed, and should stay not proposed at this scale: Docker/containers,
managed Postgres, streaming replica / HA, DB or worker split across hosts,
blue/green hosts, Prometheus + Grafana, a config-management framework. Each
would change the deploy contract (ADR-0010) or the loopback assumptions in the
units for no evidenced need.

### 3.2 Single points of failure — named and accepted with a mitigation
| SPOF | Accept? | Mitigation |
|---|---|---|
| One host holds proxy + app + DB + state + backups | **Accept** (scale) | Make rebuild fast, not the host redundant: image backups (D-C) + off-host dump/tar + the Phase 4 provisioning checklist doubling as the DR runbook. Target RTO: hours, RPO: 24 h (daily) — write both down (§4). |
| Cloudflare account (single owner login) is the only traffic lever | Accept | Owner enables 2FA (§9 SR-8); export the DNS zone file in Phase 1 so records can be recreated. |
| Operator Mac = only deploy origin and only holder of SSH private keys | Accept | Hetzner console is the break-glass; keep an offline copy of `qevik_prod` private key (owner). Not a migration item but must be written down. |
| Let's Encrypt HTTP-01 via Cloudflare :80 | Accept | Copied certs (D-E) give 60+ days of slack at cutover; Caddy renews at 2/3 lifetime. |
| DashScope as the only LLM provider | Product, not infra | out of scope. |

### 3.3 Missing security controls (added to §9 as mandatory)
- No account-level 2FA requirement (Hetzner, Cloudflare, Google Cloud) — added SR-8.
- No process-visibility control: any local user can read root argv (`/proc`); `hidepid=invisible` mount option — SR-1 (Phase 10 part).
- No `UMask` in units → state files default to 0644 (how F-2 happened) — SR-2 (unit change under review).
- No statement about the Postgres superuser: `postgres` role must remain `local peer` only (as today) — SR-1.
- Origin exposure: 80/443 open to the world at the host (Cloudflare only *trusted*, not *required*) — D-Q (Authenticated Origin Pulls or range lock, Phase 10).
- Unattended-upgrades restarts PostgreSQL on minor upgrades; `qevik-api` has `Requires=postgresql` and stops with it; recovery relies on `Restart=` — acceptable, but must be observed once in Phase 10 (operational risk, not a control gap).

### 3.4 Missing backup controls (added)
- Nothing backs up `/var/lib/caddy` (LE account), `/etc/caddy/Caddyfile`, unit files, or env-file **names** — include in the daily tar (values never).
- No restore test of the **off-host** copy — V15 added: restore one dump from the Storage Box into a scratch DB before Phase 9.
- No Cloudflare zone export — Phase 1 owner action (no secrets in a zone file).
- Retention: dumps 14 local + 30 off-host; tars 30 off-host; image backups 7 (add-on fixed).

### 3.5 Backup model, final
```
03:30 UTC  qevik-backup.service (existing, extended)
  1. pg_dump -Fc qevik → /opt/qevik/backups/qevik-<ts>.dump        (existing)
  2. pg_restore into scratch DB, verify, drop                     (existing)
  3. tar --zstd of: /var/lib/qevik/{control,evidence,jobs,prospects,outreach,audits,briefs,workspaces}
       /srv/sites  /srv/qevik-public  /etc/caddy/Caddyfile  /etc/systemd/system/qevik-*  /var/lib/caddy
       + `cut -d= -f1` name lists of /opt/qevik/*.env  → /opt/qevik/backups/state-<ts>.tar.zst   (NEW)
  4. rsync dump + tar → Storage Box sub-account (SFTP, key in /root/.ssh, 0600)                  (NEW)
  5. prune local (14) and remote (30)                                                             (NEW)
  OnFailure=qevik-backup-failed.service → writes /var/lib/qevik/control/backup.failed            (NEW)
  /api/health reports backup component: last_verified_at, last_offsite_at, failed marker         (NEW, code)
Hetzner backup add-on: daily image, 7 rotations (console toggle)
```
Steps 3–5 and the health component are implementation items (Phase 4 script
change under review; health component is a small code change) — listed so the
owner sees the whole model, not approved by this document.

### 3.6 Monitoring, final (minimum that closes "nobody notices")
1. `OnFailure=` on every `qevik-*` unit and timer → marker file → `/api/health` component (code change, small).
2. One external uptime monitor you own, two URLs, alert to you (D-P).
3. `journalctl` cap `SystemMaxUse=1G`; weekly `apt list --upgradable` + planned reboot cadence (monthly, in a window) so `reboot-required` never sits for weeks again.
4. Phase 10 daily probe from devloop-01 is **temporary** (14 days) and manual/agent-run, not a unit.

### 3.7 Operational risks the draft under-weighted
- **Reboot survival never exercised** (R-14): the target is rebooted twice before cutover (Phase 4 empty, Phase 7 with data). Pass/fail is recorded.
- **Dependency drift** (R-16): capture `pip freeze` on the old host; install on the target with `-c old-host-constraints.txt`; commit a `constraints.txt` to the repo afterwards (owner-reviewed) so the *next* rebuild is reproducible. `playwright` gets declared.
- **No DR runbook**: the Phase 4 provisioning checklist is written so that it *is* the rebuild-from-backup runbook (image restore → or → checklist + off-host restore).
- **Owner is the only operator**: every gate needs you; the plan's elapsed time is bounded by your availability, not by the work (§ executive summary).

### 3.8 Inappropriate for Qevik's current scale (explicitly not done)
HA/replication · managed DB · separate DB host · containers · Prometheus stack
· IP-allowlisted SSH · blue/green · a second production host · Hetzner Volume.

*Owner requirement AR-3 (2026-09-03): the single-host architecture is preserved; none of the
above is introduced unless a concrete requirement emerges.*

---

## 4. Final proposed target architecture — `qevik-prod-01`

```
                 Cloudflare  (DNS + proxy, 4 records; SSL mode per U2; 2FA on)
                        │  origin = qevik-prod-01 IPv4 (cutover lever; IPv6 AAAA optional)
                        ▼
   Hetzner Cloud Firewall  ── in: 22/tcp any · 80/tcp any · 443/tcp any · ICMP · (Phase 10: 80/443 CF ranges only)
                        ▼
  ┌──────────────── qevik-prod-01  (CPX31-class, nbg1, Ubuntu 26.04, 2 GB swap) ────────────────┐
  │  ufw (mirror of cloud fw)   sshd key-only, root prohibit-password, fail2ban                 │
  │  Caddy 2.x  :80 :443  ── qevik.ai (static) · www→301 · sites.qevik.ai (/srv/sites)        │
  │                          app.qevik.ai → :8081 (/api,/auth,/health) · :8080 (/control)      │
  │  qevik-api :8080   qevik-control :8081   5 × mission worker   backup + market-scan timers   │
  │  qevik-jobs.slice (browsers/builds)   Playwright Chromium (pinned build)                    │
  │  PostgreSQL 18.x  127.0.0.1:5432  db qevik  (new password; scram; local peer for postgres) │
  │  /opt/qevik (app, env, backups)  /var/lib/qevik (state)  /srv/{sites,qevik-public,-control}│
  │  OnFailure markers → /api/health                                                            │
  └───────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                              │ SFTP (sub-account key)
                                   Hetzner Storage Box  (dumps 30 d · state tars 30 d · box snapshots)
                                   Hetzner backup add-on (image, 7 d)
                                   External uptime monitor (owner-owned) → owner alert

   qevik-core-01 (old)   frozen-intact, rollback target for 14 days, then snapshot + delete
   qevik-devloop-01      DevLoop only; read-only vantage during Phases 7–10
   Operator Mac          ADR-0010 deploy origin (TARGET=root@qevik-prod-01, key qevik_prod)
```

Design properties: one host, one deploy contract, one backup unit, one
external eye. **Expansion path** (none needed now, none precluded): CPU/RAM
resize in place; a Hetzner private network to a future worker host in nbg1
(workers already talk to PG by DSN — moving them off-host is a DSN + firewall
change, not a redesign); Object Storage for assets when `atlas_assets` bytes
become worth keeping (A9 — today they are ephemeral); DevLoop executor on
devloop-01 per ADR-0011 without touching production.

RTO/RPO to write into the runbook: **RPO 24 h** (daily backup; tighten by
raising the timer frequency if the owner wants — dump is 20 MB), **RTO ≈ 2–4 h**
(image restore) or **≈ half a day** (checklist rebuild + off-host restore).

---

## 5. What lives on `qevik-prod-01` — exactly

| Component | Location | Origin | Notes |
|---|---|---|---|
| **Application code** | `/opt/qevik/atlas` (kernel, `infra/`, console src) + `.venv` | ADR-0010 `deploy_control.sh` payload from the Mac; `pip install -e .[dev] -c constraints` | Never rsync the old host's dirty tree (A1). `DEPLOYED_SHA` = old host's SHA or its reviewed successor. |
| **PostgreSQL** | cluster `18-main`, `/var/lib/postgresql/18/main`; `/etc/postgresql/18/main/{postgresql,pg_hba}.conf` | apt `postgresql-18`; data via `pg_dump`/`pg_restore` (Phases 6, 9) | Only `qevik` DB. `listen_addresses` loopback; `shared_buffers=512MB`; `max_connections=100`. `qevik_test` absent (D-G). |
| **SQLite files** | **none.** | — | PROVED: no application SQLite on the old host (only mypy cache + NSS db). The kernel's sqlite paths are test-only. The DevLoop `state.db` lives on the Mac and is out of scope. Do not introduce any. |
| **Uploads / persistent files** | `/var/lib/qevik/{control,evidence,jobs,scratch,worktrees,prospects,outreach,audits,briefs,workspaces}` (qevik:qevik 0700/0600), `/srv/sites` (qevik), `/srv/qevik-public` (from `deploy_public.sh`), `/srv/qevik-control` (deploy payload), `/opt/qevik/market` | rsync + manifests from old host (MIGRATE set); public/console regenerated | Atlas asset *bytes* remain ephemeral (`$TMPDIR`, A9) — pre-existing; not migrated, not "fixed" here. |
| **Logs** | journald only, `SystemMaxUse=1G`; Caddy access log to journald (as today) | — | No file logs, no logrotate. Export slices on demand. |
| **Backups** | `/opt/qevik/backups/` (dumps 14, tars 14) → Storage Box (30 d) ; image add-on | `qevik-backup.timer` 03:30 UTC | §3.5. First off-host restore test before cutover (V15). |
| **Secrets** | `/opt/qevik/atlas.env` (root 0600), `control.env`, `worker.env`, `places.env` (qevik 0600), `brave.env` (root 0600); `/root/.ssh/storagebox_ed25519` (0600); `/var/lib/qevik/control/vault.json` (0600) | **typed by the owner** on the target (umask 077); vault regenerated (D-I) | Names verified by the agent with `cut -d= -f1`/`stat`; values never read. No `.pgpass`, no DSN on any argv, no `cloudflare.env` (nothing uses it). |
| **systemd units** | `qevik-api`, `qevik-control`, `qevik-worker{,-research,-delivery,-publish,-healthcheck}`, `qevik-backup.{service,timer}`, `qevik-market-scan.{service,timer}`, `qevik-jobs.slice`, `qevik-api.service.d/resources.conf`, `qevik-backup-failed.service` (new) | repo `infra/` via deploy + explicit install of slice/drop-in (Y1) | All enabled; reboot-tested twice. |
| **Caddy** | `/etc/caddy/Caddyfile` (from live old-host file, minus `:8443` block, origin comment updated), `/var/lib/caddy` (copied certs + ACME account, D-E) | apt `caddy`; config from repo after review | `admin off` stays; `enable_domain.sh` is not used. |
| **Docker** | **none.** | — | Nothing on the old host is containerised; introducing it changes ADR-0010. |
| **Monitoring components** | `OnFailure=` units + marker files; `/api/health` backup/units component; nothing else on-host | small code + unit change (Phase 10) | External uptime monitor is off-host and owner-owned. |
| **Users** | `root` (deploy, key-only), `qevik` (services, no shell login, no authorized_keys), `postgres`, `caddy` | provisioning checklist | uid parity not required; create `qevik` before rsync. |
| **Explicitly not present** | hand-copied `/opt/qevik/*.py` scripts, `.pgpass`, rollback dirs of the old host, legacy Caddyfiles, `qevik_test`, pip caches, the old `.git` tree | — | archived in Phase 11, not installed. |

---

## 6. Server specification and Hetzner configuration (recommended)

| Item | Recommendation | Notes / verify in console |
|---|---|---|
| Type / CPU | **CPX31-class** — 4 vCPU AMD EPYC (shared) | INFERRED same class as today. Alternative CPX41 (8 vCPU). Names/prices unverified (U1). |
| RAM | 8 GB + **2 GB swap file** (`vm.swappiness=10`) | Resize CPU/RAM later without reinstall if needed. |
| Storage | 160 GB local NVMe (comes with the type); **no Volume** | Today 12 GB used of 150; growth is journald/evidence — capped/bounded. |
| OS | Ubuntu 26.04 LTS (same as source; PG 18, Python 3.14 from distro) | apt full-upgrade + reboot in Phase 2 before anything is installed. |
| IPv4 / IPv6 | **Primary IPv4 + IPv6 /64** both assigned | IPv4 needed for SSH from your networks and as the Cloudflare origin; AAAA origin optional. Neither IP is published in DNS. |
| Location | **nbg1** (Nuremberg) | same as old host and devloop-01; private-network option later. |
| Firewall | Hetzner **Cloud Firewall** attached to the server: in 22/tcp any, 80/tcp any, 443/tcp any, ICMP; out any. ufw identical. Phase 10: 80/443 → Cloudflare ranges (or Authenticated Origin Pulls). | Do not restrict 22 by IP (D-D). |
| SSH access model | root, `PermitRootLogin prohibit-password`, `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `MaxAuthTries 3`; **one** authorised key `qevik_prod` (Mac); fail2ban sshd jail; Hetzner web console = break-glass | `qevik` user has no login. ADR-0010 keeps deploying as root. |
| Backup strategy | daily verified dump + state tar → Storage Box; image add-on 7 d; restore test before cutover and monthly after | §3.5. |
| Off-host destination | **Hetzner Storage Box**, smallest tier, **sub-account** scoped to one directory, SFTP with a key held only on the target; Storage Box snapshots weekly | Alternative: Hetzner Object Storage via rclone. Not a Volume. |
| Account hygiene | 2FA on Hetzner, Cloudflare, Google Cloud, DashScope, Brave consoles; a separate Hetzner **project** for production if the current project mixes unrelated resources (U1) | owner actions. |
| Time / patching | systemd-timesyncd; unattended-upgrades (security) on; monthly reboot window | avoids the "reboot pending for weeks" state. |

---

## 7. Rollback model — the old server stays intact

**Invariant:** `qevik-core-01` is never written to by the agent except the
approved Phase 9 *stop* step, and is never modified, resized, rebooted or
deleted until Phase 11, which starts only after the observation period and an
explicit GO (D-N). Its LE certs, DB, state, env files and Caddy stay in place.

Before cutover (Phase 8/9 prerequisites): owner takes a **Hetzner snapshot of
the old server** (cheapest full rollback, U1 confirms availability); confirm
old-host LE cert `notAfter` is > 30 days out so a rollback never needs
re-issuance; one off-host copy of the latest verified dump exists.

| Window | Trigger | Rollback action | Data outcome |
|---|---|---|---|
| **R0 — during cutover, before the origin change** (steps 1–5) | any equality/probe failure | `systemctl start` the old units in reverse order; target stays stopped | **none lost** — old host never stopped being the truth for readers; no writes happened anywhere. |
| **R1 — first 60 min after the origin change** | public probe failure > 5 min, login broken, site 404s | owner reverts the 4 Cloudflare records → old IP (proxied, instant); start old units; stop target units | Writes made on the target in those minutes are lost unless reverse-synced (dump target → restore old; same SHA ⇒ same schema). Decide in the runbook: default **discard** (window is minutes, workers idle). |
| **R2 — days 1–14 (observation)** | data-loss signal, integration failure, instability | same lever; **reverse-sync required**: stop target units, dump target DB + rsync state back to the old host (first agent writes to old host beyond stop — needs its own GO), start old units, revert origin | Bounded by the time since cutover; missions/sites created on the target are carried back. This is why the old host is *frozen*, not *running*: its DB must be a clean base for the reverse restore. |
| **R3 — after Phase 11** | — | **none.** Forward-fix from backups (Storage Box + image). | The snapshot kept 30 days after deletion is a last-resort archive, not a rollback. |

### 7.1 Explicit RPO / RTO (AR-1 — proposed numbers, to be approved with D-M before any origin change)

| Scenario | Maximum acceptable data loss (RPO) | Expected time to restore service (RTO) | Mechanism |
|---|---|---|---|
| R0 — abort before the origin change | **0** (no writes anywhere after the freeze) | **≤ 10 min** (start old units, probe) | old host restarted |
| R1 — rollback within 60 min of the origin change | **≤ 60 min of target-side writes discarded** — the runbook default; workers are held stopped on the target for the first 15 min after cutover so the realistic loss is operator/API writes only | **≤ 15 min** (Cloudflare origin revert ≈ 1–2 min to take effect + old units start ≈ 2 min + probes) | origin revert, no data movement |
| R2 — rollback during the 14-day observation | **0 for committed data** by reverse-sync (target `pg_dump` + state rsync → old host, same `DEPLOYED_SHA`); in-flight missions at the freeze moment are re-run | **≤ 60 min** (freeze target ≈ 2 min, dump+restore ≈ 5 min for a 20 MB dump, rsync ≈ 1 min, start, probes) | reverse-sync — a separate owner GO because it writes to the old host |
| R3 — after decommission | no rollback; **disaster RPO 24 h** (daily verified backup; tighten by raising the timer frequency if wanted) | **2–4 h** image restore · **≈ ½ day** checklist rebuild + off-host restore | Hetzner image backup / Storage Box copies |

These numbers are the agent's proposal from measured sizes (dump 19.6 MB compressed, state
258 MB) and the ADR-0010 restart timings; the owner approves or changes them at D-M. Cutover
does not proceed on wording like "minutes may be lost".

Old-host **freeze** method after successful cutover (Phase 9 step 8): all
seven `qevik-*` units and both timers `systemctl disable --now` (so a reboot
cannot restart writers), a marker file `/opt/qevik/FROZEN_<ts>`, Caddy and
PostgreSQL **left running** (instant TLS + DB on rollback; PG idle costs
nothing). No password rotation *on the old host* until Phase 11 — rotating
would break rollback.

Observation period: **14 days** from T2 (D-N). Exit criteria (Phase 10):
14 daily backups VERIFIED + off-host copies present, zero unexplained unit
restarts, market scan fresh daily, public probes green from two vantages, one
real mission end-to-end, one off-host restore test passed. Any failed
criterion pauses the clock; it does not shorten it.

---

## 8. UNKNOWN items U1–U15 — classification

| # | Item | Class | How / when it resolves |
|---|---|---|---|
| U1 | Hetzner project, Cloud Firewall, backup/snapshot state of the old server, API token | **Must resolve before execution** | Phase 1 owner console read; recorded as text (no tokens). Gates D-B/D-C/D-L. |
| U2 | Cloudflare zone settings (SSL mode, WAF, rules, hidden records); token existence | **Must resolve before execution** | Phase 1 owner dashboard read + zone export. SSL mode decides whether D-E copy is mandatory (Full strict ⇒ yes). |
| U3 | External uptime/alerting anywhere | Non-blocking | Assume none; D-P adds one. Owner confirms in Phase 1 in passing. |
| U4 | Playwright install method / pip version on old host | Can resolve during execution | Phase 4 read-only `pip show playwright`, `pip freeze` on old host. |
| U5 | `qevik_test` purpose | Can resolve during execution | D-G default = not migrated; owner answers by Phase 5. |
| U6 | Content of 7 err / 21 warn per worker unit | Can resolve during execution | Phase 5 read-only journal read; if not restart noise, it becomes a Phase 7 check. |
| U7 | Legacy Caddyfiles' relationship to the live one | Non-blocking | Live `/etc/caddy/Caddyfile` is the only source; legacy files are archived, never installed. |
| U8 | Peak resource usage | Non-blocking | No history exists; mitigated by swap + reversible resize + Phase 10 observation. |
| U9 | Vault ever held real credentials; keep or regenerate key | Can resolve during execution — **before Phase 3** | Owner answers; D-I default regenerate. A wrong answer is detectable in Phase 7 (`/api/health` vault component). |
| U10 | `QEVIK_REPORTS_STORE` value | Can resolve during execution | Owner reads the value on the old host over SSH in Phase 3 and enters the same on the target. |
| U11 | Hand scripts / scratch / ad-hoc dumps still wanted | Can resolve during execution | D-I; default archive. |
| U12 | `atlas_quarantined_fixtures` origin | Non-blocking | `pg_dump` carries it regardless; owner may drop it later. |
| U13 | All `/control/*` routes auth-gated? | Non-blocking for migration | Phase 7 adds a probe (§9 SR-7); product fix separately. |
| U14 | On-host GitHub deploy key still used | Can resolve during execution | Phase 3 owner answer; default not recreated. |
| U15 | Exact public table count (75 vs 78) | Can resolve during execution | Phase 5 `count(*)` on `pg_tables`; trivial. |

---

## 9. Security findings → mandatory migration requirements

Each is a **pass/fail gate** in Phase 7 (before cutover) unless marked Phase 10.

| Req | From | Requirement on `qevik-prod-01` | Verified by |
|---|---|---|---|
| SR-1 | F-1 | No credential on any process argv, ever. DSNs only via `EnvironmentFile=`/`PGPASSFILE`. No ad-hoc root processes; hand tooling runs as `systemd-run --property=EnvironmentFile=…` or via `qevikctl --slice`. `postgres` superuser `local peer` only. New `qevik` DB password (K1/K2). Phase 10: `/proc` mounted `hidepid=invisible`. | `ps -eo args` grep for `://` and `password` = 0 hits; `pg_hba` diff. |
| SR-2 | F-2 | `/var/lib/qevik/**` 0700 dirs / 0600 files; `vault.json`, `credentials.jsonl` 0600; units get `UMask=0077` (reviewed unit change) so it stays that way. | `find /var/lib/qevik -perm /o+r` = 0; unit `systemctl show -p UMask`. |
| SR-3 | F-3 | `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `MaxAuthTries 3`, fail2ban sshd jail active; password login **tested refused** from devloop-01. **AR-2 two-session procedure, mandatory:** (1) session A stays open throughout; (2) install the `qevik_prod` public key; (3) open a *fresh* session B from the Mac with `-i ~/.ssh/qevik_prod -o IdentitiesOnly=yes` and prove it; (4) apply sshd hardening and `sshd -t`, reload (not restart); (5) from devloop-01 prove password auth is refused and a key-less attempt fails; (6) open session C with the key to prove reconnect; (7) only then close A. Never rely on disconnecting and hoping to reconnect. | `sshd -T`; `fail2ban-client status sshd`; negative test; session log A/B/C timestamps in `evidence/phase-3/`. |
| SR-4 | F-4 | Only `qevik_prod` public key in `/root/.ssh/authorized_keys`; `naml_hetzner` and `devloop_01` public keys **absent**. | `authorized_keys` fingerprint list = 1 entry, matches. |
| SR-5 | F-5 | New Google Places key: restricted to the target IPv4/IPv6 **and** to the Places API; old key revoked immediately after cutover (Phase 9 step 8), not at Phase 11. DashScope + Brave rotated (D-J); old values revoked at Phase 11. | Phase 7 market-scan test call succeeds; console screenshot of restrictions (no key value). |
| SR-6 | F-6 | Off-host copy of every verified dump + state tar (§3.5); `OnFailure=` marker surfaced in `/api/health`; **one off-host restore test passed before Phase 9** (V15); image backup add-on enabled. | Storage Box listing; restore log; `/api/health` JSON. |
| SR-7 | F-7 | Phase 7 probe: unauthenticated `GET` on every `/control/*` route reachable through Caddy must return 401/403 (or a documented public route). Any 200 with data is reported to the owner **before** cutover; it does not block the migration but is not hidden. | probe table in `evidence/phase-7/`. |
| SR-8 | new | 2FA enabled on Hetzner, Cloudflare and Google Cloud accounts before Phase 2; Cloudflare zone exported. | owner statement (no secrets). |
| SR-9 | new | No secret value ever transits chat, docs, git, task DB, logs, or agent context; env-file names verified only with `cut -d= -f1`; transcripts grep-checked for DSN shapes at every phase end. | phase evidence records. |

None of the old host's insecure properties is copied: not the key, not the
password-auth sshd, not the 0644 state, not the argv DSN, not the pinned Places
key, not the local-only backups.

---

## 10. Estimated phases, effort and blockers

| Phase | Who | Effort (work) | Elapsed (bounded by owner availability) | Gate |
|---|---|---|---|---|
| 1 Decisions + console reads | owner | 1–2 h | day 1 | D-A…D-F, D-L |
| 2 Provision | owner 30 min · agent 1 h | 2 h | day 1–2 | — |
| 3 Security + secrets | owner 1 h (typing env files) · agent 1 h | 2 h | day 2 | owner "files in place" |
| 4 Runtime prep (incl. R-12 change review + push) | agent ½ day · owner review | 1 day | day 2–4 | D-H, D-E, O10 push |
| 5 Data prep | agent ½ day · owner answers | ½ day | day 4 | D-G, D-I |
| 6 Initial sync | agent 1 h | 1 h | day 4 | — |
| 7 Shadow validation (two reboots, SR gates) | agent ½ day · owner-supervised key tests 30 min | 1 day | day 5 | **GO to 8** |
| 8 Runbook + rehearsal on test hostname | agent ½ day · owner creates test record | ½ day | day 5–6 | **STOP — D-M** |
| 9 Cutover | owner present 60 min | ~15 min downtime | day 7 (window) | present throughout |
| 10 Observation | agent daily probe · owner reads | 14 days | day 7–21 | D-N |
| 11 Decommission | owner | 1 h | day 21+ | each destructive step |

**Blockers today (nothing else stops execution):**
1. D-A…D-F, D-L not given (this document).
2. U1/U2 console reads not done (owner, Phase 1).
3. R-12 code change (parameterise the origin IP/host) not written, reviewed or pushed — owner-pushed (O10).
4. Credentials/access exist only with the owner (Hetzner, Cloudflare, provider consoles, new SSH key, new DB password) — OWNER_INPUT_REQUIRED O1–O10.
5. DevLoop remains paused for the whole migration (R-25) — no change requested.

---

## 11. What this review changed relative to the draft (for traceability)
- Sizing: 16 GiB → 8 GB + swap + resize path (D-B).
- Firewall: day-1 IP-restricted SSH + origin-lock → staged (D-D, D-Q).
- `:8443` door: "owner decision" → remove (D-D).
- Backups: four mechanisms → one extended unit + image add-on + Storage Box; Volume rejected; off-host restore test added (V15) (D-C, §3.5).
- Monitoring: undefined → minimum defined; devloop-01 probe unit rejected (D-P, §3.6).
- Rollback: "7 days" → explicit R0–R3 windows, freeze method, 14-day period, reverse-sync rule, cert-validity precondition (§7, D-N).
- Security: F-1–F-7 → SR-1–SR-9 pass/fail gates; three new controls (2FA, `hidepid`, `UMask`) (§9).
- UNKNOWNs: U1–U15 classified (§8). New decisions: D-P, D-Q.

---

## 12. Stop

2026-09-03: §2.1 decisions received (D-L for Phase 1 only). Phase 1 complete —
`PHASE_1_COMPLETION_REPORT.md`. Now stopped at the **Phase 2 provisioning gate**:
no provisioning, no Hetzner/Cloudflare action, no data movement, no production
change, no secret rotation, no DevLoop execution until the owner's Phase 2 GO.

2026-09-03 (later): owner **halted Phase 2 before any server order** and asked for a
read-only suitability assessment of the existing `qevik-devloop-01` as the production
target. Result: `DEVLOOP01_SUITABILITY_ASSESSMENT.md` — suitable; recommendation
Option A (reuse, with a free rebuild); one decision requested, **D-R**. The
"`qevik-devloop-01` DevLoop only / never production" wording in §1, §4 and §10 of
this document is **superseded pending D-R**; the §6 spec table stays as the
approved D-B baseline, which the reused host exceeds. No action taken.
