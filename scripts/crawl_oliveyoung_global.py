"""Crawl product data from Olive Young Global via their internal POST API.

API endpoint (discovered via DevTools):
  POST https://global.oliveyoung.com/product/detail-data
  Body: {"prdtNo": "GA210000002"}

Product numbers are fetched from the public sitemap:
  https://global.oliveyoung.com/sitemapindex-product.xml

Usage:
    # Refresh the whole catalog. cf_clearance is usually NOT needed — the detail-data
    # API passes with localization cookies alone (verified 2026-07-08).
    python scripts/crawl_oliveyoung_global.py

    # Only if Cloudflare starts returning 403/empty: pass a fresh browser cookie
    # (DevTools → Application → Cookies → cf_clearance).
    python scripts/crawl_oliveyoung_global.py --cf-clearance "YOUR_CF_CLEARANCE_VALUE"

    # Optional: filter by brand keyword / limit for testing
    python scripts/crawl_oliveyoung_global.py --brand "BIOHEAL BOH"
    python scripts/crawl_oliveyoung_global.py --limit 50

Note on coverage: the product/image sitemaps expose exactly ~500 curated products and
that IS the full global shop — probing ~680 prdtNos outside the sitemap (incl. beyond
the max) returned 0 products (verified 2026-07-08). There is no larger catalog to crawl.

Output:
    data/manifests/oliveyoung_global_products.csv
"""

from __future__ import annotations

import argparse
import csv
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

BASE_URL = "https://global.oliveyoung.com"
DETAIL_API = f"{BASE_URL}/product/detail-data"
SITEMAP_URL = f"{BASE_URL}/sitemapindex-product.xml"
IMAGE_CDN = "https://image.oliveyoung.com/"

FIELDNAMES = [
    "prdtNo",
    "prdtNameEn",
    "brandName",
    "category",
    "subCategory",
    "nrmlAmt",
    "saleAmt",
    "currency",
    "gdsCd",
    "imagePath",
    "sellStatCode",
    "stockQty",
    "bestYn",
    "newYn",
    "trendingYn",
    "korPrdtName",
    "productUrl",
    "imageUrl",
]

MAKEUP_WORDS = (
    "makeup",
    "lip",
    "lipstick",
    "tint",
    "rouge",
    "gloss",
    "blush",
    "cheek",
    "eye",
    "eyeshadow",
    "shadow",
    "palette",
    "mascara",
    "liner",
    "foundation",
    "cushion",
    "concealer",
    "primer",
    "powder",
)


def build_session(cf_clearance: str = "") -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "accept": "application/json, text/plain, */*",
        "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "content-type": "application/json",
        "origin": BASE_URL,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
    })
    # 실측(2026-07-08): detail-data API는 로컬라이제이션 쿠키만으로 통과한다(cf_clearance 불필요).
    # Cloudflare가 다시 조여 403/빈응답이 나올 때만 --cf-clearance 로 브라우저 쿠키를 넣으면 된다.
    cookies = {
        "curLang": "en",
        "lang": "en",
        "currency": "USD",
        "dlvCntry": "1230",
        "acesCntry": "00",
        "awsCntryCode": "1230",
    }
    if cf_clearance:
        cookies["cf_clearance"] = cf_clearance
    session.cookies.update(cookies)
    return session


def fetch_product_numbers_from_sitemap() -> list[str]:
    """Parse sitemap XML and extract all prdtNo values."""
    print(f"Fetching sitemap: {SITEMAP_URL}")
    resp = requests.get(SITEMAP_URL, timeout=30)
    resp.raise_for_status()

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(resp.text)
    product_numbers: list[str] = []

    for url_el in root.findall(".//sm:url/sm:loc", ns):
        loc = url_el.text or ""
        qs = parse_qs(urlparse(loc).query)
        prdtNo = qs.get("prdtNo", [None])[0]
        if prdtNo:
            product_numbers.append(prdtNo)

    print(f"Found {len(product_numbers):,} product numbers in sitemap")
    return product_numbers


def fetch_product(session: requests.Session, prdtNo: str) -> dict | None:
    try:
        resp = session.post(
            DETAIL_API,
            json={"prdtNo": prdtNo},
            timeout=15,
            headers={"referer": f"{BASE_URL}/product/detail?prdtNo={prdtNo}"},
        )
        if resp.status_code == 403:
            print(f"  [403] cf_clearance expired — re-run with a fresh cookie")
            return None
        if resp.status_code != 200:
            print(f"  [{resp.status_code}] {prdtNo}")
            return None

        data = resp.json()
        product = data.get("product") or data
        if not product:
            return None

        option_list = product.get("optionList") or []
        stock_qty = option_list[0].get("buyStockQty") if option_list else None

        category_parts = (product.get("allPathCtgrNameEn") or "").replace("&gt;", ">").split(">")
        category = category_parts[1].strip() if len(category_parts) > 1 else ""
        sub_category = category_parts[2].strip() if len(category_parts) > 2 else ""

        image_path = product.get("imagePath") or ""
        image_url = f"{IMAGE_CDN}{image_path}" if image_path else ""

        return {
            "prdtNo": prdtNo,
            "prdtNameEn": product.get("prdtNameEn") or product.get("prdtName", ""),
            "brandName": product.get("brandNameEn") or product.get("brandName", ""),
            "category": category,
            "subCategory": sub_category,
            "nrmlAmt": product.get("nrmlAmt") or product.get("minOptnNrmlAmt", ""),
            "saleAmt": product.get("saleAmt") or product.get("minOptnSaleAmt", ""),
            "currency": "USD",
            "gdsCd": product.get("gdsCd", ""),
            "imagePath": image_path,
            "sellStatCode": product.get("sellStatCode", ""),
            "stockQty": stock_qty,
            "bestYn": product.get("bestYn", ""),
            "newYn": product.get("newYn", ""),
            "trendingYn": product.get("trendingYn", ""),
            "korPrdtName": product.get("korPrdtName", ""),
            "productUrl": f"{BASE_URL}/product/detail?prdtNo={prdtNo}",
            "imageUrl": image_url,
        }

    except requests.exceptions.Timeout:
        print(f"  [timeout] {prdtNo}")
        return None
    except Exception as e:
        print(f"  [error] {prdtNo}: {e}")
        return None


def is_makeup_row(row: dict) -> bool:
    haystack = " ".join(
        str(row.get(field) or "").lower()
        for field in ("prdtNameEn", "korPrdtName", "category", "subCategory")
    )
    return any(word in haystack for word in MAKEUP_WORDS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl Olive Young Global product catalog via internal API.")
    parser.add_argument("--cf-clearance", default="", help="Optional cf_clearance cookie. Usually not needed (localization cookies suffice); provide only if Cloudflare starts returning 403/empty.")
    parser.add_argument("--brand", default="", help="Filter products by brand name keyword (e.g. 'BIOHEAL BOH')")
    parser.add_argument("--makeup-only", action="store_true", help="Keep only makeup/color product rows")
    parser.add_argument("--limit", type=int, default=0, help="Max products to fetch (0 = all)")
    parser.add_argument("--delay", type=float, default=0.8, help="Delay between requests in seconds (default: 0.8)")
    parser.add_argument("--out", default="data/manifests/oliveyoung_global_products.csv")
    args = parser.parse_args()

    product_numbers = fetch_product_numbers_from_sitemap()
    if args.limit > 0:
        product_numbers = product_numbers[: args.limit]

    session = build_session(args.cf_clearance)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    failed = 0

    print(f"\nFetching {len(product_numbers):,} products (delay={args.delay}s) ...")
    for i, prdtNo in enumerate(product_numbers, 1):
        row = fetch_product(session, prdtNo)
        if row is None:
            failed += 1
            if failed >= 5:
                print("Too many consecutive failures — cf_clearance likely expired. Stopping.")
                break
            continue

        failed = 0

        brand_filter = args.brand.lower()
        if brand_filter and brand_filter not in (row["brandName"] or "").lower() and brand_filter not in (row["prdtNameEn"] or "").lower():
            continue
        if args.makeup_only and not is_makeup_row(row):
            continue

        results.append(row)

        if i % 50 == 0:
            print(f"  {i:,}/{len(product_numbers):,} fetched / {len(results):,} kept")

        time.sleep(args.delay)

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nDone. Saved {len(results):,} products to {out_path}")

    # Print brand breakdown
    if results:
        from collections import Counter
        brand_counts = Counter(r["brandName"] for r in results)
        print("\nTop brands:")
        for brand, count in brand_counts.most_common(15):
            print(f"  {brand:<30} {count:>4}개")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
