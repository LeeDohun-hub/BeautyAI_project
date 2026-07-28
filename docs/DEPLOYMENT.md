# 배포 가이드 (BeautyAI)

작성 2026-07-28 · 상태: **로컬에서 프로덕션 구성 실증 완료** (클라우드 실배포는 미실행)

---

## 1. 왜 기존 구성으로는 배포가 안 됐나

| 문제 | 조치 |
|---|---|
| `frontend/Dockerfile` 이 `npm run dev`(Vite 개발서버) | `Dockerfile.prod` 신설 — 정적 빌드 후 nginx 서빙 |
| API URL 이 번들에 구워져 환경마다 재빌드 필요 | nginx 가 `/api` 를 프록시 → 같은 오리진 호출, **이미지 하나로 어느 환경에나** |
| `./data:/data` 통째 마운트(16.5GB) — 클라우드엔 그 볼륨이 없음 | `build_runtime_bundle.py` 로 **137MB** 슬림 번들 |
| `chromadb` 가 requirements 에 있으나 코드에서 미사용 | 제거 — 백엔드 이미지 3.53GB → **3.23GB** |
| CI 가 배포 산출물을 전혀 검증 안 함 | `images` 잡 추가(compose 문법 + 두 이미지 빌드) |

## 2. 구성

```
[브라우저] → :8080 nginx(frontend) ┬─ 정적 파일(SPA 폴백)
                                   └─ /api, /health → backend:8000
                                                       ├─ /data (슬림 번들, 읽기전용)
                                                       ├─ Supabase (DATABASE_URL)
                                                       └─ redis
```

백엔드는 **호스트에 포트를 노출하지 않는다.** 외부 접점은 nginx 하나뿐이다.

## 3. 배포 절차

```bash
cd BeautyAI_project

# 1) 런타임 번들 (모델 7개 + RAG jsonl 3개 = 137MB)
python scripts/build_runtime_bundle.py
#    config 가 가리키는 파일이 하나라도 없으면 exit 1 로 알려준다.
#    (없는 채로 배포하면 그 기능이 휴리스틱 폴백으로 조용히 떨어진다)

# 2) 환경변수
cp .env.prod.example .env.prod    # DATABASE_URL 등 채우기

# 3) 기동
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

접속: `http://localhost:8080` (포트는 `WEB_PORT` 로 변경)

## 4. 검증 결과 (2026-07-28 로컬 실측)

스모크 테스트는 운영 Supabase 대신 **sqlite** 로 돌려 배포 배선만 확인했다.

| 확인 | 결과 |
|---|---|
| 프론트 정적 서빙 `/` | HTTP 200, text/html |
| nginx → 백엔드 프록시 `/health` | HTTP 200 `{"status":"ok"}` |
| 프록시 경유 `/api/products` | HTTP 200, 상품 25건 |
| SPA 폴백 `/some/deep/route` | HTTP 200 (새로고침 404 없음) |
| 백엔드 8000 호스트 노출 | 닫힘 — 의도대로 프록시로만 |
| 번들에 `localhost:8000` 구워짐 | **없음** (`baseURL:""` 확인) |
| 컨테이너 안 모델 7개 로드 | 전부 `exists=True`, personal_color `load=True` |
| RAG 로드 | 9,031 레코드 |

이미지 크기: 백엔드 **3.23GB** / 프론트 **74.4MB**(기존 개발용 592MB 대비 87%↓)

## 5. 클라우드로 올릴 때 남은 일

1. **레지스트리 푸시** — CI 는 지금 빌드만 한다. GHCR 푸시·태깅은 미구현.
2. **백엔드 이미지 3.23GB 가 크다.** 대부분 torch CPU + mediapipe다. 줄이려면
   멀티스테이지로 빌드 아티팩트를 털거나, 추론을 ONNX 로 옮기는 검토가 필요하다.
3. **메모리** — torch + EfficientNet CPU 추론이라 512MB 티어로는 부족하다. **1GB 이상** 필요.
4. **슬림 번들 전달 방식** — 이미지에 `COPY` 로 굽거나(이미지가 137MB 더 커짐) 오브젝트
   스토리지에서 부팅 시 받는다. 현재 compose 는 로컬 디렉터리 마운트라 클라우드에선 그대로 못 쓴다.
5. **네일 기능을 배포에 포함하려면** 인덱스 31MB + 썸네일 6,340개를 어떻게 올릴지 같은 결정이
   필요하고, `ultralytics` 를 `backend/requirements.txt` 에 추가해야 한다(현재 미반영).

## 6. 주의

- `.env.prod` 는 `.gitignore` 의 `.env.*` 에 걸려 커밋되지 않는다(`.env.prod.example` 만 예외).
- `dist/` 도 gitignore 대상이라 런타임 번들은 배포 시점에 다시 만든다.
- 로컬 개발용 `docker-compose.yml` 은 그대로 둔다 — mysql·Vite 개발서버가 필요한 흐름이 있다.
