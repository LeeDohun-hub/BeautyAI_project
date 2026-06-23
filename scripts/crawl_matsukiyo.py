"""Crawl skincare products from Matsukiyo Cocokara online store.

The storefront is Magento (Adobe Commerce) behind Akamai Bot Manager. Two hard
constraints discovered while building this:

  1. Akamai tarpits Playwright's *bundled* Chromium. You MUST launch the locally
     installed Google Chrome via ``channel="chrome"`` so the TLS/HTTP fingerprint
     looks like a real browser.
  2. The site is JP-only and Akamai throttles bursts. Run from a Japanese egress
     IP and keep the pacing slow (a warm-up visit + several seconds between page
     loads). Hammering it trips ``ERR_HTTP2_PROTOCOL_ERROR`` / an access-denied
     interstitial.

Product list pages render ~10 items server-side and paginate via an AJAX
"next page" button (``#rightPage110``); there are no numbered page links.

Usage (keep the Japanese proxy/VPN ON for the whole run):

    python scripts/crawl_matsukiyo.py --categories 004/02/05/01 004/07 --max-pages 20
    python scripts/crawl_matsukiyo.py --category-file data/manifests/mk_categories.txt

Output:
    data/manifests/matsukiyo_products.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import time
from pathlib import Path

# Windows JP console defaults to cp932 and chokes on em-dashes / Japanese output.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.matsukiyococokara-online.com"
CAT_URL = BASE + "/store/catalog/category/view/categories/"
SEARCH_URL = BASE + "/store/catalogsearch/result/"
HOME = BASE + "/store/"

# Default skincare keyword seeds (Japanese) used when no --categories/--queries given.
DEFAULT_QUERIES = [
    "化粧水", "美容液", "乳液", "保湿クリーム", "洗顔", "クレンジング",
    "日焼け止め", "シートマスク", "美白", "オールインワン", "アイクリーム", "角質ケア",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

FIELDNAMES = [
    "jan", "brandName", "prdtName", "category",
    "saleAmt", "currency", "reviewCount", "avgRating",
    "imageUrl", "productUrl",
]

# Heuristic price: prefer the tax-included (税込) amount.
PRICE_INCL = re.compile(r"([0-9,]+)\s*円（税込）")
PRICE_ANY = re.compile(r"([0-9,]+)\s*円")
REVIEW_CNT = re.compile(r"（\s*([0-9,]+)\s*）")


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def parse_price(prc_text: str) -> int:
    m = PRICE_INCL.search(prc_text) or PRICE_ANY.search(prc_text)
    if not m:
        return 0
    return int(m.group(1).replace(",", ""))


def split_brand(title: str) -> tuple[str, str]:
    """Best-effort brand/name split. Matsukiyo titles lead with the brand token(s)."""
    title = clean(title)
    if not title:
        return "Matsukiyo", title
    # Private-brand items lead with "matsukiyo" / "MKコスメ" etc.
    first = title.split(" ", 1)
    brand = first[0]
    name = first[1] if len(first) > 1 else title
    if brand.lower() in {"matsukiyo", "mk", "mkc"}:
        return "matsukiyo", name
    return brand, name


def extract_items(page: Page, category: str) -> list[dict]:
    rows: list[dict] = []
    for it in page.query_selector_all("a.select_item"):
        href = it.get_attribute("href") or ""
        jan_m = re.search(r"/product/view/id/(\d+)", href)
        if not jan_m:
            continue

        def field(suffix: str) -> str:
            el = it.query_selector(f"[class*='box_item{suffix}']")
            return clean(el.inner_text()) if el else ""

        title = field("--tit")
        if not title:
            continue
        brand, name = split_brand(title)
        prc = field("--prc")
        img = it.query_selector("img")
        image_url = ""
        if img:
            image_url = img.get_attribute("src") or img.get_attribute("data-src") or ""
        rvw = field("--rvw")
        rcnt = REVIEW_CNT.search(rvw)

        rows.append({
            "jan": jan_m.group(1),
            "brandName": brand,
            "prdtName": name,
            "category": category,
            "saleAmt": parse_price(prc),
            "currency": "JPY",
            "reviewCount": int(rcnt.group(1).replace(",", "")) if rcnt else 0,
            "avgRating": 0.0,
            "imageUrl": image_url,
            "productUrl": href,
        })
    return rows


def jan_set(page: Page) -> set[str]:
    hrefs = page.eval_on_selector_all(
        "a[href*='/product/view/id/']", "es=>es.map(e=>e.href)")
    return {m.group(1) for h in hrefs if (m := re.search(r"/id/(\d+)", h))}


def next_enabled(page: Page):
    """Return the enabled 'next page' anchor, else None.

    Works for both category pages (anchor wrapped in ``li.is_pagerlist-next``)
    and search-result pages (bare ``a#rightPage110``). Disabled state is marked
    by an ``is_btnlink-disable`` class on the anchor or an ancestor.
    """
    nxt = page.query_selector("a#rightPage110")
    if not nxt:
        return None
    disabled = nxt.evaluate(
        "el => !!el.closest('.is_btnlink-disable') "
        "|| (el.className || '').includes('is_btnlink-disable')")
    return None if disabled else nxt


MASK_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ja-JP', 'ja', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || {runtime: {}};
"""


def goto_with_retry(page: Page, url: str, *, home: str, pause: float,
                    attempts: int = 3) -> bool:
    """Navigate with backoff; re-warm the session if Akamai stalls/resets us."""
    for attempt in range(1, attempts + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(2500)
            if page.query_selector("a[href*='/product/view/id/']"):
                return True
            # Reached a page but no products (interstitial / empty) — treat as soft block.
            print(f"    no products on attempt {attempt}; re-warming", flush=True)
        except PWTimeout:
            print(f"    nav timeout on attempt {attempt}; re-warming", flush=True)
        except Exception as exc:  # ERR_HTTP2_PROTOCOL_ERROR etc.
            print(f"    nav error on attempt {attempt}: {str(exc)[:60]}", flush=True)
        # backoff + re-warm
        time.sleep(pause * attempt * 2)
        try:
            page.goto(home, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
    return False


def crawl_target(page: Page, url: str, label: str, max_pages: int, pause: float) -> list[dict]:
    if not goto_with_retry(page, url, home=HOME, pause=pause):
        print(f"  [{label}] blocked after retries -- skipping", flush=True)
        return []
    category = label

    collected: dict[str, dict] = {}
    for pageno in range(1, max_pages + 1):
        # Search results lazy-load on scroll (~20 -> 60 per page); category pages
        # render their full batch up front. Scroll until the count stabilises.
        last = -1
        for _ in range(40):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1200)
            cur = page.eval_on_selector_all("a[href*='/product/view/id/']", "e=>e.length")
            if cur == last:
                break
            last = cur

        before = set(collected)
        for row in extract_items(page, category):
            collected.setdefault(row["jan"], row)
        new = len(collected) - len(before)
        print(f"  [{category}] page {pageno}: total {len(collected)} (+{new})", flush=True)

        nxt = next_enabled(page)
        if not nxt or (pageno > 1 and new == 0):
            break
        prev_jans = jan_set(page)
        try:
            nxt.scroll_into_view_if_needed(timeout=5000)
            nxt.click(timeout=10000)
        except PWTimeout:
            break
        # wait for the product set to actually change
        for _ in range(20):
            page.wait_for_timeout(500)
            if jan_set(page) != prev_jans:
                break
        page.wait_for_timeout(int(pause * 1000))
    return list(collected.values())


def main() -> int:
    from urllib.parse import quote

    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", nargs="*", default=None,
                        help="Keyword searches to harvest (default: skincare seed set)")
    parser.add_argument("--categories", nargs="*", default=None,
                        help="Category paths under the skincare root, e.g. 004/02/05/01")
    parser.add_argument("--category-file", default="",
                        help="Optional newline-delimited file of category paths")
    parser.add_argument("--out", default="data/manifests/matsukiyo_products.csv")
    parser.add_argument("--max-pages", type=int, default=30)
    parser.add_argument("--pause", type=float, default=6.0,
                        help="Seconds between page loads (Akamai pacing)")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    # Build (url, label) targets: explicit categories win, else keyword searches.
    targets: list[tuple[str, str]] = []
    categories = list(args.categories or [])
    if args.category_file:
        cf = Path(args.category_file)
        categories = [ln.strip() for ln in cf.read_text(encoding="utf-8").splitlines()
                      if ln.strip() and not ln.startswith("#")]
    for cat in categories:
        targets.append((CAT_URL + cat.strip("/"), f"cat:{cat}"))
    if not categories:
        queries = list(args.queries) if args.queries else DEFAULT_QUERIES
        for q in queries:
            targets.append((f"{SEARCH_URL}?q={quote(q)}", f"q:{q}"))
    if not targets:
        raise SystemExit("No categories or queries specified.")

    out_path = PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    all_rows: dict[str, dict] = {}
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                headless=not args.headed, channel="chrome",
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        except Exception as exc:  # pragma: no cover - environment specific
            raise SystemExit(
                "Could not launch Google Chrome via channel='chrome'. Install Chrome "
                f"or run `playwright install chrome`. Original error: {exc}")
        ctx = browser.new_context(user_agent=UA, locale="ja-JP",
                                  viewport={"width": 1366, "height": 900},
                                  extra_http_headers={"Accept-Language": "ja,en;q=0.8"})
        ctx.add_init_script(MASK_SCRIPT)
        page = ctx.new_page()

        # Warm up: land on the store home so Akamai issues a valid _abck token.
        print("Warming up session...", flush=True)
        page.goto(HOME, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)

        for url, label in targets:
            try:
                rows = crawl_target(page, url, label, args.max_pages, args.pause)
            except PWTimeout:
                print(f"  [{label}] timed out / blocked -- skipping", flush=True)
                continue
            for row in rows:
                all_rows.setdefault(row["jan"], row)
            time.sleep(args.pause)
        browser.close()

    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows.values())

    print(f"\nWrote {len(all_rows)} products to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
