# P1.5 — Roadmap / 0→100 Strategy Engine

Implements the 0→100 model in
[`03_QEVIK_0_TO_100_AND_CASE_STUDIES.md`](03_QEVIK_0_TO_100_AND_CASE_STUDIES.md):
given what research actually confirmed about a business, what should it do next,
in what order, and who does each part.

Three modules under `packages/kernel/atlas_kernel/roadmap/`, 31 tests in
`packages/kernel/tests/test_roadmap.py`. Nothing publishes, sends, bills or
connects a provider.

---

## 1. What it is built from

```
Research → Evidence → Readiness → Recommendations → Roadmap
                          ↑                             ↓
                    Measurement ──────────────── re-evaluation
```

Every task in a plan traces to one of exactly four sources, and there is no
fifth branch that can add one:

| Source | Produces | Executability |
|---|---|---|
| A dimension nothing has measured | a measurement task | `MEASURE_FIRST` |
| A recommendation's customer obligations | a customer task | `CUSTOMER_MUST_ACT` |
| A recommendation with a registered capability | work | `QEVIK_CAN_EXECUTE` |
| A confirmed-weak dimension no offer covers | a stated finding | `NO_CAPABILITY` |

`Roadmap.derived_from` records the inputs — observation count, recommendation
ids, which of them were scheduled, every dimension score, and which metrics were
already measured — so a plan can be re-derived and diffed rather than trusted.

## 2. Readiness — `roadmap/readiness.py`

Eight dimensions, each fed only by research features the pipeline genuinely
emits: reachability, conversion, discoverability, AI visibility, content, proof,
technical health, multilingual.

Three rules carry the weight:

- **Unverified lowers confidence, not the score.** A dimension whose inputs are
  mostly unverified reports LOW confidence and keeps whatever its confirmed
  evidence supports. Not having checked AI visibility is our blind spot, not the
  business's weakness.
- **`score is None` is not zero.** A dimension with nothing confirmed either way
  is `unmeasured`, and `unmeasured` is explicitly not `weak`.
- **Weighting is per business model** (catering, café, restaurant, ecommerce,
  B2B service, professional service, logistics, clinic). One global weighting
  would rank every business the same way and produce the same roadmap.

`Readiness.actionable` returns weak dimensions worst-first, scaled by weight.
**A strong dimension cannot appear in it** — that is arithmetic, not a warning
in a document, and it is what stops the plan manufacturing work.

### Difference from the governing document

`03_QEVIK_0_TO_100` lists nineteen dimensions, including video, social,
ecommerce, marketplaces, advertising, CRM, email, analytics and automation.
**Eight are implemented.** The eleven omitted ones have no research signal
behind them today, so scoring them would mean generating a number from nothing —
which the same document forbids two lines later with "Unmeasured ≠ bad."

They are not dropped: the eleven currently have no `SIGNALS` entry, so they
would score `None` and surface as measurement tasks rather than as invented
weaknesses. Adding one is a matter of giving it real signals, not new
machinery. **The document should not change; the implementation grows into it.**

## 3. Models — `roadmap/models.py`

`RoadmapTask` **contains** the existing `Task` from `recommendation.models`
rather than restating it. There is no second task registry, and `QEVIK_TASK` /
`CUSTOMER_TASK` remain the only kinds.

What a plan adds beyond a recommendation: `horizon` (7/30/60/90 day),
`depends_on`, `metric_key` into the measurement catalogue, and
`expected_outcome`.

Two guards refuse construction:

```python
if executability is QEVIK_CAN_EXECUTE and not capability_id:
    raise ValueError("claims Qevik can execute this but names no capability")
if executability is not MEASURE_FIRST and not evidence:
    raise ValueError("has no evidence and is not a measurement task")
```

An unverifiable claim is how a plan promises work nothing can perform, and a
task with no evidence is how it invents a weakness. Both are refused at
construction rather than checked later.

`blocked_by_customer` reads the **task's kind**, not its executability. Keying
it on `CUSTOMER_MUST_ACT` looked equivalent and was not: a measurement task
needing a Search Console grant is `MEASURE_FIRST` *and* waiting on the customer,
and reading only the executability dropped it out of the waiting list.

## 4. Generation — `roadmap/service.py`

Order matters and encodes the rules:

1. **Unmeasured dimensions first.** Proposing a fix for something nobody has
   looked at is how a plan invents a weakness. Skipped when the metric is
   already being measured — re-requesting what a customer already gave is how a
   plan reads as generated.
2. **Filter recommendations against readiness.** A recommendation whose
   dimension is already strong is dropped *before* its customer obligations are
   scheduled. Filtering later left the plan opening with "approve the portfolio
   work" for work that was never going to run.
3. **Customer obligations for surviving work only**, deduplicated by title — a
   shared obligation like approval is listed once and depended on many times.
4. **The work itself, worst dimension first.** Each piece depends only on its
   own recommendation's blocking tasks; depending on every outstanding
   obligation stalls each piece behind all of them.
5. **Confirmed-weak dimensions no offer covers** are stated with
   `NO_CAPABILITY`. Dropping them would make the plan capability-shaped — only
   the weaknesses Qevik sells against would ever appear, which reads to a
   customer as an audit and is not one.

Horizons: the first week is reserved for measurement and customer obligations,
so work starts at 30 days and blocked work sits after its prerequisite by
construction rather than by a rule that could be got wrong.

`changed(previous, current)` reports what re-evaluation moved — added, removed,
rescheduled, readiness delta — because a plan that silently regenerates
invalidates work a customer is part-way through.

## 5. Proof it is not a template

Two real shapes, generated by the same code path:

| | AHS (catering) | Clinic (dental) |
|---|---|---|
| Readiness | 64 | 59 |
| Left alone | conversion, proof, technical health | reachability, conversion, discoverability, multilingual |
| Plan | measure AI visibility · 4 customer obligations · Arabic experience · one-tap contact · editorial hub · *(no capability)* search structure | measure AI visibility · *(no capability)* content, proof, technical health |

**One task in common** — "Measure AI search visibility", because neither has ever
been checked and that is a true fact about both. Every other task differs, and
the dimensions each plan leaves alone are close to the inverse of the other's.

## 6. Negative controls

All eight required, plus the guards' own negative controls:

| Control | Test |
|---|---|
| Identical generic roadmaps | `test_two_different_businesses_do_not_get_the_same_roadmap` |
| Strong dimensions creating tasks | `test_a_strong_dimension_never_produces_a_task`, `…_does_not_drag_in_its_customer_prerequisites`, `test_a_business_strong_everywhere_gets_no_invented_work` |
| UNKNOWN treated as zero | `test_an_unmeasured_dimension_is_not_scored_as_a_failure`, `test_unverified_evidence_lowers_confidence_and_not_the_score` |
| CUSTOMER_TASK silently converted | `test_a_customer_task_is_never_relabelled_as_qevik_work`, `test_every_customer_task_survives_from_its_recommendation` |
| Unavailable capability shown executable | `test_nothing_claims_qevik_can_execute_without_naming_a_capability`, `test_a_weakness_with_no_offer_is_shown_and_not_promised` |
| Dependencies ignored | `test_work_never_precedes_what_it_depends_on`, `…only_on_its_own_prerequisites`, `test_blocked_work_is_not_ready_until_its_prerequisite_is_done` |
| Completion implying success | `test_completing_every_task_asserts_nothing_about_the_business` |
| Causation without evidence | `test_no_rationale_in_a_plan_claims_causation` + `test_the_causation_gate_can_actually_fail` |

Every sentence a customer would read — title, rationale and expected outcome —
is passed through the **P1.4 attribution gate** at `Attribution.UNKNOWN`, the
level a plan written before measurement is entitled to. Not a string blacklist:
the same structured model the measurement layer uses.

## 7. A hole found in the P1.4 gate

Writing control 8 found two causal sentences the gate permitted:

- `"This will drive more leads."` — a promise is an agency claim in the future
  tense, and it is the form a roadmap naturally reaches for.
- `"Bookings grew because of the new pages."` — `"because of Qevik"` was covered
  and bare `"because of"` was not, so the same claim passed whenever it credited
  something other than us.

`measurement/attribution.py` now classifies future-tense promises as `AGENCY`
and generic causal attribution (`because of`, `due to the`, `as a result of`,
`thanks to`) as `ATTRIBUTION`. Both are refused at `UNKNOWN`.

## 8. Two unrelated defects fixed to get a green suite

- **`tests/conftest.py` redirected the database only when `ATLAS_DATABASE_URL`
  was already set.** With nothing set, `db.py` falls back to a default named
  `atlas` — the local working database, and on the server production. The
  P1.1 guard correctly refused to collect the suite at all. The redirect now
  covers the unset case, while `QEVIK_PRODUCTION_DATABASE_URL` is set **only**
  from a deliberately configured URL: the refusal must treat an unrecognised
  database as production, and the detector must not treat a developer's scratch
  database as production. Verified in both directions.
- **`test_every_demo_the_registry_can_select_actually_exists` knew two ways a
  demo could be built and there are now three.** The AHS concept has its own
  generator writing into `dist/`. The guard was doing its job; it now recognises
  a directory with a build script *and* rendered output, and still fails for a
  slug with neither.

## 9. What P1.5 does not do

No credits, billing, portal, external publishing, marketplaces, CRM, social
autopilot or provider integrations. No new task registry, job-state registry or
approval system. A roadmap is persisted as a `BusinessEvent` under a `roadmap`
factory and read back tenant-scoped; there is no new table.

## 10. What remains for P1.6

- **Roadmap → execution.** A `QEVIK_CAN_EXECUTE` task names a capability but
  nothing turns it into a Job. That crossing is where an approved plan becomes
  work somebody agreed to, and it should stay explicit.
- **Task state.** Tasks have no lifecycle yet, so `ready_now(completed)` takes
  completion as an argument. Completion belongs on the event timeline.
- **Measurement wiring.** `metric_key` is a promise the two layers agree on
  terms; nothing yet records a baseline when a measurement task completes.
- **The eleven unimplemented dimensions**, each gated on real research signals.
- **Presentation.** Nothing renders a roadmap for a customer, and that surface
  is where the attribution gate will matter most.
