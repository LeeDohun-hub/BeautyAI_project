"""mediapipe Face Mesh 기반 얼굴형 분석.

업로드한 정면 사진에서 얼굴 가로/세로·상중하안부·턱선/광대·눈 간격 비율을 실제로
측정해 얼굴형 유형(계란형/둥근형/긴형/각진형/하트형/마름모형)을 판정한다.
하드코딩이 아니라 사람마다 다른 결과가 나온다.
"""

from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image, ImageOps

# 측정용 랜드마크 인덱스 (mediapipe 468)
CHIN = 152
FOREHEAD_TOP = 10
CHEEK_L, CHEEK_R = 234, 454       # 광대(가장 넓은 폭)
JAW_L, JAW_R = 172, 397           # 턱선 폭
TEMPLE_L, TEMPLE_R = 54, 284      # 이마(관자놀이) 폭
BROW_L, BROW_R = 105, 334         # 눈썹 상단
NOSE_BASE = 2                     # 코 아래
EYE_OUT_L, EYE_IN_L = 33, 133     # 왼눈 바깥/안쪽
EYE_IN_R = 362                    # 오른눈 안쪽
LIP_L, LIP_R = 61, 291


def _load_rgb(image_bytes: bytes) -> np.ndarray:
    image = Image.open(BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((900, 900))
    return np.ascontiguousarray(np.asarray(image, dtype=np.uint8))


def _clamp(value: float, lo: float, hi: float) -> int:
    return int(max(lo, min(hi, value)))


def analyze(image_bytes: bytes) -> dict:
    rgb = _load_rgb(image_bytes)
    h, w = rgb.shape[:2]
    import mediapipe as mp

    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=True, min_detection_confidence=0.5
    ) as mesh:
        result = mesh.process(rgb)

    if not result.multi_face_landmarks:
        return {"detected": False, "shape": "", "tags": [], "summary": "사진에서 얼굴을 찾지 못했습니다.", "ratios": [], "blusher_tip": "", "shading_tip": "", "metrics": {}}

    lm = result.multi_face_landmarks[0].landmark

    def pt(i: int) -> np.ndarray:
        return np.array([lm[i].x * w, lm[i].y * h], dtype=np.float32)

    def dist(a: int, b: int) -> float:
        return float(np.linalg.norm(pt(a) - pt(b)))

    face_height = max(1.0, dist(FOREHEAD_TOP, CHIN))
    cheek_width = max(1.0, dist(CHEEK_L, CHEEK_R))
    jaw_width = dist(JAW_L, JAW_R)
    forehead_width = dist(TEMPLE_L, TEMPLE_R)
    eye_width = max(1.0, dist(EYE_OUT_L, EYE_IN_L))
    inter_eye = dist(EYE_IN_L, EYE_IN_R)

    brow_y = (pt(BROW_L)[1] + pt(BROW_R)[1]) / 2
    # 메시 최상단(10)은 실제 헤어라인보다 아래라 '가시 이마'가 짧게 나온다.
    # 헤어라인을 근사하기 위해 상안부를 보정한다.
    upper = max(1.0, (brow_y - pt(FOREHEAD_TOP)[1]) * 1.7)
    mid = max(1.0, pt(NOSE_BASE)[1] - brow_y)
    lower = max(1.0, pt(CHIN)[1] - pt(NOSE_BASE)[1])

    wh = cheek_width / face_height               # 가로/세로
    jaw_cheek = jaw_width / cheek_width           # 턱선/광대
    forehead_cheek = forehead_width / cheek_width  # 이마/광대
    eye_ratio = inter_eye / eye_width             # 눈 사이/눈 크기
    thirds = np.array([1.0, mid / upper, lower / upper])

    # 얼굴형 판정 (휴리스틱)
    if wh < 0.72:
        shape = "긴형"
    elif wh > 0.86:
        shape = "각진형" if (jaw_cheek > 0.86 and forehead_cheek > 0.82) else "둥근형"
    else:
        if forehead_cheek > jaw_cheek + 0.10:
            shape = "하트형"
        elif forehead_cheek < 0.80 and jaw_cheek < 0.82:
            shape = "마름모형"
        elif jaw_cheek > 0.90:
            shape = "각진형"
        else:
            shape = "계란형"

    summaries = {
        "계란형": "이상적인 균형의 계란형이에요. 어떤 메이크업도 잘 어울려요.",
        "둥근형": "볼이 도톰한 둥근형이에요. 음영으로 갸름함을 살리면 또렷해져요.",
        "긴형": "세로가 긴 얼굴형이에요. 가로 포인트로 균형을 잡아 주세요.",
        "각진형": "턱선이 또렷한 각진형이에요. 부드러운 곡선 메이크업이 잘 어울려요.",
        "하트형": "이마가 넓고 턱이 갸름한 하트형이에요. 턱 쪽에 볼륨을 더해 보세요.",
        "마름모형": "광대가 돋보이는 마름모형이에요. 이마·턱을 채워 균형을 맞춰요.",
    }
    blusher_tips = {
        "계란형": "볼 중앙보다 살짝 바깥에 둥글게 올려 자연스러운 생기를 더하세요.",
        "둥근형": "광대뼈를 따라 사선으로 올려 얼굴을 갸름하게 보이게 하세요.",
        "긴형": "볼 중앙에 가로로 넓게 펴 발라 얼굴 길이를 짧아 보이게 하세요.",
        "각진형": "볼 안쪽에 둥글게 올려 각진 인상을 부드럽게 풀어 주세요.",
        "하트형": "볼 아래쪽에 둥글게 올려 시선을 중앙으로 모아 주세요.",
        "마름모형": "광대 앞쪽에 둥글게 올려 돌출된 광대를 부드럽게 정리하세요.",
    }
    shading_tips = {
        "계란형": "턱선 양옆과 광대 외곽에 가볍게 넣어 윤곽만 살짝 정리하세요.",
        "둥근형": "광대 바깥과 볼 옆면에 세로로 넣어 갸름하게 다듬어 주세요.",
        "긴형": "이마 헤어라인과 턱 끝에 넣어 세로 길이를 줄여 주세요.",
        "각진형": "턱 각진 부분에 부드럽게 넣어 곡선을 살려 주세요.",
        "하트형": "넓은 이마 양옆에 넣어 상부 폭을 정돈해 주세요.",
        "마름모형": "광대 바깥쪽에 넣어 가장 넓은 부분을 자연스럽게 줄여 주세요.",
    }

    even = float(thirds.min() / thirds.max())
    ratios = [
        {"label": "상/중/하안부 {0:.1f} : {1:.1f} : {2:.1f}".format(*thirds), "width": _clamp(even * 100, 42, 96)},
        {"label": "눈 사이/눈 크기 {0:.2f}".format(eye_ratio), "width": _clamp(eye_ratio * 62, 35, 96)},
        {"label": "얼굴 가로/세로 {0:.2f}".format(wh), "width": _clamp(wh * 105, 40, 96)},
        {"label": "턱선/광대 대비 {0:.2f}".format(jaw_cheek), "width": _clamp(jaw_cheek * 100, 40, 96)},
    ]

    return {
        "detected": True,
        "shape": shape,
        "tags": [f"#{shape}"],
        "summary": summaries[shape],
        "ratios": ratios,
        "blusher_tip": blusher_tips[shape],
        "shading_tip": shading_tips[shape],
        "metrics": {
            "width_height": round(wh, 3),
            "jaw_cheek": round(jaw_cheek, 3),
            "forehead_cheek": round(forehead_cheek, 3),
            "eye_ratio": round(eye_ratio, 3),
            "thirds": [round(float(t), 2) for t in thirds],
        },
    }
