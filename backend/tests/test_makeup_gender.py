"""가상 메이크업의 성별 분기 회귀 테스트.

핵심 계약: 남성은 색조를 '약하게' 하는 게 아니라 **항목이 다르다**(item-match 성별 분기와 동일 원칙).
  여성 = 립·볼·아이 / 남성 = 눈썹·립밤. **남성에게 블러셔·아이섀도가 올라가면 안 된다.**

⚠️ 변화량의 기준선은 0 이 아니다 — `_recolor` 가 LAB 8bit 왕복을 하므로 손대지 않은 픽셀도
   평균 ~1.2 흔들린다. 그래서 '건드리지 않는 배경'을 기준선으로 잡고 그 대비로 판정한다.
"""
import base64
import io

import cv2
import numpy as np
import pytest
from PIL import Image

from app.services.makeup_applier import (
    FACE_LEFT,
    FACE_RIGHT,
    LEFT_BROW,
    LEFT_CHEEK,
    LEFT_EYE_UPPER,
    MODEL_FACE_PATH,
    MOOD_MAKEUP,
    MOOD_MAKEUP_MALE,
    RIGHT_BROW,
    RIGHT_CHEEK,
    RIGHT_EYE_UPPER,
    _eyeshadow_poly,
    _points,
    apply_mood,
)


def _decode(data_url: str) -> np.ndarray:
    raw = base64.b64decode(data_url.split(",", 1)[1])
    return np.asarray(Image.open(io.BytesIO(raw)).convert("RGB")).astype(np.float32)


def test_male_palette_covers_same_moods() -> None:
    # 프론트가 무드 8종을 성별과 무관하게 보여주므로 두 팔레트의 키가 같아야 한다.
    assert set(MOOD_MAKEUP_MALE) == set(MOOD_MAKEUP)
    for colors in MOOD_MAKEUP_MALE.values():
        assert set(colors) == {"lip", "brow"}      # 남성 팔레트에 cheek/eye 가 있으면 안 된다


@pytest.mark.skipif(not MODEL_FACE_PATH.exists(), reason="번들 모델 사진 없음")
def test_unknown_mood_is_rejected_for_both_genders() -> None:
    raw = MODEL_FACE_PATH.read_bytes()
    for gender in ("female", "male"):
        assert apply_mood(raw, "__nope__", gender=gender)["applied"] is False


@pytest.mark.skipif(not MODEL_FACE_PATH.exists(), reason="번들 모델 사진 없음")
def test_male_gets_brow_not_blush_or_eyeshadow() -> None:
    import mediapipe as mp

    raw = MODEL_FACE_PATH.read_bytes()
    female = apply_mood(raw, "coral", gender="female")
    male = apply_mood(raw, "coral", gender="male")
    assert female["applied"] and male["applied"]
    assert female["image"] != male["image"]        # 성별에 따라 결과가 실제로 달라야 한다

    original = _decode(female["original_image"])
    h, w = original.shape[:2]
    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=True
    ) as mesh:
        found = mesh.process(original.astype(np.uint8)).multi_face_landmarks
    assert found, "모델 사진에서 얼굴을 찾지 못했다"
    lm = found[0].landmark
    face_w = float(np.linalg.norm(_points(lm, [FACE_RIGHT], w, h)[0] - _points(lm, [FACE_LEFT], w, h)[0]))

    def region(kind: str) -> np.ndarray:
        mask = np.zeros((h, w), np.uint8)
        if kind == "cheek":
            for center in (_points(lm, [LEFT_CHEEK], w, h)[0], _points(lm, [RIGHT_CHEEK], w, h)[0]):
                cv2.circle(mask, tuple(int(v) for v in center), max(5, int(face_w * 0.10)), 255, -1)
        elif kind == "eye":
            lift = max(4, int(face_w * 0.05))
            for indices in (LEFT_EYE_UPPER, RIGHT_EYE_UPPER):
                cv2.fillPoly(mask, [_eyeshadow_poly(_points(lm, indices, w, h), lift)], 255)
        else:
            for indices in (LEFT_BROW, RIGHT_BROW):
                cv2.fillConvexPoly(mask, cv2.convexHull(_points(lm, indices, w, h)), 255)
        return mask > 0

    def delta(result: dict, mask: np.ndarray) -> float:
        return float(np.abs(_decode(result["image"])[mask] - original[mask]).mean())

    # 기준선 = 절대 손대지 않는 좌상단 배경의 변화량(LAB 왕복 반올림)
    background = np.zeros((h, w), bool)
    background[: h // 20, : w // 20] = True
    baseline = delta(male, background)
    assert baseline > 0, "기준선이 0 이면 이 테스트의 판정이 무의미해진다"

    cheek, eye, brow = region("cheek"), region("eye"), region("brow")
    # 여성: 볼·눈에 확실히 색이 올라간다
    assert delta(female, cheek) > baseline * 2
    assert delta(female, eye) > baseline * 2
    # 남성: 볼은 기준선 이하(=아예 안 건드림), 눈썹은 확실히 변한다
    assert delta(male, cheek) <= baseline
    assert delta(male, brow) > baseline * 3
    assert delta(male, brow) > delta(female, brow) * 3
