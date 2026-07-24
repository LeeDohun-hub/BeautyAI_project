from __future__ import annotations

import argparse
import ast
import csv
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus

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
    # ── 바디(장벽·보습) 성분 ────────────────────────────────────────────────
    # 위 14종은 얼굴 액티브 위주라 바디 제품 전성분에 거의 안 걸린다(실측: 전성분을 확보한
    # 332건 중 68%만 검출). 바디는 에몰리언트·오클루시브로 구성되므로 아래를 추가한다.
    # targets 를 얼굴 점수(acne/pore/wrinkle/redness/pigmentation/oiliness)가 아닌
    # barrier/moisture/soothing 으로 둔다 → recommender.FACE_SCORE_TARGETS 필터에 걸려
    # 얼굴 랭킹에는 영향이 없다. 글리세린은 상품 82%에 들어 있어 이 분리가 특히 중요하다.
    "Glycerin": ("Humectant that draws water into the skin; base of most body moisturizers.", "moisture,barrier", ("glycerin", "glycerol")),
    "Petrolatum": ("Occlusive that blocks water loss. First-line emollient for atopic skin.", "barrier,moisture", ("petrolatum", "petroleum jelly", "mineral oil", "paraffin")),
    "Shea Butter": ("Rich emollient for dry and rough body skin.", "barrier,moisture", ("shea butter", "butyrospermum")),
    "Squalane": ("Lightweight emollient that restores skin lipids.", "barrier,moisture", ("squalane", "squalene")),
    "Allantoin": ("Soothing keratolytic used for rough, irritated skin.", "soothing,barrier", ("allantoin",)),
    "Colloidal Oatmeal": ("Skin protectant recognized for eczema itch relief.", "soothing,barrier", ("colloidal oatmeal", "avena sativa", "oat kernel")),
    "Urea": ("Humectant and keratolytic for very dry or thickened skin.", "moisture,barrier", ("urea",)),
    "Dimethicone": ("Silicone occlusive that reduces water loss without greasiness.", "barrier", ("dimethicone",)),
    "Jojoba Oil": ("Emollient oil close to skin sebum.", "barrier,moisture", ("jojoba", "simmondsia")),
}

TAG_INGREDIENT_FALLBACKS = {
    "acne": ["Salicylic Acid", "Centella Asiatica", "Azelaic Acid"],
    "pore": ["Niacinamide", "Salicylic Acid", "Glycolic Acid"],
    "oiliness": ["Niacinamide", "Green Tea", "Zinc"],
    "redness": ["Centella Asiatica", "Ceramide", "Panthenol"],
    "pigmentation": ["Vitamin C", "Niacinamide", "Azelaic Acid"],
    "wrinkle": ["Retinol", "Peptide", "Ceramide"],
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

MAKEUP_WORDS = (
    "lip",
    "lipstick",
    "tint",
    "rouge",
    "gloss",
    "blush",
    "blusher",
    "cheek",
    "eye",
    "eyeshadow",
    "shadow",
    "palette",
    "mascara",
    "liner",
    "nail",
    "polish",
    "foundation",
    "cushion",
    "concealer",
    "primer",
    "powder",
    "makeup",
    "cosmetic",
)

COLOR_WORDS = (
    "warm",
    "cool",
    "light",
    "bright",
    "soft",
    "muted",
    "deep",
    "coral",
    "peach",
    "pink",
    "rose",
    "mauve",
    "berry",
    "red",
    "brick",
    "terracotta",
    "orange",
    "beige",
    "brown",
    "ivory",
    "nude",
    "plum",
    "wine",
    "lavender",
)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = str(value).strip()
    if value.lower() in {"nan", "none", "null"}:
        return ""
    return re.sub(r"\s+", " ", value)


def infer_product_url(row: dict[str, str], brand: str, name: str) -> str:
    product_url = normalize_text(row.get("product_url", ""))
    asin = normalize_text(row.get("asin", "")).upper()
    source_platform = normalize_text(row.get("source_platform", "")).lower()
    source = normalize_text(row.get("source", "")).lower()
    if product_url:
        return product_url
    if asin:
        return f"https://www.amazon.com/dp/{asin}"
    if "amazon" in source_platform or "amazon" in source:
        query = quote_plus(f"{brand} {name}".strip())
        return f"https://www.amazon.com/s?k={query}"
    return ""


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


def parse_price(value: str | None) -> int:
    value = normalize_text(value)
    digits = re.sub(r"[^0-9.]", "", value)
    if not digits:
        return 0
    try:
        return int(float(digits))
    except ValueError:
        return 0


def parse_float(value: str | None) -> float:
    value = normalize_text(value)
    digits = re.sub(r"[^0-9.]", "", value)
    if not digits:
        return 0.0
    try:
        return float(digits)
    except ValueError:
        return 0.0


def parse_int(value: str | None) -> int:
    value = normalize_text(value).lower().replace(",", "")
    multiplier = 1
    if value.endswith("k"):
        multiplier = 1000
        value = value[:-1]
    digits = re.sub(r"[^0-9.]", "", value)
    if not digits:
        return 0
    try:
        return int(float(digits) * multiplier)
    except ValueError:
        return 0


def detect_ingredients(name: str, ingredients: str) -> list[str]:
    haystack = f"{name} {ingredients}".lower()
    found = []
    for ingredient_name, (_, _, needles) in INGREDIENT_RULES.items():
        if any(needle in haystack for needle in needles):
            found.append(ingredient_name)
    return found


def parse_tags(value: str | None) -> list[str]:
    value = normalize_text(value)
    if not value:
        return []
    return [tag.strip() for tag in re.split(r"[|,;/]", value) if tag.strip()]


def fallback_ingredients_from_tags(tags: list[str]) -> list[str]:
    found = []
    for tag in tags:
        for ingredient_name in TAG_INGREDIENT_FALLBACKS.get(tag, []):
            if ingredient_name not in found:
                found.append(ingredient_name)
    return found


def infer_category(name: str) -> str:
    lower = name.lower()
    makeup_categories = [
        "lipstick",
        "lip",
        "tint",
        "gloss",
        "blush",
        "cheek",
        "eyeshadow",
        "shadow",
        "palette",
        "mascara",
        "liner",
        "foundation",
        "cushion",
        "concealer",
        "primer",
        "powder",
    ]
    for category in makeup_categories:
        if category in lower:
            return "eye" if category in {"eyeshadow", "shadow", "palette", "mascara", "liner"} else category
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


def is_makeup_candidate(name: str, metadata: str) -> bool:
    haystack = f"{name} {metadata}".lower()
    return any(word in haystack for word in MAKEUP_WORDS)


def color_tags_from_text(value: str) -> list[str]:
    lower = value.lower()
    return [word for word in COLOR_WORDS if word in lower]


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
                tags = parse_tags(row.get("tags", ""))
                metadata = f"{ingredients_blob} {' '.join(tags)} {row.get('category', '')}"
                is_skincare = is_skincare_candidate(name, metadata)
                is_makeup = is_makeup_candidate(name, metadata)
                if not is_skincare and not is_makeup:
                    continue
                ingredient_names = detect_ingredients(name, ingredients_blob)
                if not ingredient_names:
                    ingredient_names = fallback_ingredients_from_tags(tags)
                if is_skincare and not ingredient_names:
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
                review_count = normalize_text(row.get("review_count", ""))
                source_platform = normalize_text(row.get("source_platform", ""))
                asin = normalize_text(row.get("asin", ""))
                category = normalize_text(row.get("category", "")) or infer_category(f"{name} {metadata}")
                color_tags = color_tags_from_text(f"{name} {metadata}")
                product_url = infer_product_url(row, brand_name, name)
                if source_platform == "amazon":
                    description = "Imported Amazon product"
                else:
                    description = "Imported makeup product" if is_makeup and not is_skincare else "Imported skincare product"
                if asin:
                    description += f" ASIN {asin}"
                if rating:
                    description += f" with source rating {rating}"
                if review_count:
                    description += f" from {review_count} reviews"
                if tags or color_tags:
                    description += f". Tags: {', '.join([*tags, *color_tags])}"
                product = Product(
                    brand=brand,
                    name=name,
                    category=category,
                    skin_types=infer_skin_types(ingredient_names) if ingredient_names else "all",
                    price=parse_price(row.get("price", "")),
                    description=description,
                    product_url=product_url,
                    image_url=normalize_text(row.get("image_url", "")),
                    avg_rating=parse_float(rating),
                    review_count=parse_int(review_count),
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
