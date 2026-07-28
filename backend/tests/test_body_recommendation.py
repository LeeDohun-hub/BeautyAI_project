"""바디 추천 슬롯 조립 테스트.

얼굴 5슬롯(클렌저·토너·세럼·보습·선크림)을 바디에 재사용하면 컬럼이 얼굴 제품으로
차버린다. 바디 전용 슬롯이 그걸 막는지, 그리고 자극 성분 배제가 실제로 도는지 본다.
"""
from types import SimpleNamespace

from app.services.body_categories import BODY_CATEGORIES, group_of
from app.services.ingredient_aliases import detect_ingredients_ko
from app.services.recommender import (
    BODY_CATALOG_CATEGORIES,
    BODY_SLOTS,
    build_body_columns,
)
from app.schemas.api import SurveyInput


def _product(name: str, category: str, ingredients: list[str], rating: float = 4.0):
    return SimpleNamespace(
        name=name,
        category=category,
        skin_types="all",
        avg_rating=rating,
        review_count=10,
        product_url="",
        ingredients=[
            SimpleNamespace(ingredient=SimpleNamespace(name=n)) for n in ingredients
        ],
    )


def _scored(products):
    # (total, platform_score, product, reason_tags, evidence)
    return [(50.0, 0.0, p, [], None) for p in products]


def _survey(skin_type: str = "dry") -> SurveyInput:
    return SurveyInput(
        skin_type=skin_type, concerns=[], sensitivity=3, routine_level="basic"
    )


def test_slots_only_use_body_care_categories() -> None:
    # 미스트·데오드란트·제모·선케어는 카탈로그로만 보유하고 추천엔 안 올린다.
    for category in BODY_CATALOG_CATEGORIES:
        assert category in BODY_CATEGORIES, category
        assert group_of(category) == "body"
    for excluded in ("body.mist", "body.deodorant", "body.hair_removal", "body.sun", "body.scrub"):
        assert excluded not in BODY_CATALOG_CATEGORIES
    # 핸드·풋은 매니페디큐어 몫이라 바디 슬롯에 없어야 한다.
    assert not any(c.startswith(("hand.", "foot.")) for c in BODY_CATALOG_CATEGORIES)
    assert [key for key, _label, _cats in BODY_SLOTS] == [
        "body_wash", "body_moisturizer", "body_treatment"
    ]


def test_face_products_never_enter_body_columns() -> None:
    # 얼굴 제품이 섞이던 게 원래 버그다(핸드오프 문서 §1 '바디 추천').
    products = [
        _product("Foaming Facial Cleanser", "cleanser", ["Ceramide"]),
        _product("페이스 세럼", "serum", ["Centella Asiatica"]),
        _product("일리윤 세라마이드 아토 로션", "body.lotion", ["Ceramide"]),
    ]
    columns = build_body_columns(_scored(products), _survey(), {"Ceramide"}, strict=False)
    picked = [p.name for _k, _l, _r, top in columns for p, *_ in top]
    assert picked == ["일리윤 세라마이드 아토 로션"]


def test_strict_mode_drops_products_without_ingredient_data() -> None:
    # avoid 목록이 있는 질환은 성분을 모르는 상품을 쓰면 안 된다 — 자극 성분 검사가 불가능하다.
    known = _product("성분아는 바디로션", "body.lotion", ["Ceramide"])
    unknown = _product("성분모르는 바디로션", "body.lotion", [])
    strict = build_body_columns(_scored([known, unknown]), _survey(), {"Ceramide"}, strict=True)
    assert [p.name for _k, _l, _r, top in strict for p, *_ in top] == ["성분아는 바디로션"]
    # strict 가 아니면 성분 미상도 후보에 남되(가점 방식), 성분 확인된 게 위로 온다.
    loose = build_body_columns(_scored([unknown, known]), _survey(), {"Ceramide"}, strict=False)
    names = [p.name for _k, _l, _r, top in loose for p, *_ in top]
    assert names == ["성분아는 바디로션", "성분모르는 바디로션"]


def test_moisturizer_slot_follows_skin_type() -> None:
    # 얼굴 보습 슬롯과 같은 규칙: 지성·복합은 로션, 그 외는 크림 우선.
    lotion = _product("바디로션", "body.lotion", ["Ceramide"])
    cream = _product("바디크림", "body.cream", ["Ceramide"])
    want = {"Ceramide"}

    def first_moisturizer(skin_type: str) -> str:
        columns = build_body_columns(_scored([lotion, cream]), _survey(skin_type), want, False)
        slot = next(top for key, _l, _r, top in columns if key == "body_moisturizer")
        return slot[0][0].name

    assert first_moisturizer("oily") == "바디로션"
    assert first_moisturizer("dry") == "바디크림"


def test_retinoid_esters_are_detected_as_retinol() -> None:
    # 실측 사고: '힐그리즈 레티노이드 0.1% 바디세럼'의 전성분은
    # 하이드록시피나콜론레티노에이트라 '레티놀' 검색에 안 걸려 습진 추천에 올라왔다.
    hpr = "정제수, 나이아신아마이드, 하이드록시피나콜론레티노에이트, 병풀추출물"
    assert "Retinol" in detect_ingredients_ko(hpr)
    # 상품명만으로도 잡혀야 한다(성분 데이터가 없는 상품이 다수라 2차 방어선이 필요).
    assert "Retinol" in detect_ingredients_ko("힐그리즈 레티노이드 0.1% 퍼밍 바디 세럼")
    assert "Retinol" in detect_ingredients_ko("레티놀 바디로션")


def test_product_market_from_url() -> None:
    from app.services.recommender import product_market

    def m(url):
        return product_market(SimpleNamespace(product_url=url))

    assert m("https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A1") == "kr"
    assert m("https://search.shopping.naver.com/x") == "kr"
    assert m("https://www.matsukiyococokara-online.com/x") == "jp"
    assert m("https://www.amazon.co.jp/dp/B00") == "jp"
    # 라쿠텐 카탈로그 상품(crawl_rakuten_jp_body): product_url 자체가 라쿠텐 → jp 시장.
    # 이게 없으면 적재한 rakuten 상품이 REGION_MARKETS['jp']에 안 잡혀 JP 추천에서 통째 탈락한다.
    assert m("https://item.rakuten.co.jp/hc7/4987036485017/") == "jp"
    assert m("https://global.oliveyoung.com/product/detail?prdtNo=GA1") == "global"
    assert m("https://www.amazon.com/dp/B00") == "us"
    assert m("") == ""


def test_region_markets_partition() -> None:
    from app.services.recommender import REGION_MARKETS

    assert REGION_MARKETS["kr"].isdisjoint(REGION_MARKETS["jp"])
    assert "kr" in REGION_MARKETS["kr"] and "jp" in REGION_MARKETS["jp"]
    assert "global" in REGION_MARKETS["jp"]
    assert REGION_MARKETS.get("all") is None
