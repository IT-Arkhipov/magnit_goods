# Product Scanning Implementation Plan

**Status:** Planning phase (2026-04-14)  
**Decision:** Use `magnit_id` only (no separate `code` column)

---

## Executive Summary

The product scanning workflow from the Catalog widget is ~70% complete but has 3 critical blockers:

1. **Missing module:** `load_catalog_from_json.py` doesn't exist (imported in routes/catalog.py:115)
2. **Data model mismatch:** `catalog_scanner.py` tries to access `Category.code` which doesn't exist in the model
3. **API integration:** Scanner needs to pass `magnit_id` (integer) to API, not string codes

Once fixed, the workflow will be fully functional:
- User selects categories in `/catalog` UI
- Clicks "Сканировать товары" → triggers async scan job
- Background scanner fetches products by category from Magnit API
- Products saved to DB with price history and daily snapshots
- UI polls job status with real-time progress updates

---

## Critical Issues & Fixes

### Issue #1: Missing `load_catalog_from_json.py` Module

**Location:** `src/server/routes/catalog.py:115`  
**Impact:** Cannot load categories from JSON file  
**Severity:** CRITICAL - blocks initial category setup

**Solution:**
Create `src/server/services/load_catalog_from_json.py` that:
- Reads `magnit_catalog.json` from project root
- Parses hierarchical structure (root categories + subcategories)
- Inserts into Category table with parent-child relationships
- Sets `magnit_id`, `name`, `url`, `parent_id` fields
- Returns summary: `{"scanned": N, "added": N, "updated": N}`

---

### Issue #2: Category Model Mismatch

**Location:** `catalog_scanner.py` lines 77, 151, 184, 234, 273  
**Problem:** Code tries to access `Category.code` but model only has `magnit_id`  
**Severity:** CRITICAL - causes AttributeError at runtime

**Current model (models.py:53-72):**
```python
class Category(Base):
    id = Column(Integer, primary_key=True)
    magnit_id = Column(Integer, nullable=True)  # Use this
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    is_tracked = Column(Boolean, default=False)
```

**Solution:** Update `catalog_scanner.py` to use `magnit_id` instead of `code`:

| Line | Current | Fix |
|------|---------|-----|
| 77 | `Category.code == cat_data["code"]` | `Category.magnit_id == cat_data["magnit_id"]` |
| 92 | `code=cat_data["code"]` | Remove (not in model) |
| 151 | `[cat.code for cat in categories]` | `[cat.magnit_id for cat in categories]` |
| 184 | `Category.code == cat_code` | `Category.magnit_id == cat_code` |
| 234 | `Category.code == cat_code` | `Category.magnit_id == cat_code` |
| 273 | `Category.code == category_code` | `Category.magnit_id == category_code` |

---

### Issue #3: API Category ID Type

**Location:** `catalog_scanner.py:198-202` and `magnit_api.py:98-140`  
**Problem:** Scanner passes `magnit_id` (integer) to API, need to verify API accepts it  
**Severity:** HIGH - API may reject wrong type

**Current flow:**
```python
# catalog_scanner.py:198
result = self.api.get_products(
    category_ids=[cat_code],  # Will be integer magnit_id
    store_code=self.store_code,
    limit=50,
    offset=offset,
)
```

**Solution:** Verify Magnit API accepts integer category IDs in `categories` field

---

## Data Flow After Fixes

```
1. LOAD CATEGORIES (One-time setup)
   POST /api/categories/load-from-json
   → Inserts 18 root + 123 subcategories into DB
   → Sets magnit_id, name, url, parent_id relationships

2. USER SELECTS CATEGORIES (catalog.html)
   GET /api/categories/tree
   → Returns hierarchical tree with is_tracked status
   POST /api/categories/update-tracking
   → Sets is_tracked=True for selected IDs

3. TRIGGER SCAN (catalog.html button)
   POST /api/catalog/scan-all-stores
   → Creates ScanJob (status: pending)
   → Spawns background thread

4. BACKGROUND SCAN (run_scan_all thread)
   For each store in DB:
   CatalogScanner(db, store_code=code, job_id=job_id)
   scanner.scan_products(
     category_ids=[cat.magnit_id for tracked cats],
     tracked_only=False
   )

5. FETCH PRODUCTS BY CATEGORY
   For each category_id (magnit_id):
   MagnitAPIClient.get_products(
     category_ids=[47161],  # Integer magnit_id
     store_code="992104",
     limit=50, offset=0
   )

6. SAVE PRODUCTS TO DB
   For each product from API:
   Check if exists (product_id + store_code)
   If exists: UPDATE price, stock, promo data
   If new: INSERT with all fields
   Record PriceHistory if price changed
   Record DailyPriceSnapshot

7. POLL JOB STATUS (catalog.html every 2s)
   GET /api/jobs/{job_id}
   → Updates progress bar
   → Shows progress_message
```

---

## Implementation Tasks (Priority Order)

### Phase 1: Critical Fixes (Blocking)

**Task 1.1:** Create `load_catalog_from_json.py`
- File: `src/server/services/load_catalog_from_json.py`
- Reads `magnit_catalog.json` from project root
- Parses hierarchical structure
- Inserts into Category table with parent-child relationships
- Handles updates for existing categories
- Returns: `{"scanned": N, "added": N, "updated": N}`

**Task 1.2:** Fix `catalog_scanner.py` - Replace `code` with `magnit_id`
- Line 77: `Category.code` → `Category.magnit_id`
- Line 92: Remove `code=cat_data["code"]` assignment
- Line 151: `[cat.code for cat in categories]` → `[cat.magnit_id for cat in categories]`
- Line 184: `Category.code == cat_code` → `Category.magnit_id == cat_code`
- Line 234: `Category.code == cat_code` → `Category.magnit_id == cat_code`
- Line 273: `Category.code == category_code` → `Category.magnit_id == category_code`
- Update debug prints to use `magnit_id` instead of `code`

**Task 1.3:** Verify API field mapping
- Test `magnit_api.py:get_products()` with integer category IDs
- Verify API response structure matches parser expectations
- Check `product_id` field name in API response
- Verify pagination fields: `hasMore`, `next_offset`

### Phase 2: Testing & Validation

**Task 2.1:** Test end-to-end workflow
- Load categories from JSON via `/api/categories/load-from-json`
- Verify categories in DB with correct parent-child relationships
- Select categories via `/api/categories/update-tracking`
- Trigger scan via `/api/catalog/scan-all-stores`
- Monitor job progress via `/api/jobs/{job_id}`
- Verify products saved to DB with correct data

**Task 2.2:** Test error scenarios
- API rate limiting (0.5s delay between requests)
- Network timeouts and retries
- Partial scan recovery
- Invalid category IDs
- Missing store codes

### Phase 3: Enhancements (Optional)

**Task 3.1:** Add error handling & retry logic
- Retry failed API requests (exponential backoff)
- Handle rate limit errors gracefully
- Log errors with context for debugging
- Mark jobs as failed with error messages

**Task 3.2:** Optimize database operations
- Batch inserts instead of individual commits
- Use bulk update for price snapshots
- Add indexes for common queries
- Consider connection pooling

**Task 3.3:** Add structured logging
- Log API requests/responses
- Track scanning progress with timestamps
- Monitor job completion rates
- Debug category/product mapping issues

---

## Files to Modify/Create

| File | Action | Priority |
|------|--------|----------|
| `src/server/services/load_catalog_from_json.py` | CREATE | CRITICAL |
| `src/server/services/catalog_scanner.py` | MODIFY (6 locations) | CRITICAL |
| `src/server/services/magnit_api.py` | VERIFY | HIGH |
| `src/server/routes/catalog.py` | No changes needed | - |
| `src/server/models.py` | No changes needed | - |
| `magnit_catalog.json` | No changes needed | - |

---

## Testing Checklist

- [ ] `load_catalog_from_json.py` loads all 141 categories correctly
- [ ] Categories have correct parent-child relationships
- [ ] `magnit_id` values match JSON file
- [ ] `catalog_scanner.py` no longer references `Category.code`
- [ ] Scanner passes integer `magnit_id` to API
- [ ] API accepts integer category IDs
- [ ] Products are saved with correct category_id
- [ ] Price history is recorded on price changes
- [ ] Daily snapshots are created/updated correctly
- [ ] Job progress updates in real-time
- [ ] Scan completes successfully for all stores
- [ ] Error handling works for API failures

---

## Success Criteria

✅ Categories load from JSON with correct hierarchy  
✅ Product scanning triggers without AttributeError  
✅ Products are fetched and saved to DB  
✅ Price history and snapshots are recorded  
✅ Job status updates in real-time  
✅ Scan completes for all stores without errors
