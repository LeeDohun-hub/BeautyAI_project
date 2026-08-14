"""피부 개선 시뮬레이션 — 케어를 이어갔을 때의 모습을 미리 보여준다.

가상성형 시뮬레이터의 조각(랜드마크 마스킹·잡티 제거·데이터 URL 변환)을 그대로 재사용한다.
차이는 **무엇을 얼마나 줄이느냐**를 분석 점수에서 가져온다는 점이다 — 걸리지 않은 항목은
건드리지 않는다. 홍조 점수가 낮은 사람의 붉은기까지 빼면 다른 사람 얼굴이 된다.

각 항목이 손대는 것:
  redness      a* 채널(붉은-초록)을 피부 영역에서만 중앙으로 당긴다
  pigmentation 자동 검출한 잡티 후보를 주변 살색으로 덮는다
  pore/acne    엣지를 살리는 블러로 요철만 눌러 준다(윤곽·눈·입은 제외)
  wrinkle      같은 블러를 약하게. 주름은 굵은 구조라 과하게 밀면 얼굴이 뭉갠 것처럼 된다
  oiliness     하이라이트(고휘도)만 살짝 눌러 번들거림을 줄인다

⚠ 눈·눈썹·입은 _feature_exclusion_mask 로 항상 뺀다. 여길 뭉개면 '보정'이 아니라 '다른 사람'이
   된다(가상성형에서 자동 잡티 제거가 눈썹·콧구멍을 잡티로 오인했던 것과 같은 부류).
"""

from __future__ import annotations

import cv2
import numpy as np

from app.services.virtual_surgery_simulator import (
    _detect,
    _feature_exclusion_mask,
    _load_rgb,
    _points,
    _soft_mask,
    _to_data_url,
    find_blemish_candidates,
    remove_blemishes,
)

# 얼굴 윤곽 랜드마크(가상성형과 같은 세트).
FACE_OVAL = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400,
    377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
]

# 점수(0~100)를 이 아래로는 손대지 않는다. 멀쩡한 항목까지 보정하면 얼굴이 바뀐다.
FLOOR = 25.0


def _weight(score: float | None) -> float:
    """점수를 0~1 보정 강도로. FLOOR 이하는 0(손대지 않음)."""
    if score is None:
        return 0.0
    return float(np.clip((float(score) - FLOOR) / (100.0 - FLOOR), 0.0, 1.0))


def _face_mask(rgb: np.ndarray, landmarks) -> np.ndarray:
    """얼굴 윤곽 소프트 마스크(0~1). 이목구비는 아직 살아 있다."""
    h, w = rgb.shape[:2]
    return _soft_mask((h, w), _points(landmarks, FACE_OVAL, w, h), blur=31)


def _skin_mask(face_mask: np.ndarray, landmarks, w: int, h: int) -> np.ndarray:
    """피부만 남긴 0~1 마스크.

    ⚠ _feature_exclusion_mask 는 **255 가 '제외'** 다(잡티 후보에서 빼려고 만든 것).
      그대로 곱하면 눈·눈썹·입만 남는다 — 반대로 뒤집어서 빼야 한다.
    """
    excluded = _feature_exclusion_mask(landmarks, w, h).astype(np.float32) / 255.0
    return np.clip(face_mask * (1.0 - excluded), 0.0, 1.0)


def _reduce_redness(rgb: np.ndarray, mask: np.ndarray, strength: float) -> np.ndarray:
    if strength <= 0:
        return rgb
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    a = lab[:, :, 1]
    # 피부 영역의 a* 중앙값으로 당긴다. 전체 평균을 쓰면 배경 색에 끌려간다.
    weights = mask
    if weights.sum() < 1e-6:
        return rgb
    center = float(np.average(a, weights=weights))
    lab[:, :, 1] = a - (a - center) * (0.55 * strength) * mask
    out = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
    return out


def _smooth_texture(rgb: np.ndarray, mask: np.ndarray, strength: float) -> np.ndarray:
    """엣지를 남기는 블러. 모공·요철만 눌리고 윤곽선은 살아 있다."""
    if strength <= 0:
        return rgb
    d = int(np.clip(5 + strength * 8, 5, 13))
    smooth = cv2.bilateralFilter(rgb, d=d, sigmaColor=45, sigmaSpace=45)
    alpha = (mask * strength)[:, :, None]
    return np.clip(rgb * (1 - alpha) + smooth * alpha, 0, 255).astype(np.uint8)


def _reduce_shine(rgb: np.ndarray, mask: np.ndarray, strength: float) -> np.ndarray:
    """번들거림 = 피부 영역의 고휘도 픽셀. 거기만 밝기를 눌러 준다."""
    if strength <= 0:
        return rgb
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    L = lab[:, :, 0]
    if mask.sum() < 1e-6:
        return rgb
    hi = float(np.percentile(L[mask > 0.35], 88)) if (mask > 0.35).any() else 255.0
    excess = np.clip(L - hi, 0, None)
    lab[:, :, 0] = L - excess * (0.6 * strength) * mask
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)


def simulate_skincare(
    image_bytes: bytes,
    scores: dict[str, float] | None = None,
    strength: float = 1.0,
) -> dict:
    """케어 후 예상 모습을 만든다.

    반환: {applied, before, after, changed(적용한 항목), message}
    얼굴을 못 찾으면 applied=False 로 돌려주고 화면은 이 영역을 감춘다 — 원본을
    '개선 결과'라고 내보내는 것이 제일 나쁘다.
    """
    rgb = _load_rgb(image_bytes)
    result = _detect(rgb)
    if not getattr(result, "multi_face_landmarks", None):
        return {
            "applied": False,
            "before": _to_data_url(rgb),
            "after": None,
            "changed": [],
            "message": "얼굴을 찾지 못해 시뮬레이션을 만들지 못했습니다.",
        }
    landmarks = result.multi_face_landmarks[0].landmark

    h, w = rgb.shape[:2]
    face_mask = _face_mask(rgb, landmarks)
    mask = _skin_mask(face_mask, landmarks, w, h)
    s = scores or {}
    k = float(np.clip(strength, 0.0, 1.0))

    w_red = _weight(s.get("redness")) * k
    w_pig = _weight(s.get("pigmentation")) * k
    w_tex = max(_weight(s.get("pore")), _weight(s.get("acne"))) * k
    w_wri = _weight(s.get("wrinkle")) * k * 0.5   # 주름은 굵은 구조라 약하게
    w_oil = _weight(s.get("oiliness")) * k

    out = rgb.copy()
    changed: list[str] = []

    if w_pig > 0:
        try:
            # 후보 탐색은 윤곽 마스크를 받는다(안쪽으로 깎아 피부만 보는 건 함수가 알아서 한다).
            points = find_blemish_candidates(rgb, face_mask, landmarks) or []
            if points:
                out = remove_blemishes(out, points, strength=float(np.clip(0.55 + 0.4 * w_pig, 0, 1)))
                changed.append("pigmentation")
        except Exception:
            # 잡티 검출은 실패해도 나머지 보정은 계속한다.
            pass

    if w_red > 0:
        out = _reduce_redness(out, mask, w_red)
        changed.append("redness")

    tex = max(w_tex, w_wri)
    if tex > 0:
        out = _smooth_texture(out, mask, tex)
        changed.append("pore" if w_tex >= w_wri else "wrinkle")

    if w_oil > 0:
        out = _reduce_shine(out, mask, w_oil)
        changed.append("oiliness")

    if not changed:
        return {
            "applied": False,
            "before": _to_data_url(rgb),
            "after": None,
            "changed": [],
            "message": "지금도 눈에 띄게 걸리는 항목이 없어 변화를 만들지 않았습니다.",
        }

    # 어디가 바뀌었는지 좌표로 같이 내려준다 — 결과 이미지만으로는 알아보기 어렵다.
    from app.services.change_highlight import change_regions

    return {
        "applied": True,
        "before": _to_data_url(rgb),
        "after": _to_data_url(out),
        "changed": changed,
        "regions": change_regions(rgb, out),
        "message": "",
    }
