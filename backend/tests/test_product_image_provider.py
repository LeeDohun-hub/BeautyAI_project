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
_OY_SEARCH = "https://global.oliveyoung.com/display/search?query=medicube"
_OY_IMAGE = "https://image.oliveyoung.com/prdtImg/1085/correct.png"


def _stub_cascade(monkeypatch, url: str) -> None:
    """지역 이미지 소스를 고정 URL 로 대체한다.

    ⚠ 개별 provider 를 monkeypatch 해도 안 먹는다 — `_PROVIDER_CASCADE` 가 임포트 시점에
    함수 **객체**를 담아두기 때문. 캐스케이드 자체를 갈아끼워야 실제 네트워크 호출이 없다.
    """
    monkeypatch.setitem(pip._PROVIDER_CASCADE, "kr", [lambda brand, name: url])


def test_keeps_live_oliveyoung_image(monkeypatch):
    """살아있는 올리브영 이미지는 유지한다 — 그 상품의 정답 사진이라 '추측'보다 정확하다."""
    monkeypatch.setattr(pip, "_is_live_image", lambda url: True)
    _stub_cascade(monkeypatch, "https://example.com/wrong.jpg")

    item = _item("medicube", "medicube Red Clear Capsule Body Lotion 230ml", _OY_IMAGE, _OY_DETAIL)
    pip.fill_missing_images([item], "kr")
    assert item.image_url == _OY_IMAGE


def test_keeps_oliveyoung_image_without_direct_link(monkeypatch):
    """올영 이미지 배제 해제(2026-08-03) 회귀 방어.

    예전엔 '올영 버튼이 검색 링크면 이미지도 못 믿는다'며 교체했는데, 이미지는 링크가 아니라
    **그 상품 행**에서 온 것이라 링크 종류와 무관하다. 배제의 전제였던 핫링크 차단·높은 사망률은
    실측으로 성립하지 않았다(cross-site Referer 로도 응답 동일, 실제 Chrome 렌더 24/24).
    """
    monkeypatch.setattr(pip, "_is_live_image", lambda url: True)
    _stub_cascade(monkeypatch, "https://example.com/other.jpg")

    item = _item("medicube", "medicube Red Clear Capsule Body Lotion 230ml", _OY_IMAGE, _OY_SEARCH)
    pip.fill_missing_images([item], "kr")
    assert item.image_url == _OY_IMAGE


def test_replaces_dead_oliveyoung_image(monkeypatch):
    """죽은 이미지는 교체한다 — 배제를 푼 뒤에도 판정 기준은 '살아있는가' 하나다."""
    monkeypatch.setattr(pip, "_is_live_image", lambda url: not url.startswith("https://image.oliveyoung.com"))
    _stub_cascade(monkeypatch, "https://example.com/live.jpg")

    item = _item("medicube", "medicube Red Clear Capsule Body Lotion 230ml", _OY_IMAGE, _OY_DETAIL)
    pip.fill_missing_images([item], "kr")
    assert item.image_url == "https://example.com/live.jpg"


def test_oliveyoung_images_are_still_http_verified(monkeypatch):
    """아마존과 달리 올영은 신뢰 호스트가 아니다(글로벌 CDN 사망률 2.4% 실측)."""
    calls: list[str] = []

    class _Stream:
        def __enter__(self):
            return SimpleNamespace(status_code=404, iter_bytes=lambda chunk_size=8: iter([b""]))

        def __exit__(self, *exc):
            return False

    def _stream(method, url, **kwargs):
        calls.append(url)
        return _Stream()

    monkeypatch.setattr(pip.httpx, "stream", _stream)
    assert pip._is_live_image(_OY_IMAGE) is False
    assert calls == [_OY_IMAGE]


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


# ── 아마존 카탈로그 이미지(KR 소스 교체, 2026-08-03) ──────────────────────────────
# 네이버 쇼핑 API 가 2026-07-31 종료되면서 KR 이미지 소스가 통째로 사라져 카드가 전부
# placeholder 가 됐다. 대체 소스는 아마존 Beauty 카탈로그의 imageUrl 이다.

_AMAZON_IMG = "https://m.media-amazon.com/images/I/71MXYsvfsVL._AC_UL320_.jpg"
_AMAZON_IMG_500 = "https://m.media-amazon.com/images/I/71MXYsvfsVL._SL500_.jpg"


def test_amazon_image_uses_button_match_and_card_size(monkeypatch):
    """카드 이미지는 아마존 **버튼과 같은 매칭**(match_for_region)의 사진을 쓴다."""
    seen: list[tuple[str, str, str]] = []

    def _match(brand, name, region, **kw):
        seen.append((brand, name, region))
        return SimpleNamespace(asin="B0X", title="t", image_url=_AMAZON_IMG, score=1.0)

    monkeypatch.setattr(pip, "match_for_region", _match)
    assert pip.amazon_image("CLIO", "CLIO Kill Cover Founwear Cushion") == _AMAZON_IMG_500
    assert pip.amazon_jp_image("CLIO", "クリオ キルカバー クッション") == _AMAZON_IMG_500
    assert [region for _, _, region in seen] == ["kr", "jp"]


def test_amazon_image_empty_when_no_match(monkeypatch):
    monkeypatch.setattr(pip, "match_for_region", lambda brand, name, region, **kw: None)
    assert pip.amazon_image("CLIO", "CLIO Kill Cover Founwear Cushion") == ""
    # 매칭돼도 카탈로그 행에 이미지가 없으면(JP ESCI 행) 빈 값.
    monkeypatch.setattr(
        pip,
        "match_for_region",
        lambda brand, name, region, **kw: SimpleNamespace(asin="B0X", title="t", image_url="", score=1.0),
    )
    assert pip.amazon_image("CLIO", "CLIO Kill Cover Founwear Cushion") == ""


def test_catalog_provider_never_gets_short_queries(monkeypatch):
    """카탈로그 매처에 짧은 질의를 주면 형제 상품(같은 브랜드 다른 라인)이 매칭된다.

    짧은 질의는 검색 API 0건을 피하려는 장치라 카탈로그에는 해가 될 뿐이다 —
    라인 토큰이 줄면 커버리지 분모가 작아져 문턱을 쉽게 넘고, 그렇게 붙은 사진은
    버튼이 여는 상품과 다른 상품이 된다.
    """
    monkeypatch.setattr(pip, "_is_live_image", lambda url: False)
    asked: list[str] = []

    def _provider(brand, name):
        asked.append(name)
        return ""

    _provider.full_name_only = True
    monkeypatch.setitem(pip._PROVIDER_CASCADE, "kr", [_provider])
    full = "CLIO Kill Cover Founwear Cushion 4 Ginger SPF50 15g"
    pip.fill_missing_images([_item("CLIO", full)], "kr")
    assert asked == [full]


def test_amazon_cdn_is_trusted_without_http_check(monkeypatch):
    """아마존 CDN 은 검증 없이 신뢰한다(핫링크 차단 없음 + 폐기 ASIN 도 이미지는 서빙).

    검증은 카드당 왕복을 더하고, 동시 검증에서 타임아웃으로 살아있는 이미지를 버렸다.
    """
    def _boom(*args, **kwargs):
        raise AssertionError("아마존 CDN URL 은 HTTP 확인을 하지 않아야 한다")

    monkeypatch.setattr(pip.httpx, "stream", _boom)
    assert pip._is_live_image(_AMAZON_IMG_500) is True
    assert pip._is_live_image("") is False


def test_existing_amazon_image_is_kept_and_resized(monkeypatch):
    """DB 시드에 이미 아마존 이미지가 있으면 교체하지 않고 크기만 카드 규격으로 맞춘다."""
    monkeypatch.setitem(pip._PROVIDER_CASCADE, "kr", [lambda brand, name: "https://example.com/other.jpg"])
    item = _item("CLIO", "CLIO Kill Cover Founwear Cushion", _AMAZON_IMG)
    pip.fill_missing_images([item], "kr")
    assert item.image_url == _AMAZON_IMG_500
