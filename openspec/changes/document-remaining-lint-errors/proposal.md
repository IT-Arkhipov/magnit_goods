# Proposal

## Why

After auditing with `ruff check src/`, 40 lint errors remain beyond the already-fixed `F841` in `verify_categories.py`. These span 11 source files across unused imports, unused variables, f-strings without placeholders, None/True comparison anti-patterns, and bare `except` clauses. Left uncleaned, they accumulate technical debt, obscure real warnings, and violate the project's own linting standard (`ruff check src/` per `AGENTS.md`). This change documents every remaining error so each can be fixed in a focused follow-up change.

## What Changes

- **No code changes.** This is a documentation-only change. It records all 40 remaining lint errors (file, line number, error code, and short description) in planning artifacts so they can be addressed one by one in follow-up changes.
- Each error will be fixed in its own `fix-<error-type>-<file>` change to keep fixes small and reviewable.

### Error Summary

| # | File | Line | Code | Description |
|---|------|------|------|-------------|
| 1 | src/scripts/verify_categories.py | 121 | F541 | f-string without placeholder |
| 2 | src/scripts/verify_categories.py | 123 | F541 | f-string without placeholder |
| 3 | src/server/database.py | 344 | E711 | Comparison to `None` should use `is not None` |
| 4 | src/server/database.py | 460 | F401 | `sqlalchemy.inspect` imported but unused |
| 5 | src/server/routes/catalog.py | 222 | E711 | Comparison to `None` should use `is not None` |
| 6 | src/server/routes/catalog.py | 237 | E712 | Avoid equality comparisons to `True` |
| 7 | src/server/routes/catalog.py | 273 | F401 | `sqlalchemy.func` imported but unused |
| 8 | src/server/routes/catalog.py | 399 | E712 | Avoid equality comparisons to `True` |
| 9 | src/server/routes/catalog.py | 550 | F541 | f-string without placeholder |
| 10 | src/server/routes/catalog.py | 552 | F541 | f-string without placeholder |
| 11 | src/server/routes/catalog.py | 582 | F401 | `traceback` imported but unused |
| 12 | src/server/routes/catalog.py | 593 | E711 | Comparison to `None` should use `is not None` |
| 13 | src/server/routes/catalog.py | 813 | E712 | Avoid equality comparisons to `True` |
| 14 | src/server/routes/prices.py | 4 | F401 | `fastapi.Body` imported but unused |
| 15 | src/server/routes/prices.py | 7 | F401 | `datetime.date` imported but unused |
| 16 | src/server/routes/prices.py | 7 | F401 | `datetime.timedelta` imported but unused |
| 17 | src/server/routes/prices.py | 11 | F401 | `ScanJobResponse` imported but unused |
| 18 | src/server/routes/stores.py | 1 | F401 | `fastapi.Request` imported but unused |
| 19 | src/server/routes/stores.py | 7 | F401 | `time` imported but unused |
| 20 | src/server/scheduler.py | 8 | F401 | `sqlalchemy.orm.Session` imported but unused |
| 21 | src/server/scheduler.py | 60 | F541 | f-string without placeholder |
| 22 | src/server/services/catalog_scanner.py | 7 | F401 | `sqlalchemy.func` imported but unused |
| 23 | src/server/services/catalog_scanner.py | 11 | F401 | `os` imported but unused |
| 24 | src/server/services/catalog_scanner.py | 248 | F401 | `traceback` imported but unused (inside except) |
| 25 | src/server/services/catalog_scanner.py | 383 | F541 | f-string without placeholder |
| 26 | src/server/services/catalog_scanner.py | 583 | F401 | `traceback` imported but unused (inside except) |
| 27 | src/server/services/catalog_scanner.py | 603 | F841 | `yesterday` assigned but never used |
| 28 | src/server/services/catalog_updater.py | 5 | F401 | `os` imported but unused |
| 29 | src/server/services/catalog_updater.py | 13 | F401 | `Store` imported but unused |
| 30 | src/server/services/category_verifier.py | 100 | F541 | f-string without placeholder |
| 31 | src/server/services/category_verifier.py | 103 | F541 | f-string without placeholder |
| 32 | src/server/services/category_verifier.py | 110 | F541 | f-string without placeholder |
| 33 | src/server/services/magnit_api.py | 22 | F401 | `REVERSE_STORE_TYPE_MAP` imported but unused |
| 34 | src/server/services/magnit_api.py | 240 | F841 | `product_name` assigned but never used |
| 35 | src/server/services/product_opener.py | 26 | F541 | f-string without placeholder |
| 36 | src/server/services/store_selector.py | 67 | E722 | Do not use bare `except` |
| 37 | src/server/services/store_selector.py | 88 | E722 | Do not use bare `except` |
| 38 | src/server/services/store_selector.py | 114 | E722 | Do not use bare `except` |
| 39 | src/server/services/store_selector.py | 150 | E722 | Do not use bare `except` |
| 40 | src/server/services/store_selector.py | 186 | E722 | Do not use bare `except` |

## Capabilities

### New Capabilities
None.

### Modified Capabilities
None.

## Impact

- **No implementation impact**: this change only documents errors.
- Follow-up changes will edit 11 source files (`verify_categories.py`, `database.py`, `routes/catalog.py`, `routes/prices.py`, `routes/stores.py`, `scheduler.py`, `services/catalog_scanner.py`, `services/catalog_updater.py`, `services/category_verifier.py`, `services/magnit_api.py`, `services/product_opener.py`, `services/store_selector.py`).
- 7 `E722` bare-except fixes in `store_selector.py` are the only ones that may change runtime exception-handling behavior (should be treated with care).


/opsx-apply fix-f541-verify_categories-warning-messages