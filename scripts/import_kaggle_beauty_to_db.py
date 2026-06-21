"""Import Amazon Beauty products from Kaggle dataset into the BeautyAI database.

Dataset: satrapankti/amazon-beauty-product-recommendation
Format: UserId, ProductId, ProductType, Rating, Timestamp, URL

Strategy:
  - Only import products where a real product name can be extracted from the URL slug
  - Use the URL-embedded ASIN (not ProductId) as the product identifier
  - This ensures all imported products have readable names and valid Amazon.com links

Usage:
    python scripts/import_kaggle_beauty_to_db.py [--csv PATH]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.database import Base, SessionLocal, engine
from app.models import Brand, Ingredient, Product, ProductIngredient
from app.services.seed import INGREDIENTS, REAL_PRODUCTS, seed_database

DEFAULT_CSV = (
    Path.home()
    / ".cache/kagglehub/datasets/satrapankti"
    / "amazon-beauty-product-recommendation/versions/1"
    / "Amazon_Beauty_Recommendation.csv"
)

SKINCARE_TYPES: dict[str, str] = {
    "Face Serum": "serum",
    "Cream & Moisturizer": "cream",
    "Face Wash & Cleansers": "cleanser",
    "Sunscreen": "sunscreen",
    "Sheet Mask": "mask",
    "Body Lotion": "lotion",
    "Body Scrubs": "treatment",
}

CATEGORY_BASE_INGREDIENTS: dict[str, list[str]] = {
    "serum": ["Hyaluronic Acid"],
    "cream": ["Ceramide", "Hyaluronic Acid"],
    "cleanser": ["Centella Asiatica"],
    "sunscreen": ["Niacinamide", "Hyaluronic Acid"],
    "mask": ["Centella Asiatica", "Hyaluronic Acid"],
    "lotion": ["Ceramide"],
    "treatment": ["Glycolic Acid"],
}

NAME_INGREDIENT_MAP: dict[str, str] = {
    "niacinamide": "Niacinamide",
    "vitamin c": "Vitamin C",
    "ascorbic": "Vitamin C",
    "retinol": "Retinol",
    "retinyl": "Retinol",
    "salicylic": "Salicylic Acid",
    "bha": "Salicylic Acid",
    "hyaluronic": "Hyaluronic Acid",
    "ceramide": "Ceramide",
    "centella": "Centella Asiatica",
    "cica": "Centella Asiatica",
    "glycolic": "Glycolic Acid",
    "aha": "Glycolic Acid",
    "lactic": "Lactic Acid",
    "azelaic": "Azelaic Acid",
    "panthenol": "Panthenol",
    "green tea": "Green Tea",
    "camellia": "Green Tea",
    "peptide": "Peptide",
    "palmitoyl": "Peptide",
    "zinc": "Zinc",
    "brightening": "Vitamin C",
    "whitening": "Vitamin C",
    "anti aging": "Retinol",
    "anti-aging": "Retinol",
    "acne": "Salicylic Acid",
    "pore": "Niacinamide",
    "soothing": "Centella Asiatica",
    "calming": "Centella Asiatica",
    "spf": "Niacinamide",
}

CATEGORY_SKIN_TYPES: dict[str, str] = {
    "serum": "all",
    "cream": "dry,sensitive,all",
    "cleanser": "oily,combination,all",
    "sunscreen": "all",
    "mask": "all",
    "lotion": "dry,sensitive,all",
    "treatment": "oily,combination,normal",
}


def extract_asin_from_url(url: str) -> str:
    if not isinstance(url, str):
        return ""
    m = re.search(r"/dp/([A-Z0-9]{10})", url)
    return m.group(1) if m else ""


def extract_name_from_url(url: str) -> str:
    if not isinstance(url, str):
        return ""
    m = re.search(r"amazon\.\w+/([^/?#]+)/dp/", url)
    if not m:
        return ""
    slug = m.group(1).replace("-", " ").replace("+", " ")
    return re.sub(r"\s+", " ", slug).strip()[:180]


def title_case(name: str) -> str:
    return " ".join(w.capitalize() if w.islower() else w for w in name.split())


def extract_brand_from_name(name: str) -> str:
    if not name:
        return "Unknown"
    return name.split()[0][:120]


def infer_ingredients(name: str, category: str) -> list[str]:
    name_lower = name.lower()
    found: list[str] = []
    for keyword, ingredient in NAME_INGREDIENT_MAP.items():
        if keyword in name_lower and ingredient not in found:
            found.append(ingredient)
    if not found:
        found = list(CATEGORY_BASE_INGREDIENTS.get(category, []))
    return found[:5]


def build_description(name: str, category: str, avg_rating: float, review_count: int) -> str:
    cat_label = {
        "serum": "face serum", "cream": "moisturizer", "cleanser": "facial cleanser",
        "sunscreen": "sunscreen", "mask": "sheet mask", "lotion": "body lotion",
        "treatment": "exfoliating treatment",
    }.get(category, "beauty product")
    desc = f"{name} — Amazon Beauty {cat_label}."
    if review_count > 0:
        desc += f" Rated {avg_rating:.1f}/5 from {review_count:,} reviews."
    return desc[:1000]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: CSV not found at {csv_path}")
        return 1

    print(f"Loading {csv_path.name} ...")
    df = pd.read_csv(csv_path, dtype=str)
    print(f"  Total rows: {len(df):,}   Unique ProductIds: {df['ProductId'].nunique():,}")

    # Filter to skincare types
    df = df[df["ProductType"].isin(SKINCARE_TYPES)].copy()
    print(f"  After skincare filter: {len(df):,} rows")

    # Only keep rows where URL has a valid /dp/ASIN slug (real product pages)
    df["url_asin"] = df["URL"].apply(extract_asin_from_url)
    df["name"] = df["URL"].apply(extract_name_from_url)
    df = df[(df["url_asin"] != "") & (df["name"] != "")].copy()
    print(f"  Rows with extractable name+ASIN from URL: {len(df):,}")

    df["Rating"] = pd.to_numeric(df["Rating"], errors="coerce")

    # Deduplicate by URL ASIN (each unique Amazon product page = one product)
    agg = (
        df.groupby("url_asin")
        .agg(
            ProductType=("ProductType", "first"),
            avg_rating=("Rating", "mean"),
            review_count=("Rating", "count"),
            name=("name", "first"),
            url=("URL", "first"),
        )
        .reset_index()
    )
    print(f"  Unique products with real names: {len(agg):,}")

    # Setup DB — clear and re-seed with our curated 25 first
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    print("\nClearing DB and re-seeding with 25 curated products...")
    db.query(ProductIngredient).delete()
    db.query(Product).delete()
    db.query(Ingredient).delete()
    db.query(Brand).delete()
    db.commit()
    seed_database(db)
    print(f"  Curated products seeded: {db.query(Product).count()}")

    # Load caches from fresh seed
    ingredient_cache: dict[str, Ingredient] = {i.name: i for i in db.query(Ingredient).all()}
    brand_cache: dict[str, Brand] = {b.name: b for b in db.query(Brand).all()}
    existing_asins: set[str] = {
        m.group(1)
        for p in db.query(Product).all()
        for m in [re.search(r"/dp/([A-Z0-9]{10})", p.product_url or "")]
        if m
    }

    imported = 0
    skipped = 0
    batch_size = 200

    print(f"\nImporting {len(agg):,} Kaggle products...")
    for _, row in agg.iterrows():
        asin = str(row["url_asin"]).strip()
        if asin in existing_asins:
            skipped += 1
            continue

        product_type = str(row["ProductType"])
        category = SKINCARE_TYPES.get(product_type, "skincare")
        name = title_case(str(row["name"]))
        brand_name = extract_brand_from_name(name)
        avg_rating = float(row["avg_rating"]) if pd.notna(row["avg_rating"]) else 0.0
        review_count = int(row["review_count"])

        ingredient_names = infer_ingredients(name, category)
        if not ingredient_names:
            skipped += 1
            continue

        skin_types = CATEGORY_SKIN_TYPES.get(category, "all")
        description = build_description(name, category, avg_rating, review_count)

        # Keep the original amazon.in URL (strip ref/query params for a clean link)
        raw_url = str(row["url"])
        clean_match = re.search(r"(https?://www\.amazon\.\w+/[^/?#]+/dp/[A-Z0-9]{10})", raw_url)
        product_url = clean_match.group(1) if clean_match else ""

        brand = brand_cache.get(brand_name)
        if brand is None:
            brand = Brand(name=brand_name, description=f"{brand_name} beauty brand")
            db.add(brand)
            db.flush()
            brand_cache[brand_name] = brand

        product = Product(
            brand=brand,
            name=name,
            category=category,
            skin_types=skin_types,
            price=0,
            description=description,
            product_url=product_url,
            image_url="",
            avg_rating=round(avg_rating, 2),
            review_count=review_count,
        )
        db.add(product)
        db.flush()

        for ing_name in ingredient_names:
            if ing_name in ingredient_cache:
                db.add(ProductIngredient(product=product, ingredient=ingredient_cache[ing_name], weight=1.0))

        existing_asins.add(asin)
        imported += 1

        if imported % batch_size == 0:
            db.commit()
            print(f"  {imported:,} / {len(agg):,} imported")

    db.commit()

    total = db.query(Product).count()
    print(f"\nDone. Total in DB: {total:,}  (25 curated + {imported} Kaggle, {skipped} skipped)")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
