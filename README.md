# BeautyAI

AI 기반 피부 분석 및 화장품 추천 플랫폼입니다.

## 기술 스택

- 프론트엔드: React, TypeScript, Material UI, Vite
- 백엔드: FastAPI, SQLAlchemy
- AI: PyTorch 연동을 고려한 서비스 경계, OpenCV 호환 이미지 처리
- 데이터베이스: SQLAlchemy 모델 + Alembic 마이그레이션, 로컬 기본값 SQLite, 운영은 Supabase/Postgres 연동 가능
- 벡터 DB: ChromaDB 연동을 고려한 RAG 서비스 경계
- 캐시/인프라: Redis, Docker, GitHub Actions 플레이스홀더

## 빠른 시작

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

http://localhost:5173 을 열고 다음 흐름으로 사용합니다.

설문 -> 얼굴 업로드 -> 피부 분석 -> 성분 추천 -> 제품 추천 -> AI 피부 상담 -> 히스토리

## API

- `POST /api/analyze-skin`
- `POST /api/recommend`
- `POST /api/chat`
- `GET /api/products`
- `GET /api/history`
- `GET /api/admin/statistics`

## 참고 사항

현재 피부 분석기는 결정론적인 MVP 구현입니다. 업로드된 얼굴 이미지를 받아 필수 여섯 가지 0-100 피부 점수를 반환합니다. `SkinAnalyzer` 서비스는 의도적으로 분리되어 있어 API 계약을 변경하지 않고도 휴리스틱 구현을 EfficientNet/PyTorch 모델로 교체할 수 있습니다.

## 데이터베이스 / 마이그레이션 (Alembic · Supabase)

스키마는 Alembic으로 관리합니다. 모델([`backend/app/models/domain.py`](backend/app/models/domain.py))을 바꾼 뒤에는 마이그레이션을 생성·적용해야 합니다. (`create_all`은 새 테이블만 만들고 기존 테이블에 컬럼을 추가하지 못합니다.)

```bash
# 모델 변경 후 마이그레이션 자동 생성
cd backend && .venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe change"
# 적용
cd backend && .venv\Scripts\python.exe -m alembic upgrade head
```

연결 대상은 `.env`의 `DATABASE_URL` 하나로 결정됩니다(Alembic도 동일 값을 사용 — 자격증명은 alembic.ini가 아닌 .env에만 둡니다).

### SQLite → Supabase(Postgres) 이전

1. Supabase 프로젝트 생성 후 `Project Settings > Database`에서 연결 문자열 확인
2. `.env`의 `DATABASE_URL`을 Postgres 주소로 교체:
   ```
   DATABASE_URL=postgresql+psycopg2://postgres:YOUR_PASSWORD@db.YOUR_PROJECT.supabase.co:5432/postgres
   ```
3. Supabase에 스키마 생성:
   ```bash
   cd backend && .venv\Scripts\python.exe -m alembic upgrade head
   ```
4. 기존 SQLite 데이터를 복사(원본 sqlite는 그대로 두고 읽기만 함):
   ```bash
   backend\.venv\Scripts\python.exe scripts\migrate_sqlite_to_postgres.py ^
       --source sqlite:///./beautyai.db ^
       --target "postgresql+psycopg2://postgres:YOUR_PASSWORD@db.YOUR_PROJECT.supabase.co:5432/postgres"
   ```
   - 타깃 테이블에 데이터가 있으면 기본적으로 중단됩니다. 덮어쓰려면 `--truncate` 추가.
   - Postgres 타깃은 복사 후 id 시퀀스를 자동 보정합니다.

이미 스키마가 있는 기존 DB를 Alembic 관리로 편입할 때는 `alembic stamp head`로 현재 리비전을 표시합니다(로컬 sqlite는 이미 stamp 처리됨).

## 피부 모델 학습

Kaggle 데이터셋을 사용하려면 Kaggle API 토큰이 필요합니다. Windows에서는 `kaggle.json`을 `%USERPROFILE%\.kaggle\kaggle.json`에 두거나, `KAGGLE_USERNAME`과 `KAGGLE_KEY`를 설정하세요.

```bash
cd backend
uv pip install -r requirements-train.txt --python .venv\Scripts\python.exe
cd ..
backend\.venv\Scripts\python.exe scripts\download_kaggle_datasets.py
backend\.venv\Scripts\python.exe scripts\build_skin_manifest.py
backend\.venv\Scripts\python.exe scripts\train_skin_efficientnet.py --epochs 1 --max-samples 512
backend\.venv\Scripts\python.exe scripts\train_skin_efficientnet.py --epochs 5
```

### 팔·목·몸 피부질환 모델

몸 피부 분석은 얼굴 모델과 분리되어 있으며 SkinDisNet의 원본 임상 이미지
1,710장을 사용합니다. 데이터 라이선스는 CC BY-NC 4.0이므로 비상업 연구 및
개발 범위에서 사용해야 합니다.

```bash
backend\.venv\Scripts\python.exe scripts\download_skindisnet.py
backend\.venv\Scripts\python.exe scripts\prepare_skindisnet.py
backend\.venv\Scripts\python.exe scripts\train_body_skin_model.py --epochs 8
backend\.venv\Scripts\python.exe scripts\evaluate_body_skin_model.py
```

학습 결과는 `data/models/body_skin_mobilenet_v3.pt`에 저장됩니다. 분류 범주는
아토피 피부염, 접촉성 피부염, 습진, 옴, 지루성 피부염, 체부백선입니다.
모델 파일이 없으면 API는 임의 진단값을 만들지 않고 `model_available=false`를
반환합니다.

학습된 모델은 `data/models/skin_efficientnet_b0.pt`에 저장됩니다. API는 `.env`에서 `SKIN_MODEL_PATH`를 읽습니다. 파일이 존재하고 PyTorch가 설치되어 있으면 `POST /api/analyze-skin`은 EfficientNet 모델을 자동으로 사용합니다. 그렇지 않으면 MVP 분석기로 대체됩니다.

## 문제성 피부 상담 지식

AI Hub의 `02.문제성 피부 메이크업 추천 데이터` 라벨 ZIP을 상담 검색 인덱스로 변환합니다.

```bash
backend\.venv\Scripts\python.exe scripts\build_problem_skin_knowledge.py
```

생성된 `data/rag/problem_skin_knowledge.jsonl`은 원본 데이터와 함께 Git에서 제외됩니다. API의 `/api/chat`은 질문, 설문, 피부 분석 점수와 유사한 상담 사례를 찾아 메이크업 방법과 추천·회피 성분을 안내합니다. 인덱스가 없으면 기존 기본 상담 지식으로 자동 대체됩니다.

원본 데이터에는 연구·학습 목적 등의 이용 조건이 포함되어 있으므로 외부 배포나 상용 서비스 적용 전 라이선스를 별도로 확인해야 합니다. 치료·질환 관련 내용은 의료 진단이 아닌 참고 정보로만 제공합니다.

