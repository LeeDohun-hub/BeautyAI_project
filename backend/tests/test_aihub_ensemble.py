"""AI-Hub 앙상블(v1+v3)·TTA·borderline 게이팅 회귀 테스트."""
from pathlib import Path

from app.ai.aihub_pc_model import AihubLabSeasonClassifier, season_from_lab
from app.core.config import Settings, get_settings
from app.services.personal_color_analyzer import PersonalColorAnalyzer


def test_season_from_lab_quadrants() -> None:
    # 규칙: 웜/쿨(b vs ITA 회귀선) x 라이트/딥(ITA vs 경계). 대표 사분면이 기대대로 나오는지.
    assert season_from_lab(70.0, 25.0) == "spring"   # 밝고(ITA↑) 노란기 강함 → 웜라이트
    assert season_from_lab(55.0, 30.0) == "autumn"   # 중간밝기·노란기 강함(회귀선 위) → 웜딥
    assert season_from_lab(70.0, 8.0) == "summer"    # 밝고 노란기 약함 → 쿨라이트
    assert season_from_lab(40.0, 6.0) == "winter"    # 어둡고 노란기 약함 → 쿨딥


def test_ensemble_paths_fallback_to_single() -> None:
    # 존재하지 않는 앙상블 경로면 단일 aihub_pc_model_path 로 폴백해야 한다.
    s = Settings(aihub_pc_ensemble_paths="./data/models/__nope_a.pt,./data/models/__nope_b.pt")
    paths = s.resolved_aihub_pc_ensemble_paths
    assert paths == [s.resolved_aihub_pc_model_path]


def test_ensemble_loads_multiple_members_when_present() -> None:
    # 실제 체크포인트가 있으면 v1(3차원)+v3(9차원) 두 멤버가 로드돼야 한다(없으면 skip).
    s = get_settings()
    paths = [p for p in s.resolved_aihub_pc_ensemble_paths if Path(p).exists()]
    if len(paths) < 2:
        import pytest

        pytest.skip("앙상블 체크포인트 2개가 없어 스킵")
    clf = AihubLabSeasonClassifier(paths, tta=True)
    assert clf.load()
    assert len(clf.members) == len(paths)
    assert {m[2] for m in clf.members} == {3, 9}  # v1=3차원, v3=9차원 head


def _reading(season_probs: dict[str, float]) -> dict:
    return {
        "brightness": 0.58, "chroma": 0.15, "warmth": 0.02, "redness": 0.02,
        "season_probs": season_probs,
        "model_season_probs": season_probs,
        "color_season_probs": None,
        "color_vector": {"quality": 0.6},
        "white_balanced": True, "face_detected": True,
        "landmark_skin_samples": 100.0, "sample_weight": 1.0,
    }


def test_borderline_flag_marks_ambiguous_only() -> None:
    analyzer = PersonalColorAnalyzer()
    # 확실: 한 계절이 지배 → borderline 0
    clear = analyzer._build_response(_reading({"spring": 0.70, "summer": 0.12, "autumn": 0.10, "winter": 0.08}))
    assert clear.metrics["borderline"] == 0.0
    # 경계선: 1·2위 격차 작고 top 확률 낮음 → borderline 1, alternate 병기
    amb = analyzer._build_response(_reading({"summer": 0.30, "winter": 0.28, "spring": 0.22, "autumn": 0.20}))
    assert amb.metrics["borderline"] == 1.0
    assert amb.alternate_season is not None
