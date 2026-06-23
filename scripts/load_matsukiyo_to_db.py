"""Load crawled Matsukiyo skincare products into the recommendation DB.

Reads data/manifests/matsukiyo_products.csv (produced by crawl_matsukiyo.py) and
upserts Brand / Product / Ingredient / ProductIngredient rows. Product URLs keep
the ``matsukiyococokara`` domain so ``platform=matsukiyo`` recommendations match
(see app.services.recommender.matched_platforms).

Runs against whatever DATABASE_URL resolves to (Supabase Postgres by default).
Override for a local sqlite dry run with --database-url sqlite:///./beautyai.db.

Usage:
    python scripts/load_matsukiyo_to_db.py
    python scripts/load_matsukiyo_to_db.py --database-url sqlite:///./beautyai.db --limit 50
"""
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

# Ingredient -> (benefit, targets, Japanese/English needles found in product names).
# Targets reuse the recommender's concern vocabulary so scoring works unchanged.
INGREDIENT_RULES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "Niacinamide": ("Balances sebum and supports tone and barrier.", "oiliness,pore,pigmentation,redness",
                    ("ナイアシンアミド", "niacinamide", "ナイアシン")),
    "Vitamin C": ("Brightening antioxidant for dullness and pigmentation.", "pigmentation,wrinkle",
                  ("ビタミンc", "ビタミンｃ", "vitamin c", "vc", "ビタc", "ビタミンC")),
    "Retinol": ("Vitamin A derivative for wrinkles and texture.", "wrinkle,pore,pigmentation",
                ("レチノール", "retinol", "レチナール", "レチニル")),
    "Hyaluronic Acid": ("Hydration support for dehydrated skin.", "wrinkle,redness",
                        ("ヒアルロン酸", "hyaluronic", "ヒアルロン")),
    "Ceramide": ("Barrier lipid for dry and sensitive skin.", "redness,wrinkle",
                 ("セラミド", "ceramide", "バリア")),
    "Centella Asiatica": ("Soothing ingredient for redness and sensitivity.", "redness,acne",
                          ("ツボクサ", "シカ", "cica", "centella", "マデカ")),
    "Salicylic Acid": ("BHA for acne-prone skin and clogged pores.", "acne,pore,oiliness",
                       ("サリチル酸", "salicylic", "bha", "ニキビ", "にきび", "アクネ", "毛穴")),
    "Collagen": ("Firming support used in wrinkle care.", "wrinkle",
                 ("コラーゲン", "collagen", "ペプチド", "peptide", "リフト", "ハリ")),
    "Green Tea": ("Antioxidant botanical for oily or red skin.", "oiliness,redness,acne",
                  ("緑茶", "茶", "チャ葉", "green tea", "ティーツリー")),
    "Panthenol": ("Barrier and soothing support for sensitive skin.", "redness,wrinkle",
                  ("パンテノール", "panthenol")),
    "Hatomugi": ("Hatomugi (Job's tears) hydrating soother popular in J-beauty.", "redness,oiliness",
                 ("ハトムギ", "はとむぎ")),
    "Vitamin A/E": ("Antioxidant vitamins for texture and barrier.", "wrinkle,redness",
                    ("ビタミンe", "ビタミンa", "トコフェロール")),
}

# Japanese (and some English) skincare product-type words: keep if matched.
SKINCARE_WORDS = (
    "化粧水", "美容液", "乳液", "クリーム", "ジェル", "ローション", "エッセンス", "セラム",
    "美白", "保湿", "洗顔", "クレンジング", "クレンズ", "メイク落とし", "日焼け止め", "日焼止め",
    "uv", "ｕｖ", "spf", "ｓｐｆ", "下地", "マスク", "パック", "角質", "ピーリング", "毛穴",
    "オールインワン", "ミスト", "バーム", "アイクリーム", "シートマスク", "拭き取り", "ふきとり",
    "スキンケア", "保水", "うるおい", "美容オイル", "フェイス", "薬用", "トナー", "アンプル",
)

# Words that mark NON-skincare items leaking into the スキンケア・メイク category
# (makeup tools, shaving, blotting paper, hygiene, etc.) -> drop.
NON_SKINCARE_WORDS = (
    "ティシュ", "ティッシュ", "トイレット", "ラップ", "ナプキン", "おむつ", "オムツ", "生理",
    "カミソリ", "かみそり", "シェーバー", "替刃", "ブラシ", "パフ", "スポンジ", "ピンセット",
    "毛抜き", "あぶらとり", "コットン", "綿棒", "マスク ふつう", "不織布マスク", "立体マスク",
    "歯ブラシ", "歯磨", "シャンプー", "リンス", "ボディソープ", "入浴", "ハンドソープ",
    "アイブロウ", "アイライナー", "マスカラ", "口紅", "リップ", "チーク", "ファンデーション",
    "ネイル", "アイシャドウ", "つけまつ", "ビューラー", "ヘアカラー", "白髪",
    # beauty devices / gadgets (not topical skincare)
    "美顔器", "マイクロカレント", "フェイスリフト", "リフトペン", "リフター", "ソニック",
    "美顔ローラー", "イオン導入", "スチーマー", "ＥＭＳ", "ems",
)


def normalize(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_int(value: object) -> int:
    digits = re.sub(r"[^0-9]", "", normalize(value))
    return int(digits) if digits else 0


def parse_float(value: object) -> float:
    text = normalize(value)
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


def is_skincare(name: str, category: str) -> bool:
    haystack = f"{name} {category}".lower()
    if any(word in haystack for word in NON_SKINCARE_WORDS):
        return False
    return any(word in haystack for word in SKINCARE_WORDS)


def detect_ingredients(name: str) -> list[str]:
    haystack = name.lower()
    found = [
        ingredient
        for ingredient, (_, _, needles) in INGREDIENT_RULES.items()
        if any(needle.lower() in haystack for needle in needles)
    ]
    if found:
        return list(dict.fromkeys(found))

    # Fallback by product type so every kept product carries at least one target.
    if any(w in haystack for w in ("洗顔", "クレンジング", "メイク落とし", "毛穴")):
        return ["Salicylic Acid", "Centella Asiatica"]
    if any(w in haystack for w in ("日焼け止め", "日焼止め", "uv", "ｕｖ", "spf", "下地")):
        return ["Niacinamide", "Vitamin C"]
    if any(w in haystack for w in ("マスク", "パック", "美容液", "アンプル", "エッセンス", "セラム")):
        return ["Niacinamide", "Hyaluronic Acid"]
    if any(w in haystack for w in ("化粧水", "ローション", "乳液", "クリーム", "保湿", "ミスト", "うるおい")):
        return ["Hyaluronic Acid", "Panthenol"]
    return ["Hyaluronic Acid"]


def infer_skin_types(ingredient_names: list[str]) -> str:
    targets: set[str] = set()
    for name in ingredient_names:
        targets.update(INGREDIENT_RULES[name][1].split(","))
    skin_types = {"all"}
    if {"oiliness", "acne", "pore"} & targets:
        skin_types.update(["oily", "combination"])
    if {"redness", "wrinkle"} & targets:
        skin_types.update(["dry", "sensitive"])
    if "pigmentation" in targets:
        skin_types.update(["normal", "dry"])
    return ",".join(sorted(skin_types))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="data/manifests/matsukiyo_products.csv")
    parser.add_argument("--database-url", default="",
                        help="Optional DB URL override, e.g. sqlite:///./beautyai.db")
    parser.add_argument("--limit", type=int, default=0, help="Max products to import, 0 = all")
    args = parser.parse_args()

    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    from app.core.database import Base, SessionLocal, engine
    from app.models import Brand, Ingredient, Product, ProductIngredient

    catalog_path = PROJECT_ROOT / args.catalog
    if not catalog_path.exists():
        raise SystemExit(f"Catalog not found: {catalog_path}")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    brand_cache = {brand.name: brand for brand in db.query(Brand).all()}
    ingredient_cache = {ing.name: ing for ing in db.query(Ingredient).all()}
    existing = {
        (product.brand.name.lower(), product.name.lower())
        for product in db.query(Product).join(Brand).all()
    }
    linked = {(item.product_id, item.ingredient_id) for item in db.query(ProductIngredient).all()}

    imported = updated = skipped = scanned = 0
    try:
        with catalog_path.open(encoding="utf-8-sig", errors="ignore", newline="") as fh:
            for row in csv.DictReader(fh):
                scanned += 1
                name = normalize(row.get("prdtName"))
                brand_name = normalize(row.get("brandName")) or "Matsukiyo"
                category = normalize(row.get("category"))
                if not name or not is_skincare(name, category):
                    skipped += 1
                    continue

                ingredient_names = detect_ingredients(name)
                brand = brand_cache.get(brand_name)
                if brand is None:
                    brand = Brand(name=brand_name, description=f"{brand_name} (Matsukiyo Cocokara source)")
                    db.add(brand)
                    db.flush()
                    brand_cache[brand_name] = brand

                price = parse_int(row.get("saleAmt"))
                review_count = parse_int(row.get("reviewCount"))
                rating = parse_float(row.get("avgRating"))
                product_url = normalize(row.get("productUrl"))
                image_url = normalize(row.get("imageUrl"))
                description = "Matsukiyo Cocokara skincare product"
                if review_count:
                    description += f" with {review_count} reviews"

                key = (brand_name.lower(), name.lower())
                if key in existing:
                    product = (
                        db.query(Product).join(Brand)
                        .filter(Brand.name == brand_name, Product.name == name).first()
                    )
                    if product is None:
                        skipped += 1
                        continue
                    product.category = category or product.category or "skincare"
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
                        category=category or "skincare",
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
                    existing.add(key)
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
                    if pair not in linked:
                        db.add(ProductIngredient(product_id=product.id, ingredient_id=ingredient.id, weight=1.0))
                        linked.add(pair)

                if args.limit and imported + updated >= args.limit:
                    break

        db.commit()
    finally:
        db.close()

    print(f"Scanned {scanned} rows. Imported {imported}, updated {updated}, skipped {skipped}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
