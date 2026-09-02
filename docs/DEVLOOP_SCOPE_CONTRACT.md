# Development loop — the allowed-path contract

_What the driver enforces about where a task's diff may go, how it records it,
and what the record does and does not say about tasks that ran before it
existed._

## The failure this replaces

A task's scope used to live in the prose of its brief: "only the repository
module", "do not touch the service". The builder was told; nothing measured.
On `t-b0dfd18dd170` the builder rewrote `service.py`, `db.py` and a second
module alongside the repository it was asked for, and this was found by a
person reading the diff after three review rounds had been spent on it. The
reports written afterwards said "scope held" for later tasks — and every one
of those was somebody looking at the diff, not the loop refusing anything.
That is observational compliance. This document describes the structural
kind, and the correction of the record for the earlier kind.

## What is enforced

Every task row carries `paths`: a JSON list of repo-relative entries, each one
of

| spelling | meaning |
|---|---|
| `packages/kernel/atlas_kernel/opportunity/repository.py` | exactly this file |
| `packages/kernel/tests/` | this directory and everything beneath it |
| `packages/kernel/tests/test_unreviewed*.py` | a glob; `*` stops at `/`, only `**` crosses a directory |

`Queue.add` refuses a task without one, and refuses a contract that bounds
nothing (`*`, `**`, `.`, `/`, an empty list, an absolute path, anything with
`..`). A task cannot enter the queue and be scope-checked against a list that
allows everything.

In `run_task`, after the round's tests pass and the size gate is satisfied,
the driver commits the round and then measures **the committed range**
`base..HEAD` with

    git diff --name-only --no-renames <base>..HEAD

`--no-renames` is deliberate: a file moved out of the contract is a write
outside it, and following the rename would report it as inside. Every changed
path is compared against the contract by `gates.within`. The result is written
to `scope_checks` **whatever the verdict**, keyed on the commit:

| column | holds |
|---|---|
| `task_id`, `round`, `sha` | which task, which round, which immutable commit |
| `declared` | the contract as the task carried it |
| `changed` | every path the range changed |
| `undeclared` | the subset of `changed` no contract entry covers |
| `verdict` | `in_scope` iff `undeclared` is empty — derived, never passed in |

A diff outside the contract is contested at once: `head_sha` is set so the
record names the commit, `.qevik/DECISION_QUEUE.md` gains a block listing the
declared and undeclared paths, the branch is kept, and **no review is
requested** — a finding cannot make an out-of-scope diff landable, so a round
is not spent asking.

The landing gate in `_ship` asks the record, in the same way it asks the
review record:

    if not self.q.review_was_clean(ident):   → CONTESTED
    if not self.q.scope_was_kept(ident):     → CONTESTED
    git merge --squash

`scope_was_kept` is true only when a `scope_checks` row exists for the task's
current `head_sha` with verdict `in_scope`. A head no check measured is
refused. This is what makes the invariant structural rather than a property of
today's control flow: any future route to the squash-merge — a second caller,
a resumed task, a hand-run `_ship` — meets the same refusal.

The builder and the fixer are shown the contract in their prompts. That is a
courtesy so they stop and say `BLOCKED:` rather than wander; it is not the
enforcement, and a test (`test_the_builder_is_shown_its_contract_but_is_not_the_enforcement`)
asserts the gate reads git and nothing about the brief.

## Reading the evidence

    infra/devloop/driver.py scope <task-id>

prints the declared contract and every scope check with its four lists and
verdict. The same rows are in SQLite:

    sqlite3 .qevik/devloop/state.db \
      "select round, sha, declared, changed, undeclared, verdict from scope_checks where task_id='…'"

A person disagreeing with a verdict has everything needed to re-run the
`git diff` themselves.

## Declaring a contract

New work:

    infra/devloop/driver.py enqueue --title … --brief … \
        --path packages/kernel/atlas_kernel/opportunity/repository.py \
        --path packages/kernel/tests/

Production-inspection rules (`infra/devloop/inspection.py`) each declare
`paths` at module level; a rule without one fails
`test_every_production_rule_declares_where_its_work_may_go`.

A row that predates the column has `paths = NULL`. Opening the database adds
the column (`Queue._migrate`) and leaves such rows NULL — the honest record
that no contract was declared, which is not the same as an empty one. The
driver refuses to run them (`BLOCKED: no allowed-path contract`) until a person
declares one:

    infra/devloop/driver.py declare-paths <task-id> --path … --path … \
        --actor ayoub --reason "from the brief's declared scope"

which writes a transition naming the actor and the contract, so the list a
task was landed under is part of its history. A contract cannot be changed
under a task that is in flight.

## What the record says about earlier tasks

Tasks that reached DONE before this gate existed have **no `scope_checks`
row**. That absence is accurate and is not backfilled: the loop did not
measure them, and inserting a row saying it did would be exactly the false
"scope held" this replaces. Where a task's diff was compared against its
brief by hand afterwards, that comparison is recorded as a transition on the
task with `actor` set to the person and the word *observational* in the
reason — never as a `scope_checks` row, which only the driver writes.

## Files

- `infra/devloop/queue.py` — `contract()`, `allowed_paths()`, `paths` column
  and migration, `scope_checks` table, `record_scope`, `scope_was_kept`,
  `scope_checks`, `declare_paths`
- `infra/devloop/gates.py` — `within()`, `scope()`, `Gate.evidence`, `scope`
  in `required()`
- `infra/devloop/driver.py` — refusal without a contract; measure after
  commit, before review; landing gate; `--path`, `declare-paths`, `scope`
- `infra/devloop/agents.py` — contract shown to builder and fixer
- `infra/devloop/projection.py` — `park_out_of_scope`
- `infra/devloop/inspection.py` — `paths` per rule
- `packages/kernel/tests/test_devloop.py` — the "scope contract" section
