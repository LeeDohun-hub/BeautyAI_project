from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import quote_plus

import pytest

import app.services.platform_resolver as pr
from app.services.platform_resolver import (
    OLIVEYOUNG_GLOBAL_DETAIL,
    OLIVEYOUNG_KR_SEARCH,
    build_search_query,
    oliveyoung_kr_query,
    resolve_product_platforms,
)


@pytest.fixture(autouse=True)
def _no_catalog(monkeypatch):
    # 레거시(검색 링크) 동작 테스트는 실제 카탈로그 CSV 유무와 무관하게 '카탈로그 없음'을
    # 가정한다. 카탈로그 분기 테스트는 본문에서 catalog_available 을 True로 덮어쓴다.
    monkeypatch.setattr(pr, "catalog_available", lambda: False)
    # 아마존 Beauty 카탈로그도 끈다(레거시 테스트는 amazon 매칭 무관 — 실제 52k 매니페스트에 의존 X).
    monkeypatch.setattr(pr.amazon_catalog, "catalog_available", lambda: False)


def _expected_oliveyoung_kr(brand: str, name: str) -> str:
    return OLIVEYOUNG_KR_SEARCH + quote_plus(oliveyoung_kr_query(brand, name))


def _product(source: str, product_url: str = "https://item.rakuten.co.jp/shop/example/"):
    return SimpleNamespace(
        brand="e.l.f.",
        name="Soft Glam Satin Foundation 20 Light Cool",
        product_url=product_url,
        source=source,
        platform_links={},
        matched_platforms=[],
    )


def test_oliveyoung_global_source_keeps_only_oy_direct_when_unmatched() -> None:
    # JP 남성 주입 상품: OY prdtNo 직링크만 유지(언어 무관 보존). 라쿠텐/아마존은 직링크 없으면
    # 안 붙는다(검색 폴백 폐기 — 직링크 있으면 버튼, 없으면 미출력). 라쿠텐 직링크는 API 검증 시
    # routes._verify_rakuten_for_global 이 별도로 붙인다.
    direct = OLIVEYOUNG_GLOBAL_DETAIL + quote_plus("GA240925619")
    product = SimpleNamespace(
        brand="ダシュ",
        name="DASHU メンズアクアトーンアップBBローション40ml",
        product_url=direct,
        source="oliveyoung_global",
        platform_links={"oliveyoung": direct},
        matched_platforms=["oliveyoung"],
    )
    resolve_product_platforms(product, "jp")
    assert product.platform_links == {"oliveyoung": direct}
    assert "rakuten" not in product.platform_links


def test_jp_existing_oliveyoung_direct_link_survives_resolve() -> None:
    # dedup으로 라쿠텐 상품에 병합된 prdtNo 직링크도 유지된다(일본어 재매칭 실패로 버려지지 않게).
    direct = OLIVEYOUNG_GLOBAL_DETAIL + quote_plus("GA111")
    product = SimpleNamespace(
        brand="DASHU",
        name="ダシュ メンズ クッション",
        product_url="https://item.rakuten.co.jp/x/",
        source="rakuten",
        platform_links={"rakuten": "https://item.rakuten.co.jp/x/", "oliveyoung": direct},
        matched_platforms=["rakuten", "oliveyoung"],
    )
    resolve_product_platforms(product, "jp")
    assert product.platform_links.get("oliveyoung") == direct


def test_naver_junk_brand_is_excluded_from_oliveyoung_query() -> None:
    assert oliveyoung_kr_query("네이버쇼핑", "하우스랩스 페어 파운데이션") == "하우스랩스 페어 파운데이션"
    assert "네이버쇼핑" not in build_search_query("네이버쇼핑", "하우스랩스 페어 파운데이션")
    assert oliveyoung_kr_query(
        "라로슈포제",
        "La Roche Posay 라로슈포제 시카플라스트 밤",
    ).startswith("라로슈포제")


def test_rakuten_source_keeps_only_rakuten_when_amazon_unmatched() -> None:
    product = _product("rakuten")

    resolve_product_platforms(product, "jp")

    assert product.platform_links == {"rakuten": "https://item.rakuten.co.jp/shop/example/"}
    assert product.matched_platforms == ["rakuten"]


def test_rakuten_source_adds_amazon_jp_only_when_asin_matched(monkeypatch) -> None:
    monkeypatch.setattr(pr.amazon_catalog, "catalog_available", lambda: True)
    monkeypatch.setattr(
        pr.amazon_catalog,
        "match_amazon",
        lambda brand, query: SimpleNamespace(asin="B0MATCHJP"),
    )
    product = _product("rakuten")

    resolve_product_platforms(product, "jp")

    assert product.platform_links["rakuten"] == "https://item.rakuten.co.jp/shop/example/"
    assert product.platform_links["amazon_jp"] == "https://www.amazon.co.jp/dp/B0MATCHJP"
    assert product.matched_platforms == ["amazon_jp", "rakuten"]


def test_merged_product_with_direct_rakuten_link_does_not_add_unmatched_amazon() -> None:
    product = _product("database", "")
    product.platform_links = {"rakuten": "https://item.rakuten.co.jp/shop/example/"}
    product.matched_platforms = ["rakuten"]

    resolve_product_platforms(product, "jp")

    assert product.platform_links == {"rakuten": "https://item.rakuten.co.jp/shop/example/"}


def test_naver_source_adds_oliveyoung_kr_without_unmatched_amazon() -> None:
    product = _product("naver", "https://search.shopping.naver.com/catalog/123")

    resolve_product_platforms(product, "kr")

    assert product.platform_links["naver"] == "https://search.shopping.naver.com/catalog/123"
    assert product.platform_links["oliveyoung"] == _expected_oliveyoung_kr(product.brand, product.name)
    assert "amazon_us" not in product.platform_links
    assert product.matched_platforms == ["naver", "oliveyoung"]


def test_naver_source_adds_amazon_us_only_when_asin_matched(monkeypatch) -> None:
    monkeypatch.setattr(pr.amazon_catalog, "catalog_available", lambda: True)
    monkeypatch.setattr(
        pr.amazon_catalog,
        "match_amazon",
        lambda brand, query: SimpleNamespace(asin="B0MATCHUS"),
    )
    product = _product("naver", "https://search.shopping.naver.com/catalog/123")

    resolve_product_platforms(product, "kr")

    assert product.platform_links["naver"] == "https://search.shopping.naver.com/catalog/123"
    assert product.platform_links["amazon_us"] == "https://www.amazon.com/dp/B0MATCHUS"
    assert product.matched_platforms == ["amazon_us", "naver", "oliveyoung"]


def test_naver_source_drops_stale_amazon_when_unmatched(monkeypatch) -> None:
    product = _product("naver", "https://search.shopping.naver.com/catalog/123")
    product.platform_links = {"amazon_us": "https://www.amazon.com/s?k=stale"}

    resolve_product_platforms(product, "kr")

    assert "amazon_us" not in product.platform_links
    assert product.platform_links["naver"] == "https://search.shopping.naver.com/catalog/123"


def test_naver_source_uses_korean_search_link_for_oliveyoung_kr() -> None:
    product = _product("naver", "https://search.shopping.naver.com/catalog/123")
    product.brand = "라로슈포제"
    product.name = "La Roche Posay Cicaplast Baume B5 Soothing Repairing Balm 라로슈포제 시카플라스트 밤 B5+ 100ml 기획"

    resolve_product_platforms(product, "kr")

    assert product.platform_links["oliveyoung"] == (
        OLIVEYOUNG_KR_SEARCH + quote_plus("라로슈포제 시카플라스트 밤")
    )
    assert product.platform_links["naver"] == "https://search.shopping.naver.com/catalog/123"
    assert "amazon_us" not in product.platform_links
    assert product.matched_platforms == ["naver", "oliveyoung"]


def test_merged_product_with_direct_naver_link_adds_only_oliveyoung_when_amazon_unmatched() -> None:
    product = _product("database", "")
    product.platform_links = {"naver": "https://search.shopping.naver.com/catalog/123"}
    product.matched_platforms = ["naver"]

    resolve_product_platforms(product, "kr")

    assert product.platform_links == {
        "naver": "https://search.shopping.naver.com/catalog/123",
        "oliveyoung": _expected_oliveyoung_kr(product.brand, product.name),
    }


def test_hide_oliveyoung_removes_kr_button_but_keeps_others() -> None:
    product = _product("naver", "https://search.shopping.naver.com/catalog/123")

    resolve_product_platforms(product, "kr", hide_oliveyoung=True)

    assert product.platform_links["naver"] == "https://search.shopping.naver.com/catalog/123"
    assert "oliveyoung" not in product.platform_links


def test_non_rakuten_jp_product_no_rakuten_or_unmatched_amazon() -> None:
    product = _product("database", "")

    resolve_product_platforms(product, "jp")

    assert "rakuten" not in product.platform_links
    assert "amazon_jp" not in product.platform_links


def test_search_query_keeps_compound_slash_in_product_identity() -> None:
    query = build_search_query("COSRX", "AHA/BHA Clarifying Treatment Toner")
    assert query == "COSRX AHA BHA Clarifying Treatment Toner"

    aliased = build_search_query(
        "코스알엑스",
        "코스알엑스 바하 블랙헤드 피지 100ml / COSRX, BHA Blackhead Power Liquid",
    )
    assert aliased == "코스알엑스 바하 블랙헤드 피지"


def test_search_query_drops_japanese_shop_prefix_before_latin_brand() -> None:
    failed = "ネムクル YOYOSOFT パウダーパフ ミニサイズ 直径4cm 入 プレストパウダー"
    successful = "YOYOSOFT パウダーパフ ミニサイズ 直径4cm 入 プレストパウダー"

    assert build_search_query("", failed) == build_search_query("", successful)
    assert build_search_query("", failed).startswith("YOYOSOFT")


def _match(prdt_no: str, gds_cd: str = ""):
    return SimpleNamespace(prdt_no=prdt_no, gds_cd=gds_cd, score=1.0)


def test_jp_catalog_match_uses_prdt_no_direct_link(monkeypatch) -> None:
    # 카탈로그가 있으면 JP 올리브영은 검색이 아니라 prdtNo 직링크.
    monkeypatch.setattr(pr, "catalog_available", lambda: True)
    monkeypatch.setattr(pr, "match_oliveyoung", lambda brand, name: _match("GA210000002"))
    product = _product("database", "")

    resolve_product_platforms(product, "jp")

    assert product.platform_links["oliveyoung"] == OLIVEYOUNG_GLOBAL_DETAIL + quote_plus("GA210000002")


def test_jp_catalog_miss_hides_oliveyoung_button(monkeypatch) -> None:
    # 카탈로그에 없으면(미취급 확정) JP 올리브영 버튼을 붙이지 않는다.
    monkeypatch.setattr(pr, "catalog_available", lambda: True)
    monkeypatch.setattr(pr, "match_oliveyoung", lambda brand, name: None)
    product = _product("database", "")

    resolve_product_platforms(product, "jp")

    assert "oliveyoung" not in product.platform_links  # 미취급 확정 → OY 버튼 없음
    assert "rakuten" not in product.platform_links
    assert "amazon_jp" not in product.platform_links


def test_jp_rakuten_source_still_gets_verified_catalog_oliveyoung(monkeypatch) -> None:
    # 라쿠텐 실상품이라도 올리브영 글로벌 카탈로그에 매칭되면 '검증된 prdtNo 직링크'를 함께 붙인다.
    monkeypatch.setattr(pr, "catalog_available", lambda: True)
    monkeypatch.setattr(pr, "match_oliveyoung", lambda brand, name: _match("GA210000009"))
    product = _product("rakuten")

    resolve_product_platforms(product, "jp")

    assert product.platform_links["rakuten"] == "https://item.rakuten.co.jp/shop/example/"
    assert product.platform_links["oliveyoung"] == OLIVEYOUNG_GLOBAL_DETAIL + quote_plus("GA210000009")
    assert product.matched_platforms == ["oliveyoung", "rakuten"]


def test_jp_rakuten_source_no_oliveyoung_or_unmatched_amazon_without_catalog(monkeypatch) -> None:
    monkeypatch.setattr(pr, "catalog_available", lambda: False)
    product = _product("rakuten")

    resolve_product_platforms(product, "jp")

    assert "oliveyoung" not in product.platform_links
    assert product.platform_links == {"rakuten": "https://item.rakuten.co.jp/shop/example/"}


def test_kr_sets_provisional_search_link_ignoring_global_catalog(monkeypatch) -> None:
    # KR은 글로벌 카탈로그와 무관하게 잠정 한글 검색 링크를 붙인다(실검증/직링크는 KR 라이브 prune).
    monkeypatch.setattr(pr, "catalog_available", lambda: True)
    monkeypatch.setattr(pr, "match_oliveyoung", lambda brand, name: None)
    product = _product("naver", "https://search.shopping.naver.com/catalog/123")

    resolve_product_platforms(product, "kr")

    assert product.platform_links["oliveyoung"] == _expected_oliveyoung_kr(product.brand, product.name)
