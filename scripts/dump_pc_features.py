"""Dump per-image personal-color features (model 4-way probs + color probs + skin metrics)
so the 2-stage prototype can be tuned without re-running inference.

Usage:
    python scripts/dump_pc_features.py --manifest <csv> --out <features.csv>
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

from app.ai.personal_color_model import EfficientNetSeasonClassifier  # noqa: E402
from app.services import personal_color_analyzer as analyzer_module  # noqa: E402
from app.services.personal_color_analyzer import PersonalColorAnalyzer  # noqa: E402

SEASONS = ("spring", "summer", "autumn", "winter")
ALIASES = {
    "spring": "spring", "spr": "spring", "봄": "spring",
    "summer": "summer", "sum": "summer", "여름": "summer",
    "autumn": "autumn", "fall": "autumn", "가을": "autumn",
    "winter": "winter", "win": "winter", "겨울": "winter",
}


def norm(v: str) -> str:
    t = (v or "").strip().lower()
    if t in ALIASES:
        return ALIASES[t]
    for a, s in ALIASES.items():
        if a in t:
            return s
    raise ValueError(v)


def resolve(p: str, mdir: Path) -> Path:
    path = Path(p)
    if path.is_absolute():
        return path
    for c in (mdir / path, ROOT / path):
        if c.exists():
            return c
    return mdir / path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model-path", default="", help="Candidate .pt (default: app settings model).")
    args = ap.parse_args()

    if args.model_path:
        mp = Path(args.model_path)
        mp = mp if mp.is_absolute() else ROOT / mp
        if not mp.exists():
            raise SystemExit(f"model not found: {mp}")
        analyzer_module._season_classifier = EfficientNetSeasonClassifier(str(mp))

    manifest = Path(args.manifest)
    with manifest.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    analyzer = PersonalColorAnalyzer()
    fields = (
        ["image_path", "actual"]
        + [f"m_{s}" for s in SEASONS]
        + [f"c_{s}" for s in SEASONS]
        + ["brightness", "chroma", "warmth", "lab_a", "lab_b", "hsv_s"]
    )
    out_rows = []
    n_err = 0
    for i, row in enumerate(rows, 1):
        raw = row.get("label") or row.get("season") or ""
        try:
            actual = norm(raw)
        except ValueError:
            n_err += 1
            continue
        ip = resolve(row["image_path"], manifest.parent)
        if not ip.exists():
            n_err += 1
            continue
        try:
            r = analyzer._read_one(ip.read_bytes(), 1.0)
        except Exception:
            n_err += 1
            continue
        mp = r.get("model_season_probs") or {}
        cp = r.get("color_season_probs") or {}
        cv = r.get("color_vector") or {}
        rec = {"image_path": str(ip), "actual": actual}
        for s in SEASONS:
            rec[f"m_{s}"] = round(float(mp.get(s, 0.0)), 5)
            rec[f"c_{s}"] = round(float(cp.get(s, 0.0)), 5)
        rec["brightness"] = round(float(r.get("brightness", 0.0)), 5)
        rec["chroma"] = round(float(r.get("chroma", 0.0)), 5)
        rec["warmth"] = round(float(r.get("warmth", 0.0)), 5)
        rec["lab_a"] = round(float(cv.get("lab_a", 0.0)), 4)
        rec["lab_b"] = round(float(cv.get("lab_b", 0.0)), 4)
        rec["hsv_s"] = round(float(cv.get("hsv_s", 0.0)), 5)
        out_rows.append(rec)
        if i % 50 == 0:
            print(f"  ...{i}/{len(rows)}", flush=True)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    print(f"dumped {len(out_rows)} rows (errors={n_err}) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
