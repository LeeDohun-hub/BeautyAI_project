"""아마존 Beauty 카탈로그 매처 테스트(임시 매니페스트 주입).

Kaggle US 데이터셋의 긴 타이틀에 강건한 '커버리지(containment) 매칭' + 브랜드 게이트를 검증한다.
"""

from __future__ import annotations

import csv
from pathlib import Path

import app.services.amazon_catalog as ac


def setup_function() -> None:
    ac.clear_cache()


def teardown_function() -> None:
    ac.clear_cache()


_HEADER = ["asin", "brand", "title", "stars", "reviews", "imageUrl"]
_ROWS = [
    ("B01CLIO", "CLIO", "CLIO Kill Cover The New Founwear Cushion 4 Ginger SPF50 30g", "4.5", "1200", ""),
    ("B02COSRX", "COSRX Advanced", "COSRX Advanced Snail 96 Mucin Power Essence 3.38 fl oz 100ml", "4.6", "50000", ""),
    ("B03BOJ", "Beauty", "Beauty of Joseon Relief Sun Rice Probiotics SPF50 50ml", "4.7", "80000", ""),
    ("B04LILY", "Lily", "Lily Of The Desert Aloe Vera Gelly Moisturizer 12 oz", "4.4", "3000", ""),
    ("B05LAN", "LANEIGE", "LANEIGE Water Bank Blue Hyaluronic Cream 50ml", "4.5", "9000", ""),
]


def _use_manifest(monkeypatch, tmp_path: Path, rows=_ROWS) -> None:
    path = tmp_path / "amazon_beauty_products.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_HEADER)
        w.writerows(rows)
    monkeypatch.setattr(ac, "_manifest_path", lambda: path)
    ac.clear_cache()


def test_unavailable_when_manifest_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(ac, "_manifest_path", lambda: tmp_path / "absent.csv")
    ac.clear_cache()
    assert ac.catalog_available() is False
    assert ac.match_amazon("CLIO", "Clio Kill Cover Cushion") is None


def test_matches_long_title_by_coverage(monkeypatch, tmp_path):
    _use_manifest(monkeypatch, tmp_path)
    m = ac.match_amazon("CLIO", "Clio Kill Cover Founwear Cushion")
    assert m is not None and m.asin == "B01CLIO"
    m2 = ac.match_amazon("COSRX", "COSRX Advanced Snail 96 Mucin Power Essence")
    assert m2 is not None and m2.asin == "B02COSRX"


def test_korean_brand_alias(monkeypatch, tmp_path):
    _use_manifest(monkeypatch, tmp_path)
    # 한글 브랜드도 영문 별칭으로 매칭(라네즈 → laneige).
    m = ac.match_amazon("라네즈", "LANEIGE Water Bank Blue Hyaluronic Cream")
    assert m is not None and m.asin == "B05LAN"


def test_amazon_search_query_translates_japanese_makeup_terms():
    assert ac.amazon_search_query("SNIDEL BEAUTY 楽天市場店", "ベージュコーラル チーク") == (
        "snidel beauty beige coral cheek"
    )
    assert ac.amazon_search_query("CLIO", "ミュートブラウン アイシャドウ パレット") == (
        "clio muted brown eyeshadow palette"
    )


def test_amazon_search_query_translates_korean_brand_and_terms():
    assert ac.amazon_search_query("자빈드서울", "윙크 파운데이션 팩트 리필 15g 23호") == (
        "javin de seoul foundation"
    )


def test_rejects_cross_brand_common_word(monkeypatch, tmp_path):
    _use_manifest(monkeypatch, tmp_path)
    # 'Beauty of Joseon' 이 공용어 'of' 로 'Lily Of The Desert' 에 새면 안 된다(브랜드 게이트).
    m = ac.match_amazon("Beauty of Joseon", "Beauty of Joseon Relief Sun Rice Probiotics")
    assert m is not None and m.asin == "B03BOJ"  # 올바른 브랜드로 매칭


def test_no_match_when_product_absent(monkeypatch, tmp_path):
    _use_manifest(monkeypatch, tmp_path)
    # 카탈로그에 없는 상품은 매칭 없음(오탐 링크 방지).
    assert ac.match_amazon("Innisfree", "Innisfree Green Tea Seed Serum") is None


def test_urls(monkeypatch, tmp_path):
    assert ac.amazon_com_url("B01X").endswith("amazon.com/dp/B01X")
    assert ac.amazon_jp_url("B01X").endswith("amazon.co.jp/dp/B01X")
