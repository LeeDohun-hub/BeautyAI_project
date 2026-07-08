"""Olive Young Global 검색 API 기반 카탈로그 크롤 (사이트맵 500개 한계 돌파).

발견(2026-07-08): `sitemapindex-product.xml`은 옛 ~500개(GA21…)만 노출하지만, 글로벌몰 실제
카탈로그는 GA21~GA26(2021~2026)에 걸쳐 수천 개다. 내부 검색 API로 브랜드/키워드별 prdtNo를
모아 detail-data로 상품정보를 채운다(localization 쿠키만 필요, cf_clearance 불필요).

  POST https://global.oliveyoung.com/display/search/product-list
    body {"query","pageNum","rowsPerPage","sort":"10", ...}
    -> search.hits.found(총개수), search.productPriceMap(키=prdtNo)

산출물은 기존 crawl_oliveyoung_global.py 와 동일한 CSV 스키마라 그대로 병합/교체 가능.

Usage:
  python scripts/crawl_oliveyoung_global_search.py --out data/manifests/oliveyoung_global_products.csv --merge
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = "https://global.oliveyoung.com"
SEARCH_API = f"{BASE}/display/search/product-list"
DETAIL_API = f"{BASE}/product/detail-data"
IMAGE_CDN = "https://image.oliveyoung.com/"
COOKIE = "curLang=en; lang=en; currency=USD; dlvCntry=1230; acesCntry=00; awsCntryCode=1230"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/149.0.0.0 Safari/537.36")

FIELDNAMES = [
    "prdtNo", "prdtNameEn", "brandName", "category", "subCategory", "nrmlAmt", "saleAmt",
    "currency", "gdsCd", "imagePath", "sellStatCode", "stockQty", "bestYn", "newYn",
    "trendingYn", "korPrdtName", "productUrl", "imageUrl",
]

# 크롤 대상: K뷰티 브랜드(recommender.KBEAUTY_BRANDS) + 색조 브랜드.
BRANDS = [
    "abib", "anua", "axis-y", "beauty of joseon", "beplain", "bioheal boh", "celimax",
    "clio", "cosrx", "d.alba", "dr.jart", "espoir", "etude", "goodal", "heimish", "hince",
    "innisfree", "isntree", "klairs", "laneige", "manyo", "medicube", "mediheal", "missha",
    "mixsoon", "numbuzin", "peripera", "purito", "rom&nd", "round lab", "skin1004",
    "skinfood", "some by mi", "sulwhasoo", "the face shop", "tirtir", "torriden",
    "3ce", "colorgram", "wakemake", "amuse", "dasique", "lilybyred", "fwee", "hera",
    "unleashia", "clove", "muzigae", "holika holika", "nature republic", "banila co",
    "vt", "abibcica", "dr.g", "aestura", "illiyoon", "bring green", "one thing", "haruharu",
]


def _post(url: str, payload: dict, timeout: float = 15.0):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"content-type": "application/json", "origin": BASE,
                 "referer": f"{BASE}/", "cookie": COOKIE, "user-agent": UA},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "ignore")
    return json.loads(raw) if raw.strip() else None


def search_prdtnos(query: str, delay: float = 0.2) -> set[str]:
    """브랜드/키워드 검색으로 모든 prdtNo를 페이지네이션 수집."""
    out: set[str] = set()
    page = 1
    while True:
        try:
            d = _post(SEARCH_API, {
                "query": query, "sort": "10", "pageNum": page, "rowsPerPage": 100,
                "brandNoList": [], "ctgrNoList": [], "eventSlprcDscntRt": [],
                "reviewScrGradeList": [], "minPrc": "", "maxPrc": "",
            })
        except Exception:
            break
        if not d:
            break
        s = d.get("search") or {}
        pmap = s.get("productPriceMap") or {}
        found = int((s.get("hits") or {}).get("found") or 0)
        if not pmap:
            break
        out.update(pmap.keys())
        if len(out) >= found or page >= 20:
            break
        page += 1
        time.sleep(delay)
    return out


def fetch_product(prdt_no: str) -> dict | None:
    try:
        d = _post(DETAIL_API, {"prdtNo": prdt_no}, timeout=12)
    except Exception:
        return None
    if not d:
        return None
    p = d.get("product") or d
    if not isinstance(p, dict) or not (p.get("prdtNameEn") or p.get("prdtName")):
        return None
    option_list = p.get("optionList") or []
    stock_qty = option_list[0].get("buyStockQty") if option_list else None
    cats = (p.get("allPathCtgrNameEn") or "").replace("&gt;", ">").split(">")
    image_path = p.get("imagePath") or ""
    return {
        "prdtNo": prdt_no,
        "prdtNameEn": p.get("prdtNameEn") or p.get("prdtName", ""),
        "brandName": p.get("brandNameEn") or p.get("brandName", ""),
        "category": cats[1].strip() if len(cats) > 1 else "",
        "subCategory": cats[2].strip() if len(cats) > 2 else "",
        "nrmlAmt": p.get("nrmlAmt") or p.get("minOptnNrmlAmt", ""),
        "saleAmt": p.get("saleAmt") or p.get("minOptnSaleAmt", ""),
        "currency": "USD",
        "gdsCd": p.get("gdsCd", ""),
        "imagePath": image_path,
        "sellStatCode": p.get("sellStatCode", ""),
        "stockQty": stock_qty,
        "bestYn": p.get("bestYn", ""),
        "newYn": p.get("newYn", ""),
        "trendingYn": p.get("trendingYn", ""),
        "korPrdtName": p.get("korPrdtName", ""),
        "productUrl": f"{BASE}/product/detail?prdtNo={prdt_no}",
        "imageUrl": f"{IMAGE_CDN}{image_path}" if image_path else "",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/manifests/oliveyoung_global_products.csv")
    ap.add_argument("--merge", action="store_true", help="기존 CSV와 prdtNo 기준 병합")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--extra", default="", help="쉼표구분 추가 검색어(브랜드 외 카테고리 등)")
    args = ap.parse_args()

    queries = list(BRANDS) + [q.strip() for q in args.extra.split(",") if q.strip()]
    print(f"검색어 {len(queries)}개로 prdtNo 수집 중...")
    prdtnos: set[str] = set()
    for i, q in enumerate(queries, 1):
        got = search_prdtnos(q)
        prdtnos |= got
        print(f"  [{i}/{len(queries)}] {q}: +{len(got)} (누적 {len(prdtnos)})", flush=True)
    print(f"고유 prdtNo: {len(prdtnos)}개. detail-data 수집 시작...")

    rows: dict[str, dict] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_product, pn): pn for pn in prdtnos}
        for fut in as_completed(futs):
            row = fut.result()
            done += 1
            if row:
                rows[row["prdtNo"]] = row
            if done % 200 == 0:
                print(f"  detail {done}/{len(prdtnos)} -> {len(rows)} ok", flush=True)

    out_path = Path(args.out)
    if args.merge and out_path.exists():
        with out_path.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                pn = (r.get("prdtNo") or "").strip()
                if pn and pn not in rows:
                    rows[pn] = {k: r.get(k, "") for k in FIELDNAMES}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows.values())
    print(f"\nDone. {len(rows)} products -> {out_path}")

    from collections import Counter
    bc = Counter(r["brandName"] for r in rows.values())
    print("top brands:", dict(bc.most_common(12)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
