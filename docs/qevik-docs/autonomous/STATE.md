# Autonomous run — durable state

**This file is the resume point.** If a session ends, work continues from here
rather than from anything remembered.

Authoritative roadmap: `01_QEVIK_PHASE_ROADMAP.md` (P1.2–P1.7, then P2–P8).
No P9+ exists and none has been invented.

## Status

| Phase | Status | Commit |
|---|---|---|
| P1.2–P1.6 | COMPLETE | pre-run |
| P1.7 Credits/Plans | COMPLETE | `9953cc8` |
| P2 Website | COMPLETE | pre-run |
| P2 Content (editorial) | COMPLETE | `eea841e` |
| P2 Multi-page website | TODO | — |
| P2 Media | TODO | — |
| P3 SEO | PARTIAL — detection + execution exist via `offer-website` | — |
| P3 AI visibility | COMPLETE (adapter + fake; live collection PENDING_CREDENTIAL) | `46d618e` |
| Credential centre (`integrations/`) | COMPLETE | `46d618e` |
| Blocker-first action centre (`controlplane/`) | COMPLETE | this commit |
| P4 Public audit route | COMPLETE | `41f47b4` |
| P4 Plans surface | COMPLETE | `200190b` |
| P4 Portal expansion | PARTIAL — reads only, no write routes | — |
| P5 Marketplace | TODO | — |
| P6 Leads/CRM/email | TODO | — |
| P7 Social/video/autopilot | TODO | — |
| P8 Agency/white label | TODO | — |
| Roadmap completeness audit | TODO | — |
| Business re-evaluation | TODO | — |

## Governing documents (read before resuming)

- `01_QEVIK_PHASE_ROADMAP.md` — the numbered roadmap, P1.2–P8.
- `QEVIK_MASTER_AUTONOMOUS_EXECUTION_V2.md` — extends it with the control
  plane, credential centre, agent orchestration and mission control. 2,894
  lines; §3 (blocker-first) and §15/16 are the largest unimplemented parts.
- `QEVIK_PENDING_IMPLEMENTATION_DOCS/` — 13 further specs, **not yet read in
  full**. Contains browser-agent, worker, factory, control-plane and acceptance
  specs that may already define work counted as "remaining" below.

## Standing constraints (do not re-derive)

- One executor registry: `execution/capabilities/EXECUTORS`. Offers with no
  executor must never be presented as executable.
- One quota ledger: `quota.QuotaLedger`. `credits/` reserves against it.
- One approval service: `approval.ApprovalService`. Execution approval and
  artefact approval are distinct actions.
- One credential model: `publication.Connection` — references, never secrets.
- One tenancy module: `opportunity.tenancy`. Cross-tenant reads are *absent*.
- `AIVisibilityObservation` already separates mention / citation / position and
  refuses a position without `position_available`.
- Bundle identity: `execution/artefacts.bundle_hash`, used by execution and the
  publication gate both.

## Baselines

Full suite 2339 passed / 25 skipped · ruff 22 · mypy 135. Any run that raises
ruff or mypy above these has regressed.


## Next unblocked work, in order

1. **P8 agency / white label** — `organization/` already has Organization,
   Membership, Team, Role and `tenant_id`. Verify 1:N org→tenant against the
   schema before changing anything. No external dependency.
2. **P2 multi-page website** — the bundle machinery and `SiteContent` already
   support it; `offer-website` declares only "a page with a title" because that
   is all every build carries today.
3. **P2 media** — `media/providers/mock.py` exists; wire a local vertical slice.
4. **P5/P6/P7 adapters** — follow the `aivisibility` pattern exactly: protocol,
   local fixture provider, `PendingCredentialProvider`, entry in
   `integrations/registry.py`. Only the live call is blocked.
5. **Write routes** on the customer surface (complete a task, request an
   approval) — reads exist, writes do not.

## Not yet read

`QEVIK_PENDING_IMPLEMENTATION_DOCS/` — 13 specs, tracked in the repo, not read
in full. Read these before assuming the list above is complete; they may define
work counted as "remaining".
