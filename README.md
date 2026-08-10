# BeautyAI (YoPalette)

사진 한 장으로 **피부 · 퍼스널컬러 · 네일 · 얼굴 비율**을 분석하고, 결과에 맞는 화장품을 추천하는 서비스입니다. 판매·결제는 자매 프로젝트 [BeautyWEB](../BeautyWEB_project) 이 담당하며, 두 서비스는 같은 계정으로 이어집니다.

🇯🇵 [日本語版 README](./README_ja.md)

---

## 기능

| 모듈 | 하는 일 |
|---|---|
| 피부 케어 분석 | 얼굴·바디 사진 → 6항목 점수 → 성분·상품 추천 → 결과지 |
| 퍼스널컬러 | 얼굴 사진 → 시즌 판정 → 팔레트·메이크업 → 아이템 매칭 |
| 네일·페디 | 손·발 사진 → 네일 검출 → 발색 미리보기 → 유사 디자인·상품 |
| 가상 성형 | 얼굴 비율 분석 → 목표별 미리보기 → 상담용 리포트 |
| AI 상담 | 성분·루틴 질문 + 카탈로그 조회(재고를 지어내지 않습니다) |

한국어 / 일본어를 지원합니다.

## 기술 스택

- **프론트엔드** React 18 · TypeScript · MUI v6 · Vite
- **백엔드** FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2
- **추론** PyTorch(.pt) · MediaPipe · OpenCV · scikit-learn
- **상담** OpenAI API + 로컬 RAG(JSONL)
- **DB** PostgreSQL(개발·운영) / SQLite(로컬 단독)
- **배포** Docker Compose · nginx · Caddy 2 · GitHub Actions

---

## 빠른 시작

### 방법 1. Docker (권장)

가장 확실합니다. Postgres·백엔드·프론트가 한 번에 뜹니다.

```bash
cd BeautyAI_project
docker compose up -d --build
docker compose ps
```

- 프론트: http://localhost:5173
- 백엔드 문서: http://localhost:8000/docs

카탈로그를 채우려면 (최초 1회):

```bash
docker compose exec backend python scripts/seed_dev_db.py
```

### 방법 2. 로컬 실행

**백엔드**

```bash
cd BeautyAI_project/backend

python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# DB 를 따로 띄우지 않고 SQLite 로 바로 돌립니다
set DATABASE_URL=sqlite:///./beautyai.db      # macOS/Linux: export ...
python -m uvicorn app.main:app --reload --port 8000
```

**프론트엔드**

```bash
cd BeautyAI_project/frontend
npm ci
npm run dev        # http://localhost:5173
```

> `uv` 를 쓴다면 `uv venv .venv && uv pip install -r requirements.txt` 로 대체할 수 있습니다.

---

## 환경 변수

`backend/.env` 에 넣거나 셸에서 export 합니다. **모두 없어도 서비스는 뜹니다** — 해당 기능만 꺼집니다.

| 키 | 기본값 | 없으면 |
|---|---|---|
| `DATABASE_URL` | SQLite | — |
| `APP_ENV` | (없음) | `production` 일 때만 운영 DB 가드가 동작 |
| `REQUIRE_LOGIN` | `false` | 로그인 없이 전 기능 사용 |
| `CORS_ORIGINS` | `http://localhost:5173` | 프론트에서 API 호출 차단 |
| `OPENAI_API_KEY` | (없음) | 상담이 지식베이스 폴백으로 동작 |
| `OPENAI_MODEL` | `gpt-4.1-mini` | — |
| `JWT_SECRET` | 개발용 기본값 | BeautyWEB 계정 연동 불가 |
| `RAKUTEN_APP_ID` | (없음) | 일본 라쿠텐 상품 검색 불가 |
| `SKIN_MODEL_PATH` 등 | `/data/models/*.pt` | 해당 분석이 `model_available=false` 로 응답 |

> ⚠️ `.env` 는 **절대 커밋하지 마세요.** `.gitignore` 에 포함되어 있습니다. API 키를 공개 저장소나 이슈·PR 에 붙여넣지 마세요.

### 모델 파일

분석 기능은 `data/models/*.pt` 체크포인트가 필요합니다. 저장소에는 포함되지 않습니다(용량). 파일이 없으면 해당 API 가 `model_available: false` 로 응답하고, **다른 기능은 정상 동작합니다.**

```text
data/models/
├── skin_efficientnet_b0.pt              얼굴 피부 6항목
├── derma_tier1_gate.pt                  피부질환 선별 게이트
├── derma_tier2_classifier.pt            피부질환 분류
├── personal_color_retrain_try2_*.pt     퍼스널컬러
├── body_skin_mobilenet_v3.pt            바디 피부
└── nail_embedder_efficientnet_b0.pt     네일 디자인 검색
```

---

## 테스트

```bash
cd BeautyAI_project/backend

# ⚠️ 그냥 돌리면 .env 의 운영 DB 를 물어 오래 걸립니다. SQLite 로 덮어쓰세요.
set DATABASE_URL=sqlite:///./test_run.db
set APP_ENV=test
pytest -q
```

약 760건이 돕니다. `data/` 가 없는 환경(CI 등)에서는 데이터 의존 테스트가 자동으로 skip 됩니다.

프론트엔드:

```bash
cd BeautyAI_project/frontend
npm run lint
npm run build
```

---

## 프로젝트 구조

```text
BeautyAI_project
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI 앱
│   │   ├── api/routes.py      모든 엔드포인트
│   │   ├── core/              설정 · DB 세션
│   │   ├── models/domain.py   SQLAlchemy 모델 11개
│   │   ├── schemas/api.py     요청 · 응답 스키마
│   │   ├── ai/                모델 로더
│   │   └── services/          도메인 로직 (약 37개)
│   ├── alembic/               마이그레이션
│   ├── tests/                 pytest
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx            화면 전체
│       ├── api/client.ts      백엔드 호출
│       ├── i18n.ts            한국어 · 일본어 사전
│       └── styles.css         스타일
├── data/                      모델 · RAG · 카탈로그  ※ 컨테이너에서는 /data
├── docs/                      설계 문서
├── docker-compose.yml         로컬
├── docker-compose.prod.yml    운영
└── Caddyfile                  리버스 프록시 · 자동 HTTPS
```

---

## 문서

| 문서 | 내용 |
|---|---|
| [AI_요건정의서](docs/AI_요건정의서.md) | 무엇을 만드는가 |
| [AI_기본설계서](docs/AI_기본설계서.md) | 어떤 구조로 만드는가 |
| [AI_상세설계서](docs/AI_상세설계서.md) | 어디에 어떻게 들어 있는가 |
| [AI_system-design-overview](docs/AI_system-design-overview.md) | 런타임 구성과 처리 흐름 |
| [AI_ERD](docs/AI_ERD.md) | 데이터 모델 |

각 문서에는 일본어판(`*_ja.md`)이 있습니다.

---

## 기여할 때

- 브랜치를 만들어 작업하고 PR 을 올립니다. **기본 브랜치에 머지되어야 배포가 돕니다.**
- 커밋 전에 `pytest` 와 `npm run build` 를 돌립니다.
- **화면에 나가는 한국어 문장을 새로 만들면 일본어판도 함께 만듭니다.** 수치·이름이 끼어 조립되는 문장은 프론트 사전으로 옮길 수 없어, 서버가 두 벌을 만들어야 합니다. 지키지 않으면 `tests/test_assembled_sentence_inventory.py` 가 실패합니다.
- 분석 결과 문구에는 "확정 진단이 아님"을 남깁니다.

## 라이선스 · 주의

- 분석 결과는 **참고용**이며 의학적 진단이 아닙니다.
- 업로드한 사진은 저장하지 않습니다(확장자만 기록).
- `DELETE /api/me/data` 로 사용자가 직접 데이터를 지울 수 있습니다.
