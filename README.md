# BeautyAI

AI-based skin analysis and cosmetics recommendation platform.

## Stack

- Frontend: React, TypeScript, Material UI, Vite
- Backend: FastAPI, SQLAlchemy
- AI: PyTorch-ready service boundary, OpenCV-compatible image handling
- Database: MySQL-ready SQLAlchemy models, SQLite default for local development
- Vector DB: ChromaDB-ready RAG service boundary
- Cache/Infra: Redis, Docker, GitHub Actions placeholders

## Quick Start

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

Open http://localhost:5173 and use the flow:

Survey -> Face upload -> Skin analysis -> Ingredient recommendation -> Product recommendation -> AI skin consultation -> History.

## API

- `POST /api/analyze-skin`
- `POST /api/recommend`
- `POST /api/chat`
- `GET /api/products`
- `GET /api/history`
- `GET /api/admin/statistics`

## Notes

The current skin analyzer is a deterministic MVP implementation. It accepts an uploaded face image and returns the required six 0-100 skin scores. The `SkinAnalyzer` service is intentionally isolated so an EfficientNet/PyTorch model can replace the heuristic implementation without changing API contracts.

## Skin Model Training

Kaggle datasets require a Kaggle API token. Put `kaggle.json` in `%USERPROFILE%\.kaggle\kaggle.json` on Windows, or set `KAGGLE_USERNAME` and `KAGGLE_KEY`.

```bash
cd backend
uv pip install -r requirements-train.txt --python .venv\Scripts\python.exe
cd ..
backend\.venv\Scripts\python.exe scripts\download_kaggle_datasets.py
backend\.venv\Scripts\python.exe scripts\build_skin_manifest.py
backend\.venv\Scripts\python.exe scripts\train_skin_efficientnet.py --epochs 1 --max-samples 512
backend\.venv\Scripts\python.exe scripts\train_skin_efficientnet.py --epochs 5
```

The trained model is saved to `data/models/skin_efficientnet_b0.pt`. The API reads `SKIN_MODEL_PATH` from `.env`; if the file exists and PyTorch is installed, `POST /api/analyze-skin` uses the EfficientNet model automatically. If not, it falls back to the MVP analyzer.

Product/review datasets can be converted into catalog candidates with:

```bash
backend\.venv\Scripts\python.exe scripts\import_product_catalog.py
backend\.venv\Scripts\python.exe scripts\load_product_catalog_to_db.py --limit 5000
```

