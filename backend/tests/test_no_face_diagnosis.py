"""얼굴 미검출 시 '왜 못 찾았는지'를 짚어주는지 검사한다.

왜 만들었나: 지금까지는 "얼굴을 찾지 못했습니다"만 나갔다. 사용자는 무엇을 고쳐야 할지
모른 채 같은 사진을 다시 올린다. 2026-08-04 실측에서 열화된 사진은 품질 게이트가 아니라
**검출 단계에서 먼저 떨어진다**는 것이 확인돼(게이트는 랜드마크가 있어야 돈다),
그 구간을 안내가 비어 있는 채로 둘 수 없었다.

문턱 근거(표본 5장, 전체 이미지 지표):
    조건        전체밝기      전체흐림      짧은변
    원본        130~138      144~338      750
    밝기0.4     51.7~54.6    25~56        750
    흐림r8      130~138      1.7~2.0      750
    축소0.05    130~138      105~291      127
"""

import numpy as np

from app.services import virtual_surgery_simulator as vss


def _photo(brightness: int = 135, noise: int = 26, size: tuple[int, int] = (700, 700)) -> np.ndarray:
    rng = np.random.default_rng(0)
    return np.clip(rng.normal(brightness, noise, size=(*size, 3)), 0, 255).astype(np.uint8)


def test_normal_photo_gets_no_extra_reason() -> None:
    """정상 사진인데 얼굴만 없는 경우(예: 얼굴이 안 찍힘)에는 억지 이유를 붙이지 않는다."""
    assert vss.diagnose_no_face(_photo()) == ""


def test_dark_photo_says_dark() -> None:
    assert "어두워서" in vss.diagnose_no_face(_photo(brightness=45))


def test_small_photo_says_resolution() -> None:
    assert "해상도" in vss.diagnose_no_face(_photo(size=(150, 150)))


def test_overexposed_photo_says_light() -> None:
    assert "빛이 너무 강해" in vss.diagnose_no_face(_photo(brightness=252, noise=2))


def test_blurry_photo_says_blurry() -> None:
    y = np.linspace(90, 170, 700, dtype=np.float32)
    smooth = np.repeat(np.repeat(y[:, None], 700, axis=1)[:, :, None], 3, axis=2).astype(np.uint8)
    assert "흔들렸거나" in vss.diagnose_no_face(smooth)


def test_dark_wins_over_blur() -> None:
    """어두우면 흐림 지표도 같이 떨어진다(실측 25~56).

    순서를 잘못 두면 어두운 사진에 '흔들렸다'고 말하게 된다 — 사용자가 엉뚱한 걸 고친다.
    """
    dark_and_smooth = np.full((700, 700, 3), 40, dtype=np.uint8)
    assert "어두워서" in vss.diagnose_no_face(dark_and_smooth)


def test_reason_is_separate_from_the_base_message() -> None:
    """이유는 안내 문장에 **이어붙이지 않고** photo_quality 로 따로 나간다.

    이어붙이면 번역 키가 '기본문 + 이유' 조합만큼 늘어난다(이유 4개면 5가지).
    이유를 하나 더할 때마다 조합이 또 늘어나므로 분리해 둔다.
    """
    q = vss.no_face_quality(_photo(brightness=45))
    assert q["ok"] is False
    assert [i["code"] for i in q["issues"]] == ["no_face_reason"]
    assert "어두워서" in q["issues"][0]["message"]
    # 기본 안내 문장 자체는 이유가 섞이지 않은 채로 유지된다.
    assert vss.NO_FACE_MESSAGE == "얼굴을 찾지 못했습니다. 정면 얼굴과 밝은 조명의 사진으로 다시 시도해 주세요."


def test_no_reason_means_ok_true() -> None:
    """짚을 이유가 없으면 경고를 만들지 않는다 — 억지 이유는 오히려 방해다."""
    q = vss.no_face_quality(_photo())
    assert q["ok"] is True
    assert q["issues"] == []
