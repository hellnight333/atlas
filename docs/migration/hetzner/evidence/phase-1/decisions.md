# Phase 1 — owner decisions record (2026-09-03)

Source: owner message 2026-09-03 ("Owner decisions for the Hetzner migration"),
verbatim intent preserved; agent commentary marked *[agent]*.

## Decisions

| ID | Owner decision | Status |
|---|---|---|
| D-A | Approve the proposed target architecture (`OWNER_DECISION_AND_FINAL_ARCHITECTURE.md` §4) as the governing migration design. | **APPROVED** |
| D-B | CPX31-class: 4 vCPU / 8 GB / ~160 GB NVMe + 2 GB swap, subject to confirming the exact current Hetzner product name and price in the console before provisioning. No upgrade to a larger class without evidence from actual load or capacity requirements. | **APPROVED** — *[agent] see §"Open item on D-B" below: the exact product name for nbg1 is CPX32, and post-2026-06-15 pricing changes the cost comparison; the owner re-confirms the type at the Phase 2 gate.* |
| D-C | Hetzner Storage Box sub-account = the independent off-host backup target; Hetzner image backup add-on on; a Volume is never the only backup mechanism. | **APPROVED** |
| D-D | Cloud Firewall + ufw mirror; public ingress only 22/80/443; no `:8443` door; SSH key-only; Cloudflare origin-IP restriction deferred to post-migration hardening (D-Q). | **APPROVED** |
| D-F | Dedicated `qevik_prod` SSH key; `naml_hetzner` never authorised on the new host. | **APPROVED** |
| D-L | Phase 1 read-only console checks and all non-destructive preparation work. **Not** blanket approval for provisioning or any cost-incurring Hetzner action. | **APPROVED FOR PHASE 1 ONLY** |

Not yet decided (unchanged): D-E, D-G, D-H, D-I, D-J, D-K, D-M, D-N, D-O, D-P, D-Q.

## Additional owner requirements (binding from 2026-09-03)

| # | Requirement | Where it now lives |
|---|---|---|
| AR-1 | Rollback policy must state explicit RPO and RTO (maximum acceptable data-loss window and expected rollback time) before Phase 9 cutover approval; "minutes of writes may be lost" is not acceptable wording. | `OWNER_DECISION_AND_FINAL_ARCHITECTURE.md` §7 (proposed numbers, for approval at D-M); `MASTER_MIGRATION_PLAN.md` Phase 8 evidence + Phase 9 prerequisites |
| AR-2 | SSH hardening uses a safe two-session procedure: install `qevik_prod` key → prove a fresh independent session with that key → prove password auth refused → prove reconnect → only then finalise. Never a disconnect-and-reconnect gamble. | `MASTER_MIGRATION_PLAN.md` Phase 3; `OWNER_DECISION…` §9 SR-3 |
| AR-3 | Preserve the single-host architecture. No Docker, Kubernetes, replicas, managed DB, Prometheus or additional infrastructure unless a concrete requirement emerges. | `OWNER_DECISION…` §3.8 (already), §4 |
| AR-4 | Old production host untouched except explicitly approved migration/rollback steps; rollback-capable throughout the observation period. | `OWNER_DECISION…` §7 invariant; plan Phases 5–11 "Forbidden" lines |
| AR-5 | DevLoop remains paused. No DevLoop tasks, provisioning, DNS changes, data migration or secret rotation unless explicitly approved at the next gate. | standing; `EXECUTIVE_MIGRATION_READINESS_REPORT.md` header |

## T1–T10 mapping (draft architecture §10 → decided state)

| T | Item | State after 2026-09-03 |
|---|---|---|
| T1 | size / region / disk / backup add-on | D-B + D-C decided; exact product re-confirmed at Phase 2 gate |
| T2 | off-host backup | D-C decided (Storage Box sub-account) |
| T3 | cloud firewall | D-D decided |
| T4 | `:8443` | D-D decided: removed |
| T5 | certs copy vs re-issue | open (D-E) — Phase 4 |
| T6 | dedicated key | D-F decided |
| T7 | swap | D-B decided: 2 GB |
| T8 | `qevik_test` | open (D-G) — Phase 5 |
| T9 | backup failure visibility | D-C decided in principle; implementation approval in Phase 10 |
| T10 | retarget strategy | open (D-H) — before Phase 4 |

## UNKNOWNs touched in Phase 1

| U | Result |
|---|---|
| U1 | Hetzner console state: **still owner-only** — no API token or `hcloud` context exists on the Mac or on either host (evidence: `probes-2026-09-03.txt`). Public price sheet recorded instead; console confirmation pending. |
| U2 | Cloudflare SSL mode: **PROVED not Flexible** (origin :80 answers 308 for all four hosts and the sites work through the edge). Full vs Full (strict): owner dashboard read pending. Either is compatible with copying the LE certs (D-E). |
| U3 | External alerting: unchanged (none found anywhere reachable); D-P adds one. |
| U8 | Peak usage: unchanged UNKNOWN. |

## Open item on D-B (owner re-confirms at the Phase 2 gate)

Facts found in Phase 1 (third-party price sheets, not the console — see probes file):

1. The 4 vCPU / 8 GB / 160 GB AMD plan sold in nbg1 today is named **CPX32**. "CPX31" is now a US-only name. The old host's shape (4 vCPU Genoa / 7.7 GB / 152.6 G) matches that family.
2. Hetzner raised CPX prices on **2026-06-15**: CPX32 €13.99 → **€35.49/mo**; CPX42 €25.49 → €69.49/mo (excl. VAT, excl. €0.50 IPv4).
3. The CX line (Intel/AMD shared) is far cheaper in DE/FI — **CX33** 4/8/80 GB €8.49; **CX43** 8/16/160 GB €15.99 — but hetzner.com displayed every CX plan as "not available" when read on 2026-09-03. Whether it is orderable in nbg1 is a console fact (U1).
4. *[agent, correction]* The Phase 0 design assumed "CPX31-class = like-for-like cost". After the June change that is no longer true; the like-for-like AMD plan is ~2.5× the price it was.

Consequence: D-B as approved (CPX32, €35.49 + IPv4 + 20 % backups ≈ €43/mo + Storage Box €3.20) remains valid and is what Phase 2 will provision **unless** the owner, seeing CX43 or CX33 orderable in the console, chooses one of them. This is a re-confirmation, not a new decision made by the agent: the agent's recommendation is in `PHASE_1_COMPLETION_REPORT.md` §6.
