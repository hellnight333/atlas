# Contributing to Atlas

Atlas is source-available under the [Business Source License 1.1](LICENSE) and
maintained by one person. Contributions are welcome, with the caveats below
stated plainly so nobody wastes an afternoon.

## Before you write code

**Open an issue or discussion first** for anything beyond a bug fix, typo, or
documentation improvement. Atlas has a written architecture
([`CLAUDE.md`](CLAUDE.md)) and deliberate scope limits, and a PR that conflicts
with either will be closed regardless of how good the code is. A five-minute
conversation beforehand avoids that.

### The one architectural rule

> **No studio may call a provider directly.** All capability flows through the
> kernel.

A PR that breaks this does not merge. There is a contract test enforcing it,
along with one that keeps object construction inside the composition root.

### Deliberately out of scope

Not "unbuilt" — **not wanted**: a marketplace, billing, a cloud or SaaS
offering, mobile apps, a remote worker daemon, a separate vector database, and
autonomous agents that act without human approval. `CLAUDE.md` explains why.

## Licensing of contributions

By opening a pull request you agree that your contribution is licensed under
the Business Source License 1.1, and that the Licensor may also distribute it
under the Change License (Apache-2.0) when the Change Date arrives, and may
offer it under separate commercial terms.

If you cannot agree to that, please open an issue describing the fix instead
of a PR. That is a legitimate way to help and it will be credited.

## Setting up

```bash
git clone https://github.com/hellnight333/atlas.git
cd atlas
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd apps/desktop && npm install && cd ../..
pre-commit install
```

You need PostgreSQL 14+ running for the kernel tests. See
[`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md).

## Before you open a PR

All four gates must pass. CI runs exactly these:

```bash
ruff check .
black --check .
mypy packages/kernel/atlas_kernel
python -m pytest packages/kernel/tests          # coverage gate: 90%
cd apps/desktop && npx tsc --noEmit && npm run build && npm run lint
```

Two things that will save you a confused hour:

- **Do not run the test suite twice at once.** Tests share one database and
  several assert "no new work was created" by comparing row counts. A parallel
  run makes them fail even though nothing is wrong.
- **The test database persists between runs.** Generate unique ids in tests —
  a fixed id passes once and fails forever after.

## What makes a PR easy to merge

- One concern per PR.
- A test that fails before your change and passes after.
- Comments that explain *why*, not *what*. The code already says what.
- Match the surrounding style rather than introducing a new one.
- If you fix a bug, say what the user-visible symptom was.

## What will be sent back

- Reformatting or renaming unrelated to the change.
- New abstractions with one caller. Atlas's fourth principle is "never
  over-engineer" and it is enforced.
- Speculative configuration options.
- Anything that lowers the coverage gate.
- New third-party dependencies without a stated reason. Every dependency ships
  in the installer and must be added to `NOTICE` with its real license.

## Reporting bugs and security issues

Bugs: use the issue template — the diagnostics export field matters.
Security: read [`.github/SECURITY.md`](.github/SECURITY.md). Never file a
security problem as a public issue.
