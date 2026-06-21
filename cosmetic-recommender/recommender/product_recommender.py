"""
Crawler output based product recommender.

피부진단 결과의 concerns와 크롤링 상품 tags를 매칭하고,
랭킹/가격/혜택 정보를 점수화해 실제 판매 상품 TOP5를 추천합니다.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CONCERN_ALIASES: dict[str, set[str]] = {
    "pore": {"pore", "모공"},
    "oil": {"oil", "oiliness", "유분", "지성"},
    "acne": {"acne", "blemish", "트러블", "여드름"},
    "redness": {"redness", "sensitive", "민감", "홍조", "진정"},
    "texture": {"texture", "wrinkle", "주름", "결"},
}

SKIN_TYPE_BONUS: dict[str, set[str]] = {
    "oily": {"oil", "pore", "acne"},
    "combination": {"oil", "pore", "redness"},
    "dry": {"redness", "texture"},
    "sensitive": {"redness"},
    "normal": set(),
}


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
    tags: set[str]


@dataclass
class Recommendation:
    product: Product
    score: float
    reason: str


def _parse_bool(value: object) -> bool:
    """CSV/JSON에서 읽은 다양한 Boolean 표현을 bool로 정규화합니다."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _parse_int(value: object) -> int:
    """가격/순위 값이 비어 있거나 쉼표가 있어도 안전하게 정수로 바꿉니다."""
    digits = "".join(char for char in str(value) if char.isdigit())
    return int(digits) if digits else 0


def _parse_tags(value: object) -> set[str]:
    """CSV의 'pore|acne' 또는 JSON list 형태의 tags를 set으로 변환합니다."""
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    return {item.strip() for item in str(value).split("|") if item.strip()}


def normalize_concerns(concerns: Iterable[str]) -> set[str]:
    """사용자 concern 값을 추천 태그 체계로 정규화합니다."""
    normalized = set()
    for concern in concerns:
        lower = concern.strip().lower()
        for tag, aliases in CONCERN_ALIASES.items():
            if lower == tag or lower in {alias.lower() for alias in aliases}:
                normalized.add(tag)
                break
        else:
            normalized.add(lower)
    return normalized


def load_products(path: str | Path) -> list[Product]:
    """products.csv 또는 products.json을 읽어 Product 리스트로 변환합니다."""
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"상품 데이터 파일이 없습니다: {input_path}")

    if input_path.suffix.lower() == ".json":
        with input_path.open("r", encoding="utf-8") as file:
            rows = json.load(file)
    else:
        with input_path.open("r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))

    products = []
    for row in rows:
        products.append(
            Product(
                rank=_parse_int(row.get("rank")),
                brand=str(row.get("brand", "")),
                product_name=str(row.get("product_name", "")),
                category=str(row.get("category", "")),
                original_price=_parse_int(row.get("original_price")),
                current_price=_parse_int(row.get("current_price")),
                sale=_parse_bool(row.get("sale")),
                coupon=_parse_bool(row.get("coupon")),
                gift=_parse_bool(row.get("gift")),
                today_delivery=_parse_bool(row.get("today_delivery")),
                product_url=str(row.get("product_url", "")),
                tags=_parse_tags(row.get("tags", "")),
            )
        )
    return products


def score_product(product: Product, target_tags: set[str], max_price: int) -> tuple[float, str]:
    """
    추천 점수를 계산합니다.
    - concern/tag 일치가 가장 중요합니다.
    - 랭킹이 높을수록, 가격이 낮을수록 유리합니다.
    - 세일/쿠폰/오늘드림/증정은 구매 편의와 혜택으로 가산합니다.
    """
    matched_tags = product.tags.intersection(target_tags)
    if not matched_tags:
        return 0.0, ""

    rank_score = max(0, 101 - product.rank) * 0.25
    price_score = (1 - (product.current_price / max_price)) * 20 if max_price else 0
    benefit_score = 0
    benefit_score += 8 if product.sale else 0
    benefit_score += 6 if product.coupon else 0
    benefit_score += 4 if product.today_delivery else 0
    benefit_score += 2 if product.gift else 0
    tag_score = len(matched_tags) * 30

    score = tag_score + rank_score + price_score + benefit_score
    reasons = [f"{', '.join(sorted(matched_tags))} 고민과 태그가 일치"]
    if product.rank:
        reasons.append(f"랭킹 {product.rank}위")
    if product.sale:
        reasons.append("세일")
    if product.coupon:
        reasons.append("쿠폰")
    if product.today_delivery:
        reasons.append("오늘드림")
    if product.current_price:
        reasons.append(f"현재가 {product.current_price:,}원")
    return round(score, 2), ", ".join(reasons)


def recommend_products(
    products: list[Product],
    skin_type: str,
    concerns: Iterable[str],
    top_k: int = 5,
) -> list[Recommendation]:
    """피부진단 결과를 받아 실제 상품 TOP5 추천을 반환합니다."""
    target_tags = normalize_concerns(concerns)
    target_tags.update(SKIN_TYPE_BONUS.get(skin_type.lower(), set()))
    max_price = max((product.current_price for product in products), default=0)

    recommendations = []
    for product in products:
        score, reason = score_product(product, target_tags, max_price)
        if score > 0:
            recommendations.append(Recommendation(product=product, score=score, reason=reason))

    recommendations.sort(key=lambda item: item.score, reverse=True)
    return recommendations[:top_k]
