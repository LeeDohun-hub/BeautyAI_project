import requests, re

CF = "w9l997abvdotjNPeCTVbHC_tT.Y82OlFD8d8OoPEec0-1782044462-1.2.1.1-RBA3kNNRGf3Fe.7b65J_XhYQm7sJCE3tjTz3UzaJU959UeDEECgQO_kHNfPXQMeA7cLVX7Rboqpg9qgEry9RBjH263fJFrgX6QVIiolYkQ9A.vBd2mvValaRXYmu82xzy0x0p6zX028x4hJkmNa7_laptoKzlY987I9gFXQP4FwJgFr85DNZMWS34qfnb04xALlMm_4IQ9tD6LTr6Gvn9CUq_fyMxzgRQjCF.ZYMnBUPnqmqRHBB8KdGJ1QMTW4jD4mFrjzT0u_4meIzg4BMD1eG6ouJ6w5pB_lTF32.GqkjvDUt2u8b3OvNf7_gDaHqy0R.vnMt5hwc7mNZVaxpBA"

base = "https://global.oliveyoung.com"
cookies = {"curLang": "en", "lang": "en", "currency": "USD", "dlvCntry": "1230", "acesCntry": "00", "cf_clearance": CF}

# Step 1: Get CSRF token from search page
print("Step 1: Fetching CSRF token from search page ...")
r0 = requests.get(
    f"{base}/display/search?query=BIOHEAL+BOH",
    headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0.0.0 Safari/537.36"},
    cookies=cookies, timeout=10
)
csrf = re.search(r'name="_csrf"\s+content="([^"]+)"', r0.text)
csrf_token = csrf.group(1) if csrf else ""
print(f"  CSRF token: {csrf_token}")

# Also grab any session cookies set
cookies.update(r0.cookies.get_dict())

headers = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json",
    "origin": base,
    "referer": f"{base}/display/search?query=BIOHEAL%20BOH",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0.0.0 Safari/537.36",
    "X-CSRF-TOKEN": csrf_token,
}

# Step 2: Try endpoints with CSRF
print("\nStep 2: Trying search endpoints with CSRF token ...")
body_variants = [
    {"query": "BIOHEAL BOH", "pageNo": 1, "pageSize": 20},
    {"keyword": "BIOHEAL BOH", "pageNo": 1, "pageSize": 20},
    {"searchText": "BIOHEAL BOH", "pageNo": 1},
    {"query": "BIOHEAL BOH", "page": 1, "size": 20},
]
paths = [
    "/display/search-data",
    "/display/search-list-data",
    "/display/search-product-data",
    "/search/product-data",
    "/search/list-data",
    "/product/search-list-data",
    "/display/srch-data",
    "/display/search-prd-data",
]

for path in paths:
    for body in body_variants[:1]:  # try first body variant only
        r = requests.post(f"{base}{path}", json=body, headers=headers, cookies=cookies, timeout=8)
        if r.status_code != 404:
            print(f"  [{r.status_code}] POST {path}")
            if r.status_code == 200 and r.text.strip():
                print(f"    => {r.text[:400]}")
