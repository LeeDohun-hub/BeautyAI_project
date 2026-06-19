from __future__ import annotations

import argparse
import ast
import csv
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import Base, SessionLocal, engine
from app.models import Brand, Ingredient, Product, ProductIngredient


INGREDIENT_RULES = {
    "Niacinamide": ("Helps balance sebum, pores, tone, and barrier support.", "oiliness,pore,pigmentation,redness", ("niacinamide",)),
    "Salicylic Acid": ("BHA used for acne-prone skin, clogged pores, and oiliness.", "acne,pore,oiliness", ("salicylic acid", "bha")),
    "Centella Asiatica": ("Soothing ingredient used for redness and sensitive skin.", "redness,acne", ("centella", "cica", "madecassoside")),
    "Retinol": ("Vitamin A derivative used for wrinkles and texture care.", "wrinkle,pore,pigmentation", ("retinol", "retinal", "retinyl")),
    "Hyaluronic Acid": ("Hydration support for dehydrated or barrier-weakened skin.", "wrinkle,redness", ("hyaluronic", "sodium hyaluronate")),
    "Vitamin C": ("Brightening antioxidant used for dullness and pigmentation.", "pigmentation,wrinkle", ("ascorbic acid", "vitamin c", "ascorbyl")),
    "Ceramide": ("Barrier lipid helpful for dry, sensitive, and irritated skin.", "redness,wrinkle", ("ceramide",)),
    "Glycolic Acid": ("AHA exfoliant used for texture and pigmentation care.", "pigmentation,pore,wrinkle", ("glycolic acid",)),
    "Lactic Acid": ("Gentle AHA used for texture, dullness, and hydration support.", "pigmentation,pore,wrinkle", ("lactic acid",)),
    "Azelaic Acid": ("Ingredient used for redness, blemishes, and uneven tone.", "redness,acne,pigmentation", ("azelaic acid",)),
    "Panthenol": ("Barrier and soothing support for sensitive skin.", "redness,wrinkle", ("panthenol",)),
    "Green Tea": ("Antioxidant and soothing botanical for oily or red skin.", "oiliness,redness,acne", ("green tea", "camellia sinensis")),
    "Zinc": ("Sebum and blemish support often used for oily skin.", "oiliness,acne", ("zinc",)),
    "Peptide": ("Firming support used in wrinkle care products.", "wrinkle", ("peptide", "palmitoyl")),
}

SKINCARE_WORDS = (
    "serum",
    "cream",
    "moistur",
    "toner",
    "cleanser",
    "sunscreen",
    "spf",
    "mask",
    "essence",
    "ampoule",
    "lotion",
    "gel",
    "balm",
    "treatment",
    "exfol",
    "peel",
    "acne",
    "pore",
    "wrinkle",
    "bright",
    "hydr",
)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = str(value).strip()
    if value.lower() in {"nan", "none", "null"}:
        return ""
    return re.sub(r"\s+", " ", value)


def clean_brand(value: str) -> str:
    value = normalize_text(value)
    if not value or value.isdigit():
        return "Unknown"
    return value[:120]


def clean_name(value: str) -> str:
    return normalize_text(value)[:180]


def parse_ingredient_blob(value: str) -> str:
    value = normalize_text(value)
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value
        if isinstance(parsed, list):
            return ", ".join(str(item) for item in parsed)
    return value


def detect_ingredients(name: str, ingredients: str) -> list[str]:
    haystack = f"{name} {ingredients}".lower()
    found = []
    for ingredient_name, (_, _, needles) in INGREDIENT_RULES.items():
        if any(needle in haystack for needle in needles):
            found.append(ingredient_name)
    return found


def infer_category(name: str) -> str:
    lower = name.lower()
    for category in ["serum", "cream", "toner", "cleanser", "sunscreen", "mask", "essence", "ampoule", "lotion", "gel", "balm", "treatment"]:
        if category in lower:
            return category
    return "skincare"


def infer_skin_types(ingredients: list[str]) -> str:
    targets = set()
    for ingredient in ingredients:
        targets.update(INGREDIENT_RULES[ingredient][1].split(","))
    skin_types = {"all"}
    if {"oiliness", "acne", "pore"} & targets:
        skin_types.update(["oily", "combination"])
    if {"redness", "wrinkle"} & targets:
        skin_types.update(["dry", "sensitive"])
    if "pigmentation" in targets:
        skin_types.update(["normal", "dry"])
    return ",".join(sorted(skin_types))


def is_skincare_candidate(name: str, ingredients: str) -> bool:
    haystack = f"{name} {ingredients}".lower()
    return any(word in haystack for word in SKINCARE_WORDS)


def ensure_ingredient(db, cache: dict[str, Ingredient], name: str) -> Ingredient:
    if name in cache:
        return cache[name]
    existing = db.query(Ingredient).filter(Ingredient.name == name).one_or_none()
    if existing:
        cache[name] = existing
        return existing
    benefit, targets, _ = INGREDIENT_RULES[name]
    ingredient = Ingredient(name=name, benefit=benefit, targets=targets)
    db.add(ingredient)
    db.flush()
    cache[name] = ingredient
    return ingredient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="data/manifests/product_catalog_candidates.csv")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

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

    imported = 0
    scanned = 0
    seen = set(existing_products)
    try:
        with catalog_path.open(encoding="utf-8", errors="ignore", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                scanned += 1
                name = clean_name(row.get("name", ""))
                if not name:
                    continue
                brand_name = clean_brand(row.get("brand", ""))
                ingredients_blob = parse_ingredient_blob(row.get("ingredients", ""))
                if not is_skincare_candidate(name, ingredients_blob):
                    continue
                ingredient_names = detect_ingredients(name, ingredients_blob)
                if not ingredient_names:
                    continue
                key = (brand_name.lower(), name.lower())
                if key in seen:
                    continue
                seen.add(key)

                brand = brand_cache.get(brand_name)
                if brand is None:
                    brand = Brand(name=brand_name, description=f"{brand_name} skincare product source")
                    db.add(brand)
                    db.flush()
                    brand_cache[brand_name] = brand

                rating = normalize_text(row.get("rating", ""))
                description = "Imported skincare product"
                if rating:
                    description += f" with source rating {rating}"
                product = Product(
                    brand=brand,
                    name=name,
                    category=infer_category(name),
                    skin_types=infer_skin_types(ingredient_names),
                    price=0,
                    description=description,
                )
                db.add(product)
                db.flush()
                for ingredient_name in ingredient_names:
                    ingredient = ensure_ingredient(db, ingredient_cache, ingredient_name)
                    db.add(ProductIngredient(product=product, ingredient=ingredient, weight=1.0))
                imported += 1

                if imported % args.batch_size == 0:
                    db.commit()
                    print(f"imported={imported} scanned={scanned}")
                if imported >= args.limit:
                    break
        db.commit()
    finally:
        db.close()

    print(f"Imported {imported} products from {scanned} scanned rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
