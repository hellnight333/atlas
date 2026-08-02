# What this changes

<!-- One or two sentences. If it fixes a bug, say what the user saw. -->

Closes #

## Why

<!-- The reasoning. What was wrong, or what became possible. -->

## How it was verified

<!-- Not "tests pass" — what did you actually exercise? -->

- [ ] `ruff check .`
- [ ] `black --check .`
- [ ] `mypy packages/kernel/atlas_kernel`
- [ ] `python -m pytest packages/kernel/tests` (90% coverage gate)
- [ ] `npx tsc --noEmit && npm run build && npm run lint` (if desktop changed)
- [ ] Exercised against a running Atlas, not only the test suite

## Checklist

- [ ] No studio calls a provider directly
- [ ] Object construction stays in the composition root
- [ ] New dependencies (if any) are added to `NOTICE` with their real license
- [ ] The coverage gate is unchanged
- [ ] I agree my contribution is licensed per [CONTRIBUTING.md](../CONTRIBUTING.md)
