from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import quote_plus

from app.services.platform_resolver import (
    OLIVEYOUNG_KR_SEARCH,
    build_search_query,
    oliveyoung_kr_query,
    resolve_product_platforms,
)


def test_naver_junk_brand_is_excluded_from_oliveyoung_query() -> None:
    # 네이버가 브랜드 미상일 때 채우는 '네이버쇼핑'이 검색어 앞에 붙으면 올리브영이 0건이 된다.
    # (실측: query=네이버쇼핑+하우스랩스+페어 → '검색 결과가 없어요')
    assert oliveyoung_kr_query("네이버쇼핑", "하우스랩스 페어 파운데이션") == "하우스랩스 페어 파운데이션"
    assert "네이버쇼핑" not in build_search_query("네이버쇼핑", "하우스랩스 페어 파운데이션")
    # 진짜 한글 브랜드는 기존대로 앞에 붙는다.
    assert oliveyoung_kr_query("라로슈포제", "La Roche Posay 라로슈포제 시카플라스트 밤").startswith("라로슈포제")


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


def test_rakuten_source_keeps_only_verified_rakuten_button_for_jp() -> None:
    product = _product("rakuten")

    resolve_product_platforms(product, "jp")

    assert product.platform_links == {"rakuten": "https://item.rakuten.co.jp/shop/example/"}
    assert product.matched_platforms == ["rakuten"]


def test_merged_product_with_direct_rakuten_link_does_not_add_unverified_buttons() -> None:
    product = _product("database", "")
    product.platform_links = {"rakuten": "https://item.rakuten.co.jp/shop/example/"}
    product.matched_platforms = ["rakuten"]

    resolve_product_platforms(product, "jp")

    assert product.platform_links == {"rakuten": "https://item.rakuten.co.jp/shop/example/"}
    assert product.matched_platforms == ["rakuten"]


def test_naver_source_adds_oliveyoung_kr_search_button_for_kr() -> None:
    product = _product("naver", "https://search.shopping.naver.com/catalog/123")

    resolve_product_platforms(product, "kr")

    assert product.platform_links["naver"] == "https://search.shopping.naver.com/catalog/123"
    # 국내몰은 서버 검증이 불가능하므로 검색 링크로 항상 노출한다(네이버 보강 상품도 동일).
    assert product.platform_links["oliveyoung"] == _expected_oliveyoung_kr(product.brand, product.name)
    assert product.matched_platforms == ["naver", "oliveyoung"]


def test_naver_source_preserves_existing_english_amazon_search_for_kr() -> None:
    product = _product("naver", "https://search.shopping.naver.com/catalog/123")
    product.platform_links = {
        "amazon_us": "https://www.amazon.com/s?k=The+Ordinary+AHA+30%25+BHA+2%25+Peeling+Solution",
    }

    resolve_product_platforms(product, "kr")

    assert product.platform_links == {
        "amazon_us": "https://www.amazon.com/s?k=The+Ordinary+AHA+30%25+BHA+2%25+Peeling+Solution",
        "naver": "https://search.shopping.naver.com/catalog/123",
        "oliveyoung": _expected_oliveyoung_kr(product.brand, product.name),
    }
    assert product.matched_platforms == ["amazon_us", "naver", "oliveyoung"]


def test_naver_source_uses_preserved_english_amazon_query_for_korean_only_name() -> None:
    product = _product("naver", "https://search.shopping.naver.com/catalog/123")
    product.brand = "올레이"
    product.name = "올레이 리제너리스트 레티놀 24 나이트 페이스 크림 모이스처라이저 무향 50g"
    product.platform_links = {
        "amazon_us": "https://www.amazon.com/s?k=Olay+Regenerist+Retinol+24+Night+Face+Moisturizer",
    }

    resolve_product_platforms(product, "kr")

    assert product.platform_links == {
        "amazon_us": "https://www.amazon.com/s?k=Olay+Regenerist+Retinol+24+Night+Face+Moisturizer",
        "naver": "https://search.shopping.naver.com/catalog/123",
        "oliveyoung": _expected_oliveyoung_kr(product.brand, product.name),
    }
    assert product.matched_platforms == ["amazon_us", "naver", "oliveyoung"]


def test_naver_source_uses_korean_search_link_for_oliveyoung_kr() -> None:
    product = _product("naver", "https://search.shopping.naver.com/catalog/123")
    product.brand = "라로슈포제"
    product.name = "La Roche Posay Cicaplast Baume B5 Soothing Repairing Balm 라로슈포제 시카플라스트 밤 B5+ 100ml 기획"
    product.platform_links = {
        "amazon_us": "https://www.amazon.com/s?k=La+Roche+Posay+Cicaplast+Baume+B5",
    }

    resolve_product_platforms(product, "kr")

    # 하드코딩 goodsNo 없이 한글 라인명 검색 링크로 노출된다.
    assert product.platform_links["oliveyoung"] == (
        OLIVEYOUNG_KR_SEARCH + quote_plus("라로슈포제 시카플라스트 밤")
    )
    assert product.platform_links["naver"] == "https://search.shopping.naver.com/catalog/123"
    assert product.platform_links["amazon_us"] == "https://www.amazon.com/s?k=La+Roche+Posay+Cicaplast+Baume+B5"
    assert product.matched_platforms == ["amazon_us", "naver", "oliveyoung"]


def test_naver_source_prefers_english_alias_for_amazon_search() -> None:
    product = _product("naver", "https://search.shopping.naver.com/catalog/123")
    product.brand = "코스알엑스"
    product.name = "코스알엑스 바하 블랙헤드 피지 100ml / COSRX, BHA Blackhead Power Liquid"
    product.platform_links = {
        "amazon_us": "https://www.amazon.com/s?k=COSRX+AHA+BHA+Clarifying+Treatment+Toner",
    }

    resolve_product_platforms(product, "kr")

    assert product.platform_links["amazon_us"] == "https://www.amazon.com/s?k=COSRX+BHA+Blackhead+Power+Liquid"
    assert product.platform_links["naver"] == "https://search.shopping.naver.com/catalog/123"
    assert product.platform_links["oliveyoung"] == _expected_oliveyoung_kr(product.brand, product.name)


def test_merged_product_with_direct_naver_link_adds_only_oliveyoung_kr_search_button() -> None:
    product = _product("database", "")
    product.platform_links = {"naver": "https://search.shopping.naver.com/catalog/123"}
    product.matched_platforms = ["naver"]

    resolve_product_platforms(product, "kr")

    # 네이버 직링크는 유지하고, 검증 불가한 amazon은 붙이지 않되 올리브영 검색 링크는 노출한다.
    assert product.platform_links == {
        "naver": "https://search.shopping.naver.com/catalog/123",
        "oliveyoung": _expected_oliveyoung_kr(product.brand, product.name),
    }
    assert product.matched_platforms == ["naver", "oliveyoung"]


def test_hide_oliveyoung_removes_kr_button_but_keeps_others() -> None:
    product = _product("naver", "https://search.shopping.naver.com/catalog/123")

    resolve_product_platforms(product, "kr", hide_oliveyoung=True)

    assert product.platform_links["naver"] == "https://search.shopping.naver.com/catalog/123"
    assert "oliveyoung" not in product.platform_links


def test_non_rakuten_jp_product_can_expose_search_platform_buttons() -> None:
    product = _product("database", "")

    resolve_product_platforms(product, "jp")

    assert {"rakuten", "amazon_jp"}.issubset(product.platform_links)
    assert {"rakuten", "amazon_jp"}.issubset(product.matched_platforms)


def test_search_query_keeps_compound_slash_in_product_identity() -> None:
    # 'AHA/BHA'는 붙은 슬래시라 상품 정체성이다. ' / ' 별칭 구분자와 달리 자르면 안 된다.
    # (자르면 'COSRX AHA'만 남아 라쿠텐/아마존 검색이 실제 토너를 못 찾는다.)
    query = build_search_query("COSRX", "AHA/BHA Clarifying Treatment Toner")
    assert query == "COSRX AHA BHA Clarifying Treatment Toner"

    # ' / ' 공백 구분자는 기존대로 이후를 버린다(영문 별칭 분리).
    aliased = build_search_query("코스알엑스", "코스알엑스 바하 블랙헤드 피지 100ml / COSRX, BHA Blackhead Power Liquid")
    assert aliased == "코스알엑스 바하 블랙헤드 피지"


def test_search_query_drops_japanese_shop_prefix_before_latin_brand() -> None:
    failed = "ネムクル YOYOSOFT パウダーパフ ミニサイズ 直径4cm 入 プレストパウダー"
    successful = "YOYOSOFT パウダーパフ ミニサイズ 直径4cm 入 プレストパウダー"

    assert build_search_query("", failed) == build_search_query("", successful)
    assert build_search_query("", failed).startswith("YOYOSOFT")
