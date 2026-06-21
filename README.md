# BeautyAI

AI 기반 피부 분석 및 화장품 추천 플랫폼입니다.

## 기술 스택

- 프론트엔드: React, TypeScript, Material UI, Vite
- 백엔드: FastAPI, SQLAlchemy
- AI: PyTorch 연동을 고려한 서비스 경계, OpenCV 호환 이미지 처리
- 데이터베이스: MySQL 연동 가능 SQLAlchemy 모델, 로컬 개발 기본값은 SQLite
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

학습된 모델은 `data/models/skin_efficientnet_b0.pt`에 저장됩니다. API는 `.env`에서 `SKIN_MODEL_PATH`를 읽습니다. 파일이 존재하고 PyTorch가 설치되어 있으면 `POST /api/analyze-skin`은 EfficientNet 모델을 자동으로 사용합니다. 그렇지 않으면 MVP 분석기로 대체됩니다.

제품/리뷰 데이터셋은 Amazon Beauty 데이터셋 기반 카탈로그 후보로 변환할 수 있습니다.

```bash
backend\.venv\Scripts\python.exe scripts\download_kaggle_datasets.py --only satrapankti/amazon-beauty-product-recommendation
backend\.venv\Scripts\python.exe scripts\import_amazon_beauty_catalog.py --root data\datasets\kaggle --out data\manifests\amazon_beauty_catalog.csv
backend\.venv\Scripts\python.exe scripts\load_product_catalog_to_db.py --catalog data\manifests\amazon_beauty_catalog.csv --limit 5000
```

Amazon Beauty 카탈로그 변환기는 상품명, 브랜드, 가격, 카테고리, 평점, 리뷰 수, 설명, 리뷰 텍스트를 기반으로 피부 고민 태그를 자동 생성합니다. 성분 정보가 없는 상품도 `acne`, `pore`, `oiliness`, `redness`, `pigmentation`, `wrinkle` 태그를 추천 성분 타깃으로 매핑해 기존 추천 API와 연결됩니다.

