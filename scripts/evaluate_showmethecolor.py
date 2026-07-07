"""ShowMeTheColor(OpenCV/dlib 색상 휴리스틱)를 우리 평가셋에 물려 현행과 비교.

ShowMeTheColor(https://github.com/starbucksdolcelatte/ShowMeTheColor)는 학습 모델이 아니라
dlib 68랜드마크로 뺨/눈썹/눈 대표색을 뽑아 Lab b(웜/쿨) + HSV S(계절)로 사계절을 규칙 분류한다.
README상 4계절은 약하지만 웜/쿨은 70~100%로 강하다고 주장 → warmcool 지표를 특히 본다.

그들의 DetectFace/DominantColors/tone_analysis 를 그대로 재사용한다. dlib predictor는 절대경로로
1회 로드해 캐시(원본은 상대경로 '../res/...' 하드코딩 + 이미지마다 재로딩).

Usage:
    backend/.venv/Scripts/python.exe scripts/evaluate_showmethecolor.py \
        --manifest data/eval/deeparmo_test_manifest.csv \
        --smtc-src "<...>/ShowMeTheColor/src" \
        --out-dir data/eval/reports_smtc_deeparmo
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

SEASONS = ("spring", "summer", "autumn", "winter")
_ALIAS = {
    "spring": "spring", "spr": "spring", "봄": "spring", "봄웜": "spring",
    "summer": "summer", "sum": "summer", "여름": "summer", "여름쿨": "summer",
    "autumn": "autumn", "fall": "autumn", "가을": "autumn", "가을웜": "autumn",
    "winter": "winter", "wnt": "winter", "겨울": "winter", "겨울쿨": "winter",
}
_WARM = {"spring", "autumn"}


def _norm_label(raw: str) -> str | None:
    key = (raw or "").strip().lower()
    if key in _ALIAS:
        return _ALIAS[key]
    for token, season in _ALIAS.items():
        if token in key:
            return season
    return None


def warmcool(season: str) -> str:
    return "warm" if season in _WARM else "cool"


def _load_smtc(smtc_src: Path):
    """ShowMeTheColor 모듈 로드 + dlib predictor 절대경로 캐시."""
    sys.path.insert(0, str(smtc_src))

    # ShowMeTheColor는 구버전 numpy 별칭(np.bool 등)을 쓴다 — 최신 numpy에서 제거됨. shim 복원.
    for _alias, _t in (("bool", bool), ("int", int), ("float", float), ("object", object)):
        if not hasattr(np, _alias):
            setattr(np, _alias, _t)

    import dlib

    dat = smtc_src.parent / "res" / "shape_predictor_68_face_landmarks.dat"
    predictor = dlib.shape_predictor(str(dat))
    dlib.shape_predictor = lambda *a, **k: predictor  # DetectFace의 상대경로 호출을 캐시로 대체

    # 최신 imutils의 FACIAL_LANDMARKS_IDXS는 inner_mouth가 추가돼 8항목(원본은 7항목).
    # ShowMeTheColor의 detect_face_part는 7슬롯 + [1:5] 슬라이싱을 가정하므로, 원본이 쓰던
    # 7항목 순서로 되돌린다(뺨은 별도 인덱스, 여기선 눈썹/눈 범위만 실제로 쓰인다).
    from collections import OrderedDict

    from imutils import face_utils
    face_utils.FACIAL_LANDMARKS_IDXS = OrderedDict([
        ("mouth", (48, 68)),
        ("right_eyebrow", (17, 22)),
        ("left_eyebrow", (22, 27)),
        ("right_eye", (36, 42)),
        ("left_eye", (42, 48)),
        ("nose", (27, 36)),
        ("jaw", (0, 17)),
    ])

    from personal_color_analysis import tone_analysis  # noqa: E402
    from personal_color_analysis.color_extract import DominantColors  # noqa: E402
    from personal_color_analysis.detect_face import DetectFace  # noqa: E402
    from colormath.color_conversions import convert_color  # noqa: E402
    from colormath.color_objects import HSVColor, LabColor, sRGBColor  # noqa: E402

    def analyze(imgpath: str) -> tuple[str, dict[str, float]]:
        """(season, features) 반환. features는 뺨/눈썹/눈의 Lab L·a·b, HSV S 등."""
        df = DetectFace(imgpath)
        face = [df.left_cheek, df.right_cheek, df.left_eyebrow,
                df.right_eyebrow, df.left_eye, df.right_eye]
        temp = []
        for f in face:
            dc = DominantColors(f, 4)
            face_part_color, _ = dc.getHistogram()
            temp.append(np.array(face_part_color[0]))
        cheek = np.mean([temp[0], temp[1]], axis=0)
        eyebrow = np.mean([temp[2], temp[3]], axis=0)
        eye = np.mean([temp[4], temp[5]], axis=0)

        parts = {"skin": cheek, "brow": eyebrow, "eye": eye}
        feats: dict[str, float] = {}
        Lab_b, hsv_s = [], []
        for name, c in parts.items():
            rgb = sRGBColor(c[0], c[1], c[2], is_upscaled=True)
            lab = convert_color(rgb, LabColor, through_rgb_type=sRGBColor)
            hsv = convert_color(rgb, HSVColor, through_rgb_type=sRGBColor)
            feats[f"{name}_L"] = round(float(lab.lab_l), 3)
            feats[f"{name}_a"] = round(float(lab.lab_a), 3)
            feats[f"{name}_b"] = round(float(lab.lab_b), 3)
            feats[f"{name}_S"] = round(float(hsv.hsv_s) * 100, 3)
            feats[f"{name}_R"], feats[f"{name}_G"], feats[f"{name}_B"] = (float(c[0]), float(c[1]), float(c[2]))
            Lab_b.append(float(format(lab.lab_b, ".2f")))
            hsv_s.append(float(format(hsv.hsv_s, ".2f")) * 100)

        # 원본 personal_color.analysis 와 동일한 가중치/분기.
        if tone_analysis.is_warm(Lab_b, [30, 20, 5]):
            season = "spring" if tone_analysis.is_spr(hsv_s, [10, 1, 1]) else "autumn"
        else:
            season = "summer" if tone_analysis.is_smr(hsv_s, [10, 1, 1]) else "winter"
        return season, feats

    return analyze


def _resolve(image_path: str) -> Path:
    p = Path(image_path)
    return p if p.is_absolute() else (ROOT / image_path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate ShowMeTheColor heuristic on our eval set.")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--smtc-src", required=True, help="ShowMeTheColor/src 경로")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    analyze = _load_smtc(Path(args.smtc_src).resolve())

    rows = list(csv.DictReader(open(args.manifest, encoding="utf-8-sig")))
    if args.limit:
        rows = rows[: args.limit]

    total = detected = season_ok = warm_ok = 0
    undetected = 0
    predicted_counts: Counter = Counter()
    per_season = {s: {"total": 0, "correct": 0, "warm_correct": 0} for s in SEASONS}
    records = []

    for row in rows:
        actual = _norm_label(row.get("label", ""))
        if actual is None:
            continue
        total += 1
        img = _resolve(row["image_path"])
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                pred, _feats = analyze(str(img))
        except Exception:
            undetected += 1
            records.append({"image_path": row["image_path"], "actual": actual, "predicted": "", "detected": 0})
            continue
        detected += 1
        predicted_counts[pred] += 1
        s_ok = int(pred == actual)
        w_ok = int(warmcool(pred) == warmcool(actual))
        season_ok += s_ok
        warm_ok += w_ok
        per_season[actual]["total"] += 1
        per_season[actual]["correct"] += s_ok
        per_season[actual]["warm_correct"] += w_ok
        records.append({"image_path": row["image_path"], "actual": actual, "predicted": pred, "detected": 1})

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "manifest": args.manifest,
        "total": total,
        "detected": detected,
        "undetected": undetected,
        "detection_rate": round(detected / total, 4) if total else 0.0,
        # detected-only (얼굴 인식된 표본 기준)
        "accuracy_detected": round(season_ok / detected, 4) if detected else 0.0,
        "warmcool_accuracy_detected": round(warm_ok / detected, 4) if detected else 0.0,
        # full-set (미검출=오답, 현행 baseline과 같은 분모)
        "accuracy_full": round(season_ok / total, 4) if total else 0.0,
        "warmcool_accuracy_full": round(warm_ok / total, 4) if total else 0.0,
        "predicted_counts": dict(predicted_counts),
        "per_season": {
            s: {
                "n": v["total"],
                "accuracy": round(v["correct"] / v["total"], 4) if v["total"] else None,
                "warmcool_accuracy": round(v["warm_correct"] / v["total"], 4) if v["total"] else None,
            }
            for s, v in per_season.items()
        },
    }
    with (out_dir / "showmethecolor_eval_report.json").open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with (out_dir / "predictions.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["image_path", "actual", "predicted", "detected"])
        w.writeheader()
        w.writerows(records)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
