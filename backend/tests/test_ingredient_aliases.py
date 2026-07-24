"""한글/일본어 성분명 → 표준 성분명 매핑 테스트.

전성분 문자열은 올리브영 상품정보제공고시에서 실제로 받아온 것이다.
"""
from app.services.ingredient_aliases import (
    detect_ingredients_ja,
    detect_ingredients_ko,
    split_ingredients_ko,
)

# 아비브 핸드크림(A000000234418) 실제 고시 전성분 일부.
ABIB_HAND = (
    "S타입 정제수, 글리세린, 카프릴릭/카프릭트라이글리세라이드, 세틸에틸헥사노에이트, 향료, "
    "1,2-헥산다이올, 시어버터, 카보머, 에틸헥실글리세린, 잔탄검, 시트로넬올, 판테놀, 쿠마린, 토코페롤"
)
# 일리윤 세라마이드 아토 로션(A000000217765) 실제 고시 전성분 일부.
ILLIYOON_ATO = (
    "정제수, 글리세린, 프로판다이올, 다이메티콘, 하이드로제네이티드쌀겨오일, "
    "세틸에틸헥사노에이트, 1,2-헥산다이올, 글리세릴스테아레이트, 세라마이드엔피, "
    "병풀추출물, 소듐하이알루로네이트"
)


def test_detects_ingredient_absent_from_product_name() -> None:
    # 상품명은 '아비브 핸드크림 3종'뿐이라 이름 기반으론 아무것도 안 잡힌다.
    # 고시 전성분에서는 판테놀이 나온다 — 이게 고시를 쓰는 이유다.
    assert "Panthenol" in detect_ingredients_ko(ABIB_HAND)


def test_detects_derivative_forms() -> None:
    # 표준화 성분명은 유도체로 적힌다. 정확일치로 쪼개면 전부 놓친다.
    found = detect_ingredients_ko(ILLIYOON_ATO)
    assert "Ceramide" in found            # 세라마이드엔피
    assert "Centella Asiatica" in found   # 병풀추출물
    assert "Hyaluronic Acid" in found     # 소듐하이알루로네이트


def test_korean_inci_uses_aessid_not_san() -> None:
    # 대한화장품협회 표준명은 '살리실산'이 아니라 '살리실릭애씨드'다. 둘 다 잡아야 한다.
    assert detect_ingredients_ko("정제수, 살리실릭애씨드") == ["Salicylic Acid"]
    assert detect_ingredients_ko("정제수, 살리실산") == ["Salicylic Acid"]


def test_zinc_oxide_is_not_treated_as_sebum_zinc() -> None:
    # 징크옥사이드는 자외선차단제다. 이걸 Zinc 로 잡으면 선크림이 전부 피지케어가 된다.
    assert "Zinc" not in detect_ingredients_ko("정제수, 징크옥사이드, 티타늄디옥사이드")
    assert "Zinc" in detect_ingredients_ko("정제수, 징크피씨에이")


def test_split_strips_set_product_type_label() -> None:
    # 기획/세트 상품은 'S타입 정제수, ...' 처럼 타입 라벨이 앞에 붙는다.
    parts = split_ingredients_ko(ABIB_HAND)
    assert parts[0] == "정제수"
    assert "판테놀" in parts


def test_empty_input_is_safe() -> None:
    assert detect_ingredients_ko("") == []
    assert detect_ingredients_ko(None or "") == []
    assert split_ingredients_ko("") == []


def test_japanese_aliases() -> None:
    # 라쿠텐 itemCaption 용(현재 미사용이지만 매핑은 유지).
    caption = "成分：グリチルレチン酸ステアリル その他の成分：セラミド、ヒアルロン酸、パンテノール"
    found = detect_ingredients_ja(caption)
    assert {"Ceramide", "Hyaluronic Acid", "Panthenol"} <= set(found)


def test_body_emollients_are_detected() -> None:
    # 얼굴 액티브 14종만 보면 바디 제품 전성분의 68%만 잡힌다(실측). 실제 바디 구성은
    # 에몰리언트·오클루시브다. 아래는 올리브영 고시에서 그대로 가져온 문자열.
    innisfree = "정제수, 부틸렌글라이콜, 베헤닐알코올, 세테아릴알코올, 시어버터, 펜틸렌글라이콜"
    assert "Shea Butter" in detect_ingredients_ko(innisfree)
    vaseline = "페트롤라툼(43.2 %), 황색4호, 티타늄디옥사이드"
    assert "Petrolatum" in detect_ingredients_ko(vaseline)
    skinfood = "정제수, 소듐라우레스설페이트, 코카미도프로필베타인, 꿀추출물, 글리세린"
    assert "Glycerin" in detect_ingredients_ko(skinfood)


def test_body_emollients_use_non_face_targets() -> None:
    # 글리세린은 상품 82%에 들어 있다. 얼굴 점수 타깃을 주면 severity_focus(타깃 평균)가
    # 뭉개져 얼굴 랭킹이 망가진다. barrier/moisture/soothing 으로 격리한다.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from load_product_catalog_to_db import INGREDIENT_RULES

    from app.services.recommender import FACE_SCORE_TARGETS

    body_only = [
        "Glycerin", "Petrolatum", "Shea Butter", "Squalane",
        "Allantoin", "Colloidal Oatmeal", "Urea", "Dimethicone", "Jojoba Oil",
    ]
    for name in body_only:
        targets = set(INGREDIENT_RULES[name][1].split(","))
        assert not (targets & FACE_SCORE_TARGETS), f"{name} 이 얼굴 타깃을 가짐: {targets}"
    # 기존 얼굴 성분은 반대로 전부 얼굴 타깃이어야 한다(필터가 no-op 임을 보장).
    for name in ("Niacinamide", "Retinol", "Ceramide", "Panthenol"):
        targets = set(INGREDIENT_RULES[name][1].split(","))
        assert targets & FACE_SCORE_TARGETS, name


def test_japanese_body_emollients() -> None:
    # 라쿠텐 itemCaption 실측 표기.
    caption = "【その他の成分】精製水、濃グリセリン、シア脂、スクワラン、ワセリン、メチルポリシロキサン"
    found = set(detect_ingredients_ja(caption))
    assert {"Glycerin", "Shea Butter", "Squalane", "Petrolatum", "Dimethicone"} <= found
