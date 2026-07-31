"""국내몰 브랜드 별칭 — 하드코딩 32종 + 카탈로그 자동생성.

배경: 2026-07-31 네이버 쇼핑 검색 종료로 `_kr_brand()` 의 (3)단계(네이버가 채워준 한글명에서
브랜드 추출)가 죽었다. 별칭 표에 없는 브랜드는 영문 그대로 국내몰(한글) 검색에 들어가
line_match_score 의 브랜드 매칭이 실패하고, 정상 상품까지 기각된다. 그래서 카탈로그에서
자동 생성한 별칭을 합쳐 커버리지를 넓혔다. 이 테스트가 그 경로를 지킨다.
"""

from __future__ import annotations

import pytest

from app.services.oliveyoung_kr_search import (
    _BRAND_ALIAS,
    _brand_alias_key,
    _catalog_brand_alias,
    _kr_brand,
)


def test_hangul_brand_passes_through() -> None:
    assert _kr_brand("라운드랩", "라운드랩 자작나무 토너") == "라운드랩"


@pytest.mark.parametrize(
    ("english", "korean"),
    [("rom&nd", "롬앤"), ("peripera", "페리페라"), ("CLIO", "클리오"), ("Anua", "아누아")],
)
def test_hardcoded_alias_still_wins(english: str, korean: str) -> None:
    """손으로 검수한 표가 자동생성보다 우선이어야 한다."""
    assert _kr_brand(english, "") == korean


def test_catalog_alias_extends_coverage() -> None:
    """카탈로그 자동생성이 하드코딩보다 넓어야 한다(없으면 이 기능의 의미가 없다)."""
    catalog = _catalog_brand_alias()
    if not catalog:
        pytest.skip("올리브영 글로벌 카탈로그가 없는 환경(런타임 번들 미포함)")

    assert len(catalog) >= 50, f"자동 생성 별칭이 너무 적다: {len(catalog)}종"
    # 하드코딩에 없던 브랜드가 실제로 채워져야 한다.
    new_keys = set(catalog) - set(_BRAND_ALIAS)
    assert new_keys, "자동 생성이 하드코딩과 완전히 겹친다 — 넓히는 효과가 없다"


def test_catalog_alias_values_are_korean() -> None:
    """영문/기호가 브랜드로 굳으면 국내몰 검색이 오히려 나빠진다."""
    catalog = _catalog_brand_alias()
    if not catalog:
        pytest.skip("올리브영 글로벌 카탈로그가 없는 환경")

    import re

    hangul = re.compile(r"[가-힣]")
    for key, value in catalog.items():
        assert hangul.search(value), f"{key} → {value!r} 에 한글이 없다"


def test_unknown_brand_falls_back_to_hangul_token() -> None:
    """별칭에 없으면 이름에서 한글 토큰을 줍는 기존 폴백이 살아 있어야 한다."""
    assert _kr_brand("SomeUnknownBrandXYZ", "무명 브랜드 토너") == "무명"


def test_unknown_brand_without_hangul_keeps_english() -> None:
    assert _kr_brand("SomeUnknownBrandXYZ", "Plain English Toner") == "SomeUnknownBrandXYZ"


def test_alias_key_normalizes_punctuation() -> None:
    """'rom&nd' 와 'romnd' 가 같은 키여야 표가 갈라지지 않는다."""
    assert _brand_alias_key("rom&nd") == _brand_alias_key("romnd") == "romnd"
    assert _brand_alias_key("Dr.Jart+") == "drjart"
