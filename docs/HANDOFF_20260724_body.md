# 집에서 이어서 작업 — 바디 추천 (2026-07-24)

회사 PC에서 push 완료(`main`). 집에서는 **git pull + .env·모델 수동 이전 + docker 재빌드**면 그대로 이어집니다.

---

## ✅ git이 옮긴 것 (pull하면 끝)
- 코드 전부(backend/frontend), `docker-compose.yml`
- 오늘 만든 바디 추천 시스템 소스·테스트·문서
- 상세 설계: **`docs/BODY_CATEGORY_SPEC.md`** (§1~11, 오늘 작업 전말 — 여기부터 읽으세요)

## ❌ git이 안 옮기는 것 (수동 이전 — USB/개인클라우드, 공개 저장소 금지)
1. **`.env`** (루트, 비밀키) — 없으면 백엔드·DB·API 안 돔
   - `DATABASE_URL`(운영 Supabase — **이게 카탈로그 6,991건·바디 970건의 실제 저장소**), `RAKUTEN_*`, `NAVER_*`, `OPENAI_*` 등
   - ⚠️ `docker-compose.yml`이 이제 `.env`의 `DATABASE_URL`을 상속하므로, `.env`가 없으면 빈 로컬 MySQL(상품 25개)로 폴백 → 추천이 빔
2. **`data/models/*.pt`** — 없으면 분석 휴리스틱 폴백
   - `skin_efficientnet_b0.pt`, `body_skin_mobilenet_v3.pt`(또는 derma 2단), `personal_color_*.pt`

## 🟡 선택 이전 (없으면 재생성 가능, 있으면 시간 절약)
바디 성분·이미지는 **운영 Supabase에 이미 적재**돼서 `.env`만 있으면 집에서도 바로 나옴.
아래는 재수집/보강할 때만 필요:
- `data/manifests/body_products.csv` (바디 카탈로그 — `scripts/build_body_catalog.py`로 재생성)
- `data/manifests/oliveyoung_kr_ingredients.csv` (KR 고시 전성분 — `scripts/enrich_ingredients_oliveyoung.py`로 재수집, curl_cffi)
- `data/manifests/rakuten_jp_ingredients.csv` (JP 라쿠텐 전성분+직링크)
- `data/manifests/oliveyoung_kr_products.csv` (goodsNo 카탈로그)

---

## 🏠 집 PC 세팅
```bash
git pull                       # 또는 clone
# .env 를 루트에, data/models/*.pt 를 data/models/ 에 복사(USB)
docker compose up -d --build   # .env의 Supabase를 백엔드가 상속
```
확인: STEP3 재분석 → 바디 추천 3컬럼(세정/보습/집중케어) + 구매버튼이 뜨면 정상.

---

## 📌 현재 상태 (이번 세션 완료분, 운영 반영됨)
- 바디 상품 6→970건, `body./hand./foot.` 네임스페이스로 얼굴과 분리
- 성분: 올영 고시(KR)·라쿠텐(JP) 전성분, 성분 보유율 60%. 지어낸 성분 815건 제거
- 추천: 바디 슬롯(세정→보습→집중케어), **성분 없으면 추천 금지**, 자극성분 2중 배제, 지역별 구매가능 상품만
- 영유아·아동: age_group `baby`/`child` → 안내+소아안전 큐레이션(액티브·향료 배제)
- **마츠키요 크롤 배제**(2026-07-24 결정): `build_body_catalog`에서 수집 제거 + 런타임 필터. DB 옛 마츠키요 행은 추천에서 걸러짐(재적재 불필요)
- 테스트 246 pass

## 🔜 내일/집에서 할 일
1. **바디 커버리지 갭 보강**
   - 아마존 US/HF는 성분 출처가 없음(상품명 추론만)
   - JP 집중케어(body.treatment/oil) 성분보유 상품 부족 → 컬럼이 빔
   - 남은 성분 미보강 상품: `scripts/enrich_db_ingredients_from_oliveyoung.py`(IP 쿨다운 후 `--delay 4`)
2. **영유아 큐레이션 프론트 확인** — 나이 입력(0~2 baby / 3~9 child) → 밴드 실동작, 안내문·순한상품만 뜨는지
3. (마츠키요 배제 후) JP 바디가 아마존JP·글로벌만 남아 얇음 — 필요시 아마존JP 바디 크롤 보강 검토

## 🗺️ 핵심 파일 지도
| 파일 | 역할 |
|---|---|
| `backend/app/services/body_categories.py` | 카테고리 기준·분류(브랜드 폴백 포함) |
| `backend/app/services/ingredient_aliases.py` | 한/일 성분명→표준명 매핑 |
| `backend/app/services/pediatric_care.py` | 소아 안전 게이트 |
| `backend/app/services/recommender.py` | `recommend_derma_care`(바디)·`_recommend_pediatric`·`build_body_columns`·마츠키요 배제 |
| `backend/app/api/routes.py` | region 전달·라쿠텐 직링크·원산지 폴백 |
| `scripts/build_body_catalog.py` | 소스→body_products.csv |
| `scripts/load_body_catalog_to_db.py` | DB 적재(`--sqlite`/운영은 `BODY_LOAD_CONFIRM=yes`) |
| `docs/BODY_CATEGORY_SPEC.md` | **전체 설계·의사결정 기록** |
