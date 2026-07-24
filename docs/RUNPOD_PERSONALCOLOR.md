# RunPod 다인종 퍼스널컬러 본학습 — 압축 세팅부터 결과 회수까지 (Step by Step)

AI-Hub '글로벌 다인종 피부색 데이터'(재확보 완료)로 백본을 다인종 사전학습(Stage1)하고,
계절 데이터(Deep Armo + CapstoneA)로 4계절 헤드를 파인튜닝(Stage2)한다. **GPU 필수**라
RunPod에서 돌리고, 결과 `.pt` 만 로컬로 가져와 백엔드에 붙인다.

- 로컬 = Windows (`C:\WorkSpace\Beauty_Project\BeautyAI_project`), Git Bash 기준
- 파이썬: 로컬은 miniforge `C:/Users/suppo/miniforge3/python.exe`, 학습은 pod에서 venv
- 전송: **runpodctl**(P2P, 클라우드 불필요) 기본 + scp 대안

전체 흐름: **① 로컬 압축 세팅 → ② 업로드 → ③ pod에서 학습 → ④ 모델 회수 → ⑤ 백엔드 통합**

---

## ① 로컬 압축 세팅 (여기부터가 "압축파일 세팅")

### 1-1. 라벨 매니페스트 확인 (이미 생성됨)
```bash
cd /c/WorkSpace/Beauty_Project/BeautyAI_project
PY="/c/Users/suppo/miniforge3/python.exe"
# 없으면 생성 (실측 Lab → 밝기보정 언더톤 라벨)
[ -f data/manifests/aihub_skincolor_full_manifest.csv ] || \
  PYTHONUTF8=1 "$PY" scripts/build_aihub_skincolor_manifest.py
wc -l data/manifests/aihub_skincolor_full_manifest.csv   # 9028 (2257명×4장) 근처
```

### 1-2. 패키지 조립 (이미지 512px 다운스케일 + 매니페스트 + 스크립트 동봉)
> 19GB 원본을 그대로 올리지 않는다. 학습은 224px로 리사이즈하므로 512px면 충분하고, 업로드가 ~1–2GB로 줄어든다.
> 손상된 zip(`TS_중동,남아시아_중간색`, 0바이트)은 자동으로 건너뛴다.
```bash
PYTHONUTF8=1 "$PY" scripts/pack_runpod_pc.py --clean --max-side 512
#   → runpod_pc/ 아래로:
#      data/aihub/<대륙>/*.jpg           (Stage1 이미지)
#      data/manifests/multiethnic_all.csv (image_path/fitzpatrick/ita_avg/continent)
#      data/season/{deeparmo,capstonea}/*.jpg + *_manifest.csv  (Stage2)
#      scripts/train_global_personal_color.py, evaluate_personal_color_model.py
#      backend/requirements-train.txt, run_all.sh
#   실행 끝에 "총 용량: N MB" 와 tar 명령이 찍힌다. (조립에 ~15–25분)
```
> Stage1 데이터만 빠르게 보려면 `--aihub-only`.

### 1-3. tar 로 묶기
```bash
tar czf /c/WorkSpace/Beauty_Project/runpod_pc.tar.gz \
  -C /c/WorkSpace/Beauty_Project/BeautyAI_project runpod_pc
ls -lh /c/WorkSpace/Beauty_Project/runpod_pc.tar.gz    # 업로드할 파일
```

---

## ② RunPod 세팅 + 업로드

### 2-1. Pod 생성 (웹 콘솔)
1. https://runpod.io → **Pods → Deploy**
2. GPU: **RTX 4090** (또는 A40/L40S). 이 규모는 4090 1장이면 충분.
3. 템플릿: **RunPod PyTorch 2.x** (Ubuntu, CUDA, python3 포함)
4. Disk: Container/Volume **40GB 이상** (데이터 압축해제 여유)
5. **Deploy On-Demand** → 뜨면 **Connect → SSH** 에서 접속정보 확인
   - 예: `ssh root@<POD_IP> -p <PORT> -i ~/.ssh/id_ed25519`

### 2-2. runpodctl 준비
- **로컬(Windows)**: https://github.com/runpod/runpodctl/releases 에서 `runpodctl-windows-amd64.exe` 다운 → `runpodctl.exe`로 두고 PATH에 추가 (또는 그 폴더에서 실행)
- **Pod**: RunPod 템플릿에 기본 설치돼 있음. 없으면:
  ```bash
  wget -qO- cli.runpod.net | bash
  ```

### 2-3. 업로드 (로컬 → Pod, runpodctl P2P)
```bash
# [로컬에서]
runpodctl send /c/WorkSpace/Beauty_Project/runpod_pc.tar.gz
#   → "Code is: 8338-xxxx-xxxx-xxxx" 같은 1회용 코드가 나온다. 이 코드를 복사.
```
```bash
# [Pod SSH 안에서]
cd /workspace
runpodctl receive 8338-xxxx-xxxx-xxxx     # 로컬에서 나온 코드
tar xzf runpod_pc.tar.gz
cd runpod_pc
```
> 대안(scp): `scp -P <PORT> -i ~/.ssh/id_ed25519 /c/WorkSpace/Beauty_Project/runpod_pc.tar.gz root@<POD_IP>:/workspace/`

---

## ③ Pod에서 학습

### 3-1. 환경 + 학습 (한 번에)
```bash
# [Pod, /workspace/runpod_pc 에서]
bash run_all.sh
#   run_all.sh = venv 생성 → requirements 설치 → Stage1(20ep) → Stage2(30ep)
```

### 3-2. 또는 단계별로 (권장 — 분포 확인하며)
```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements-train.txt
python -c "import torch;print('cuda', torch.cuda.is_available())"   # True 여야 함
mkdir -p data/models

# Stage1: 다인종 사전학습 (Fitzpatrick 분류 + ITA 회귀 + 대륙 분류 멀티태스크)
python scripts/train_global_personal_color.py --stage 1 \
  --multiethnic data/manifests/multiethnic_all.csv \
  --out data/models/backbone_multiethnic.pt --epochs 20 --batch 64
#   4090에서 ~8k장×20ep ≈ 20–40분. 로그의 epoch loss 하강 확인.

# Stage2: 계절 헤드 파인튜닝 (Stage1 백본 로드 → 4계절)
python scripts/train_global_personal_color.py --stage 2 \
  --season-manifests data/manifests/deeparmo_manifest.csv,data/manifests/capstonea_manifest.csv \
  --init data/models/backbone_multiethnic.pt \
  --out data/models/personal_color_global.pt --epochs 30 --batch 64
#   → data/models/personal_color_global.pt (앱 호환 EfficientNet-B0 전체 저장)
```

### 3-3. 평가 (편향 확인 = "특정 계절 편향시 top-2")
```bash
python scripts/evaluate_personal_color_model.py \
  --model data/models/personal_color_global.pt \
  --manifest data/manifests/deeparmo_manifest.csv --split test \
  --out data/eval/reports_global_new
cat data/eval/reports_global_new/personal_color_eval_report.json
```
**확인 포인트**: confusion_matrix 에서 한 계절로 쏠리는지(예: 전부 winter). 쏠리면 학습 실패가 아니라
**단일 계절 강제의 한계** — 프로덕션 분석기가 `alternate_season`(top-2)로 이미 완충한다. 실측 근거:
동북아 62% neutral, 픽셀 warm/cool 정확도 54%(≈찍기) → **단일 확정 대신 top-2+신뢰도가 정답.**

---

## ④ 모델 회수 (Pod → 로컬)

```bash
# [Pod에서]
runpodctl send data/models/personal_color_global.pt
#   → 코드 복사 (예: 4471-yyyy-yyyy-yyyy)
#   백본도 보관하려면: runpodctl send data/models/backbone_multiethnic.pt
```
```bash
# [로컬에서]
cd /c/WorkSpace/Beauty_Project/BeautyAI_project/data/models
runpodctl receive 4471-yyyy-yyyy-yyyy
ls -lh personal_color_global.pt      # 도착 확인
```
> 대안(scp): `scp -P <PORT> -i ~/.ssh/id_ed25519 root@<POD_IP>:/workspace/runpod_pc/data/models/personal_color_global.pt ./`

### 4-1. Pod 정리 (과금 중단)
```bash
# 결과 다 받았으면 웹 콘솔에서 Pod Stop/Terminate (실행 중엔 계속 과금).
```

---

## ⑤ 로컬 백엔드 통합 + 검증

```bash
cd /c/WorkSpace/Beauty_Project/BeautyAI_project
VP="backend/.venv/Scripts/python.exe"

# 로드 sanity check
"$VP" -c "import torch;ck=torch.load('data/models/personal_color_global.pt',map_location='cpu');print(list(ck.keys()))"

# 로컬 홀드아웃으로 현행 모델과 비교 (외부 40장 등)
PERSONAL_COLOR_MODEL_PATH="data/models/personal_color_global.pt" \
  "$VP" scripts/evaluate_personal_color_model.py \
  --model data/models/personal_color_global.pt \
  --manifest data/eval/personal_color_eval_manifest.example.csv \
  --out data/eval/reports_global_local
```
- 현행 대비 좋으면 백엔드 설정의 모델 경로를 교체:
  `.env` / docker-compose 의 `PERSONAL_COLOR_MODEL_PATH` 를 `personal_color_global.pt` 로.
- 나쁘면 백본(backbone_multiethnic.pt)만 유지하고 Stage2 재조정(에폭/블렌드) 후 재평가.

---

## ⑥ Stage2 재튜닝 (1차가 현행을 못 넘었을 때)

1차 결과(external_40): 새 모델 blend 0.325 < 현행 0.425. 원인 = Stage2가 **전체 파인튜닝**이라
Stage1의 다인종 표현이 유럽셋 학습에 덮여 winter/cool 쪽으로 쏠림. 개선안 = **백본 동결 + 계절
클래스 가중치**. (학습 스크립트에 `--freeze-backbone` `--class-weight` `--label-smoothing` 추가됨.)

### 6-1. 수정된 학습 스크립트만 Pod로 재업로드 (백본 재학습 불필요)
```bash
# [로컬]
runpodctl send scripts/train_global_personal_color.py     # → 코드
# [Pod, /workspace/runpod_pc]
runpodctl receive <코드>          # scripts/ 에 덮어쓰기(같은 파일명)
mv train_global_personal_color.py scripts/ 2>/dev/null || true   # 홈에 받아졌으면 이동
```

### 6-2. 변형 3종 학습 (기존 backbone_multiethnic.pt 재사용, Stage2만)
```bash
# [Pod, /workspace/runpod_pc, venv 활성]
# A) 백본 동결 + 클래스 가중치 (핵심 개선안)
python scripts/train_global_personal_color.py --stage 2 \
  --season-manifests data/manifests/deeparmo_manifest.csv,data/manifests/capstonea_manifest.csv \
  --init data/models/backbone_multiethnic.pt --freeze-backbone --class-weight \
  --out data/models/pc_global_frozen_cw.pt --epochs 30 --batch 128 --lr 1e-3

# B) 동결 + 가중치 + label smoothing 0.1
python scripts/train_global_personal_color.py --stage 2 \
  --season-manifests data/manifests/deeparmo_manifest.csv,data/manifests/capstonea_manifest.csv \
  --init data/models/backbone_multiethnic.pt --freeze-backbone --class-weight --label-smoothing 0.1 \
  --out data/models/pc_global_frozen_cw_ls10.pt --epochs 40 --batch 128 --lr 1e-3

# C) 가중치만(동결 X) — 비교군
python scripts/train_global_personal_color.py --stage 2 \
  --season-manifests data/manifests/deeparmo_manifest.csv,data/manifests/capstonea_manifest.csv \
  --init data/models/backbone_multiethnic.pt --class-weight \
  --out data/models/pc_global_cw.pt --epochs 30 --batch 128
```
> 동결 학습은 헤드만 도니 **수십 초~1분**이면 끝. 3종 다 돌려도 금방.

### 6-3. 3종 회수 → 로컬에서 external_40로 일괄 비교
```bash
# [Pod] 한 번에 보내기
tar czf pc_variants.tar.gz data/models/pc_global_*.pt && runpodctl send pc_variants.tar.gz
# [로컬]
cd /c/WorkSpace/Beauty_Project/BeautyAI_project && runpodctl receive <코드> && tar xf pc_variants.tar.gz
VP="backend/.venv/Scripts/python.exe"
for m in pc_global_frozen_cw pc_global_frozen_cw_ls10 pc_global_cw; do
  "$VP" scripts/evaluate_personal_color_model.py --manifest data/eval/external_40_manifest.csv \
    --model-path data/models/$m.pt --out-dir data/eval/reports_$m
done
# 현행 0.425를 넘는 게 있으면 그걸 채택(PERSONAL_COLOR_MODEL_PATH 교체). 없으면 현행 유지.
```
> **현실적 기대치**: 오늘 검증대로 천장은 라벨(언더톤 애매성)이라, 재튜닝이 현행을 크게 넘긴 어렵다.
> 넘으면 채택, 못 넘으면 **현행 유지 + top-2 UX**가 정답 — 둘 다 정당한 결론.

---

## ⑦ 한국 연예인 셋 투입 Stage2 (2026-07-17 신설 — 지금은 이걸 쓴다)

⑥까지가 전부 실패한 이유가 밝혀졌다: **학습에 한국 얼굴이 8.5%(capstonea 456장)뿐이었고, 이미 만들어둔
연예인 라벨셋 667장이 매니페스트 어디에도 안 들어가 있었다.** 이번엔 그걸 넣는다.

- 자산: `korean_celebrity_face_crop_manifest.csv` 667장(연예인 60명 컨센서스, 계절 균형 155/156/179/177)
- CPU 실측: 동결로 넣으면 top-1은 0.3867(<현행 0.4133)이나 **여름 recall 0.20→0.50**(그간 죽던 클래스가 처음 살아남),
  균형acc 0.3642→0.4262. **백본 풀면 한국 1123장만으론 7에폭에 loss 0.31 = 과적합** → 유럽 볼륨 필수.

### 7-1. 패키징 (Stage1 건너뜀 — 백본 재사용)
```bash
cd /c/WorkSpace/Beauty_Project/BeautyAI_project
VP="backend/.venv/Scripts/python.exe"
PYTHONUTF8=1 "$VP" scripts/pack_runpod_pc.py --season-only --clean --max-side 512
#   → deeparmo 4920 + capstonea 456 + korean_celeb 667 = 6043장(한국 18.6%), backbone_multiethnic.pt 동봉
#   → runpod_pc/ 213MB, run_season.sh 포함. 19GB AIHub 안 건드리므로 1~2분.
tar czf /c/WorkSpace/Beauty_Project/runpod_pc_kr.tar.gz \
  -C /c/WorkSpace/Beauty_Project/BeautyAI_project runpod_pc     # 194MB
```

### 7-2. 업로드 → 학습 (**웹 UI 업로드 + pod 자체 터미널** — runpodctl/scp 안 씀)
Pod 생성은 ②-1 과 동일(RTX 4090, 템플릿 PyTorch 2.x, Disk 40GB+).
`runpod_pc_kr.tar.gz`(194MB)를 **Jupyter/웹 파일 브라우저로 `/workspace` 에 업로드**한 뒤,
**pod 터미널에 아래 한 덩어리를 붙여넣기**하면 끝.
```bash
cd /workspace && tar xzf runpod_pc_kr.tar.gz && cd runpod_pc && bash run_season.sh
```
`run_season.sh` 가 하는 일: cuda 확인 → 변형 3종 학습(pc_kr_all_ft / _ft_cw / _frozen) →
결과를 `/workspace/pc_kr.tar.gz` 로 묶기. 6043장·30ep면 4090에서 수십 분.
> **venv 안 만든다.** 템플릿의 torch+CUDA 를 그대로 쓴다(venv 파면 torch 2.5GB 재다운로드).
> cuda 줄이 `False` 로 찍히면 CPU pod 이라 헛돈다 — 즉시 중단하고 GPU pod 으로 다시 만들 것.

### 7-3. 회수 → 채점
학습이 끝나면 **`/workspace/pc_kr.tar.gz`(~50MB)를 웹 UI 로 내려받아** 로컬 프로젝트 루트에 두고:
```bash
tar xf pc_kr.tar.gz      # → data/models/pc_kr_*.pt 3개
for m in pc_kr_all_ft pc_kr_all_ft_cw pc_kr_all_frozen; do
  for s in capstonea_test external_40; do
    PYTHONUTF8=1 "$VP" scripts/evaluate_personal_color_model.py \
      --manifest data/eval/${s}_manifest.csv --model-path data/models/$m.pt --out-dir data/eval/reports_${m}_${s}
  done
done
```
> **채점 기준**: capstonea test blend **0.4133** / external_40 blend **0.4250** 을 넘어야 채택.
> ⚠️ **정확도만 보지 말 것.** capstonea는 spring이 31/75라 "전부 spring" 찍기만 해도 0.4133이 나온다
> (external_40은 균형셋이라 아무 단일계절 찍기 = 0.2500). **balanced-acc + per-class recall 동반 확인 필수** —
> 정확도 단독으로 보면 다수클래스 붕괴를 "승리"로 오독한다(⑥의 frozen_cw가 실제로 그랬다).

---

## 트러블슈팅 / 체크리스트
- **`invalid option name: set: pipefail`** (2026-07-17 실제 발생): Windows 에서 만든 `.sh` 가 CRLF 라
  bash 가 `pipefail\r` 을 옵션으로 읽어 죽는다. pod 에서 즉시 고치기: `sed -i 's/\r$//' run_season.sh`.
  근본 수정은 `pack_runpod_pc.py` 의 `write_text(..., newline="\n")` (적용됨 — 셸 스크립트는 반드시 LF).
- **`Cannot change ownership to uid 197609` 수백 줄**: Windows tar 가 기록한 UID 를 컨테이너가 재현하려다
  실패하는 것뿐, **무해**. `tar xzf ... --no-same-owner` 로 조용히 시킨다.
  ⚠️ 단 이 노이즈에 **진짜 에러가 묻힌다** — `gzip: unexpected end of file` / `Unexpected EOF in archive` 가
  같이 보이면 그건 **업로드가 잘린 것**이니 풀지 말고 크기부터 대조할 것(`ls -l`, `sha256sum`).
- **업로드가 자꾸 잘림**: 웹 UI 로 큰 파일 올리면 중간에 끊긴다. `--max-side 256` 으로 패키징하면
  213MB→88MB(tar 78MB)로 줄고 **화질 손실 없음**(학습이 `Resize((224,224))` 로 어차피 224 로 뭉갬).
- **cuda False**: 템플릿이 CPU면 헛돎. `torch.cuda.is_available()` True 확인 후 학습.
- **multiethnic rows 0**: `pack_runpod_pc.py`가 매니페스트를 못 찾음 → 1-1 먼저 실행.
- **Stage1 continent 미매칭**: 매니페스트 `continent` 값이 스크립트 `CONTINENTS` 목록과 일치해야 함(한글 그대로).
- **업로드 느림**: `--max-side 384`로 더 줄이거나, scp/네트워크볼륨 사용.
- **runpodctl 코드 만료**: 코드는 1회용·단시간 — send 직후 바로 receive.
- **디스크 부족**: Pod Volume 40GB+ 권장(tar+압축해제 동시 존재).
