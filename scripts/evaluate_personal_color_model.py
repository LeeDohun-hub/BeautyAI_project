"""Evaluate the production personal color analyzer on an expert-labeled set.

The manifest should be a CSV with at least:

    image_path,label

`label` may be one of spring/summer/autumn/winter, a Korean label containing
봄/여름/가을/겨울, or an analyzer label such as "summer cool mute".

Example:
    python scripts/evaluate_personal_color_model.py \
        --manifest data/eval/personal_color_eval_manifest.csv \
        --out-dir data/eval/reports

    python scripts/evaluate_personal_color_model.py \
        --manifest data/eval/personal_color_eval_manifest.csv \
        --model-path data/models/personal_color_efficientnet.pt \
        --out-dir data/eval/reports_candidate
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

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
SEASON_ALIASES = {
    "spring": "spring",
    "spr": "spring",
    "봄": "spring",
    "봄웜": "spring",
    "봄 웜": "spring",
    "summer": "summer",
    "sum": "summer",
    "여름": "summer",
    "여름쿨": "summer",
    "여름 쿨": "summer",
    "autumn": "autumn",
    "fall": "autumn",
    "가을": "autumn",
    "가을웜": "autumn",
    "가을 웜": "autumn",
    "winter": "winter",
    "win": "winter",
    "겨울": "winter",
    "겨울쿨": "winter",
    "겨울 쿨": "winter",
}


def normalize_season(value: str) -> str:
    text = (value or "").strip().lower()
    if text in SEASON_ALIASES:
        return SEASON_ALIASES[text]
    for alias, season in SEASON_ALIASES.items():
        if alias in text:
            return season
    raise ValueError(f"unknown season label: {value!r}")


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise SystemExit(f"manifest is empty: {path}")
    if "image_path" not in rows[0]:
        raise SystemExit("manifest must include image_path")
    if "label" not in rows[0] and "season" not in rows[0]:
        raise SystemExit("manifest must include label or season")
    return rows


def resolve_image_path(value: str, manifest_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [manifest_dir / path, ROOT / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_project_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT / path


def top2_from_probs(probs: dict[str, float] | None, fallback: str) -> list[str]:
    if not probs:
        return [fallback]
    return [season for season, _ in sorted(probs.items(), key=lambda item: item[1], reverse=True)[:2]]


def predict_from_probs(probs: dict[str, float] | None, fallback: str) -> str:
    if not probs:
        return fallback
    return max(probs, key=probs.get)


def warmcool(season: str) -> str:
    return "warm" if season in {"spring", "autumn"} else "cool"


def empty_matrix() -> dict[str, dict[str, int]]:
    return {actual: {pred: 0 for pred in SEASONS} for actual in SEASONS}


def write_confusion_matrix(path: Path, matrix: dict[str, dict[str, int]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["actual", *SEASONS])
        for actual in SEASONS:
            writer.writerow([actual, *[matrix[actual][pred] for pred in SEASONS]])


def write_predictions(path: Path, predictions: list[dict[str, Any]]) -> None:
    fields = [
        "image_path",
        "actual",
        "predicted",
        "model_predicted",
        "color_predicted",
        "correct",
        "model_correct",
        "color_correct",
        "top2_correct",
        "model_top2_correct",
        "color_top2_correct",
        "warmcool_correct",
        "model_warmcool_correct",
        "color_warmcool_correct",
        "confidence",
        "top1_prob",
        "top2_prob",
        "model_top1_prob",
        "color_top1_prob",
        "season_margin",
        "color_vector_used",
        "skin_vector_quality",
        "lab_l",
        "lab_a",
        "lab_b",
        "hsv_s",
        "landmark_skin_samples",
        "alternate_label",
        "model_used",
        "face_detected",
        "capture_quality",
        "label",
        "decision_note",
        "summary",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in predictions:
            writer.writerow({field: row.get(field, "") for field in fields})


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the production personal color analyzer.")
    parser.add_argument("--manifest", required=True, help="CSV with image_path,label or image_path,season.")
    parser.add_argument("--out-dir", default="data/eval/reports")
    parser.add_argument(
        "--model-path",
        default="",
        help="Optional candidate .pt path. When omitted, the app settings model path is used.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional debug limit.")
    args = parser.parse_args()

    manifest = Path(args.manifest)
    rows = read_manifest(manifest)
    if args.limit:
        rows = rows[: args.limit]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    model_path = ""
    if args.model_path:
        candidate_model_path = resolve_project_path(args.model_path)
        if not candidate_model_path.exists():
            raise SystemExit(f"model not found: {candidate_model_path}")
        model_path = str(candidate_model_path)
        analyzer_module._season_classifier = EfficientNetSeasonClassifier(model_path)

    analyzer = PersonalColorAnalyzer()
    matrix = empty_matrix()
    predictions: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    label_counts: Counter[str] = Counter()
    predicted_counts: Counter[str] = Counter()
    method_counts: dict[str, Counter[str]] = {
        "blended": Counter(),
        "model": Counter(),
        "color": Counter(),
    }
    model_used_count = 0
    face_detected_count = 0

    for index, row in enumerate(rows, start=1):
        raw_label = row.get("label") or row.get("season") or ""
        try:
            actual = normalize_season(raw_label)
        except ValueError as exc:
            errors.append({"row": str(index), "image_path": row.get("image_path", ""), "error": str(exc)})
            continue

        image_path = resolve_image_path(row["image_path"], manifest.parent)
        if not image_path.exists():
            errors.append({"row": str(index), "image_path": str(image_path), "error": "image not found"})
            continue

        try:
            reading = analyzer._read_one(image_path.read_bytes())
            response = analyzer._build_response(reading, samples=1)
        except Exception as exc:
            errors.append({"row": str(index), "image_path": str(image_path), "error": repr(exc)})
            continue

        predicted = response.season
        probs = reading.get("season_probs")
        model_probs = reading.get("model_season_probs")
        color_probs = reading.get("color_season_probs")
        ordered_probs = sorted((probs or {}).items(), key=lambda item: item[1], reverse=True)
        ordered_model_probs = sorted((model_probs or {}).items(), key=lambda item: item[1], reverse=True)
        ordered_color_probs = sorted((color_probs or {}).items(), key=lambda item: item[1], reverse=True)
        model_predicted = predict_from_probs(model_probs, predicted)
        color_predicted = predict_from_probs(color_probs, predicted)
        top2 = top2_from_probs(probs, predicted)
        model_top2 = top2_from_probs(model_probs, model_predicted)
        color_top2 = top2_from_probs(color_probs, color_predicted)
        correct = predicted == actual
        model_correct = model_predicted == actual
        color_correct = color_predicted == actual
        top2_correct = actual in top2
        model_top2_correct = actual in model_top2
        color_top2_correct = actual in color_top2
        warmcool_correct = warmcool(predicted) == warmcool(actual)
        model_warmcool_correct = warmcool(model_predicted) == warmcool(actual)
        color_warmcool_correct = warmcool(color_predicted) == warmcool(actual)

        matrix[actual][predicted] += 1
        label_counts[actual] += 1
        predicted_counts[predicted] += 1
        method_counts["blended"][predicted] += 1
        method_counts["model"][model_predicted] += 1
        method_counts["color"][color_predicted] += 1
        model_used_count += int(response.metrics.get("model_used", 0.0) >= 1.0)
        face_detected_count += int(response.metrics.get("face_detected", 0.0) >= 1.0)
        predictions.append(
            {
                "image_path": str(image_path),
                "actual": actual,
                "predicted": predicted,
                "model_predicted": model_predicted,
                "color_predicted": color_predicted,
                "correct": int(correct),
                "model_correct": int(model_correct),
                "color_correct": int(color_correct),
                "top2_correct": int(top2_correct),
                "model_top2_correct": int(model_top2_correct),
                "color_top2_correct": int(color_top2_correct),
                "warmcool_correct": int(warmcool_correct),
                "model_warmcool_correct": int(model_warmcool_correct),
                "color_warmcool_correct": int(color_warmcool_correct),
                "confidence": response.confidence,
                "top1_prob": round(float(ordered_probs[0][1]), 4) if ordered_probs else "",
                "top2_prob": round(float(ordered_probs[1][1]), 4) if len(ordered_probs) > 1 else "",
                "model_top1_prob": round(float(ordered_model_probs[0][1]), 4) if ordered_model_probs else "",
                "color_top1_prob": round(float(ordered_color_probs[0][1]), 4) if ordered_color_probs else "",
                "season_margin": response.metrics.get("season_margin", ""),
                "color_vector_used": response.metrics.get("color_vector_used", 0.0),
                "skin_vector_quality": response.metrics.get("skin_vector_quality", ""),
                "lab_l": response.metrics.get("lab_l", ""),
                "lab_a": response.metrics.get("lab_a", ""),
                "lab_b": response.metrics.get("lab_b", ""),
                "hsv_s": response.metrics.get("hsv_s", ""),
                "landmark_skin_samples": response.metrics.get("landmark_skin_samples", ""),
                "alternate_label": response.alternate_label or "",
                "model_used": response.metrics.get("model_used", 0.0),
                "face_detected": response.metrics.get("face_detected", 0.0),
                "capture_quality": response.metrics.get("capture_quality", 0.0),
                "label": response.label,
                "decision_note": response.decision_note or "",
                "summary": response.skin_summary,
            }
        )

    total = len(predictions)
    correct_total = sum(int(row["correct"]) for row in predictions)
    top2_total = sum(int(row["top2_correct"]) for row in predictions)
    warmcool_total = sum(int(row["warmcool_correct"]) for row in predictions)
    method_metrics = {}
    for method, prefix in (("blended", ""), ("model", "model_"), ("color", "color_")):
        method_correct = sum(int(row[f"{prefix}correct"]) for row in predictions)
        method_top2 = sum(int(row[f"{prefix}top2_correct"]) for row in predictions)
        method_warmcool = sum(int(row[f"{prefix}warmcool_correct"]) for row in predictions)
        method_metrics[method] = {
            "accuracy": round(method_correct / total, 4) if total else 0.0,
            "top2_accuracy": round(method_top2 / total, 4) if total else 0.0,
            "warmcool_accuracy": round(method_warmcool / total, 4) if total else 0.0,
            "predicted_counts": dict(method_counts[method]),
        }
    low_margin_total = sum(
        1
        for row in predictions
        if isinstance(row.get("season_margin"), (float, int)) and float(row["season_margin"]) < 0.16
    )
    per_season = {}
    for season in SEASONS:
        season_total = label_counts[season]
        season_correct = sum(
            1 for row in predictions if row["actual"] == season and row["predicted"] == season
        )
        per_season[season] = {
            "total": season_total,
            "correct": season_correct,
            "accuracy": round(season_correct / season_total, 4) if season_total else None,
        }

    report = {
        "manifest": str(manifest),
        "model_path": model_path or "app settings",
        "total": total,
        "errors": len(errors),
        "accuracy": round(correct_total / total, 4) if total else 0.0,
        "top2_accuracy": round(top2_total / total, 4) if total else 0.0,
        "warmcool_accuracy": round(warmcool_total / total, 4) if total else 0.0,
        "method_metrics": method_metrics,
        "low_margin_rate": round(low_margin_total / total, 4) if total else 0.0,
        "low_margin_count": low_margin_total,
        "model_used_rate": round(model_used_count / total, 4) if total else 0.0,
        "face_detected_rate": round(face_detected_count / total, 4) if total else 0.0,
        "label_counts": dict(label_counts),
        "predicted_counts": dict(predicted_counts),
        "per_season": per_season,
        "confusion_matrix": matrix,
        "high_value_confusions": {
            "summer_as_winter": matrix["summer"]["winter"],
            "winter_as_summer": matrix["winter"]["summer"],
            "spring_as_autumn": matrix["spring"]["autumn"],
            "autumn_as_spring": matrix["autumn"]["spring"],
        },
    }

    report_path = out_dir / "personal_color_eval_report.json"
    matrix_path = out_dir / "confusion_matrix.csv"
    predictions_path = out_dir / "predictions.csv"
    errors_path = out_dir / "errors.json"

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_confusion_matrix(matrix_path, matrix)
    write_predictions(predictions_path, predictions)
    errors_path.write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"evaluated={total} errors={len(errors)}")
    print(
        f"accuracy={report['accuracy']:.4f} top2_accuracy={report['top2_accuracy']:.4f} "
        f"warmcool_accuracy={report['warmcool_accuracy']:.4f}"
    )
    for method, metrics in method_metrics.items():
        print(
            f"{method}: accuracy={metrics['accuracy']:.4f} "
            f"top2={metrics['top2_accuracy']:.4f} warmcool={metrics['warmcool_accuracy']:.4f} "
            f"predicted={metrics['predicted_counts']}"
        )
    print(f"model_used_rate={report['model_used_rate']:.4f} face_detected_rate={report['face_detected_rate']:.4f}")
    print(f"report: {report_path}")
    print(f"matrix: {matrix_path}")
    print(f"predictions: {predictions_path}")
    if errors:
        print(f"errors: {errors_path}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
