# Codex 핸드오프 — 바디 피부 추천 (2026-07-23)

BeautyAI 스킨케어 추천 앱. 최근 세션에서 **상품 추천을 "평면 리스트 → 카테고리 컬럼"** 으로 재설계했고,
이어서 **바디 피부 추천**을 붙이는 중 **데이터 제약**에 막혔다. 이 문서로 이어받으면 된다.

---
## 1. 지금까지 완료된 것 (코드에 반영됨)

### 얼굴(face) 추천 = 카테고리 상품 컬럼
- **개념**: "루틴/순서"가 아니라 **카테고리별 상품 컬럼**(퍼스널컬러 립/아이/베이스처럼). 컬럼당 상품 여러 개.
- 백엔드: `recommender.py`의 `build_product_columns(scored, survey)` — 클렌저/토너/세럼/보습/선크림 5컬럼, 각 top-4.
  세럼=사진 고민(`_serum_sort_key`, 민감시 레티놀/AHA 감점), 나머지=품질(`_generic_quality`), 보습=피부타입으로 로션/크림 택1.
- 스키마: `api.py`의 `ProductColumn{key,label,reason,products[]}`, `RecommendationResponse.product_columns`.
- 프론트: `App.tsx` `renderRecommendationPage` — `item-match-columns` 컬럼 렌더(퍼스널컬러와 동일 CSS). `showColumns` 플래그(face·body 공통).
- 상품 분류 게이트: `routine_steps.py` `classify_routine_step(category,name)` — 4,516개를 5카테고리로 분류하며 잡음(헤어·색조·바디·아이·두피) 제거. 단위테스트 `tests/test_routine_steps.py`(74 pass).

### 바디(body) 분석 = derma 2단
- `dermatology_analyzer.py` (DermatologyAnalyzer) — tier1(정상/양성/악성의심) + tier2(9그룹). 이제 **전체 9그룹 확률 높은순 표시**(전엔 `[:3]`).
- 프론트도 `averageBodyConditions`의 `.slice(0,3)` 제거함.
- **결정됨**: 바디 분류기는 derma 2단으로 단일화. `body_skin_mobilenet`/`BodySkinAnalyzer`는 폐기(routes.py import 제거함, 파일/샘플/config 경로는 아직 남음 → 정리 대상).

### 바디 추천 = 얼굴 컬럼 엔진 재사용 (여기가 문제)
- `recommend_derma_care`가 컨디션→적합성분 scored를 `build_product_columns`에 넣어 **얼굴과 같은 5컬럼**을 낸다.
- **문제**: 카탈로그가 얼굴 제품 위주라 **얼굴 제품(예: "Foaming Facial Cleanser")이 바디 컬럼에 끌려 들어감.** + 바디엔 토너/세럼/선크림 개념이 안 맞음.

---
## 2. 근본 원인 (반드시 이해할 것)

**카탈로그에 바디 제품이 거의 없다.**
- 총 4,516개 중 명시 바디 ~152(3.4%), 명시 얼굴 ~221(5%), 나머지는 암묵적 얼굴.
- `load_product_catalog_to_db.py` `infer_category`가 **body lotion→'lotion', body cream→'cream'** 로 얼굴과 동일 분류 → 바디 구분 불가.
- `SKINCARE_WORDS`에 wash/oil/scrub/butter 없음 → 바디워시·바디오일·스크럽은 **필터에서 탈락**.
- 후보풀 `data/manifests/product_catalog_candidates.csv`(110만행)에서 노이즈 제거 후 **진짜 바디 제품 ~88개뿐**(body_lotion 40·body_oil 31·body_cream 16·**body_wash 1·body_scrub 0**).
- 게다가 candidates.csv는 **5필드(source,brand,name,ingredients,rating)뿐 — 이미지/가격/URL 없음.** (얼굴 카드 이미지는 별도 `enrich_product_images.py`로 채운 것.)
- 리치 소스 `amazon_beauty_products.csv`는 `asin,brand,title,stars,reviews,imageUrl` — **이미지는 있으나 성분 없음**(태깅 약함).

→ "이미지+성분+수량" 다 갖춘 바디 카탈로그는 현재 데이터로 불가. 별도 수집 필요.

---
## 3. 부분 구축물 (이어서 쓰면 됨)
- `scripts/load_body_products.py` (신규) — candidates.csv에서 바디 제품을 감지해 **body_wash/body_lotion/body_cream/body_oil/body_scrub** 카테고리로 적재 + 14성분 룰 태깅(미검출 보습은 Panthenol/Ceramide 폴백).
  - `--sqlite`로 로컬 beautyai.db 테스트만 함(88개 적재됨). **운영 DB(Supabase)엔 안 넣음.**
  - `load_product_catalog_to_db`의 함수 재사용(detect_ingredients 등).

---
## 4. 사용자 미결정 (Codex가 물어보거나 진행 정하기)
바디 데이터 제약 때문에 3안 제시했고 **아직 미선택**:
1. **데이터에 맞춰 컬럼 축소** — 바디로션/바디오일/바디크림 3컬럼만(워시·스크럽 제외), 88개로 조립+이미지 enrich. *지금 가능한 최선, 추천.*
2. **amazon 소스로 확장** — 이미지 있는 바디 더 확보하되 성분은 이름기반+폴백(약함).
3. **바디 크롤 프로젝트** — 올리브영/아마존 바디 카테고리 실제 수집(별도 작업·시간).

---
## 5. 남은 작업 (택1 후)
1. **바디 제품 적재**: `load_body_products.py` 운영 DB 실행(+`enrich_product_images.py`로 이미지). ※운영 DB 쓰기라 사용자 승인 후.
2. **바디 컬럼 taxonomy**: `classify_routine_step`(또는 별도 body 분류)에서 `body_*` 카테고리 → 바디 컬럼 매핑 추가. `ROUTINE_SLOTS`는 face 전용이므로 **BODY_SLOTS 신설**.
3. **`recommend_derma_care`**: 바디 모드에선 face 5컬럼이 아니라 **바디 컬럼**(택1한 3~5개)으로 조립하도록 교체. 지금은 `build_product_columns`(face 슬롯)를 그대로 써서 얼굴 제품이 섞임.
4. **프론트**: `product_columns` 렌더는 이미 범용(라벨만 바뀜) → 백엔드가 바디 컬럼 라벨/키 내면 그대로 나옴.
5. **정리(선택)**: `recommend_products`의 죽은 body 분기 + `BODY_CARE_CATEGORIES`/`BODY_SAFE_INGREDIENTS` 상수, `body_skin_analyzer.py`/`body_skin_model.py`/config mobilenet 경로 제거.

---
## 6. 핵심 파일
| 파일 | 역할 |
|---|---|
| `backend/app/services/recommender.py` | `build_product_columns`, `recommend_products`(face), `recommend_derma_care`(body), `_serum_sort_key`, `_generic_quality`, `_product_out` |
| `backend/app/services/routine_steps.py` | `classify_routine_step` — 5 face 카테고리 분류 + 품질게이트(잡음제거). 바디 카테고리 추가 지점 |
| `backend/app/services/dermatology_analyzer.py` | 바디 분석(derma 2단, 9그룹) |
| `backend/app/schemas/api.py` | `ProductColumn`, `product_columns` |
| `backend/app/api/routes.py` | `/recommend`(body→recommend_derma_care), 지역 입점보강(products+product_columns) |
| `frontend/src/App.tsx` | `renderRecommendationPage`(컬럼), `averageBodyConditions`, `showColumns` |
| `frontend/src/types/api.ts` | `ProductColumn` |
| `scripts/load_body_products.py` | 바디 제품 적재(신규·부분) |
| `scripts/load_product_catalog_to_db.py` | 메인 적재(`infer_category`가 근본원인) |
| `scripts/enrich_product_images.py` | 이미지 보강(적재 후 별도 실행) |
| `docs/ROUTINE_RECOMMENDATION_SPEC.md` | 추천 설계 스펙 |

---
## 7. 운영/환경 메모
- **반영**: 백엔드 재시작 + 프론트 재빌드. STEP3 결과는 프론트 state에 캐시되므로 **재분석 필요**.
- **DB**: 운영=Supabase(`.env` DATABASE_URL). 로컬 테스트=sqlite `beautyai.db`(스크립트 `--sqlite`, 앱은 env override). ※로컬 sqlite엔 테스트 바디 88개 들어가 있음(운영 무관).
- **성공 기준(사용자)**: "상품 컬럼들이 추천 성분(진정/장벽: 센텔라·판테놀·세라마이드·HA 등)을 커버하면 됨."
- 프론트 검증: `cd frontend && npx tsc --noEmit`. 백엔드 테스트 수집: `cd backend && python -m pytest tests/ -q --co`(220개).
- 콘솔 cp932라 파이썬 실행 시 `PYTHONUTF8=1` 권장.
