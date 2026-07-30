# 배포 가이드 (BeautyAI)

작성 2026-07-28 · 갱신 2026-07-30
상태: **로컬에서 프로덕션 구성 실증 완료** (E2E 16/16). AWS EC2 배포 절차는 §5 — 실배포는 미실행.

---

## 1. 왜 기존 구성으로는 배포가 안 됐나

| 문제 | 조치 |
|---|---|
| `frontend/Dockerfile` 이 `npm run dev`(Vite 개발서버) | `Dockerfile.prod` 신설 — 정적 빌드 후 nginx 서빙 |
| API URL 이 번들에 구워져 환경마다 재빌드 필요 | nginx 가 `/api` 를 프록시 → 같은 오리진 호출, **이미지 하나로 어느 환경에나** |
| `./data:/data` 통째 마운트(16.5GB) — 클라우드엔 그 볼륨이 없음 | `build_runtime_bundle.py` 로 **137MB** 슬림 번들 |
| `chromadb` 가 requirements 에 있으나 코드에서 미사용 | 제거 — 백엔드 이미지 3.53GB → **3.23GB** |
| `ultralytics` 추가 시 CUDA torch 가 딸려와 이미지가 **10.2GB** 로 부풂 | Dockerfile 에서 **CPU torch 를 requirements 보다 먼저** 설치 → **3.79GB** |
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

이미지 크기: 백엔드 **3.79GB**(네일 기능 포함) / 프론트 **74.4MB**(기존 개발용 592MB 대비 87%↓)

### ⚠️ Dockerfile 설치 순서 함정 (실측 3.23GB → 10.2GB → 3.79GB)

`ultralytics` 를 `requirements.txt` 에 넣고 그걸 CPU torch 보다 **먼저** 설치하면, pip 가
ultralytics 의 `torch` 요구를 PyPI 기본 휠(**CUDA 빌드**)로 해결하면서 `nvidia-*`(2.7GB)와
`triton`(0.7GB)을 끌고 온다. 뒤이어 CPU torch 를 깔아도 이미 들어온 CUDA 패키지는 레이어에 남는다.

→ **CPU torch 를 requirements 보다 먼저** 설치하면 요구가 이미 충족돼 CUDA 를 받지 않는다.
확인법: `docker run --rm <image> sh -c "ls /usr/local/lib/python3.11/site-packages | grep -E '^(nvidia|triton)'"`
가 비어 있어야 한다(`nvidia_ml_py` 는 ultralytics 의 순수 파이썬 패키지라 무관).

### 네일 기능 end-to-end 실측 (프록시 경유)

`POST /api/analyze-nail-design` → `feature_available=true`, index 6,340, 네일 3개 검출,
유사 디자인 5건(썸네일 base64 13KB씩), 시즌 적합도 `가을 웜 뮤트 81.6점`.

## 5. AWS EC2 배포 (2026-07-30 확정)

**방식: EC2 단일 인스턴스 + docker compose. 런타임 번들은 이미지에 COPY.**

왜 이 조합인가:
- 컨테이너가 **계속 떠 있어야** 한다. 기동 시 카탈로그·모델을 데우는 데 40초가 걸리고,
  그 후 요청은 캐시 덕에 빠르다(추천 14초 → 재요청 9초). 태스크가 자주 뜨고 지는
  Fargate 류는 매번 4.5GB 이미지 pull + 40초 워밍을 다시 치른다.
- 번들을 마운트가 아니라 **이미지에 굽는다**. 마운트에 의존하면 원격 호스트에 번들을 따로
  올려야 하고, 빠뜨리면 **에러 없이 기능만 조용히 죽는다**(실측 2회: 2026-07-28 카탈로그
  0건, 2026-07-30 ASIN 검증파일 누락 → 아마존 매칭 18.8%→5%).

### 5.1 인스턴스 사양

| 항목 | 값 | 근거 |
|---|---|---|
| 타입 | **t3.medium (2 vCPU / 4GB)** | 백엔드 컨테이너 실측 **1.24GB** 상주. 2GB 티어(t3.small)는 OS·Docker 오버헤드까지 더하면 빠듯하다 |
| 디스크 | 30GB gp3 이상 | 백엔드 이미지 4.54GB + 프론트 74.5MB + 레이어 캐시 |
| OS | Amazon Linux 2023 또는 Ubuntu 22.04 | docker + compose plugin 설치 |
| 보안그룹 | 80/443 인바운드 | 백엔드(8000)는 **열지 않는다** — nginx 프록시로만 접근 |

⚠ 로컬에서 개발 스택과 프로덕션을 동시에 띄우면 메모리 경합으로 응답이 3~10배 느려진다
(실측: 추천 14초 → 125초). 벤치마킹은 한쪽만 띄우고 할 것.

### 5.2 이미지 만들기

번들은 **빌드 전에** 만들어야 한다. 없으면 COPY 가 실패한다.

```bash
python scripts/build_runtime_bundle.py          # dist/runtime_data (372MB)
docker compose -f docker-compose.prod.yml --env-file .env.prod build
```

- 백엔드는 `backend/Dockerfile.prod`(컨텍스트 = 저장소 루트)로 빌드된다.
  루트 `.dockerignore` 가 허용목록이라 `data/`(18GB)는 컨텍스트에 실리지 않는다.
- 개발용 `backend/Dockerfile`(컨텍스트 = `backend/`)은 그대로 둔다.

### 5.3 EC2 로 옮기는 두 가지 방법

**(a) 인스턴스에서 직접 빌드** — 레지스트리 불필요, 가장 단순
```bash
# EC2 에서
git clone <repo> && cd BeautyAI_project
# 모델·카탈로그 원본(data/)이 있어야 번들을 만들 수 있다 → S3 등으로 필요한 것만 전송
python scripts/build_runtime_bundle.py
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```
→ 빌드에 CPU·시간이 들고(t3.medium 에서 수십 분), `data/` 원본을 인스턴스에 올려야 한다.

**(b) 로컬에서 빌드 → ECR 푸시 → EC2 에서 pull** *(권장)*
```bash
# 로컬
aws ecr create-repository --repository-name beautyai-backend
aws ecr get-login-password --region <리전> | docker login --username AWS --password-stdin <계정>.dkr.ecr.<리전>.amazonaws.com
docker tag beautyai_prod-backend:latest  <계정>.dkr.ecr.<리전>.amazonaws.com/beautyai-backend:<태그>
docker push <계정>.dkr.ecr.<리전>.amazonaws.com/beautyai-backend:<태그>
# 프론트도 동일하게
```
EC2 에는 `docker-compose.prod.yml` 의 `build:` 를 `image:` 로 바꾼 파일을 두고 `up -d` 한다.
→ **번들이 이미 이미지 안에 있으므로 EC2 에 `data/` 를 올릴 필요가 없다.**

### 5.4 기동 확인 (순서대로)

```bash
curl -f http://<호스트>/health   # {"status":"ok"}   — 프로세스 생존
curl -f http://<호스트>/ready    # {"status":"ready"} — 워밍 완료(기동 후 ~40초)
```

- ALB/타깃그룹 헬스체크는 **`/ready`** 를 봐야 한다. `/health` 로 두면 워밍 전에 트래픽이
  붙어 첫 사용자가 30초를 기다린다(실측).
- 반대로 **liveness(재시작 판단)에 `/ready` 를 쓰면 안 된다.** 워밍 중 503 을 '죽음'으로 읽고
  재시작하면, 재시작마다 워밍을 다시 해 영원히 준비되지 않는다.
- 번들이 제대로 들어갔는지 확인:
  ```bash
  docker compose -f docker-compose.prod.yml exec backend python -c \
    "from app.services import amazon_catalog as ac; print(len(ac._load_items('us')), len(ac._dead_asins()))"
  # 63801 476  ← 0 이 나오면 번들 누락
  ```

### 5.5 아직 안 된 것

1. **ECR 푸시 자동화** — CI 는 빌드만 한다. 태깅·푸시는 수동.
2. **HTTPS** — 현재 nginx 는 8080 평문. ALB + ACM 인증서, 또는 인스턴스에 Caddy/certbot 필요.
3. **백엔드 이미지 4.54GB** — torch CPU + mediapipe + 번들 372MB. 줄이려면 멀티스테이지나
   추론 ONNX 이관 검토.
4. ~~슬림 번들 전달 방식~~ **완료(2026-07-30)** — 이미지에 COPY 로 확정.
5. ~~네일 기능 포함~~ **완료(2026-07-28)** — `--no-nail` 로 빼면 번들이 작아지고
   `/api/analyze-nail-design` 이 `feature_available=false` 로 응답한다.

## 6. 주의

- `.env.prod` 는 `.gitignore` 의 `.env.*` 에 걸려 커밋되지 않는다(`.env.prod.example` 만 예외).
- `dist/` 도 gitignore 대상이라 런타임 번들은 배포 시점에 다시 만든다.
- 로컬 개발용 `docker-compose.yml` 은 그대로 둔다 — mysql·Vite 개발서버가 필요한 흐름이 있다.
