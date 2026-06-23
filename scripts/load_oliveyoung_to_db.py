from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))


INGREDIENT_RULES = {
    "Niacinamide": ("Helps balance sebum, pores, tone, and barrier support.", "oiliness,pore,pigmentation,redness", ("niacinamide", "tone up", "toning")),
    "Salicylic Acid": ("BHA used for acne-prone skin, clogged pores, and oiliness.", "acne,pore,oiliness", ("salicylic", "bha", "trouble", "acne", "pimple", "spot patch")),
    "Centella Asiatica": ("Soothing ingredient used for redness and sensitive skin.", "redness,acne", ("centella", "cica", "madecassoside", "soothing")),
    "Retinol": ("Vitamin A derivative used for wrinkles and texture care.", "wrinkle,pore,pigmentation", ("retinol", "retinal", "retinyl")),
    "Hyaluronic Acid": ("Hydration support for dehydrated or barrier-weakened skin.", "wrinkle,redness", ("hyaluronic", "hydrating", "hydration", "moisture", "aqua")),
    "Vitamin C": ("Brightening antioxidant used for dullness and pigmentation.", "pigmentation,wrinkle", ("vitamin c", "vita", "bright", "glow", "dark spot")),
    "Ceramide": ("Barrier lipid helpful for dry, sensitive, and irritated skin.", "redness,wrinkle", ("ceramide", "barrier")),
    "Glycolic Acid": ("AHA exfoliant used for texture and pigmentation care.", "pigmentation,pore,wrinkle", ("glycolic", "aha", "peeling", "peel")),
    "Lactic Acid": ("Gentle AHA used for texture, dullness, and hydration support.", "pigmentation,pore,wrinkle", ("lactic",)),
    "Azelaic Acid": ("Ingredient used for redness, blemishes, and uneven tone.", "redness,acne,pigmentation", ("azelaic",)),
    "Panthenol": ("Barrier and soothing support for sensitive skin.", "redness,wrinkle", ("panthenol", "panthecell", "pantenol")),
    "Green Tea": ("Antioxidant and soothing botanical for oily or red skin.", "oiliness,redness,acne", ("green tea", "tea tree")),
    "Zinc": ("Sebum and blemish support often used for oily skin.", "oiliness,acne", ("zinc", "sebum")),
    "Peptide": ("Firming support used in wrinkle care products.", "wrinkle", ("peptide", "collagen", "lifting", "firming", "probioderm")),
}

SKINCARE_WORDS = (
    "ampoule", "balm", "barrier", "bright", "cica", "cleanser", "cream", "essence",
    "exfol", "gel", "hydr", "lotion", "mask", "mist", "moistur", "pad", "peel",
    "pore", "serum", "skin care", "skincare", "spot", "sun", "sunscreen", "spf",
    "toner", "treatment", "wrinkle",
)

MAKEUP_WORDS = (
    "bb", "blush", "blusher", "brow", "conceal", "contour", "eyeliner", "eye liner",
    "foundation", "highlighter", "lip", "mascara", "nail", "palette", "tint",
)


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("&trade;", "TM")).strip()


def parse_int(value: object) -> int:
    text = normalize_text(value)
    digits = re.sub(r"[^0-9.]", "", text)
    if not digits:
        return 0
    try:
        return int(float(digits))
    except ValueError:
        return 0


def parse_float(value: object) -> float:
    text = normalize_text(value)
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def is_skincare(row: dict[str, str]) -> bool:
    haystack = " ".join(
        normalize_text(row.get(field, "")).lower()
        for field in ("prdtName", "prdtNameEn", "category", "subCategory")
    )
    if "skin care" in haystack or "skincare" in haystack:
        return True
    if any(word in haystack for word in SKINCARE_WORDS):
        return not any(word in haystack for word in MAKEUP_WORDS)
    return False


def detect_ingredients(row: dict[str, str]) -> list[str]:
    haystack = " ".join(
        normalize_text(row.get(field, "")).lower()
        for field in ("brandName", "prdtName", "prdtNameEn", "category", "subCategory")
    )
    found = [
        ingredient_name
        for ingredient_name, (_, _, needles) in INGREDIENT_RULES.items()
        if any(needle in haystack for needle in needles)
    ]

    if found:
        return list(dict.fromkeys(found))

    if any(word in haystack for word in ("cleanser", "cleansing", "pore")):
        return ["Salicylic Acid", "Centella Asiatica"]
    if any(word in haystack for word in ("cream", "lotion", "moisture", "hydrating", "toner")):
        return ["Hyaluronic Acid", "Panthenol"]
    if any(word in haystack for word in ("sunscreen", "sun cream", "spf")):
        return ["Niacinamide", "Vitamin C"]
    if any(word in haystack for word in ("mask", "pad", "ampoule", "serum")):
        return ["Niacinamide", "Hyaluronic Acid"]
    return []


def infer_skin_types(ingredient_names: list[str]) -> str:
    targets = set()
    for ingredient_name in dict.fromkeys(ingredient_names):
        targets.update(INGREDIENT_RULES[ingredient_name][1].split(","))

    skin_types = {"all"}
    if {"oiliness", "acne", "pore"} & targets:
        skin_types.update(["oily", "combination"])
    if {"redness", "wrinkle"} & targets:
        skin_types.update(["dry", "sensitive"])
    if "pigmentation" in targets:
        skin_types.update(["normal", "dry"])
    return ",".join(sorted(skin_types))


def bootstrap_backend(database_url: str | None) -> None:
    if database_url:
        os.environ["DATABASE_URL"] = database_url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="data/manifests/oy_recommendation_products.csv")
    parser.add_argument("--database-url", default="", help="Optional DB URL override, e.g. sqlite:///./beautyai.db")
    parser.add_argument("--limit", type=int, default=0, help="Max rows to import, 0 means all")
    args = parser.parse_args()

    bootstrap_backend(args.database_url)

    from app.core.database import Base, SessionLocal, engine
    from app.models import Brand, Ingredient, Product, ProductIngredient

    catalog_path = PROJECT_ROOT / args.catalog
    if not catalog_path.exists():
        raise SystemExit(f"Catalog not found: {catalog_path}")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    brand_cache = {brand.name: brand for brand in db.query(Brand).all()}
    ingredient_cache = {ingredient.name: ingredient for ingredient in db.query(Ingredient).all()}
    existing_products = {
        (product.brand.name.lower(), product.name.lower())
        for product in db.query(Product).join(Brand).all()
    }
    linked_pairs = {
        (item.product_id, item.ingredient_id)
        for item in db.query(ProductIngredient).all()
    }

    imported = 0
    updated = 0
    skipped = 0
    scanned = 0
    try:
        with catalog_path.open(encoding="utf-8-sig", errors="ignore", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                scanned += 1
                name = normalize_text(row.get("prdtName") or row.get("prdtNameEn"))
                brand_name = normalize_text(row.get("brandName"))
                if not name or not brand_name or not is_skincare(row):
                    skipped += 1
                    continue

                ingredient_names = list(dict.fromkeys(detect_ingredients(row)))
                if not ingredient_names:
                    skipped += 1
                    continue

                brand = brand_cache.get(brand_name)
                if brand is None:
                    brand = Brand(name=brand_name, description=f"{brand_name} Olive Young Global source")
                    db.add(brand)
                    db.flush()
                    brand_cache[brand_name] = brand

                key = (brand_name.lower(), name.lower())
                price = parse_int(row.get("saleAmt") or row.get("nrmlAmt"))
                rating = parse_float(row.get("avgRating"))
                review_count = parse_int(row.get("reviewCount"))
                product_url = normalize_text(row.get("productUrl"))
                image_url = normalize_text(row.get("imageUrl"))
                description = "Olive Young Global skincare product"
                if rating:
                    description += f" with Olive Young rating {rating:.1f}"
                if review_count:
                    description += f" from {review_count} reviews"

                if key in existing_products:
                    product = (
                        db.query(Product)
                        .join(Brand)
                        .filter(Brand.name == brand_name, Product.name == name)
                        .one()
                    )
                    product.category = normalize_text(row.get("subCategory") or row.get("category")) or product.category
                    product.skin_types = infer_skin_types(ingredient_names)
                    product.price = price or product.price
                    product.description = description
                    product.product_url = product_url or product.product_url
                    product.image_url = image_url or product.image_url
                    product.avg_rating = rating or product.avg_rating
                    product.review_count = review_count or product.review_count
                    updated += 1
                else:
                    product = Product(
                        brand=brand,
                        name=name,
                        category=normalize_text(row.get("subCategory") or row.get("category")) or "skincare",
                        skin_types=infer_skin_types(ingredient_names),
                        price=price,
                        description=description,
                        product_url=product_url,
                        image_url=image_url,
                        avg_rating=rating,
                        review_count=review_count,
                    )
                    db.add(product)
                    db.flush()
                    existing_products.add(key)
                    imported += 1

                for ingredient_name in ingredient_names:
                    ingredient = ingredient_cache.get(ingredient_name)
                    if ingredient is None:
                        benefit, targets, _ = INGREDIENT_RULES[ingredient_name]
                        ingredient = Ingredient(name=ingredient_name, benefit=benefit, targets=targets)
                        db.add(ingredient)
                        db.flush()
                        ingredient_cache[ingredient_name] = ingredient

                    pair = (product.id, ingredient.id)
                    if pair not in linked_pairs:
                        db.add(ProductIngredient(product_id=product.id, ingredient_id=ingredient.id, weight=1.0))
                        linked_pairs.add(pair)

                if args.limit and imported + updated >= args.limit:
                    break

        db.commit()
    finally:
        db.close()

    print(f"Scanned {scanned} rows. Imported {imported}, updated {updated}, skipped {skipped}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
