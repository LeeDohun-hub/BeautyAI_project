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
    # 브랜드 컬럼이 'i'로 깨진 행(실데이터에 428행 존재). 부분문자열('i' in 'espoir')로 새면 안 된다.
    ("B06KISS", "i", "i ENVY BY KISS Brow Stamp Perfect Eyebrow Dark Brown KPBS01", "4.2", "500", ""),
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


def test_rejects_degenerate_short_brand_key(monkeypatch, tmp_path):
    _use_manifest(monkeypatch, tmp_path)
    # 브랜드키 'i'(1글자, 컬럼 파싱 오류)가 'espoir'의 부분문자열이라도 매칭되면 안 된다.
    # (실측 오탐: 에스쁘아 브로우 펜슬 → 'i ENVY BY KISS Brow Stamp' 링크)
    m = ac.match_amazon("에스쁘아", "espoir brown brow soft pencil")
    assert m is None


def test_no_match_when_product_absent(monkeypatch, tmp_path):
    _use_manifest(monkeypatch, tmp_path)
    # 카탈로그에 없는 상품은 매칭 없음(오탐 링크 방지).
    assert ac.match_amazon("Innisfree", "Innisfree Green Tea Seed Serum") is None


def test_merges_crawl_manifest(monkeypatch, tmp_path):
    # 크롤 보강 매니페스트(amazon_beauty_us.csv)가 있으면 Kaggle 베이스와 함께 로드된다.
    _use_manifest(monkeypatch, tmp_path)  # 베이스(amazon_beauty_products.csv)
    crawl = tmp_path / "amazon_beauty_us.csv"
    with crawl.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_HEADER)
        # 베이스에 없는 espoir 브로우 펜슬(크롤로만 확보). 타이틀에 브랜드 없어도 brand 컬럼으로 매칭.
        w.writerow(("B0ESPOIR1", "espoir", "The Brow Balance Pencil #3 Soft Brown Eye Brow Pencil", "4.5", "300", ""))
    ac.clear_cache()
    m = ac.match_amazon("에스쁘아", "espoir the brow balance pencil soft brown")
    assert m is not None and m.asin == "B0ESPOIR1"


def test_crawl_manifest_absent_is_fine(monkeypatch, tmp_path):
    # 크롤 파일이 없어도(베이스만) 정상 동작한다.
    _use_manifest(monkeypatch, tmp_path)
    assert ac.catalog_available() is True
    assert ac.match_amazon("CLIO", "Clio Kill Cover Founwear Cushion") is not None


def test_jp_catalog_matches_japanese_title(monkeypatch, tmp_path):
    # JP 카탈로그(amazon_beauty_jp.csv, 일본어 타이틀)를 '일본어 상품명'으로 매칭한다.
    # 브랜드는 라틴 시드(anua)라 게이트가 라틴↔라틴으로 맞고, 라인은 일본어 토큰(ドクダミ)이 겹친다.
    _use_manifest(monkeypatch, tmp_path)  # US 베이스(무관)
    jp = tmp_path / "amazon_beauty_jp.csv"
    with jp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_HEADER)
        w.writerow(("B0JPANUA1", "anua", "ANUA アヌア ドクダミ77 スージングトナー 250ml", "4.6", "900", ""))
    ac.clear_cache()
    # 한글 브랜드 + 일본어 상품명 → JP 카탈로그 매칭
    m = ac.match_amazon("아누아", "アヌア ドクダミ77 トナー", region="jp")
    assert m is not None and m.asin == "B0JPANUA1"
    # US 카탈로그(영문)에는 이 일본어 상품이 없다 → region 기본(us)이면 매칭 없음
    assert ac.match_amazon("아누아", "アヌア ドクダミ77 トナー") is None


def test_jp_catalog_rejects_row_with_conflicting_brand_in_title(monkeypatch, tmp_path):
    _use_manifest(monkeypatch, tmp_path)
    jp = tmp_path / "amazon_beauty_jp.csv"
    with jp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_HEADER)
        w.writerow((
            "B0WRONG2AN",
            "wakemake",
            "2aN Official Eyeshadow Palette BETTER ME EYE PALETTE 14 Slush Pop",
            "4.5",
            "420",
            "",
        ))
    ac.clear_cache()

    assert ac.match_amazon("WAKEMAKE", "Soft Blurring Eye Palette", region="jp") is None


def test_urls(monkeypatch, tmp_path):
    assert ac.amazon_com_url("B01X").endswith("amazon.com/dp/B01X")
    assert ac.amazon_jp_url("B01X").endswith("amazon.co.jp/dp/B01X")


# ── 2026-07-30 버그리포트 회귀 방어 ────────────────────────────────────────────
# 사용자가 보고한 오매칭 4건의 원인별 게이트를 각각 고정한다.


def test_rejects_brand_key_matching_mid_word(monkeypatch, tmp_path):
    """브랜드 부분문자열 오탐: 'anua' 는 'm-anua-l' 의 부분문자열이다.

    실측 오탐: '아누아 어성초 쿼세티놀 포어 딥 클렌징폼' → 'Manual Facial Cleansing Kabuki Brush'.
    길이 4 하한만으론 단어 **중간**에 걸리는 걸 못 막아, 접두 규칙으로 바꿨다.
    """
    _use_manifest(monkeypatch, tmp_path, rows=[
        ("B0MANUAL", "Manual", "Manual Facial Cleansing Kabuki Brush Skin Cleanser for Applying Foundation", "4.1", "700", ""),
    ])
    assert ac.match_amazon("아누아", "anua heartleaf quercetinol pore deep cleansing foam") is None


def test_rejects_different_product_form(monkeypatch, tmp_path):
    """제형 게이트: 선크림 쿼리가 '수딩 크림'에 매칭되면 안 된다.

    실측 오탐: '아누아 어성초 실키 모이스처 선크림' → 'Anua Heartleaf 70% Soothing Cream'.
    라인 토큰 2개(cream/moisture)만 겹쳐도 커버리지 0.5 를 넘겨 통과했다.
    """
    _use_manifest(monkeypatch, tmp_path, rows=[
        ("B0ANUASOOTH", "Anua", "Anua Heartleaf 70% Soothing Cream 100ml moisturizing soothing the skin", "4.6", "5000", ""),
    ])
    assert ac.match_amazon("아누아", "anua moisture sunscreen silky cream") is None
    # 같은 제형(수딩크림)으로 물으면 정상 매칭돼야 한다(게이트가 과하게 막지 않는지 확인).
    m = ac.match_amazon("아누아", "anua heartleaf soothing cream moisturizing")
    assert m is not None and m.asin == "B0ANUASOOTH"


def test_rejects_tool_for_cosmetic_query(monkeypatch, tmp_path):
    """도구/부속품은 화장품 쿼리의 매칭 대상이 아니다(제형='tool')."""
    _use_manifest(monkeypatch, tmp_path, rows=[
        ("B0BRUSH1", "CLIO", "CLIO Makeup Brush Set 5 pcs for Cushion Foundation", "4.3", "800", ""),
    ])
    assert ac.match_amazon("CLIO", "clio kill cover founwear cushion") is None


def test_requires_rare_identity_token(monkeypatch, tmp_path):
    """희귀어 게이트: 상품 정체성을 정하는 희귀 토큰이 빠진 후보는 기각한다.

    실측 오탐: 'St.Tropez Gradual Tan **Watermelon** …' → '… **Tinted** …'(다른 SKU).
    문턱 판정이 '카탈로그에 흔한 어휘일 때만' 켜지도록, 흔한 토큰을 채워 중앙값을 올린다.
    """
    common = [
        (f"B0FILL{i:02d}", "Generic", f"Generic Daily Firming Body Lotion Tan Moisturizer variant {i}", "4.0", "10", "")
        for i in range(200)
    ]
    _use_manifest(monkeypatch, tmp_path, rows=[
        ("B0STTINT", "St.Tropez", "St.Tropez Gradual Tan Tinted Daily Firming Body Lotion 200ml Tanning Moisturizer", "4.4", "3000", ""),
        *common,
    ])
    # 'watermelon' 은 이 카탈로그에 없으므로 요구 대상이 아니고(df=0), 'gradual' 은 희귀+후보에 존재.
    # 대신 후보에 없는 희귀어를 요구하는지 확인하려면 카탈로그에 있는 희귀어를 쓴다.
    assert ac.match_amazon("St.Tropez", "st tropez gradual tan tinted daily firming lotion") is not None
    # 'tinted' 대신 다른 쉐이드(카탈로그에 존재하는 희귀어)를 요구하면 기각돼야 한다.
    _use_manifest(monkeypatch, tmp_path, rows=[
        ("B0STTINT", "St.Tropez", "St.Tropez Gradual Tan Tinted Daily Firming Body Lotion 200ml Tanning Moisturizer", "4.4", "3000", ""),
        ("B0WMELON", "Generic", "Generic Watermelon Sugar Scrub", "4.0", "5", ""),
        *common,
    ])
    assert ac.match_amazon("St.Tropez", "st tropez gradual tan watermelon daily firming lotion") is None


def test_untrusted_source_requires_verified_asin(monkeypatch, tmp_path):
    """사망률 높은 덤프(HF)는 개별 HTTP 검증된 ASIN만 링크로 쓴다.

    HF 카탈로그는 실측 사망률 48.5% 인데 전체 매칭의 80% 를 차지해, 게이트 없이 쓰면
    아마존 버튼 10개 중 4개가 404("Sorry! We couldn't find that page")로 열렸다.
    """
    _use_manifest(monkeypatch, tmp_path, rows=[])  # 베이스는 비움
    hf = tmp_path / "amazon_beauty_hf.csv"
    with hf.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_HEADER)
        w.writerow(("B0HFDEAD", "holika", "HOLIKA HOLIKA My Fave Mood Eye Palette 01 Daisy Matte Shimmer", "4.3", "900", ""))
    ac.clear_cache()

    # 미검증 HF 행 → 버튼 없음
    monkeypatch.setattr(ac, "_verified_alive_asins", lambda: frozenset())
    assert ac.match_amazon("홀리카홀리카", "holika my fave mood eye palette") is None

    # 검증(ok)된 뒤에는 쓸 수 있다
    ac.match_amazon.cache_clear()
    monkeypatch.setattr(ac, "_verified_alive_asins", lambda: frozenset({"B0HFDEAD"}))
    m = ac.match_amazon("홀리카홀리카", "holika my fave mood eye palette")
    assert m is not None and m.asin == "B0HFDEAD"


def test_product_form_detects_korean_and_japanese():
    assert ac.product_form("아누아 어성초 실키 모이스처 선크림 50ml") == "sunscreen"
    assert ac.product_form("ANUA ドクダミ77 スージングトナー 250ml") == "toner"
    assert ac.product_form("メイクブラシ 5本セット 携帯用") == "tool"
    assert ac.product_form("ROUND LAB Pine Calming Cica Body Wash 400ml") == "bodywash"


def test_rare_token_gate_off_for_cross_language_catalog(monkeypatch, tmp_path):
    """JP 카탈로그(일본어)에 영문 쿼리를 넣으면 영문 토큰이 전부 '희귀'로 잡힌다.

    그 상태로 게이트를 켜면 완전일치를 요구해 amazon_jp 링크가 전멸한다(실측 5→0).
    쿼리 어휘가 카탈로그에 흔할 때만 켜지는지 확인한다.
    """
    _use_manifest(monkeypatch, tmp_path, rows=[])
    jp = tmp_path / "amazon_beauty_jp.csv"
    with jp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_HEADER)
        w.writerow(("B0JPANUA2", "anua", "ANUA アヌア ドクダミ 77 スージング トナー 250ml 化粧水", "4.6", "900", ""))
    ac.clear_cache()
    # 영문 쿼리의 라인 토큰(heartleaf/soothing/toner)은 이 카탈로그에 df 0~1 이라 희귀 판정이
    # 무의미하다 → 게이트가 꺼지고, 브랜드+제형(토너)으로 매칭돼야 한다.
    assert ac._rare_tokens(frozenset({"heartleaf", "soothing", "toner"}), "jp") == frozenset()
