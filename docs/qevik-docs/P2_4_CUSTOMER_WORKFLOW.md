# P2.4 — the customer boundary

The proven engine gets a door. Nine read routes, four small kernel modules, and
one field on `User` — because the thing that was missing was not a dashboard, it
was an answer to *whose data is this*.

---

## 1. Files changed

| File | |
|---|---|
| `customer/api.py` | new — the router |
| `customer/tasks.py` | new — completion needs proof |
| `customer/strategy.py` | new — the paragraph a customer reads |
| `customer/public.py` | new — the unauthenticated boundary |
| `customer/__init__.py` | new |
| `measurement/schedule.py` | new — what is due, no worker |
| `tests/test_customer_workflow.py` | new — 50 tests |
| `auth/models.py`, `auth/store.py` | `User.tenant_id` + `set_tenant` |
| `execution/models.py`, `execution/service.py` | units retained |
| `pyproject.toml` | `customer/api.py` joins the existing B008 router ignore |

## 2. Schema change

One, and genuinely required: `ALTER TABLE qevik_users ADD COLUMN IF NOT EXISTS
tenant_id TEXT NOT NULL DEFAULT ''`. Nothing else could turn an authenticated
request into a `TenantId`, and every customer read needs one.

`''` means **not established**, not "any". Existing operator accounts keep
working on the internal surfaces and reach none of the customer ones.

## 3. Routes

All `GET`, all under `/api/customer`, all requiring `Scope.READ`:

`/me` · `/capabilities` · `/businesses/{id}/research` · `/roadmap` ·
`/strategy` · `/tasks` · `/previews` · `/publications` · `/measurements`

No route takes a tenant in a path, query or header. **A customer cannot ask for
another customer's data because there is no argument in which to ask.**

## 4. Systems reused

`ApprovalService` · `roadmap.presentation.view` and `capabilities` ·
`roadmap.assess`/`generate`/`facts_for` · `measurement.service` ·
`publication.service` and `staging` · `opportunity.tenancy` · `BusinessEvent` ·
the P1.4 claim gate · the existing auth middleware and `Scope`.

No new registry, approval mechanism or job-state vocabulary.

## 5. Tenant enforcement

- **Resolved from the user, never the request.** `current_tenant` raises 403 on
  an empty tenant rather than defaulting — an implicit fallback would make every
  downstream `owns()` check pass for whichever tenant it named, and each one
  would look correct in review.
- **Another tenant's resource is absent, not forbidden.** Identical 404 and
  identical body for "does not exist" and "not yours". 403-vs-404 tells an
  attacker which ids exist.
- **Every read, tested both ways.** Seven routes × A-cannot-see-B and
  B-cannot-see-A. A boundary that holds for six endpoints and leaks on the
  seventh is not a boundary, and the seventh is always the one added last.

Two routes leaked while being written: `previews` and `publications` filtered a
tenant-scoped event list by business id and returned an empty `200` for another
tenant's business — a different answer to "is this mine" than the other five
gave. They now establish the business first.

## 6. Customer task lifecycle — a checkbox is not proof

A customer task is the only work Qevik cannot do, so it is the only one whose
completion Qevik cannot observe by having done it.

| Proof | Means |
|---|---|
| `OBSERVED` | The system checked. `verify_domain` resolves the host. |
| `APPROVAL` | An `ApprovalRequest` reached APPROVED. |
| `ARTEFACT` | The customer supplied something, stored under an id. |
| `ATTESTATION` | The customer said so — **and it records who**. |

`ATTESTATION` exists because some things cannot be checked: *"we have permission
to use these photographs"* is a statement about a contract Qevik cannot read.
Recording it as an attestation with a name is honest; recording it as an
observation is not; recording nothing is how the question gets skipped. An
unsigned attestation is refused.

`complete()` refuses a Qevik task outright — completing our own work on the
customer's behalf is the conversion the distinction exists to prevent, and it
would arrive as a plausible-looking call.

`outstanding()` answers *"what does Qevik need from me?"* and says what each
obligation unblocks. A list with no consequence attached is one people put off.

## 7. Roadmap presentation and the strategy

`view()` from P1.6 already answered the ten questions. P2.4 adds
`strategy.summarise()` — the paragraph somebody reads out on a call, assembled
from the same values the structure carries, so the two cannot disagree.

Derived, never templated. Two rules:

- **A dimension nobody measured is described as unmeasured**, not weak.
  Weaknesses and blind spots are listed in separate groups, capped separately —
  merging them into one ranked top-three buried every unmeasured dimension
  behind the confirmed ones, which is the fact a customer is least able to
  discover for themselves.
- **Every sentence passes the claim gate at UNKNOWN.** A strategy is written
  before anything has been measured, and this is the text most likely to drift
  towards salesmanship.

Two businesses produce different prose and different priorities, because both
come from their own evidence.

## 8. Measurement scheduling — a boundary, not a scheduler

`measurement/schedule.py` answers **"what is due?"** and nothing else. `due()`
returns measurements whose window has closed, oldest first. `plan()` groups
everything by state and reports the waiting-on-a-source group *separately* —
those are not late, and a queue mixing "overdue" with "impossible" trains whoever
reads it to ignore both.

A future worker asks `due()`, reads whatever source is connected, and calls
`close_measurement`. Nothing here reads a metric; a test reads the source to
confirm it cannot.

## 9. Public/private boundary

`customer/public.py` is **allow-list, not redaction**. A public payload is
assembled by naming the fields that may appear, and `guard()` walks the finished
object and refuses anything outside the set. Redaction is a deny-list that
silently passes whatever was added last.

The public audit **counts rather than names**: "four things to fix" is honest;
listing them gives away the work. No tenant, no ids, no evidence, no customer
tasks.

The `qevik.ai → audit → report → opportunities → capabilities → login` flow is
not built. Its boundary is.

## 10. Metering later, without reopening execution

`ExecutionOutcome` now carries `estimated_units` (from the offer) and
`actual_units` (only when a capability reported it). `None` means nobody
counted — never zero work. With tenant, job, run, asset and capability already
on the outcome, every job run before billing exists stays auditable.

**No billing, no credits, no charging.**

## 11. Negative controls — all fifteen, 50 tests

| Required | Test |
|---|---|
| Another tenant | `test_a_customer_cannot_see_another_tenants_business` ×7, `…_is_symmetric` ×7 |
| Another tenant's preview | the previews route in both parametrised sets |
| Another tenant's asset | `test_a_customer_cannot_reach_another_tenants_asset` |
| Approving another tenant's job | `test_a_customer_cannot_approve_another_tenants_job` |
| Publishing another tenant's asset | P2.1 `test_another_tenant_cannot_publish` |
| Execution without customer task completion | P1.6 `test_a_task_with_unresolved_dependencies_cannot_execute` |
| Publication without artefact approval | P2.3 `test_publication_without_artefact_approval_is_refused` |
| Execution approval becoming publication approval | `test_execution_approval_is_not_publication_approval` |
| Missing provider as zero | `test_a_missing_provider_is_unavailable_not_zero` |
| Missing evidence as weakness | `test_missing_evidence_is_never_presented_as_a_weakness` |
| Roadmap mutation | P2.3 `test_re_evaluation_generates_a_new_state_and_leaves_the_old_one` |
| Unsupported capability as executable | `test_a_task_with_no_executor_is_never_offered_as_executable` |
| Customer task becoming a Qevik task | `test_qevik_cannot_complete_its_own_work_as_the_customer` |
| Public endpoint exposing private research | `test_a_public_audit_carries_nothing_private`, `…_guard_refuses_a_field_nobody_allowed` |
| Aggregate leaking tenant counts | `test_no_aggregate_leaks_another_tenants_counts` |

Plus 404-indistinguishability, no-tenant lockout, no-route-names-a-tenant, and
`test_no_handler_reimplements_kernel_logic` — which reads the router's source
and fails on a kernel call it should have delegated.

**Full suite: 2261 passed, 25 skipped.** ruff 22, mypy 135 — both at baseline.

## 12. What is production-ready

The tenant boundary, on every customer read, tested in both directions. Customer
task completion with evidence. The strategy and roadmap surfaces, gated. The
public allow-list. The measurement schedule query. Units retained for later
metering.

## 13. Remaining limitations

- **Reads only.** No route completes a task, requests an approval or triggers
  execution; those services exist and are tested, and exposing them is a
  deliberate next step rather than an oversight.
- **`research_reader` and `plan_reader` are injected.** The router names the
  contract; a deployment supplies the source. Nothing wires them to the
  repository yet.
- **No worker calls `due()`.**
- **No public route.** `public.audit()` exists; nothing serves it.
- **`User.tenant_id` is set administratively.** No signup, no invitation, no
  organization-to-user provisioning flow.
- **No UI.** Deliberately — the objective was the boundary.
