# Proposal

## Why

Ruff reports `F841` in `src/scripts/verify_categories.py:73`: the local variable `sidebar` is assigned a Playwright locator but never used. Leaving dead variable assignments pollutes the codebase with noise, violates the linting standard (`ruff check src/`), and adds maintenance burden. This fix removes the unused variable without affecting behavior.

## What Changes

- `src/scripts/verify_categories.py:73`: remove unused `sidebar` variable assignment.
- No behavior change.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
None.

## Impact

- Affected code: `src/scripts/verify_categories.py`
- No API, dependency, or behavioral impact.
