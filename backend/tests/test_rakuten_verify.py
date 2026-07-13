"""JP 라쿠텐 검증 직링크 부착 테스트(네트워크 없이 가짜 클라이언트로).

스킨케어 `/recommend` 흐름은 라쿠텐 소스가 아니면 라쿠텐 버튼이 안 붙던 문제를 보완했다
(_verify_rakuten_for_skincare). 브랜드 일치 리스팅만 채택하고, 못 찾으면 미출력임을 검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from app.api.routes import (
    _filter_by_requested_platform,
    _verify_rakuten_for_global,
    _verify_rakuten_for_skincare,
)


@dataclass
class _FakeHit:
    brand: str
    name: str
    product_url: str


class _FakeClient:
    """search(keyword) -> 키워드에 매핑된 히트. 호출 키워드를 기록한다."""

    configured = True

    def __init__(self, table: dict[str, list[_FakeHit]]):
        self.table = table
        self.calls: list[str] = []

    def search(self, keyword: str, hits: int = 3):
        self.calls.append(keyword)
        return self.table.get(keyword, [])


def _product(brand: str, name: str, source: str = "", links: dict | None = None):
    return SimpleNamespace(
        brand=brand, name=name, source=source,
        product_url="", platform_links=dict(links or {}), matched_platforms=[],
    )


def test_skincare_attaches_verified_rakuten_link():
    name = "COSRX Advanced Snail 96 Mucin Power Essence"
    client = _FakeClient({name: [_FakeHit("koreabeautystar", "[COSRX] カタツムリ96 エッセンス", "https://item.rakuten.co.jp/x/cosrx1/")]})
    products = [_product("COSRX", name)]  # source="" (스킨케어 추천 그대로)
    _verify_rakuten_for_skincare(products, client)
    assert products[0].platform_links.get("rakuten") == "https://item.rakuten.co.jp/x/cosrx1/"
    assert "rakuten" in products[0].matched_platforms


def test_skincare_no_button_when_brand_mismatch():
    # 히트는 있으나 브랜드(anua)가 리스팅에 없으면 붙이지 않는다(엉뚱한 상품 방지).
    name = "Anua Heartleaf 77 Soothing Toner"
    client = _FakeClient({name: [_FakeHit("someshop", "他社 ドクダミ トナー 250ml", "https://item.rakuten.co.jp/x/other/")]})
    products = [_product("Anua", name)]
    _verify_rakuten_for_skincare(products, client)
    assert products[0].platform_links.get("rakuten") is None


def test_skincare_skips_products_already_having_rakuten():
    name = "Beauty of Joseon Relief Sun"
    client = _FakeClient({name: [_FakeHit("shop", "Beauty of Joseon 米 日焼け止め", "https://item.rakuten.co.jp/x/new/")]})
    products = [_product("Beauty of Joseon", name, links={"rakuten": "https://existing/"})]
    _verify_rakuten_for_skincare(products, client)
    assert products[0].platform_links["rakuten"] == "https://existing/"  # 기존 직링크 유지
    assert client.calls == []  # 이미 있으면 API 호출도 안 함


def test_skincare_respects_limit():
    # limit=1이면 상위 1개만 검증(라쿠텐 429 방지).
    client = _FakeClient({
        "A Serum": [_FakeHit("s", "A Serum", "https://item.rakuten.co.jp/x/a/")],
        "B Serum": [_FakeHit("s", "B Serum", "https://item.rakuten.co.jp/x/b/")],
    })
    products = [_product("A", "A Serum"), _product("B", "B Serum")]
    _verify_rakuten_for_skincare(products, client, limit=1)
    assert products[0].platform_links.get("rakuten")
    assert products[1].platform_links.get("rakuten") is None


def test_item_match_male_flow_unaffected():
    # 회귀: source='oliveyoung_global'만 처리하는 아이템매칭 남성 흐름은 그대로 동작한다.
    name = "UNO Whip Wash"
    client = _FakeClient({name: [_FakeHit("shop", "ウーノ UNO ホイップウォッシュ 洗顔", "https://item.rakuten.co.jp/x/uno/")]})
    male = [_product("UNO", name, source="oliveyoung_global")]
    other = [_product("UNO", name, source="")]  # 글로벌 소스 아님 → 이 함수는 무시
    _verify_rakuten_for_global(male, client)
    _verify_rakuten_for_global(other, client)
    assert male[0].platform_links.get("rakuten") == "https://item.rakuten.co.jp/x/uno/"
    assert other[0].platform_links.get("rakuten") is None


def test_item_match_platform_filter_keeps_only_requested_direct_links():
    amazon = _product("peripera", "Pure Blushed Sunshine Cheek", links={"amazon_jp": "https://www.amazon.co.jp/dp/B07C9CPRQQ"})
    rakuten = _product("CANMAKE", "Shading Powder", links={"rakuten": "https://item.rakuten.co.jp/x/canmake/"})

    assert _filter_by_requested_platform([amazon, rakuten], "all") == [amazon, rakuten]
    assert _filter_by_requested_platform([amazon, rakuten], "amazon_jp") == [amazon]
