from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings


@dataclass(frozen=True)
class MatsukiyoMatch:
    brand: str
    name: str
    product_url: str
    image_url: str | None
    score: float


@dataclass(frozen=True)
class _MatsukiyoItem:
    brand: str
    name: str
    product_url: str
    image_url: str | None
    brand_key: str
    tokens: frozenset[str]


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "official",
    "shop",
    "shopping",
    "product",
    "cosme",
    "cosmetic",
    "cosmetics",
}


def normalize_key(value: str) -> str:
    value = str(value or "").lower()
    value = re.sub(r"[^0-9a-z가-힣ぁ-んァ-ン一-龥]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens_for(*values: str) -> frozenset[str]:
    return frozenset(
        token
        for token in normalize_key(" ".join(values)).split()
        if len(token) >= 2 and token not in STOPWORDS
    )


@lru_cache(maxsize=1)
def _load_items() -> tuple[_MatsukiyoItem, ...]:
    path = get_settings().project_root / "data" / "manifests" / "matsukiyo_products.csv"
    if not path.exists():
        return ()

    items: list[_MatsukiyoItem] = []
    with path.open(encoding="utf-8-sig", errors="ignore", newline="") as file:
        for row in csv.DictReader(file):
            brand = str(row.get("brandName") or "").strip()
            name = str(row.get("prdtName") or "").strip()
            product_url = str(row.get("productUrl") or "").strip()
            if not name or "matsukiyococokara" not in product_url:
                continue
            items.append(
                _MatsukiyoItem(
                    brand=brand,
                    name=name,
                    product_url=product_url,
                    image_url=str(row.get("imageUrl") or "").strip() or None,
                    brand_key=normalize_key(brand),
                    tokens=tokens_for(brand, name),
                )
            )
    return tuple(items)


def match_matsukiyo_product(brand: str, name: str, min_score: float = 0.58) -> MatsukiyoMatch | None:
    product_brand_key = normalize_key(brand)
    product_tokens = tokens_for(brand, name)
    if not product_tokens:
        return None

    best: MatsukiyoMatch | None = None
    for item in _load_items():
        if product_brand_key and item.brand_key and not (
            product_brand_key == item.brand_key
            or product_brand_key in item.brand_key
            or item.brand_key in product_brand_key
        ):
            continue

        overlap = len(product_tokens.intersection(item.tokens))
        if overlap == 0:
            continue
        union = len(product_tokens.union(item.tokens))
        score = overlap / union if union else 0.0
        if product_brand_key and item.brand_key:
            score += 0.25
        if score < min_score:
            continue

        candidate = MatsukiyoMatch(
            brand=item.brand,
            name=item.name,
            product_url=item.product_url,
            image_url=item.image_url,
            score=round(min(1.0, score), 3),
        )
        if best is None or candidate.score > best.score:
            best = candidate
    return best

