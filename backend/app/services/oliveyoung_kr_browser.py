"""올리브영 국내몰(oliveyoung.co.kr) — 헤드풀 브라우저로 Cloudflare JS 챌린지 통과.

curl_cffi 의 TLS 지문 위조(impersonate="chrome")로 통과하던 국내몰이 2026-07 경 Cloudflare
Managed(JS) 챌린지로 승격돼, 도메인 전체가 403 을 준다(main.do 조차). TLS 지문만으론 못 넘고
JS 를 실행하는 '진짜 브라우저'가 있어야 챌린지가 자동 해제된다.

실측(probe): playwright + 시스템 Chrome 으로
  - headless=True  → 403 (챌린지 미해제, '잠시만 기다리십시오…' 에서 멈춤)
  - headless=False → 200, 정상 JSON (챌린지 자동 해제)
→ **반드시 헤드풀**이어야 한다. 그래서 이 모듈은 런타임 라이브 경로가 아니라, 오프라인
배치 크롤(scripts/crawl_oliveyoung_kr.py)이 fat 카탈로그를 만들 때 쓴다. 런타임은 그 카탈로그를
먼저 매칭하므로(catalog-first) Cloudflare 와 무관하게 goodsNo 직링크를 낸다.

playwright 미설치/브라우저 없음 환경에서도 앱이 죽지 않게 lazy import + None 폴백을 쓴다
(curl_cffi 폴백과 동일한 규약).
"""

from __future__ import annotations

import json
from urllib.parse import quote_plus

from app.services.oliveyoung_kr_search import KRSearch, _parse

_SEARCH_API = "https://www.oliveyoung.co.kr/store/search/NewMainSearchApi.do"
_SEARCH_MAIN = "https://www.oliveyoung.co.kr/store/search/getSearchMain.do?query="
_WARM_QUERY = "에스쁘아"  # 챌린지 워밍업용(결과 유무 무관, 아무 인기 쿼리면 됨)
_NAV_TIMEOUT_MS = 30000
_CHALLENGE_WAIT_MS = 4500  # CF 챌린지 자동 해제 대기
_FETCH_TIMEOUT_MS = 15000

def _decode_payload(body: str) -> dict | None:
    """NewMainSearchApi 응답을 dict 로 디코드.

    브라우저 fetch 로 받으면 content-type 이 text/plain 이고 본문이 **이중 인코딩된 JSON 문자열**
    (예: '"{\\"Parameter\\":...}"')로 온다(실측). 1차 json.loads 는 str 을 주므로 str 이면 한 번 더
    디코드한다. 방어적으로 최대 2회까지 푼다.
    """
    body = (body or "").strip()
    if not body:
        return None
    try:
        data = json.loads(body)
    except Exception:
        return None
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return None
    return data if isinstance(data, dict) else None


_API_JS = """
async ([base, query]) => {
  const url = base + '?query=' + encodeURIComponent(query) + '&pageIdx=1&rowsPerPage=24';
  const r = await fetch(url, {headers: {'x-requested-with': 'XMLHttpRequest'}, credentials: 'include'});
  return {status: r.status, body: await r.text()};
}
"""


class KRBrowserSession:
    """헤드풀 Chrome 세션. 한 번 챌린지를 풀면 컨텍스트를 재사용해 여러 쿼리를 in-page fetch 한다.

    with KRBrowserSession() as s:
        sr = s.search("클리오 킬커버")   # KRSearch | None

    curl_cffi 대비 느리지만(브라우저), 배치 크롤에서 한 번 워밍 후 쿠키를 재사용하므로 쿼리당
    비용은 fetch 1회다. 컨텍스트 매니저로 브라우저를 확실히 닫는다.
    """

    def __init__(self, headless: bool = False):
        # headless=False 가 기본. 헤드리스는 챌린지에 막힌다(실측). 오버라이드는 테스트/디버깅용.
        self._headless = headless
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None
        self._warm = False

    def __enter__(self) -> "KRBrowserSession":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> bool:
        """브라우저 기동 + 챌린지 워밍. 성공 True. playwright/Chrome 없으면 False(폴백)."""
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return False
        try:
            self._pw = sync_playwright().start()
            # channel="chrome": 시스템 Chrome 사용(chromium 다운로드 불필요, 봇 탐지에도 유리).
            self._browser = self._pw.chromium.launch(channel="chrome", headless=self._headless)
            self._ctx = self._browser.new_context(locale="ko-KR")
            self._page = self._ctx.new_page()
            return self._warm_up()
        except Exception:
            self.close()
            return False

    def _warm_up(self) -> bool:
        """검색 메인 페이지로 이동해 CF 챌린지를 자동 해제시킨다(200 확인)."""
        try:
            resp = self._page.goto(
                _SEARCH_MAIN + quote_plus(_WARM_QUERY),
                wait_until="domcontentloaded",
                timeout=_NAV_TIMEOUT_MS,
            )
            self._page.wait_for_timeout(_CHALLENGE_WAIT_MS)
            self._warm = bool(resp and resp.status == 200)
            return self._warm
        except Exception:
            self._warm = False
            return False

    def search(self, query: str) -> KRSearch | None:
        """국내몰 검색 결과(KRSearch). None=검증 불가(미기동/챌린지 재발/파싱 실패)."""
        query = (query or "").strip()
        if not query or self._page is None:
            return None
        if not self._warm and not self._warm_up():
            return None
        try:
            res = self._page.evaluate(_API_JS, [_SEARCH_API, query])
        except Exception:
            return None
        if res.get("status") != 200:
            # 챌린지 재발(403 HTML) 등 → 한 번 재워밍 후 1회 재시도.
            self._warm = False
            if not self._warm_up():
                return None
            try:
                res = self._page.evaluate(_API_JS, [_SEARCH_API, query])
            except Exception:
                return None
            if res.get("status") != 200:
                return None
        body = res.get("body") or ""
        payload = _decode_payload(body)
        if payload is None:
            return None
        try:
            return _parse(payload)
        except Exception:
            return None

    def close(self) -> None:
        for closer in (self._browser, self._pw):
            try:
                if closer is self._pw and closer is not None:
                    closer.stop()
                elif closer is not None:
                    closer.close()
            except Exception:
                pass
        self._pw = self._browser = self._ctx = self._page = None
        self._warm = False
