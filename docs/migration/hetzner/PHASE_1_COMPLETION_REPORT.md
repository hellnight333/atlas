# PHASE_1_COMPLETION_REPORT — Hetzner production migration

**Date:** 2026-09-03. **Phase:** 1 (decisions + read-only checks + non-destructive preparation).
**Gate ahead:** Phase 2 provisioning — **OWNER GO REQUIRED**; nothing cost-incurring or
infrastructure-creating has been done.

What was done: owner decisions recorded (`evidence/phase-1/decisions.md`); second-vantage
probes from `qevik-devloop-01` and read-only metadata reads on both hosts
(`evidence/phase-1/probes-2026-09-03.txt`); public price-sheet research; documents updated.
What was **not** done: no Hetzner or Cloudflare account action (no API access exists — see §2),
no server, no key generation, no DNS, no data, no secret, no DevLoop task, no push.

Evidence tags: PROVED (observed this session) · OBSERVED-3P (third-party public source) ·
INFERRED · OWNER (only the owner can read it).

## 1. Exact Hetzner server product name and current monthly price

| Item | Value | Tag |
|---|---|---|
| Product name for a 4 vCPU AMD / 8 GB / 160 GB NVMe server in **nbg1** | **CPX32** (the "CPX31" name in the Phase 0 docs is now US-only) | OBSERVED-3P (hetzner.com plan table shows CPX32 for eu-central/NBG1/HEL1; prices not rendered on the page) |
| CPX32 monthly price | **€35.49 / month excl. VAT** (hourly-capped), raised from €13.99 on 2026-06-15 | OBSERVED-3P (northflank.com; costgoat.com "last updated 2026-08-02"); **console confirmation pending (owner)** |
| Add-ons | IPv4 primary IP €0.50/mo · Backups +20 % (€7.10 on CPX32) · Snapshots €0.0143/GB/mo · Storage Box BX11 (1 TB) €3.20/mo | OBSERVED-3P |
| **Total for the approved D-B configuration** | CPX32 €35.49 + IPv4 €0.50 + backups €7.10 + BX11 €3.20 = **≈ €46.29 / month excl. VAT** | derived |
| Cheaper shapes on the same sheet | **CX43** 8 vCPU / 16 GB / 160 GB **€15.99** (total ≈ €22.89) · **CX33** 4 vCPU / 8 GB / 80 GB **€8.49** (total ≈ €13.89). DE/FI only; hetzner.com displayed every CX plan as **"not available"** on 2026-09-03 — orderability in nbg1 is a console fact | OBSERVED-3P |

## 2. Project / account state relevant to provisioning

- **No Hetzner API token, `hcloud` CLI context, or Cloudflare API token exists** on the operator Mac, on `qevik-core-01` (Phase 0: `cloudflare.env` absent) or on `qevik-devloop-01`. PROVED (names-only search). Every Hetzner/Cloudflare read or write is therefore a **console action by the owner**, exactly as the plan assumed.
- Both existing servers are in `region eu-central`, `availability-zone nbg1-dc3` (Hetzner metadata service, PROVED): `qevik-core-01` id 162146484; `qevik-devloop-01` id 164307556.
- Which **project** they sit in, whether that project holds unrelated resources, existing SSH keys registered in the project, existing Cloud Firewalls, and the account's 2FA state: **OWNER** (console → Cloud → project list; Security → SSH keys; Firewalls; account → Security).
- Observation for the owner's attention (not a decision request): `qevik-devloop-01` reads as 8 vCPU / 15 GB / 305 GB AMD Genoa — the shape of a **CPX42**, which the June price change moved to ≈ €69.49/mo. It is currently bare (DevLoop paused). INFERRED from shape; console confirms the type and price.

## 3. Snapshot / image-backup state

- `qevik-core-01` (162146484): backup add-on and snapshots — **OWNER** (console → server → Backups / Snapshots). Phase 0 found no evidence of either from inside the host (nothing can be seen from inside).
- Requirement before Phase 9 (unchanged): one **Hetzner snapshot of the old server** taken by the owner in the hours before cutover (≈ 12 GB used → ≈ €0.20/mo at the snapshot rate). Optionally enable the backup add-on on the old server now for +20 % of its price — owner's call, not required by the plan.

## 4. Region confirmation

**nbg1 (eu-central, nbg1-dc3)** — confirmed as the region for `qevik-prod-01`: same as both existing servers (PROVED via metadata), same legal jurisdiction, enables a Hetzner private network later. CPX32 is listed for NBG1; CX availability there is the console question in §1.

## 5. Cloudflare SSL/TLS mode

- **PROVED not "Flexible"**: the origin answers `308 → https://` on `:80` for all four hostnames, and all sites work through the edge; Flexible would loop.
- **Full vs Full (strict)**: not distinguishable from outside — **OWNER** (dashboard → qevik.ai → SSL/TLS → Overview). Either mode is compatible with copying the LE certificates to the target (D-E), so this does not change the design; it is recorded for the cutover runbook.
- Also read: origin certificates for all four names expire **2026-11-17** (PROVED) — the rollback precondition (§7 of the decision doc) holds for a cutover on or before ~2026-10-04; after that, certificates on the old host will have auto-renewed anyway (Caddy renews at 2/3 lifetime).

## 6. Confirmation of the recommended server specification

The approved D-B specification stands and is what Phase 2 will create unless the owner changes it after the console read:

| Spec | Value |
|---|---|
| Type | **CPX32** — 4 vCPU AMD EPYC (shared), 8 GB RAM, 160 GB NVMe, 20 TB traffic |
| Swap | 2 GB swap file, `vm.swappiness=10` |
| OS | Ubuntu 26.04 LTS |
| Network | primary IPv4 + IPv6 /64 |
| Location | nbg1 |
| Firewall | Hetzner Cloud Firewall: in 22/tcp, 80/tcp, 443/tcp, ICMP; out any; ufw mirror on host |
| Backup | image backup add-on on; Storage Box BX11 sub-account for dump + state tars |

*[agent recommendation, DQ-009 — the owner decides]* Because the price sheet moved, the
like-for-like AMD plan now costs ≈ €35 where a CX43 (8 vCPU / 16 GB / 160 GB) costs ≈ €16 and a
CX33 (4 / 8 / 80 GB) ≈ €8.50. If the console shows CX43 orderable in nbg1, I would take
**CX43** — same 160 GB disk, double the headroom, under half the price; the "no larger class
without evidence" rule was about not paying more, and here the larger class costs less. If only
CX33 is orderable, 80 GB is still 6× today's 12 GB usage and is acceptable. If no CX plan is
orderable, **CPX32** as approved. CPU family (Intel/AMD shared vs AMD EPYC shared) is immaterial
at load 0.25. The old host's true type and current price (console) settle whether the migration
itself lowers or raises the monthly bill.

## 7. Newly discovered blockers or unknowns

| # | Finding | Effect |
|---|---|---|
| N-1 | Hetzner price change 2026-06-15 (CPX ×2.5). Phase 0's "like-for-like cost" assumption was wrong. | D-B re-confirmation at the Phase 2 gate (§6). Not a blocker. |
| N-2 | CX plans shown "not available" on hetzner.com. | Only the console tells whether they can be ordered in nbg1. |
| N-3 | No API access to Hetzner/Cloudflare anywhere. | Every console step is the owner's; the plan already assumed this. Not a blocker. |
| N-4 | `qevik-devloop-01` shape = CPX42 (≈ €69.49/mo post-change), currently idle. | ~~Outside this migration's scope~~ — **withdrawn 2026-09-03** by owner instruction; assessed as the production target in `DEVLOOP01_SUITABILITY_ASSESSMENT.md` (suitable; Option A recommended; D-R pending). §8 below is superseded by that document's §10 if D-R-1/D-R-2 is chosen. |
| N-5 | Cloudflare Full vs Full (strict) still unread. | Runbook detail; not blocking. |

No new blocker for Phase 2 beyond the existing ones: owner GO, U1/U2 console reads, `qevik_prod`
key creation (owner or agent with an explicit go — it is a credential), and the R-12 code change
(parameterise the hard-coded origin IP; owner-reviewed, owner-pushed) which is needed by Phase 4,
not by Phase 2.

## 8. Exact first cost-incurring actions Phase 2 would perform

All in the Hetzner console, **by the owner**, in this order. Billing for a server starts at
creation (hourly, capped monthly); deleting it is the rollback.

| Step | Action | Cost effect | Who |
|---|---|---|---|
| 0 | Generate `qevik_prod` ed25519 key pair on the Mac (`ssh-keygen -t ed25519 -f ~/.ssh/qevik_prod -C qevik_prod`); add the **public** key to the Hetzner project (Security → SSH keys). | none | owner (or agent on explicit go; passphrase choice is the owner's) |
| 1 | Create Cloud Firewall `qevik-prod-fw`: inbound 22/tcp any, 80/tcp any, 443/tcp any, ICMP any; outbound any. | none | owner |
| 2 | **Create server** `qevik-prod-01`: nbg1 · Ubuntu 26.04 · type per D-B re-confirmation (CPX32 unless changed) · IPv4 + IPv6 · SSH key `qevik_prod` only · firewall from step 1 · **Backups: enabled** · no Volume · no private network yet. | **first charge**: server €35.49/mo-capped (or the chosen type) + IPv4 €0.50 + backups 20 % | owner |
| 3 | Record from the console: server id, IPv4, IPv6, **host key fingerprint** (server → Rescue/Console shows it; or read via console once) → `evidence/phase-2/host-identity.txt`. | none | owner reads, agent records |
| 4 | Order **Storage Box BX11**, create sub-account `qevik-prod-backup` limited to its own directory, SFTP enabled. Credential goes only to the target's `/root` in Phase 4 (0600), never to the Mac, chat or repo. | BX11 €3.20/mo | owner |
| 5 | Agent verifies over SSH with `qevik_prod`: `os-release`, `nproc`, `free`, `lsblk`, `ufw status`, `sshd -T` subset, `apt list --upgradable | wc -l`; second vantage from devloop-01: 22 open, 80/443 closed (no Caddy yet). | none | agent |
| 6 | Agent (if included in the GO): `apt full-upgrade` + reboot **the new host only**; confirm reboot-required cleared. | none | agent |

Not part of Phase 2: any change to `qevik-core-01`, `qevik-devloop-01`, Cloudflare, secrets,
DevLoop; installing Qevik components (Phase 4); the old-server snapshot (Phase 8/9).

Expected recurring cost after Phase 2, before decommission: the new server's monthly price
(≈ €46.29 excl. VAT for CPX32 with add-ons, ≈ €22.89 for CX43, ≈ €13.89 for CX33) **in addition
to** the old server for the length of the migration + 14-day observation (≈ 3–4 weeks), then the
old server is deleted (Phase 11) and its snapshot kept 30 days (≈ €0.20/mo).

## 9. Stop

Phase 1 complete. Waiting for: (a) owner console reads for §1 (CPX32 price and CX orderability),
§2 (project, keys, 2FA), §3 (old-server backup/snapshot state), §5 (SSL mode); (b) D-B
re-confirmation or change; (c) **GO for Phase 2** (D-L, full), including whether the agent may
generate the `qevik_prod` key and run step 6.
