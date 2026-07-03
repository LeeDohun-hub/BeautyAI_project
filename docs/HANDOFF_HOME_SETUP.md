# 회사 PC → 집 PC 이전 가이드 (2026-07-03)

회사 PC에서 push 완료(`main` @ `b29e920`). 집에서는 **git pull + 아래 2가지 수동 이전**만 하면 그대로 이어집니다.

---

## ✅ git이 이미 옮긴 것 (pull하면 끝)
- 코드 전부 (backend/frontend), `docker-compose.yml`, `Dockerfile`
- 문서: `docs/CLAUDE_HANDOFF_20260703.md`(오늘 작업 전말), `docs/PERSONAL_COLOR_EVAL.md`
- 스크립트: `scripts/evaluate_personal_color_model.py`, `build_personal_color_eval_manifest.py`, `experiment_lab_warmcool.py`, `prepare_personal_color_face_crops.py`

## ❌ git이 안 옮기는 것 (반드시 수동 이전) — gitignore
USB나 개인 클라우드로 옮기세요. **채팅/공개 저장소에 올리지 말 것.**

1. **`.env`** (프로젝트 루트, 비밀키) — 이게 없으면 백엔드·API 안 돔
   - 키: `OPENAI_*`, `NAVER_*`, `RAKUTEN_*`, `ROBOFLOW_*`, `KAGGLE_*`, `DATABASE_URL`, 모델경로 등
2. **`data/models/*.pt`** (총 ~38MB) — 이게 없으면 `model_used=0`(휴리스틱 폴백)
   - `personal_color_efficientnet.pt` (16MB) ← 퍼스널컬러 딥러닝, **필수**
   - `skin_efficientnet_b0.pt` (16MB)
   - `body_skin_mobilenet_v3.pt` (6MB)

## 🟡 선택 이전 (있으면 시간 절약, 없으면 재생성 가능)
- `data/manifests/personal_color_manifest.csv` (Deep Armocromia 매니페스트)
- `data/eval/lab_features.csv` (LAB 특징 캐시 — 없으면 재추출에 ~20분)
- `data/eval/*.csv`, `data/eval/reports_*/` (평가 매니페스트·리포트)
- **대용량 데이터셋은 이전 불필요**: Deep Armocromia(~4GB)는 재다운, CapstoneA는 `.env`의 ROBOFLOW 키로 재다운 가능

---

## 🏠 집 PC 세팅 순서
```bash
# 1) 코드 받기
git clone https://github.com/LeeDohun-hub/BeautyAI_project.git   # 또는 기존 폴더에서 git pull
cd BeautyAI_project

# 2) .env 를 프로젝트 루트에 복사 (USB에서)
#    data/models/*.pt 를 data/models/ 에 복사 (USB에서)

# 3) 실행
docker compose up --build
```

### 검증 (모델이 켜졌는지)
```powershell
docker compose exec backend python -c "from app.core.config import get_settings; from app.ai.personal_color_model import EfficientNetSeasonClassifier; p=get_settings().resolved_personal_color_model_path; c=EfficientNetSeasonClassifier(p); print(p); print('available=',c.available,'load=',c.load())"
# 기대: /data/models/personal_color_efficientnet.pt  available= True load= True
```
- 또는 브라우저 Step1에 얼굴 업로드 → 결과 칩에 **"딥러닝 모델 사용"** 이면 정상(`휴리스틱 보조`면 모델 미로드).

### ⚠️ 함정 (오늘 겪은 것)
- docker 볼륨은 **`./data:/data`** 여야 함(`/app/data` 아님). 컨테이너 `config.project_root`가 `/`로 잡혀서 그럼. 이미 `docker-compose.yml`에 반영+env 절대경로 고정됨 — **건드리지 말 것.**

---

## 다음 작업 (집에서 이어서)
`docs/CLAUDE_HANDOFF_20260703.md` §16 참고. 요약:
- ① KR 소형 홀드아웃(공개 K-연예인 50~100장)으로 실사용 정확도 측정
- ② 키오스크 통제촬영 프로토타입
- ③ FaRL vs mediapipe 크롭 비교
- ④ 동의기반 수집·라벨 파이프라인 설계
- (핵심 결론: 모델이 Deep Armocromia에 과적합 → 아키텍처 아닌 **동아시아 실사용 데이터**가 병목)
