# BeautyAI 詳細設計書

> 韓国語版: [AI_상세설계서.md](./AI_상세설계서.md)

## 1. 文書の目的

基本設計書が「何を作るか」なら、本書は「どこにどう入っているか」を記す。コードを初めて開く人がファイルまでたどり着ける水準で書く。

- 作成基準: 2026-08-10、実装コード

## 2. プロジェクト構成

```text
BeautyAI_project
├── backend/
│   ├── app/
│   │   ├── main.py               FastAPI アプリ
│   │   ├── api/routes.py         すべてのエンドポイント
│   │   ├── core/                 設定(config)・DBセッション(database)
│   │   ├── models/domain.py      SQLAlchemyモデル 11件
│   │   ├── schemas/api.py        リクエスト・レスポンススキーマ
│   │   ├── ai/                   モデルローダ（肌・皮膚科・パーソナルカラー・ネイル）
│   │   └── services/             ドメインロジック 約37モジュール
│   ├── alembic/                  マイグレーション
│   ├── tests/                    pytest
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx               画面全体（約6,000行）
│       ├── api/client.ts         バックエンド呼び出し
│       ├── i18n.ts               韓国語・日本語辞書
│       ├── types/api.ts          レスポンス型
│       └── styles.css            スタイル全体（約2,100行）
├── data/                         モデル(.pt)・RAG(.jsonl)・カタログ  ※ コンテナでは /data
├── docs/                         設計文書（本ファイルを含む）
├── docker-compose.yml            ローカル開発
├── docker-compose.prod.yml       本番
└── Caddyfile                     リバースプロキシ・自動HTTPS
```

## 3. 環境設定

| キー | 既定値 | 説明 |
|---|---|---|
| `DATABASE_URL` | ローカルSQLite | 開発も Postgres 推奨（本番と同じエンジン）。本番DB接続には別途ガードがある |
| `APP_ENV` | — | `production` のとき本番DBガードが動作 |
| `ALLOW_PRODUCTION_DB` | false | 本番DBを意図的に見るときのみ true |
| `JWT_SECRET` | — | **BeautyWEB と同じ値**でなければチケット検証ができない |
| `REQUIRE_LOGIN` | false（ローカル） | 本番は true |
| `CORS_ORIGINS` | localhost:5173 | フロントのオリジン |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | — | 無ければ相談が知識ベースへフォールバック |
| `SKIN_MODEL_PATH` ほか | `/data/models/*.pt` | 無ければ該当機能がオフになる |
| `RAKUTEN_*`, `NAVER_*` | — | 商品検索 |
| `WEB_LOGIN_URL`, `WEB_CART_URL` | — | Web連携リンク |

## 4. API詳細

### 4.1 状態

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/health` | 生存確認 |
| GET | `/ready` | 依存関係の準備確認 |

### 4.2 アカウント・個人情報

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/auth/config` | ログイン要否・Webリンク |
| POST | `/api/auth/exchange` | Webハンドオフチケット → AIセッション（12h） |
| GET | `/api/auth/me` | 現在のセッション利用者 |
| DELETE | `/api/me/data` | 自分の分析・アンケート・推薦・相談履歴を削除 |

### 4.3 肌分析・推薦

| メソッド | パス | リクエスト | レスポンス |
|---|---|---|---|
| POST | `/api/analyze-skin` | `image`（ファイル）, `analysis_mode`（`auto`/`face`/`body`） | `analysis_id`, `scores`（6項目）, `body_conditions`, `summary`, `confidence_note(_ja)`, `model_available`, `urgent` |
| POST | `/api/recommend` | アンケート + スコア/analysis_id + 地域・プラットフォーム | `ingredients`, `products`, `product_columns`, `explanation(_ja)`, `evidence(_ja)` |
| GET | `/api/history` | — | 推薦履歴 |

`explanation` は改行を含む要約文で、350字前後の成分の根拠は `evidence` として分離して返す。フロントは要約を `pre-line` で描画し、根拠は折りたたむ。

### 4.4 パーソナルカラー・スタイル

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/analyze-personal-color` | シーズン判定 + パレット + `skin_summary(_ja)` + `decision_note(_ja)` |
| GET | `/api/personal-color/profile` | Webに保存されたパーソナルカラー |
| POST | `/api/personal-color/item-match` | カテゴリ別の商品列 |
| POST | `/api/analyze-face-shape` | 顔型・比率 |
| POST | `/api/style/makeup-preview` | メイクカラーのプレビュー |
| POST | `/api/style/makeup-preview/photo` | 写真上へのメイク適用 |
| GET | `/api/style/mood-thumbnails` | ムードのサムネイル |

### 4.5 ネイル・バーチャル整形

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/analyze-nail-design` | ネイル検出・色抽出・類似デザイン |
| POST | `/api/virtual-surgery/simulate` | 目標別シミュレーション |
| POST | `/api/virtual-surgery/preview-cards` | プレビューカード |
| POST | `/api/virtual-surgery/retouch` | 利用者が選んだ位置のみのシミ処理 |

### 4.6 相談

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/chat` | `message`, `context`（`scores`+`survey`）, `lang` → `answer`, `sources` |

処理の順序が重要である。

```
1) カタログの質問か？  ── はい ──► DB照会で答える（LLMを経由しない）
   │ いいえ
2) LLMが有効か？      ── はい ──► 根拠を検索したうえで LLM が回答を作成
   │ 失敗
3) 問題肌コーパス → 成分コーパス → キーワードフォールバック → 範囲外の案内
```

1番を先頭に置く理由は、在庫や取り扱いの有無をモデルが作り話すると、利用者を店舗まで無駄足させてしまうからである。

### 4.7 商品・ハンドオフ・運用

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/products` | カタログ全体 |
| POST | `/api/cart/handoff` | 結果シートQR用の使い捨てコード発行 |
| POST | `/internal/cart-handoff/resolve` | WEB がコードで商品リストを受け取る |
| GET | `/api/admin/statistics` | 運用統計 |

## 5. 主要スキーマ

### 5.1 `SurveyInput`

性別、年代、肌タイプ、敏感度、お悩み（肌・メイク・部位・男性向け追加）、ルーティンのレベル。

### 5.2 `SkinScores`

`acne` / `pore` / `wrinkle` / `redness` / `pigmentation` / `oiliness`、各 0〜100。

⚠ 6項目は完全には独立しない（ラベル自体が一部重なる）。画面は3グループ・3区分で見せる。

### 5.3 `RecommendationResponse`

`ingredients`, `products`, `product_columns`, `explanation`, `explanation_ja`, `evidence`, `evidence_ja`。

### 5.4 `ProductColumn`

`key`, `label`, `reason`, `products[]`。フロントは `key` でヘッダーの色を選ぶ。

## 6. 分析サービスの詳細

### 6.1 `skin_analyzer`

- 顔検出（MediaPipe） → 余白を持たせたクロップ → モデル推論。
- 赤みは回帰出力ではなく **LAB a\* に基づく色の実測値**で置き換える。学習データがほとんど無く、回帰出力を信頼できないためである。
- ホワイトバランス補正はマスキングより**先に**かける。
- 複数枚を入れると平均を取る（照明によるブレが最大の誤差要因である）。

### 6.2 `dermatology_analyzer` / `body_skin_analyzer`

2段構成（ゲート → 分類）。確定診断ではないことを要約文に明示し、悪性の疑いは商品推薦ではなく受診を案内する。

### 6.3 `personal_color_analyzer`

- 分光測色を基準に学習した Lab 回帰 → 季節ルールの2段構成。
- 判定根拠（`skin_summary`）と境界の案内（`decision_note`）を韓国語・日本語の2種類作る。
- 照明が色を歪めた写真は判定から除外する。

### 6.4 `nail_design_index`

セグメンテーションでネイル領域を探し、色を抽出する。発色プレビューは楕円近似のため、実際と異なり得ることを画面に明示する。

## 7. 推薦サービスの詳細

### 7.1 成分推論 `infer_ingredients`

スコア45以上の項目 + アンケートのお悩み + 年齢による優先度 + 敏感度・肌タイプの補正で優先お悩み集合を作り、成分の `targets` との積集合が大きい順に上位5件を選ぶ。

### 7.2 商品列 `build_product_columns`

ルーティンスロット（クレンザー・化粧水・美容液・保湿・日焼け止め）ごとに候補を集め、列あたり4件まで選ぶ。美容液のみ写真のお悩み基準で、他は品質（評価・肌タイプ適合）基準である。

⚠ ランキングのループで成分の関連を `selectinload` すると、リクエストあたり数秒増える。キャッシュされた `ingredient_index()` を使う。

### 7.3 要約文の組み立て

```
build_explanation()      韓国語の要約（改行を含む）
build_explanation_ja()   日本語の要約
build_skincare_recommendation_hint()  成分の根拠 → evidence フィールド
```

商品名は34字で切り ` · ` でつなぐ。カタログの原タイトルにカンマが含まれるため、カンマでつなぐと項目の境界が消える。切ったあとに重複も除去する。

### 7.4 知識検索 `skincare_ingredient_knowledge`

- コーパスは JSONL（約8,300件）。お悩み語・質問・メタデータをトークン化してスコアを出す。
- 採用しきい値は 6.0。下げると一般的な単語が2つ重なるだけで、主題の異なる回答が出てしまう。
- コーパスの回答は**事例の原文**であり、最初の文がその事例本人の年齢・性別・肌タイプで始まる。そのため、関連度が同程度の候補の中では**利用者と属性が同じ事例**を優先する。
  - ⚠ 属性の適合度をスコアに足さない。足すと主題の異なる事例までしきい値を超える。1点バケットの中での**順序**にのみ使う。

### 7.5 カタログ回答 `chat_catalog_answers`

- 意図判定は保守的である。引用符/「〜という商品」/「商品名」のいずれかで名前が特定され、かつ照会の意図語がある場合のみ受け付ける。
- 商品名がブランドで始まる場合はブランドを省く（カタログが商品名にブランドを含んでいる）。
- `category` は内部キーのためラベル表に置き換え、未知のキーは隠す。
- 韓国語・日本語の文はモジュール定数に対で置く。関数の中に韓国語リテラルを残さないことで、片方だけ増える事故を構造的に防ぐ。

## 8. フロントエンドの詳細

### 8.1 構成

`App.tsx` の1ファイルでモジュール・ステップを状態として切り替える（ルーターなし）。

```ts
type AppModule = 'home' | 'skin-care' | 'personal-color' | 'nail-design' | 'virtual-surgery';
```

### 8.2 主なクライアント関数（`api/client.ts`）

`analyzeSkin`, `recommend`, `analyzePersonalColor`, `matchPersonalColorItems`, `analyzeFaceShape`, `analyzeNailDesign`, `simulateVirtualSurgery`, `previewMakeupOnPhoto`, `chat`, `createCartHandoff`, `exchangeTicket`, `fetchMe`, `deleteMyData`, `getHistory`。

### 8.3 多言語（`i18n.ts`）

- 固定文言は辞書で置き換える。
- サーバーが `*_ja` を併せて返す文は `localizedSentence(ko, ja)` で選ぶ。
- 辞書に無い組み合わせ語は単語単位で置き換える。

### 8.4 モバイルレイアウト（`styles.css`, ≤600px）

| 項目 | 処理 |
|---|---|
| 列の配置 | `xs=6` で PC と同じく2列並列（以前の `xs=12` では1画面に商品1つだった） |
| 列ヘッダー | `position: sticky`。`top` は 0 ではなく **58px** — スマホでは言語トグルが画面上部全体を覆う不透明バーになる |
| ヘッダーの色 | `data-column` でカテゴリごとに背景色・左の帯 |
| カード | 余白・文字を縮小して約348px |
| 購入ボタン | 高さは維持（タッチ下限44px）、スマホでは短い名前（`short`）で行数を減らす |

## 9. テスト設計

`backend/tests` 基準、約760件。

| まとまり | 確認内容 |
|---|---|
| 多言語 | 日本語レスポンスに韓国語が残らないか、韓/日の表のキーが一致するか |
| 組み立て型文のインベントリ | 新しい組み立て型の韓国語文が分類なしに追加されていないか（AST検査） |
| 推薦 | 性別・年齢・肌タイプに応じて列・成分が正しく分かれるか |
| 相談 | カタログの質問が通常の相談を横取りしないか、見つからなければ見つからないと言うか |
| 知識検索 | 属性がスコアに混ざらないか、主題がより合う事例が勝つか |
| 安全 | 乳幼児の経路が大人向け製品にフォールバックしないか、香料ゲートが多言語か |

⚠ CI には `data/` が無い。データを読むテストには skip ガードが必要である。

## 10. デプロイ

```
push（デフォルトブランチ） → CI（pytest · lint · build）
                     └─ 成功時 workflow_run → Deploy（self-hosted ランナー）
                                                 └─ イメージビルド → バンドル → compose up
```

- `workflow_run` は**デフォルトブランチでのみ**走る。作業ブランチにpushするとデプロイが静かに動かない。
- デプロイ失敗の有無は Deploy ジョブの所要時間から見る（1秒ならCI失敗でスキップされている）。
