# P2.1 — Publication Foundation

`READY_TO_PUBLISH` becomes `PUBLISHED`, once, through a second approval, with a
record that survives.

```
READY_TO_PUBLISH → Publication Target → Connection → Artefact Approval
  → Publish → PUBLISHED → Publication Record → (Measurement, later)
```

This is the first place in Qevik where a failed refusal means a stranger sees
something. Every earlier boundary was internal — a job that should not have run
can be deleted. A page that should not have been published has been read by the
time anybody notices. The whole design follows from that.

---

## 1. Files changed

| File | |
|---|---|
| `publication/models.py` | new — `Connection`, `Destination`, `PublicationRecord` |
| `publication/connections.py` | new — tenant-scoped store, resolve-at-use |
| `publication/gate.py` | new — artefact approval + nine conditions |
| `publication/service.py` | new — `publish`, `stage`, `read`, `to_event` |
| `publication/__init__.py` | new |
| `tests/test_publication.py` | new — 38 tests |
| `execution/service.py` | `publish()` refusal message now points at the real path |
| `tests/test_execution_slice.py` | matches the new message |

**No schema or migration changes.** A publication is a `BusinessEvent`.

## 2. Existing systems reused

- **`PublicationStatus`** from `media.models` — its six values are already
  right, and a second copy would drift.
- **`DeploymentTarget` / `DeploymentTargetRegistry` / `PublishedVersion`** from
  `website.targets` — the publish-then-promote split already existed, designed
  so an artefact can be *reachable but not yet live*. That is exactly the shape
  publication needs, and `stage()` exposes it.
- **`LocalDirectoryTarget`** — the one real target connected. Versioned
  directories and an atomic symlink swap.
- **`ApprovalService` / `ApprovalRequest` / `ApprovalState`** — the third caller,
  after the Media Factory and outreach.
- **`ExecutionOutcome`**, `Asset` provenance, `opportunity.tenancy`,
  `BusinessEvent`, the P1.4 attribution model.

No second publication system, approval system or status enum.

## 3. New models and functions

`Connection` · `ConnectionKind` · `Destination` · `PublicationRecord` ·
`SecretLeak` · `NotPublishable` · `artefact_fingerprint()` · `ConnectionStore` ·
`ConnectionNotFound` · `CredentialUnavailable` · `from_environment()` ·
`filesystem_root()` · `Publishable` · `request_artefact_approval()` · `unmet()` ·
`check()` · `require()` · `stage()` · `publish()` · `to_event()` · `read()` ·
`published_fingerprints()`.

## 4. The two approvals

| | Execution approval (P1.6) | Artefact approval (P2.1) |
|---|---|---|
| Question | Should Qevik perform this work? | May **this exact output** go to **this exact destination**? |
| When | Before anything exists | After it exists and can be looked at |
| Action | `qevik.roadmap.task.execute` | `qevik.publication.artefact.publish` |
| Fingerprint | capability · recommendation · evidence | **content hash** · target · slug · tenant |
| Says | `"publishes": false` | "This makes the artefact live." |

Somebody can want a portfolio system and reject the one that was built.
Collapsing the two would mean the first yes published the second thing unseen,
which is the entire reason `READY_TO_PUBLISH` exists.

Different action names, so a policy can require a different approver for
publication without either module knowing such a policy exists.

## 5. Publication lifecycle

`PENDING_APPROVAL → APPROVED → PUBLISHED | FAILED | REJECTED`, using the
existing enum. Two properties do the work:

- **`PUBLISHED` is written in exactly one place**, after the target returned. A
  test reads the source and asserts both — that it is written once, and that the
  failure path appears before it.
- **A failure is a record, not an exception.** Losing it would leave the
  customer's site in an unknown state with nothing written down. A retry is a
  *new* record; the failed one stays, because "we tried twice and the first
  404'd" is not reconstructable later.

## 6. Connection model — references, never credentials

A `Connection` holds the *name* of a secret: an environment variable, a vault
key, a directory root. Turning it into a credential is a separate act performed
by a resolver at the moment of use, and the result is returned to one caller and
kept nowhere.

Nothing written down can leak because there is nothing there to leak — a
stronger property than remembering to redact, which works until the one log line
nobody thought about.

Three protections:

1. **Construction refuses a credential.** A reference containing `sk-`, `ya29.`,
   `ghp_`, `xoxb-`, `AKIA` or `-----BEGIN` raises `SecretLeak`, naming the
   marker. That value is written to events and reports, so pasting a token into
   it is the mistake that makes everything else here irrelevant.
2. **No tenant, no connection.** A connection with no owner is not shared — it
   is refused, because the other reading is one customer publishing with
   another's credential.
3. **Errors name the reference, never the value**, and never its length or
   shape. An error message is a place credentials leak.

`ConnectionKind` is `FILESYSTEM` (the reference *is* the value and is not
secret) · `API_TOKEN` · `OAUTH`. A kind with no registered resolver cannot be
used, which is the right default for one nobody has implemented.

## 7. Tenant enforcement

Every read is tenant-scoped, and **`resolve()` re-checks ownership** rather than
trusting the object it was handed. That is not belt-and-braces: a `Connection`
is an ordinary value that can be passed anywhere, and the only point at which
being entitled to it actually matters is where it becomes a credential.

Another tenant's connection reads as *absent*, never as "exists but forbidden" —
that answer is itself information. The gate checks tenancy on the execution, the
asset, the connection and the approval independently, and a missing tenant is
refused rather than treated as "any".

## 8. Provenance — immutable, and complete on failure too

tenant · business · recommendation · roadmap task · run · job · asset · content
hash · target · destination · connection id · execution approval · artefact
approval · fingerprint · status · external id · external url · error ·
attempted at · completed at.

Written by one builder for both outcomes, because building the shared part as a
dict and splatting it meant a field could be added to one branch and not the
other — and a record that carries its provenance only when publication
*succeeded* is exactly the record nobody has when they need it.

`summary()` is the only shape that goes into an event, so a field added later is
reviewed once rather than appearing because a `model_dump()` picked it up.

## 9. The nine conditions

tenant · recommendation provenance · job and run provenance · asset provenance
(including that the asset was produced by *this* job) · QA passed · state is
`READY_TO_PUBLISH` · registered target · tenant-owned, resolvable connection ·
artefact approval matching the fingerprint. Plus a duplicate check.

There is no path to "publishable" that consists of not finding a problem.

**One hole found while writing this**: the approval fingerprint covers the
asset's content hash, but `publish()` writes whatever `files` it is handed —
they are a separate argument and nothing compared them. An approval for artefact
A could have published bytes B. The gate now hashes the files and requires a
match. It caught a real mismatch on its first run, where the proof script had
executed under one business name and re-derived under another.

## 10. Negative controls — all twelve required, 38 tests

| Required | Test |
|---|---|
| Without recommendation approval | `test_an_execution_with_no_recommendation_or_job_is_refused` |
| Without artefact approval | `test_publishing_without_the_artefact_approval_is_refused`, `test_the_recommendation_approval_cannot_stand_in_for_it` |
| Without QA | `test_publishing_without_qa_is_refused`, `test_an_unrun_gate_blocks_exactly_as_a_failed_one_does` |
| Before READY_TO_PUBLISH | `test_publishing_before_ready_to_publish_is_refused` |
| Missing credential | `test_a_missing_connection_is_refused`, `test_an_unresolvable_credential_is_refused_before_anything_is_attempted` |
| Another tenant's credential | `test_another_tenants_credential_cannot_be_used`, `…_is_invisible_and_unresolvable` |
| Unsupported target | `test_an_unsupported_target_is_refused`, `test_a_connection_for_a_different_target_is_refused` |
| Invalid asset provenance | `test_an_asset_from_another_job_is_refused`, `test_an_asset_with_missing_provenance_is_refused` |
| Failed publication becoming PUBLISHED | `test_a_failed_publication_never_becomes_published`, `test_a_failure_is_recorded_rather_than_lost`, `test_only_a_target_reporting_success_can_write_published` |
| Duplicate publication | `test_the_same_artefact_is_not_published_twice` + `…_may_go_to_a_different_destination` |
| READY_TO_PUBLISH as PUBLISHED | `test_ready_to_publish_is_not_published`, `test_the_execution_layer_still_cannot_reach_the_outside_world` |
| Success as business success | `test_publication_success_is_not_business_success`, `test_the_record_has_no_field_that_could_read_as_a_result` |

Plus credential-leak controls (`test_a_connection_refuses_to_hold_a_credential`,
`test_no_credential_reaches_the_event_or_the_record`,
`test_the_credential_is_never_in_an_error_message`), the approved-bytes control,
and `test_the_gate_passes_a_genuinely_publishable_artefact` — a check that
refuses everything is not a check.

**Full suite: 2161 passed, 25 skipped.** ruff 35, mypy 135 — both at or below
their pre-existing counts; P2.1 adds none.

## 11. Publication is an intervention, not a result

`PublicationRecord.is_business_result` returns `False`, always, and exists so
the question has a written answer. Code reaching for "did this work" gets a no
from here and has to go to `measurement/`, where the answer depends on evidence.

The record has `status`, `external_id` and `error`, and a test asserts no field
name contains *success*, *improvement*, *uplift*, *roi*, *conversions*,
*revenue* or *worked*.

## 12. Scope held

No Amazon, Noon, Google Ads, social, multi-account publishing, autopilot, CRM,
credits, billing, portal or affiliates. One target is connected: a local
directory a web server serves. The abstraction supports credentialed targets —
`API_TOKEN` and `OAUTH` kinds resolve and are refused when unset — but none is
wired.

## 13. What remains for the next P2 capability

- **A credentialed target.** Everything about the connection model is exercised
  except a real remote host. `CloudflarePagesTarget` and the SSH target already
  exist in `website/targets/` and are the obvious next ones; each needs a
  `Connection` kind and a resolver, not new machinery.
- **The measurement leg.** `publish()` records a timestamp that is exactly the
  `intervention_at` P1.6's `close_measurement()` needs. Nothing yet joins them,
  so no baseline is re-read after a publication.
- **Nothing calls `stage()` before approving.** The preview URL is the real
  artefact on the real host, and an approver should be looking at it rather than
  at a content hash. The function exists; the flow does not use it yet.
- **Publication is not on the roadmap surface.** `presentation.view()` shows
  what will be built, not what is live.
- **No repository persistence.** Records live on the event timeline, which is
  correct, but there is no indexed read for "what is live for this tenant right
  now" beyond folding events.
