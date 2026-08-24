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
| P2 Multi-page website | COMPLETE | `HEAD` |
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
| Business re-evaluation (§18) | COMPLETE — run as a real mission | `5655ee3` |
| Credential vault (§17) | COMPLETE | `e8a5eec` + `e432f5c` |
| Credential centre HTTP | COMPLETE | `a05ce30` + `e432f5c` |
| Mission control HTTP (§12) | COMPLETE | `a05ce30` |
| Worker as its own process | COMPLETE — proven by subprocess test | `a05ce30` |

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

Full suite 2579 passed / 25 skipped · ruff 22 · mypy 135. Any run that raises
ruff or mypy above these has regressed.

**A green suite does not mean the repository is complete.** Two commits reported
adding the credential vault and added only its tests: `.gitignore` carried a
generic `credentials/` rule that also matched the source package, and every test
passed locally because the files were on disk. `test_repository_completeness.py`
now asks git rather than the filesystem. Treat a passing suite as evidence about
this working copy, not about a clone.


## Reconciliation done

`ROADMAP_RECONCILIATION.md` and `MASTER_EXECUTION_STATE.md` are now the
execution map. The pending docs are a **second programme** (Phase 1–12,
execution platform) and docs 11/11A a **third** (media business). P1–P8 remains
authoritative. Do not renumber.

## Next unblocked work, in order

1. **Customer write routes** — complete a task with proof, request an approval.
   The services exist and are tested; only the routes are missing.
2. **P2 media** — `media/providers/mock.py` exists; wire a local vertical slice.
3. **Chat intake → plan → approval** with the conversation persisted, feeding
   `POST /api/missions`. The mission surface accepts a title and description
   today; nothing turns a conversation into one.
4. **P5/P6/P7 adapters** — follow the `aivisibility` pattern exactly: protocol,
   local fixture provider, `PendingCredentialProvider`, entry in
   `integrations/registry.py`. Only the live call is blocked.
5. **Live provider probes** for the credential centre. `POST
   /api/credentials/{provider}/test` returns 501 for every provider until
   `app.state.credential_probes` is populated — deliberately, because a probe
   that guessed would be worse than none.

## What multi-page generation actually decided

The split is driven by content and is not a setting. A page is kept only if,
once rendered, it clears `THIN_CONTENT_CHARS` — **imported from
`opportunity/detectors/website.py`, never restated** — and a site splits only if
at least two pages earn it. An earlier version used three invented thresholds
and shipped a 222-character contact page: the exact defect Atlas detects on
strangers' sites and sells the fix for. Tightening the detector now tightens the
generator in the same commit.

## Not yet read

`QEVIK_PENDING_IMPLEMENTATION_DOCS/` — 13 specs, tracked in the repo, not read
in full. Read these before assuming the list above is complete; they may define
work counted as "remaining".
