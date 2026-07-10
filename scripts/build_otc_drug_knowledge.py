"""OpenFDA Human OTC Drug Labels(Kaggle) → 병별 OTC 의약품 예시 JSONL.

병별 OTC 유효성분(OTC_INGREDIENTS)으로 OTC 라벨에서 실제 제품(브랜드/용도/적응증)을
뽑아 data/rag/otc_drug_knowledge.jsonl 로 저장한다. recommend_derma_care가 이걸 읽어
'무좀 → 항진균제(라미실 등)' 처럼 실제 OTC 예시를 안내에 붙인다.

스키마를 모르는 상태에서도 동작하도록 CSV/JSON(SPL) 모두, 필드명도 유연하게 탐지한다.
주의: 미국 FDA OTC 기준. 진단·처방이 아닌 참고용.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.derma_condition_care import OTC_INGREDIENTS  # noqa: E402

# 성분(제네릭) → 병 목록 (한 성분이 여러 병에 쓰일 수 있음: salicylic/hydrocortisone 등)
INGREDIENT_TO_CONDITIONS: dict[str, list[str]] = {}
for _cond, _ings in OTC_INGREDIENTS.items():
    for _ing in _ings:
        INGREDIENT_TO_CONDITIONS.setdefault(_ing.lower(), []).append(_cond)

ALL_GENERICS = sorted(INGREDIENT_TO_CONDITIONS)

NAME_KEYS = ("brand_name", "brand", "openfda_brand_name", "product_name", "name")
GENERIC_KEYS = ("generic_name", "openfda_generic_name", "substance_name", "active_ingredient", "active_ingredients")
PURPOSE_KEYS = ("purpose", "openfda_purpose")
INDIC_KEYS = ("indications_and_usage", "indications", "indication")
MATCH_KEYS = ("active_ingredient", "active_ingredients", "generic_name", "substance_name", "openfda_generic_name", "spl_product_data_elements")


def _as_text(value) -> str:
    """str / list[str] / list[dict{text|name}] 무엇이든 소문자 텍스트로."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_as_text(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_as_text(v) for v in value)
    return str(value)


def _first(record: dict, keys, lower_map: dict[str, str]) -> str:
    for key in keys:
        actual = lower_map.get(key)
        if actual is not None and record.get(actual) not in (None, ""):
            return _as_text(record.get(actual)).strip()
    return ""


def _iter_records(root: Path):
    """CSV/JSON/JSONL 레코드를 dict로 순회."""
    for path in root.rglob("*"):
        suffix = path.suffix.lower()
        if suffix == ".csv":
            with path.open(encoding="utf-8", errors="ignore", newline="") as file:
                for row in csv.DictReader(file):
                    yield row
        elif suffix in (".json", ".jsonl", ".ndjson"):
            with path.open(encoding="utf-8", errors="ignore") as file:
                text = file.read().strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                for line in text.splitlines():
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue
                continue
            results = data.get("results") if isinstance(data, dict) else data
            if isinstance(results, list):
                yield from (r for r in results if isinstance(r, dict))
            elif isinstance(data, dict):
                yield data


def _flatten_openfda(record: dict) -> dict:
    """SPL의 openfda 하위 필드를 최상위로 승격(brand_name 등)."""
    merged = dict(record)
    openfda = record.get("openfda")
    if isinstance(openfda, dict):
        for key, value in openfda.items():
            merged.setdefault(key, value)
            merged.setdefault(f"openfda_{key}", value)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/datasets/kaggle/cahyaasrini__openfda-human-otc-drug-labels")
    parser.add_argument("--out", default="data/rag/otc_drug_knowledge.jsonl")
    parser.add_argument("--per-condition", type=int, default=8)
    args = parser.parse_args()

    root = PROJECT_ROOT / args.root
    if not root.exists():
        # slug 폴더가 다르게 풀렸을 수 있으니 부분탐색.
        base = PROJECT_ROOT / "data/datasets/kaggle"
        found = [p for p in base.rglob("*openfda*") if p.is_dir()] if base.exists() else []
        if not found:
            raise SystemExit(f"OTC 데이터셋 폴더를 찾지 못함: {root}")
        root = found[0]
        print(f"폴더 자동탐지: {root}")

    seen: set[tuple[str, str]] = set()
    per_count: dict[str, int] = {cond: 0 for cond in OTC_INGREDIENTS}
    rows: list[dict] = []
    scanned = 0
    for raw in _iter_records(root):
        scanned += 1
        record = _flatten_openfda(raw)
        lower_map = {key.lower(): key for key in record}
        haystack = " ".join(_first(record, (k,), lower_map) for k in MATCH_KEYS).lower()
        if not haystack:
            haystack = _as_text(record).lower()

        brand = _first(record, NAME_KEYS, lower_map) or _first(record, GENERIC_KEYS, lower_map)
        purpose = _first(record, PURPOSE_KEYS, lower_map)
        indications = _first(record, INDIC_KEYS, lower_map)

        for generic in ALL_GENERICS:
            if generic not in haystack:
                continue
            for condition in INGREDIENT_TO_CONDITIONS[generic]:
                if per_count[condition] >= args.per_condition:
                    continue
                key = (condition, (brand or generic).lower())
                if key in seen:
                    continue
                seen.add(key)
                per_count[condition] += 1
                rows.append({
                    "condition": condition,
                    "ingredient": generic,
                    "brand": brand[:120],
                    "purpose": purpose[:160],
                    "indications": indications[:240],
                })

    out = PROJECT_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"scanned={scanned} records, wrote {len(rows)} OTC examples → {out}")
    for cond, count in per_count.items():
        print(f"  {cond:18s} {count}")
    if rows:
        print("sample:", json.dumps(rows[0], ensure_ascii=False)[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
