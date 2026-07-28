# 네일 대체 데이터 확보 리포트 — AI-Hub 04 블로커 우회

작성 2026-07-28 · 상태: **1단계(네일 영역 검출) 언블록 완료**

AI-Hub 04 재다운로드가 막혀 있어, 공개 소스로 대체 경로를 확보하고 보유 이미지로 검증했다.
관련: [nail_design_feature_design.md](nail_design_feature_design.md) · [nail_dataset_inspection_report.md](nail_dataset_inspection_report.md)

---

## 1. 요약

| 막혀 있던 것 | 대체재 | 결과 |
|---|---|---|
| 학습 라벨(TL_발) 0바이트 → 네일 마스크 못 만듦 | 사전학습 YOLOv8 세그 모델 | **학습 없이 마스크 확보**, 발 909장 100% 검출 |
| 손(hand) 전 파일 0바이트 → 손 이미지 없음 | Roboflow 손톱 세그 데이터셋 | **손톱 7,025장 + 인스턴스 세그 라벨** 확보 |
| 리트리벌(B안) 인덱스 입력 없음 | 위 둘로 크롭 파이프라인 | 발 검증셋에서 **네일 크롭 456개** 생성 |

**결론: 설계문서 §2의 "네일 영역 검출" 단계는 AI-Hub 없이 지금 돌아간다.** 남은 블로커는
디자인 **범주 라벨**(A안 분류)뿐이고, B안 리트리벌 MVP는 착수 가능한 상태다.

## 2. 확보한 자산

### 모델 — `data/models/nails_seg_s_yolov8_v1.pt` (22.8MB)
- 출처: [mnemic/nails_seg_yolov8](https://huggingface.co/mnemic/nails_seg_yolov8) · **CC BY 4.0**
- YOLOv8s-seg, 단일 클래스 `Nail`, task=segment (박스 + 인스턴스 마스크)
- 학습 원본이 아래 Roboflow 데이터셋 → **그 데이터로 이 모델을 평가하면 누수**다.

### 데이터 — `data/nail_reference/nails_segmentation_v51_yolov8/` (225.5MB)
- 출처: [Personal Projects / nails_segmentation](https://universe.roboflow.com/personal-projects-jfbag/nails_segmentation) · **CC BY 4.0**
- 원본 3,626장 → v51(증강 포함) **7,025장**: train 6,786 / valid 231 / test 8
- 인스턴스 세그멘테이션 라벨(YOLOv8 txt) 7,025개 동봉
- 손톱(fingernail) 중심 → **AI-Hub 손 트랙 0바이트의 대체재**

> `data/` 는 .gitignore 대상이라 리포지토리에 딸려 들어가지 않는다. 재취득은 §6 명령으로.

## 3. 검증 — 보유 발 이미지 909장 (AI-Hub 04, 우리 데이터)

모델은 **손톱으로 학습**됐는데 발톱에 전이되는지가 관건이었다. `conf>=0.25` 기준:

| 소스 | 이미지 | 검출된 이미지 | 총 검출 | 이미지당 평균 | conf 중앙값 | 마스크 면적 |
|---|---|---|---|---|---|---|
| VS_디자인데이터_발 (검증) | 100 | **100 (100%)** | 470 | 4.70 | 0.936 | 5.98% |
| TS_디자인데이터_발 (학습) | 809 | **809 (100%)** | 3,732 | 4.61 | 0.940 | 6.13% |

- 검출 수 분포의 최빈값이 **5개**(발가락 수와 일치), 4~5개가 전체의 90%.
- 3D 보석·글리터가 붙은 네일아트도 잡는다(육안 확인).
- **전이 성공.** 발톱 전용 파인튜닝 없이 1단계를 쓸 수 있다.

### 손 이미지 (Roboflow valid 120장) — 참고용
120/120 검출, 이미지당 5.81개, conf 중앙값 0.944.
⚠️ 이 split은 모델의 학습 프로젝트에서 나온 것이라 **누수**다. "손에서도 동작한다"는 sanity check 이상으로 해석하면 안 된다.

## 4. 크롭 파이프라인 (리트리벌 인덱스 입력)

발 검증셋 100장 → `conf>=0.4` → 네일별 크롭 **456개** (`data/nail_crops/foot_val/`).

- 크롭 최대변 px: 최소 20 / 중앙값 55 / 최대 268
- **32px 미만 27개(5.9%)** — 새끼발톱·초점 흐림. 임베딩 전에 최소 크기 필터 필요.
- 육안 확인 결과 단색·글리터·보석·패턴 디자인이 깨끗하게 분리됨 → 임베딩/팔레트 추출에 바로 투입 가능.

## 5. 한계 (다음 작업 전에 알고 있어야 할 것)

1. **정답 마스크가 없다.** 발 라벨(TL_발)이 0바이트라 위 수치는 전부 *검출률*이지 *정확도*가 아니다. 과검출(6~9개)이 오탐인지 양발이 함께 찍힌 건지 구분 못 함.
2. **범주 라벨은 여전히 없다.** A안(디자인 분류)은 AI-Hub 04 메타데이터(572267/572268) 확보 전까지 막혀 있다.
3. **라이선스는 CC BY 4.0** — 상업 이용 가능하나 **출처표기 의무**. 서비스에 넣으면 크레딧 표기가 필요하다.
4. 데이터가 손톱 편중이라 발톱 파인튜닝용으로 쓰면 도메인 갭이 있다.

## 6. 재현 명령

```bash
cd BeautyAI_project
python scripts/fetch_nail_reference_data.py                      # 모델 + 데이터셋 취득
python scripts/detect_nail_regions.py --json-out out.json        # 보유 발 이미지 전체 평가
python scripts/detect_nail_regions.py \
    --source "data/04.네일 및 페디큐어 데이터/.../VS_디자인데이터_발.zip" \
    --conf 0.4 --crop-dir data/nail_crops/foot_val                # 크롭 생성
```

의존성: `ultralytics`(신규, backend venv에 설치됨 — numpy/torch 변경 없음).
앱에 태우려면 `backend/requirements.txt` 에도 추가해야 한다.

## 7. 다음 단계 제안

> **1번은 같은 날 완료됨** → [nail_retrieval_mvp_20260728.md](nail_retrieval_mvp_20260728.md)
> (인덱스 6,340개, 랜덤 대비 색차 75.2% 개선, color hit@5 96%)

1. ~~**B안 MVP 착수** — 크롭 임베딩 인덱스(사전학습 CNN) + 최근접 검색. 학습 불필요.~~ ✅
2. **팔레트 추출 브리지** — 크롭에서 대표색 추출 → 기존 퍼스널컬러 `nail` 컬럼([pc-item-match-pipeline])과 연결하면 "내 사진 속 디자인 → 비슷한 색 상품" 이 바로 된다.
3. `POST /api/analyze-nail-design` + 홈 카드 활성화(설계문서 §4·§5).
4. AI-Hub 04 메타데이터가 확보되면 A안 분류로 승격.

---

### 출처표기 (CC BY 4.0)
- Model: mnemic, *nails_seg_yolov8*, HuggingFace — https://huggingface.co/mnemic/nails_seg_yolov8
- Data: Personal Projects, *nails_segmentation*, Roboflow Universe — https://universe.roboflow.com/personal-projects-jfbag/nails_segmentation
