# BeautyAI (YoPalette)

写真1枚で **肌 · パーソナルカラー · ネイル · 顔の比率** を分析し、結果に合う化粧品を推薦するサービスです。販売・決済は姉妹プロジェクトの [BeautyWEB](../BeautyWEB_project) が担当し、両サービスは同じアカウントでつながります。

🇰🇷 [한국어版 README](./README.md)

---

## 機能

| モジュール | 内容 |
|---|---|
| 肌ケア分析 | 顔・体の写真 → 6項目スコア → 成分・商品推薦 → 結果シート |
| パーソナルカラー | 顔写真 → シーズン判定 → パレット・メイク → アイテムマッチング |
| ネイル・ペディ | 手足の写真 → ネイル検出 → 発色プレビュー → 類似デザイン・商品 |
| バーチャル整形 | 顔の比率分析 → 目標別プレビュー → 相談用レポート |
| AI相談 | 成分・ルーティンの質問 + カタログ照会（在庫を作り話しません） |

韓国語 / 日本語に対応しています。

## 技術スタック

- **フロントエンド** React 18 · TypeScript · MUI v6 · Vite
- **バックエンド** FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2
- **推論** PyTorch(.pt) · MediaPipe · OpenCV · scikit-learn
- **相談** OpenAI API + ローカルRAG（JSONL）
- **DB** PostgreSQL（開発・本番）/ SQLite（ローカル単独）
- **デプロイ** Docker Compose · nginx · Caddy 2 · GitHub Actions

---

## クイックスタート

### 方法1. Docker（推奨）

もっとも確実です。Postgres・バックエンド・フロントが一度に立ち上がります。

```bash
cd BeautyAI_project
docker compose up -d --build
docker compose ps
```

- フロント: http://localhost:5173
- バックエンドのドキュメント: http://localhost:8000/docs

カタログを入れる場合（初回のみ）:

```bash
docker compose exec backend python scripts/seed_dev_db.py
```

### 方法2. ローカル実行

**バックエンド**

```bash
cd BeautyAI_project/backend

python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# DB を別途立てず SQLite でそのまま動かします
set DATABASE_URL=sqlite:///./beautyai.db      # macOS/Linux: export ...
python -m uvicorn app.main:app --reload --port 8000
```

**フロントエンド**

```bash
cd BeautyAI_project/frontend
npm ci
npm run dev        # http://localhost:5173
```

> `uv` を使う場合は `uv venv .venv && uv pip install -r requirements.txt` で置き換えられます。

---

## 環境変数

`backend/.env` に置くか、シェルで export します。**すべて無くてもサービスは起動します** — 該当機能だけがオフになります。

| キー | 既定値 | 無い場合 |
|---|---|---|
| `DATABASE_URL` | SQLite | — |
| `APP_ENV` | （なし） | `production` のときのみ本番DBガードが動作 |
| `REQUIRE_LOGIN` | `false` | ログインなしで全機能を利用 |
| `CORS_ORIGINS` | `http://localhost:5173` | フロントからのAPI呼び出しが遮断される |
| `OPENAI_API_KEY` | （なし） | 相談が知識ベースへフォールバック |
| `OPENAI_MODEL` | `gpt-4.1-mini` | — |
| `JWT_SECRET` | 開発用の既定値 | BeautyWEB とのアカウント連携が不可 |
| `RAKUTEN_APP_ID` | （なし） | 日本の楽天商品検索が不可 |
| `SKIN_MODEL_PATH` など | `/data/models/*.pt` | 該当分析が `model_available=false` で応答 |

> ⚠️ `.env` は **絶対にコミットしないでください。** `.gitignore` に含まれています。APIキーを公開リポジトリやIssue・PRに貼らないでください。

### モデルファイル

分析機能には `data/models/*.pt` のチェックポイントが必要です。容量のためリポジトリには含まれていません。ファイルが無い場合、該当APIは `model_available: false` で応答し、**他の機能は正常に動作します。**

```text
data/models/
├── skin_efficientnet_b0.pt              顔の肌6項目
├── derma_tier1_gate.pt                  皮膚疾患スクリーニングのゲート
├── derma_tier2_classifier.pt            皮膚疾患の分類
├── personal_color_retrain_try2_*.pt     パーソナルカラー
├── body_skin_mobilenet_v3.pt            体の肌
└── nail_embedder_efficientnet_b0.pt     ネイルデザイン検索
```

---

## テスト

```bash
cd BeautyAI_project/backend

# ⚠️ そのまま実行すると .env の本番DBに接続して時間がかかります。SQLite で上書きしてください。
set DATABASE_URL=sqlite:///./test_run.db
set APP_ENV=test
pytest -q
```

約760件が実行されます。`data/` が無い環境（CIなど）では、データ依存のテストが自動的に skip されます。

フロントエンド:

```bash
cd BeautyAI_project/frontend
npm run lint
npm run build
```

---

## プロジェクト構成

```text
BeautyAI_project
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI アプリ
│   │   ├── api/routes.py      すべてのエンドポイント
│   │   ├── core/              設定 · DBセッション
│   │   ├── models/domain.py   SQLAlchemyモデル 11件
│   │   ├── schemas/api.py     リクエスト · レスポンススキーマ
│   │   ├── ai/                モデルローダ
│   │   └── services/          ドメインロジック（約37件）
│   ├── alembic/               マイグレーション
│   ├── tests/                 pytest
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx            画面全体
│       ├── api/client.ts      バックエンド呼び出し
│       ├── i18n.ts            韓国語 · 日本語辞書
│       └── styles.css         スタイル
├── data/                      モデル · RAG · カタログ  ※ コンテナでは /data
├── docs/                      設計文書
├── docker-compose.yml         ローカル
├── docker-compose.prod.yml    本番
└── Caddyfile                  リバースプロキシ · 自動HTTPS
```

---

## ドキュメント

| 文書 | 内容 |
|---|---|
| [AI_要件定義書](docs/AI_요건정의서_ja.md) | 何を作るか |
| [AI_基本設計書](docs/AI_기본설계서_ja.md) | どんな構造で作るか |
| [AI_詳細設計書](docs/AI_상세설계서_ja.md) | どこにどう入っているか |
| [AI_system-design-overview](docs/AI_system-design-overview_ja.md) | ランタイム構成と処理フロー |
| [AI_ERD](docs/AI_ERD_ja.md) | データモデル |

各文書には韓国語版（拡張子 `_ja` なし）があります。

---

## コントリビュートするとき

- ブランチを作って作業し、PRを出します。**デフォルトブランチにマージされて初めてデプロイが走ります。**
- コミット前に `pytest` と `npm run build` を実行します。
- **画面に出る韓国語の文を新しく作ったら、日本語版も一緒に作ります。** 数値・名前が差し込まれて組み立てられる文はフロント辞書では置き換えられないため、サーバーが2種類作る必要があります。守らないと `tests/test_assembled_sentence_inventory.py` が失敗します。
- 分析結果の文言には「確定診断ではない」ことを残します。

## ライセンス・注意

- 分析結果は**参考**であり、医学的な診断ではありません。
- アップロードした写真は保存しません（拡張子のみ記録）。
- `DELETE /api/me/data` で利用者が自分のデータを削除できます。
