"""실시간 플랫폼 입점 확인 정책 테스트.

실제 네트워크/네이버 API를 호출하지 않도록 내부 함수를 monkeypatch 한다.
판정은 '브랜드' 검색 기준이다(상품 풀네임 검색은 네이버에서 신뢰도가 낮으므로).
"""

from __future__ import annotations

import app.services.platform_availability as pa


def _settings(client_id, client_secret):
    return lambda: type("S", (), {"naver_client_id": client_id, "naver_client_secret": client_secret})()


def setup_function() -> None:
    pa.clear_cache()


def test_no_credentials_hides_nothing(monkeypatch):
    # 자격증명이 없으면 확인 불가 → 숨길 플랫폼 없음.
    monkeypatch.setattr(pa, "get_settings", _settings(None, None))
    hidden = pa.unavailable_platforms_bulk([(1, "BIOHEAL BOH", "Vitacnergy Patch", {"naver", "amazon_us", "matsukiyo"})])
    assert hidden == {}


def test_brand_absent_hides_only_naver(monkeypatch):
    monkeypatch.setattr(pa, "get_settings", _settings("id", "sec"))
    # 브랜드 검색 0건 → 미입점(False).
    monkeypatch.setattr(pa, "_naver_search_total", lambda query: 0)
    hidden = pa.unavailable_platforms_bulk([(7, "FakeBrand", "Product", {"naver", "amazon_us", "oliveyoung"})])
    assert hidden == {7: {"naver"}}


def test_brand_present_hides_nothing(monkeypatch):
    monkeypatch.setattr(pa, "get_settings", _settings("id", "sec"))
    monkeypatch.setattr(pa, "_naver_search_total", lambda query: 9405)
    hidden = pa.unavailable_platforms_bulk([(7, "SKIN1004", "Centella Ampoule", {"naver", "amazon_us"})])
    assert hidden == {}


def test_naver_error_treated_as_unverifiable(monkeypatch):
    monkeypatch.setattr(pa, "get_settings", _settings("id", "sec"))
    # 네트워크 오류 등 → None(확인 불가) → 숨기지 않음(일단 표시).
    monkeypatch.setattr(pa, "_naver_search_total", lambda query: None)
    hidden = pa.unavailable_platforms_bulk([(7, "Brand", "Product", {"naver", "amazon_us"})])
    assert hidden == {}


def test_product_without_naver_candidate_skipped(monkeypatch):
    monkeypatch.setattr(pa, "get_settings", _settings("id", "sec"))
    called = False

    def _fake_total(query):
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(pa, "_naver_search_total", _fake_total)
    hidden = pa.unavailable_platforms_bulk([(7, "Brand", "Product", {"amazon_us", "oliveyoung"})])
    assert hidden == {}
    assert called is False


def test_query_uses_brand_only(monkeypatch):
    # 판정 쿼리에 상품명이 아니라 브랜드만 쓰이는지 확인.
    monkeypatch.setattr(pa, "get_settings", _settings("id", "sec"))
    seen = []

    def _fake_total(query):
        seen.append(query)
        return 5

    monkeypatch.setattr(pa, "_naver_search_total", _fake_total)
    pa.naver_available("SKIN1004", "Madagascar Centella Retinol Ampoule 30ml")
    assert seen == ["SKIN1004"]


def test_cache_dedupes_same_brand(monkeypatch):
    monkeypatch.setattr(pa, "get_settings", _settings("id", "sec"))
    calls = {"n": 0}

    def _fake_total(query):
        calls["n"] += 1
        return 0

    monkeypatch.setattr(pa, "_naver_search_total", _fake_total)
    # 같은 브랜드는 한 번만 조회(캐시).
    pa.naver_available("Brand", "Product A")
    pa.naver_available("Brand", "Product B")
    assert calls["n"] == 1
