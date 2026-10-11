# Tasks

## 1. Remove unused sidebar variable

- [x] 1.1 Remove `sidebar = self.page.locator(...).first` assignment from `src/scripts/verify_categories.py:73`
- [x] 1.2 Verify `ruff check src/` passes without new F841 errors
- [x] 1.3 Run existing tests to confirm no behavioral regression