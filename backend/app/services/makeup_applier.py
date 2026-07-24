"""mediapipe Face Mesh 기반 가상 메이크업.

선택한 메이크업 무드의 색상을 모델 사진(test_face)의 입술·볼·눈에 입혀
'무드를 적용한' 결과 이미지를 만든다. 입술/볼/눈 영역은 468(+478) 랜드마크로
정확히 마스킹하고, LAB 색공간에서 a/b(색상)는 타깃으로 이동시키되 L(명도)은
대부분 보존해 음영·질감을 유지한다.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

MODEL_FACE_PATH = Path(__file__).resolve().parents[1] / "assets" / "model_face.png"

# 무드별 메이크업 색상 (입술/볼/아이, RGB hex) — 프론트 STYLE_MOODS 8종과 1:1.
MOOD_MAKEUP: dict[str, dict[str, str]] = {
    "cherry-chocolate": {"lip": "#6E1F2C", "cheek": "#A6505F", "eye": "#5C3B30"},
    "tomato-red": {"lip": "#D83A28", "cheek": "#E07A60", "eye": "#B05A40"},
    "rose-wine": {"lip": "#7A1F3D", "cheek": "#B05A72", "eye": "#6E3A4A"},
    "plum-creme": {"lip": "#7D2E63", "cheek": "#AE789A", "eye": "#6E4A66"},
    "berry-sorbet": {"lip": "#D8466E", "cheek": "#E87AA0", "eye": "#C56A8A"},
    "peach-latte": {"lip": "#E07A60", "cheek": "#F0A98A", "eye": "#D9A48C"},
    "coral": {"lip": "#F2604C", "cheek": "#FF8A73", "eye": "#E08A73"},
    "caramel-mocha": {"lip": "#A86B47", "cheek": "#C0906E", "eye": "#9A6A48"},
}

# 남성용 — 색조를 '약하게' 하는 게 아니라 **항목 자체를 교체**한다(item-match 성별 분기와 동일 원칙).
# 여성: 립·볼·아이 / 남성: 눈썹·립밤. 남성에게 블러셔·아이섀도는 올리지 않는다.
#   lip  = 틴트가 아니라 '립밤 바른 정도'의 자연 톤(채도를 크게 낮춘 뮤트 로즈브라운)
#   brow = 무드의 웜/쿨에 맞춘 눈썹 색(웜무드=웜브라운, 쿨무드=애쉬브라운)
MOOD_MAKEUP_MALE: dict[str, dict[str, str]] = {
    "cherry-chocolate": {"lip": "#8C5A55", "brow": "#4A3328"},
    "tomato-red": {"lip": "#A8635A", "brow": "#5A3A28"},
    "rose-wine": {"lip": "#97605F", "brow": "#4A3A38"},
    "plum-creme": {"lip": "#8E5F63", "brow": "#46383C"},
    "berry-sorbet": {"lip": "#A0635F", "brow": "#4A3A3A"},
    "peach-latte": {"lip": "#AE6F5E", "brow": "#5C4030"},
    "coral": {"lip": "#B26A58", "brow": "#5C4030"},
    "caramel-mocha": {"lip": "#A2705A", "brow": "#55402E"},
}

# mediapipe FaceMesh 랜드마크 인덱스
LIPS_OUTER = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
LIPS_INNER = [78, 95, 88, 178, 87, 14, 317, 402, 318, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191]
LEFT_EYE_UPPER = [33, 246, 161, 160, 159, 158, 157, 173, 133]
RIGHT_EYE_UPPER = [263, 466, 388, 387, 386, 385, 384, 398, 362]
LEFT_CHEEK = 50
RIGHT_CHEEK = 280
# 눈썹 — 각 눈썹의 아래선/윗선. 두 줄을 합쳐 convex hull 로 눈썹 영역을 만든다.
LEFT_BROW = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
RIGHT_BROW = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]
FACE_LEFT = 234
FACE_RIGHT = 454


def _hex_to_bgr(hex_color: str) -> np.ndarray:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return np.array([b, g, r], dtype=np.float32)


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
    return np.array(
        [(int(landmarks[i].x * w), int(landmarks[i].y * h)) for i in indices],
        dtype=np.int32,
    )


def _feather(mask: np.ndarray, blur: int) -> np.ndarray:
    if blur > 0:
        k = blur * 2 + 1
        mask = cv2.GaussianBlur(mask, (k, k), 0)
    return mask.astype(np.float32) / 255.0


def _recolor(img_bgr: np.ndarray, mask: np.ndarray, target_bgr: np.ndarray, strength: float, l_strength: float) -> np.ndarray:
    """mask 영역의 색상(a,b)을 target으로 이동. L은 l_strength 만큼만 이동(음영 보존)."""
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    target = cv2.cvtColor(np.uint8([[target_bgr]]), cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)
    m = mask * strength
    ml = mask * l_strength
    lab[..., 0] = lab[..., 0] * (1 - ml) + target[0] * ml
    lab[..., 1] = lab[..., 1] * (1 - m) + target[1] * m
    lab[..., 2] = lab[..., 2] * (1 - m) + target[2] * m
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def _lip_color_gate(img_bgr: np.ndarray, geom: np.ndarray) -> np.ndarray:
    """기하 입술마스크 안에서 '입술색(붉음, LAB a* 높음)' 픽셀만 남기는 소프트 게이트.

    오므린 입·측면 각도에서 랜드마크 폴리곤이 입술선을 넘어 아랫입술 아래 스킨으로
    번지는 것을 억제한다. 영역 내에서 덜 붉은(=스킨) 하위 픽셀을 부드럽게 깎는다.
    """
    region = geom > 0.05
    if int(region.sum()) < 20:
        return np.ones_like(geom, dtype=np.float32)
    a = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)[:, :, 1].astype(np.float32)  # a 채널: 128 중립, 클수록 붉음
    thr = float(np.percentile(a[region], 30))
    # a>=thr+? → 1(유지), a<<thr → 0(스킨 번짐 제거). 완만한 경사로 자연스럽게.
    return np.clip((a - thr) / 5.0 + 0.6, 0.0, 1.0)


def _brow_hair_gate(img_bgr: np.ndarray, geom: np.ndarray) -> np.ndarray:
    """눈썹 영역 안에서 '눈썹털(어두운) 픽셀'만 남기는 소프트 게이트.

    convex hull 은 눈썹보다 넓게 잡히므로 그대로 칠하면 주변 피부까지 어두워진다.
    영역 내 밝기(L) 하위 픽셀만 남겨 털 위에만 색이 올라가게 한다(입술 게이트와 같은 원리).
    """
    region = geom > 0.05
    if int(region.sum()) < 20:
        return np.ones_like(geom, dtype=np.float32)
    lightness = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)[:, :, 0].astype(np.float32)
    thr = float(np.percentile(lightness[region], 55))
    return np.clip((thr - lightness) / 8.0 + 0.35, 0.0, 1.0)


def _eyeshadow_poly(pts: np.ndarray, lift: int) -> np.ndarray:
    top = pts.copy()
    top[:, 1] = np.clip(top[:, 1] - lift, 0, None)
    return np.vstack([pts, top[::-1]])


def _face_crop(rgb: np.ndarray, landmarks, w: int, h: int) -> np.ndarray:
    """랜드마크 경계로 얼굴 중심 인물 컷을 만든다(이마/턱 여유 포함)."""
    xs = np.array([p.x for p in landmarks], dtype=np.float32) * w
    ys = np.array([p.y for p in landmarks], dtype=np.float32) * h
    x1, x2, y1, y2 = xs.min(), xs.max(), ys.min(), ys.max()
    fw, fh = max(1.0, x2 - x1), max(1.0, y2 - y1)
    cx1 = int(max(0, x1 - fw * 0.35))
    cx2 = int(min(w, x2 + fw * 0.35))
    cy1 = int(max(0, y1 - fh * 0.70))
    cy2 = int(min(h, y2 + fh * 0.30))
    crop = rgb[cy1:cy2, cx1:cx2]
    return crop if crop.size else rgb


def apply_mood(
    image_bytes: bytes,
    mood_id: str,
    max_size: int = 1000,
    crop_face: bool = False,
    gender: str = "female",
) -> dict:
    """사진에 메이크업 무드를 적용한다. gender="male" 이면 눈썹·립밤만 올린다."""
    is_male = (gender or "").strip().lower() == "male"
    rgb = _load_rgb(image_bytes, max_size)
    original_url = _to_data_url(rgb)
    colors = (MOOD_MAKEUP_MALE if is_male else MOOD_MAKEUP).get(mood_id)
    if colors is None:
        return {"applied": False, "message": "지원하지 않는 무드입니다.", "original_image": original_url, "image": original_url}

    h, w = rgb.shape[:2]
    import mediapipe as mp

    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
    ) as mesh:
        result = mesh.process(rgb)

    if not result.multi_face_landmarks:
        return {"applied": False, "message": "사진에서 얼굴을 찾지 못했습니다.", "original_image": original_url, "image": original_url}

    lm = result.multi_face_landmarks[0].landmark
    img_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    face_left = _points(lm, [FACE_LEFT], w, h)[0]
    face_right = _points(lm, [FACE_RIGHT], w, h)[0]
    face_w = max(1.0, float(np.linalg.norm(face_right - face_left)))

    # 입술 — 폴리곤을 살짝 깎고(erode) 입술색 게이트로 스킨 번짐을 막는다(오므린 입/측면 대응).
    lip_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(lip_mask, [_points(lm, LIPS_OUTER, w, h)], 255)
    erode = max(1, int(face_w * 0.010))
    lip_mask = cv2.erode(lip_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode, erode)))
    inner = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(inner, [_points(lm, LIPS_INNER, w, h)], 255)
    lip = np.clip(_feather(lip_mask, 2) - _feather(inner, 1), 0, 1)
    lip = lip * _lip_color_gate(img_bgr, lip)

    if is_male:
        # 남성 — 눈썹 정돈 + 립밤. **블러셔·아이섀도는 올리지 않는다.**
        # 입술은 '바른 티'가 아니라 원래 입술색이 정돈된 정도까지만(강도 0.22).
        img_bgr = _recolor(img_bgr, lip, _hex_to_bgr(colors["lip"]), strength=0.22, l_strength=0.06)
        brow_mask = np.zeros((h, w), dtype=np.uint8)
        for indices in (LEFT_BROW, RIGHT_BROW):
            cv2.fillConvexPoly(brow_mask, cv2.convexHull(_points(lm, indices, w, h)), 255)
        brow = _feather(brow_mask, max(2, int(face_w * 0.008)))
        brow = brow * _brow_hair_gate(img_bgr, brow)
        img_bgr = _recolor(img_bgr, brow, _hex_to_bgr(colors["brow"]), strength=0.45, l_strength=0.30)
        message = "눈썹과 립밤을 적용했습니다."
    else:
        # 입술은 풀립스틱보다 은은한 '틴트'가 자연스러워 강도를 낮춰 기본값으로 둔다.
        img_bgr = _recolor(img_bgr, lip, _hex_to_bgr(colors["lip"]), strength=0.55, l_strength=0.28)

        # 볼 (블러셔) — 소프트 원형 (자연스럽게 은은히)
        cheek_mask = np.zeros((h, w), dtype=np.uint8)
        radius = max(5, int(face_w * 0.10))
        for center in (_points(lm, [LEFT_CHEEK], w, h)[0], _points(lm, [RIGHT_CHEEK], w, h)[0]):
            cv2.circle(cheek_mask, tuple(int(v) for v in center), radius, 255, -1)
        cheek = _feather(cheek_mask, max(10, int(face_w * 0.06)))
        img_bgr = _recolor(img_bgr, cheek, _hex_to_bgr(colors["cheek"]), strength=0.20, l_strength=0.04)

        # 아이섀도 — 윗눈꺼풀 위로 살짝
        lift = max(4, int(face_w * 0.05))
        eye_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(eye_mask, [_eyeshadow_poly(_points(lm, LEFT_EYE_UPPER, w, h), lift)], 255)
        cv2.fillPoly(eye_mask, [_eyeshadow_poly(_points(lm, RIGHT_EYE_UPPER, w, h), lift)], 255)
        eye = _feather(eye_mask, max(3, int(face_w * 0.015)))
        img_bgr = _recolor(img_bgr, eye, _hex_to_bgr(colors["eye"]), strength=0.30, l_strength=0.14)
        message = "메이크업 무드를 적용했습니다."

    applied_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    if crop_face:
        applied_rgb = _face_crop(applied_rgb, lm, w, h)
    return {"applied": True, "message": message, "original_image": original_url, "image": _to_data_url(applied_rgb)}


def apply_mood_to_model(mood_id: str, max_size: int = 1000, crop_face: bool = False) -> dict:
    """번들된 모델 사진에 무드를 적용한다."""
    if not MODEL_FACE_PATH.exists():
        return {"applied": False, "message": "모델 사진이 없습니다.", "original_image": "", "image": ""}
    return apply_mood(MODEL_FACE_PATH.read_bytes(), mood_id, max_size, crop_face)


@lru_cache(maxsize=32)
def model_mood_thumbnail(mood_id: str) -> str:
    """모델에 무드를 적용해 얼굴 중심으로 자른 카드 썸네일(data URL). 결정적이라 캐시한다."""
    result = apply_mood_to_model(mood_id, max_size=720, crop_face=True)
    return result.get("image", "") if result.get("applied") else ""


def all_mood_thumbnails() -> dict[str, str]:
    return {mood_id: model_mood_thumbnail(mood_id) for mood_id in MOOD_MAKEUP}
