"""KR 네이버 한글화 보강 + 올리브영 후보 쿼리(정크/중복 가드) 테스트."""

from __future__ import annotations

from types import SimpleNamespace

import app.services.naver_kr_enricher as enr
from app.services.naver_client import NaverProduct
from app.services.platform_resolver import oliveyoung_kr_query, oliveyoung_query_candidates


def _np(brand, name, url="https://smartstore.naver.com/x", image="img"):
    return NaverProduct(
        id="1", brand=brand, name=name, price=1000, image_url=image,
        product_url=url, review_average=None, review_count=None, keyword="",
    )


def _product(brand, name):
    return SimpleNamespace(brand=brand, name=name, source="", product_url=None,
                           image_url=None, platform_links={}, matched_platforms=[])


# --- 올리브영 후보 쿼리 가드 ---

def test_candidates_skip_duplicate_brand_in_name():
    # 이름이 이미 브랜드로 시작하면 브랜드를 또 붙이지 않는다('오휘 오휘…' 방지).
    cands = oliveyoung_query_candidates("오휘", "오휘 더퍼스트 제너츄어 립스틱")
    assert not any(c.startswith("오휘 오휘") for c in cands)
    assert cands[0].startswith("오휘 더퍼스트")


def test_candidates_drop_junk_naver_brand():
    # '네이버쇼핑' 정크 브랜드는 쿼리에 섞지 않고 상품명 코어만 쓴다.
    cands = oliveyoung_query_candidates("네이버쇼핑", "하우스랩스 040 페어 뉴트럴 파운데이션")
    assert all("네이버쇼핑" not in c for c in cands)
    assert cands[0].startswith("하우스랩스")


def test_candidates_normal_brand_prefixed():
    cands = oliveyoung_query_candidates("Dr. Jart+", "Cicapair Tiger Grass Color Correcting Treatment SPF 30")
    assert cands == ["Dr.Jart+ Cicapair Tiger", "Dr.Jart+ Cicapair", "Dr.Jart+"]


# --- 올리브영 국내몰: 한글 우선 쿼리 ---

def test_kr_query_prefers_korean_even_when_korean_is_at_tail():
    # 영문이 앞, 한글이 뒤에 있어도 한글 토큰만 뽑아 쿼리를 만든다.
    q = oliveyoung_kr_query("라로슈포제", "La Roche Posay Cicaplast Baume B5 라로슈포제 시카플라스트")
    assert q == "라로슈포제 시카플라스트"


def test_kr_query_no_duplicate_brand():
    # 브랜드가 이미 첫 한글 토큰이면 중복해서 붙이지 않는다.
    q = oliveyoung_kr_query("세라비", "CeraVe 세라비 모이스처라이징 크림 453g")
    assert q == "세라비 모이스처라이징 크림"


def test_kr_query_falls_back_to_english_when_no_korean():
    # 한글이 전혀 없으면 영문 후보 쿼리로 폴백한다.
    q = oliveyoung_kr_query("CeraVe", "Moisturizing Cream")
    assert q == "CeraVe Moisturizing Cream"


# --- 한글 브랜드 추출 ---

def test_korean_brand_prefers_hangul():
    items = [_np("네이버쇼핑", "x"), _np("세라비", "y")]
    assert enr._korean_brand(items, "CeraVe") == "세라비"


def test_korean_brand_skips_junk_and_unknown():
    items = [_np("네이버쇼핑", "x"), _np("UNKNOWN", "y")]
    # 한글이지만 정크인 '네이버쇼핑', 한글 아닌 'UNKNOWN' 모두 제외 → 원문 유지.
    assert enr._korean_brand(items, "The Ordinary") == "The Ordinary"


# --- 보강 파이프라인 ---

def test_enrich_replaces_with_korean_and_marks_source(monkeypatch):
    class FakeClient:
        configured = True
        def search(self, query, hits=5):
            return [_np("세라비", "CeraVe 세라비 모이스처라이징 크림 453g", url="https://smartstore.naver.com/p/1")]
    monkeypatch.setattr(enr, "NaverClient", lambda: FakeClient())
    p = _product("CeraVe", "Moisturizing Cream")
    n = enr.enrich_products_with_naver_kr([p])
    assert n == 1
    assert p.brand == "세라비"
    assert p.name.startswith("CeraVe 세라비")
    assert p.source == "naver"
    assert p.product_url == "https://smartstore.naver.com/p/1"
    assert p.image_url == "img"


def test_enrich_preserves_original_english_amazon_query_for_korean_only_result(monkeypatch):
    class FakeClient:
        configured = True
        def search(self, query, hits=5):
            return [_np("올레이", "올레이 리제너리스트 레티놀 24 나이트 페이스 크림 모이스처라이저 무향 50g")]
    monkeypatch.setattr(enr, "NaverClient", lambda: FakeClient())
    p = _product("Olay", "Regenerist Retinol 24 Night Face Moisturizer")

    n = enr.enrich_products_with_naver_kr([p])

    assert n == 1
    assert p.brand == "올레이"
    assert p.name.startswith("올레이 리제너리스트")
    assert p.platform_links["amazon_us"] == (
        "https://www.amazon.com/s?k=Olay+Regenerist+Retinol+24+Night+Face+Moisturizer"
    )


def test_enrich_replaces_stale_direct_amazon_url_with_search_query(monkeypatch):
    class FakeClient:
        configured = True
        def search(self, query, hits=5):
            return [_np("올레이", "올레이 리제너리스트 레티놀 24 나이트 페이스 크림 모이스처라이저 무향 50g")]
    monkeypatch.setattr(enr, "NaverClient", lambda: FakeClient())
    p = _product("Olay", "Regenerist Retinol 24 Night Face Moisturizer")
    p.platform_links = {"amazon_us": "https://www.amazon.com/dp/B07MCJFKQ8"}

    n = enr.enrich_products_with_naver_kr([p])

    assert n == 1
    assert p.platform_links["amazon_us"] == (
        "https://www.amazon.com/s?k=Olay+Regenerist+Retinol+24+Night+Face+Moisturizer"
    )


def test_enrich_keeps_original_when_no_results(monkeypatch):
    class FakeClient:
        configured = True
        def search(self, query, hits=5):
            return []
    monkeypatch.setattr(enr, "NaverClient", lambda: FakeClient())
    p = _product("CeraVe", "Moisturizing Cream")
    assert enr.enrich_products_with_naver_kr([p]) == 0
    assert p.brand == "CeraVe" and p.source == ""


def test_enrich_noop_when_unconfigured(monkeypatch):
    class FakeClient:
        configured = False
        def search(self, query, hits=5):
            raise AssertionError("should not be called")
    monkeypatch.setattr(enr, "NaverClient", lambda: FakeClient())
    p = _product("CeraVe", "Moisturizing Cream")
    assert enr.enrich_products_with_naver_kr([p]) == 0
    assert p.source == ""
