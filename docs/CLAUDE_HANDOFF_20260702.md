# Claude Session Handoff — 2026-07-02

Codex 가 `CODEX_HANDOFF.md` 를 실시간 편집 중이라 충돌 회피를 위해 별도 파일로 남긴다.
이번 세션에 Claude 가 작업한 내용 + Part B(퍼스널컬러 딥러닝) 진행상태 + 다음 단계.

> ⚠️ Codex 가 backend(`recommender.py`, `personal_color_analyzer.py`, `schemas/api.py`,
> `config.py`, `skincare_ingredient_knowledge.py`)를 병행 수정 중. 아래 파일은 겹칠 수 있음.

---

## 1. 입점 리졸버 (product-centric) — 신규
- `backend/app/services/platform_resolver.py` (신규), `backend/app/api/routes.py`
- 상품 1개 = 카드 1개 + 지역별 플랫폼 버튼. 라우트: `dedup_by_line` → 랭킹 → `_balance_item_categories`(8개) → 최종 8개에 `resolve_product_platforms(product, region)`.
- `build_search_query()`: 프로모(`【ポイント10倍】`)·샵이름(`公式ショップ`,`Strawberrynet`,`EZCOSHOP`)·쉐이드 꼬리(`Coral Series`) 제거 → 아마존/올리브영 검색 0건 문제 해결.
- 올리브영: **KR=국내몰 `oliveyoung.co.kr` / JP=글로벌 `global.oliveyoung.com`**. JP는 J-뷰티(캔메이크 등)만 제외, 그 외(글로벌·K뷰티) 노출.
- **마츠키요 드롭**(사유는 `docs/banned.md`): 크롤 데이터가 스킨케어(cat:004)뿐, 색조 3%, 안티봇(HTTP2)으로 검증 불가.

## 2. 피부케어 추천 = 퍼스널컬러와 동일 구성
- `frontend/src/App.tsx`, `backend/app/api/routes.py`, `backend/app/schemas/api.py`(`RecommendationRequest.region`), `frontend/src/api/client.ts`
- 맞춤 추천 = 카드 그리드 + 이미지(네이버 검색). **지역(KR/JP) selector + 지역별 플랫폼 필터**, 카드 버튼 `ITEM_PLATFORM_META`(라쿠텐 포함) 통일.
- `recommend` 라우트: 상품 선택은 region-무관(`platform="all"`), 버튼만 `resolve_product_platforms(p, region)` + `fill_missing_images(p, region)`.

## 3. 퍼스널컬러 화이트밸런스 (조명 안정화)
- `backend/app/services/personal_color_analyzer.py`
- 눈흰자(공막) 기준 색항상성. **mediapipe 랜드마크**(회전 4방향 대응), 눈흰자 미검출 시 원본 폴백. 클램프 [0.75, 1.33].
- 검증: 같은 얼굴에 웜/쿨 조명 강제해도 진단 수렴(봄웜↔가을웜 흔들림 완화).
- ⚠️ **로컬 venv엔 mediapipe 없음**(Docker에만 설치). 로컬 테스트 시 WB는 폴백된다.

## 4. 퍼스널컬러 딥러닝 (Part B) — 진행 중 ★
- 신규: `backend/app/ai/personal_color_model.py`(`EfficientNetSeasonClassifier`, 4계절),
  `scripts/prepare_personal_color_dataset.py`, `scripts/train_personal_color_efficientnet.py`
- 수정: `backend/app/core/config.py`(`personal_color_model_path`), `backend/app/services/personal_color_analyzer.py`(모델 통합)
- **설계**: CNN은 **4계절(웜/쿨)만** 예측 → tone 결정. subtype(밝기/선명도)은 WB 보정 지표로 계산. 모델 없으면 휴리스틱+WB 폴백.
- **데이터(Deep Armocromia, 연구용)**:
  - `annotations.csv` → `data/release/annotations.csv` (있음, 4920행, 이탈리아어 계절)
  - 원본 RGB → `data/original_images_facer_masks-.../original_images_facer_masks/ORIGINAL_RGB_NOT_PROCESSED.zip` (**비번 잠김, 압축 해제 대기**)
  - 주의: annotations 경로(`RGB/.../id.jpg`) ≠ 실제(`ORIGINAL_RGB_NOT_PROCESSED/.../id.png`) — 폴더명·확장자 다름. prepare 스크립트가 (partition/class/sub_class + stem)로 재구성 + png/jpg 유연 매칭.
- **다음 단계**:
  1. `python scripts/prepare_personal_color_dataset.py --annotations data/release/annotations.csv --image-root "<풀린 ORIGINAL_RGB_NOT_PROCESSED 폴더>"`
  2. (의존성) `cd backend && uv pip install -r requirements-train.txt --python .venv\Scripts\python.exe`
  3. `backend\.venv\Scripts\python.exe scripts\train_personal_color_efficientnet.py --epochs 15`
  4. `data/models/personal_color_efficientnet.pt` 생성 → 분석기 자동 사용 (`metrics.model_used=1.0`)
- ⚠️ **Docker는 `data/`를 컨테이너에 안 넣음** → 학습한 모델을 컨테이너가 못 봄.
  - 해결: 로컬 실행(`run-backend.cmd`) 또는 `docker-compose.yml` backend 에 `volumes: - ./data:/data` 추가 후 재기동.

## 5. 결과지 QR
- `frontend/src/App.tsx` (`qrImageUrl` 헬퍼)
- 가짜 CSS QR(`.fake-qr`)을 **실제 스캔 QR 이미지**(api.qrserver.com)로 교체. QR1=앱 URL, QR2=BeautyWEB `/cart`. (실제 타깃 URL은 추후 연결)

## 상업화 메모 (퍼스널컬러 데이터)
- Deep Armocromia/CapstoneA 등 공개 얼굴셋 = **연구용/웹스크랩** → 상업 불가.
- 상업 전환: 방법(CNN)은 재사용, **자체 동의 데이터 + 특징(LAB)만 저장** 방식으로 재설계 (개인정보/초상권).

## 디스크 정리 메모
- Docker 빌드 캐시 ~5.7GB prune 완료. C: 여유 4G→23G(사용자 정리).
- 재정리 여지: `data/datasets`(3.8G, 재다운 가능), Docker WSL vhdx(16.5G, 압축 시 ~5G 회수).
