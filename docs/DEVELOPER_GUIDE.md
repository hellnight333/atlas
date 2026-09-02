# Atlas Developer Guide

## Setup

1. Install Python 3.11+.
2. Install Node.js 22+ (`node --version`). The console regression proof in
   `packages/kernel/tests/test_app_composition.py` executes the Opportunities
   view under node, and the suite fails deliberately when it is absent rather
   than skipping; deselect it knowingly with `-m "not integration"`.
3. Install dev dependencies:
   `python -m pip install -e '.[dev]'`
4. Install pre-commit hooks:
   `pre-commit install`

## Daily Commands

- Ruff: `python -m ruff check packages/kernel workers`
- Black: `python -m black packages/kernel workers`
- Mypy: `python -m mypy packages/kernel/atlas_kernel`
- Tests: `python -m pytest packages/kernel/tests`

## Architectural Guardrails

- Do not bypass the Event Bus.
- Do not bypass the Capability Layer.
- Every execution path must flow through an Execution Decision.
- Do not construct core runtime subsystems outside the composition root.

## Pre-commit

Pre-commit runs Ruff, Black, mypy, whitespace cleanup, and architecture contract tests before commit.

## Coverage

Pytest is configured to generate terminal and XML coverage reports with a 90% minimum threshold for `packages/kernel/atlas_kernel`.
