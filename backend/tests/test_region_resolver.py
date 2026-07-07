from __future__ import annotations

from types import SimpleNamespace

from app.api.routes import _resolve_region


def _request(headers: dict[str, str]):
    return SimpleNamespace(headers=headers)


def test_explicit_region_wins_over_headers():
    request = _request({"cf-ipcountry": "JP", "accept-language": "ja-JP"})

    assert _resolve_region("kr", request, "jp") == "kr"


def test_region_auto_uses_cdn_country_header():
    assert _resolve_region("auto", _request({"cf-ipcountry": "KR"}), "jp") == "kr"
    assert _resolve_region("auto", _request({"x-vercel-ip-country": "JP"}), "kr") == "jp"


def test_region_auto_falls_back_to_accept_language():
    assert _resolve_region("auto", _request({"accept-language": "ja-JP,ja;q=0.9"}), "kr") == "jp"
    assert _resolve_region("auto", _request({"accept-language": "ko-KR,ko;q=0.9"}), "jp") == "kr"


def test_region_auto_uses_route_fallback_when_unknown():
    assert _resolve_region("auto", _request({"accept-language": "en-US,en;q=0.9"}), "kr") == "kr"
