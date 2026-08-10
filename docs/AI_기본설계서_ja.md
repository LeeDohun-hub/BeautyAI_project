# BeautyAI 基本設計書

> 韓国語版: [AI_기본설계서.md](./AI_기본설계서.md)

## 1. システム概要

BeautyAI（サービス名 **YoPalette**）は、写真1枚で肌・パーソナルカラー・ネイルを分析し、その結果に合う商品までつなぐサービスである。販売・決済は BeautyWEB が担い、両サービスは同じアカウントでつながる。

- 作成基準: 2026-08-10、実装コード
- 前版（2026-06-29）は顔・体の肌分析が中心だった。モジュール5つ・多言語・Web連携が追加されたため全面改訂する。

## 2. 設計目標

| 目標 | 設計上の決定 |
|---|---|
| 判定と販売をつなぐ | 分析結果 → 成分 → 商品列 → 購入リンク → 結果シートQR → Webカートまで一本でつなぐ。 |
| 分からないことは分からないと言う | 根拠が無ければ答えを作らない。カタログの質問は LLM ではなく DB が答える。 |
| モデルが無くてもサービスは生きる | モデル・コーパスが無ければその機能だけ `feature_available=false` でオフになる。 |
| 日本語に韓国語を混ぜない | 組み立て型の文はサーバーが2種類作る。翻訳が無ければ段落を省略する。 |
| 判断の限界を隠さない | 確定診断ではないことを画面に残し、精度の低い項目は区分で表示する。 |

## 3. システム構成

```
                      インターネット
                         │ 443
               ┌─────────▼─────────┐
               │ Caddy 2（自動HTTPS）│  ai.yopalette.com
               └─────────┬─────────┘
                 ┌───────▼────────┐
                 │ frontend       │  nginx + React 18 + MUI
                 │（内部 8080）     │  /api, /internal → backend へプロキシ
                 └───────┬────────┘
                 ┌───────▼────────┐        ┌────────────────┐
                 │ backend :8000  │◄──────►│ BeautyWEB      │
                 │ FastAPI        │        │（アカウント・カート）│
                 └───┬────────┬───┘        └────────────────┘
        ┌────────────▼──┐  ┌──▼───────────┐
        │ PostgreSQL    │  │ /data        │
        │（本番・開発）    │  │ models(.pt)  │
        └───────────────┘  │ RAG(.jsonl)  │
                           │ カタログ       │
                           └──────────────┘
   外部: OpenAI（相談） · 楽天/オリーブヤング/Amazon（商品）
```

- 外部との接点は Caddy ひとつ。フロントはホストポートを公開しない。
- `/api`, `/internal` のルーティングはフロントの nginx が行う。Caddy はホストを振り分けるだけ。
- `/data` のマウントが無いとモデル・RAG がロードされない。コンテナ基準のパスは `/data`（`/app/data` ではない）。

## 4. 技術スタック

| 区分 | 技術 |
|---|---|
| フロント | React 18, TypeScript, MUI v6, Vite, lucide-react |
| バックエンド | FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2 |
| 推論 | PyTorch（.pt チェックポイント）, MediaPipe（顔ランドマーク）, OpenCV, scikit-learn |
| 相談 | OpenAI API + ローカルRAG（JSONLコーパス） |
| DB | PostgreSQL（開発・本番）, SQLite（ローカル単独実行） |
| デプロイ | Docker Compose, nginx, Caddy 2, GitHub Actions（self-hosted ランナー） |

## 5. 画面フロー

### 5.1 モジュール選択（ホーム）

パーソナルカラー / 肌ケア分析 / ネイル・ペディ / バーチャル整形 から選ぶ。Webアカウントで入っていれば右上に連携状態を表示する。

### 5.2 肌ケア分析（6ステップ）

```
1 アンケート → 2 写真入力 → 3 分析 → 4 推薦 → 5 結果シート → 6 相談
```

- ステップ1は個人情報の同意前は次に進めない。
- ステップ4で成分・カテゴリ別の商品列・成分の根拠を見る。
- ステップ5の結果シートに選んだ商品が載り、QRが付く。

### 5.3 パーソナルカラー（6ステップ）

```
1 基本情報 → 2 撮影/アップロード → 3 パーソナルカラー結果 → 4 アイテムマッチング → 5 スタイル → 6 結果シート
```

Webに保存されたパーソナルカラーがあれば、ステップ2・3をスキップできる。

### 5.4 ネイル・ペディ

アップロード → ネイル検出 → 色の選択 → 発色プレビュー → 類似デザイン → その色で購入できる商品。

### 5.5 バーチャル整形

基本情報・目標 → 写真分析 → 顔の比率 → プレビューカード → 相談用レポート。

## 6. バックエンドのモジュール構成

```text
backend/app/
├── main.py                アプリケーションのエントリ
├── api/routes.py          すべてのHTTPエンドポイント
├── core/                  設定・DBセッション
├── models/domain.py       SQLAlchemyモデル
├── schemas/api.py         リクエスト・レスポンススキーマ
├── ai/                    モデルローダ（肌・皮膚科・パーソナルカラー・ネイル）
└── services/              ドメインロジック（約37モジュール）
```

サービス層の主なまとまり。

| まとまり | モジュール |
|---|---|
| 分析 | `skin_analyzer`, `body_skin_analyzer`, `dermatology_analyzer`, `personal_color_analyzer`, `face_shape_analyzer`, `nail_design_index`, `virtual_surgery_simulator` |
| 推薦 | `recommender`, `routine_steps`, `body_categories`, `pediatric_care`, `derma_condition_care` |
| 知識 | `skincare_ingredient_knowledge`, `problem_skin_knowledge`, `ingredient_aliases`, `kr_ingredient_notice` |
| 相談 | `chatbot`, `chat_catalog_answers`, `llm_consult` |
| 商品・プラットフォーム | `oliveyoung_*`, `amazon_catalog`, `rakuten_*`, `matsukiyo_matcher`, `naver_*`, `platform_resolver`, `platform_availability`, `product_image_provider` |
| その他 | `makeup_applier`, `nail_palette`, `image_router`, `data_retention`, `seed` |

## 7. 主要API

| 分類 | エンドポイント |
|---|---|
| 状態 | `GET /health`, `GET /ready` |
| アカウント | `GET /api/auth/config`, `POST /api/auth/exchange`, `GET /api/auth/me`, `DELETE /api/me/data` |
| 肌 | `POST /api/analyze-skin`, `POST /api/recommend`, `GET /api/history` |
| パーソナルカラー | `POST /api/analyze-personal-color`, `GET /api/personal-color/profile`, `POST /api/personal-color/item-match`, `POST /api/analyze-face-shape` |
| スタイル | `POST /api/style/makeup-preview`, `POST /api/style/makeup-preview/photo`, `GET /api/style/mood-thumbnails` |
| ネイル | `POST /api/analyze-nail-design` |
| バーチャル整形 | `POST /api/virtual-surgery/simulate`, `/preview-cards`, `/retouch` |
| 相談 | `POST /api/chat` |
| 商品 | `GET /api/products` |
| カートハンドオフ | `POST /api/cart/handoff`, `POST /internal/cart-handoff/resolve` |
| 運用 | `GET /api/admin/statistics` |

## 8. データモデルの概要

11テーブル。詳細は `AI_ERD_ja.md`。

| まとまり | テーブル |
|---|---|
| アカウント・連携 | `users`, `cart_handoffs`, `used_tickets` |
| 分析 | `surveys`, `skin_analyses` |
| カタログ | `brands`, `products`, `ingredients`, `product_ingredients` |
| 履歴 | `recommendation_histories`, `chat_histories` |

## 9. 推薦ロジックの概要

### 9.1 顔

```
スコア(6項目) + アンケート ──► 優先お悩み集合
        │
        ▼
  成分推論(infer_ingredients) ──► 上位5件
        │
        ▼
  ルーティンスロット別の商品列（クレンザー・化粧水・美容液・保湿・日焼け止め）
        │  美容液のみ写真のお悩み基準、他は品質（評価・肌タイプ適合）
        ▼
  プラットフォームリンク付与 → リンクが空のカードを除去 → 要約文・成分の根拠
```

### 9.2 体・皮膚科

疾患スクリーニングの結果を基準にボディ洗浄・保湿のスロットを埋める。刺激成分を避けるべき疾患の場合は、**成分が確認できた商品のみ**を載せる。成分が不明な商品は回避チェックができないためである。

### 9.3 パーソナルカラーのアイテムマッチング

```
シーズン・トーン → カテゴリ別の色キーワード → ライブ検索 + ローカルカタログ
        → resolve（リンク付与） → balance（列のバランス） → 画面
```
⚠ **resolve を balance より先に**行わないと列が空になる。順序を戻すと一部の列が丸ごと空く。

## 10. 外部プラットフォームのリンク

| プラットフォーム | 地域 | 方式 |
|---|---|---|
| オリーブヤング | KR/グローバル | カタログ照合による直リンク、失敗時は検索リンク |
| Amazon | KR/JP | 検証済みのASIN直リンクのみ |
| 楽天 | JP | API検索結果の商品URL |
| マツキヨ | JP | 照合できた場合は検索リンク |

価格は表示しない。1枚のカードに販売先が複数あり、表示価格がどこにも一致しない。

## 11. 多言語の設計

| 対象 | 方法 |
|---|---|
| 固定文言 | フロントの辞書（`i18n.ts`） |
| 組み立て型の文 | サーバーが `*_ja` の対を作って一緒に返す |
| 知識コーパス | 日本語訳があるレコードのみ使用。無ければ段落を省略 |
| 商品名・成分名 | 固有名詞のため翻訳しない |

組み立て型の韓国語文はテストでリストが固定されており、新しく増えると分類するまで失敗する。

## 12. 運用上の考慮

- モデル・RAG は `/data` のマウントに依存する。新しいデータファイルはランタイムのバンドル一覧にも入れないと、本番で静かに落ちる。
- デプロイは self-hosted ランナーで走り、CI 成功後に**デフォルトブランチでのみ**トリガーされる。
- 写真は分析後に元のファイル名を残さない。
- 相談・推薦の応答が長くなり得るため、プロキシのタイムアウトを300sに合わせる。
