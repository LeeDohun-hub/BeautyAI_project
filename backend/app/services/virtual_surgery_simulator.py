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

FACE_OVAL = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
]
NOSE_LINE = [6, 197, 195, 5, 4, 1, 19, 94, 2]


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


def _reshape_face(rgb: np.ndarray, face_mask: np.ndarray, face_pts: np.ndarray, strength: float) -> np.ndarray:
    """Subtle horizontal remap inside the face oval.

    The effect is deliberately capped so the preview stays in "planning" territory,
    not identity-changing retouching.
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
    lower_face_weight = np.exp(-((vertical - 0.70) ** 2) / 0.12)
    scale = 1.0 - min(0.075, strength * 0.075) * lower_face_weight * face_mask
    map_x = cx + (xx - cx) / np.clip(scale, 0.86, 1.0)
    map_y = yy
    warped = cv2.remap(rgb, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    alpha = np.clip(face_mask[..., None] * 0.86, 0.0, 1.0)
    return np.clip(rgb * (1 - alpha) + warped * alpha, 0, 255).astype(np.uint8)


def _soften_blemishes(rgb: np.ndarray, face_mask: np.ndarray, strength: float) -> tuple[np.ndarray, int]:
    if strength <= 0:
        return rgb, 0
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    lightness = lab[:, :, 0].astype(np.float32)
    local = cv2.GaussianBlur(lightness, (31, 31), 0)
    dark_delta = np.clip(local - lightness, 0, 255)
    candidate = ((dark_delta > 13) & (face_mask > 0.55)).astype(np.uint8) * 255
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    num, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, 8)
    mask = np.zeros(candidate.shape, dtype=np.uint8)
    count = 0
    for idx in range(1, num):
      area = int(stats[idx, cv2.CC_STAT_AREA])
      if 5 <= area <= 170:
          mask[labels == idx] = 255
          count += 1

    if count == 0:
        return rgb, 0

    radius = 3
    mask = cv2.dilate(mask, np.ones((radius, radius), np.uint8))
    repaired = cv2.inpaint(bgr, mask, 3, cv2.INPAINT_TELEA)
    alpha = (cv2.GaussianBlur(mask, (13, 13), 0).astype(np.float32) / 255.0) * min(0.86, strength)
    out = bgr * (1 - alpha[..., None]) + repaired * alpha[..., None]
    return cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB), count


def _add_contour_guides(rgb: np.ndarray, landmarks, w: int, h: int, nose_strength: float) -> np.ndarray:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    overlay = bgr.copy()
    nose = _points(landmarks, NOSE_LINE, w, h)
    if nose_strength > 0:
        cv2.polylines(overlay, [nose], False, (246, 248, 255), max(1, int(w * 0.004)), cv2.LINE_AA)
        for p in nose[2:7:2]:
            cv2.circle(overlay, tuple(int(v) for v in p), max(2, int(w * 0.007)), (238, 226, 214), -1, cv2.LINE_AA)
    alpha = min(0.22, 0.08 + nose_strength * 0.16)
    out = cv2.addWeighted(overlay, alpha, bgr, 1 - alpha, 0)
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


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
) -> dict:
    rgb = _load_rgb(image_bytes)
    original_url = _to_data_url(rgb)
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
        return {
            "detected": False,
            "message": "얼굴을 찾지 못했습니다. 정면 얼굴과 밝은 조명의 사진으로 다시 시도해 주세요.",
            "original_image": original_url,
            "preview_image": original_url,
            "face_shape": None,
            "recommendations": [],
            "metrics": {},
            "disclaimer": "비의료 참고용 가상 미용 시뮬레이션입니다.",
        }

    lm = result.multi_face_landmarks[0].landmark
    face_pts = _points(lm, FACE_OVAL, w, h)
    face_mask = _soft_mask((h, w), face_pts, max(15, int(w * 0.025)))

    face_strength = np.clip((face_line + jaw_balance) / 200.0, 0.0, 1.0)
    out = _reshape_face(rgb, face_mask, face_pts, face_strength)
    out, blemish_count = _soften_blemishes(out, face_mask, np.clip(blemish_care / 100.0, 0.0, 1.0))
    out = _add_contour_guides(out, lm, w, h, np.clip(nose_contour / 100.0, 0.0, 1.0))

    face_result = analyze_face_shape(image_bytes)
    recommendations = _recommendations(face_result, blemish_count)
    x1, y1, x2, y2 = _face_bounds(face_pts, w, h)

    return {
        "detected": True,
        "message": "얼굴 비율 기반 추천과 자연스러운 미리보기를 생성했습니다.",
        "original_image": original_url,
        "preview_image": _to_data_url(out),
        "face_shape": face_result,
        "recommendations": recommendations,
        "metrics": {
            "face_box": [x1, y1, x2, y2],
            "blemish_candidates": blemish_count,
            "naturalness_score": int(max(52, 94 - face_strength * 22 - (nose_contour / 100.0) * 8)),
        },
        "disclaimer": "비의료 참고용 가상 미용 시뮬레이션입니다. 실제 시술 여부는 전문 의료진 상담이 필요합니다.",
    }
