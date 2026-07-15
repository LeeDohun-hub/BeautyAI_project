"""Pexels 퍼스널컬러 후보 이미지 수집 (품질 확인용 프로브).

주의: candidate_label 은 '검색어 → 계절' 추정 라벨이라 노이즈가 크다.
학습에 그대로 쓰지 말 것 — 조명/WB 아티팩트를 학습하게 됨. 품질 육안 확인 용도.

실행:
    $env:PEXELS_API_KEY = (Select-String '^PEXELS_API_KEY' .env).Line.Split('=',2)[1].Trim()
    python scripts/collect_pexels_personal_color.py
출력:
    data/pexels_personal_color_candidates.json
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import requests

PEXELS_API_KEY = os.environ["PEXELS_API_KEY"]

SEASON_QUERIES = {
    "spring": [
        "asian face warm natural light",
        "bright warm portrait",
        "peach skin portrait",
        "golden skin face",
    ],
    "summer": [
        "asian face soft cool light",
        "soft cool portrait",
        "pastel face portrait",
        "ash brown hair portrait",
    ],
    "autumn": [
        "asian face warm earthy",
        "muted warm portrait",
        "brown orange makeup portrait",
        "autumn tone face",
    ],
    "winter": [
        "asian face high contrast",
        "cool high contrast portrait",
        "black hair pale skin portrait",
        "jewel tone face portrait",
    ],
}


def fetch_pexels_images(query: str, per_page: int = 20) -> list[dict]:
    response = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": PEXELS_API_KEY},
        params={"query": query, "per_page": per_page, "orientation": "square"},
        timeout=20,
    )
    response.raise_for_status()

    results = []
    for photo in response.json().get("photos", []):
        results.append({
            "id": photo["id"],
            "photographer": photo["photographer"],
            "page_url": photo["url"],
            "image_url": photo["src"]["large"],
            "original_url": photo["src"]["original"],
            "query": query,
        })
    return results


def main() -> int:
    dataset: list[dict] = []
    seen: set[int] = set()
    dupes = 0
    per_query: Counter[str] = Counter()

    for season, queries in SEASON_QUERIES.items():
        for query in queries:
            try:
                photos = fetch_pexels_images(query, per_page=20)
            except requests.HTTPError as exc:
                print(f"  [skip] {season}/{query!r}: {exc}")
                continue
            for image in photos:
                if image["id"] in seen:  # 같은 사진이 여러 쿼리에 걸림
                    dupes += 1
                    continue
                seen.add(image["id"])
                image["candidate_label"] = season
                dataset.append(image)
                per_query[f"{season}/{query}"] += 1

    out = Path("data/pexels_personal_color_candidates.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")

    per_season = Counter(img["candidate_label"] for img in dataset)
    print(f"수집된 후보 이미지: {len(dataset)}장 (중복 제거 {dupes}장)")
    print("계절별:", dict(per_season))
    print("쿼리별:")
    for key, count in per_query.items():
        print(f"  {count:3d}  {key}")
    print(f"저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
