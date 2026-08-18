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


def _body_skin_mask(rgb: np.ndarray) -> np.ndarray:
    """바디 사진엔 얼굴 랜드마크가 없다. 살색 범위로 피부를 골라낸다.

    YCrCb 의 Cr/Cb 는 조명(Y)과 비교적 분리돼 있어, 밝기가 달라도 살색 범위가 덜 흔들린다.
    정밀한 분할이 아니라 **어디를 보정할지** 정하는 용도라 이 정도면 충분하다.
    """
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    skin = cv2.inRange(ycrcb, np.array([0, 133, 77], np.uint8), np.array([255, 173, 127], np.uint8))
    k = max(3, int(min(rgb.shape[:2]) * 0.02) | 1)
    skin = cv2.morphologyEx(skin, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, np.ones((k * 2 + 1, k * 2 + 1), np.uint8))
    return cv2.GaussianBlur(skin, (k * 2 + 1, k * 2 + 1), 0).astype(np.float32) / 255.0


def find_body_pigment_candidates(rgb: np.ndarray, skin_mask: np.ndarray) -> list[dict]:
    """바디 사진에서 색소 자국(점·기미·지루각화 등)의 위치를 찾는다.

    얼굴용 find_blemish_candidates 를 그대로 못 쓰는 이유가 두 가지다.

    ① **얼굴 마스크와 랜드마크를 전제**로 한다(윤곽 안쪽으로 깎고 이목구비를 뺀다).
       바디엔 둘 다 없다.
    ② **크기 기준이 얼굴 셀카 기준**이다(면적 5~170px). 바디는 대개 접사라 병변 하나가
       수천 px 를 차지한다 — 그 기준으로는 정작 크고 뚜렷한 것만 걸러낸다.
       그래서 여기서는 면적을 **이미지 대비 비율**로 잡는다.

    좌표는 0~1 정규화(remove_blemishes 규약과 같다). r 은 이미지 **너비** 기준이다.
    """
    full_h, full_w = rgb.shape[:2]
    # 큰 커널 연산이 뒤에 있으므로 작업 해상도를 고정한다(속도 + 결과 일관성).
    scale = 512.0 / max(full_h, full_w)
    if scale < 1.0:
        small = cv2.resize(rgb, (int(full_w * scale), int(full_h * scale)), interpolation=cv2.INTER_AREA)
        small_mask = cv2.resize(skin_mask, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_LINEAR)
    else:
        small, small_mask = rgb, skin_mask
    h, w = small.shape[:2]

    lab = cv2.cvtColor(cv2.cvtColor(small, cv2.COLOR_RGB2BGR), cv2.COLOR_BGR2LAB)
    lightness = lab[:, :, 0].astype(np.float32)

    # 주변보다 얼마나 어두운가 = black-hat(닫힘 − 원본).
    #
    # ⚠ 가우시안 국소평균을 쓰면 안 된다. 커널이 병변보다 크지 않으면 '주변 평균'이 병변
    #   자신에 끌려가 차이가 0 이 된다 — 실측(420px 사진, 지름 50px 점): 커널 51px 에서
    #   delta 0.7, 커널 169px 에서 76.3. 바디는 접사라 병변이 크고 크기를 미리 모르므로
    #   **크기에 덜 휘둘리는** 형태학 연산이 맞다. 닫힘은 구조요소보다 작은 어두운 얼룩을
    #   주변 밝기로 메우므로, 그 차이가 곧 '얼마나 어두운 점인가'가 된다.
    ksize = max(15, int(min(h, w) * 0.30) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    closed = cv2.morphologyEx(lightness, cv2.MORPH_CLOSE, kernel)
    dark_delta = np.clip(closed - lightness, 0, 255)

    # 피부 안쪽만 본다. 테두리를 안 깎으면 옷·배경 경계의 그늘이 색소로 잡힌다.
    margin = max(3, int(min(h, w) * 0.02))
    inner = cv2.erode((small_mask > 0.5).astype(np.uint8) * 255, np.ones((margin, margin), np.uint8))
    usable = inner > 0
    if not usable.any():
        return []

    values = dark_delta[usable]
    if values.size == 0:
        return []
    # 문턱은 사진마다 다르다(조명·피부톤). Otsu 로 잡되 **최소 문턱**을 깔아 둔다 —
    # 깨끗한 피부에서도 Otsu 는 노이즈를 억지로 둘로 가르기 때문이다.
    otsu, _ = cv2.threshold(
        np.clip(dark_delta, 0, 255).astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    threshold = max(10.0, float(otsu))

    candidate = ((dark_delta > threshold) & usable).astype(np.uint8) * 255
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    # 색소는 가장자리가 흐려 조각날 수 있다 — 붙여서 하나로 본다.
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

    total = float(h * w)
    num, labels, stats, centroids = cv2.connectedComponentsWithStats(candidate, 8)
    found: list[dict] = []
    for idx in range(1, num):
        area = int(stats[idx, cv2.CC_STAT_AREA])
        ratio = area / total
        # 너무 작으면 노이즈, 너무 크면 그림자나 조명 얼룩이다(피부의 12% 를 넘는 '점'은 없다).
        if not (0.00004 <= ratio <= 0.12):
            continue
        bw = int(stats[idx, cv2.CC_STAT_WIDTH])
        bh = int(stats[idx, cv2.CC_STAT_HEIGHT])
        # 색소 자국은 대체로 둥글다. 길쭉한 것(주름 그늘·옷 경계·체모)은 뺀다.
        if max(bw, bh) > 3.2 * max(1, min(bw, bh)):
            continue
        # 옅은 얼룩까지 지우면 피부가 밀랍처럼 된다. 실제로 어두운 것만 남긴다.
        if float(dark_delta[labels == idx].mean()) < 12.0:
            continue
        cx, cy = centroids[idx]
        # 반지름은 경계보다 넉넉하게 — 가장자리 색이 남으면 '지운 티'만 나고 색소는 보인다.
        radius = 0.5 * max(bw, bh) * 1.25
        found.append({"x": float(cx / w), "y": float(cy / h), "r": float(radius / w)})

    # 큰 것부터. 화면에서 눈에 띄는 것이 먼저 지워져야 '없앴다'로 읽힌다.
    found.sort(key=lambda p: -p["r"])
    return found[:12]


def _erase_pigment(rgb: np.ndarray, points: list[dict], strength: float) -> np.ndarray:
    """찾은 색소 자국을 주변 살색으로 덮는다.

    remove_blemishes(얼굴용)를 안 쓰는 이유는 **inpaint 반지름이 3 으로 고정**이라서다.
    얼굴 좁쌀엔 맞지만 바디 접사의 큰 병변에는 턱없이 작아, 가운데가 얼룩덜룩하게 남는다.
    여기서는 병변 크기에 맞춰 반지름을 키운다.
    """
    if not points or strength <= 0:
        return rgb
    h, w = rgb.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    largest = 0
    for point in points:
        x = int(float(point.get("x", 0)) * w)
        y = int(float(point.get("y", 0)) * h)
        r = max(4, int(float(point.get("r", 0)) * w) + 2)
        largest = max(largest, r)
        cv2.circle(mask, (x, y), r, 255, -1)

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    repaired = cv2.inpaint(bgr, mask, max(3, min(largest, 24)), cv2.INPAINT_TELEA)

    # ⚠ TELEA 는 구멍 **테두리에서 안쪽으로** 색을 전파한다. 병변이 크면 가운데까지 닿기
    #   전에 힘이 빠져 얼룩덜룩한 심지가 남는다(실측: 지름 66px 병변에서 83.5% 만 제거,
    #   나머지가 중앙에 그대로 보였다). 채운 결과를 병변 크기에 맞춰 한 번 더 뭉개면
    #   그 심지가 사라지고 주변 살색으로 고르게 덮인다.
    if largest >= 10:
        smooth = max(9, (largest // 2) * 2 + 1)
        repaired = cv2.GaussianBlur(repaired, (smooth, smooth), 0)

    # 가장자리는 부드럽게 잇되 **중심은 완전히 덮어야** 한다. 페더가 반지름만큼 크면
    # 중심 알파가 1 에 못 미쳐 원래 색이 비쳐 보인다.
    feather = max(5, (largest // 3) * 2 + 1)
    alpha = (cv2.GaussianBlur(mask, (feather, feather), 0).astype(np.float32) / 255.0)
    alpha = np.clip(alpha * min(1.0, strength), 0.0, 1.0)
    out = bgr * (1 - alpha[..., None]) + repaired * alpha[..., None]
    return cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)


def simulate_skincare(
    image_bytes: bytes,
    scores: dict[str, float] | None = None,
    strength: float = 1.0,
    mode: str = "face",
) -> dict:
    """케어 후 예상 모습을 만든다.

    반환: {applied, before, after, changed(적용한 항목), message}
    얼굴을 못 찾으면 applied=False 로 돌려주고 화면은 이 영역을 감춘다 — 원본을
    '개선 결과'라고 내보내는 것이 제일 나쁘다.
    """
    rgb = _load_rgb(image_bytes)
    h, w = rgb.shape[:2]

    # 바디는 얼굴 랜드마크가 없다. 살색 범위로 피부를 고르고, 잡티 인페인팅은 건너뛴다
    # (후보 탐색이 얼굴 마스크를 전제로 만들어져 있다).
    is_body = mode == "body"
    landmarks = None
    face_mask = None
    if is_body:
        mask = _body_skin_mask(rgb)
        if float(mask.mean()) < 0.02:
            return {
                "applied": False,
                "before": _to_data_url(rgb),
                "after": None,
                "changed": [],
                "message": "피부 영역을 찾지 못해 시뮬레이션을 만들지 못했습니다.",
            }
    else:
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
        face_mask = _face_mask(rgb, landmarks)
        mask = _skin_mask(face_mask, landmarks, w, h)

    s = scores or {}
    # 바디는 6항목 점수가 없다(질환 선별이라 body_conditions 만 온다). 점수가 하나도
    # 안 오면 붉은기·결만 중간 강도로 다듬는다 — 없는 점수를 지어내지 않는다.
    if is_body and not any(float(s.get(k) or 0) > 0 for k in ("redness", "pore", "acne")):
        s = {**s, "redness": 55.0, "pore": 50.0}
    k = float(np.clip(strength, 0.0, 1.0))

    w_red = _weight(s.get("redness")) * k
    w_pig = _weight(s.get("pigmentation")) * k
    w_tex = max(_weight(s.get("pore")), _weight(s.get("acne"))) * k
    w_wri = _weight(s.get("wrinkle")) * k * 0.5   # 주름은 굵은 구조라 약하게
    w_oil = _weight(s.get("oiliness")) * k

    out = rgb.copy()
    changed: list[str] = []

    if is_body:
        # ⚠ 예전엔 이 블록이 `face_mask is not None` 조건 아래에 있어서 **바디에서는 색소
        #   제거가 통째로 실행되지 않았다.** 그래서 바디 결과지의 '케어 후'가 홍조·결만
        #   손댄 거의 같은 사진이었고, 정작 사용자가 신경 쓰는 점·색소는 그대로 남았다
        #   (제보 2026-08-18). 바디에서 눈에 띄는 건 결이 아니라 색소다 — 여기가 본체다.
        #
        # 바디는 pigmentation 점수 자체가 없으므로(질환 선별이라 6항목이 안 온다) 점수로
        # 게이트하지 않고 **검출되면 지운다**. 점수를 지어내는 것보다 정직하다.
        # 강도는 1.0 고정이다. 점수로 깎으면 안 된다 — 바디엔 pigmentation 점수가 아예
        # 안 오므로 w_pig 는 항상 0 이고, 그때 강도 0.85 는 **원본의 15% 를 그대로 비쳐
        # 보이게** 한다(실측: 원본 67 → 결과 170, 깨끗한 피부 187). 그 정도로 남으면
        # '지웠다'가 아니라 '문질렀다'로 보인다. 색소는 지우거나 안 지우거나 둘 중 하나다.
        try:
            points = find_body_pigment_candidates(rgb, mask)
            if points:
                out = _erase_pigment(out, points, strength=1.0)
                changed.append("pigmentation")
        except Exception:
            # 색소 검출이 실패해도 나머지 보정은 계속한다.
            pass
    elif w_pig > 0 and face_mask is not None:
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
