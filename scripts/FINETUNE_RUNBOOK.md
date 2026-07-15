# 범용 퍼스널컬러 파인튜닝 런북 (RunPod GPU)

**목표:** 유럽(Deep Armocromia) + 다인종 셀럽(Palette Hunt 275명)으로 EfficientNet-B0을
파인튜닝해 **유럽 밖(비유럽) 정확도를 올리되 유럽 성능은 유지**. 인물-분리 분할이라 누수 0.

**현행 베이스라인(이겨야 할 대상, model-only 기준):**
- 유럽 test: ~0.54 · 글로벌(웹) 다인종: ~0.36 · capstonea: 0.27 (블렌드 시 0.41)
- 매크로 평균(범용) ≈ 0.43 → 이걸 올리는 게 성공 기준.

**솔직한 기대치:** 라벨이 단일소스(Palette Hunt, 노이즈)·이미지가 웹(조명 노이즈)이라
극적 상승은 장담 못 함. 유럽 안 깨고 비유럽 +몇 pp면 성공. 안 오르면 "데이터 품질이 벽"임을 확정.

---

## 0. 데이터 (RunPod에 있어야 할 것)
프로젝트 루트(`BeautyAI_project/`) 기준 상대경로로 매니페스트가 작성돼 있음. 아래가 RunPod에 존재해야 함:
- `data/original_images_facer_masks-.../` (유럽 원본, 이미 RunPod에 있을 것)
- `data/datasets/global_face_crops/` (**신규 — 업로드 필요**, 약 2,690장)
- `data/manifests/finetune_train_manifest.csv`, `finetune_global_test_manifest.csv`,
  `euro_test_manifest.csv`, `capstonea_test_manifest.csv` (신규)

**글로벌 크롭 zip 만들어 업로드(로컬에서):**
```bash
cd BeautyAI_project
tar -czf global_face_crops.tgz data/datasets/global_face_crops data/manifests/finetune_train_manifest.csv data/manifests/finetune_global_test_manifest.csv data/manifests/euro_test_manifest.csv
# → global_face_crops.tgz 를 RunPod에 업로드 후: tar -xzf global_face_crops.tgz
```
※ capstonea 홀드아웃 eval을 RunPod에서도 하려면 `data/datasets/capstonea_personal_color/` +
`data/eval/capstonea_test_manifest.csv`도 업로드. (또는 eval은 로컬 CPU에서 돌려도 됨)

## 1. 의존성
```bash
cd BeautyAI_project
uv pip install -r backend/requirements-train.txt --python backend/.venv/bin/python  # torch/torchvision/pandas/sklearn
```

## 2. 베이스라인 측정 (현행 모델, 학습 전 — 반드시 먼저)
```bash
PY=backend/.venv/bin/python   # RunPod 리눅스
for m in finetune_global_test euro_test capstonea_test; do
  $PY scripts/evaluate_personal_color_model.py \
    --manifest data/manifests/${m}_manifest.csv \
    --out-dir data/eval/base_${m}
done
# 각 리포트의 method_metrics.model.accuracy (= model-only) 를 기록.
```

## 3. 파인튜닝
```bash
$PY scripts/train_personal_color_efficientnet.py \
  --manifest data/manifests/finetune_train_manifest.csv \
  --out data/models/personal_color_finetune_v1.pt \
  --epochs 20 --batch-size 32 --lr 3e-4 --label-smoothing 0.1 --mixup-alpha 0.2 --num-workers 8
# partition 컬럼(train/validation)을 그대로 사용 → 인물 누수 없음.
# --num-workers 8: RunPod 리눅스 데이터로딩 병목 해소(로컬 윈도우는 0 유지 권장).
# val_acc 는 글로벌-val(다인종) 기준. best 체크포인트 자동 저장.
```

## 4. 파인튜닝 모델 재측정 (같은 4셋)
```bash
for m in finetune_global_test euro_test capstonea_test; do
  $PY scripts/evaluate_personal_color_model.py \
    --manifest data/manifests/${m}_manifest.csv \
    --model-path data/models/personal_color_finetune_v1.pt \
    --out-dir data/eval/ft_${m}
done
```

## 5. 판정
각 셋의 **model-only accuracy**를 base vs ft 비교:
| 셋 | base(model) | ft(model) | 목표 |
|---|---|---|---|
| 글로벌 홀드아웃(439, 다인종) | ~0.36 | ? | ↑ (핵심) |
| 유럽 test(912) | ~0.54 | ? | 유지(±2pp) |
| capstonea(75) | 0.27 | ? | ↑ 또는 유지 |

- **글로벌 홀드아웃 ↑ + 유럽 유지** → 성공. 새 모델 배포 검토(블렌드는 model-only 우세였으니 끄거나 축소).
- **글로벌 안 오르거나 유럽 깨짐** → 데이터 품질이 벽. 다음은 라벨 교차검증(shadecompass 등 다중소스 컨센서스) 또는 이미지 정제(정면·자연광 선별) 후 재시도.

## 6. 새 체크포인트 회수
`data/models/personal_color_finetune_v1.pt` + `data/eval/ft_*` 리포트를 로컬로 내려서 알려주면
내가 base vs ft 표를 정리하고 배포 여부를 판단.
