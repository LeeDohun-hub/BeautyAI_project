"""아마존 ASIN 생존 검증 → 죽은 ASIN 블록리스트.

왜: Kaggle/HF(McAuley 2023) 카탈로그엔 이미 폐기된 ASIN이 많아(실측 매칭 표본의 ~45%),
그 dp 링크가 amazon "Page Not Found"(404)로 열린다. 사용자 원칙: 에러페이지 열리는 버튼은
내지 않는다. 검색(/s)은 amazon이 차단하지만 **상품페이지(/dp)는 접근 가능**(실측)하므로,
오프라인에서 /dp 를 HTTP 확인해 404를 블록리스트에 적는다. match_amazon 은 블록리스트 ASIN을
건너뛰고 살아있는 차선을 고른다.

상태 파일(재개용): data/manifests/amazon_asin_status.json  {asin: "ok"|"dead"}
블록리스트(매처가 읽음): data/manifests/amazon_dead_asins.txt

Usage:
  # 특정 브랜드의 카탈로그 ASIN 전부 검증(리포트된 버그 브랜드 우선 처리에 적합)
  python scripts/verify_amazon_asins.py --brands "bobbi brown" hera missha anessa curel
  # US 카탈로그 전체(느림, 재개형) / 명시 ASIN
  python scripts/verify_amazon_asins.py --catalog us
  python scripts/verify_amazon_asins.py --asins B008UBTCMI B0716YQJC2
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

_MANIFEST_DIR = _ROOT / "data" / "manifests"
_STATUS_PATH = _MANIFEST_DIR / "amazon_asin_status.json"
_DEAD_PATH = _MANIFEST_DIR / "amazon_dead_asins.txt"

_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]
_DEAD_MARKERS = ("page not found", "looking for something", "the web address you entered is not")

# ⚠ 이 헤더 세트가 없으면 아마존이 3.7KB 짜리 봇 차단 페이지를 200 으로 돌려준다(실측). 그러면
# _check 가 전부 "unknown" 이 되어 블록리스트가 자라지 못하고, 죽은 ASIN(HF 카탈로그 실측
# 48.5%)이 그대로 버튼으로 나간다 — 사용자가 본 "Sorry! We couldn't find that page"의 원인.
# Sec-Fetch-* + br 인코딩 + 최신 Chrome UA 를 함께 보내면 실 페이지(200/404)가 온다.
_BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def _load_status() -> dict[str, str]:
    if _STATUS_PATH.exists():
        try:
            return json.loads(_STATUS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save(status: dict[str, str]) -> None:
    _STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    dead = sorted(a for a, s in status.items() if s == "dead")
    _DEAD_PATH.write_text("# amazon.com/dp 404(죽은 링크) ASIN. verify_amazon_asins.py 생성.\n"
                          + "\n".join(dead) + "\n", encoding="utf-8")


def _warm_cookies(region: str = "us") -> dict[str, str]:
    """헤드풀 Chrome 으로 'Continue shopping' 인터스티셜을 통과하고 쿠키를 얻는다.

    요청을 많이 보낸 IP 에는 아마존이 도메인 전체에 인터스티셜을 세운다(홈페이지도 200/3.7KB,
    본문은 "Click the button below to continue shopping"). 이 상태에서는 헤더를 어떻게 맞춰도,
    curl_cffi 로 TLS 지문을 위조해도 통과하지 못한다(실측: httpx·curl_cffi(chrome124/120/
    safari17)·헤드리스 브라우저 전부 차단 페이지).

    버튼을 실제로 누르면 세션 쿠키가 발급되고, 그 쿠키를 httpx 에 넘기면 이후 요청은 정상
    200/404 를 받는다(실측). 그래서 브라우저는 '워밍업 1회'에만 쓰고 본 검증은 빠른 HTTP 로 한다
    — oliveyoung_kr_browser 의 KRBrowserSession 과 같은 전략이다.

    playwright/Chrome 이 없으면 빈 dict 를 반환한다(쿠키 없이 진행 → 대개 unknown 이 되고
    아래 경고가 뜬다).
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("playwright 없음 — 쿠키 워밍업을 건너뜁니다(차단 시 unknown 이 됩니다)")
        return {}
    host = "www.amazon.co.jp" if region == "jp" else "www.amazon.com"
    domain = host.split("www.")[-1]
    probe = f"https://{host}/dp/{_WARM_ASIN}"
    jar: dict[str, str] = {}
    try:
        with sync_playwright() as pw:
            # channel="chrome": 시스템 Chrome(다운로드 불필요). headless 는 인터스티셜에 막힌다.
            browser = pw.chromium.launch(channel="chrome", headless=False)
            try:
                ctx = browser.new_context(locale="en-US")
                page = ctx.new_page()
                # 인터스티셜은 한 번에 안 걷힐 수 있다. 통과 토큰(x-amz-captcha-*)이 붙을 때까지 반복.
                for _ in range(3):
                    page.goto(probe, wait_until="domcontentloaded", timeout=45000)
                    button = page.locator(
                        'button:has-text("Continue shopping"), input[type=submit][value*="Continue"]'
                    ).first
                    if button.count():
                        button.click(timeout=8000)
                        page.wait_for_timeout(2500)
                    jar = {
                        c["name"]: c["value"]
                        for c in ctx.cookies()
                        if c["domain"].lstrip(".").endswith(domain)
                    }
                    if any(name.startswith("x-amz-captcha") for name in jar):
                        break
                    page.wait_for_timeout(1500)
            finally:
                browser.close()
    except Exception as exc:
        print(f"쿠키 워밍업 실패({type(exc).__name__}) — 쿠키 없이 진행합니다")
        return {}
    has_token = any(name.startswith("x-amz-captcha") for name in jar)
    print(f"쿠키 워밍업 완료: {len(jar)}개 (통과토큰 {'있음' if has_token else '없음'})")
    return jar


# 워밍업/검증용으로 쓰는 '살아있는 것이 확인된' ASIN(Bobbi Brown 립스틱).
_WARM_ASIN = "B078SHTQXM"


_COOKIES: dict[str, str] = {}


def _check(asin: str, region: str = "us") -> str:
    """amazon 상품페이지를 확인. 'ok' | 'dead' | 'unknown'(차단/에러: 재시도 여지 남김)."""
    host = "www.amazon.co.jp" if region == "jp" else "www.amazon.com"
    url = f"https://{host}/dp/{asin}"
    try:
        r = httpx.get(url, headers={"User-Agent": random.choice(_UAS), **_BASE_HEADERS},
                      cookies=_COOKIES or None, timeout=20, follow_redirects=True)
    except Exception:
        return "unknown"
    low = r.text.lower()
    if r.status_code == 404 or any(m in low for m in _DEAD_MARKERS):
        return "dead"
    if r.status_code == 200 and ("api-services-support@amazon" in low or "captcha" in low) and len(r.text) < 6000:
        return "unknown"  # 봇 차단 페이지 → 판정 보류
    if r.status_code == 200:
        return "ok"
    return "unknown"


def _source_of_asins(filenames: tuple[str, ...]) -> set[str]:
    """지정한 카탈로그 CSV 들에 들어있는 ASIN 집합(소스별 검증용)."""
    out: set[str] = set()
    for name in filenames:
        path = _MANIFEST_DIR / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", errors="ignore", newline="") as fh:
            for row in csv.DictReader(fh):
                asin = (row.get("asin") or "").strip()
                if asin:
                    out.add(asin)
    return out


_SERVED_PATH = _MANIFEST_DIR / "amazon_served_asins.txt"


def _collect_asins(args) -> list[str]:
    if args.asins:
        return list(dict.fromkeys(args.asins))
    if args.served:
        # '실제로 추천에 뜨는 ASIN'만 검증한다(생성: scripts/build_amazon_served_asins.py).
        # HF 카탈로그 11,593건 전수 검증은 몇 시간 걸리는데, 그중 실제로 버튼이 되는 건 643건뿐이다.
        if not _SERVED_PATH.exists():
            print(f"없음: {_SERVED_PATH} — build_amazon_served_asins.py 를 먼저 실행하세요")
            return []
        return [a for a in _SERVED_PATH.read_text(encoding="utf-8").split() if a]
    from app.services import amazon_catalog as ac
    region = "jp" if args.catalog == "jp" else "us"
    items = list(ac._load_items(region))
    if args.brands:
        keys = [re.sub(r"[^a-z0-9]", "", b.lower()) for b in args.brands]
        items = [it for it in items if any(k in re.sub(r"[^a-z0-9]", "", it.brand_key) for k in keys)]
    if args.source:
        # 소스별 검증. HF(McAuley 2023)는 실측 사망률 48.5% 인데 전체 매칭의 80% 를 차지해,
        # 여기만 먼저 검증해도 죽은 버튼이 대부분 사라진다(amazon_catalog._TRUSTED_SOURCES 참고).
        allowed = _source_of_asins(tuple(args.source))
        items = [it for it in items if it.asin in allowed]
    # 리뷰수 많은(=추천에 뜰 확률 높은 대표) 상품부터 검증 → 부분 실행으로도 노출 버튼을 먼저 커버.
    items.sort(key=lambda it: it.reviews, reverse=True)
    return list(dict.fromkeys(it.asin for it in items))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", choices=["us", "jp"], default="us")
    ap.add_argument("--brands", nargs="*", help="이 브랜드들의 카탈로그 ASIN만 검증")
    ap.add_argument("--asins", nargs="*", help="명시 ASIN 목록")
    ap.add_argument("--source", nargs="*", help="이 카탈로그 CSV 에 있는 ASIN 만 검증(예: amazon_beauty_hf.csv)")
    ap.add_argument("--served", action="store_true", help="추천에 실제로 뜨는 ASIN만 검증(amazon_served_asins.txt)")
    ap.add_argument("--limit", type=int, default=0, help="최대 검증 개수(0=전부)")
    ap.add_argument("--workers", type=int, default=4, help="동시 요청 수(과하면 차단됨)")
    ap.add_argument("--delay", type=float, default=0.4, help="워커별 요청 간 딜레이(초)")
    ap.add_argument("--recheck", action="store_true", help="이미 판정된 ASIN도 다시 확인")
    ap.add_argument("--no-warm", action="store_true", help="브라우저 쿠키 워밍업 생략")
    args = ap.parse_args()

    _MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    status = _load_status()
    asins = _collect_asins(args)
    todo = [a for a in asins if args.recheck or a not in status]
    if args.limit:
        todo = todo[: args.limit]
    print(f"검증 대상 {len(asins)}개 중 {len(todo)}개 확인 (기존 판정 {len(status)}개)", flush=True)

    region = "jp" if args.catalog == "jp" else "us"
    if todo and not args.no_warm:
        global _COOKIES
        # 워밍업이 '실제로 통했는지' 살아있는 ASIN 으로 확인하고, 실패하면 다시 시도한다.
        # 확인 없이 진행하면 전 건이 unknown 으로 흘러가 아무것도 판정하지 못한 채 끝난다.
        for attempt in range(1, 4):
            _COOKIES = _warm_cookies(region)
            if _check(_WARM_ASIN, region) == "ok":
                break
            print(f"  워밍업 확인 실패({attempt}/3) — 재시도")
            time.sleep(5)
        else:
            print("워밍업이 끝내 통하지 않았습니다. 잠시 뒤 다시 실행하세요.")
            return 1
    counts = {"ok": 0, "dead": 0, "unknown": 0}
    lock = threading.Lock()
    done = 0

    def work(asin: str) -> None:
        nonlocal done
        res = _check(asin, region)
        time.sleep(args.delay + random.uniform(0, 0.4))
        with lock:
            if res != "unknown":
                status[asin] = res
            counts[res] += 1
            done += 1
            if done % 25 == 0:
                _save(status)
                print(f"  [{done}/{len(todo)}] ok {counts['ok']} / dead {counts['dead']} / unknown {counts['unknown']}", flush=True)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        list(pool.map(work, todo))
    _save(status)
    print(f"완료: ok {counts['ok']}, dead {counts['dead']}, unknown {counts['unknown']} "
          f"-> {_DEAD_PATH.name} ({sum(1 for s in status.values() if s == 'dead')} dead total)")

    # ⚠ '조용한 실패'를 큰 소리로 알린다. 이 검증기는 아마존 봇 차단 페이지를 200 으로 받아
    # 전부 unknown 으로 떨어뜨리면서도 정상 종료했고, 그 바람에 블록리스트가 몇 주 동안 자라지
    # 못해 죽은 링크가 계속 사용자에게 나갔다(2026-07-30 규명). unknown 비율이 높으면 실패다.
    if todo and counts["unknown"] / len(todo) > 0.3:
        print(
            f"\n⚠️ 경고: {counts['unknown']}/{len(todo)} 건이 판정 불가(unknown)입니다.\n"
            "   아마존이 이 IP 를 차단/스로틀 중일 가능성이 큽니다(요청을 많이 보낸 직후에 발생).\n"
            "   → 몇 시간 뒤 --workers 2 --delay 2 로 다시 돌리세요. 지금 결과는 '검증 완료'가 아닙니다."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
