# Design

## Context

See proposal.md - Why. The fix targets `src/scripts/verify_categories.py:73`.

## Goals / Non-Goals

**Goals:**
- Remove the unused `sidebar` local variable assignment to satisfy `F841`.

**Non-Goals:**
- No refactoring of the locator logic or the category verification flow.

## Decisions

Remove the `sidebar = self.page.locator(...).first` assignment at line 73. The variable is never read; deleting it is safe and has no side effects (Playwright locators are lazy — no call is made to the browser until `.first` resolves, and even then it is unused).

No design alternatives: this is a one-line dead-code removal.

## Risks / Trade-offs

- [None expected] — removing an unused variable cannot alter runtime behavior.

## Migration Plan

Not applicable — no persistent state or migration involved.

## Open Questions

None.
