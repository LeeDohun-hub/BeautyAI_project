# Claude Code Handoff - BeautyAI Item Recommendation Fixes

Last updated: 2026-07-13

Workspace:

```text
C:\WorkSpace\Beauty_Project\BeautyAI_project
branch: main
```

## User Goal

The user wants the item recommendation step fully stabilized.

Scope covered in this session:

- Personal-color item matching.
- Skin-care recommendation item matching.
- Japan/Korea region behavior.
- Male/female result paths.
- Amazon JP direct-link buttons.

Primary user rule:

```text
If a real direct product URL can be verified, keep the URL button.
If it cannot be verified or opens an Amazon "Looking for something?" page, remove the URL button.
Do not use search-result URLs as fake direct links.
```

## Important Context

The user specifically reported:

- `peripera Pure Blushed Sunshine Cheek` opened an Amazon JP error page.
- `WAKEMAKE Soft Blurring Eye Palette` opened a `2aN` product page.
- `BOBBI BROWN eyeshadow palette` had an invalid/wrong Amazon JP link.
- `Mentholatum Fondue Lip Balm Baby Pink 3.2g` had an invalid/wrong Amazon JP link.
- They suspected the newly added HuggingFace Amazon dataset might be involved.

That suspicion was valid. The bad behavior came from US/HF ASINs being reused as `amazon.co.jp/dp/{asin}`.

## Current Worktree State

Tracked modified files:

```text
backend/app/api/routes.py
backend/app/services/amazon_catalog.py
backend/app/services/platform_resolver.py
backend/tests/test_amazon_catalog.py
backend/tests/test_platform_resolver.py
```

Untracked files present before/around this work:

```text
.codex_checkpoint_item_match_20260713.patch
.codex_pre_rollback_20260713_140210.patch
backend/tests/test_rakuten_verify.py
scripts/build_amazon_catalog_from_hf.py
scripts/crawl_amazon_beauty_catalog.py
```

Do not delete or reset these unless the user explicitly asks.

## What Changed

### 1. Amazon JP no longer reuses US/HF ASINs

File:

```text
backend/app/services/platform_resolver.py
```

Key rule now:

```text
JP Amazon buttons are allowed only when:
1. There is a verified line override, or
2. The product matches the real JP Amazon catalog.

US/HF Amazon ASINs must not be converted into amazon.co.jp/dp links.
```

Do not reintroduce this pattern:

```python
fallback = amazon_catalog.match_amazon(brand, en_query)
return amazon_catalog.amazon_jp_url(fallback.asin)
```

That is the exact class of bug that caused 404 pages and wrong products.

### 2. Verified JP direct-link overrides

File:

```text
backend/app/services/platform_resolver.py
```

Verified direct lines currently kept:

```text
WAKEMAKE Soft Blurring Eye Palette -> https://www.amazon.co.jp/dp/B0DHXR1ZV3
peripera Pure Blushed Sunshine Cheek -> https://www.amazon.co.jp/dp/B0H6D154Y7
The Ordinary Niacinamide 10% + Zinc 1% -> https://www.amazon.co.jp/dp/B01MDTVZTZ
La Roche-Posay Effaclar Medicated Gel Facial Cleanser -> https://www.amazon.co.jp/dp/B003JSEGNC
```

Removed/blocked examples:

```text
B07C9CPRQQ  # Peripera, Amazon JP 404
B0FJFQLHM2  # WAKEMAKE request, actually 2aN
B07D8DBS7S  # Paula's Choice, Amazon JP 404
B0B15P25JC  # The Ordinary, Amazon JP 404
B07Q39P7W4  # The Ordinary AHA/BHA, Amazon JP 404
B07YY954DX  # Bobbi Brown, not safe enough to attach to current recommendation
```

### 3. JP catalog blocks rows with conflicting brands in the title

File:

```text
backend/app/services/amazon_catalog.py
```

Reason:

`amazon_beauty_jp.csv` had rows where the CSV `brand` column said `wakemake`, but the title clearly said `2aN`.

Fix:

If `region="jp"` and the title contains another known brand key, the match is rejected.

Example blocked:

```text
brand column: wakemake
title: 2aN Official Eyeshadow Palette BETTER ME EYE PALETTE 14 Slush Pop
```

### 4. Skin-care `/api/recommend` platform handling fixed

File:

```text
backend/app/api/routes.py
```

Important flow:

```text
1. Build broad product candidates.
2. Resolve platform links with platform_resolver.
3. Verify/prune platform URLs.
4. Apply the user's selected platform filter.
```

This matters because old platform scoring could filter out products before the resolver had a chance to attach verified Amazon JP links.

Do not move the platform filter before `resolve_product_platforms`.

### 5. Personal-color item-match platform filter fixed

File:

```text
backend/app/api/routes.py
```

After platform links are resolved, item-match results are filtered by requested platform.

For example:

```text
region=jp, platform=amazon_jp
```

now returns only products that actually have a verified `amazon_jp` direct link.

## Validation Already Run

Backend full test suite:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project\backend
.\.venv\Scripts\python.exe -m pytest -q
```

Result:

```text
139 passed in 77.48s
```

Backend Docker rebuild:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project
docker compose up -d --build backend
```

Result:

```text
backend image rebuilt
backend container restarted
```

## Live API Verification Result

Actual local API matrix was tested after Docker rebuild.

Personal-color item matching:

```text
PC all jp female: 10 products, 8 amazon_jp links
PC all jp male: 10 products, 0 amazon_jp links
PC all kr female: 10 products, 0 amazon_jp links
PC all kr male: 10 products, 0 amazon_jp links
PC amazon_jp jp female: 6 products, 6 amazon_jp links, all have link=True
PC amazon_jp jp male: 0 products, 0 amazon_jp links, all have link=True
```

Skin-care recommendation:

```text
SKIN all jp female: 5 products, 2 amazon_jp links
SKIN all jp male: 5 products, 2 amazon_jp links
SKIN all kr female: 5 products, 0 amazon_jp links
SKIN all kr male: 5 products, 0 amazon_jp links
SKIN amazon_jp jp female: 2 products, 2 amazon_jp links, all have link=True
SKIN amazon_jp jp male: 2 products, 2 amazon_jp links, all have link=True
```

Remaining Amazon JP direct links were HTTP checked and all returned 200:

```text
https://www.amazon.co.jp/dp/B003JSEGNC  OK  La Roche-Posay Effaclar Medicated Gel Facial Cleanser
https://www.amazon.co.jp/dp/B01MDTVZTZ  OK  The Ordinary Niacinamide 10% + Zinc 1%
https://www.amazon.co.jp/dp/B08PF3HX2F  OK  rom&nd Juicy Lasting Tint Coral Series
https://www.amazon.co.jp/dp/B09LCMQM44  OK  TIRTIR Mask Fit Red Cushion
https://www.amazon.co.jp/dp/B09W9J7FC9  OK  peripera Ink Mood Glowy Tint
https://www.amazon.co.jp/dp/B0CJC5YR2G  OK  CLIO Pro Eye Palette
https://www.amazon.co.jp/dp/B0DHXR1ZV3  OK  WAKEMAKE Soft Blurring Eye Palette
https://www.amazon.co.jp/dp/B0H6D154Y7  OK  peripera Pure Blushed Sunshine Cheek
```

Failure list from the live verification:

```text
FAILURES []
```

## Notes For Claude

Be careful with these points:

- `data/manifests/amazon_beauty_hf.csv` is useful for US/KR Amazon.com matching, but must not be used to create Amazon JP direct links.
- `data/manifests/amazon_beauty_jp.csv` can have wrong `brand` column values because crawler/search seed labels leaked into rows.
- For JP Amazon, title-level brand conflict detection is necessary.
- `Bobbi Brown B07YY954DX` exists as a page but should not be attached unless the exact recommended line can be verified.
- `Mentholatum Fondue Lip Balm Baby Pink 3.2g` has no verified direct JP link in the current catalog; leave the Amazon JP button absent unless verified.

## Rollback / Checkpoint Files

Existing checkpoint file:

```text
.codex_checkpoint_item_match_20260713.patch
```

Pre-rollback backup made during the previous rollback request:

```text
.codex_pre_rollback_20260713_140210.patch
```

If the user asks to roll back, clarify which point they mean:

```text
1. Original checkpoint: .codex_checkpoint_item_match_20260713.patch
2. State before rollback: .codex_pre_rollback_20260713_140210.patch
3. Current fixed state after Amazon JP stabilization
```

## Suggested Next Action

If continuing work, start with:

```powershell
cd C:\WorkSpace\Beauty_Project\BeautyAI_project
git status --short
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

Then manually verify the frontend at:

```text
http://localhost:5173
```

Focus on Step 4 item matching and skin-care result cards. The backend is already rebuilt and running from the latest fixed code.
