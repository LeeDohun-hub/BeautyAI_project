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

## 2026-07-02 Update: Personal-Color EfficientNet Bootstrap

Files:

```text
backend/app/services/personal_color_analyzer.py
scripts/prepare_personal_color_dataset.py
scripts/train_personal_color_efficientnet.py
```

Local generated artifacts, ignored by git:

```text
data/manifests/personal_color_manifest.csv
data/models/personal_color_efficientnet.pt
```

Done:

- Generated `personal_color_manifest.csv` from `data/release/annotations.csv` and extracted `ORIGINAL_RGB_NOT_PROCESSED` images.
- Matched all 4,920 annotation rows to images.
  - train: 4,008
  - test: 912
  - autumn: 1,305
  - summer: 1,129
  - winter: 1,305
  - spring: 1,181
- Trained a quick CPU bootstrap model with:

```powershell
backend\.venv\Scripts\python.exe scripts\train_personal_color_efficientnet.py --manifest data\manifests\personal_color_manifest.csv --out data\models\personal_color_efficientnet.pt --epochs 3 --batch-size 32 --max-samples 400
```

Result:

```text
best val_acc=0.3836
```

Important note:

- This is only a smoke-test/bootstrap model, not a production-quality model.
- Full 15-epoch CPU training was started but stopped because it was projected to take multiple hours.
- `PersonalColorAnalyzer` now keeps the model-predicted season when selecting the final profile. Before this fix, a model prediction such as `autumn` could become a final `spring` response because only warm/cool tone was used.

Validation:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project\backend
.\.venv\Scripts\python.exe -m pytest tests\test_api.py -q
```

Result:

```text
5 passed in 67.90s
```

## 2026-07-02 Update: Skincare Ingredient-Efficacy Knowledge

Files:

```text
scripts/build_skincare_ingredient_knowledge.py
backend/app/services/skincare_ingredient_knowledge.py
backend/app/services/chatbot.py
backend/app/services/recommender.py
backend/app/core/config.py
backend/tests/test_skincare_ingredient_knowledge.py
```

Local generated artifact, ignored by git:

```text
data/rag/skincare_ingredient_knowledge.jsonl
```

Done:

- Added preprocessing for AI Hub `03.스킨케어 성분-효능 추천 데이터`.
- The script reads label `.jsonl` files inside ZIP archives and writes service-safe JSONL records.
- `chain_of_thought` from the source data is intentionally not stored or exposed.
- Generated `data/rag/skincare_ingredient_knowledge.jsonl`.

Generation result:

```text
Wrote 8341 records
- 과각질/악건성: 55
- 모공: 2562
- 미백(색소침착/기미/칙칙함): 3162
- 민감성(트러블/자극감): 8
- 붉어짐(홍조): 131
- 여드름/뾰루지: 781
- 주름: 1597
- 피부처짐/탄력저하: 45
```

Runtime behavior:

- `/api/chat` still checks problem-skin makeup knowledge first.
- If that match is weak, chat now falls back to skincare ingredient-efficacy knowledge.
- Face-skin product recommendation explanations append a short ingredient-efficacy rationale when a close match exists.

Useful command:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project
backend\.venv\Scripts\python.exe scripts\build_skincare_ingredient_knowledge.py
```

Validation:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project\backend
.\.venv\Scripts\python.exe -m pytest tests\test_skincare_ingredient_knowledge.py tests\test_problem_skin_knowledge.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_api.py -q
```

Result:

```text
4 passed in 4.34s
5 passed in 95.28s
```

## 2026-07-02 Update: Evidence-Based Recommendation UX

Files:

```text
backend/app/schemas/api.py
backend/app/services/recommender.py
backend/app/services/skincare_ingredient_knowledge.py
backend/app/services/personal_color_analyzer.py
frontend/src/types/api.ts
frontend/src/App.tsx
```

Done:

- Product recommendations now include optional:
  - `reason_tags`
  - `evidence_note`
- Face-skin recommendations use `03.스킨케어 성분-효능 추천 데이터` matches more directly:
  - maps matched skincare concern to internal targets such as `pore`, `acne`, `pigmentation`
  - adds a small score bonus when product ingredient targets overlap the matched AI Hub concern
  - adds product-level evidence notes when the match is relevant
- Frontend recommendation cards now show reason chips and a short evidence note.
- Personal-color analysis now adds:
  - `metrics.capture_quality`
  - capture/lighting/model-use guidance in `advice`
- Frontend personal-color result card now shows:
  - analysis quality
  - whether the deep-learning model was used
  - whether white-balance lighting correction was applied

Validation:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project\backend
.\.venv\Scripts\python.exe -m py_compile app\schemas\api.py app\services\recommender.py app\services\personal_color_analyzer.py app\services\skincare_ingredient_knowledge.py
.\.venv\Scripts\python.exe -m pytest tests\test_skincare_ingredient_knowledge.py tests\test_problem_skin_knowledge.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_api.py -q

cd C:\WorkSpace\Beauty_Project\BeautyAI_project\frontend
npm.cmd run build
```

Result:

```text
4 passed in 4.53s
5 passed in 81.19s
frontend build passed
```

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
