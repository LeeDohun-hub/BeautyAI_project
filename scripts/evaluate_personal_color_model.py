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
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

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
        "correct",
        "top2_correct",
        "confidence",
        "top1_prob",
        "top2_prob",
        "season_margin",
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
        ordered_probs = sorted((probs or {}).items(), key=lambda item: item[1], reverse=True)
        top2 = top2_from_probs(probs, predicted)
        correct = predicted == actual
        top2_correct = actual in top2

        matrix[actual][predicted] += 1
        label_counts[actual] += 1
        predicted_counts[predicted] += 1
        model_used_count += int(response.metrics.get("model_used", 0.0) >= 1.0)
        face_detected_count += int(response.metrics.get("face_detected", 0.0) >= 1.0)
        predictions.append(
            {
                "image_path": str(image_path),
                "actual": actual,
                "predicted": predicted,
                "correct": int(correct),
                "top2_correct": int(top2_correct),
                "confidence": response.confidence,
                "top1_prob": round(float(ordered_probs[0][1]), 4) if ordered_probs else "",
                "top2_prob": round(float(ordered_probs[1][1]), 4) if len(ordered_probs) > 1 else "",
                "season_margin": response.metrics.get("season_margin", ""),
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
    print(f"accuracy={report['accuracy']:.4f} top2_accuracy={report['top2_accuracy']:.4f}")
    print(f"model_used_rate={report['model_used_rate']:.4f} face_detected_rate={report['face_detected_rate']:.4f}")
    print(f"report: {report_path}")
    print(f"matrix: {matrix_path}")
    print(f"predictions: {predictions_path}")
    if errors:
        print(f"errors: {errors_path}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
