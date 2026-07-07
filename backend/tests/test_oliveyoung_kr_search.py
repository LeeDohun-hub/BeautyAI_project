"""올리브영 국내몰 라이브 검색(NewMainSearchApi) 매칭/prune 테스트.

network(curl_cffi)를 타지 않도록 search_kr 를 monkeypatch 한다.
"""

from __future__ import annotations

import csv
from types import SimpleNamespace

import pytest

import app.services.oliveyoung_kr_search as ks
from app.services.oliveyoung_kr_search import KRResult, KRSearch


@pytest.fixture(autouse=True)
def _no_kr_catalog(monkeypatch, tmp_path):
    # 라이브 검색 경로 테스트는 실제 KR 카탈로그 CSV 유무와 무관하게 '카탈로그 없음'을 가정한다.
    # 카탈로그 테스트는 본문에서 _use_kr_catalog 로 덮어쓴다.
    monkeypatch.setattr(ks, "_kr_catalog_path", lambda: tmp_path / "absent.csv")
    ks.clear_cache()


def _use_kr_catalog(monkeypatch, tmp_path, rows):
    path = tmp_path / "oliveyoung_kr_products.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["goodsNo", "brandName", "goodsName", "soldOut"])
        writer.writerows(rows)
    monkeypatch.setattr(ks, "_kr_catalog_path", lambda: path)
    ks.clear_kr_catalog_cache()


def _product(brand, name, links):
    return SimpleNamespace(brand=brand, name=name, platform_links=dict(links), matched_platforms=sorted(links))


# '오휘 더퍼스트' 검색의 1등이 '포맨'인 실제 상황. 매칭이 라인을 구별해야 한다.
_OHUI = (
    KRResult("A_MEN", "오휘", "오휘 더 퍼스트 제너츄어 포맨 모이스처라이저 110ml", False),
    KRResult("A_LIP", "오휘", "오휘 더퍼스트 제너츄어 립스틱", False),
)


def _fixed(search: KRSearch):
    return lambda query: search


def test_parse_extracts_fields_and_soldout():
    payload = {
        "Parameter": [{"totalCount": 2}],
        "Data": [{"Result": [
            {"GOODS_NO": "A1", "GOODS_NM": "롬앤 제로 벨벳 틴트", "ONL_BRND_NM": "롬앤", "GOODS_SOUT_INFO": "N"},
            {"GOODS_NO": "A2", "GOODS_NM": "품절상품", "ONL_BRND_NM": "롬앤", "GOODS_SOUT_INFO": "Y"},
        ]}],
    }
    sr = ks._parse(payload)
    assert sr.total_count == 2 and len(sr.results) == 2
    assert sr.results[0].goods_no == "A1" and sr.results[0].sold_out is False
    assert sr.results[1].sold_out is True


def test_resolve_picks_correct_line_not_top_result(monkeypatch):
    monkeypatch.setattr(ks, "search_kr", _fixed(KRSearch(2, _OHUI)))
    match, verifiable = ks.resolve_kr_goods("오휘", "오휘 더퍼스트 제너츄어 립스틱")
    assert verifiable is True
    assert match is not None and match.goods_no == "A_LIP"  # 포맨(A_MEN)으로 새지 않는다


def test_resolve_zero_results_is_verifiable_absent(monkeypatch):
    monkeypatch.setattr(ks, "search_kr", _fixed(KRSearch(0, ())))
    match, verifiable = ks.resolve_kr_goods("없는브랜드", "없는 상품 이름")
    assert match is None and verifiable is True


def test_resolve_network_error_is_unverifiable(monkeypatch):
    monkeypatch.setattr(ks, "search_kr", lambda query: None)
    match, verifiable = ks.resolve_kr_goods("오휘", "오휘 더퍼스트 립스틱")
    assert match is None and verifiable is False


def test_resolve_soldout_only_no_match(monkeypatch):
    soldout = (KRResult("A_LIP", "오휘", "오휘 더퍼스트 제너츄어 립스틱", True),)
    monkeypatch.setattr(ks, "search_kr", _fixed(KRSearch(1, soldout)))
    match, verifiable = ks.resolve_kr_goods("오휘", "오휘 더퍼스트 제너츄어 립스틱")
    assert match is None and verifiable is True


def test_prune_replaces_with_goods_direct_link(monkeypatch):
    monkeypatch.setattr(ks, "search_kr", _fixed(KRSearch(2, _OHUI)))
    p = _product("오휘", "오휘 더퍼스트 제너츄어 립스틱", {"oliveyoung": "old", "naver": "n"})
    ks.prune_kr_oliveyoung([p])
    assert p.platform_links["oliveyoung"] == ks.kr_goods_url("A_LIP")
    assert "oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A_LIP" in p.platform_links["oliveyoung"]
    assert p.matched_platforms == ["naver", "oliveyoung"]


def test_prune_removes_button_when_verifiable_absent(monkeypatch):
    monkeypatch.setattr(ks, "search_kr", _fixed(KRSearch(0, ())))
    p = _product("없는브랜드", "없는 상품", {"oliveyoung": "old", "naver": "n"})
    ks.prune_kr_oliveyoung([p])
    assert "oliveyoung" not in p.platform_links
    assert p.matched_platforms == ["naver"]


def test_prune_removes_button_when_unverifiable(monkeypatch):
    # 정책: 네트워크 오류/429로 검증 불가면 버튼을 '유지'가 아니라 '제거'한다.
    # 잠정 검색 링크를 남기면 실제로 미취급인 상품에도 버튼이 붙는 오탐이 생기기 때문.
    monkeypatch.setattr(ks, "search_kr", lambda query: None)
    p = _product("오휘", "오휘 더퍼스트 립스틱", {"oliveyoung": "old", "naver": "n"})
    ks.prune_kr_oliveyoung([p])
    assert "oliveyoung" not in p.platform_links
    assert p.platform_links == {"naver": "n"}


def test_prune_skips_products_without_oliveyoung(monkeypatch):
    called = {"n": 0}
    def _spy(query):
        called["n"] += 1
        return KRSearch(0, ())
    monkeypatch.setattr(ks, "search_kr", _spy)
    p = _product("Brand", "Product", {"naver": "n"})
    ks.prune_kr_oliveyoung([p])
    assert called["n"] == 0 and p.platform_links == {"naver": "n"}


# ── 로컬 KR 카탈로그(배치 크롤) ──────────────────────────────────────────

_CAT_ROWS = [
    ("A_ZV", "롬앤", "롬앤 제로 벨벳 틴트", "N"),
    ("A_GW", "롬앤", "롬앤 글래스팅 워터 틴트", "N"),
    ("A_OOS", "롬앤", "롬앤 제로 매트 립스틱", "Y"),
]


def test_kr_catalog_unavailable_when_csv_missing(monkeypatch, tmp_path):
    assert ks.kr_catalog_available() is False  # autouse 픽스처가 빈 경로로 지정
    assert ks.match_kr_catalog("롬앤", "롬앤 제로 벨벳 틴트") is None


def test_kr_catalog_matches_correct_line(monkeypatch, tmp_path):
    _use_kr_catalog(monkeypatch, tmp_path, _CAT_ROWS)
    assert ks.kr_catalog_available() is True
    m = ks.match_kr_catalog("롬앤", "롬앤 제로 벨벳 틴트")
    assert m is not None and m.goods_no == "A_ZV"


def test_kr_catalog_skips_soldout(monkeypatch, tmp_path):
    _use_kr_catalog(monkeypatch, tmp_path, _CAT_ROWS)
    assert ks.match_kr_catalog("롬앤", "롬앤 제로 매트 립스틱") is None


def test_resolve_prefers_catalog_without_live_call(monkeypatch, tmp_path):
    _use_kr_catalog(monkeypatch, tmp_path, _CAT_ROWS)
    called = {"n": 0}
    def _spy(query):
        called["n"] += 1
        return KRSearch(0, ())
    monkeypatch.setattr(ks, "search_kr", _spy)
    match, verifiable = ks.resolve_kr_goods("롬앤", "롬앤 제로 벨벳 틴트")
    assert match is not None and match.goods_no == "A_ZV"
    assert verifiable is True
    assert called["n"] == 0  # 카탈로그 매칭 시 라이브 호출 안 함


def test_resolve_falls_back_to_live_on_catalog_miss(monkeypatch, tmp_path):
    _use_kr_catalog(monkeypatch, tmp_path, _CAT_ROWS)
    # 카탈로그에 없는 상품 → 라이브 검색으로 폴백해 찾는다.
    live = (KRResult("A_LIVE", "클리오", "클리오 킬커버 파운데이션", False),)
    monkeypatch.setattr(ks, "search_kr", _fixed(KRSearch(1, live)))
    match, verifiable = ks.resolve_kr_goods("클리오", "클리오 킬커버 파운데이션")
    assert match is not None and match.goods_no == "A_LIVE"
