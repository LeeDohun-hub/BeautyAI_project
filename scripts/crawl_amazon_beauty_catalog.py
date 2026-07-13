"""Amazon 검색 크롤 → 지역별 Beauty ASIN 카탈로그(오프라인 빌드).

왜: Kaggle 데이터셋은 amazon.com(US)만이라 (1) 한/일 국내 뷰티 상품 커버리지 부족,
(2) JP 버튼은 US ASIN 재활용이라 amazon.co.jp에서 404 위험. 그래서 브랜드 시드로
amazon.co.jp / amazon.com 검색을 '오프라인에서 한 번' 크롤해, 각 마켓의 '진짜 ASIN'을
카탈로그로 만든다. 요청 시엔 이 카탈로그를 인메모리 매칭(검색 스크래핑 아님 → 안티봇/지연/
오탐 회피). 매칭은 기존 amazon_catalog 로직 재사용.

출력(loader 스키마 호환): data/manifests/amazon_beauty_{region}.csv
  컬럼: asin, brand, title, stars, reviews, imageUrl
  - region=jp → amazon.co.jp 검색 → JP ASIN (JP 버튼 amazon.co.jp/dp/{asin} 가 실재)
  - region=us → amazon.com  검색 → US ASIN (KR 버튼 amazon.com/dp/{asin})

정중함: 요청마다 랜덤 딜레이, UA 로테이션, 차단 시 백오프→브라우저 폴백→스킵. 재개 가능
(이미 크롤된 브랜드는 건너뜀). 브랜드당 검색 1페이지(~20~50개)만 → 저볼륨.

Usage:
  python scripts/crawl_amazon_beauty_catalog.py --region jp [--limit-brands N] [--delay 3]
  python scripts/crawl_amazon_beauty_catalog.py --region us
  python scripts/crawl_amazon_beauty_catalog.py --region jp --brands peripera espoir mentholatum
"""
from __future__ import annotations

import argparse
import csv
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

import httpx

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

FIELDNAMES = ["asin", "brand", "title", "stars", "reviews", "imageUrl"]

_REGION = {
    "jp": ("https://www.amazon.co.jp/s?k=", "ja,en-US;q=0.8"),
    "us": ("https://www.amazon.com/s?k=", "en-US,en;q=0.9"),
}

_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
]

_ASIN_RE = re.compile(r"[A-Z0-9]{10}")
_JUNK_TITLE = re.compile(
    r"その他の購入オプション|More Buying Choices|各商品詳細ページ|詳細ページを確認|^\s*$"
)
# 검색결과 카드 타이틀 앞에 붙는 광고 라벨 제거('Sponsored Ad - ', 'Sponsored ', 'スポンサー ').
_SPONSORED = re.compile(r"^\s*(sponsored(\s+ad)?\s*[-–:]?\s*|スポンサー\s*(プロダクト)?\s*)", re.I)


def _seed_brands() -> list[str]:
    """앱의 브랜드 지식을 시드로 재활용(K/J-beauty + 한글→영문 별칭). 영문/로마자 시드는
    amazon.co.jp/.com 양쪽에서 잘 걸린다(실측: 'espoir' 검색이 일본 리스팅 반환)."""
    from app.services.amazon_catalog import _KO_TO_EN_BRAND
    from app.services.recommender import JBEAUTY_BRANDS, KBEAUTY_BRANDS

    raw = set(KBEAUTY_BRANDS) | set(JBEAUTY_BRANDS) | set(_KO_TO_EN_BRAND.values())
    # 중복/변형 정리: 'rom&nd'/'romand', 'dr jart'/'dr.jart', 'manyo'/'ma:nyo' 등은 한쪽만.
    seen: set[str] = set()
    out: list[str] = []
    for b in sorted(raw):
        key = re.sub(r"[^a-z0-9]", "", b.lower())
        if key and key not in seen:
            seen.add(key)
            out.append(b)
    return out


# 스폰서(광고) 카드 마커. 브랜드 검색의 스폰서 결과는 '경쟁사 상품'이라(실측: espoir 검색의
# 스폰서 = JUNG SAEM MOOL/VDL/MEDIHEAL 등) 시드 브랜드로 태깅하면 오탐. 통째로 버린다.
_SPONSORED_CARD = re.compile(r"s-sponsored|AdHolder|Sponsored Ad|View Sponsored|puis-sponsored|スポンサー", re.I)


def _parse_search(html: str, seed_brand: str) -> list[dict]:
    """검색결과 HTML에서 (asin, title, image) 카드를 뽑는다.

    핵심: 아마존은 브랜드명을 상품 타이틀에 안 넣는 경우가 많다(실측: espoir 오가닉 결과
    'The Brow Balance Pencil #3 Soft Brown'에 'espoir' 문자열 없음). 그래서 타이틀-내-브랜드를
    요구하지 않고, 대신 **스폰서(경쟁사 광고) 카드만 버리고 오가닉 결과는 시드 브랜드로 신뢰**한다
    (브랜드 검색의 오가닉 relevance는 그 브랜드로 좁게 나옴 — 실측). 최종 오탐 방어는 다운스트림
    매처(브랜드 게이트 + 라인토큰 ≥2 겹침)가 담당한다."""
    cards = re.split(r'(?=data-asin=")', html)
    rows: list[dict] = []
    seen_asin: set[str] = set()
    for card in cards:
        m = re.match(r'data-asin="([A-Z0-9]{10})"', card)
        if not m:
            continue
        asin = m.group(1)
        if asin in seen_asin:
            continue
        if _SPONSORED_CARD.search(card):
            continue  # 경쟁사 광고 → 버림
        mt = re.search(r'<h2[^>]*aria-label="([^"]+)"', card)
        if not mt:
            mt = re.search(r"<h2[^>]*>.*?<span[^>]*>(.*?)</span>", card, re.S)
        if not mt:
            continue
        title = re.sub(r"<[^>]+>", "", mt.group(1)).strip()
        title = _SPONSORED.sub("", title).strip()
        if not title or _JUNK_TITLE.search(title):
            continue
        mi = re.search(r'<img[^>]+class="s-image"[^>]+src="([^"]+)"', card)
        image = mi.group(1) if mi else ""
        seen_asin.add(asin)
        rows.append({"asin": asin, "brand": seed_brand, "title": title[:300],
                     "stars": "", "reviews": "", "imageUrl": image})
    return rows


def _blocked(status: int, html: str) -> bool:
    if status != 200:
        return True
    low = html.lower()
    return ("api-services-support@amazon" in low or "enter the characters you see" in low
            or "captcha" in low or "ロボットではありません" in html)


def _fetch(url: str, lang: str, *, browser_fallback: bool = True) -> str | None:
    headers = {"User-Agent": random.choice(_UAS), "Accept-Language": lang,
               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    # 아마존은 IP를 stateful하게 차단하므로, 막히면 창(window)이 리셋되도록 길게 쿨다운한다
    # (장시간 무인 배치 기준). 그래도 안 풀리면 브라우저 폴백 → 최종 None(다음 실행 때 재개).
    for attempt in range(3):
        try:
            r = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
            if not _blocked(r.status_code, r.text):
                return r.text
            print(f"    blocked (HTTP {r.status_code}), cooldown...", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"    fetch err: {type(exc).__name__}", file=sys.stderr)
        time.sleep(30 * (attempt + 1) + random.uniform(0, 15))  # 30/60/90s 쿨다운
    if browser_fallback:
        return _browser_fetch(url)
    return None


def _browser_fetch(url: str) -> str | None:
    """차단 시 폴백: 시스템 Chrome(playwright)로 렌더. 미설치면 None."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(user_agent=random.choice(_UAS))
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            html = page.content()
            browser.close()
            return None if _blocked(200, html) else html
    except Exception as exc:  # noqa: BLE001
        print(f"    browser fallback err: {type(exc).__name__}", file=sys.stderr)
        return None


def _done_brands(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    done: set[str] = set()
    with out_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            b = (row.get("brand") or "").strip()
            if b:
                done.add(b)
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", required=True, choices=["jp", "us"])
    ap.add_argument("--brands", nargs="*", help="특정 브랜드만(기본: 앱 시드 전체)")
    ap.add_argument("--limit-brands", type=int, default=0, help="상위 N개 브랜드만(테스트용)")
    ap.add_argument("--delay", type=float, default=6.0, help="요청 간 기본 딜레이(초). 아마존은 "
                    "공격적으로 차단하므로 크게 잡는다(권장 6~12). 차단되면 백오프→스킵, 재실행 시 재개.")
    ap.add_argument("--out", default="")
    ap.add_argument("--fresh", action="store_true", help="기존 파일 무시하고 새로 시작")
    args = ap.parse_args()

    base, lang = _REGION[args.region]
    out_path = Path(args.out) if args.out else _ROOT / "data" / "manifests" / f"amazon_beauty_{args.region}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    brands = args.brands or _seed_brands()
    if args.limit_brands:
        brands = brands[: args.limit_brands]

    done = set() if args.fresh else _done_brands(out_path)
    mode = "w" if (args.fresh or not out_path.exists()) else "a"
    todo = [b for b in brands if b not in done]
    print(f"[{args.region}] 브랜드 {len(brands)}개 중 {len(todo)}개 크롤 예정 (완료 {len(done)}) -> {out_path}")

    total_rows = 0
    with out_path.open(mode, encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDNAMES)
        if mode == "w":
            writer.writeheader()
        for i, brand in enumerate(todo, 1):
            url = base + quote_plus(brand)
            html = _fetch(url, lang)
            if not html:
                print(f"  [{i}/{len(todo)}] {brand}: 차단/실패 → 스킵", file=sys.stderr)
                continue
            rows = _parse_search(html, brand)
            for row in rows:
                writer.writerow(row)
            out.flush()
            total_rows += len(rows)
            print(f"  [{i}/{len(todo)}] {brand}: {len(rows)}개")
            time.sleep(args.delay + random.uniform(0, 2))  # 정중한 딜레이

    print(f"완료: {total_rows}개 행 추가 -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
