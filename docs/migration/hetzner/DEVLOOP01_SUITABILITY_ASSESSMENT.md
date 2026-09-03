# DEVLOOP01_SUITABILITY_ASSESSMENT — can `qevik-devloop-01` be the new production host?

**Date:** 2026-09-03. **Trigger:** owner instruction — "STOP Phase 2 provisioning before creating
or ordering any new Hetzner server … perform a read-only suitability assessment of the existing
`qevik-devloop-01` as the potential target for the new Qevik production environment."
**Mode:** read-only. Nothing on `qevik-devloop-01`, `qevik-core-01`, Hetzner, Cloudflare or DNS was
changed; no server created or ordered; no data moved; no secret touched; DevLoop still paused.
**Evidence:** `evidence/phase-1/devloop01-inventory-2026-09-03.txt` (sanitised host inventory,
07:28–07:35 UTC) and `evidence/phase-1/probes-2026-09-03.txt` (Phase 1 probes, price sheet).
**Tags:** PROVED (read on the host this session) · OBSERVED-3P (public third-party source) ·
INFERRED (derived, method stated) · UNKNOWN / OWNER (only the console shows it).
**Supersedes:** `PHASE_1_COMPLETION_REPORT.md` §7 N-4 ("outside this migration's scope") — withdrawn.
**Decision requested:** one — **D-R** (§9). The owner decides; this document recommends (DQ-009).

---

## 0. Answer in five lines

1. `qevik-devloop-01` is a **bare, idle, fully patched Ubuntu 26.04.1 server, 8 vCPU / 15.2 GiB / 305 GB,
   nbg1-dc3, IPv4 + IPv6**, created **2026-09-02 12:18 UTC** (PROVED). Nothing runs on it but the
   stock OS; nothing depends on it; it holds no data worth keeping.
2. It is **technically suitable** as the production target and **exceeds** the approved D-B
   specification (4 / 8 / 160 + swap) in every dimension.
3. Its only real liabilities are (a) it is **not yet hardened** (password auth on, ufw inactive,
   no swap, Cloud Firewall / backup add-on state unknown) — all of which Phase 3 would do to a new
   server anyway — and (b) it is the host **ADR-0011 / DQ-011 designated for the DevLoop executor**,
   so reusing it requires the owner to re-home DevLoop to a future server.
4. **Recommendation: Option A — reuse `qevik-devloop-01` as `qevik-prod-01`**, with a free
   console **rebuild** as the first Phase 2 step so that "clean" becomes PROVED instead of INFERRED.
5. Cost is the one axis where the answer depends on an intention only the owner holds (§7.1):
   reuse is cheaper than *buying another server while keeping this one*; it is **more expensive per
   month than buying a CPX32 and deleting this one** — but that deletion was never proposed and
   would leave DevLoop without the host DQ-011 approved.

---

## 1. Exact server type and specification (PROVED unless tagged)

| Item | Value | Tag |
|---|---|---|
| Hetzner instance id / hostname | `164307556` / `qevik-devloop-01` | PROVED (metadata service) |
| Region / availability zone | `eu-central` / **`nbg1-dc3`** — same DC as `qevik-core-01` (162146484) | PROVED |
| CPU | **8 vCPU**, AMD EPYC-Genoa (shared), 1 thread/core, 8 cores/socket | PROVED |
| RAM | **15 603 MiB** (≈ 15.2 GiB); 1.1 GiB used at rest; **no swap** | PROVED |
| Disk | `/dev/sda` **305.2 GB** ext4 root, 301 G size, **1.7 G used**; `/boot/efi` vfat; no volumes | PROVED |
| IPv4 | `91.107.244.253/32` (primary IP; DHCP) | PROVED |
| IPv6 | `2a01:4f8:1c1b:1dbe::1/64`, gateway `fe80::1` (static via cloud-init) | PROVED |
| Product name | shape matches **CPX42** (8 vCPU AMD / 16 GB / 320 GB) | INFERRED — **console confirms (OWNER)** |
| Price | **CPX42 ≈ €69.49 / month excl. VAT** after the 2026-06-15 price change (was €25.49) + IPv4 €0.50 | OBSERVED-3P — **console/invoice confirms (OWNER)** |
| Backups add-on, snapshots, Cloud Firewall, project, labels | not readable from inside the host | **OWNER** (console) |
| Created | **2026-09-02 12:18 UTC** (first journal boot, first cloud-init run, `/var/lib/cloud/instances/164307556`) | PROVED |

Note on ADR-0011: that ADR approved a **CX43 (€15.99) or CX53 (€29.49)** for the DevLoop executor.
The server that exists is a CPX42 — a different, more expensive line. The most likely reason is that
CX plans showed as "not available" in the console (hetzner.com displayed every CX plan as "not
available" on 2026-09-03 — OBSERVED-3P); the owner can confirm. This matters for Option B (§7):
the "cheaper CX43" branch of the Phase 1 recommendation is probably **not orderable** (INFERRED).

## 2. Operating system and patch state (PROVED)

| Item | Value |
|---|---|
| OS | Ubuntu **26.04.1 LTS** (resolute), Hetzner minimal image (`Ubuntu-2604-resolute-64-minimal`, image built 2026-08-26) |
| Kernel | `7.0.0-30-generic` (Ubuntu 7.0.12 base), booted 2026-09-02 12:24 UTC; uptime 19 h at read |
| Updates | `apt full-upgrade` run by the owner on 2026-09-02 12:23 (apt history), followed by reboots; **0 upgradable, no reboot-required** |
| Unattended upgrades | enabled, timer active |
| Package count | 585 (stock minimal + `git`, `python3.14`, `tmux`, `ufw` present) |
| Time sync | chrony active |
| Same major OS as `qevik-core-01` (26.04) — Python 3.14 / PostgreSQL 18 from distro, as the target architecture requires | ✔ |

## 3. Everything running on it (PROVED)

- **systemd services (non-default running):** `ssh`, `cron`, `chrony`, `rsyslog`, `unattended-upgrades`,
  `qemu-guest-agent`, `atd`, `multipathd`, `polkit`, `networkd-dispatcher`, systemd core units
  (journald/networkd/resolved/udevd/logind/hostnamed). **No custom units** in `/etc/systemd/system`
  (only symlinks/drop-ins from packages).
- **Timers:** stock only (apt-daily, apt-daily-upgrade, fstrim, logrotate, e2scrub, motd-news,
  dpkg-db-backup, man-db, update-notifier). **No cron jobs** for any user; `/etc/cron.d` stock.
- **Containers:** no docker, podman, containerd, or container units.
- **Processes:** stock daemons only (list in evidence §"processes"); nothing owned by a non-system
  user; no Python/Node/Postgres/Caddy/nginx; the only non-system processes were this assessment's own SSH session.
- **Listening ports:** `sshd :22` (0.0.0.0) — and only that; systemd-resolved and chrony on loopback.
  Nothing on 80 / 443 / 8080 / 8081 / 5432 / 8443.
- **Firewall:** `ufw` installed, **inactive** (`ENABLED=no`; defaults would be DROP in / ACCEPT out). Hetzner Cloud Firewall: UNKNOWN (console).
- **SSH:** `PermitRootLogin prohibit-password`, `PubkeyAuthentication yes`, **`PasswordAuthentication yes`**,
  `KbdInteractiveAuthentication no`, `MaxAuthTries 6`. Exactly **one** authorised key:
  ED25519 `SHA256:0ony14dB7vfo4y0xVmaDwHIonDE2khTODM2YiE76ues` = the Mac's `~/.ssh/devloop_01` = the key
  registered in the Hetzner project for this server (metadata `public-keys`). No fail2ban.
- **Users:** `root` only with a home; no `devloop`, `qevik`, or other login users.
- **Background noise:** **11 683** failed/invalid SSH attempts in the last 24 h (Internet scanning;
  password auth is effectively unusable because root is `prohibit-password` and no other user exists)
  and hourly `ssh-rsa not in PubkeyAcceptedAlgorithms` pre-auth rejections (the "ssh-rsa in" lines in
  the Phase 1 raw read; resolved — they are rejected scanner attempts, not logins).

## 4. Is it truly idle? Does any workflow depend on it?

**Idle: PROVED.** No workload, no listener but SSH, no timers, no cron, no containers, 1.7 GB disk
used (OS), load ≈ 0.

**Dependencies: none found.**
- Every accepted SSH login since creation (17 of them) came from **one address, 178.104.85.106**,
  with the single ED25519 key — i.e. the owner's Mac sessions (the owner's own inspection/upgrade
  commands are the whole `.bash_history`: `hostnamectl…`, `apt full-upgrade`, `reboot` ×2,
  `uname -r`, `cd ~/atlas` — no clone exists, so that last command did nothing) plus this project's
  read-only vantage sessions. No third party has ever logged in (PROVED for the journal's lifetime,
  which equals the server's lifetime).
- **Repository:** `grep` of `~/atlas` for `91.107.244.253`, `qevik-devloop-01`, `devloop_01` hits
  **only the migration documents** (9 files under `docs/migration/hetzner/`) — **no code, no unit,
  no script, no gate** references this host. ADR-0011 refers to a *future* "devloop-01" by role, not by IP.
- **DevLoop:** paused; ADR-0011 Phase 1 ("Provision") was never formally executed on this box — no
  `devloop` user, no hardening, no clone, no service. It is a raw server the owner bought ahead of
  the ADR-0011 gates, not a DevLoop installation.
- **Production:** `qevik-core-01` has no reference to it (Phase 0 inventory); it is not a backup
  target, not a vantage point for any unit, not in Cloudflare.
- **This migration plan** used it only as an *agent-run, manual* second-vantage probe source
  (Phases 7–10). That role moves elsewhere if Option A is chosen (§8, U16).

## 5. Persistent data on the server — classification

| Data | Size | Class | Note |
|---|---|---|---|
| Ubuntu OS + packages (stock + full-upgrade) | 1.7 G | **Disposable** | Reinstallable from the Hetzner image in minutes. |
| `/root/.ssh/authorized_keys` (1 key, `devloop_01`) | 1 line | **Disposable — must be *replaced*** | D-F/SR-4: only `qevik_prod` may be on the production host. The devloop key was also re-injected from the Hetzner project at creation; a rebuild would inject whichever project key the owner selects. |
| `/root/.bash_history` (292 B, owner's 9 inspection/upgrade commands) | 292 B | **Disposable** | No secrets in it (read; quoted above). |
| Host SSH key pair (`/etc/ssh/ssh_host_*`) | — | **Disposable** | Regenerated on rebuild; either way the fingerprint gets recorded in `evidence/phase-2/` before first production use. |
| systemd journal (24 M, since 2026-09-02) | 24 M | **Disposable** | Evidence value only; the relevant facts are captured in this document's evidence file. |
| cloud-init instance data, apt lists, machine-id | — | **Disposable** | |
| `/opt`, `/srv`, `/mnt`, `/home`, `/var/lib/postgresql`, `/var/lib/qevik`, `/etc/caddy` | **absent / empty** | — | Nothing to preserve or migrate. |
| Hetzner-side objects: backups, snapshots, firewall, labels, project membership | — | **UNKNOWN (OWNER)** | Not visible from inside. If a backup add-on is already on, it is a cost line to keep for production; if snapshots exist they are the owner's to keep or delete. |

**Can preserve:** nothing needs preserving. **Must migrate elsewhere:** nothing. **Disposable:** all
of the above. **Unknown:** only console-side objects. The server can be rebuilt, renamed or
re-keyed **without losing anything that anyone would want back.**

## 6. Can it safely become the production target?

**Yes — after Phases 3–8 exactly as already planned, with three additions and one governance change.**

What is already right (PROVED): same OS major as source; same DC; IPv4 + IPv6; ≥ 2× the approved
CPU / RAM, ≈ 2× the disk; fully patched; no reboot pending; no foreign software; no data; no
dependants; single key, single user; nothing listening but SSH.

What is not yet right (all fixable, all of it Phase 2/3 work a *new* server would need too):

| Gap | Required end state | Where in the plan |
|---|---|---|
| `PasswordAuthentication yes`, `MaxAuthTries 6`, no fail2ban | SR-3 (`no`, `3`, fail2ban) via the **AR-2 two-session procedure** | Phase 3 |
| Authorised key is `devloop_01` | SR-4: **only** `qevik_prod` — devloop key removed | Phase 2 (rebuild with `qevik_prod` selected) or Phase 3 (add-then-remove under AR-2) |
| No swap | 2 GB swap file, `vm.swappiness=10` (D-B) | Phase 3/4 |
| ufw inactive; Cloud Firewall unknown | D-D: Cloud Firewall 22/80/443 + ufw mirror, `:8443` closed | Phase 2 (console) + Phase 3 |
| Backup add-on unknown; no Storage Box | D-C: image backups on + BX11 sub-account | Phase 2 (console) |
| Hostname `qevik-devloop-01` | `qevik-prod-01` — console rename (free, no reboot) + `hostnamectl` on the host | Phase 2 (owner) / Phase 3 (agent) |
| "Clean" state is INFERRED (1 day of Internet exposure with key-only effective auth, no indicators of compromise) | PROVED-clean | **Optional rebuild** in Phase 2 (§9 D-R) — free, ~2 minutes, keeps IPs and id |

Governance change: ADR-0011 / DQ-011 must be **amended** (owner decision, documented): the DevLoop
executor becomes a *future* server created when DevLoop is un-paused and its gates pass — and
**DevLoop must never run on the production host** (ADR-0011 rejected Option B for exactly that
reason; AR-3 and the migration spec say the same). Reuse does not violate ADR-0011's substance; it
retargets the *name*.

## 7. Option A (reuse `qevik-devloop-01`) vs Option B (create `qevik-prod-01`)

Prices OBSERVED-3P, excl. VAT, console-confirmation pending; "old" = `qevik-core-01` (CPX32-shape,
≈ €35.99 with IPv4, INFERRED — existing servers are billed at current list prices).

### 7.1 Cost

| Scenario | During migration (old + all) | Steady state after Phase 11 | Net **new** spend vs today |
|---|---|---|---|
| **A** — reuse devloop-01 as prod; DevLoop host bought later, when un-paused (CX53 €29.49 per ADR-0011, if orderable) | old €35.99 + devloop-01 €69.99 + backups 20 % €13.90 + BX11 €3.20 = **€123.08** | **€87.09** (+ DevLoop host later) | **+ €17.10 / mo** now (backups + Storage Box only) |
| **B1** — new CPX32 for prod; devloop-01 kept idle for DevLoop | old €35.99 + new €46.29 + devloop-01 €69.99 = **€152.27** | **€116.28** | + €46.29 / mo |
| B2 — new CPX32 for prod; **delete** devloop-01 (not proposed by anyone; would need its own owner decision and re-buys DevLoop's host later) | old €35.99 + new €46.29 = €82.28 | €46.29 (+ DevLoop host later) | + €46.29 − €69.99 = − €23.70 / mo |
| B3 — new CX43 (€15.99) for prod + delete devloop-01 | €58.88 | €22.89 | probably **not orderable** (§1 note) |

Reading: against the only Option B that keeps today's fleet (B1), **A saves ≈ €29 / mo and one
purchase**. A is more expensive than B2 by ≈ €41 / mo *only if* the owner would otherwise delete the
CPX42 — a decision never put on the table, and one that leaves DevLoop hostless. Hetzner cannot
rescale a server to a **smaller disk** ("you can only rescale to server plans with a disk size equal to or larger
than the current disk" — docs.hetzner.com FAQ, OBSERVED-3P), so devloop-01 can never be shrunk to CPX32 pricing.

### 7.2 Performance

A: 8 vCPU / 15.2 GiB / 305 GB — 2× the approved D-B capacity; production today uses 1.7 GiB RAM
and load ≈ 0.25 (single sample, U8). B: 4 / 8 / 160 (+ resize path). Both are sufficient; A removes
U8 (peak unknown) as a risk without any resize step. D-B's "do not upgrade to the larger class
without evidence" was a **purchase** constraint; reuse buys nothing — but the owner should
consciously accept that production would run on a larger-than-approved shape (§9).

### 7.3 Risk

| | A | B |
|---|---|---|
| Clean baseline | INFERRED (no indicators; 1 day exposed, key-only effective) → **PROVED after a free rebuild** | PROVED by construction |
| Wrong size / OS / region at Phase 2 | not possible — already known (PROVED) | possible; rollback = delete |
| Orderability / price surprises | none | CX43 likely unavailable; CPX32 €35.49 |
| Loss of the second vantage point | **yes** — devloop-01 *is* the Phase 7–10 probe source; needs a replacement (U16, §8) | no |
| DevLoop plan | ADR-0011 amendment; executor host deferred to a future purchase | unchanged |
| Everything from Phase 3 onward | identical | identical |

### 7.4 Security

End state identical (SR-1…SR-9, D-D, D-F). A has one extra step: the `devloop_01` key must be
**removed**, not merely joined — SR-4 already says "only `qevik_prod`" and the Phase 3 checklist
verifies a one-line `authorized_keys`. The `devloop_01` private key on the Mac then has no host left
and should be deleted (owner action, no rotation of anything else involved). The rebuild variant
lets the owner select `qevik_prod` in the console so the devloop key never touches the production image.

### 7.5 Migration complexity

Phases 3–11: **unchanged**. Phase 2 for A is *smaller*: no server creation, no product/price
decision, no key-fingerprint-from-a-new-server step; it gains a console rename, an optional
rebuild, the backup add-on toggle, firewall attachment, and one documentation amendment
(ADR-0011). **Zero code changes** beyond what R-12 already requires (no code references this host).

### 7.6 Rollback implications

Cutover rollback (Phase 9, R0–R3, §7.1 of the decision document) is **identical**: it depends only
on the old host staying frozen (AR-4) and Cloudflare origin flipping back. Phase 2 rollback: A =
rebuild back to a bare server (free, nothing lost); B = delete the new server. A has no
"we created something we now regret" branch at all.

### 7.7 Operational simplicity

A: one fewer server in the project during and after migration (2 → 1 after Phase 11 instead of 3 → 2);
one fewer key; one fewer firewall; one fewer backup line. The one complication is naming: the
server was called *devloop* and some Phase 0/1 documents describe it as "DevLoop only, never
production" — those lines are superseded by this assessment and the owner's instruction, and are
listed in §10 for correction on approval.

## 8. New unknown

| # | Item | Blocking? | Resolution |
|---|---|---|---|
| **U16** | Second-vantage probe source once devloop-01 is production | Non-blocking, must be decided before Phase 7 | Candidates: (a) `qevik-core-01` itself, read-only `curl`/`ssh -T` only, under an explicit AR-4 carve-out (it is already the source of truth we are comparing against, so it can probe the *new* host but not itself); (b) a free external checker for HTTPS only; (c) the Mac (unreliable egress — rejected as sole source); (d) the future DevLoop host, when it exists. Recommendation: (a) + (b) during Phases 7–10; nothing needed after Phase 11 beyond Phase 10's monitoring minimum (D-P). |

## 9. Recommendation — and the single decision requested

**Recommend Option A: reuse `qevik-devloop-01` as `qevik-prod-01`.** It is owned, idle,
patched, in the right DC, on the right OS, larger than needed, referenced by no code, holding no
data, and cheaper than adding a third server. The DevLoop plan is retargeted on paper only.

**D-R (owner):** choose one —

- **D-R-1 (recommended):** Reuse with a **free console rebuild** first (Ubuntu 26.04, SSH key =
  `qevik_prod` only, same IPs, same id) so the production image is clean by construction and the
  `devloop_01` key never exists on it. Cost €0; ~2 minutes; loses nothing (§5).
- **D-R-2:** Reuse **as-is** (no rebuild); clean state stays INFERRED; the devloop key is swapped
  for `qevik_prod` inside the AR-2 procedure in Phase 3.
- **D-R-3:** Do not reuse; proceed with Option B (new server per `PHASE_1_COMPLETION_REPORT.md` §8),
  devloop-01 stays reserved for DevLoop (B1), or is deleted by a separate decision (B2).

With D-R-1 or D-R-2 the owner is also confirming, explicitly: (i) production runs on an 8 / 16 / 320
shape (larger than D-B) at the CPX42 rate; (ii) ADR-0011 is amended — the DevLoop executor will be a
different, future server, and DevLoop never runs on production; (iii) the DevLoop-only wording in
the Phase 0/1 documents is superseded.

## 10. Revised Phase 2 — if D-R-1 / D-R-2 is chosen (replaces `PHASE_1_COMPLETION_REPORT.md` §8)

All console steps are the **owner's**. Nothing below happens until the owner's explicit Phase 2 GO
(D-L, full). **No step orders a server.** Only step 5 adds a recurring cost, and step 2 changes one.

| Step | Action | Cost effect | Who | Evidence |
|---|---|---|---|---|
| 0 | Generate `qevik_prod` ed25519 key pair on the Mac; add the **public** key to the Hetzner project (Security → SSH keys). | none | owner (or agent on explicit go) | fingerprint in `evidence/phase-2/host-identity.txt` |
| 1 | Console: **rename** server `qevik-devloop-01` → **`qevik-prod-01`** (free, OBSERVED-3P; no reboot; IPs and id unchanged; the OS hostname is set separately in step 6). | none | owner | screenshot / console read |
| 1a | **D-R-1 only:** console **Rebuild** → Ubuntu 26.04, SSH key **`qevik_prod` only**. Removes everything in §5 (all disposable — Hetzner FAQ: "all saved data will be lost", OBSERVED-3P). Server keeps `164307556`, `91.107.244.253`, IPv6 (rebuild reimages the same server — INFERRED; the console shows the IP before confirming). Record the **new host-key fingerprint** from the console before the first SSH. | none | owner | fingerprint + timestamp |
| 2 | Console: **Backups: enable** (+20 % ≈ €13.90/mo on CPX42) — or confirm already enabled. Confirm/record: product name, price, project, labels, existing snapshots. | +20 % of server price | owner | console read → `host-identity.txt` |
| 3 | Console: create Cloud Firewall `qevik-prod-fw` (in 22/80/443 tcp any + ICMP; out any) and **attach** to the server. | none | owner | rule listing |
| 4 | Agent verifies read-only over SSH (`qevik_prod` after 1a, `devloop_01` under D-R-2): `os-release`, `nproc`, `free`, `lsblk`, `ufw status`, `sshd -T` subset, `apt list --upgradable`; hostname; authorized_keys = 1 line. Second vantage per U16 (§8): 22 open; 80/443 closed until Caddy. | none | agent | `evidence/phase-2/` |
| 5 | Order **Storage Box BX11**, sub-account `qevik-prod-backup`, SFTP; credential to the target's `/root` in Phase 4 only. | **BX11 €3.20/mo** | owner | order confirmation (no credential) |
| 6 | (if in the GO) `apt full-upgrade` + reboot **this host only**; `hostnamectl set-hostname qevik-prod-01`; confirm reboot-required cleared. | none | agent | journal boot id |
| 7 | Documentation: ADR-0011 amendment ("executor host = future server; devloop-01 retargeted to production 2026-09-0x"); DQ-011 note; DQ-014 row; §10 corrections in this document. | none | agent | commit (no push) |

Then Phase 3 as written in `MASTER_MIGRATION_PLAN.md`, with SR-3's **AR-2 two-session procedure**
mandatory (under D-R-2 it also performs the devloop→qevik_prod key swap: add `qevik_prod`, prove
session B with it, remove `devloop_01`, prove session C, disable password auth, prove refusal).

Rollback of the whole of Phase 2: console rebuild back to bare (free). Nothing else depends on the host.

Recurring cost after Phase 2 (excl. VAT, OBSERVED-3P): old host ≈ €35.99 + reused host ≈ €69.99 +
backups ≈ €13.90 + BX11 €3.20 ≈ **€123.08 / mo** for the ≈ 3–4 weeks of migration + observation,
then ≈ **€87.09 / mo** after Phase 11 (old host deleted, snapshot ≈ €0.20/mo for 30 days).

## 11. Documents that change on approval (not yet changed — pending D-R)

| Document | Change |
|---|---|
| `OWNER_DECISION_AND_FINAL_ARCHITECTURE.md` | §1 table row "DevLoop"; §2.1 D-B note (shape larger than approved, no purchase); §4 diagram `qevik-devloop-01 DevLoop only` line; §6 spec table (type/RAM/storage/IP rows become PROVED values); §7.1/§9 unchanged; §10 Phase 2 effort; §12 status |
| `MASTER_MIGRATION_PLAN.md` | Phase 2 objective/allowed/forbidden/evidence/rollback rewritten per §10 above; "touching `qevik-devloop-01`" moves from Forbidden to the approved steps; U16 vantage rule in Phases 7–10 |
| `PHASE_1_COMPLETION_REPORT.md` | §7 N-4 withdrawn → pointer here; §8 superseded by §10 above |
| `MIGRATION_RISK_REGISTER.md` | R-12 unchanged; new R-26 "second vantage lost" (U16); R-25 DevLoop-paused unchanged |
| `docs/decisions/ADR-0011-DevLoop-Executor-Host.md` | Implementation-record entry: server bought 2026-09-02 as CPX42 (not CX43/CX53) ahead of the gates; retargeted to production per D-R; executor host = future server |
| `.qevik/DECISION_QUEUE.md` | DQ-014 status; DQ-011 note |

Already changed in this commit: this document; sanitised evidence file; one-line status pointers in
`OWNER_DECISION_AND_FINAL_ARCHITECTURE.md` §12, `MASTER_MIGRATION_PLAN.md` Phase 2,
`PHASE_1_COMPLETION_REPORT.md` N-4, and the DQ-014 row — all marked "pending D-R".

## 12. Stop

Assessment complete. Waiting for **D-R** (and, with it, the owner's console confirmations of §1
product/price and §5 console-side objects). Until then: no Hetzner action, no rename, no rebuild, no
key change, no DNS, no data movement, no secret rotation, no DevLoop execution, no push.
