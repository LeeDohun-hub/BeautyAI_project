"""Crawl BIOHEAL BOH and WAKEMAKE products and reviews from Olive Young Global.

The product sitemap only exposes a small subset of products. This crawler uses
the same search and product review APIs that the Olive Young Global frontend
uses.

Usage:
    backend\\.venv\\Scripts\\python.exe scripts\\crawl_oliveyoung_brand_reviews.py ^
      --cf-clearance "VALUE" --max-reviews 50

Outputs:
    data/manifests/oy_brand_products.csv
    data/manifests/oy_brand_reviews.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://global.oliveyoung.com"
SEARCH_PAGE = f"{BASE_URL}/display/search"
SEARCH_API = f"{BASE_URL}/display/search/product-list"
DETAIL_API = f"{BASE_URL}/product/detail-data"
REVIEW_API = f"{BASE_URL}/product/review-list"
IMAGE_CDN = "https://image.oliveyoung.com/"

DEFAULT_QUERIES = ["BIOHEAL BOH", "WAKEMAKE"]

PRODUCT_FIELDS = [
    "sourceQuery",
    "prdtNo",
    "brandNo",
    "brandName",
    "prdtName",
    "category",
    "subCategory",
    "nrmlAmt",
    "saleAmt",
    "currency",
    "sellStatCode",
    "stockQty",
    "bestYn",
    "newYn",
    "soldOutYn",
    "reviewCount",
    "avgRating",
    "imagePath",
    "imageUrl",
    "productUrl",
]

REVIEW_FIELDS = [
    "prdtNo",
    "brandName",
    "prdtName",
    "reviewNo",
    "rating",
    "reviewContent",
    "reviewDate",
    "likeCount",
    "optionName",
    "reviewSource",
    "mediaReviewYn",
    "loginId",
]


def build_session(cf_clearance: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "origin": BASE_URL,
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
    )
    session.cookies.update(
        {
            "curLang": "en",
            "lang": "en",
            "currency": "USD",
            "dlvCntry": "1230",
            "acesCntry": "00",
            "awsCntryCode": "1230",
            "cf_clearance": cf_clearance,
        }
    )
    return session


def scalar(value: Any, default: Any = "") -> Any:
    if isinstance(value, list):
        return value[0] if value else default
    return default if value is None else value


def clean_text(value: Any) -> str:
    return str(scalar(value, "")).replace("\r", " ").replace("\n", " ").strip()


def extract_csrf(html: str) -> str:
    match = re.search(r'name="_csrf"\s+content="([^"]+)"', html)
    return match.group(1) if match else ""


def search_products(
    session: requests.Session,
    query: str,
    rows_per_page: int,
    delay: float,
) -> list[dict[str, Any]]:
    page = 1
    products: list[dict[str, Any]] = []

    page_resp = session.get(SEARCH_PAGE, params={"query": query}, timeout=20)
    page_resp.raise_for_status()
    csrf = extract_csrf(page_resp.text)

    headers = {
        "referer": page_resp.url,
        "X-CSRF-TOKEN": csrf,
    }

    while True:
        payload = {
            "query": query,
            "pageNum": page,
            "rowsPerPage": rows_per_page,
        }
        resp = session.post(SEARCH_API, json=payload, headers=headers, timeout=25)
        if resp.status_code == 403:
            raise RuntimeError("cf_clearance expired while calling search API")
        resp.raise_for_status()

        search = resp.json().get("search") or {}
        hits = search.get("hits") or {}
        found = int(hits.get("found") or 0)
        hit_rows = hits.get("hit") or []

        print(f"[search] {query}: page {page}, {len(hit_rows)} rows, found={found}", flush=True)
        for hit in hit_rows:
            fields = hit.get("fields") or hit
            if fields:
                products.append(fields)

        if not hit_rows or len(products) >= found:
            break
        if page >= math.ceil(found / rows_per_page):
            break

        page += 1
        time.sleep(delay)

    return products


def normalize_product(source_query: str, product: dict[str, Any]) -> dict[str, Any]:
    category_parts = product.get("allPathCtgrNameList") or []
    category = category_parts[1] if len(category_parts) > 1 else product.get("ctgrName", "")
    sub_category = category_parts[2] if len(category_parts) > 2 else product.get("ctgrName", "")
    image_path = clean_text(product.get("imagePath"))
    return {
        "sourceQuery": source_query,
        "prdtNo": clean_text(product.get("prdtNo")),
        "brandNo": clean_text(product.get("brandNo")),
        "brandName": clean_text(product.get("brandName")),
        "prdtName": clean_text(product.get("prdtName")),
        "category": clean_text(category),
        "subCategory": clean_text(sub_category),
        "nrmlAmt": scalar(product.get("nrmlAmt")),
        "saleAmt": scalar(product.get("saleAmt")),
        "currency": "USD",
        "sellStatCode": clean_text(product.get("sellStatCode")),
        "stockQty": scalar(product.get("stockQty")),
        "bestYn": clean_text(product.get("bestYn")),
        "newYn": clean_text(product.get("newYn")),
        "soldOutYn": clean_text(product.get("soldOutYn")),
        "reviewCount": scalar(product.get("reviewCnt")),
        "avgRating": scalar(product.get("reviewScore")),
        "imagePath": image_path,
        "imageUrl": f"{IMAGE_CDN}{image_path}" if image_path else "",
        "productUrl": f"{BASE_URL}/product/detail?prdtNo={clean_text(product.get('prdtNo'))}",
    }


def fetch_detail(session: requests.Session, prdt_no: str) -> dict[str, Any]:
    resp = session.post(
        DETAIL_API,
        json={"prdtNo": prdt_no},
        headers={"referer": f"{BASE_URL}/product/detail?prdtNo={prdt_no}"},
        timeout=20,
    )
    if resp.status_code == 403:
        raise RuntimeError("cf_clearance expired while calling detail API")
    resp.raise_for_status()
    return resp.json().get("product") or resp.json()


def fetch_reviews(
    session: requests.Session,
    product_row: dict[str, Any],
    detail: dict[str, Any],
    max_reviews: int,
    delay: float,
) -> list[dict[str, Any]]:
    if max_reviews <= 0:
        return []

    prdt_no = product_row["prdtNo"]
    reviews: list[dict[str, Any]] = []
    page = 1
    page_size = min(20, max_reviews)

    base_payload = {
        "filterYn": detail.get("filterYn"),
        "prdtNo": prdt_no,
        "prdtGbnCode": detail.get("prdtGbnCode") or "10",
        "movReviewYn": "N",
        "photoReviewYn": "N",
        "optnYn": detail.get("optnYn") or "N",
        "transUseYn": "N",
    }

    while len(reviews) < max_reviews:
        payload = {
            **base_payload,
            "pageNum": page,
            "rowsPerPage": page_size,
            "sort": "01",
        }
        resp = session.post(
            REVIEW_API,
            json=payload,
            headers={"referer": f"{BASE_URL}/product/detail?prdtNo={prdt_no}"},
            timeout=25,
        )
        if resp.status_code == 403:
            raise RuntimeError("cf_clearance expired while calling review API")
        resp.raise_for_status()

        data = resp.json()
        review_list = data.get("reviewList") or []
        total_count = int(data.get("totalCount") or 0)
        if not review_list:
            break

        for review in review_list:
            if len(reviews) >= max_reviews:
                break
            reviews.append(
                {
                    "prdtNo": prdt_no,
                    "brandName": product_row["brandName"],
                    "prdtName": product_row["prdtName"],
                    "reviewNo": clean_text(review.get("prdtReviewNo")),
                    "rating": scalar(review.get("previewScore")),
                    "reviewContent": clean_text(review.get("conText")),
                    "reviewDate": clean_text(review.get("reviewRgstYmd")),
                    "likeCount": scalar(review.get("goodCnt")),
                    "optionName": clean_text(review.get("snglOptnName")),
                    "reviewSource": clean_text(review.get("reviewSource")),
                    "mediaReviewYn": clean_text(review.get("mediaReviewYn")),
                    "loginId": clean_text(review.get("loginId")),
                }
            )

        if len(review_list) < page_size:
            break
        if total_count and len(reviews) >= total_count:
            break

        page += 1
        time.sleep(delay)

    return reviews


def write_csv(path: str, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crawl BIOHEAL BOH and WAKEMAKE data from Olive Young Global."
    )
    parser.add_argument("--cf-clearance", required=True, help="cf_clearance cookie value")
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Search query to crawl. Can be repeated. Defaults to BIOHEAL BOH and WAKEMAKE.",
    )
    parser.add_argument("--rows-per-page", type=int, default=100)
    parser.add_argument("--max-reviews", type=int, default=50, help="Max reviews per product")
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--product-out", default="data/manifests/oy_brand_products.csv")
    parser.add_argument("--review-out", default="data/manifests/oy_brand_reviews.csv")
    args = parser.parse_args()

    session = build_session(args.cf_clearance)
    queries = args.query or DEFAULT_QUERIES

    product_rows: list[dict[str, Any]] = []
    raw_by_prdt_no: dict[str, dict[str, Any]] = {}

    for query in queries:
        for product in search_products(session, query, args.rows_per_page, args.delay):
            prdt_no = clean_text(product.get("prdtNo"))
            if not prdt_no or prdt_no in raw_by_prdt_no:
                continue
            raw_by_prdt_no[prdt_no] = product
            product_rows.append(normalize_product(query, product))
        time.sleep(args.delay)

    review_rows: list[dict[str, Any]] = []
    print(f"\nFound {len(product_rows)} unique products. Fetching reviews...", flush=True)

    for idx, row in enumerate(product_rows, 1):
        detail = fetch_detail(session, row["prdtNo"])
        reviews = fetch_reviews(session, row, detail, args.max_reviews, args.delay)
        review_rows.extend(reviews)
        print(
            f"[reviews] {idx}/{len(product_rows)} {row['brandName']} - "
            f"{row['prdtName']} => {len(reviews)}",
            flush=True,
        )
        time.sleep(args.delay)

    write_csv(args.product_out, PRODUCT_FIELDS, product_rows)
    write_csv(args.review_out, REVIEW_FIELDS, review_rows)

    print(f"\nSaved {len(product_rows)} products -> {args.product_out}")
    print(f"Saved {len(review_rows)} reviews -> {args.review_out}")

    by_brand: dict[str, int] = {}
    for row in product_rows:
        by_brand[row["brandName"]] = by_brand.get(row["brandName"], 0) + 1
    print("\nProducts by brand:")
    for brand, count in sorted(by_brand.items()):
        print(f"  {brand}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
