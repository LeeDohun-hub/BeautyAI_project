"""영유아·소아 안전 게이트 테스트.

원칙: 분류기가 아니라 추천 시점에 연령을 고려한다. baby/child 밴드는 성인 액티브·향료를
배제한 순한 상품만, 그것도 성분이 확인된 것만 노출한다.
"""
from types import SimpleNamespace

from app.services.pediatric_care import (
    PEDIATRIC_AVOID_INGREDIENTS,
    PEDIATRIC_GUIDANCE_INGREDIENTS,
    PEDIATRIC_SAFE_INGREDIENTS,
    has_fragrance_signal,
    is_pediatric,
    is_pediatric_safe,
)


def test_pediatric_age_bands() -> None:
    assert is_pediatric("baby")
    assert is_pediatric("child")
    assert not is_pediatric("10s")
    assert not is_pediatric("30s")
    assert not is_pediatric(None)


def test_safe_and_avoid_sets_are_disjoint() -> None:
    # 같은 성분이 안전이면서 배제일 수 없다.
    assert PEDIATRIC_SAFE_INGREDIENTS.isdisjoint(PEDIATRIC_AVOID_INGREDIENTS)


def test_gentle_moisturizer_passes() -> None:
    assert is_pediatric_safe({"Ceramide", "Glycerin", "Shea Butter"}, "아토팜 판테놀 로션")
    assert is_pediatric_safe({"Petrolatum", "Glycerin"}, "존슨즈베이비 베드타임 로션")


def test_active_ingredients_blocked() -> None:
    # 순한 보습에 액티브가 하나라도 섞이면 배제.
    assert not is_pediatric_safe({"Glycerin", "Salicylic Acid"}, "등드름 바디워시")
    assert not is_pediatric_safe({"Glycerin", "Niacinamide"}, "미백 바디세럼")
    assert not is_pediatric_safe({"Retinol"}, "레티노이드 바디세럼")


def test_missing_ingredients_blocked() -> None:
    # 성분 우선 원칙: 모르면 소아에 올리지 않는다.
    assert not is_pediatric_safe(set(), "아토팜 로션")


def test_unknown_emollient_blocked_by_whitelist() -> None:
    # 화이트리스트 밖 성분이 있으면(안전을 모르므로) 배제.
    assert not is_pediatric_safe({"Ceramide", "SomeUnlistedActive"}, "바디로션")


def test_fragrance_blocked_unless_fragrance_free() -> None:
    assert has_fragrance_signal("존슨즈 아로마밀크 피치&애프리콧")
    assert not has_fragrance_signal("큐렐 무향 로션")
    # 향료 신호가 있으면 성분이 안전해도 배제.
    assert not is_pediatric_safe({"Glycerin", "Shea Butter"}, "존슨즈 아로마밀크 피치")
    # 무향 명시는 통과.
    assert is_pediatric_safe({"Glycerin", "Ceramide"}, "저자극 무향 바디로션")


def test_japanese_fragrance_names_blocked() -> None:
    # JP 상품은 전성분 원문이 없어 이름 검사가 유일한 향료 게이트다. 일본어 향 표현이
    # 있으면 성분이 안전해도 소아에 올리지 않는다(실측 누출: 마츠키요 弱酸性ボディミルク フローラル).
    assert has_fragrance_signal("弱酸性ボディミルク フローラル ４００ｍｌ")
    assert has_fragrance_signal("弱酸性ボディミルク ローズ ４００ｍｌ")
    assert has_fragrance_signal("マシュマロケア ボディミルク シルキーフラワー ２００ｍＬ")
    safe = {"Glycerin", "Hyaluronic Acid", "Petrolatum"}
    assert not is_pediatric_safe(safe, "弱酸性ボディミルク フローラル ４００ｍｌ")
    assert not is_pediatric_safe(safe, "弱酸性ボディミルク ローズ ４００ｍｌ")
    # 무향(無香料) 표기는 계속 통과해야 한다(위 fragrance-free 선통과).
    assert not has_fragrance_signal("弱酸性ボディミルク 無香料 ４００ｍｌ")
    assert is_pediatric_safe(safe, "弱酸性ボディミルク 無香料 ４００ｍｌ")
    # 한자·기타 향 표현도 잡아야 한다(카타카나만 잡으면 새어나감 — 실측 누출).
    assert has_fragrance_signal("BACKYARD FAMILY Saharaの薔薇 CE ローション")
    assert has_fragrance_signal("マッサージオイル 金木犀 ボディオイル")
    assert not is_pediatric_safe(safe, "Saharaの薔薇 ボディセラム")


def test_guidance_ingredients_are_all_safe() -> None:
    # 성분 우선 안내: '이런 성분을 찾으세요'로 내보내는 성분은 반드시 소아안전 화이트리스트
    # 안에 있어야 하고, 배제 성분과 겹치면 안 된다(아기에게 배제 성분을 안내하면 안 됨).
    names = {name for name, _ in PEDIATRIC_GUIDANCE_INGREDIENTS}
    assert names, "안내 성분이 비어 있으면 안 된다"
    assert names <= PEDIATRIC_SAFE_INGREDIENTS
    assert names.isdisjoint(PEDIATRIC_AVOID_INGREDIENTS)
    # 각 항목은 (성분명, 설명) 쌍이고 설명이 비어 있으면 안 된다.
    assert all(name and benefit for name, benefit in PEDIATRIC_GUIDANCE_INGREDIENTS)


def test_recommend_pediatric_surfaces_ingredient_guidance() -> None:
    # 상품이 0건이어도 성분 안내는 항상 채워져야 한다(성인 제품 폴백 금지의 실행가능한 대안).
    import inspect

    from app.services import recommender

    src = inspect.getsource(recommender._recommend_pediatric)
    assert "ingredients=guidance_ingredients" in src
    assert "ingredients=[]" not in src


def test_recommend_derma_care_routes_pediatric() -> None:
    # baby/child age_group 이면 질환 판정과 무관하게 소아 경로로 분기해야 한다.
    # (분류기가 성인 기준이라 아기 질환 판정을 신뢰하지 않는다.)
    import inspect

    from app.services import recommender

    src = inspect.getsource(recommender.recommend_derma_care)
    # 소아 분기가 악성(REFERRAL) 체크보다 먼저 온다.
    assert src.index("is_pediatric(survey.age_group)") < src.index('REFERRAL')


def test_fragrance_in_full_ingredient_list_blocked() -> None:
    # 상품명이 깨끗해도 전성분 원문에 향료·향료알러젠이 있으면 영유아 부적합.
    from app.services.pediatric_care import raw_ingredients_have_fragrance

    loccitane = "정제수, 시어버터, 글리세린, 향료, 리날룰, 제라니올, 시트로넬올"
    assert raw_ingredients_have_fragrance(loccitane)
    essential = "정제수, 글리세린, 라벤더오일, 페퍼민트오일"
    assert raw_ingredients_have_fragrance(essential)
    # 향료 성분이 없으면 통과.
    clean = "정제수, 글리세린, 세라마이드엔피, 판테놀, 다이메티콘"
    assert not raw_ingredients_have_fragrance(clean)
    assert not raw_ingredients_have_fragrance("")
