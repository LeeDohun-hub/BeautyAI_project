"""Quick scan: find all BIOHEAL BOH and WAKEMAKE products across 500 sitemap entries."""
import requests
import time
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse
from collections import Counter
import sys

CF = sys.argv[1]
BASE = "https://global.oliveyoung.com"

session = requests.Session()
session.headers.update({
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json",
    "origin": BASE,
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
})
session.cookies.update({
    "curLang": "en", "lang": "en", "currency": "USD",
    "dlvCntry": "1230", "acesCntry": "00", "awsCntryCode": "1230",
    "cf_clearance": CF,
})

r = session.get(BASE + "/sitemapindex-product.xml", timeout=15)
ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
root = ET.fromstring(r.text)
nums = []
for el in root.findall(".//sm:url/sm:loc", ns):
    qs = parse_qs(urlparse(el.text or "").query)
    n = qs.get("prdtNo", [None])[0]
    if n:
        nums.append(n)

brand_counter = Counter()
target_products = []
errors = 0

print(f"Scanning all {len(nums)} products (0.25s delay)...")
for i, prdtNo in enumerate(nums, 1):
    try:
        r2 = session.post(
            BASE + "/product/detail-data",
            json={"prdtNo": prdtNo},
            headers={"referer": BASE + "/product/detail?prdtNo=" + prdtNo},
            timeout=10,
        )
        if r2.status_code == 403:
            print("403 - cookie expired")
            break
        if r2.status_code != 200:
            errors += 1
            time.sleep(0.3)
            continue

        d = r2.json()
        prod = d.get("product") or d
        brand = prod.get("brandNameEn") or prod.get("korBrandName") or ""
        name = prod.get("prdtNameEn") or prod.get("prdtName", "")
        brand_counter[brand] += 1

        bl = brand.lower()
        if "bioheal" in bl or "wakemake" in bl:
            target_products.append({"prdtNo": prdtNo, "brand": brand, "name": name})
            print(f"  [{i:3d}] TARGET: {brand} | {name}")

        if i % 50 == 0:
            print(f"  Progress: {i}/{len(nums)} | targets so far: {len(target_products)}")

        time.sleep(0.25)
    except Exception as e:
        errors += 1
        print(f"  [err] {prdtNo}: {e}")

print(f"\nScan complete. Errors: {errors}")
print(f"Target products found: {len(target_products)}")
print("\nAll brands (top 35):")
for brand, cnt in brand_counter.most_common(35):
    marker = " <<<"
    bl = brand.lower()
    if "bioheal" in bl or "wakemake" in bl:
        line = f"  {brand:<35} {cnt:>3}{marker}"
    else:
        line = f"  {brand:<35} {cnt:>3}"
    print(line)

print("\nTarget product list:")
for p in target_products:
    print(f"  prdtNo={p['prdtNo']} | {p['brand']} | {p['name']}")
