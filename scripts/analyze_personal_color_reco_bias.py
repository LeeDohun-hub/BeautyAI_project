"""Task 4: per-season recommendation bias check.

Runs recommend_personal_color_products for each of the 4 seasons using keywords
derived from that season's actual makeup palette (backend PROFILES), then reports
the top products per season and cross-season overlap (bias) metrics.
"""
from __future__ import annotations

import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.database import SessionLocal  # noqa: E402
from app.services.recommender import recommend_personal_color_products  # noqa: E402

# Keywords per season, built from the real backend makeup palette (PROFILES),
# mirroring the frontend bilingual item-match query (KR color word + EN token).
SEASON_KEYWORDS = {
    "spring": [
        "코랄 핑크 립", "coral lipstick", "피치 베이지 립", "peach lip tint",
        "살구 코랄 블러셔", "apricot blush", "샴페인 베이지 아이섀도우", "champagne eyeshadow",
        "아이보리 베이지 파운데이션", "ivory foundation", "warm light",
    ],
    "summer": [
        "로즈 핑크 립", "rose lipstick", "쿨 핑크 립", "cool pink lip",
        "라벤더 핑크 블러셔", "lavender blush", "모브 베이지 아이섀도우", "mauve eyeshadow",
        "핑크 베이스 파운데이션", "pink foundation", "cool light",
    ],
    "autumn": [
        "브릭 레드 립", "brick red lipstick", "테라코타 립", "terracotta lip",
        "시나몬 베이지 블러셔", "cinnamon blush", "카멜 브라운 아이섀도우", "camel brown eyeshadow",
        "웜 베이지 파운데이션", "warm beige foundation", "warm deep",
    ],
    "winter": [
        "버건디 립", "burgundy lipstick", "체리 레드 립", "cherry red lip",
        "쿨 로즈 블러셔", "cool rose blush", "차콜 브라운 아이섀도우", "charcoal brown eyeshadow",
        "쿨 베이지 파운데이션", "cool beige foundation", "cool deep",
    ],
}

REGION = sys.argv[1] if len(sys.argv) > 1 else "kr"
LIMIT = 8


def main() -> int:
    db = SessionLocal()
    per_season = {}
    try:
        for season, keywords in SEASON_KEYWORDS.items():
            results = recommend_personal_color_products(
                db, keywords, region=REGION, platform="all", limit=LIMIT
            )
            per_season[season] = results
    finally:
        db.close()

    # Print top products per season
    for season, results in per_season.items():
        print(f"\n=== {season.upper()} (region={REGION}) top {len(results)} ===")
        for rank, p in enumerate(results, 1):
            src = "CATALOG" if p.id < 0 else "db"
            print(f"  {rank:>2}. [{p.score:>4}] {p.brand} | {p.name[:52]} | {p.category} ({src})")

    # Bias metrics: identity by (brand,name)
    def key(p):
        return f"{p.brand}|{p.name}".lower()

    season_sets = {s: {key(p) for p in r} for s, r in per_season.items()}
    all_keys = Counter()
    for s in season_sets.values():
        all_keys.update(s)

    print("\n\n########## BIAS / OVERLAP ANALYSIS ##########")
    shared_all = [k for k, c in all_keys.items() if c == 4]
    print(f"products appearing in ALL 4 seasons: {len(shared_all)}")
    for k in shared_all:
        print("   *", k)
    shared_3plus = [k for k, c in all_keys.items() if c >= 3]
    print(f"products appearing in >=3 seasons: {len(shared_3plus)}")

    print("\npairwise Jaccard overlap (1.0 = identical top lists):")
    for a, b in combinations(season_sets, 2):
        inter = len(season_sets[a] & season_sets[b])
        union = len(season_sets[a] | season_sets[b])
        print(f"  {a:>6} vs {b:<6}: {inter}/{union} = {inter/union:.2f}")

    total_unique = len(all_keys)
    print(f"\ntotal unique products across all seasons = {total_unique} "
          f"(of {4*LIMIT} slots) -> diversity ratio {total_unique/(4*LIMIT):.2f}")

    # DB vs catalog fallback share
    db_share = {s: sum(1 for p in r if p.id >= 0) for s, r in per_season.items()}
    print(f"db-sourced product count per season (rest are curated CATALOG fallback): {db_share}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
