"""Virtual aesthetic recommendation and subtle preview simulation.

This module is intentionally non-medical. It produces a conservative beauty
planning preview from face landmarks: light face-frame reshaping, mild nose
highlighting, and blemish-softening candidates.
"""

from __future__ import annotations

import base64
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.services.face_shape_analyzer import analyze as analyze_face_shape

# 워프 상한(얼굴 폭을 최대 몇 %까지 줄이나). 슬라이더를 끝까지 밀었을 때의 값이다.
#
# 7.5% 였는데 **원본과 나란히 놓고 봐야 겨우 알아챌 수준**이라, 사용자가 "게이지가 안 먹는다"고
# 느꼈다(실측 비교, 2026-08-03). 카드별 미리보기를 붙이면 카드 4장이 서로 구분되지 않는다.
# 같은 사진에 7.5 / 12 / 18% 를 돌려 눈으로 비교한 결과:
#   7.5% — 차이를 못 느낀다
#   12%  — 하관 변화가 보이면서 **같은 사람으로 남는다**  ← 채택
#   18%  — 원본에 없던 갸름함이 생겨 '필터' 로 넘어간다(주석의 identity-changing 경계)
_MAX_FACE_NARROWING = 0.12

# 정면에서 벗어난 사진은 워프를 줄인다. 축소가 얼굴 중심선 기준 좌우 대칭이라,
# 각도가 있으면 한쪽만 눌려 왜곡이 커진다 — 상한을 올릴수록 이 문제도 같이 커진다.
_FRONTAL_FULL = 0.12   # 이보다 정면이면 강도 그대로
_FRONTAL_NONE = 0.30   # 이보다 틀어지면 워프하지 않는다(추천·분석은 그대로 제공)

# ── 법적 고지 ──────────────────────────────────────────────────────────────────
# **모듈 상수로 둔다.** 반환 딕셔너리 안에 인라인으로 두었더니, 문장을 늘리면서
# 여러 줄 문자열이 되자 소스를 정규식으로 훑던 번역 검사가 조용히 이 문자열을 놓쳤다
# (검사 29건 → 28건). 상수면 테스트가 실제 값을 그대로 읽을 수 있다.
#
# 문장 셋의 역할이 각각 다르므로 줄이지 말 것(docs/medical_ad_working_assumptions.md 전제 3):
#   1) 비의료·참고용      — 무엇인지
#   2) 결과 미보장·개인차  — 효과를 단정하지 않음
#   3) 의료기관 아님       — 주체가 누구인지
#
# ⚠ 고치면 frontend/src/i18n.ts 의 키도 같이 고쳐야 한다. 안 고치면 일본어 모드에서
#   한국어 고지가 그대로 나간다(한국·일본 모두 규제 대상).
DISCLAIMER_SHORT = "비의료 참고용 가상 미용 시뮬레이션입니다."
DISCLAIMER_FULL = (
    "비의료 참고용 가상 미용 시뮬레이션입니다. 실제 시술 여부는 전문 의료진 상담이 필요합니다. "
    "실제 결과는 개인에 따라 다르며, 이 이미지는 결과를 보장하지 않습니다. "
    "이 서비스는 의료기관이 아니며 진단·치료·시술을 제공하지 않습니다."
)

FACE_OVAL = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
]
NOSE_LINE = [6, 197, 195, 5, 4, 1, 19, 94, 2]

# 잡티 후보에서 **빼야 하는** 영역: 눈·눈썹·입술.
#
# 왜 필요한가(2026-08-04 실측): 잡티 탐지는 '주변보다 어두운 국소 영역'을 찾는데,
# 눈썹·쌍꺼풀선·속눈썹·입술선·콧구멍이 전부 그 조건을 만족한다. 변화량을 6배 증폭해
# 히트맵을 떠 보니 **건드리는 곳이 잡티가 아니라 전부 이목구비였다.**
# 지금은 효과가 약해(평균 픽셀차 0.02) 티가 안 났을 뿐, 강도를 올리면 눈썹이 지워진다.
LEFT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
RIGHT_EYE = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]
LEFT_BROW = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
RIGHT_BROW = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]
LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
# 콧구멍 주변. 그림자가 깊어 잡티로 잡힌다.
NOSTRILS = [1, 2, 98, 97, 326, 327, 94, 19]

_FEATURE_REGIONS = (LEFT_EYE, RIGHT_EYE, LEFT_BROW, RIGHT_BROW, LIPS, NOSTRILS)


def _feature_exclusion_mask(landmarks, w: int, h: int) -> np.ndarray:
    """이목구비 영역 마스크(255=제외). 잡티 후보에서 뺀다.

    각 영역을 볼록껍질로 채운 뒤 넉넉히 부풀린다 — 속눈썹·눈썹 끝처럼 랜드마크 바깥으로
    삐져나오는 부분까지 덮어야 한다.
    """
    mask = np.zeros((h, w), dtype=np.uint8)
    for indices in _FEATURE_REGIONS:
        points = _points(landmarks, indices, w, h)
        if len(points) >= 3:
            cv2.fillConvexPoly(mask, cv2.convexHull(points), 255)
    # 얼굴 폭에 비례해 부풀린다(사진 해상도가 달라도 같은 비율로 덮이게).
    grow = max(5, int(w * 0.018))
    return cv2.dilate(mask, np.ones((grow, grow), np.uint8))


def _load_rgb(image_bytes: bytes, max_size: int = 1000) -> np.ndarray:
    image = Image.open(BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((max_size, max_size))
    return np.ascontiguousarray(np.asarray(image, dtype=np.uint8))


def _to_data_url(rgb_uint8: np.ndarray) -> str:
    buf = BytesIO()
    Image.fromarray(rgb_uint8).save(buf, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _points(landmarks, indices: list[int], w: int, h: int) -> np.ndarray:
    return np.array([(int(landmarks[i].x * w), int(landmarks[i].y * h)) for i in indices], dtype=np.int32)


def _soft_mask(shape: tuple[int, int], points: np.ndarray, blur: int) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(points), 255)
    blur = max(1, blur)
    return cv2.GaussianBlur(mask, (blur * 2 + 1, blur * 2 + 1), 0).astype(np.float32) / 255.0


def _face_bounds(points: np.ndarray, w: int, h: int) -> tuple[int, int, int, int]:
    """얼굴 경계 상자. **파이썬 int 로 변환해서** 반환한다.

    `points.min(axis=0)` 은 numpy 정수를 주고, 그 값으로 계산한 결과도 numpy 정수로 남는다.
    그대로 응답 metrics 에 실으면 FastAPI 직렬화가 터진다
    (`PydanticSerializationError: Unable to serialize unknown type: numpy.int64`).
    브라우저에는 CORS 오류로 보여서(에러 응답엔 CORS 헤더가 안 붙는다) 원인을 찾기 어렵다 —
    실측으로 가상 성형 분석이 통째로 실패하고 있었다.
    """
    x1, y1 = points.min(axis=0)
    x2, y2 = points.max(axis=0)
    pad_x = int((x2 - x1) * 0.12)
    pad_y = int((y2 - y1) * 0.08)
    return (
        int(max(0, x1 - pad_x)),
        int(max(0, y1 - pad_y)),
        int(min(w, x2 + pad_x)),
        int(min(h, y2 + pad_y)),
    )


def _reshape_face(
    rgb: np.ndarray,
    face_mask: np.ndarray,
    face_pts: np.ndarray,
    strength: float,
    jaw_focus: float = 0.5,
) -> np.ndarray:
    """Subtle horizontal remap inside the face oval.

    The effect is deliberately capped so the preview stays in "planning" territory,
    not identity-changing retouching.

    strength  = 얼마나 줄일지, jaw_focus = **어디를** 줄일지(0=중안부 쪽, 1=턱끝 쪽).
    ⚠ 예전엔 face_line 과 jaw_balance 를 **더해서** 강도 하나로만 썼다. 그래서 슬라이더가
      2개인데 자유도는 1개였고, 합이 같은 프리셋은 결과가 완전히 같았다(실측: '부드러운
      동안형' vs '입체 세련형' 픽셀차 0.02 — 카드가 달라도 그림이 같았다).
      두 값을 분리해야 카드 4장이 서로 구분된다.
    """
    if strength <= 0:
        return rgb
    h, w = rgb.shape[:2]
    xs = face_pts[:, 0].astype(np.float32)
    ys = face_pts[:, 1].astype(np.float32)
    cx = float(xs.mean())
    y_top, y_bottom = float(ys.min()), float(ys.max())
    yy, xx = np.indices((h, w), dtype=np.float32)
    vertical = np.clip((yy - y_top) / max(1.0, y_bottom - y_top), 0.0, 1.0)
    # jaw_focus 가 높을수록 축소가 아래(턱)로 내려가고 좁게 모인다 → 'V라인'.
    # 낮으면 중안부까지 완만하게 퍼진다 → '계란형/동안형'.
    focus = float(np.clip(jaw_focus, 0.0, 1.0))
    center = 0.55 + 0.25 * focus
    spread = 0.20 - 0.11 * focus
    lower_face_weight = np.exp(-((vertical - center) ** 2) / max(0.04, spread))
    cap = _MAX_FACE_NARROWING
    scale = 1.0 - min(cap, strength * cap) * lower_face_weight * face_mask
    # 하한은 상한에 맞춰 따라간다. 예전엔 0.86 고정이라 상한을 올려도 여기서 잘려나갔다.
    map_x = cx + (xx - cx) / np.clip(scale, 1.0 - cap - 0.02, 1.0)
    map_y = yy
    warped = cv2.remap(rgb, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    alpha = np.clip(face_mask[..., None] * 0.86, 0.0, 1.0)
    return np.clip(rgb * (1 - alpha) + warped * alpha, 0, 255).astype(np.uint8)


def find_blemish_candidates(
    rgb: np.ndarray,
    face_mask: np.ndarray,
    landmarks=None,
) -> list[dict]:
    """점·잡티 **후보 위치**를 찾는다. 지우지는 않는다.

    왜 자동으로 안 지우나(2026-08-04 결정): 자동 제거는 오탐/미탐 줄다리기가 끝나지 않는다.
    실측에서 후보 45개 중 대부분이 눈썹·쌍꺼풀선·입술선이었고(이목구비 제외로 13개까지
    줄였지만 여전히 헤어라인이 섞인다), 정작 뚜렷한 주근깨는 못 잡았다.
    설계안이 말한 대로 **후보만 보여주고 지울지는 사용자가 고른다** — 오탐이 나와도
    사용자가 안 고르면 그만이라, 정밀도 요구가 훨씬 낮아진다.

    좌표는 **0~1 정규화**로 돌려준다. 프론트가 이미지를 어떤 크기로 그리든 그대로 얹을 수 있게.
    """
    h, w = rgb.shape[:2]
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    lightness = lab[:, :, 0].astype(np.float32)
    local = cv2.GaussianBlur(lightness, (31, 31), 0)
    dark_delta = np.clip(local - lightness, 0, 255)

    usable = face_mask > 0.55
    if landmarks is not None:
        # 이목구비(눈·눈썹·입술·콧구멍)를 뺀다. 안 빼면 후보의 70% 가 여기서 나온다.
        usable &= _feature_exclusion_mask(landmarks, w, h) == 0

    candidate = ((dark_delta > 13) & usable).astype(np.uint8) * 255
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    num, _labels, stats, centroids = cv2.connectedComponentsWithStats(candidate, 8)
    found: list[dict] = []
    for idx in range(1, num):
        area = int(stats[idx, cv2.CC_STAT_AREA])
        if not (5 <= area <= 170):
            continue
        bw = int(stats[idx, cv2.CC_STAT_WIDTH])
        bh = int(stats[idx, cv2.CC_STAT_HEIGHT])
        # 잡티는 둥글다. 눈썹·헤어라인 조각처럼 **길쭉한 것**은 뺀다.
        if max(bw, bh) > 3 * max(1, min(bw, bh)):
            continue
        cx, cy = centroids[idx]
        found.append({
            "x": round(float(cx) / w, 4),
            "y": round(float(cy) / h, 4),
            "r": round(max(bw, bh) / 2.0 / w, 4),
        })

    # 큰 것부터 남긴다(눈에 띄는 순).
    found.sort(key=lambda c: c["r"], reverse=True)

    # ⚠ **최소 간격을 강제한다.** 화면의 점 마커는 크기가 고정(22~30px)이라, 후보 둘이
    #   가까우면 마커가 겹쳐 **뒤에 있는 점을 누를 수 없다**(브라우저 검증에서
    #   'intercepts pointer events' 로 드러났다 — 테스트만의 문제가 아니라 사용자도 못 누른다).
    #   0.04 = 이미지 폭의 4%. 표시 폭 ~450px 기준 약 18px 로, 마커가 겹치지 않는 최소값이다.
    #   가까운 둘 중에서는 **큰 쪽**이 남는다(위에서 정렬해 뒀다).
    min_gap = 0.04
    spaced: list[dict] = []
    for point in found:
        if all(
            (point["x"] - kept["x"]) ** 2 + (point["y"] - kept["y"]) ** 2 >= min_gap ** 2
            for kept in spaced
        ):
            spaced.append(point)
        if len(spaced) >= 20:
            break
    return spaced


def remove_blemishes(rgb: np.ndarray, points: list[dict], strength: float = 0.9) -> np.ndarray:
    """사용자가 고른 지점만 지운다. 좌표는 0~1 정규화."""
    if not points or strength <= 0:
        return rgb
    h, w = rgb.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for point in points:
        x = int(float(point.get("x", 0)) * w)
        y = int(float(point.get("y", 0)) * h)
        # 반지름이 없거나 너무 작으면 최소 크기를 준다 — 점만 찍으면 티가 안 지워진다.
        r = max(3, int(float(point.get("r", 0)) * w) + 2)
        cv2.circle(mask, (x, y), r, 255, -1)

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    repaired = cv2.inpaint(bgr, mask, 3, cv2.INPAINT_TELEA)
    alpha = (cv2.GaussianBlur(mask, (13, 13), 0).astype(np.float32) / 255.0) * min(0.95, strength)
    out = bgr * (1 - alpha[..., None]) + repaired * alpha[..., None]
    return cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)


def _add_contour_guides(rgb: np.ndarray, landmarks, w: int, h: int, nose_strength: float) -> np.ndarray:
    """콧대에 하이라이트를 얹는다.

    ⚠ 예전에는 흰 선(polylines)과 점(circle)을 **그렸다.** 결과물을 보니 하이라이터가 아니라
    **코에 그어놓은 낙서**로 보였다(실측 2026-08-04). 사용자는 '왜 선이 그어졌지'로 받아들인다.
    지금은 콧대를 따라 만든 마스크를 크게 블러해 **밝기만 더한다** — 실제 하이라이터에 가깝다.

    밝기는 Lab 의 L 채널에만 더한다. BGR 에 흰색을 섞으면 채도가 빠져 회색빛이 돈다.
    """
    if nose_strength <= 0:
        return rgb

    nose = _points(landmarks, NOSE_LINE, w, h)
    band = np.zeros((h, w), dtype=np.uint8)
    # 콧대 폭에 맞춘 굵기. 얼굴 크기에 비례해야 사진 해상도가 달라도 같게 보인다.
    thickness = max(3, int(w * 0.030))
    cv2.polylines(band, [nose], False, 255, thickness, cv2.LINE_AA)
    # 큰 블러가 핵심이다. 경계가 남으면 다시 '그린 것'처럼 보인다.
    blur = max(3, int(w * 0.05)) | 1
    soft = cv2.GaussianBlur(band, (blur, blur), 0).astype(np.float32) / 255.0

    lab = cv2.cvtColor(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), cv2.COLOR_BGR2LAB).astype(np.float32)
    # 최대 +14 L. 그 이상은 콧대가 하얗게 떠서 합성 티가 난다(눈으로 비교해 정한 값).
    lab[:, :, 0] = np.clip(lab[:, :, 0] + soft * (14.0 * nose_strength), 0, 255)
    bgr = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


# 사용자가 1단계에서 고르는 '개선하고 싶은 부위' → 추천 카테고리(복수 가능).
# 화면 문구를 그대로 키로 쓴다(i18n 과 같은 방식) — 사전에 없는 값이 와도 무시될 뿐 안 깨진다.
#
# ⚠ 값이 **집합**인 이유: `_recommendations` 는 얼굴 지표에 따라 `nose_contour` 와 `balance`
#   중 **하나만** 만든다(eye_ratio 분기). '코 라인'을 골랐는데 그 사진이 balance 쪽으로
#   판정되면 매칭이 통째로 실패해, 고른 게 무시된 것처럼 보였다(실측). balance 추천 문구도
#   "코 라인 하이라이트와 눈앞머리 음영"이라 실제로 코를 다룬다 — 둘 다 걸어주는 게 맞다.
_CONCERN_TO_CATEGORIES = {
    "윤곽·얼굴형": {"face_frame"},
    "턱끝·하관": {"face_frame"},
    "광대·볼 폭": {"face_frame"},
    "코 라인": {"nose_contour", "balance"},
    "중안부 비율": {"balance", "nose_contour"},
    "점·잡티 제거": {"blemish"},
}


def _prioritize(recs: list[dict], concerns: list[str] | None) -> list[dict]:
    """사용자가 고른 부위를 위로 올린다(1순위가 가장 위).

    ⚠ 점수를 조작하지 않고 **정렬만** 바꾼다. 점수는 '사진에서 그렇게 보인다'는 측정값이라,
    사용자가 골랐다고 올리면 근거가 무너진다(설계안 §10 의 '단정 금지' 와 같은 이유).
    대신 `selected` 플래그를 실어 프론트가 '선택하신 부위' 로 표시할 수 있게 한다.
    """
    if not concerns:
        return recs
    # 1순위(첫 항목)가 가장 앞. 같은 카테고리로 매핑되는 부위가 여럿이면 먼저 고른 쪽이 이긴다.
    order: dict[str, int] = {}
    for rank, concern in enumerate(concerns):
        for category in _CONCERN_TO_CATEGORIES.get(concern, ()):
            if category not in order:
                order[category] = rank
    for rec in recs:
        rec["selected"] = rec.get("category") in order
    return sorted(recs, key=lambda rec: order.get(rec.get("category", ""), len(order) + 1))


def _screen_for_referral(image_bytes: bytes) -> dict:
    """미용 추천 **전에** 질환 소견을 선별한다(설계안 §10 안전장치).

    미용 목적으로 올린 사진이라도 진료가 필요한 소견이 보이면 그쪽을 먼저 알리는 게 맞다.
    자산은 이미 있었다 — `derma_tier1_gate.pt` 는 바디 분석에서만 쓰이고 성형 플로우엔
    연결돼 있지 않았다(설계 검토 2026-08-03).

    ⚠ 추천을 **막지는 않는다**. 이건 진단이 아니라 선별이고, 오탐으로 기능을 잠그면
    사용자가 안내 자체를 무시하게 된다. 정보를 더해 사용자가 판단하게 한다.
    ⚠ Tier1(악성 recall 89%)만 신뢰한다 — Tier2 의 malignant 는 9지선다라 게이트로 쓰면
    과잉 오탐이 난다(dermatology_analyzer 주석과 같은 이유).
    """
    try:
        from app.services.dermatology_analyzer import SCREENING_NOTE, DermatologyAnalyzer

        result = DermatologyAnalyzer().analyze(image_bytes)
    except Exception:
        # 선별 모델이 배포에 없거나 실패해도 성형 기능 자체는 계속 돌아야 한다.
        return {"urgent": False, "label": "", "confidence": 0.0, "message": ""}

    if not result.get("model_available") or not result.get("urgent"):
        return {"urgent": False, "label": "", "confidence": 0.0, "message": ""}
    return {
        "urgent": True,
        "label": str(result.get("tier1_label") or ""),
        "confidence": float(result.get("tier1_confidence") or 0.0),
        "message": "사진에서 진료가 필요할 수 있는 소견이 보입니다. 미용 시술보다 피부과 전문의 진료를 먼저 권합니다. " + SCREENING_NOTE,
    }


def _detect(rgb: np.ndarray):
    """Face Mesh 1회 실행. **가장 비싼 단계**라, 카드 여러 장을 만들 때 이걸 재사용한다."""
    import mediapipe as mp

    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
    ) as mesh:
        return mesh.process(rgb)


def _render(rgb, lm, face_mask, face_pts, tuning: dict, frontal: float) -> np.ndarray:
    """랜드마크가 이미 있을 때 미리보기 한 장을 그린다(카드별 프리셋 렌더에 재사용)."""
    h, w = rgb.shape[:2]
    strength = np.clip(tuning["face_line"] / 100.0, 0.0, 1.0) * frontal
    out = _reshape_face(rgb, face_mask, face_pts, strength, tuning["jaw_balance"] / 100.0)
    # ⚠ 카드 미리보기에서는 잡티를 건드리지 않는다. 카드가 말하는 것은 **얼굴선·코**이고,
    #   잡티 자동 제거는 어차피 눈에 안 보이는 수준이었다(실측 픽셀차 0.005).
    #   지우는 것은 결과 화면에서 사용자가 고른 지점만 한다(2026-08-04 결정).
    return _add_contour_guides(out, lm, w, h, np.clip(tuning["nose_contour"] / 100.0, 0.0, 1.0))


# 개선 방향 카드 = 슬라이더 프리셋. **백엔드가 단일 출처**다 — 예전엔 프론트에만 있어서
# 미리보기를 만들 수 없었고(카드는 일러스트였다), 값이 두 곳에 흩어질 위험도 있었다.
CARD_PRESETS: tuple[dict, ...] = (
    {"id": "oval", "title": "계란형 밸런스",
     "summary": "전체 얼굴선은 유지하면서 턱선과 광대 폭을 부드럽게 정리합니다.",
     "tuning": {"face_line": 44, "jaw_balance": 32, "nose_contour": 28, "blemish_care": 50}},
    {"id": "vline", "title": "V라인 윤곽",
     "summary": "하관과 턱끝 중심으로 갸름한 인상을 강조합니다.",
     "tuning": {"face_line": 68, "jaw_balance": 64, "nose_contour": 32, "blemish_care": 45}},
    # ⚠ 카드끼리 face_line(양)과 jaw_balance(위치)가 **둘 다 비슷하면 그림이 같아진다.**
    #   '동안형'은 넓고 약하게(중안부까지), '세련형'은 코 중심이라 얼굴선은 거의 안 건드린다.
    {"id": "soft", "title": "부드러운 동안형",
     "summary": "각진 인상을 줄이고 볼륨감과 부드러운 얼굴선을 우선합니다.",
     "tuning": {"face_line": 30, "jaw_balance": 15, "nose_contour": 20, "blemish_care": 62}},
    {"id": "defined", "title": "입체 세련형",
     "summary": "코 라인과 중안부 입체감을 살려 또렷한 인상을 만듭니다.",
     "tuning": {"face_line": 18, "jaw_balance": 55, "nose_contour": 85, "blemish_care": 45}},
)

# 변화 강도. 슬라이더의 숫자(%)를 대신한다 — "코 라인 62%" 같은 값이 결과지에 실려 병원에
# 가면 수술 수치처럼 읽히는데, 실제로는 의학적 의미가 없는 워프 강도라 오해만 만든다.
INTENSITY_SCALE = {"natural": 0.6, "balanced": 1.0, "defined": 1.35}


def preview_cards(image_bytes: bytes, intensity: str = "balanced") -> dict:
    """카드별로 '내 얼굴에 적용한' 미리보기를 만든다.

    Face Mesh 는 **1회만** 돌리고 워프만 카드 수만큼 반복한다 — 탐지가 가장 비싼 단계라,
    이렇게 하면 카드 4장이 단일 시뮬레이션과 큰 차이 없는 시간에 나온다.
    """
    rgb = _load_rgb(image_bytes)
    h, w = rgb.shape[:2]
    result = _detect(rgb)
    if not result.multi_face_landmarks:
        return {
            "detected": False,
            "message": NO_FACE_MESSAGE,
            "original_image": _to_data_url(rgb),
            "cards": [],
            # 왜 못 찾았는지를 짚어준다. 이게 없으면 사용자가 같은 사진을 다시 올린다.
            "photo_quality": no_face_quality(rgb),
        }

    lm = result.multi_face_landmarks[0].landmark
    face_pts = _points(lm, FACE_OVAL, w, h)
    face_mask = _soft_mask((h, w), face_pts, max(15, int(w * 0.025)))
    frontal = _frontal_factor(_frontal_offset(lm, w, h))
    scale = INTENSITY_SCALE.get((intensity or "balanced").strip().lower(), 1.0)

    cards = []
    for preset in CARD_PRESETS:
        tuning = {key: min(100, int(value * scale)) for key, value in preset["tuning"].items()}
        cards.append({
            "id": preset["id"],
            "title": preset["title"],
            "summary": preset["summary"],
            "preview_image": _to_data_url(_render(rgb, lm, face_mask, face_pts, tuning, frontal)),
        })

    message = "카드별 미리보기를 만들었습니다."
    if frontal <= 0.0:
        message = "얼굴이 옆으로 돌아가 있어 얼굴선 보정은 적용하지 않았습니다. 정면 사진이면 카드별 차이가 더 잘 보입니다."
    elif frontal < 1.0:
        message = "정면에서 조금 벗어나 있어 얼굴선 보정을 약하게 적용했습니다."
    return {
        "detected": True,
        "message": message,
        "original_image": _to_data_url(rgb),
        "cards": cards,
        # 카드 화면이 사진 업로드 직후에 오므로, 품질 경고를 여기서 보여줘야 사용자가
        # 결과지까지 간 뒤에야 '다시 찍으세요' 를 듣는 일이 없다.
        "photo_quality": assess_photo_quality(rgb, face_pts),
    }


def _frontal_offset(landmarks, w: int, h: int) -> float:
    """정면에서 얼마나 벗어났는지(0=정면). 눈 사이 거리로 정규화한 코끝 좌우 쏠림.

    얼굴이 돌아가면 코끝이 두 눈의 중점에서 한쪽으로 밀린다. 랜드마크 3점이면 되고
    카메라 내부 파라미터가 필요 없어(solvePnP 대비) 사진 한 장 입력에 적합하다.
    """
    eye_l = np.array([landmarks[33].x * w, landmarks[33].y * h], dtype=np.float32)
    eye_r = np.array([landmarks[263].x * w, landmarks[263].y * h], dtype=np.float32)
    nose = np.array([landmarks[1].x * w, landmarks[1].y * h], dtype=np.float32)
    inter_eye = float(np.linalg.norm(eye_r - eye_l))
    if inter_eye <= 1.0:
        return 0.0
    mid = (eye_l + eye_r) / 2.0
    # 눈을 잇는 선 방향으로의 성분만 본다(고개를 갸웃한 roll 에는 영향받지 않게).
    axis = (eye_r - eye_l) / inter_eye
    return float(abs(np.dot(nose - mid, axis)) / inter_eye)


def _frontal_factor(offset: float) -> float:
    """워프 강도에 곱할 계수(1=그대로, 0=워프 안 함)."""
    if offset <= _FRONTAL_FULL:
        return 1.0
    if offset >= _FRONTAL_NONE:
        return 0.0
    return float((_FRONTAL_NONE - offset) / (_FRONTAL_NONE - _FRONTAL_FULL))


# ── 사진 품질 게이트 ────────────────────────────────────────────────────────────
# 문턱은 실측으로 잡았다(2026-08-04, docs/ 실사진 표본 + 인위적 열화본 대조).
# 지어낸 숫자를 쓰면 정상 사진이 막히거나(사용자 이탈) 아무것도 안 걸린다.
#
#   지표                     정상 사진       열화본        문턱
#   흐림(라플라시안 분산)    145~338        2.0          < 40
#   밝기(얼굴 평균)          133~138        40           < 70
#   과노출(>248 픽셀 비율)   0.000          0.767        > 0.15
#   가림(피부중앙값 이탈)    0.086~0.150    0.373~0.651  > 0.28
#   해상도(얼굴 폭 px)       678~836        —            < 250
#
# 해상도 문턱의 근거: 얼굴 폭을 단계적으로 줄이며 눈비율을 재보니 170~190px 에서
# 원본 대비 최대 3.79% 어긋났고, 한 표본은 400px 아래에서 검출 자체가 실패했다.
# `_recommendations` 가 eye>1.15 같은 문턱으로 분기하므로 3% 오차는 추천을 바꾼다.
_QUALITY_BLUR_MIN = 40.0
_QUALITY_DARK_MAX = 70.0
_QUALITY_CLIPPED_MAX = 0.15
_QUALITY_OCCLUSION_MAX = 0.28
_QUALITY_FACE_WIDTH_MIN = 250


def _face_region_stats(rgb: np.ndarray, face_pts: np.ndarray) -> dict[str, float]:
    h, w = rgb.shape[:2]
    # cv2.fillConvexPoly 는 int32 만 받는다. 실사용 경로(_points)는 이미 int32 지만,
    # 이 함수는 밖에서도 부를 수 있으므로 여기서 맞춰 둔다 — dtype 때문에 죽는 건 함정이다.
    face_pts = np.asarray(face_pts, dtype=np.int32)
    x1, y1 = np.maximum(face_pts.min(axis=0).astype(int), 0)
    x2 = min(int(face_pts[:, 0].max()), w - 1)
    y2 = min(int(face_pts[:, 1].max()), h - 1)
    crop = rgb[y1:y2, x1:x2]
    if crop.size == 0 or crop.shape[0] < 5 or crop.shape[1] < 5:
        return {}
    gray = crop @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    # 라플라시안 분산 = 초점 지표. 흐리면 고주파가 사라져 분산이 급락한다(150 → 2).
    lap = (
        gray[:-2, 1:-1] + gray[1:-1, :-2] - 4 * gray[1:-1, 1:-1] + gray[1:-1, 2:] + gray[2:, 1:-1]
    )

    # 가림: 얼굴 오벌 **안쪽**만 본다. 사각 크롭을 쓰면 배경·머리카락이 섞여 오탐이 난다.
    mask = _soft_mask((h, w), face_pts, 0) > 0.5
    inside = rgb[mask].astype(np.float32)
    occlusion = 0.0
    if inside.shape[0] >= 100:
        median = np.median(inside, axis=0)
        # 손·마스크·선글라스는 피부 중앙값에서 채널합 110 이상 벌어진다. 조명 그라데이션은
        # 완만해서 이 비율을 크게 올리지 않는다(정상 사진 실측 최대 0.150).
        occlusion = float((np.abs(inside - median).sum(axis=1) > 110).mean())

    return {
        "blur": float(lap.var()),
        "brightness": float(gray.mean()),
        "clipped": float((gray > 248).mean()),
        "occlusion": occlusion,
        "face_width": float(face_pts[:, 0].max() - face_pts[:, 0].min()),
    }


# 얼굴을 못 찾았을 때 **전체 이미지**로 이유를 짚기 위한 문턱.
# 위의 얼굴영역 문턱과 값이 겹치지만 **별개로 측정한 것**이다(2026-08-04, 표본 5장):
#
#   조건        전체밝기      전체흐림      짧은변
#   원본        130~138      144~338      750
#   밝기0.4     51.7~54.6    25~56        750
#   흐림r8      130~138      1.7~2.0      750
#   축소0.05    130~138      105~291      127
#
# ⚠ 어두우면 흐림 지표도 같이 떨어진다(25~56). 그래서 진단 순서를 해상도→어두움→과노출→흐림
#   으로 두어, 어두운 사진에 '흔들렸다'고 잘못 말하지 않게 한다.
_NOFACE_SHORT_SIDE_MIN = 200


def diagnose_no_face(rgb: np.ndarray) -> str:
    """얼굴을 못 찾은 이유를 추정해 안내 문장 뒤에 붙일 조각을 만든다.

    왜 필요한가: 지금까지는 "얼굴을 찾지 못했습니다"만 나갔다. 사용자는 무엇을 고쳐야
    할지 모른 채 같은 사진을 다시 올린다. 랜드마크가 없어도 밝기·흐림·해상도는 잴 수 있다.

    ⚠ 추정이다. 단정하지 않는 표현을 쓴다 — 정면이 아니거나 얼굴이 없어서일 수도 있다.
    """
    h, w = rgb.shape[:2]
    gray = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    if min(h, w) < _NOFACE_SHORT_SIDE_MIN:
        return "사진 해상도가 낮은 것 같습니다. 더 큰 사진으로 올려 주세요."
    if gray.mean() < _QUALITY_DARK_MAX:
        return "사진이 어두워서 얼굴을 찾지 못했을 수 있습니다. 밝은 곳에서 다시 찍어 주세요."
    if float((gray > 248).mean()) > _QUALITY_CLIPPED_MAX:
        return "빛이 너무 강해 얼굴이 하얗게 날아간 것 같습니다. 직사광선을 피해 주세요."
    lap = gray[:-2, 1:-1] + gray[1:-1, :-2] - 4 * gray[1:-1, 1:-1] + gray[1:-1, 2:] + gray[2:, 1:-1]
    if float(lap.var()) < _QUALITY_BLUR_MIN:
        return "사진이 흔들렸거나 초점이 맞지 않은 것 같습니다. 다시 찍어 주세요."
    return ""


NO_FACE_MESSAGE = "얼굴을 찾지 못했습니다. 정면 얼굴과 밝은 조명의 사진으로 다시 시도해 주세요."

# ── 상담 질문 ──────────────────────────────────────────────────────────────────
# 설계안 §16. **시술을 권하는 것이 아니라 사용자가 물어볼 것을 주는 기능**이다.
# 이 방향이 법적으로도 안전하다 — 우리는 무엇을 하라고 말하지 않고, 사용자가 의료진에게
# 판단에 필요한 것을 묻게 돕는다(docs/medical_ad_working_assumptions.md 전제 1).
#
# 규칙:
#   · 시술명·비용을 쓰지 않는다(법무 회신 전까지 금지 항목).
#   · '해야 한다'가 아니라 '물어보라'로 쓴다. 필요 여부는 의료진이 판단한다.
#   · 되돌릴 수 있는지·부작용·회복기간은 **항상** 넣는다. 사용자가 먼저 떠올리기 어렵고,
#     안 물으면 나중에 문제가 되는 것들이다.
_QUESTIONS_ALWAYS = (
    "제 얼굴 비율에서 이 방향이 자연스러운지, 다른 대안은 없는지 알고 싶습니다.",
    "예상되는 부작용과 회복 기간은 어느 정도인가요?",
    # 비용을 **우리가 표시하는 대신** 사용자가 묻게 한다(2026-08-04 결정).
    #   · 우리에겐 쓸 수 있는 가격 데이터가 없다. 심평원 공개 API 는 인증키가 필요하고
    #     미용 성형이 공개 항목에 들어가는지도 확인되지 않았다.
    #   · 가격 표시는 의료광고 판정의 핵심 요소다(medical_ad_working_assumptions.md).
    #     묻게 하면 사용자는 필요한 정보를 얻고, 우리는 광고 주체가 되지 않는다.
    #   · '추가 비용'을 같이 묻게 한 이유: 마취·검사·재수술이 따로 청구되는 경우가 흔한데
    #     총액만 물으면 나중에 알게 된다.
    "총 비용이 얼마인가요? 마취·검사·재수술처럼 따로 청구되는 항목이 있나요?",
    "결과가 마음에 들지 않으면 되돌릴 수 있나요? 되돌린다면 어떤 방법인가요?",
    "상담해 주시는 분과 실제로 시술하시는 분이 같은가요?",
)

_QUESTIONS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "face_frame": (
        "제 골격 상태에서 비수술적인 방법으로 가능한 범위는 어디까지인가요?",
        "얼굴선을 바꾸면 표정이나 씹는 기능에 영향이 있나요?",
    ),
    "nose_contour": (
        "메이크업이나 음영만으로도 차이가 나던데, 지금 상태에서 다른 방법이 필요한가요?",
        "시간이 지나면 모양이 변할 수 있나요?",
    ),
    "balance": (
        "좌우 차이는 누구나 있다고 들었는데, 제 정도는 어느 수준인가요?",
    ),
    "blemish": (
        "제거한 자리에 색소침착이나 흉터가 남을 가능성은 어느 정도인가요?",
        "한 번에 끝나나요, 여러 번 받아야 하나요?",
    ),
}

_QUESTION_IF_REFERRAL = (
    "사진 분석에서 진료가 필요할 수 있다는 안내를 받았습니다. 이 부분을 먼저 봐 주실 수 있나요?"
)


def consultation_questions(
    concerns: list[str] | None,
    recommendations: list[dict] | None = None,
    referral_urgent: bool = False,
) -> list[str]:
    """상담에서 물어볼 질문 목록. 고른 부위와 추천 카테고리에 맞춰 고른다.

    ⚠ 순서가 의미를 갖는다. 진료 안내가 있으면 **그것부터** 묻게 한다 —
    미용 상담이 진료보다 앞서면 안 된다.
    """
    questions: list[str] = []
    if referral_urgent:
        questions.append(_QUESTION_IF_REFERRAL)

    categories: list[str] = []
    for concern in concerns or []:
        for category in _CONCERN_TO_CATEGORIES.get(concern, ()):
            if category not in categories:
                categories.append(category)
    # 고른 부위가 없으면 분석이 짚은 쪽을 쓴다(사용자가 1단계를 건너뛴 경우).
    if not categories:
        for rec in recommendations or []:
            category = rec.get("category")
            if category and category not in categories:
                categories.append(category)

    for category in categories:
        for question in _QUESTIONS_BY_CATEGORY.get(category, ()):
            if question not in questions:
                questions.append(question)

    questions.extend(q for q in _QUESTIONS_ALWAYS if q not in questions)
    return questions


def no_face_quality(rgb: np.ndarray) -> dict:
    """얼굴 미검출 시의 photo_quality. 짚을 수 있는 이유를 issue 하나로 담는다.

    ⚠ 안내 문장에 **이어붙이지 않는다.** 이어붙이면 번역 키가 '기본문 + 이유' 조합만큼
    늘어나고(현재 5가지), 이유를 하나 추가할 때마다 조합이 또 늘어난다.
    분리해 두면 기본문과 이유가 각자 한 번씩만 번역되면 된다.
    """
    reason = diagnose_no_face(rgb)
    return {
        "ok": not reason,
        "issues": [{"code": "no_face_reason", "message": reason}] if reason else [],
        "metrics": {},
    }


def assess_photo_quality(rgb: np.ndarray, face_pts: np.ndarray) -> dict:
    """사진 품질을 재서 문제를 목록으로 돌려준다.

    ⚠ **막지 않는다.** 사진이 완벽하지 않아도 분석은 제공하고, '정확도가 떨어질 수 있다'를
    알리기만 한다. 게이트가 결과를 안 주면 사용자는 이유를 모른 채 이탈한다 —
    얼굴을 아예 못 찾은 경우만 기존대로 별도 처리한다.
    """
    stats = _face_region_stats(rgb, face_pts)
    if not stats:
        return {"ok": True, "issues": [], "metrics": {}}

    issues: list[dict[str, str]] = []
    if stats["face_width"] < _QUALITY_FACE_WIDTH_MIN:
        issues.append({
            "code": "small_face",
            "message": "얼굴이 작게 나와 비율 측정이 부정확할 수 있습니다. 얼굴이 화면을 채우도록 가까이서 찍어 주세요.",
        })
    if stats["blur"] < _QUALITY_BLUR_MIN:
        issues.append({
            "code": "blurry",
            "message": "사진이 흔들렸거나 초점이 맞지 않습니다. 다시 찍으면 더 정확합니다.",
        })
    if stats["brightness"] < _QUALITY_DARK_MAX:
        issues.append({
            "code": "dark",
            "message": "사진이 어둡습니다. 창가나 밝은 조명 아래에서 찍어 주세요.",
        })
    if stats["clipped"] > _QUALITY_CLIPPED_MAX:
        issues.append({
            "code": "overexposed",
            "message": "빛이 너무 강해 얼굴 일부가 하얗게 날아갔습니다. 직사광선을 피해 주세요.",
        })
    if stats["occlusion"] > _QUALITY_OCCLUSION_MAX:
        issues.append({
            "code": "occluded",
            "message": "얼굴 일부가 가려진 것 같습니다. 머리카락·손·마스크·안경을 치우면 더 정확합니다.",
        })

    return {
        "ok": not issues,
        "issues": issues,
        "metrics": {key: round(value, 3) for key, value in stats.items()},
    }


def _recommendations(face_result: dict, blemish_count: int) -> list[dict]:
    metrics = face_result.get("metrics", {})
    wh = float(metrics.get("width_height", 0.78) or 0.78)
    jaw = float(metrics.get("jaw_cheek", 0.86) or 0.86)
    eye = float(metrics.get("eye_ratio", 1.0) or 1.0)
    recs: list[dict] = []

    if wh >= 0.84 or jaw >= 0.90:
        recs.append({
            "title": "윤곽 균형 추천",
            "category": "face_frame",
            "score": 86,
            "summary": "얼굴 폭과 하관 존재감이 먼저 보이는 편이라, 큰 변화보다 턱선·광대 주변을 5~8%만 정리하는 방향을 추천합니다.",
        })
    else:
        recs.append({
            "title": "자연스러운 얼굴선 유지",
            "category": "face_frame",
            "score": 78,
            "summary": "현재 얼굴 프레임은 균형이 안정적인 편입니다. 과한 축소보다 헤어라인·쉐딩 중심의 가벼운 보정이 어울립니다.",
        })

    if eye > 1.15:
        recs.append({
            "title": "중안부 포인트 보완",
            "category": "balance",
            "score": 74,
            "summary": "눈 사이 간격이 넓게 인식될 수 있어 코 라인 하이라이트와 눈앞머리 음영을 함께 보는 구성이 직관적입니다.",
        })
    else:
        recs.append({
            "title": "입체감 포인트",
            "category": "nose_contour",
            "score": 72,
            "summary": "콧대와 코끝은 작은 하이라이트만으로도 전후 차이가 잘 보입니다. 시술 추천보다 메이크업/필터 비교를 먼저 제안합니다.",
        })

    recs.append({
        # ⚠ 여기서 모공/주름/색소를 나눠 말하지 않는다. 피부 회귀기(skin_model.TARGETS)는
        #   6채널로 보이지만 실측상 6개를 구분하지 못한다(라벨이 같아 pore≈wrinkle, 출력
        #   채널 상관 0.95+). 서비스는 이미 3그룹 표시로 낮춰 쓰고 있다. 성형 리포트에서만
        #   세분해 말하면 모델이 못 주는 해상도를 약속하는 셈이라, 이 카드는 '사진에서 눈에
        #   띄는 점·잡티' 라는 **이미지 기반 후보**로만 다룬다(설계 검토 §3).
        "title": "점·잡티 제거 후보",
        "category": "blemish",
        "score": min(92, 58 + blemish_count * 6),
        "summary": f"사진에서 자동 후보 {blemish_count}개를 찾았습니다. 사용자가 직접 누른 위치만 제거하는 방식으로 신뢰도를 높일 수 있습니다.",
    })
    return recs


def simulate(
    image_bytes: bytes,
    face_line: int = 42,
    jaw_balance: int = 28,
    nose_contour: int = 34,
    blemish_care: int = 56,
    concerns: list[str] | None = None,
    desired_moods: list[str] | None = None,
) -> dict:
    """concerns/desired_moods 는 1단계에서 사용자가 고른 값이다(1순위가 첫 항목).

    예전엔 이 값들이 프론트 state 에만 있고 백엔드로 오지 않아, **사용자가 '코 라인'을
    골라도 추천이 전혀 달라지지 않았다**(사용자 지적 2026-08-03). 결과지까지 이어지려면
    입력이 여기까지 와야 한다. 다만 점수는 사진 측정값이라 건드리지 않고 **순서와 표시**에만
    반영한다 — 고른 것만으로 근거가 세지면 안 되기 때문이다.
    """
    rgb = _load_rgb(image_bytes)
    original_url = _to_data_url(rgb)
    h, w = rgb.shape[:2]
    result = _detect(rgb)

    if not result.multi_face_landmarks:
        return {
            "detected": False,
            "message": NO_FACE_MESSAGE,
            "original_image": original_url,
            "preview_image": original_url,
            "face_shape": None,
            "recommendations": [],
            "metrics": {},
            "disclaimer": DISCLAIMER_SHORT,
            "photo_quality": no_face_quality(rgb),
        }

    lm = result.multi_face_landmarks[0].landmark
    face_pts = _points(lm, FACE_OVAL, w, h)
    face_mask = _soft_mask((h, w), face_pts, max(15, int(w * 0.025)))

    # 정면 게이트 — 축소는 얼굴 중심선 기준 좌우 대칭이라, 각도가 있으면 한쪽만 눌린다.
    # 상한을 12% 로 올리면서 이 왜곡도 같이 커지므로 강도를 각도에 따라 낮춘다.
    offset = _frontal_offset(lm, w, h)
    frontal = _frontal_factor(offset)

    face_strength = np.clip(face_line / 100.0, 0.0, 1.0) * frontal
    out = _reshape_face(rgb, face_mask, face_pts, face_strength, jaw_balance / 100.0)
    out = _add_contour_guides(out, lm, w, h, np.clip(nose_contour / 100.0, 0.0, 1.0))

    # 잡티는 **자동으로 지우지 않는다.** 후보 위치만 돌려주고, 지울지는 사용자가 고른다
    # (2026-08-04 결정). blemish_care 는 이제 '지우는 강도'가 아니라 후보를 볼지 여부다.
    blemish_points = (
        find_blemish_candidates(rgb, face_mask, lm) if blemish_care > 0 else []
    )
    blemish_count = len(blemish_points)

    # ⚠ 여기서 Face Mesh 가 한 번 더 돈다(이 모듈에서 이미 한 번 돌렸다). 재사용을 시도했다가
    #   되돌렸다 — 측정해 보니 **이득이 작고 부작용이 있었다**:
    #   · 워밍 후 Face Mesh 는 0.17s 로, simulate 전체 0.58s 중 일부일 뿐이다
    #     (예전에 3.7s 로 보였던 건 첫 호출의 모델 로딩 시간이었다).
    #   · 이 모듈은 1000px, 얼굴형 분석기는 900px 로 리사이즈한다. 랜드마크 정밀도가
    #     해상도에 따라 달라져 eye_ratio 가 1.361↔1.404(3%) 로 어긋났다. `_recommendations`
    #     가 eye>1.15 같은 문턱으로 분기하므로, 경계 근처 얼굴에서 추천이 바뀔 수 있다.
    #   해상도를 맞추기 전에는 각자 탐지하는 게 안전하다.
    face_result = analyze_face_shape(image_bytes)
    recommendations = _prioritize(_recommendations(face_result, blemish_count), concerns)
    referral = _screen_for_referral(image_bytes)
    x1, y1, x2, y2 = _face_bounds(face_pts, w, h)

    # 잡티 보정과 코 하이라이트는 각도와 무관하므로 계속 적용된다. 그래서 '분석은 됐지만
    # 얼굴선 보정만 뺐다'는 걸 말해 줘야 사용자가 "왜 안 바뀌지?" 로 돌아가지 않는다.
    message = "얼굴 비율 기반 추천과 자연스러운 미리보기를 생성했습니다."
    if frontal <= 0.0:
        message = "얼굴이 옆으로 돌아가 있어 얼굴선 보정은 적용하지 않았습니다. 정면 사진이면 더 정확합니다."
    elif frontal < 1.0:
        message = "정면에서 조금 벗어나 있어 얼굴선 보정을 약하게 적용했습니다. 정면 사진이면 더 정확합니다."

    return {
        "detected": True,
        "message": message,
        "original_image": original_url,
        "preview_image": _to_data_url(out),
        "face_shape": face_result,
        "recommendations": recommendations,
        "metrics": {
            "face_box": [x1, y1, x2, y2],
            "blemish_candidates": blemish_count,
            "naturalness_score": int(max(52, 94 - face_strength * 22 - (nose_contour / 100.0) * 8)),
            # 사용자가 고른 값을 그대로 돌려준다 — 결과지가 '무엇을 원한다고 했는지'를
            # 다시 프론트 state 에서 끌어오지 않고 응답 하나로 그릴 수 있게(출력·저장 일관성).
            "concerns": list(concerns or []),
            "desired_moods": list(desired_moods or []),
            # 정면도(0=정면). 프론트가 '정면 사진 다시 올리기' 안내를 띄울 근거로 쓴다.
            "frontal_offset": round(offset, 3),
            "frontal_factor": round(frontal, 2),
        },
        "photo_quality": assess_photo_quality(rgb, face_pts),
        "disclaimer": DISCLAIMER_FULL,
        "referral": referral,
        # 상담에서 물어볼 것(설계안 §16). 시술을 권하지 않고 **질문을 준다**.
        "consultation_questions": consultation_questions(
            concerns, recommendations, bool(referral.get("urgent")),
        ),
        # 점·잡티 후보 위치(0~1 정규화). 지우지는 않았다 — 사용자가 고른 것만 지운다.
        "blemish_points": blemish_points,
    }
