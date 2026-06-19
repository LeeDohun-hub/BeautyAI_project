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
]

PRODUCTS = [
    ("AquaLab", "Barrier Calm Serum", "serum", "dry,sensitive,combination", 29000, "Low-irritation serum for redness and barrier care.", ["Centella Asiatica", "Ceramide", "Hyaluronic Acid"]),
    ("DermaPure", "Pore Reset Toner", "toner", "oily,combination", 22000, "Daily toner for visible pores and oil control.", ["Niacinamide", "Salicylic Acid"]),
    ("GlowRx", "Bright C Ampoule", "ampoule", "all,normal,dry", 36000, "Antioxidant ampoule for uneven tone and dark spots.", ["Vitamin C", "Hyaluronic Acid"]),
    ("SkinTheory", "Retinol Night Cream", "cream", "normal,dry,combination", 42000, "Night cream for fine lines and texture care.", ["Retinol", "Ceramide"]),
    ("CleanDerm", "Acne Spot Gel", "spot", "oily,combination", 18000, "Focused blemish gel for acne-prone areas.", ["Salicylic Acid", "Centella Asiatica"]),
    ("BalanceLab", "Sebum Control Lotion", "lotion", "oily,combination", 25000, "Light lotion for shine control and pore care.", ["Niacinamide", "Hyaluronic Acid"]),
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
    for brand_name, product_name, category, skin_types, price, description, ingredient_names in PRODUCTS:
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
        )
        db.add(product)
        for ingredient_name in ingredient_names:
            db.add(ProductIngredient(product=product, ingredient=ingredient_map[ingredient_name], weight=1.0))

    db.commit()

