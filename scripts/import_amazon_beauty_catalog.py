from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


FIELDNAMES = [
    "source",
    "product_id",
    "brand",
    "name",
    "category",
    "price",
    "ingredients",
    "rating",
    "review_count",
    "description",
    "tags",
    "product_url",
    "image_url",
]

TAG_RULES = {
    "acne": ("acne", "blemish", "breakout", "pimple", "spot", "여드름", "트러블"),
    "pore": ("pore", "pores", "blackhead", "whitehead", "모공"),
    "oiliness": ("oil", "oily", "sebum", "shine", "matte", "지성", "유분", "피지"),
    "redness": ("redness", "red", "sensitive", "calming", "soothing", "cica", "centella", "민감", "진정", "홍조"),
    "pigmentation": ("bright", "brightening", "dark spot", "hyperpigmentation", "vitamin c", "tone", "색소", "미백"),
    "wrinkle": ("wrinkle", "anti-aging", "retinol", "firming", "fine line", "elastic", "주름", "탄력"),
}

SKINCARE_CATEGORIES = {
    "toner": ("toner", "skin toner", "스킨", "토너"),
    "lotion": ("lotion", "emulsion", "로션", "에멀전"),
    "serum": ("serum", "ampoule", "essence", "세럼", "앰플", "에센스"),
    "cream": ("cream", "moisturizer", "크림", "보습"),
    "spot": ("spot", "patch", "blemish", "acne", "스팟", "패치", "트러블"),
    "cleanser": ("cleanser", "cleansing", "wash", "foam", "클렌저", "클렌징"),
    "sunscreen": ("sunscreen", "spf", "sunblock", "선크림", "자외선"),
    "mask": ("mask", "sheet mask", "마스크", "팩"),
}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(normalize_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {normalize_text(item)}" for key, item in value.items())
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "[]", "{}"}:
        return ""
    return re.sub(r"\s+", " ", text)


def pick(row: dict[str, Any], candidates: Iterable[str]) -> Any:
    lowered = {key.lower().replace("_", "").replace(" ", ""): key for key in row}
    for candidate in candidates:
        key = lowered.get(candidate.lower().replace("_", "").replace(" ", ""))
        if key is not None:
            return row.get(key)
    return ""


def parse_price(value: Any) -> int:
    if isinstance(value, (int, float)) and value == value:
        return int(float(value))
    digits = re.sub(r"[^0-9.]", "", normalize_text(value))
    if not digits:
        return 0
    try:
        return int(float(digits))
    except ValueError:
        return 0


def parse_rating(value: Any) -> float:
    try:
        rating = float(value)
    except (TypeError, ValueError):
        return 0.0
    if rating != rating:
        return 0.0
    return round(rating, 3)


def iter_rows(path: Path) -> Iterable[dict[str, Any]]:
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".csv"):
        with path.open(encoding="utf-8", errors="ignore", newline="") as file:
            yield from csv.DictReader(file)
        return

    if ".json" in suffixes:
        if suffixes.endswith(".gz"):
            file_context = gzip.open(path, "rt", encoding="utf-8-sig", errors="ignore")
        else:
            file_context = path.open("r", encoding="utf-8-sig", errors="ignore")
        with file_context as file:
            first = file.read(1)
            file.seek(0)
            if first == "[":
                payload = json.load(file)
                if isinstance(payload, list):
                    for item in payload:
                        if isinstance(item, dict):
                            yield item
                return
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    yield item


def iter_data_files(root: Path) -> Iterable[Path]:
    for pattern in ("*.csv", "*.json", "*.jsonl", "*.json.gz", "*.jsonl.gz"):
        yield from root.rglob(pattern)


def infer_category(text: str) -> str:
    lower = text.lower()
    for category, keywords in SKINCARE_CATEGORIES.items():
        if any(keyword in lower for keyword in keywords):
            return category
    return "skincare"


def infer_tags(text: str) -> list[str]:
    lower = text.lower()
    tags = [
        tag
        for tag, keywords in TAG_RULES.items()
        if any(keyword in lower for keyword in keywords)
    ]
    return sorted(set(tags))


def is_beauty_or_skincare(text: str) -> bool:
    lower = text.lower()
    beauty_words = (
        "beauty",
        "skin",
        "skincare",
        "face",
        "facial",
        "serum",
        "cream",
        "toner",
        "lotion",
        "cleanser",
        "moistur",
        "sunscreen",
        "mask",
        "acne",
        "pore",
        "wrinkle",
        "retinol",
    )
    return any(word in lower for word in beauty_words)


def collect_review_stats(root: Path, max_rows: int) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"rating_sum": 0.0, "review_count": 0, "reviews": []})
    scanned = 0

    for path in iter_data_files(root):
        for row in iter_rows(path):
            product_id = normalize_text(pick(row, ["asin", "product_id", "productid", "productId", "ProductId"]))
            rating = parse_rating(pick(row, ["overall", "rating", "Rating", "stars"]))
            if not product_id or rating <= 0:
                continue
            text = normalize_text(pick(row, ["reviewText", "review_text", "summary", "review", "Review"]))
            stats[product_id]["rating_sum"] += rating
            stats[product_id]["review_count"] += 1
            if text and len(stats[product_id]["reviews"]) < 5:
                stats[product_id]["reviews"].append(text[:400])
            scanned += 1
            if scanned >= max_rows:
                return stats
    return stats


def build_catalog(root: Path, max_rows: int, max_review_rows: int) -> list[dict[str, str]]:
    review_stats = collect_review_stats(root, max_rows=max_review_rows)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    scanned = 0

    for path in iter_data_files(root):
        for row in iter_rows(path):
            product_id = normalize_text(pick(row, ["asin", "product_id", "productid", "productId", "ProductId"]))
            name = normalize_text(pick(row, ["title", "product_name", "product name", "name", "productName"]))
            brand = normalize_text(pick(row, ["brand", "brand_name", "manufacturer"]))
            description = normalize_text(pick(row, ["description", "details", "about_product", "feature", "features"]))
            categories = normalize_text(pick(row, ["categories", "category", "main_cat", "main_category"]))

            if not name:
                continue

            key = product_id or f"{brand}:{name}".lower()
            if key in seen:
                continue

            searchable = " ".join(
                [
                    name,
                    brand,
                    description,
                    categories,
                    " ".join(review_stats.get(product_id, {}).get("reviews", [])),
                ]
            )
            if not is_beauty_or_skincare(searchable):
                continue

            tags = infer_tags(searchable)
            if not tags:
                continue

            stats = review_stats.get(product_id, {})
            review_count = int(stats.get("review_count", 0) or 0)
            rating_sum = float(stats.get("rating_sum", 0.0) or 0.0)
            rating = rating_sum / review_count if review_count else parse_rating(pick(row, ["rating", "average_rating", "stars"]))

            rows.append(
                {
                    "source": str(path),
                    "product_id": product_id,
                    "brand": brand or "Unknown",
                    "name": name[:180],
                    "category": infer_category(searchable),
                    "price": str(parse_price(pick(row, ["price", "current_price", "actual_price"]))),
                    "ingredients": normalize_text(pick(row, ["ingredients", "ingredient"]))[:1000],
                    "rating": f"{rating:.3f}" if rating else "",
                    "review_count": str(review_count),
                    "description": description[:1000],
                    "tags": "|".join(tags),
                    "product_url": f"https://www.amazon.com/dp/{product_id}" if product_id else "",
                    "image_url": normalize_text(pick(row, ["imUrl", "image", "image_url", "imgUrl"])),
                }
            )
            seen.add(key)
            scanned += 1
            if scanned >= max_rows:
                return rows

    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Amazon Beauty metadata/reviews into a skincare product catalog.")
    parser.add_argument("--root", default="data/datasets/kaggle")
    parser.add_argument("--out", default="data/manifests/amazon_beauty_catalog.csv")
    parser.add_argument("--max-rows", type=int, default=200000)
    parser.add_argument("--max-review-rows", type=int, default=500000)
    args = parser.parse_args()

    root = Path(args.root)
    rows = build_catalog(root=root, max_rows=args.max_rows, max_review_rows=args.max_review_rows)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} Amazon Beauty catalog rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
