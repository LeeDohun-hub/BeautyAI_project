# Codex Handoff - BeautyAI Personal Color Item Matching

Last updated: 2026-07-01

## Latest Batch Status

User asked to proceed autonomously in this order:

1. Replace flat Naver/Rakuten score with personal-color fit score.
2. `#3` Personal-color + mood combination.
3. `#1` Matsukiyo matcher.
4. `#2` OliveYoung makeup catalog crawl/import path.

Status: all four items are implemented and verified.

## Completed

### Personal-color fit score

Files:

```text
backend/app/services/recommender.py
backend/app/api/routes.py
```

Done:

- Added `personal_color_fit_score_for_text`.
- DB, curated catalog, Rakuten, and Naver item matching now use category/color/tone token matching.
- Rating/review/image presence are only secondary signals.
- Removed flat Rakuten formula based on `40 + rating`.
- Removed flat Naver formula based on `60 + image bonus`.

### Personal-color + mood combination

File:

```text
frontend/src/App.tsx
```

Done:

- Added `combinedPersonalColorMoodKeywords`.
- Mood matching sends analyzed personal-color keywords + selected mood keywords + profile label/tone/subtype hints.
- Step 4 uses `moodItems` when a mood is selected.
- Step 4 shows a message that the personal-color result and mood are both reflected.

### Matsukiyo matcher

Files:

```text
backend/app/services/matsukiyo_matcher.py
backend/app/api/routes.py
```

Done:

- Added cached CSV matcher for `data/manifests/matsukiyo_products.csv`.
- Matches by brand/name tokens.
- Attaches real `matsukiyo` URL to item-match results when confidence is high.
- Adds Matsukiyo image if the item had none and the matched row has one.

### OliveYoung makeup catalog path

Files:

```text
scripts/crawl_oliveyoung_global.py
scripts/load_oliveyoung_to_db.py
```

Done:

- `crawl_oliveyoung_global.py` now supports `--makeup-only`.
- `load_oliveyoung_to_db.py` now supports `--mode skincare|makeup|all`.
- Makeup rows can be imported without skincare ingredient detection.
- Makeup category is inferred as `lip`, `blush`, `eye`, or `base` where possible.

### Currency / layout already done

File:

```text
frontend/src/App.tsx
frontend/src/styles.css
```

Done:

- Personal-color item cards:
  - `kr` -> `₩`
  - `jp` -> `¥`
- Step 4 item matching remains grouped by columns:
  - lip
  - blush
  - eye
  - base

## Validation

Frontend build:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project\frontend
npm.cmd run build
```

Result: passed.

Python syntax:

```powershell
cd C:\WorkSpace\Beauty_Project
.\BeautyAI_project\backend\.venv\Scripts\python.exe -m py_compile BeautyAI_project\backend\app\api\routes.py BeautyAI_project\backend\app\services\recommender.py BeautyAI_project\backend\app\services\matsukiyo_matcher.py BeautyAI_project\scripts\crawl_oliveyoung_global.py BeautyAI_project\scripts\load_oliveyoung_to_db.py
```

Result: passed.

Backend tests:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project\backend
.venv\Scripts\python.exe -m pytest tests\test_api.py -q
```

Result:

```text
5 passed
```

## Useful Commands

Crawl OliveYoung makeup catalog, requires fresh `cf_clearance`:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project
backend\.venv\Scripts\python.exe scripts\crawl_oliveyoung_global.py --cf-clearance "<COOKIE>" --makeup-only --out data/manifests/oliveyoung_global_makeup_products.csv
```

Import OliveYoung makeup catalog:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project
backend\.venv\Scripts\python.exe scripts\load_oliveyoung_to_db.py --catalog data/manifests/oliveyoung_global_makeup_products.csv --mode makeup
```

## Remaining Optional Improvements

- Add focused tests for `personal_color_fit_score_for_text`.
- Add API smoke test for `/api/personal-color/item-match`.
- Review skin-care recommendation currency display; personal-color item cards are done.
- Run actual OliveYoung makeup crawl with a valid cookie.

## 2026-07-01 Update: KR Currency / Verified Platform Links

Files:

```text
frontend/src/App.tsx
backend/app/api/routes.py
```

Done:

- Personal-color item cards now format prices with `Intl.NumberFormat`.
  - `region=kr` -> `KRW`
  - `region=jp` -> `JPY`
- Live Naver products no longer expose speculative `Amazon.com` or `Olive Young` buttons.
- Live Rakuten products no longer expose speculative `Amazon JP` buttons.
- Platform buttons should now represent backend-confirmed links only:
  - Naver API item -> `naver`
  - Rakuten API item -> `rakuten`
  - Matsukiyo -> attached only after CSV matcher confirms a real URL

OliveYoung note:

- Do not generate OliveYoung fallback links from Korean Naver product names.
- Better architecture: keep display names separate from platform search names, e.g. `display_name`, `canonical_en_name`, `naver_query_ko`, `oliveyoung_query_en`, `rakuten_query_ja`.
- Frontend should render only backend-supplied `platform_links`; backend should attach link provenance such as `source`, `matched`, or `search_fallback`.

Validation:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project\frontend
npm.cmd run build

cd C:\WorkSpace\Beauty_Project\BeautyAI_project\backend
.\.venv\Scripts\python.exe -m py_compile .\app\api\routes.py
```

Result: passed.
