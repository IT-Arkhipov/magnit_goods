# AGENTS.md

Agent instructions for the magnit_goods project — a FastAPI web server for tracking Magnit retail store prices.

## Running the server

```bash
# From project root
python -m uvicorn src.server.main:app --host 0.0.0.0 --port 8000 --reload
```

Server runs on http://localhost:8000. Do NOT use `npm run dev` or similar — this is a Python project.

## Environment setup

Copy `.env.example` to `.env` and set:
- `STORE_CODE` — Magnit store code (e.g., "992104")
- `STORE_TYPE` — Store type (e.g., "Мини")
- `GOODS_URL` — API endpoint (default: https://magnit.ru/webgate/v1/goods)

The server updates `.env` automatically when user selects a store via `/api/stores/select`.

## Database

SQLite at `src/data/magnit.db` (gitignored). Tables auto-created on startup via `init_db()` in `main.py`.

**Migration quirks:**
- `migrate_store_ids()` runs on startup — converts integer IDs to MD5 hash strings (12 chars)
- `migrate_categories()` runs on startup — updates category table structure if needed
- Store IDs are `MD5(store_code|store_type|full_address)[:12]`, NOT auto-increment integers

## Project structure

```
src/
├── server/
│   ├── main.py              # FastAPI app, migrations, page routes
│   ├── database.py          # SQLAlchemy engine, session, init_db()
│   ├── models.py            # Store, Category, Product, PriceHistory, ScanJob
│   ├── schemas.py           # Pydantic request/response models
│   ├── scheduler.py         # APScheduler for price updates
│   ├── routes/              # API endpoints
│   │   ├── stores.py        # Store CRUD, scan, select
│   │   ├── catalog.py       # Categories, products (full replacement update)
│   │   ├── prices.py        # Price history, alerts
│   │   └── jobs.py          # Background job status
│   ├── services/
│   │   ├── magnit_api.py    # MagnitAPIClient (rate limit: 0.5s)
│   │   ├── catalog_scanner.py
│   │   ├── catalog_updater.py  # Catalog update service (replace_all_categories)
│   │   ├── price_tracker.py
│   │   └── notifications.py
│   └── templates/           # Jinja2 HTML
└── data/
    ├── magnit.db            # SQLite database
    └── categories.json      # Root categories definition (14 items)
```

## API rate limiting

`MagnitAPIClient` enforces 0.5s delay between requests to avoid rate limits. Do NOT remove `_rate_limit_wait()` calls.

## Store scanning workflow

Two-step process:
1. `POST /api/stores/preview` — search by address, return results with checkboxes (no DB save)
2. `POST /api/stores/add-selected` — save selected stores to DB

Deduplication by `store_code`. Existing stores shown as "(уже в базе)" in preview.

## Category tracking

80 categories in DB (14 root + 66 subcategories). Hierarchical tree with parent-child sync:
- Selecting parent → auto-selects all children
- Partial selection → parent shows indeterminate state
- State persists in `categories.is_tracked` column

Load categories: run `src/server/services/load_catalog_from_json.py` (one-time setup).

**Catalog update logic:**
- Button "Обновить каталог" performs complete category replacement
- First fetches all categories from Magnit API, then clears DB and repopulates
- Preserves `is_tracked` settings for categories with matching `magnit_id`
- If API fails, DB remains unchanged (error displayed to user)

## Background jobs

`ScanJob` model tracks async operations. Status: `pending`, `running`, `completed`, `failed`.

**Important:** On server restart, `_mark_all_running_failed_on_startup()` marks all running jobs as failed (prevents stale state).

## Testing

No test framework configured. Use manual testing via:
- Swagger UI: http://localhost:8000/docs
- Web pages: `/`, `/catalog`, `/products`, `/deals`, `/jobs`

Root test files (`test_*.py`) are ad-hoc scripts, not pytest suites.

## Development status (2026-04-17)

**Completed:**
- Module 1: Stores (CRUD, scan, select) — 100%
- Module 2: Catalog (categories, UI) — 100%

**In progress:**
- Product scanning by category
- Price monitoring and history
- Discount alerts

See `IMPLEMENTATION_PLAN.md` and `NEXT_STEPS.md` for roadmap.

## Common pitfalls

- Store IDs are strings (MD5 hashes), not integers — use `store_hash_id()` helper
- Don't bypass rate limiting in `magnit_api.py` — API will block requests
- Migrations run automatically on startup — don't manually alter tables
- `.env` is auto-updated by `/api/stores/select` — don't edit manually during runtime
- Server must run from project root (`D:\pythonProjects\magnit_goods`) for correct paths
- Catalog update uses complete replacement logic — don't interrupt the process during update

## Language

Code comments and docstrings are in Russian. Commit messages use Russian format: `<тип>: <описание>`.
