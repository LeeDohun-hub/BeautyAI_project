# 2단 피부질환 모델 (Tier1 선별 게이트 + Tier2 케어 분류) — 실행 런북

목표: **의사 대체가 아니라, 중병(흑색종·피부암) 조기발견을 놓치지 않는 선별 + 광범위 케어 안내.**
- **Tier1 게이트**: `normal / benign_concern / urgent_referral` — 악성 의심을 놓치지 않는 고-recall.
- **Tier2 분류**: 질환 그룹(습진·여드름·건선·진균·기생·바이러스·색소양성·악성·기타) — 케어/성분 안내용.

라벨 통일 기준: [scripts/dermatology_taxonomy.py](../scripts/dermatology_taxonomy.py) (단일 소스).

## 데이터셋 (스마트폰/임상 도메인 우선)
| slug | 역할 |
|---|---|
| `mahdavi1202/skin-cancer` (PAD-UFES-20) | 스마트폰 병변 6종, 암 100% 조직검사 확진 → Tier1 정답 소스 |
| `shubhamgoel27/dermnet` | 임상 23종 → Tier2 breadth |
| `nazmussadat013/fitzpatrick17k` | 다인종 톤 + `three_partition_label` → Tier1 보강 |
| 기존 SkinDisNet | benign 습진/진균/기생 |
| 정상 | (1) facial-skin-datasets `normal` 폴더 + (3) 병변사진 주변부 크롭 |

## 실행 (RunPod, GPU 필수)

```bash
# 0) 환경
pip install -r backend/requirements-train.txt

# 1) 다운로드 (Kaggle 인증 필요: KAGGLE_USERNAME/KAGGLE_KEY)
python scripts/download_kaggle_datasets.py --only \
  mahdavi1202/skin-cancer shubhamgoel27/dermnet nazmussadat013/fitzpatrick17k

# 2) 통합 매니페스트 (+ 병변 주변부에서 정상 크롭 4000장 harvest)
python scripts/prepare_dermatology_dataset.py \
  --root data/datasets \
  --out data/manifests/dermatology_manifest.csv \
  --harvest-normal 4000
#   → 출력 끝에 Tier1/Tier2 분포가 찍힌다. 여기서 클래스 불균형/누락을 먼저 확인.

# 3) 학습
python scripts/train_dermatology.py --tier 1 \
  --manifest data/manifests/dermatology_manifest.csv \
  --out data/models/derma_tier1_gate.pt --epochs 15 --batch-size 32

python scripts/train_dermatology.py --tier 2 \
  --manifest data/manifests/dermatology_manifest.csv \
  --out data/models/derma_tier2_classifier.pt --epochs 20 --batch-size 32

# 4) 평가 (Tier1은 악성 recall + '악성을 정상으로 놓친 건수'가 핵심)
python scripts/evaluate_dermatology.py --tier 1 --model data/models/derma_tier1_gate.pt
python scripts/evaluate_dermatology.py --tier 2 --model data/models/derma_tier2_classifier.pt
```

## 주의 / 검증 포인트
- **먼저 2)단계 분포부터 본다.** Fitzpatrick 미러마다 CSV 컬럼명이 달라 어댑터가 0건이면
  `adapt_fitzpatrick`의 컬럼 키(`three_partition_label` 등)를 실제 헤더에 맞춰 조정.
- **Tier1 best 체크포인트는 전체정확도가 아니라 urgent recall 우선**으로 저장된다.
  평가에서 "악성→정상 오분류 건수"가 0에 가까운지 반드시 확인(가장 위험한 오류).
- **정상 크롭 도메인 함정**: 정상은 병변 사진 주변부에서 뽑아 같은 도메인이다. 별도 셀카
  정상셋만 쓰면 모델이 '도메인'을 외우므로 지양.
- 학습된 모델을 백엔드에 붙이는 통합(신규 analyzer + 라우팅)은 모델이 나온 뒤 진행한다.
```
```
