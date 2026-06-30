# Claude Code Handoff - BeautyAI

## 1. Current Goal

Continue work on BeautyAI after recent design and frontend flow changes.

The desired product direction is:

- BeautyAI home screen with modules:
  - Personal Color
  - Skin Care Analysis
  - Future modules
- Skin Care Analysis should be one user-facing flow.
- The user should not manually choose face vs body.
- Uploaded/captured skin photos should be routed automatically by backend image routing.
- Basic info is collected before photo capture:
  - age
  - gender
  - self-identified race identity
  - privacy consent

Important product note:

- The previous concern about "AI says acne when user is not acne-prone" was only background justification from reference services. Do not treat it as a project requirement.
- The user specifically worried that asking skin concerns before photo analysis could bias the result. The current direction is to collect only basic info first, then take photos. Skin concerns and makeup concerns should not be part of the pre-photo step.

## 2. Repository

Working directory:

```text
C:\WorkSpace\BeautyAI_project
```

Related separate web mock project:

```text
C:\WorkSpace\BeautyWEB_project
```

BeautyWEB has a simple frontend that links into this AI project. Most recent AI work is in `BeautyAI_project`.

## 3. Current Local Git State

There are many uncommitted changes. Some existed before the latest work.

Tracked modified files include:

```text
.env.example
.gitignore
README.md
backend/app/api/routes.py
backend/app/core/config.py
backend/app/schemas/api.py
backend/app/services/chatbot.py
backend/app/services/recommender.py
backend/tests/test_api.py
frontend/src/App.tsx
frontend/src/api/client.ts
frontend/src/styles.css
frontend/src/types/api.ts
```

Untracked code/scripts include:

```text
backend/app/ai/body_skin_model.py
backend/app/services/body_skin_analyzer.py
backend/app/services/image_router.py
backend/app/services/problem_skin_knowledge.py
backend/tests/test_problem_skin_knowledge.py
scripts/build_problem_skin_knowledge.py
scripts/crawl_oliveyoung_brand_reviews (1).py
scripts/download_skindisnet.py
scripts/evaluate_body_skin_model.py
scripts/prepare_skindisnet.py
scripts/train_body_skin_model.py
scripts/validate_aihub_archives.py
```

Untracked docs include:

```text
docs/AI_요건정의서.md
docs/AI_기본설계서.md
docs/AI_상세설계서.md
docs/AI_ERD.md
docs/AI_system-design-overview.md
docs/CLAUDE_CODE_HANDOFF.md
```

## 4. Recent Work Done

### 4.1 BeautyAI home/module flow

File:

```text
frontend/src/App.tsx
frontend/src/styles.css
```

Added a BeautyAI home screen before the existing stepper flow.

Home modules:

- Personal Color: shown as 준비 중
- Skin Care Analysis: active, starts current analysis flow
- Future modules: placeholder

When clicking Skin Care Analysis, the app enters the existing stepper flow.

### 4.2 Simplified pre-photo input

The old first step asked:

- skin concerns
- makeup base concerns
- care areas
- sensitivity
- skin type
- routine

This was removed from the first step.

The new first step asks only:

- age
- gender: female / male
- self-identified race identity: select list
- privacy consent checkbox

Race identity options currently in `frontend/src/App.tsx`:

```text
동아시아
동남아시아
남아시아
중동/북아프리카
흑인/아프리카계
백인/유럽계
라틴계
혼혈/다인종
기타
응답하지 않음
```

`age` is used to derive `age_group` via `ageToAgeGroup()`.

DTO additions:

```text
frontend/src/types/api.ts
backend/app/schemas/api.py
```

Added:

- `age`
- `race_identity`
- `privacy_consent`

These are currently passed through as survey fields. They are not deeply used in recommendation logic yet.

### 4.3 Face/body user-facing toggle removed

The previous UI had:

```text
얼굴 피부 케어 | 바디 피부 케어
```

This was removed.

The user now sees one photo step:

```text
피부 케어 입력
얼굴 또는 케어가 필요한 피부 부위 사진을 1~5장 등록해 주세요.
```

### 4.4 Automatic image routing

New file:

```text
backend/app/services/image_router.py
```

Implemented OpenCV Haar Cascade based routing:

- If a sufficiently large face is detected: route to `face`
- If no face or face too small: route to `body`

Current logic:

```text
largest_face_ratio >= 0.025 -> face
else -> body
```

Backend route:

```text
backend/app/api/routes.py
```

`/api/analyze-skin` now defaults to:

```text
analysis_mode=auto
```

Then routes internally to `face` or `body`.

Frontend:

```text
frontend/src/types/api.ts
```

`AnalysisMode` now includes:

```ts
'auto' | 'face' | 'body'
```

Frontend analyze call sends:

```text
analysis_mode=auto
```

For multiple uploaded photos, `frontend/src/App.tsx` groups backend results:

- face results
- body results

It uses the majority mode as final result mode.

## 5. Existing Larger Uncommitted Feature Set

These changes likely existed before the latest handoff work. The user was unsure whether they made them and did not push them.

### 5.1 Body skin analysis

Files:

```text
backend/app/ai/body_skin_model.py
backend/app/services/body_skin_analyzer.py
scripts/download_skindisnet.py
scripts/prepare_skindisnet.py
scripts/train_body_skin_model.py
scripts/evaluate_body_skin_model.py
```

Purpose:

- Adds a MobileNetV3 based body skin classifier.
- Classes:
  - atopic_dermatitis
  - contact_dermatitis
  - eczema
  - scabies
  - seborrheic_dermatitis
  - tinea_corporis
- Uses SkinDisNet data scripts to download, prepare, train, and evaluate.

Risk:

- This was not explicitly requested by the user in the current flow.
- It has now been folded into "Skin Care Analysis" as an automatic route, but product fit should still be reviewed.
- Some Korean/Japanese labels in `body_skin_analyzer.py` appear mojibake/corrupted.

### 5.2 Body-safe recommendation logic

File:

```text
backend/app/services/recommender.py
```

Adds:

- body-safe ingredient priority
- avoid ingredient list
- body-care category filter
- body-specific explanation

Risk:

- Recommendation rules are heuristic.
- Product catalog may not have enough body-care products with matching ingredients.

### 5.3 Problem skin knowledge search

Files:

```text
backend/app/services/problem_skin_knowledge.py
backend/app/services/chatbot.py
scripts/build_problem_skin_knowledge.py
backend/tests/test_problem_skin_knowledge.py
```

Purpose:

- Build/load `data/rag/problem_skin_knowledge.jsonl`
- Search it before falling back to hardcoded chatbot knowledge
- Return `sources`

Risk:

- Several strings in `problem_skin_knowledge.py` and its test appear mojibake/corrupted.
- Need encoding cleanup before user-facing quality pass.

## 6. Verification Already Run

Frontend build:

```powershell
cd C:\WorkSpace\BeautyAI_project\frontend
npm.cmd run build
```

Result:

```text
success
```

Backend API tests:

```powershell
cd C:\WorkSpace\BeautyAI_project\backend
.venv\Scripts\python.exe -m pytest tests\test_api.py -q
```

Result:

```text
5 passed
```

Note:

- Running pytest from repo root failed with `ModuleNotFoundError: No module named 'app'`.
- Run tests from `backend/`.

## 7. Important Risks / Things To Review Next

### 7.1 Encoding/mojibake

Several files contain corrupted Korean/Japanese text:

```text
backend/app/services/body_skin_analyzer.py
backend/app/services/problem_skin_knowledge.py
backend/tests/test_problem_skin_knowledge.py
README.md
possibly frontend/src/App.tsx in some terminal outputs, though source read with UTF-8 looked mostly okay
```

Before final UI/demo, clean user-facing Korean strings.

### 7.2 Automatic routing is MVP only

Current `image_router.py` uses face detection, not a true body/skin classifier.

Behavior:

- Face detected -> face analysis
- Face not detected -> body analysis

This means non-skin images may still route to body.

Recommended next step:

- Add `unknown` / `low_quality` / `not_skin` route.
- Add image quality checks:
  - blur
  - darkness
  - tiny subject
  - non-skin/background-heavy image

### 7.3 Body analysis model may be unavailable

If `data/models/body_skin_mobilenet_v3.pt` does not exist:

- backend returns `model_available=false`
- frontend shows warning

This is intentional fallback.

### 7.4 Race identity handling

The UI currently collects self-identified race identity as a select field because the user referenced a similar service doing this.

Be careful:

- Do not use it to make stereotyped recommendations.
- If used, prefer audit/normalization/color calibration context only.
- Consider adding explanatory helper text if product requires.

### 7.5 Old concern inputs removed from first step

Skin concerns/makeup concerns/care areas were removed from pre-photo flow to avoid anchoring bias.

If reintroduced, place them after image analysis and make clear:

```text
photo-based result
user-stated concern
recommendation combines both
```

## 8. Suggested Next Tasks

1. Run the app manually:

```powershell
cd C:\WorkSpace\BeautyAI_project\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

```powershell
cd C:\WorkSpace\BeautyAI_project\frontend
npm.cmd run dev
```

2. Test UI manually:

- Home screen appears
- Skin Care Analysis starts
- Basic info page requires age, gender, race identity, privacy consent
- Photo page shows no face/body toggle
- Photo upload sends `analysis_mode=auto`
- Face photo routes to `face`
- Non-face/body image routes to `body` or returns body fallback if model missing

3. Clean mojibake strings.

4. Decide whether to keep body skin analysis in the product scope.

5. If keeping automatic routing:

- Add `unknown` route
- Add route result metadata to response if useful
- Add tests for `image_router.py`

## 9. Potential Commit Message

If committing all current feature/doc changes together:

```text
feat: add skin care analysis hub and auto image routing
```

Longer:

```text
feat: add BeautyAI hub, skin care auto routing, and AI docs

- add BeautyAI home module selection
- simplify pre-photo input to age, gender, race identity, and consent
- remove user-facing face/body toggle
- route images automatically with OpenCV face detection
- add body skin analysis and body-safe recommendation support
- add problem skin knowledge search for chatbot
- add AI requirements, design, ERD, and system overview docs
```

