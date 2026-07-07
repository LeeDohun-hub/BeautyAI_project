"""올리브영 로컬 카탈로그 매처 테스트.

임시 CSV를 _catalog_path 로 주입해(monkeypatch) 실제 크롤 데이터 없이 검증한다.
"""

from __future__ import annotations

import csv
from pathlib import Path

import app.services.oliveyoung_catalog as oc


def setup_function() -> None:
    oc.clear_cache()


def teardown_function() -> None:
    # 픽스처 CSV가 lru_cache에 남아 다른 테스트(platform_resolver 레거시 경로)를 오염시키지
    # 않도록 캐시를 비운다. 이후 _load_items는 실제(없는) 경로를 읽어 빈 카탈로그가 된다.
    oc.clear_cache()


_HEADER = [
    "prdtNo", "prdtNameEn", "brandName", "korPrdtName", "gdsCd", "sellStatCode", "stockQty",
]

# 같은 브랜드(OHUI)에 라인이 다른 두 상품 + 재고 0(품절) 상품. '더퍼스트 립스틱' 질의가
# '포맨 로션'으로 새지 않아야 한다(오탐 차단이 이 방식의 핵심).
_ROWS = [
    ("GA_LIP", "The First Geniture Lipstick", "OHUI", "오휘 더퍼스트 제너츄어 립스틱", "8801234000001", "10", "47"),
    ("GA_MEN", "The First Geniture For Men Lotion", "OHUI", "오휘 더퍼스트 제너츄어 포맨 로션", "8801234000002", "10", "12"),
    ("GA_OOS", "Cicapair Tiger Grass Cream", "Dr.Jart+", "시카페어 타이거 그라스 크림", "8801234000003", "10", "0"),
    # 같은 브랜드 + 같은 제품군어(틴트)지만 라인이 다른 상품(오탐 회귀용).
    ("GA_JT", "Juicy Liar Water Tint", "LILYBYRED", "릴리바이레드 쥬시 라이어 워터 틴트", "8801234000004", "10", "20"),
]


def _write_catalog(tmp_path: Path) -> Path:
    path = tmp_path / "oliveyoung_global_products.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_HEADER)
        writer.writerows(_ROWS)
    return path


def _use_catalog(monkeypatch, path: Path) -> None:
    monkeypatch.setattr(oc, "_catalog_path", lambda: path)
    oc.clear_cache()


def test_catalog_unavailable_when_csv_missing(monkeypatch, tmp_path):
    _use_catalog(monkeypatch, tmp_path / "does_not_exist.csv")
    assert oc.catalog_available() is False
    assert oc.match_oliveyoung("OHUI", "The First Geniture Lipstick") is None


def test_exact_line_matches_and_returns_prdt_no(monkeypatch, tmp_path):
    _use_catalog(monkeypatch, _write_catalog(tmp_path))
    assert oc.catalog_available() is True
    match = oc.match_oliveyoung("OHUI", "The First Geniture Lipstick")
    assert match is not None
    assert match.prdt_no == "GA_LIP"
    assert match.gds_cd == "8801234000001"


def test_korean_identity_matches_via_name_kr(monkeypatch, tmp_path):
    # 네이버 한글 보강 후(한글 브랜드/상품명)에도 korPrdtName 토큰으로 매칭된다.
    _use_catalog(monkeypatch, _write_catalog(tmp_path))
    match = oc.match_oliveyoung("오휘", "오휘 더퍼스트 제너츄어 립스틱")
    assert match is not None
    assert match.prdt_no == "GA_LIP"


def test_different_line_does_not_cross_match(monkeypatch, tmp_path):
    # '더퍼스트 립스틱' 질의는 립스틱(GA_LIP)에 걸려야지 '포맨 로션'(GA_MEN)으로 새면 안 된다.
    _use_catalog(monkeypatch, _write_catalog(tmp_path))
    match = oc.match_oliveyoung("OHUI", "The First Geniture Lipstick")
    assert match is not None and match.prdt_no != "GA_MEN"


def test_soldout_rows_are_excluded(monkeypatch, tmp_path):
    # 재고 0(품절) 상품은 인덱스에서 빠져 매칭되지 않는다(죽은 링크 방지).
    _use_catalog(monkeypatch, _write_catalog(tmp_path))
    assert oc.match_oliveyoung("Dr.Jart+", "Cicapair Tiger Grass Cream") is None


def test_unrelated_product_returns_none(monkeypatch, tmp_path):
    _use_catalog(monkeypatch, _write_catalog(tmp_path))
    assert oc.match_oliveyoung("CeraVe", "Moisturizing Cream For Dry Skin") is None


def test_same_brand_different_line_not_cross_matched(monkeypatch, tmp_path):
    # 카탈로그엔 '쥬시 라이어 워터 틴트'만 있고 '글로우 래스팅 워터 틴트'는 없다. 브랜드+제품군어
    # (틴트)만 겹친다고 엉뚱한 라인에 직링크가 붙으면 안 된다(브랜드 이중계상 오탐 회귀).
    _use_catalog(monkeypatch, _write_catalog(tmp_path))
    assert oc.match_oliveyoung("릴리바이레드", "릴리바이레드 글로우 래스팅 워터 틴트") is None
    # 실제로 있는 라인은 정상 매칭.
    got = oc.match_oliveyoung("릴리바이레드", "릴리바이레드 쥬시 라이어 워터 틴트")
    assert got is not None and got.prdt_no == "GA_JT"
