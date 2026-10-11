# Design

## Context

See proposal.md - Why. `ruff check src/` reports 40 errors across 11 files. The fix pattern per error code:
- **F401** (unused import): remove the import unless used elsewhere in the file.
- **F841** (unused variable): remove the assignment.
- **F541** (f-string without placeholder): drop the `f` prefix (no `{}` placeholders present).
- **E711** (`x != None`): replace with `x is not None`.
- **E712** (`x == True`): replace with truthy form `x`.
- **E722** (bare `except`): replace with `except Exception:`; do not swallow exceptions silently.

## Goals / Non-Goals

**Goals:**
- Document every remaining lint error (proposal.md) so each can be fixed atomically.
- Provide a per-error fix approach (this design) for the implementation.

**Non-Goals:**
- No runtime behavior changes (all fixes are dead-code removal or style).
- No new specs — the change declares `skip_specs: true`.
- No test additions.

## Decisions

1. **One change per error.** Each of the 40 errors becomes its own change (`fix-<code>-<file>`). This matches how the project already tracked the first fix and keeps PRs small and reviewable.
2. **Order fixes by risk.** Handle `E722` bare-except fixes (`store_selector.py`) with care since they alter exception handling, even though `except Exception:` preserves current semantics.
3. **Verify with ruff.** Each change's verification step re-runs `ruff check src/` and confirms the targeted error is gone and no new ones appear.
4. **Prefer targeted edits.** Where `ruff --fix` can resolve an error automatically, use it; for `E722`, edit manually.

## Risks / Trade-offs

- [E722 changes may subtly alter behavior] → `except Exception:` catches the same exceptions as bare `except` in CPython, but also non-`BaseException` subclasses that a bare `except` might have missed; review `store_selector.py` exception contexts.
- [E711/E712 refactors are safe] → no behavioral impact; SQLAlchemy filters accept `is not None`/truthy forms identically.
- [Removing imports might break other uses] → verify the imported name is unused elsewhere in the file (ruff reports full scope).

## Migration Plan

Not applicable — no persistent state, database, or deployment impact.

## Open Questions

None — each error's fix is self-contained and documented.
