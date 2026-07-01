from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))


BRAND_FIELDS = ("brandName", "brand_name", "brand name", "brand")
NAME_FIELDS = ("prdtName", "prdtNameEn", "product_name", "product name", "product", "name", "title")
IMAGE_FIELDS = ("imageUrl", "image_url", "image url", "image", "img", "picture", "photo", "thumbnail")
URL_FIELDS = ("productUrl", "product_url", "product url", "url", "link", "product_link", "product link")

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "set",
    "new",
    "official",
    "shop",
    "shopping",
    "product",
    "cosmetic",
    "cosmetics",
}


@dataclass(frozen=True)
class ImageCandidate:
    source: str
    brand: str
    name: str
    image_url: str
    product_url: str
    brand_key: str
    name_key: str
    tokens: frozenset[str]


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    if value.lower() in {"nan", "none", "null"}:
        return ""
    return re.sub(r"\s+", " ", value)


def normalize_key(value: str) -> str:
    value = normalize_text(value).lower()
    value = re.sub(r"[^0-9a-z가-힣ぁ-んァ-ン一-龥]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in normalize_key(value).split()
        if len(token) >= 2 and token not in STOPWORDS
    )


def first_value(row: dict[str, str], fields: tuple[str, ...]) -> str:
    lower_map = {key.lower(): key for key in row}
    for field in fields:
        key = lower_map.get(field.lower())
        if key and normalize_text(row.get(key)):
            return normalize_text(row.get(key))
    return ""


def is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def load_candidates(paths: list[Path]) -> list[ImageCandidate]:
    candidates: list[ImageCandidate] = []
    seen: set[tuple[str, str, str]] = set()

    for root in paths:
        if not root.exists():
            continue
        files = [root] if root.is_file() else list(root.rglob("*.csv"))
        for csv_path in files:
            try:
                with csv_path.open(encoding="utf-8-sig", errors="ignore", newline="") as file:
                    reader = csv.DictReader(file)
                    field_names = tuple(reader.fieldnames or ())
                    lower_fields = {field.lower() for field in field_names}
                    if not any(field.lower() in lower_fields for field in IMAGE_FIELDS):
                        continue
                    for row in reader:
                        image_url = first_value(row, IMAGE_FIELDS)
                        if not is_http_url(image_url):
                            continue
                        brand = first_value(row, BRAND_FIELDS)
                        name = first_value(row, NAME_FIELDS)
                        product_url = first_value(row, URL_FIELDS)
                        if not name:
                            continue

                        brand_key = normalize_key(brand)
                        name_key = normalize_key(name)
                        token_set = tokens(f"{brand} {name}")
                        if len(token_set) < 2:
                            continue

                        dedupe_key = (brand_key, name_key, image_url)
                        if dedupe_key in seen:
                            continue
                        seen.add(dedupe_key)
                        candidates.append(
                            ImageCandidate(
                                source=str(csv_path.relative_to(PROJECT_ROOT)),
                                brand=brand,
                                name=name,
                                image_url=image_url,
                                product_url=product_url,
                                brand_key=brand_key,
                                name_key=name_key,
                                tokens=token_set,
                            )
                        )
            except OSError:
                continue

    return candidates


def candidate_score(product_brand: str, product_name: str, candidate: ImageCandidate) -> float:
    product_brand_key = normalize_key(product_brand)
    product_name_key = normalize_key(product_name)
    product_tokens = tokens(f"{product_brand} {product_name}")
    if not product_tokens:
        return 0.0

    if product_brand_key and candidate.brand_key and not (
        product_brand_key == candidate.brand_key
        or product_brand_key in candidate.brand_key
        or candidate.brand_key in product_brand_key
    ):
        return 0.0

    overlap = len(product_tokens.intersection(candidate.tokens))
    union = len(product_tokens.union(candidate.tokens))
    token_score = overlap / union if union else 0.0

    brand_score = 0.0
    if product_brand_key and candidate.brand_key:
        if product_brand_key == candidate.brand_key:
            brand_score = 0.28
        elif product_brand_key in candidate.brand_key or candidate.brand_key in product_brand_key:
            brand_score = 0.18

    name_score = 0.0
    if product_name_key == candidate.name_key:
        name_score = 0.35
    elif product_name_key and candidate.name_key and (
        product_name_key in candidate.name_key or candidate.name_key in product_name_key
    ):
        name_score = 0.22

    return min(1.0, token_score * 0.7 + brand_score + name_score)


def build_candidate_index(candidates: list[ImageCandidate]) -> dict[str, list[ImageCandidate]]:
    index: dict[str, list[ImageCandidate]] = {}
    for candidate in candidates:
        for token in candidate.tokens:
            index.setdefault(token, []).append(candidate)
    return index


def candidate_pool(
    product_brand: str,
    product_name: str,
    index: dict[str, list[ImageCandidate]],
) -> list[ImageCandidate]:
    product_tokens = tokens(f"{product_brand} {product_name}")
    ranked: dict[ImageCandidate, int] = {}
    for token in product_tokens:
        for candidate in index.get(token, []):
            ranked[candidate] = ranked.get(candidate, 0) + 1
    return [
        candidate
        for candidate, _count in sorted(ranked.items(), key=lambda item: item[1], reverse=True)[:250]
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--roots",
        nargs="*",
        default=["data/manifests"],
        help="CSV files or directories to scan for image URLs.",
    )
    parser.add_argument("--database-url", default="", help="Optional DB URL override.")
    parser.add_argument("--min-score", type=float, default=0.72)
    parser.add_argument("--limit", type=int, default=0, help="Max products to update, 0 = no limit.")
    parser.add_argument("--apply", action="store_true", help="Write updates. Omit for dry-run.")
    args = parser.parse_args()

    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    from app.core.database import SessionLocal
    from app.models import Product

    roots = [PROJECT_ROOT / path for path in args.roots]
    candidates = load_candidates(roots)
    candidate_index = build_candidate_index(candidates)
    print(f"Loaded {len(candidates)} image candidates.")

    db = SessionLocal()
    matched = 0
    scanned = 0
    examples: list[tuple[str, str, float, str, str]] = []
    try:
        products = (
            db.query(Product)
            .filter((Product.image_url == "") | (Product.image_url.is_(None)))
            .all()
        )
        for product in products:
            scanned += 1
            best: tuple[float, ImageCandidate] | None = None
            product_brand = product.brand.name if product.brand else ""
            for candidate in candidate_pool(product_brand, product.name, candidate_index):
                score = candidate_score(product_brand, product.name, candidate)
                if score >= args.min_score and (best is None or score > best[0]):
                    best = (score, candidate)

            if best is None:
                continue

            score, candidate = best
            matched += 1
            if len(examples) < 10:
                examples.append((product_brand, product.name, score, candidate.name, candidate.image_url))
            if args.apply:
                product.image_url = candidate.image_url
            if args.limit and matched >= args.limit:
                break

        if args.apply:
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()

    mode = "updated" if args.apply else "matched(dry-run)"
    print(f"{mode}={matched} scanned_products_without_images={scanned}")
    for brand, name, score, candidate_name, image_url in examples:
        print(f"- {brand} / {name} -> {candidate_name} ({score:.2f}) {image_url}")
    if not args.apply:
        print("Dry-run only. Re-run with --apply to write image_url updates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
