# BeautyAI 상세설계서

## 1. 문서 목적

기본설계서가 "무엇을 만드는가"라면 이 문서는 "어디에 어떻게 들어 있는가"를 적는다. 코드를 처음 여는 사람이 파일을 찾아갈 수 있는 수준까지 쓴다.

- 작성 기준: 2026-08-10, 실제 구현 코드

## 2. 프로젝트 구조

```text
BeautyAI_project
├── backend/
│   ├── app/
│   │   ├── main.py               FastAPI 앱
│   │   ├── api/routes.py         모든 엔드포인트
│   │   ├── core/                 설정(config)·DB 세션(database)
│   │   ├── models/domain.py      SQLAlchemy 모델 11개
│   │   ├── schemas/api.py        요청·응답 스키마
│   │   ├── ai/                   모델 로더(피부·더모·퍼스널컬러·네일)
│   │   └── services/             도메인 로직 약 37개 모듈
│   ├── alembic/                  마이그레이션
│   ├── tests/                    pytest
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx               화면 전체(약 6,000줄)
│       ├── api/client.ts         백엔드 호출
│       ├── i18n.ts               한국어·일본어 사전
│       ├── types/api.ts          응답 타입
│       └── styles.css            스타일 전체(약 2,100줄)
├── data/                         모델(.pt)·RAG(.jsonl)·카탈로그  ※ 컨테이너에서는 /data
├── docs/                         설계 문서(이 파일 포함)
├── docker-compose.yml            로컬 개발
├── docker-compose.prod.yml       운영
└── Caddyfile                     리버스 프록시·자동 HTTPS
```

## 3. 환경 설정

| 키 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | 로컬 SQLite | 개발은 Postgres 권장(운영과 같은 엔진). 운영 DB 접속에는 별도 가드가 있다 |
| `APP_ENV` | — | `production` 이면 운영 DB 가드가 동작 |
| `ALLOW_PRODUCTION_DB` | false | 운영 DB 를 의도적으로 볼 때만 true |
| `JWT_SECRET` | — | **BeautyWEB 과 같은 값**이어야 티켓 검증이 된다 |
| `REQUIRE_LOGIN` | false(로컬) | 운영은 true |
| `CORS_ORIGINS` | localhost:5173 | 프론트 오리진 |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | — | 없으면 상담이 지식베이스 폴백으로 동작 |
| `SKIN_MODEL_PATH` 외 | `/data/models/*.pt` | 없으면 해당 기능이 꺼진다 |
| `RAKUTEN_*`, `NAVER_*` | — | 상품 검색 |
| `WEB_LOGIN_URL`, `WEB_CART_URL` | — | 웹 연동 링크 |

## 4. API 상세

### 4.1 상태

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/health` | 생존 확인 |
| GET | `/ready` | 의존성 준비 확인 |

### 4.2 계정 · 개인정보

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/auth/config` | 로그인 필요 여부·웹 링크 |
| POST | `/api/auth/exchange` | 웹 핸드오프 티켓 → AI 세션(12h) |
| GET | `/api/auth/me` | 현재 세션 사용자 |
| DELETE | `/api/me/data` | 내 분석·설문·추천·상담 이력 삭제 |

### 4.3 피부 분석 · 추천

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| POST | `/api/analyze-skin` | `image`(파일), `analysis_mode`(`auto`/`face`/`body`) | `analysis_id`, `scores`(6항목), `body_conditions`, `summary`, `confidence_note(_ja)`, `model_available`, `urgent` |
| POST | `/api/recommend` | 설문 + 점수/analysis_id + 지역·플랫폼 | `ingredients`, `products`, `product_columns`, `explanation(_ja)`, `evidence(_ja)` |
| GET | `/api/history` | — | 추천 이력 |

`explanation` 은 줄바꿈이 포함된 요약문이고, 350자 내외의 성분 근거는 `evidence` 로 분리해 내려보낸다. 프론트는 요약을 `pre-line` 으로 그리고 근거는 접어 둔다.

### 4.4 퍼스널컬러 · 스타일

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/analyze-personal-color` | 시즌 판정 + 팔레트 + `skin_summary(_ja)` + `decision_note(_ja)` |
| GET | `/api/personal-color/profile` | 웹에 저장된 퍼스널컬러 |
| POST | `/api/personal-color/item-match` | 카테고리별 상품 컬럼 |
| POST | `/api/analyze-face-shape` | 얼굴형·비율 |
| POST | `/api/style/makeup-preview` | 메이크업 컬러 미리보기 |
| POST | `/api/style/makeup-preview/photo` | 사진 위 메이크업 적용 |
| GET | `/api/style/mood-thumbnails` | 무드 썸네일 |

### 4.5 네일 · 가상 성형

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/analyze-nail-design` | 네일 검출·색 추출·유사 디자인 |
| POST | `/api/virtual-surgery/simulate` | 목표별 시뮬레이션 |
| POST | `/api/virtual-surgery/preview-cards` | 미리보기 카드 |
| POST | `/api/virtual-surgery/retouch` | 사용자가 고른 위치만 잡티 처리 |

### 4.6 상담

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/chat` | `message`, `context`(`scores`+`survey`), `lang` → `answer`, `sources` |

처리 순서가 중요하다.

```
1) 카탈로그 질문인가?  ── 예 ──► DB 조회로 답한다(LLM 을 타지 않는다)
   │ 아니오
2) LLM 이 켜져 있는가? ── 예 ──► 근거 검색 후 LLM 이 답변 작성
   │ 실패
3) 문제성 피부 코퍼스 → 성분 코퍼스 → 키워드 폴백 → 범위 밖 안내
```

1번을 앞에 두는 이유는, 재고·취급 여부를 모델이 지어내면 사용자를 매장까지 헛걸음시키기 때문이다.

### 4.7 상품 · 핸드오프 · 운영

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/products` | 전체 카탈로그 |
| POST | `/api/cart/handoff` | 결과지 QR 용 1회용 코드 발급 |
| POST | `/internal/cart-handoff/resolve` | WEB 이 코드로 상품 목록을 받아간다 |
| GET | `/api/admin/statistics` | 운영 통계 |

## 5. 주요 스키마

### 5.1 `SurveyInput`

성별, 연령대, 피부타입, 민감도, 고민(피부·메이크업·부위·남성 추가), 루틴 수준.

### 5.2 `SkinScores`

`acne` / `pore` / `wrinkle` / `redness` / `pigmentation` / `oiliness`, 각 0~100.

⚠ 6항목은 완전히 독립되지 않는다(라벨 자체가 일부 겹친다). 화면은 3그룹·3구간으로 보여준다.

### 5.3 `RecommendationResponse`

`ingredients`, `products`, `product_columns`, `explanation`, `explanation_ja`, `evidence`, `evidence_ja`.

### 5.4 `ProductColumn`

`key`, `label`, `reason`, `products[]`. 프론트는 `key` 로 헤더 색을 고른다.

## 6. 분석 서비스 상세

### 6.1 `skin_analyzer`

- 얼굴 검출(MediaPipe) → 여유 패딩 크롭 → 모델 추론.
- 홍조는 회귀 출력 대신 **LAB a\* 기반 색상 측정값**으로 대체한다. 학습 데이터가 거의 없어 회귀 출력을 믿을 수 없다.
- 화이트밸런스 보정은 마스킹보다 **먼저** 건다.
- 여러 장을 넣으면 평균을 낸다(조명에 따른 흔들림이 가장 큰 오차원이다).

### 6.2 `dermatology_analyzer` / `body_skin_analyzer`

2단 구조(게이트 → 분류). 확정 진단이 아님을 요약문에 명시하고, 악성 의심은 제품 추천 대신 진료를 안내한다.

### 6.3 `personal_color_analyzer`

- 분광측색 기준으로 학습한 Lab 회귀 → 계절 규칙 2단 구조.
- 판정 근거(`skin_summary`)와 경계 안내(`decision_note`)를 한국어·일본어 두 벌로 만든다.
- 조명이 색을 왜곡한 사진은 판정에서 제외한다.

### 6.4 `nail_design_index`

세그멘테이션으로 네일 영역을 찾고 색을 추출한다. 발색 미리보기는 타원 근사이므로 실제와 다를 수 있음을 화면에 명시한다.

## 7. 추천 서비스 상세

### 7.1 성분 추론 `infer_ingredients`

점수 45 이상 항목 + 설문 고민 + 연령 우선순위 + 민감도·피부타입 보정으로 우선 고민 집합을 만들고, 성분의 `targets` 와 교집합이 큰 순으로 상위 5개를 고른다.

### 7.2 상품 컬럼 `build_product_columns`

루틴 슬롯(클렌저·토너·세럼·보습·선크림)별로 후보를 모아 컬럼당 4개까지 고른다. 세럼만 사진 고민 기반이고 나머지는 품질(평점·피부타입 적합) 기준이다.

⚠ 랭킹 루프에서 성분 관계를 `selectinload` 하면 요청당 수 초가 늘어난다. 캐시된 `ingredient_index()` 를 쓴다.

### 7.3 요약문 조립

```
build_explanation()      한국어 요약(줄바꿈 포함)
build_explanation_ja()   일본어 요약
build_skincare_recommendation_hint()  성분 근거 → evidence 필드
```

상품명은 34자로 자르고 ` · ` 로 잇는다. 카탈로그 원제목에 쉼표가 들어 있어 쉼표로 이으면 항목 경계가 사라진다. 자른 뒤 중복도 제거한다.

### 7.4 지식 검색 `skincare_ingredient_knowledge`

- 코퍼스는 JSONL(약 8,300건). 고민어·질문·메타데이터를 토큰화해 점수를 낸다.
- 채택 임계값 6.0. 낮추면 일반 단어 두 개만 겹쳐도 주제가 다른 답이 나간다.
- 코퍼스 답변은 **사례 원문**이라 첫 문장이 그 사례 본인의 나이·성별·피부타입으로 시작한다. 그래서 관련도가 엇비슷한 후보들 사이에서는 **사용자와 인구통계가 같은 사례**를 앞세운다.
  - ⚠ 인구통계 적합도를 점수에 더하지 않는다. 더하면 주제가 다른 사례도 임계값을 넘는다. 1점 버킷 안에서 순서로만 쓴다.

### 7.5 카탈로그 답변 `chat_catalog_answers`

- 의도 판별은 보수적이다. 따옴표/'라는 상품'/'상품명' 중 하나로 이름이 특정되고, 조회 의도어가 함께 있을 때만 받는다.
- 상품명이 브랜드로 시작하면 브랜드를 생략한다(카탈로그가 상품명에 브랜드를 품고 있다).
- `category` 는 내부 키라 라벨표로 옮기고, 모르는 키는 감춘다.
- 한국어·일본어 문장은 모듈 상수에 쌍으로 둔다. 함수 안에 한국어 리터럴을 남기지 않아야 한쪽만 늘어나는 사고가 막힌다.

## 8. 프론트엔드 상세

### 8.1 구성

`App.tsx` 한 파일에서 모듈·단계를 상태로 전환한다(라우터 없음).

```ts
type AppModule = 'home' | 'skin-care' | 'personal-color' | 'nail-design' | 'virtual-surgery';
```

### 8.2 주요 클라이언트 함수 (`api/client.ts`)

`analyzeSkin`, `recommend`, `analyzePersonalColor`, `matchPersonalColorItems`, `analyzeFaceShape`, `analyzeNailDesign`, `simulateVirtualSurgery`, `previewMakeupOnPhoto`, `chat`, `createCartHandoff`, `exchangeTicket`, `fetchMe`, `deleteMyData`, `getHistory`.

### 8.3 다국어 (`i18n.ts`)

- 고정 문구는 사전으로 옮긴다.
- 서버가 `*_ja` 를 함께 내려준 문장은 `localizedSentence(ko, ja)` 로 고른다.
- 사전에 없는 조합어는 단어 단위로 옮긴다.

### 8.4 모바일 레이아웃 (`styles.css`, ≤600px)

| 항목 | 처리 |
|---|---|
| 컬럼 배치 | `xs=6` 으로 PC 처럼 2열 병렬(예전 `xs=12` 는 한 화면에 상품 1개였다) |
| 컬럼 헤더 | `position: sticky`. `top` 은 0 이 아니라 **58px** — 폰에서 언어 토글이 상단 전체를 덮는 불투명 바로 바뀐다 |
| 헤더 색 | `data-column` 으로 카테고리마다 배경색·왼쪽 띠 |
| 카드 | 여백·글자 축소로 약 348px |
| 구매 버튼 | 높이는 유지(터치 하한 44px), 폰에서는 짧은 이름(`short`)으로 줄 수를 줄인다 |

## 9. 테스트 설계

`backend/tests` 기준, 약 760건.

| 묶음 | 확인 내용 |
|---|---|
| 다국어 | 일본어 응답에 한국어가 남지 않는가, 한/일 표의 키가 일치하는가 |
| 조립형 문장 인벤토리 | 새 조립형 한국어 문장이 분류 없이 추가되지 않았는가(AST 검사) |
| 추천 | 성별·연령·피부타입에 따라 컬럼·성분이 맞게 갈리는가 |
| 상담 | 카탈로그 질문이 일반 상담을 가로채지 않는가, 못 찾으면 못 찾았다고 하는가 |
| 지식 검색 | 인구통계가 점수에 섞이지 않는가, 주제가 더 맞는 사례가 이기는가 |
| 안전 | 영유아 경로가 성인 제품으로 폴백하지 않는가, 향료 게이트가 다국어인가 |

⚠ CI 에는 `data/` 가 없다. 데이터를 읽는 테스트에는 skip 가드가 필요하다.

## 10. 배포

```
push(기본 브랜치) → CI(pytest · lint · build)
                     └─ 성공 시 workflow_run → Deploy(self-hosted 러너)
                                                 └─ 이미지 빌드 → 번들 → compose up
```

- `workflow_run` 은 **기본 브랜치에서만** 돈다. 작업 브랜치에 푸시하면 배포가 조용히 안 된다.
- 배포 실패 여부는 Deploy 잡의 소요 시간부터 본다(1초면 CI 실패로 건너뛴 것).
