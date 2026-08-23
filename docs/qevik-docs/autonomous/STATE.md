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
| P3 AI visibility | IN PROGRESS | — |
| P4 Public audit route | COMPLETE | `41f47b4` |
| P4 Plans surface | TODO | — |
| P5 Marketplace | TODO | — |
| P6 Leads/CRM/email | TODO | — |
| P7 Social/video/autopilot | TODO | — |
| P8 Agency/white label | TODO | — |
| Roadmap completeness audit | TODO | — |
| Business re-evaluation | TODO | — |

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

Full suite 2302 passed / 25 skipped · ruff 22 · mypy 135. Any run that raises
ruff or mypy above these has regressed.
