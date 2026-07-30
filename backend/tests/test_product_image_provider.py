"""상품 이미지 보강 회귀 테스트(2026-07-30 버그리포트: 카드 이미지가 다른 상품).

사용자 관측:
- 'medicube Red Clear Capsule Body Lotion 230ml' — 상품명·직링크는 맞는데 이미지가 다른 상품.
- 'Anua Heartleaf Silky Moisture Sun Cream' — 이미지가 선크림이 아니었다.
원인: (1) 올리브영 직링크 상품인데도 정답인 카탈로그 이미지를 버리고 검색으로 추측했고,
      (2) 긴 상품명이 0건이면 마지막에 '브랜드만' 질의해 1위 결과 이미지를 그대로 채택했다.
"""

from __future__ import annotations

from types import SimpleNamespace

import app.services.product_image_provider as pip


def setup_function() -> None:
    pip.clear_cache()


def teardown_function() -> None:
    pip.clear_cache()


def _item(brand: str, name: str, image_url: str = "", oy_url: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        brand=brand,
        name=name,
        image_url=image_url,
        platform_links=({"oliveyoung": oy_url} if oy_url else {}),
    )


_OY_DETAIL = "https://global.oliveyoung.com/product/detail?prdtNo=GA250430394"
_OY_IMAGE = "https://image.oliveyoung.com/prdtImg/1085/correct.png"


def _stub_cascade(monkeypatch, url: str) -> None:
    """지역 이미지 소스를 고정 URL 로 대체한다.

    ⚠ `naver_image` 를 monkeypatch 해도 안 먹는다 — `_PROVIDER_CASCADE` 가 임포트 시점에
    함수 **객체**를 담아두기 때문. 캐스케이드 자체를 갈아끼워야 실제 네트워크 호출이 없다.
    """
    monkeypatch.setitem(pip._PROVIDER_CASCADE, "kr", [lambda brand, name: url])


def test_keeps_oliveyoung_image_when_card_has_direct_link(monkeypatch):
    """직링크가 가리키는 상품의 카탈로그 이미지는 '추측'보다 정확하므로 유지한다."""
    monkeypatch.setattr(pip, "_is_live_image", lambda url: True)
    _stub_cascade(monkeypatch, "https://example.com/wrong.jpg")

    item = _item("medicube", "medicube Red Clear Capsule Body Lotion 230ml", _OY_IMAGE, _OY_DETAIL)
    pip.fill_missing_images([item], "kr")
    assert item.image_url == _OY_IMAGE


def test_replaces_oliveyoung_image_when_link_is_only_a_search(monkeypatch):
    """검색 링크는 어떤 상품이 열릴지 모른다 → 종전대로 지역 소스 이미지로 교체한다."""
    monkeypatch.setattr(pip, "_is_live_image", lambda url: True)
    _stub_cascade(monkeypatch, "https://example.com/naver.jpg")

    search_link = "https://global.oliveyoung.com/display/search?query=medicube"
    item = _item("medicube", "medicube Red Clear Capsule Body Lotion 230ml", _OY_IMAGE, search_link)
    pip.fill_missing_images([item], "kr")
    assert item.image_url == "https://example.com/naver.jpg"


def test_replaces_dead_oliveyoung_image_even_with_direct_link(monkeypatch):
    """죽은 이미지는 직링크 상품이라도 교체한다(올영 CDN 403/삭제 대응)."""
    monkeypatch.setattr(pip, "_is_live_image", lambda url: not url.startswith("https://image.oliveyoung.com"))
    _stub_cascade(monkeypatch, "https://example.com/live.jpg")

    item = _item("medicube", "medicube Red Clear Capsule Body Lotion 230ml", _OY_IMAGE, _OY_DETAIL)
    pip.fill_missing_images([item], "kr")
    assert item.image_url == "https://example.com/live.jpg"


def test_naver_image_rejects_different_product_form(monkeypatch):
    """선크림 카드에 토너 리스팅 이미지가 붙지 않아야 한다."""
    monkeypatch.setattr(pip, "get_settings", lambda: SimpleNamespace(
        naver_client_id="id", naver_client_secret="secret"))

    class _Resp:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict:
            return {"items": [
                {"title": "아누아 어성초 77 수딩 토너 250ml", "image": "https://example.com/toner.jpg"},
                {"title": "아누아 어성초 실키 모이스처 선크림 50ml", "image": "https://example.com/sun.jpg"},
            ]}

    monkeypatch.setattr(pip.httpx, "get", lambda *a, **k: _Resp())
    got = pip.naver_image("아누아", "아누아 어성초 실키 모이스처 선크림 50ml")
    assert got == "https://example.com/sun.jpg"


def test_naver_image_no_top_result_fallback_for_brand_only_query(monkeypatch):
    """브랜드만 남은 질의에서 1위 결과를 채택하면 같은 브랜드의 '아무 상품' 이미지가 붙는다.

    이게 medicube 바디로션 카드에 다른 메디큐브 상품 사진이 붙은 직접 원인이었다.
    """
    monkeypatch.setattr(pip, "get_settings", lambda: SimpleNamespace(
        naver_client_id="id", naver_client_secret="secret"))

    class _Resp:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict:
            # 브랜드/상품명 토큰이 전혀 겹치지 않는 결과(다른 상품).
            return {"items": [{"title": "전혀 다른 상품", "image": "https://example.com/other.jpg"}]}

    monkeypatch.setattr(pip.httpx, "get", lambda *a, **k: _Resp())
    assert pip.naver_image("medicube", "medicube") == ""
    # 상품 토큰이 있는 질의라면 종전처럼 1위 결과 폴백을 허용한다(한글명 브랜드 대응).
    assert pip.naver_image("medicube", "medicube red capsule body lotion") == "https://example.com/other.jpg"
