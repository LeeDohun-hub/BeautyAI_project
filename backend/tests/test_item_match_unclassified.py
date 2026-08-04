"""분류 못 한 상품은 응답에 실리지 않는다.

왜 중요한가(2026-08-04 실측): 라쿠텐이 '로즈 핑크 립' 검색에 캔들홀더
(キャンドルホルダー … 燭台 … インテリア)를 물어왔다. 백엔드 분류기는 화장품이 아니라고
판정해 column=None 을 줬는데, **프론트에는 column 이 없을 때 쓰는 폴백 규칙이 있다.**
그 폴백은 키워드만 보므로 '로즈 핑크 립'의 '립'에 걸려 **립 컬럼에 캔들홀더 카드가 떴다.**

판정 주체가 둘이면 이런 일이 난다. 백엔드가 끊어야 한다.
"""

from app.api.routes import _item_match_category


class _P:
    """RakutenProduct 대용 — 분류기가 보는 건 name/keyword 뿐이다."""

    def __init__(self, name: str, keyword: str = "") -> None:
        self.name = name
        self.keyword = keyword


def test_candle_holder_is_not_classified() -> None:
    """실제로 라쿠텐이 물어온 상품. 키워드에 '립'이 있어도 화장품이 아니다."""
    product = _P(
        name="キャンドルホルダー 北欧 陶器 おしゃれ 香薫 燭台 インテリア 雑貨 チューリップ型",
        keyword="로즈 핑크 립",
    )
    assert _item_match_category(product) is None


def test_real_lip_product_is_classified() -> None:
    """반대쪽도 지킨다 — 진짜 립이 걸러지면 컬럼이 빈다."""
    assert _item_match_category(_P(name="롬앤 쥬시 래스팅 틴트", keyword="로즈 핑크 립")) == "lip"


def test_nail_is_not_confused_with_snail() -> None:
    """반복 재발한 부분문자열 오탐(nail ⊂ snail). 회귀로 남긴다."""
    assert _item_match_category(_P(name="코스알엑스 스네일 뮤신 에센스", keyword="네일")) != "nail"
    assert _item_match_category(_P(name="데싱디바 젤 네일 스티커", keyword="네일")) == "nail"


def test_unclassified_products_are_dropped_from_response() -> None:
    """라우트가 실제로 걸러내는지 — 분류기만 맞고 응답이 그대로면 의미가 없다."""
    import inspect

    from app.api import routes

    source = inspect.getsource(routes.personal_color_item_match)
    assert "products = [p for p in products if p.column]" in source, (
        "분류 실패 상품을 거르는 줄이 사라졌습니다 — 프론트 폴백이 되살립니다"
    )
