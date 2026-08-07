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
_GOODS_DETAIL = "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo="
# 상품 이미지 CDN. 삭제된 상품은 cf-static 의 기본 자리표시자를 주므로 호스트로 걸러낸다.
_GOODS_IMAGE_HOST = "https://image.oliveyoung.co.kr/"
# 내려간 상품 페이지의 제목(상품명 대신 몰 이름이 그대로 남는다).
_GENERIC_TITLE = "올리브영 온라인몰"
# og:image 가 채워졌는지 — 상품 썸네일이든 기본 자리표시자든, 값이 있으면 판정할 수 있다.
_DETAIL_READY_JS = """
() => {
  const m = document.querySelector('meta[property="og:image"]');
  return !!(m && m.content);
}
"""
_DETAIL_READY_MS = 8000
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

    def goods_detail(self, goods_no: str) -> tuple[str | None, bool | None]:
        """상품 상세 페이지에서 (대표 이미지 URL, 판매 중 여부)를 읽는다.

        검색 API 로는 못 채우는 상품이 남는다 — 한정기획·단종처럼 **이름으로 다시 검색해도
        안 나오는** 것들이다(실측 2026-08-07: 검색 기반 백필 뒤 100건). goodsNo 는 알고 있으니
        상세 페이지를 직접 연다.

        ⚠ 삭제된 상품도 HTTP 200 을 준다. 구분은 **og:image 의 호스트**로 한다 —
          살아 있으면 image.oliveyoung.co.kr 의 상품 썸네일, 내려갔으면 cf-static 의
          기본 자리표시자(img_oy_default)에 제목이 '올리브영 온라인몰'이다.

        ⚠ 본문의 '상품을 찾을 수 없어요' 로는 판정하면 안 된다. 이 문구는 SPA 셸에 숨어 있어서
          **멀쩡한 상품 페이지에서도 innerText 에 잡힌다**(실측 2026-08-07: 셀리맥스·힌스·
          마녀공장 등 정상 상품이 전부 '없음'으로 나왔고, 그 판정으로 6건을 잘못 내렸다가
          되돌렸다). 표시가 아니라 **이미지 출처**가 진짜 신호다.

        반환의 두 번째 값은 **3-상태**다:
            True  = 상품 썸네일이 있다(판매 중)
            False = 기본 자리표시자 + 일반 제목(삭제·단종 확정)
            None  = 모름(네트워크·챌린지 실패, 렌더 지연 등)
        ⚠ 실패를 False 로 뭉뚱그리면 멀쩡한 상품이 죽은 것으로 표시된다. 호출부가
          False 일 때만 카탈로그에서 내리도록 셋을 구분한다.
        """
        goods_no = (goods_no or "").strip()
        if not goods_no or self._page is None:
            return None, None
        if not self._warm and not self._warm_up():
            return None, None
        try:
            self._page.goto(
                _GOODS_DETAIL + quote_plus(goods_no),
                wait_until="domcontentloaded",
                timeout=_NAV_TIMEOUT_MS,
            )
            # ⚠ 상세 페이지는 Next.js SPA 라 domcontentloaded 직후엔 og:image 가 아직 없다.
            #   그 시점에 읽으면 전부 '모름'이 된다. 메타가 채워질 때까지 기다린다
            #   (고정 sleep 보다 빠르고, 안 채워지면 타임아웃 뒤 한 번 더 읽어 본다).
            self._page.wait_for_function(_DETAIL_READY_JS, timeout=_DETAIL_READY_MS)
        except Exception:
            pass
        try:
            info = self._page.evaluate(
                "() => ({"
                "  image: (document.querySelector('meta[property=\"og:image\"]') || {}).content || '',"
                "  title: document.title || ''"
                "})"
            )
        except Exception:
            return None, None
        src = (info.get("image") or "").strip()
        if src.startswith(_GOODS_IMAGE_HOST) and "img_oy_default" not in src:
            return src, True
        # 기본 자리표시자 + 일반 제목이면 내려간 상품이다. 둘 중 하나만이면 판정하지 않는다.
        if "img_oy_default" in src and (info.get("title") or "").strip() == _GENERIC_TITLE:
            return None, False
        return None, None

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
