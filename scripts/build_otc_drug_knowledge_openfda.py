"""라이브 OpenFDA API → 병별 OTC 의약품 예시 JSONL (Kaggle 불필요).

api.fda.gov/drug/label 를 product_type=HUMAN OTC DRUG + 유효성분으로 조회해 실제 OTC
제품(브랜드/용도/적응증)을 뽑아 data/rag/otc_drug_knowledge.jsonl 로 저장한다.
표준 라이브러리(urllib)만 사용. API 키 불필요(무키 240req/min·1000/day).

주의: 미국 FDA OTC 기준. 진단·처방이 아닌 참고용.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.derma_condition_care import OTC_INGREDIENTS  # noqa: E402

API = "https://api.fda.gov/drug/label.json"


def query_otc(generic: str, limit: int) -> list[dict]:
    search = f'openfda.product_type:"HUMAN OTC DRUG" AND active_ingredient:"{generic}"'
    url = f"{API}?" + urllib.parse.urlencode({"search": search, "limit": limit})
    req = urllib.request.Request(url, headers={"User-Agent": "beautyai-otc-builder"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out = []
    for result in data.get("results", []):
        openfda = result.get("openfda", {})
        brand = (openfda.get("brand_name") or [""])[0]
        purpose = (result.get("purpose") or [""])[0]
        indications = (result.get("indications_and_usage") or [""])[0]
        out.append({
            "brand": str(brand)[:120],
            "purpose": str(purpose)[:160],
            "indications": str(indications)[:240],
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/rag/otc_drug_knowledge.jsonl")
    parser.add_argument("--per-ingredient", type=int, default=3)
    args = parser.parse_args()

    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for condition, generics in OTC_INGREDIENTS.items():
        for generic in generics:
            try:
                hits = query_otc(generic, args.per_ingredient)
            except Exception as exc:
                print(f"  [{condition}/{generic}] 조회 실패: {exc}")
                continue
            kept = 0
            for hit in hits:
                brand = hit["brand"] or generic
                key = (condition, brand.lower())
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"condition": condition, "ingredient": generic, **hit, "brand": brand})
                kept += 1
            print(f"  [{condition}/{generic}] {kept}건")
            time.sleep(0.3)  # rate limit 예의

    out = PROJECT_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\nwrote {len(rows)} OTC examples → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
