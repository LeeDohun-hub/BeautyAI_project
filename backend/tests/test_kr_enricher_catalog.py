"""KR 한글화 — 로컬 카탈로그 경로.

네이버 쇼핑 검색이 2026-07-31 종료되면서 한글화가 통째로 죽었다(200 OK + 빈 결과라
예외도 안 났다). 올리브영 글로벌 카탈로그에 영문명·한글명이 함께 있어서 그걸로 대신한다.
네트워크를 타지 않고 오탐도 없다(카탈로그가 출처).
"""

from __future__ import annotations

import re

import pytest

from app.services import naver_kr_enricher as enr

HANGUL = re.compile(r"[가-힣]")


class Card:
    """enricher 가 만지는 최소 인터페이스."""

    def __init__(self, brand: str, name: str) -> None:
        self.brand = brand
        self.name = name
        self.product_url = "https://example.test/original"
        self.image_url = "https://example.test/img.jpg"
        self.source = "beautyai_db"
        self.platform_links: dict[str, str] = {}


def _catalog_ready() -> bool:
    from app.services.oliveyoung_catalog import catalog_available

    return catalog_available()


def test_already_korean_is_left_alone() -> None:
    card = Card("라운드랩", "라운드랩 자작나무 수분크림")
    assert enr._enrich_one_from_catalog(card) is False
    assert card.name == "라운드랩 자작나무 수분크림"


def test_unknown_product_is_not_touched() -> None:
    card = Card("NoSuchBrandXYZ", "Totally Made Up Product 9999")
    assert enr._enrich_one_from_catalog(card) is False
    assert card.name == "Totally Made Up Product 9999"


def test_catalog_match_localizes_name_and_brand() -> None:
    if not _catalog_ready():
        pytest.skip("올리브영 글로벌 카탈로그가 없는 환경(런타임 번들 미포함)")

    from app.services.oliveyoung_catalog import catalog_items

    # 카탈로그에서 한글명을 가진 실제 상품을 하나 골라 그 영문명으로 보강해 본다.
    sample = next(
        (i for i in catalog_items() if HANGUL.search(i.name_kr or "") and (i.name_en or "").strip()),
        None,
    )
    if sample is None:
        pytest.skip("한글명을 가진 카탈로그 상품이 없다")

    card = Card(sample.brand, sample.name_en)
    assert enr._enrich_one_from_catalog(card) is True
    assert HANGUL.search(card.name), f"한글화 실패: {card.name!r}"


def test_links_and_images_are_not_overwritten() -> None:
    """링크·이미지는 뒤따르는 resolve/이미지 캐스케이드의 몫이다.

    여기서 글로벌몰 URL 을 박으면 KR 카드가 글로벌몰로 가버리고, 올리브영 이미지는
    미리보기에서 배제하기로 한 정책과 충돌한다.
    """
    if not _catalog_ready():
        pytest.skip("올리브영 글로벌 카탈로그가 없는 환경")

    from app.services.oliveyoung_catalog import catalog_items

    sample = next(
        (i for i in catalog_items() if HANGUL.search(i.name_kr or "") and (i.name_en or "").strip()),
        None,
    )
    if sample is None:
        pytest.skip("한글명을 가진 카탈로그 상품이 없다")

    card = Card(sample.brand, sample.name_en)
    enr._enrich_one_from_catalog(card)
    assert card.product_url == "https://example.test/original"
    assert card.image_url == "https://example.test/img.jpg"


def test_enrich_runs_without_naver_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """자격증명이 없어도 카탈로그 경로는 돌아야 한다.

    예전 구현은 맨 앞에서 `if not client.configured: return 0` 으로 빠져나가, 네이버 키를
    비우는 순간 한글화가 0이 됐다.
    """
    monkeypatch.setattr(enr.NaverClient, "configured", property(lambda self: False))

    cards = [Card("라운드랩", "라운드랩 자작나무 수분크림"), Card("NoSuch", "Nope 123")]
    assert enr.enrich_products_with_naver_kr(cards) == 0  # 둘 다 대상 아님 — 예외 없이 끝나야 한다


def test_dead_naver_does_not_block_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """종료된 쇼핑 API 가 200 OK + 빈 결과를 줘도 카탈로그 보강은 살아 있어야 한다."""
    if not _catalog_ready():
        pytest.skip("올리브영 글로벌 카탈로그가 없는 환경")

    from app.services.oliveyoung_catalog import catalog_items

    sample = next(
        (i for i in catalog_items() if HANGUL.search(i.name_kr or "") and (i.name_en or "").strip()),
        None,
    )
    if sample is None:
        pytest.skip("한글명을 가진 카탈로그 상품이 없다")

    monkeypatch.setattr(enr.NaverClient, "configured", property(lambda self: True))
    monkeypatch.setattr(enr.NaverClient, "search", lambda self, q, hits=5: [])

    card = Card(sample.brand, sample.name_en)
    assert enr.enrich_products_with_naver_kr([card]) == 1
    assert HANGUL.search(card.name)
