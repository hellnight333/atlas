# Atlas CI

## Pipeline

GitHub Actions workflow: `.github/workflows/ci.yml`

The CI job runs:

- Ruff linting
- Black formatting check
- mypy type checking
- pytest with coverage threshold and XML report generation

## Failure Policy

Any lint, formatting, type, test, or coverage failure causes CI to fail.

## Coverage Artifact

CI uploads `coverage.xml` as an artifact for inspection.
