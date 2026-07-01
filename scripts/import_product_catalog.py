from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from urllib.parse import unquote, urlparse


OUTPUT_FIELDS = [
    "source",
    "source_platform",
    "asin",
    "brand",
    "name",
    "category",
    "ingredients",
    "tags",
    "price",
    "rating",
    "review_count",
    "product_url",
    "image_url",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/datasets/kaggle")
    parser.add_argument("--out", default="data/manifests/product_catalog_candidates.csv")
    args = parser.parse_args()

    rows: list[dict[str, str]] = []
    for csv_path in Path(args.root).rglob("*.csv"):
        try:
            with csv_path.open(encoding="utf-8", errors="ignore", newline="") as file:
                reader = csv.DictReader(file)
                fields = {field.lower(): field for field in (reader.fieldnames or [])}
                name_key = pick_field(fields, ["product_name", "product name", "product", "name", "title"])
                product_id_key = pick_field(fields, ["asin", "product_id", "product id", "productid", "item_id", "item id"])
                brand_key = pick_field(fields, ["brand_name", "brand name", "brand"])
                ingredient_key = pick_field(fields, ["ingredients", "ingredient", "highlights"])
                category_key = pick_field(fields, ["category", "product_type", "product type", "type"])
                shade_key = pick_field(fields, ["shade", "shade_name", "shade name", "color", "colour", "hex", "hex_value", "hex value"])
                tag_key = pick_field(fields, ["tags", "tag", "labels", "label", "skin_tone", "skin tone", "undertone"])
                price_key = pick_field(fields, ["price", "sale_price", "sale price", "price_usd", "usd"])
                rating_key = pick_field(fields, ["rating", "avg_rating", "reviews_rating", "stars"])
                review_count_key = pick_field(fields, ["review_count", "review count", "reviews", "number_of_reviews", "number of reviews"])
                product_url_key = pick_field(fields, ["product_url", "product url", "url", "link", "product_link", "product link"])
                image_url_key = pick_field(fields, ["image_url", "image url", "image", "img", "picture", "photo"])
                if not name_key and not product_id_key and not product_url_key:
                    continue
                for row in reader:
                    product_url = row.get(product_url_key or "", "")
                    asin = infer_asin(row.get(product_id_key or "", ""), product_url)
                    source_platform = infer_source_platform(csv_path, product_url, asin)
                    shade = row.get(shade_key or "", "")
                    tags = merge_text(row.get(tag_key or "", ""), shade)
                    raw_name = row.get(name_key or "", "")
                    if not raw_name:
                        raw_name = name_from_url(product_url) or row.get(category_key or "", "") or asin
                    name = merge_name(raw_name, shade)
                    rows.append(
                        {
                            "source": str(csv_path),
                            "source_platform": source_platform,
                            "asin": asin,
                            "brand": row.get(brand_key or "", ""),
                            "name": name,
                            "category": row.get(category_key or "", ""),
                            "ingredients": row.get(ingredient_key or "", ""),
                            "tags": tags,
                            "price": row.get(price_key or "", ""),
                            "rating": row.get(rating_key or "", ""),
                            "review_count": row.get(review_count_key or "", ""),
                            "product_url": product_url,
                            "image_url": row.get(image_url_key or "", ""),
                        }
                    )
        except OSError:
            continue

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} product candidates to {out}")
    return 0


def pick_field(fields: dict[str, str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in fields:
            return fields[candidate]
    for candidate in candidates:
        compact = candidate.replace("_", "").replace(" ", "")
        for key, value in fields.items():
            if key.replace("_", "").replace(" ", "") == compact:
                return value
    return None


def merge_text(*values: str) -> str:
    return " | ".join(str(value).strip() for value in values if str(value).strip())


def merge_name(name: str, shade: str) -> str:
    name = str(name).strip()
    shade = str(shade).strip()
    if not shade or shade.lower() in name.lower():
        return name
    return f"{name} - {shade}"


def infer_source_platform(csv_path: Path, product_url: str, asin: str) -> str:
    text = f"{csv_path} {product_url}".lower()
    if "amazon" in text or asin:
        return "amazon"
    if "sephora" in text:
        return "sephora"
    if "dermstore" in text:
        return "dermstore"
    return ""


def infer_asin(product_id: str, product_url: str) -> str:
    product_id = str(product_id).strip()
    if re.fullmatch(r"[A-Z0-9]{10}", product_id, flags=re.IGNORECASE):
        return product_id.upper()
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", str(product_url), flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def name_from_url(product_url: str) -> str:
    try:
        path_parts = [part for part in urlparse(str(product_url)).path.split("/") if part]
    except ValueError:
        return ""
    for part in path_parts:
        if part.lower() in {"dp", "gp", "product"}:
            break
        if re.fullmatch(r"[A-Z0-9]{10}", part, flags=re.IGNORECASE):
            continue
        cleaned = unquote(part).replace("-", " ").replace("_", " ").strip()
        if len(cleaned) >= 4:
            return re.sub(r"\s+", " ", cleaned)
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
