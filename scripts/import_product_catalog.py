from __future__ import annotations

import argparse
import csv
from pathlib import Path


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
                name_key = pick_field(fields, ["product_name", "product name", "name", "title"])
                brand_key = pick_field(fields, ["brand_name", "brand name", "brand"])
                ingredient_key = pick_field(fields, ["ingredients", "ingredient", "highlights"])
                rating_key = pick_field(fields, ["rating", "avg_rating", "reviews_rating", "stars"])
                if not name_key:
                    continue
                for row in reader:
                    rows.append(
                        {
                            "source": str(csv_path),
                            "brand": row.get(brand_key or "", ""),
                            "name": row.get(name_key, ""),
                            "ingredients": row.get(ingredient_key or "", ""),
                            "rating": row.get(rating_key or "", ""),
                        }
                    )
        except OSError:
            continue

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["source", "brand", "name", "ingredients", "rating"])
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


if __name__ == "__main__":
    raise SystemExit(main())
