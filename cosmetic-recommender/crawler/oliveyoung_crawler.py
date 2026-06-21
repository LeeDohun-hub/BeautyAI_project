"""
Olive Young ranking crawler for portfolio / personal learning projects.

주의:
- 올리브영 사이트의 이용약관과 robots.txt를 확인한 뒤 사용하세요.
- 과도한 요청을 피하기 위해 기본 sleep을 넣었습니다.
- HTML 구조는 언제든 바뀔 수 있으므로 SELECTORS / CATEGORY_URLS만 고쳐도
  최대한 유지보수할 수 있게 분리했습니다.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag


BASE_URL = "https://www.oliveyoung.co.kr"
BEST_LIST_URL = f"{BASE_URL}/store/main/getBestList.do"

# 참고 글과 같은 판매랭킹 URL 구조입니다.
# 세부 카테고리 dispCatNo는 사이트 개편에 따라 달라질 수 있어 여기에서만 관리합니다.
# 정확한 세부 카테고리 번호를 알게 되면 각 URL만 교체하면 됩니다.
CATEGORY_URLS: dict[str, str] = {
    "toner": f"{BEST_LIST_URL}?dispCatNo=900000100100001&fltDispCatNo=&pageIdx=0&rowsPerPage=0",
    "lotion": f"{BEST_LIST_URL}?dispCatNo=900000100100001&fltDispCatNo=&pageIdx=0&rowsPerPage=0",
    "serum": f"{BEST_LIST_URL}?dispCatNo=900000100100001&fltDispCatNo=&pageIdx=0&rowsPerPage=0",
    "cream": f"{BEST_LIST_URL}?dispCatNo=900000100100001&fltDispCatNo=&pageIdx=0&rowsPerPage=0",
    "spot_care": f"{BEST_LIST_URL}?dispCatNo=900000100100001&fltDispCatNo=&pageIdx=0&rowsPerPage=0",
}

# 카테고리 URL이 넓은 스킨케어 랭킹을 가리키는 경우 상품명으로 한 번 더 필터링합니다.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "toner": ("토너", "스킨", "패드", "toner", "skin", "pad"),
    "lotion": ("로션", "에멀전", "lotion", "emulsion"),
    "serum": ("세럼", "앰플", "에센스", "serum", "ampoule", "essence"),
    "cream": ("크림", "cream"),
    "spot_care": ("스팟", "트러블", "패치", "spot", "blemish", "acne", "patch"),
}

# CSS selector는 사이트 구조 변경에 가장 취약한 부분이므로 한 곳에 모아둡니다.
SELECTORS = {
    "product_items": ".cate_prd_list li",
    "brand": ".tx_brand",
    "product_name": ".tx_name",
    "current_price": ".tx_cur .tx_num",
    "original_price": ".tx_org .tx_num",
    "price_area": ".prd_price",
    "product_link": "a[href*='getGoodsDetail.do'], a[href*='goodsNo=']",
    "sale_flag": ".icon_flag.sale",
    "coupon_flag": ".icon_flag.coupon",
    "gift_flag": ".icon_flag.gift",
    "today_delivery_flag": ".icon_flag.delivery",
}

TAG_RULES: dict[str, tuple[str, ...]] = {
    "pore": ("모공", "피지", "sebum", "pore"),
    "oil": ("유분", "지성", "sebum", "oil control", "oil", "번들"),
    "acne": ("여드름", "트러블", "blemish", "acne", "spot", "스팟"),
    "redness": ("진정", "장벽", "민감", "redness", "시카", "cica", "calming"),
    "texture": ("결", "레티놀", "주름", "texture", "retinol", "wrinkle", "탄력"),
}

FIELDNAMES = [
    "rank",
    "brand",
    "product_name",
    "category",
    "original_price",
    "current_price",
    "sale",
    "coupon",
    "gift",
    "today_delivery",
    "product_url",
    "tags",
]


@dataclass
class Product:
    rank: int
    brand: str
    product_name: str
    category: str
    original_price: int
    current_price: int
    sale: bool
    coupon: bool
    gift: bool
    today_delivery: bool
    product_url: str
    tags: list[str]


def _text(node: Tag | None) -> str:
    """BeautifulSoup Tag에서 공백이 정리된 텍스트를 꺼냅니다."""
    return node.get_text(" ", strip=True) if node else ""


def _parse_price(value: str) -> int:
    """'29,000원~' 같은 문자열에서 숫자만 뽑아 정수로 바꿉니다."""
    digits = re.sub(r"[^0-9]", "", value)
    return int(digits) if digits else 0


def infer_category(product_name: str, fallback: str) -> str:
    """상품명 기반으로 실제 상품 카테고리를 추정합니다."""
    lower_name = product_name.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword.lower() in lower_name for keyword in keywords):
            return category
    return fallback


def build_tags(product_name: str, category: str) -> list[str]:
    """
    상품명과 카테고리에서 추천용 태그를 자동 생성합니다.
    피부진단 concern과 이 태그가 만나는 상품을 추천 후보로 사용합니다.
    """
    text = f"{product_name} {category}".lower()
    tags = set()
    for tag, keywords in TAG_RULES.items():
        if any(keyword.lower() in text for keyword in keywords):
            tags.add(tag)

    # 카테고리 자체가 스팟 케어면 acne 태그를 보강합니다.
    if category == "spot_care":
        tags.add("acne")

    return sorted(tags)


def is_category_match(product_name: str, category: str) -> bool:
    """넓은 랭킹 페이지에서 원하는 카테고리 상품만 남기기 위한 필터입니다."""
    keywords = CATEGORY_KEYWORDS.get(category, ())
    lower_name = product_name.lower()
    return not keywords or any(keyword.lower() in lower_name for keyword in keywords)


def fetch_html(url: str, sleep_seconds: float = 1.5, timeout: int = 10) -> str:
    """
    올리브영 HTML을 가져옵니다.
    sleep_seconds는 요청 간격을 두기 위한 안전장치입니다.
    """
    time.sleep(sleep_seconds)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Referer": BASE_URL,
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_products(html: str, category: str, limit: int = 100) -> list[Product]:
    """판매랭킹 HTML에서 상품 정보를 Product 리스트로 변환합니다."""
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(SELECTORS["product_items"])
    products: list[Product] = []

    for item in items:
        brand = _text(item.select_one(SELECTORS["brand"]))
        product_name = _text(item.select_one(SELECTORS["product_name"]))
        if not brand or not product_name:
            continue

        if not is_category_match(product_name, category):
            continue

        current_price = _parse_price(_text(item.select_one(SELECTORS["current_price"])))
        original_price = _parse_price(_text(item.select_one(SELECTORS["original_price"])))
        if not original_price:
            original_price = current_price

        link = item.select_one(SELECTORS["product_link"])
        product_url = urljoin(BASE_URL, link.get("href", "")) if link else ""

        inferred_category = infer_category(product_name, category)
        tags = build_tags(product_name, inferred_category)

        products.append(
            Product(
                rank=len(products) + 1,
                brand=brand,
                product_name=product_name,
                category=inferred_category,
                original_price=original_price,
                current_price=current_price,
                sale=item.select_one(SELECTORS["sale_flag"]) is not None,
                coupon=item.select_one(SELECTORS["coupon_flag"]) is not None,
                gift=item.select_one(SELECTORS["gift_flag"]) is not None,
                today_delivery=item.select_one(SELECTORS["today_delivery_flag"]) is not None,
                product_url=product_url,
                tags=tags,
            )
        )

        if len(products) >= limit:
            break

    return products


def crawl_category(category: str, limit: int = 100, sleep_seconds: float = 1.5) -> list[Product]:
    """toner/lotion/serum/cream/spot_care 중 하나의 카테고리 상품을 수집합니다."""
    if category not in CATEGORY_URLS:
        raise ValueError(f"지원하지 않는 카테고리입니다: {category}")

    url = CATEGORY_URLS[category]
    try:
        html = fetch_html(url, sleep_seconds=sleep_seconds)
        return parse_products(html, category=category, limit=limit)
    except requests.RequestException as exc:
        logging.warning("올리브영 요청 실패: category=%s url=%s error=%s", category, url, exc)
    except Exception as exc:
        logging.exception("상품 파싱 실패: category=%s error=%s", category, exc)
    return []


def crawl_categories(
    categories: Iterable[str] = CATEGORY_URLS.keys(),
    limit_per_category: int = 100,
    sleep_seconds: float = 1.5,
) -> list[Product]:
    """여러 카테고리를 순차적으로 수집합니다. 중복 상품 URL은 한 번만 남깁니다."""
    collected: list[Product] = []
    seen_keys: set[str] = set()

    for category in categories:
        for product in crawl_category(category, limit=limit_per_category, sleep_seconds=sleep_seconds):
            dedupe_key = product.product_url or f"{product.brand}:{product.product_name}"
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            collected.append(product)

    return collected


def save_products_csv(products: list[Product], path: str | Path) -> None:
    """크롤링 결과를 products.csv로 저장합니다."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        for product in products:
            row = asdict(product)
            row["tags"] = "|".join(product.tags)
            writer.writerow(row)


def save_products_json(products: list[Product], path: str | Path) -> None:
    """크롤링 결과를 products.json으로 저장합니다."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump([asdict(product) for product in products], file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    products = crawl_categories(limit_per_category=100, sleep_seconds=1.5)
    save_products_csv(products, Path(__file__).resolve().parents[1] / "data" / "products.csv")
    save_products_json(products, Path(__file__).resolve().parents[1] / "data" / "products.json")
    logging.info("수집 완료: %s개 상품", len(products))
