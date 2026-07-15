"""Calibrate our pixel-estimated skin Lab against AI Hub spectrophotometer ground truth.

For each East-Asian Sample image, run the production analyzer's skin color estimate
(lab_a/lab_b from pixels, after white-balance) and pair it with the instrument-measured
CIELab from the label (manifest gt_lab_a/gt_lab_b). Dumps a comparison CSV; the error
and a warm/cool calibration are computed by analyze step.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
import os
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

from app.services.personal_color_analyzer import PersonalColorAnalyzer  # noqa: E402

MANIFEST = ROOT / "data/manifests/aihub_skincolor_sample_manifest.csv"
OUT = ROOT / "data/eval/aihub_lab_calibration.csv"


def main() -> int:
    rows = [r for r in csv.DictReader(MANIFEST.open(encoding="utf-8"))
            if r["region"] == "동북아시아"]
    analyzer = PersonalColorAnalyzer()
    out_rows = []
    for i, r in enumerate(rows, 1):
        ip = ROOT / r["image_path"]
        if not ip.exists():
            continue
        try:
            reading = analyzer._read_one(ip.read_bytes(), 1.0)
        except Exception as exc:
            out_rows.append({**base(r), "error": repr(exc)[:60]})
            continue
        cv = reading.get("color_vector") or {}
        out_rows.append({
            **base(r),
            "est_lab_a": round(float(cv.get("lab_a", 0.0)), 3),
            "est_lab_b": round(float(cv.get("lab_b", 0.0)), 3),
            "est_lab_l": round(float(cv.get("lab_l", 0.0)), 3),
            "warmth": round(float(reading.get("warmth", 0.0)), 4),
            "face_detected": int(float(reading.get("face_detected", 0.0)) >= 1.0),
            "white_balanced": int(bool(reading.get("white_balanced"))),
            "skin_quality": round(float(cv.get("quality", 0.0)), 3),
            "error": "",
        })
        if i % 20 == 0:
            print(f"  ...{i}/{len(rows)}", flush=True)

    fields = ["uid", "image_path", "gt_lab_a", "gt_lab_b", "gt_ita",
              "est_lab_a", "est_lab_b", "est_lab_l", "warmth",
              "face_detected", "white_balanced", "skin_quality", "error"]
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in out_rows:
            w.writerow({k: row.get(k, "") for k in fields})
    ok = sum(1 for r in out_rows if not r.get("error"))
    print(f"processed {len(out_rows)} images ({ok} ok) -> {OUT}")
    return 0


def base(r: dict) -> dict:
    return {"uid": r["uid"], "image_path": r["image_path"],
            "gt_lab_a": r["lab_a"], "gt_lab_b": r["lab_b"], "gt_ita": r["ita"]}


if __name__ == "__main__":
    raise SystemExit(main())
