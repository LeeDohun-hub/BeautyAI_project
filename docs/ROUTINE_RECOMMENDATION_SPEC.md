# 루틴 기반 상품 추천 설계 스펙 (v1)

작성 2026-07-23. 상태: **구현 완료(구동/재빌드만 남음).**
> ⚠️ 개념 수정(2026-07-23): "루틴/순서"가 아니라 **카테고리별 상품 컬럼**(퍼스널컬러 립/아이/베이스처럼).
> 컬럼=클렌저/토너/세럼/보습/선크림, 컬럼당 상품 **여러 개**. STEP/순서/우선순위/사용팁 제거.
> 스키마 `routine`→`product_columns`(`ProductColumn{key,label,reason,products[]}`), `build_routine`→`build_product_columns`.
> **바디도 동일 5컬럼 엔진 재사용**: derma 2단 컨디션→진정/장벽 scored→`build_product_columns`(recommend_derma_care). 프론트 게이팅 `showColumns`(face·body 공통). 바디 분류기=derma 2단 단일화(mobilenet/BodySkinAnalyzer 폐기, import 제거함). 악성의심=제품 대신 전문가 안내(컬럼 없음).
- ① `app/services/routine_steps.py` + `tests/test_routine_steps.py`(74 pass). 카탈로그 4,516개 게이트 통과 1,679(37%), 잡음(헤어·색조·바디·아이·두피) 제거.
- ② `recommender.py`의 `build_routine`/`_product_out` — `RecommendationResponse.routine[]` 추가(기존 `products`·원점수 유지=하위호환). 세럼=사진고민(민감시 강한액티브 감점), 보습=피부타입 택1, 나머지=품질.
- ③ 프론트: `types/api.ts`에 `RoutineStep`/`routine`, `App.tsx` 추천페이지에 "추천 루틴(순서대로)" 카드 섹션(우선순위='딱 하나만' 강조 + 이유·사용팁·플랫폼 버튼). tsc 통과.
- 검증: 백엔드 74 pass·220 collect OK·앱 import OK / 프론트 tsc 0. 반영엔 백엔드 재시작 + 프론트 재빌드 필요.
기존 추천은 "성분 맞는 상품 상위 5개 평면 나열"이라 실제 사용 방식(단계별 루틴)과 안 맞고,
카테고리 오염(잡음 상품)이 섞여 나왔다. 이 스펙은 **표준 루틴 순서로 단계당 1개씩** 추천한다.

## 1. 확정된 결정
- **루틴 골격(고정 순서)**: `클렌저 → 토너 → 세럼 → 보습(로션/크림 택1) → 선크림`
- **완결형**: 항상 모든 단계를 채운다(고민 없어도 무난한 걸로 채움).
- **보습은 자동 택1**: 피부타입으로 로션 또는 크림 하나만. (지성·복합→로션 / 건성·중성→크림 / 민감→크림 장벽보습)
- **카테고리 매핑 = 품질 게이트**: 6단계 중 하나로 **확실히 분류된 상품만** 후보. 분류 불가/잡음은 제외.
  (부수효과: 헤어·키트·바디 등 오염 상품이 자동으로 추천에서 빠짐)
- **개인화의 핵심은 세럼 칸**: 사진 진단 1순위 고민 → 성분 → 세럼. 나머지 칸은 피부타입+평점.

## 2. 카테고리 → 단계 매핑 규칙

### 2-1. 명시 카테고리 (그대로 배정)
| 단계 | 카테고리 |
|---|---|
| 클렌저 | cleanser, Cleansers |
| 토너 | toner, Pads |
| 세럼 | serum, essence, ampoule, treatment, Treatments, Blemish & Acne Treatments, Acne & Blemish Treatments |
| 로션 | lotion |
| 크림 | cream, Moisturizers |
| 선크림 | sunscreen, Sunscreen |
| **제외** | mask, Sheet Masks, Facial Masks, Patches, Gift Set, Body Moisturizers, Face, Nose Pack, Hair Wash, Eye, Bath & Shower, After Sun Care |

### 2-2. `skincare`(2,014개·45%) → 이름 추론
실측: 이름으로 26%만 단계 분류, 74%는 헤어/샴푸/키트/필링 등 잡음. → **아래 규칙 순서대로 첫 매치**, 없으면 제외.

**① BLOCK(최우선 제외)**: `hair, shampoo, conditioner, hairspray, styling, mousse, kit, set, body, shower, bath, nail, lip, perfume, fragrance, deodorant, 헤어, 샴푸, 바디, 샤워`

**② 단계 키워드** (블록 통과분에만, 위→아래 우선):
- 선크림: `sun, spf, uv, 자외선, 선크림, 선블록, 선스틱, 톤업선`
- 클렌저: `cleans, foam, wash, 클렌징, 클렌저, 폼, 세안, remover, 리무버, cleansing oil, cleansing balm`
- 토너: `toner, 토너, softener, 스킨, mist, 미스트, pad, 패드, toning`
- 세럼: `serum, 세럼, essence, 에센스, ampoule, 앰플, treatment, peel, 필링, exfoliat, 각질, booster, 부스터, spot, dark spot, concentrate`
- 로션: `lotion, 로션, emulsion, 에멀전, 에멀션`
- 크림: `cream, 크림, moistur, 모이스, butter, 버터, nourish, 수분크림`
- else → **제외**

### 2-3. `balm` / `gel` → 이름 재분류
- 이름에 `cleans|클렌징|cleansing oil|메이크업|makeup|remover|리무버` → **클렌저**
- 그 외 → **크림**(보습)

## 3. 단계별 상품 선택 로직
각 단계의 후보 풀(품질 게이트 통과분) 안에서 아래 기준으로 1개.

- **클렌저**: 피부타입 적합 + 순함(민감이면 저자극/무향 우선) + 평점.
- **토너**: 피부타입 + 평점. 민감(`sensitivity≥4`)이면 진정 성분(센텔라·판테놀) 가점.
- **세럼(개인화 핵심)**: 사진 진단 1순위 고민 → 성분군 → 해당 성분 함유 세럼을 기존 점수(severity_focus + concern_hit)로 랭킹.
  - acne → Salicylic Acid · Zinc · Azelaic Acid
  - pigmentation → Vitamin C · Niacinamide · Azelaic Acid
  - wrinkle → Retinol · Peptide
  - pore → Niacinamide · Salicylic Acid · Retinol
  - oiliness → Niacinamide · Zinc · Green Tea
  - redness → Centella · Panthenol · Azelaic Acid
  - **강한 고민 없음(밴드 전부 낮음)** → Hyaluronic Acid · Niacinamide (무난·보습). ※완결형이라 항상 채움.
  - **민감 피부**: Retinol·고농도 AHA 회피, Azelaic·Centella·Niacinamide 선호.
- **보습(로션 or 크림)**: 피부타입으로 단계 확정 후, 그 풀에서 피부타입 적합+평점. 건성/민감은 세라마이드·판테놀 가점.
- **선크림**: 평점 + 피부타입(지성=산뜻/무기자차, 건성=촉촉). 얼굴용만.

**공통**: 1순위 고민 밴드(높음>보통>낮음)와 설문 고민을 신뢰 신호로. **정밀 점수(예: 54.3)에 의존하지 않는다**(노이즈·거친 라벨). 플랫폼/예산 필터는 후보 풀에 선반영.

**폴백**: 단계 풀이 비면 ①피부타입 필터 완화 → ②평점순 → ③그래도 없으면 그 단계는 생략하고 안내 문구.

## 4. 안전 / 도메인 규칙
- **세럼 1개만** 추천 → 액티브 동시투입(레티놀+AHA+비타민C) 자극 문제 원천 차단.
- **선크림 = 아침만**, 세럼(레티놀류) = 저녁·주2회 시작·임신 시 회피 안내.
- **민감 피부**: 전 단계 저자극 우선, 강한 액티브 배제.
- **화장품 ≠ 의료**: 심한 트러블·의심 병변은 기존 피부질환 선별(tier1/2)로 안내하고 "진단 아님, 심하면 전문가" 문구. 특정 치료 연고는 OTC/전문가 영역으로 분리.

## 5. 출력 구조(응답)
```
[진단 한 줄]  가장 관리 필요: {top1}, {top2}  (사진 밴드 + 설문)
[루틴 — 순서대로]
  1. 클렌저   {product}  — {이유}
  2. 토너     {product}  — {이유}
  3. 세럼     {product}  — 성분 {ing}, 타깃 {concern} · 사용팁(AM/PM·빈도)
  4. 보습     {로션|크림} {product}  — {이유}
  5. 선크림   {product}  — 아침 필수
[딱 하나만 한다면]  {우선순위 단계}
[주의]  {민감·액티브·의료 안내}
```

## 6. 구현 시 바뀌는 것(다음 단계)
- `classify_routine_step(product) -> step | None` : 2절 규칙(명시맵 + 이름추론 + block). 순수 함수, 단위테스트.
- `recommend_products`를 **단계별 랭킹 + 완결형 조립**으로 교체(기존 스코어 함수 재사용).
- 응답 스키마에 루틴 구조 추가(`routine: list[{step, product, ingredient, reason, usage}]`). 기존 `products`/원점수는 유지(하위호환·추천 근거).
- 프론트: "AI 추천 상품 기반 루틴 세트 섹션"으로 렌더(리포트 로드맵 항목).

## 7. 남은 미세 항목(구현 중 확정)
- 클렌저를 추천에 포함할지(완결형=포함, 유저 순서는 "클렌징 후"라 생략도 가능) → 기본 포함, 토글 여지.
- `Pads`(토너패드 vs 각질패드), `essence`(토너 성격 vs 세럼) 경계 케이스 이름 재확인.
- 세럼 성분↔상품 매칭 시 성분 태그 정확도(현재 키워드 태깅) 점검.
