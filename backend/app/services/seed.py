from sqlalchemy.orm import Session

from app.models import Brand, Ingredient, Product, ProductIngredient


INGREDIENTS = [
    ("Niacinamide", "Helps balance sebum, tone, pores, and barrier support.", "oiliness,pore,pigmentation,redness"),
    ("Salicylic Acid", "BHA ingredient useful for clogged pores and acne-prone skin.", "acne,pore,oiliness"),
    ("Centella Asiatica", "Soothing botanical often used for sensitivity and redness.", "redness,acne"),
    ("Retinol", "Supports wrinkle care and skin texture renewal.", "wrinkle,pore,pigmentation"),
    ("Hyaluronic Acid", "Hydration support for dehydrated or barrier-weakened skin.", "wrinkle,redness"),
    ("Vitamin C", "Brightening antioxidant used for dullness and pigmentation.", "pigmentation,wrinkle"),
    ("Ceramide", "Barrier lipid helpful for sensitive and dry skin.", "redness,wrinkle"),
    ("Glycolic Acid", "AHA exfoliant used for texture and pigmentation care.", "pigmentation,pore,wrinkle"),
    ("Lactic Acid", "Gentle AHA used for texture, dullness, and hydration support.", "pigmentation,pore,wrinkle"),
    ("Azelaic Acid", "Ingredient used for redness, blemishes, and uneven tone.", "redness,acne,pigmentation"),
    ("Panthenol", "Barrier and soothing support for sensitive skin.", "redness,wrinkle"),
    ("Green Tea", "Antioxidant and soothing botanical for oily or red skin.", "oiliness,redness,acne"),
    ("Zinc", "Sebum and blemish support often used for oily skin.", "oiliness,acne"),
    ("Peptide", "Firming support used in wrinkle care products.", "wrinkle"),
]

# (brand, name, category, skin_types, price_usd_cents, description, ingredient_names, product_url)
# price in USD cents (890 = $8.90). product_url: direct amazon.com/dp/ for stable ASINs,
# amazon.com/s?k= search URL for brands where ASINs are unstable (The Ordinary, etc.)
def _search(brand: str, name: str) -> str:
    query = (brand + " " + name).replace(" ", "+")
    return f"https://www.amazon.com/s?k={query}"


REAL_PRODUCTS = [
    (
        "The Ordinary",
        "Niacinamide 10% + Zinc 1%",
        "serum",
        "oily,combination,all",
        890,
        "High-strength vitamin and mineral blemish formula. Visibly reduces skin blemishes, congestion, and pore appearance.",
        ["Niacinamide", "Zinc"],
        _search("The Ordinary", "Niacinamide 10% Zinc 1%"),
    ),
    (
        "Paula's Choice",
        "SKIN PERFECTING 2% BHA Liquid Exfoliant",
        "toner",
        "oily,combination",
        3400,
        "Leave-on exfoliant with 2% salicylic acid. Unclogs pores, smooths wrinkles, and brightens dull skin.",
        ["Salicylic Acid"],
        "https://www.amazon.com/dp/B00949CTQQ",
    ),
    (
        "The Ordinary",
        "Retinol 0.5% in Squalane",
        "serum",
        "normal,dry,combination",
        1080,
        "Moderate-strength retinol in lightweight squalane. Targets fine lines, skin texture, and pore appearance.",
        ["Retinol"],
        _search("The Ordinary", "Retinol 0.5% in Squalane"),
    ),
    (
        "TruSkin",
        "Vitamin C Serum for Face",
        "serum",
        "all",
        1999,
        "Brightening serum with 20% Vitamin C, hyaluronic acid, and Vitamin E. Fades dark spots and evens skin tone.",
        ["Vitamin C", "Hyaluronic Acid"],
        "https://www.amazon.com/dp/B01M0AQKBT",
    ),
    (
        "CeraVe",
        "Moisturizing Cream",
        "cream",
        "dry,sensitive,all",
        1699,
        "Daily face and body moisturizer with three essential ceramides and hyaluronic acid. Restores and maintains the skin barrier.",
        ["Ceramide", "Hyaluronic Acid"],
        "https://www.amazon.com/dp/B00TTD9BRC",
    ),
    (
        "Neutrogena",
        "Hydro Boost Water Gel",
        "cream",
        "oily,combination,all",
        1997,
        "Lightweight water-gel moisturizer with hyaluronic acid. Absorbs instantly, leaves no greasy residue.",
        ["Hyaluronic Acid"],
        "https://www.amazon.com/dp/B01MYGZVR0",
    ),
    (
        "Dr. Jart+",
        "Cicapair Tiger Grass Color Correcting Treatment SPF 30",
        "cream",
        "sensitive,all",
        5200,
        "Skin recovery treatment and color corrector with Centella Asiatica. Soothes redness and evens skin tone.",
        ["Centella Asiatica", "Panthenol"],
        _search("Dr. Jart+", "Cicapair Tiger Grass Color Correcting Treatment"),
    ),
    (
        "The Ordinary",
        "AHA 30% + BHA 2% Peeling Solution",
        "treatment",
        "oily,combination,normal",
        900,
        "10-minute exfoliating facial with alpha and beta hydroxy acids. Improves skin radiance and reduces blemishes.",
        ["Glycolic Acid", "Lactic Acid", "Salicylic Acid"],
        _search("The Ordinary", "AHA 30% BHA 2% Peeling Solution"),
    ),
    (
        "The Ordinary",
        "Azelaic Acid Suspension 10%",
        "serum",
        "oily,combination,sensitive",
        800,
        "Brightening and blemish-reducing formula with 10% azelaic acid. Targets uneven tone and redness.",
        ["Azelaic Acid"],
        _search("The Ordinary", "Azelaic Acid Suspension 10%"),
    ),
    (
        "Olay",
        "Regenerist Retinol 24 Night Face Moisturizer",
        "cream",
        "normal,dry,combination",
        2899,
        "Night cream with retinol and Vitamin B3 (niacinamide). 24-hour hydration and visibly improved skin texture.",
        ["Retinol", "Niacinamide"],
        "https://www.amazon.com/dp/B07MCJFKQ8",
    ),
    (
        "CeraVe",
        "Foaming Facial Cleanser",
        "cleanser",
        "oily,combination,all",
        1599,
        "Daily foaming cleanser with ceramides and hyaluronic acid. Removes excess oil without disrupting the skin barrier.",
        ["Ceramide", "Hyaluronic Acid"],
        "https://www.amazon.com/dp/B01N1LL62W",
    ),
    (
        "The Ordinary",
        "Buffet Multi-Technology Peptide Serum",
        "serum",
        "all,normal,dry",
        1480,
        "Multi-peptide serum targeting multiple signs of aging simultaneously. Smooths fine lines and improves overall skin quality.",
        ["Peptide", "Hyaluronic Acid"],
        _search("The Ordinary", "Buffet Peptide Serum"),
    ),
    (
        "La Roche-Posay",
        "Effaclar Medicated Gel Facial Cleanser",
        "cleanser",
        "oily,combination",
        1795,
        "Foaming gel cleanser with 2% salicylic acid. Removes excess oil and impurities while treating active acne.",
        ["Salicylic Acid"],
        "https://www.amazon.com/dp/B01GV5ZP3Q",
    ),
    (
        "EltaMD",
        "UV Clear Broad-Spectrum SPF 46",
        "sunscreen",
        "all,sensitive",
        3600,
        "Oil-free face sunscreen with niacinamide and hyaluronic acid. Ideal for acne-prone and redness-sensitive skin.",
        ["Niacinamide", "Hyaluronic Acid"],
        "https://www.amazon.com/dp/B002MSN3QQ",
    ),
    (
        "Paula's Choice",
        "SKIN PERFECTING 8% AHA Gel Exfoliant",
        "toner",
        "normal,dry,combination",
        3400,
        "Exfoliating gel with 8% glycolic acid. Reduces wrinkles, smooths rough texture, and brightens uneven skin tone.",
        ["Glycolic Acid"],
        "https://www.amazon.com/dp/B00IKQMKIU",
    ),
    (
        "COSRX",
        "Advanced Snail 96 Mucin Power Essence",
        "serum",
        "all,sensitive,dry",
        2500,
        "96% snail secretion filtrate essence with centella extract. Hydrates, repairs skin barrier, and improves texture.",
        ["Centella Asiatica", "Hyaluronic Acid"],
        "https://www.amazon.com/dp/B00PBX3L7K",
    ),
    (
        "Cetaphil",
        "Moisturizing Lotion for All Skin Types",
        "lotion",
        "all,sensitive",
        1299,
        "Daily moisturizing lotion with panthenol and glycerin. Lightweight hydration for normal to dry sensitive skin.",
        ["Panthenol", "Hyaluronic Acid"],
        "https://www.amazon.com/dp/B001ETMD4K",
    ),
    (
        "La Roche-Posay",
        "Cicaplast Baume B5 Multi-Purpose Balm",
        "cream",
        "sensitive,dry,all",
        1995,
        "Ultra-repairing soothing balm with panthenol and centella asiatica. Soothes and repairs irritated or sensitized skin.",
        ["Panthenol", "Centella Asiatica"],
        _search("La Roche-Posay", "Cicaplast Baume B5"),
    ),
    (
        "The Ordinary",
        "Ascorbic Acid 8% + Alpha Arbutin 2%",
        "serum",
        "normal,dry,combination",
        1200,
        "Advanced brightening formula combining vitamin C with alpha arbutin. Reduces dark spots and uneven skin tone.",
        ["Vitamin C"],
        _search("The Ordinary", "Ascorbic Acid 8% Alpha Arbutin 2%"),
    ),
    (
        "First Aid Beauty",
        "Ultra Repair Cream Intense Hydration",
        "cream",
        "dry,sensitive,all",
        3200,
        "Rich moisturizing cream with colloidal oatmeal, ceramides, and panthenol. Provides intense hydration for dry, rough skin.",
        ["Ceramide", "Panthenol"],
        _search("First Aid Beauty", "Ultra Repair Cream"),
    ),
    (
        "RoC",
        "Retinol Correxion Line Smoothing Retinol Serum",
        "serum",
        "normal,dry,combination",
        2699,
        "Pure retinol and mineral-enriched serum. Visibly reduces fine lines and wrinkles, smooths and firms skin texture.",
        ["Retinol", "Peptide"],
        _search("RoC", "Retinol Correxion Line Smoothing Serum"),
    ),
    (
        "Neutrogena",
        "Rapid Clear Stubborn Acne Spot Gel",
        "spot",
        "oily,combination",
        799,
        "Maximum-strength benzoyl peroxide spot treatment for stubborn acne. Fast-acting formula for blemish and acne care.",
        ["Salicylic Acid", "Zinc"],
        "https://www.amazon.com/dp/B000FCLKUS",
    ),
    (
        "innisfree",
        "Green Tea Seed Hyaluronic Acid Serum",
        "serum",
        "all,oily,combination",
        2800,
        "Moisturizing serum with Jeju green tea seed hyaluronic acid. Provides multi-layer deep hydration and sebum balance.",
        ["Green Tea", "Hyaluronic Acid"],
        _search("innisfree", "Green Tea Seed Hyaluronic Acid Serum"),
    ),
    (
        "The Ordinary",
        "Glycolic Acid 7% Toning Solution",
        "toner",
        "oily,combination,normal",
        990,
        "Alpha hydroxy acid toning solution for improved skin radiance, clarity, and texture. Gentle daily exfoliation.",
        ["Glycolic Acid", "Lactic Acid"],
        _search("The Ordinary", "Glycolic Acid 7% Toning Solution"),
    ),
    (
        "COSRX",
        "AHA/BHA Clarifying Treatment Toner",
        "toner",
        "oily,combination",
        2200,
        "Exfoliating toner with AHA and BHA. Minimizes pores, controls excess sebum, and gently exfoliates dead skin cells.",
        ["Glycolic Acid", "Salicylic Acid"],
        "https://www.amazon.com/dp/B00P9B5DFQ",
    ),
]


def seed_database(db: Session) -> None:
    if db.query(Product).first():
        return

    ingredient_map: dict[str, Ingredient] = {}
    for name, benefit, targets in INGREDIENTS:
        ingredient = Ingredient(name=name, benefit=benefit, targets=targets)
        db.add(ingredient)
        ingredient_map[name] = ingredient

    brand_map: dict[str, Brand] = {}
    for brand_name, product_name, category, skin_types, price, description, ingredient_names, product_url in REAL_PRODUCTS:
        brand = brand_map.get(brand_name)
        if brand is None:
            brand = Brand(name=brand_name, description=f"{brand_name} skincare brand")
            db.add(brand)
            brand_map[brand_name] = brand

        product = Product(
            brand=brand,
            name=product_name,
            category=category,
            skin_types=skin_types,
            price=price,
            description=description,
            product_url=product_url,
            image_url="",
        )
        db.add(product)
        for ingredient_name in ingredient_names:
            db.add(ProductIngredient(product=product, ingredient=ingredient_map[ingredient_name], weight=1.0))

    db.commit()


def reseed_database(db: Session) -> None:
    """Clear all product/ingredient/brand data and re-seed with real Amazon products."""
    db.query(ProductIngredient).delete()
    db.query(Product).delete()
    db.query(Ingredient).delete()
    db.query(Brand).delete()
    db.commit()
    seed_database(db)
