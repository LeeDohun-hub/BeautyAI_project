# BeautyAI 기본설계서

## 1. 시스템 개요

BeautyAI(서비스명 **YoPalette**)는 사진 한 장으로 피부·퍼스널컬러·네일을 분석하고, 그 결과에 맞는 상품까지 연결하는 서비스다. 판매·결제는 BeautyWEB 이 맡고, 두 서비스는 같은 계정으로 이어진다.

- 작성 기준: 2026-08-10, 실제 구현 코드
- 이전 판(2026-06-29)은 얼굴·바디 피부 분석 중심이었다. 모듈 5개·다국어·웹 연동이 추가되어 전면 개정한다.

## 2. 설계 목표

| 목표 | 설계 결정 |
|---|---|
| 판정과 판매를 잇는다 | 분석 결과 → 성분 → 상품 컬럼 → 구매 링크 → 결과지 QR → 웹 장바구니까지 한 줄로 잇는다. |
| 모르는 것은 모른다고 한다 | 근거가 없으면 답을 만들지 않는다. 카탈로그 질문은 LLM 이 아니라 DB 가 답한다. |
| 모델이 없어도 서비스는 산다 | 모델·코퍼스가 없으면 그 기능만 `feature_available=false` 로 꺼진다. |
| 일본어에 한국어를 섞지 않는다 | 조립형 문장은 서버가 두 벌 만든다. 번역이 없으면 문단을 생략한다. |
| 판단의 한계를 숨기지 않는다 | 확정 진단이 아님을 화면에 남기고, 정밀도가 낮은 항목은 구간으로 표시한다. |

## 3. 시스템 구성

```
                      인터넷
                         │ 443
               ┌─────────▼─────────┐
               │ Caddy 2 (자동 HTTPS)│  ai.yopalette.com
               └─────────┬─────────┘
                 ┌───────▼────────┐
                 │ frontend       │  nginx + React 18 + MUI
                 │ (내부 8080)     │  /api, /internal → backend 프록시
                 └───────┬────────┘
                 ┌───────▼────────┐        ┌────────────────┐
                 │ backend :8000  │◄──────►│ BeautyWEB      │
                 │ FastAPI        │        │ (계정·장바구니) │
                 └───┬────────┬───┘        └────────────────┘
        ┌────────────▼──┐  ┌──▼───────────┐
        │ PostgreSQL    │  │ /data        │
        │ (운영·개발)     │  │ 모델(.pt)     │
        └───────────────┘  │ RAG(.jsonl)  │
                           │ 카탈로그       │
                           └──────────────┘
   외부: OpenAI(상담) · 라쿠텐/올리브영/아마존(상품)
```

- 외부 접점은 Caddy 하나다. 프론트는 호스트 포트를 열지 않는다.
- `/api`, `/internal` 라우팅은 프론트 nginx 가 한다. Caddy 는 호스트만 가른다.
- `/data` 마운트가 없으면 모델·RAG 가 로드되지 않는다. 컨테이너 기준 경로는 `/data` 다(`/app/data` 아님).

## 4. 기술 스택

| 구분 | 기술 |
|---|---|
| 프론트 | React 18, TypeScript, MUI v6, Vite, lucide-react |
| 백엔드 | FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2 |
| 추론 | PyTorch(.pt 체크포인트), MediaPipe(얼굴 랜드마크), OpenCV, scikit-learn |
| 상담 | OpenAI API + 로컬 RAG(JSONL 코퍼스) |
| DB | PostgreSQL(개발·운영), SQLite(로컬 단독 실행) |
| 배포 | Docker Compose, nginx, Caddy 2, GitHub Actions(self-hosted 러너) |

## 5. 화면 흐름

### 5.1 모듈 선택 (홈)

퍼스널컬러 / 피부 케어 분석 / 네일·페디 / 가상 성형 중 선택한다. 웹 계정으로 들어왔으면 우상단에 연동 상태를 표시한다.

### 5.2 피부 케어 분석 (6단계)

```
1 설문 → 2 사진 입력 → 3 분석 → 4 추천 → 5 결과지 → 6 상담
```

- 1단계는 개인정보 동의 전에는 다음으로 못 간다.
- 4단계에서 성분·카테고리별 상품 컬럼·성분 근거를 본다.
- 5단계 결과지에 담은 상품이 실리고 QR 이 붙는다.

### 5.3 퍼스널컬러 (6단계)

```
1 기본정보 → 2 촬영/업로드 → 3 퍼스널컬러 결과 → 4 아이템 매칭 → 5 스타일 → 6 결과지
```

웹에 저장된 퍼스널컬러가 있으면 2·3단계를 건너뛸 수 있다.

### 5.4 네일·페디

업로드 → 네일 검출 → 색 선택 → 발색 미리보기 → 비슷한 디자인 → 그 색으로 살 수 있는 상품.

### 5.5 가상 성형

기본정보·목표 → 사진 분석 → 얼굴 비율 → 미리보기 카드 → 상담용 리포트.

## 6. 백엔드 모듈 구조

```text
backend/app/
├── main.py                애플리케이션 진입
├── api/routes.py          모든 HTTP 엔드포인트
├── core/                  설정·DB 세션
├── models/domain.py       SQLAlchemy 모델
├── schemas/api.py         요청·응답 스키마
├── ai/                    모델 로더(피부·더모·퍼스널컬러·네일)
└── services/              도메인 로직 (약 37개 모듈)
```

서비스 계층의 주요 묶음.

| 묶음 | 모듈 |
|---|---|
| 분석 | `skin_analyzer`, `body_skin_analyzer`, `dermatology_analyzer`, `personal_color_analyzer`, `face_shape_analyzer`, `nail_design_index`, `virtual_surgery_simulator` |
| 추천 | `recommender`, `routine_steps`, `body_categories`, `pediatric_care`, `derma_condition_care` |
| 지식 | `skincare_ingredient_knowledge`, `problem_skin_knowledge`, `ingredient_aliases`, `kr_ingredient_notice` |
| 상담 | `chatbot`, `chat_catalog_answers`, `llm_consult` |
| 상품·플랫폼 | `oliveyoung_*`, `amazon_catalog`, `rakuten_*`, `matsukiyo_matcher`, `naver_*`, `platform_resolver`, `platform_availability`, `product_image_provider` |
| 기타 | `makeup_applier`, `nail_palette`, `image_router`, `data_retention`, `seed` |

## 7. 주요 API

| 분류 | 엔드포인트 |
|---|---|
| 상태 | `GET /health`, `GET /ready` |
| 계정 | `GET /api/auth/config`, `POST /api/auth/exchange`, `GET /api/auth/me`, `DELETE /api/me/data` |
| 피부 | `POST /api/analyze-skin`, `POST /api/recommend`, `GET /api/history` |
| 퍼스널컬러 | `POST /api/analyze-personal-color`, `GET /api/personal-color/profile`, `POST /api/personal-color/item-match`, `POST /api/analyze-face-shape` |
| 스타일 | `POST /api/style/makeup-preview`, `POST /api/style/makeup-preview/photo`, `GET /api/style/mood-thumbnails` |
| 네일 | `POST /api/analyze-nail-design` |
| 가상 성형 | `POST /api/virtual-surgery/simulate`, `/preview-cards`, `/retouch` |
| 상담 | `POST /api/chat` |
| 상품 | `GET /api/products` |
| 장바구니 핸드오프 | `POST /api/cart/handoff`, `POST /internal/cart-handoff/resolve` |
| 운영 | `GET /api/admin/statistics` |

## 8. 데이터 모델 개요

11개 테이블. 상세는 `AI_ERD.md`.

| 묶음 | 테이블 |
|---|---|
| 계정·연동 | `users`, `cart_handoffs`, `used_tickets` |
| 분석 | `surveys`, `skin_analyses` |
| 카탈로그 | `brands`, `products`, `ingredients`, `product_ingredients` |
| 이력 | `recommendation_histories`, `chat_histories` |

## 9. 추천 로직 개요

### 9.1 얼굴

```
점수(6항목) + 설문 ──► 우선 고민 집합
        │
        ▼
  성분 추론(infer_ingredients) ──► 상위 5개
        │
        ▼
  루틴 슬롯별 상품 컬럼(클렌저·토너·세럼·보습·선크림)
        │  세럼만 사진 고민 기반, 나머지는 품질(평점·피부타입 적합)
        ▼
  플랫폼 링크 부여 → 빈 링크 카드 제거 → 요약문·성분 근거
```

### 9.2 바디·더모

질환 선별 결과를 기준으로 바디 세정·보습 슬롯을 채운다. 자극 성분을 피해야 하는 질환이면 **성분이 확인된 상품만** 올린다. 성분을 모르는 상품은 회피 검사를 할 수 없기 때문이다.

### 9.3 퍼스널컬러 아이템 매칭

```
시즌·톤 → 카테고리별 색상 키워드 → 라이브 검색 + 로컬 카탈로그
        → 링크 부여(resolve) → 컬럼 균형(balance) → 화면
```
⚠ **resolve 를 balance 보다 먼저** 해야 컬럼이 비지 않는다. 순서를 되돌리면 일부 컬럼이 통째로 빈다.

## 10. 외부 플랫폼 링크

| 플랫폼 | 지역 | 방식 |
|---|---|---|
| 올리브영 | KR/글로벌 | 카탈로그 매칭 직링크, 실패 시 검색 링크 |
| 아마존 | KR/JP | 검증된 ASIN 직링크만 |
| 라쿠텐 | JP | API 검색 결과의 상품 URL |
| 마츠키요 | JP | 매칭 시 검색 링크 |

가격은 표시하지 않는다. 카드 하나에 판매처가 여럿이라 표시가가 어느 곳에서도 맞지 않는다.

## 11. 다국어 설계

| 대상 | 방법 |
|---|---|
| 고정 문구 | 프론트 사전(`i18n.ts`) |
| 조립형 문장 | 서버가 `*_ja` 쌍을 만들어 함께 내려보냄 |
| 지식 코퍼스 | 일본어 번역본이 있는 레코드만 사용. 없으면 문단 생략 |
| 상품명·성분명 | 고유명사이므로 옮기지 않는다 |

조립형 한국어 문장은 테스트로 목록이 고정되어 있어, 새로 생기면 분류할 때까지 실패한다.

## 12. 운영 고려사항

- 모델·RAG 는 `/data` 마운트에 의존한다. 새 데이터 파일은 런타임 번들 목록에도 넣어야 프로덕션에서 조용히 죽지 않는다.
- 배포는 self-hosted 러너에서 돌며, CI 성공 후 **기본 브랜치에서만** 트리거된다.
- 사진은 분석 후 원본 파일명을 남기지 않는다.
- 상담·추천 응답이 길어질 수 있어 프록시 타임아웃을 300s 로 맞춘다.
