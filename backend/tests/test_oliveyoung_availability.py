"""올리브영 글로벌몰 입점 검증 + 검색어 후보 로직 테스트.

실제 네트워크를 타지 않도록 _has_results 를 monkeypatch 한다.
"""

from __future__ import annotations

from types import SimpleNamespace

import app.services.oliveyoung_availability as oa
from app.services.platform_resolver import oliveyoung_query_candidates


def setup_function() -> None:
    oa.clear_cache()


def _product(brand, name, links):
    return SimpleNamespace(brand=brand, name=name, platform_links=dict(links), matched_platforms=sorted(links))


def test_candidates_keep_brand_and_shrink_name():
    # 모든 후보에 정규화된 브랜드가 유지되고, 라인 토큰이 점점 줄어든다.
    cands = oliveyoung_query_candidates("Dr. Jart+", "Cicapair Tiger Grass Color Correcting Treatment SPF 30")
    assert cands == ["Dr.Jart+ Cicapair Tiger", "Dr.Jart+ Cicapair", "Dr.Jart+"]


def test_candidates_normalize_dot_space():
    # 'Dr. Jart+' → 'Dr.Jart+' (점 뒤 공백 제거) — 올리브영 검색이 공백에 민감.
    assert all(c.startswith("Dr.Jart+") for c in oliveyoung_query_candidates("Dr. Jart+", "Cicapair"))


def test_resolve_returns_first_hitting_query(monkeypatch):
    # 첫 후보는 0건, 두 번째가 히트 → 두 번째를 채택.
    hits = {"Cetaphil Moisturizing Lotion": False, "Cetaphil Moisturizing": True}
    monkeypatch.setattr(oa, "_has_results", lambda q: hits.get(q, False))
    assert oa.resolve_global_query("Cetaphil", "Moisturizing Lotion for All Skin Types") == "Cetaphil Moisturizing"


def test_resolve_all_zero_hides(monkeypatch):
    # 전 후보 명시적 0건 → None(버튼 숨김).
    monkeypatch.setattr(oa, "_has_results", lambda q: False)
    assert oa.resolve_global_query("CeraVe", "Moisturizing Cream") is None


def test_resolve_unverifiable_hides(monkeypatch):
    # 엄격 정책: 네트워크 오류 등 확인 불가(None)는 버튼 숨김.
    monkeypatch.setattr(oa, "_has_results", lambda q: None)
    assert oa.resolve_global_query("Dr. Jart+", "Cicapair Tiger Grass") is None


def test_resolve_does_not_fallback_to_brand_only(monkeypatch):
    # 브랜드 단독 검색은 해당 상품 입점 근거가 아니므로 채택하지 않는다.
    hits = {"The Ordinary": True}
    monkeypatch.setattr(oa, "_has_results", lambda q: hits.get(q, False))
    assert oa.resolve_global_query("The Ordinary", "AHA 30% + BHA 2% Peeling Solution") is None


def test_prune_removes_button_when_zero(monkeypatch):
    monkeypatch.setattr(oa, "_has_results", lambda q: False)
    p = _product("CeraVe", "Moisturizing Cream",
                 {"oliveyoung": "x", "rakuten": "r", "amazon_jp": "a"})
    oa.prune_global_oliveyoung([p])
    assert "oliveyoung" not in p.platform_links
    assert p.matched_platforms == ["amazon_jp", "rakuten"]


def test_prune_replaces_with_verified_query(monkeypatch):
    monkeypatch.setattr(oa, "_has_results", lambda q: q == "Dr.Jart+ Cicapair Tiger")
    p = _product("Dr. Jart+", "Cicapair Tiger Grass Color Correcting Treatment SPF 30",
                 {"oliveyoung": "old", "rakuten": "r"})
    oa.prune_global_oliveyoung([p])
    assert "oliveyoung" in p.platform_links
    assert "Cicapair+Tiger" in p.platform_links["oliveyoung"]
    assert "global.oliveyoung.com" in p.platform_links["oliveyoung"]


def test_prune_skips_products_without_oliveyoung(monkeypatch):
    called = {"n": 0}

    def _fake(brand, name):
        called["n"] += 1
        return None

    monkeypatch.setattr(oa, "resolve_global_query", _fake)
    p = _product("Brand", "Product", {"rakuten": "r"})
    oa.prune_global_oliveyoung([p])
    assert called["n"] == 0
    assert p.platform_links == {"rakuten": "r"}
