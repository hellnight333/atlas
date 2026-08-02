# Atlas Testing

## Test Suites

- Behavioral tests: kernel runtime behavior and API compatibility
- Architecture contract tests: frozen architectural rules
- Documentation validation tests: internal link and ADR consistency checks

## Commands

- Full suite: `python -m pytest packages/kernel/tests`
- Architecture only: `python -m pytest packages/kernel/tests/test_architecture_contracts.py`
- Docs validation only: `python -m pytest packages/kernel/tests/test_docs_validation.py`

## Coverage

Coverage is enforced with `--cov-fail-under=90` and reported in terminal plus `coverage.xml`.

## Contract Coverage

Contract tests assert:

- shared EventBus identity
- workflow engine never selects providers
- execution policy never executes jobs
- executors never choose providers
- providers never choose executors
- capabilities remain provider-agnostic
- assets always belong to a project
- composition root remains the only construction point
