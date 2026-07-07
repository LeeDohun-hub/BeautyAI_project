"""Evaluate a Hugging Face/timm personal color classifier on local manifests.

Example:
    python scripts/evaluate_hf_personal_color_model.py ^
      --manifest data/eval/deeparmo_test_manifest.csv ^
      --out-dir data/eval/reports_hf_jiwoon_deeparmo ^
      --tta

The default model is jiwoonkim00/personal-color-classifier. Its model card
describes an EfficientNet-B0 classifier with four labels:
spring_warm, summer_cool, autumn_warm, winter_cool.
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

SEASONS = ("spring", "summer", "autumn", "winter")
DEFAULT_LABEL_ORDER = ("spring_warm", "summer_cool", "autumn_warm", "winter_cool")
SEASON_ALIASES = {
    "spring": "spring",
    "spr": "spring",
    "봄": "spring",
    "봄웜": "spring",
    "봄 웜": "spring",
    "spring_warm": "spring",
    "summer": "summer",
    "sum": "summer",
    "여름": "summer",
    "여쿨": "summer",
    "여름쿨": "summer",
    "summer_cool": "summer",
    "autumn": "autumn",
    "fall": "autumn",
    "가을": "autumn",
    "가을웜": "autumn",
    "가을 웜": "autumn",
    "autumn_warm": "autumn",
    "winter": "winter",
    "win": "winter",
    "겨울": "winter",
    "겨쿨": "winter",
    "겨울쿨": "winter",
    "winter_cool": "winter",
}


def _dependency_error(exc: Exception) -> SystemExit:
    return SystemExit(
        "Missing dependency for HF evaluation. Install with:\n"
        "  backend\\.venv\\Scripts\\python.exe -m pip install timm huggingface_hub safetensors\n"
        f"Original error: {exc!r}"
    )


def load_runtime_dependencies():
    try:
        import torch
        import timm
        from huggingface_hub import hf_hub_download
        from PIL import Image
        from torchvision import transforms
    except Exception as exc:  # pragma: no cover - exercised in user env only
        raise _dependency_error(exc) from exc

    try:
        import numpy as np
        from app.services.personal_color_analyzer import PersonalColorAnalyzer
    except Exception:
        np = None
        PersonalColorAnalyzer = None
    return torch, timm, hf_hub_download, Image, transforms, np, PersonalColorAnalyzer


def normalize_season(value: str) -> str:
    text = (value or "").strip().lower()
    if text in SEASON_ALIASES:
        return SEASON_ALIASES[text]
    for alias, season in SEASON_ALIASES.items():
        if alias in text:
            return season
    raise ValueError(f"unknown season label: {value!r}")


def warmcool(season: str) -> str:
    return "warm" if season in {"spring", "autumn"} else "cool"


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
        "warmcool_correct",
        "top1_prob",
        "top2_prob",
        "prob_spring",
        "prob_summer",
        "prob_autumn",
        "prob_winter",
        "raw_label",
        "face_cropped",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in predictions:
            writer.writerow({field: row.get(field, "") for field in fields})


def label_to_season(label: str) -> str:
    return normalize_season(label)


def load_rgb_image(path: Path, analyzer: Any | None, use_face_crop: bool) -> tuple[Image.Image, bool]:
    image = Image.open(path).convert("RGB")
    if not use_face_crop:
        return image, False
    if analyzer is None or np is None:
        raise SystemExit("Face crop requested, but backend analyzer dependencies are unavailable.")
    rgb = np.asarray(image)
    crop_rgb, face_detected = analyzer._face_crop(rgb)
    if not face_detected:
        return image, False
    return Image.fromarray(crop_rgb.astype("uint8")).convert("RGB"), True


def predict_probs(
    model: torch.nn.Module,
    transforms_list,
    image: Image.Image,
    labels: tuple[str, ...],
    device: torch.device,
) -> dict[str, float]:
    probs_sum = None
    with torch.no_grad():
        for transform in transforms_list:
            batch = transform(image).unsqueeze(0).to(device)
            logits = model(batch)
            if isinstance(logits, (tuple, list)):
                logits = logits[0]
            probs = torch.softmax(logits, dim=1).squeeze(0).detach().cpu()
            probs_sum = probs if probs_sum is None else probs_sum + probs
    averaged = probs_sum / len(transforms_list)
    return {
        label_to_season(label): float(averaged[index])
        for index, label in enumerate(labels)
    }


def build_transforms(transforms_module, tta: bool):
    mean = [0.485, 0.456, 0.406]
    std = [0.229, 0.224, 0.225]
    if not tta:
        return [
            transforms_module.Compose(
                [
                    transforms_module.Resize(256),
                    transforms_module.CenterCrop(224),
                    transforms_module.ToTensor(),
                    transforms_module.Normalize(mean, std),
                ]
            )
        ]
    return [
        transforms_module.Compose(
            [
                transforms_module.Resize(256),
                transforms_module.CenterCrop(224),
                transforms_module.ToTensor(),
                transforms_module.Normalize(mean, std),
            ]
        ),
        transforms_module.Compose(
            [
                transforms_module.Resize(256),
                transforms_module.CenterCrop(224),
                transforms_module.RandomHorizontalFlip(p=1.0),
                transforms_module.ToTensor(),
                transforms_module.Normalize(mean, std),
            ]
        ),
        transforms_module.Compose(
            [
                transforms_module.Resize(232),
                transforms_module.CenterCrop(224),
                transforms_module.ToTensor(),
                transforms_module.Normalize(mean, std),
            ]
        ),
        transforms_module.Compose(
            [
                transforms_module.Resize(232),
                transforms_module.CenterCrop(224),
                transforms_module.RandomHorizontalFlip(p=1.0),
                transforms_module.ToTensor(),
                transforms_module.Normalize(mean, std),
            ]
        ),
        transforms_module.Compose(
            [
                transforms_module.Resize(280),
                transforms_module.CenterCrop(224),
                transforms_module.ToTensor(),
                transforms_module.Normalize(mean, std),
            ]
        ),
        transforms_module.Compose(
            [
                transforms_module.Resize(280),
                transforms_module.CenterCrop(224),
                transforms_module.RandomHorizontalFlip(p=1.0),
                transforms_module.ToTensor(),
                transforms_module.Normalize(mean, std),
            ]
        ),
    ]


def load_hf_checkpoint_model(timm, torch, hf_hub_download, args, device):
    if args.checkpoint:
        checkpoint_path = Path(args.checkpoint)
        if not checkpoint_path.is_absolute():
            checkpoint_path = ROOT / checkpoint_path
    else:
        checkpoint_path = Path(hf_hub_download(args.hf_repo, args.checkpoint_file))
    model = timm.create_model(args.model_name, pretrained=False, num_classes=4)
    # HF checkpoint contains numpy scalar metadata; this is a trusted model
    # source selected for evaluation, so load the full checkpoint explicitly.
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    state = checkpoint.get("model_state_dict", checkpoint)
    model.load_state_dict(state)
    return model.to(device).eval(), str(checkpoint_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a HF/timm personal color classifier.")
    parser.add_argument("--manifest", required=True, help="CSV with image_path,label or image_path,season.")
    parser.add_argument("--out-dir", default="data/eval/reports_hf_personal_color")
    parser.add_argument("--hf-repo", default="jiwoonkim00/personal-color-classifier")
    parser.add_argument("--checkpoint-file", default="personal_color_korean_tuned_v2.pt")
    parser.add_argument("--checkpoint", default="", help="Optional local .pt checkpoint path.")
    parser.add_argument("--model-name", default="efficientnet_b0.ra_in1k")
    parser.add_argument(
        "--label-order",
        default=",".join(DEFAULT_LABEL_ORDER),
        help="Comma-separated class order for model logits.",
    )
    parser.add_argument("--tta", action="store_true", help="Average original and horizontal flip predictions.")
    parser.add_argument("--no-face-crop", action="store_true", help="Evaluate the full image instead of production face crop.")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    (
        torch,
        timm,
        hf_hub_download,
        Image,
        transforms,
        np,
        PersonalColorAnalyzer,
    ) = load_runtime_dependencies()
    globals()["torch"] = torch
    globals()["Image"] = Image
    globals()["np"] = np

    labels = tuple(label.strip() for label in args.label_order.split(",") if label.strip())
    if len(labels) != 4:
        raise SystemExit("--label-order must contain exactly 4 labels")
    for label in labels:
        label_to_season(label)

    manifest = Path(args.manifest)
    rows = read_manifest(manifest)
    if args.limit:
        rows = rows[: args.limit]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, checkpoint_path = load_hf_checkpoint_model(timm, torch, hf_hub_download, args, device)
    transforms_list = build_transforms(transforms, args.tta)
    analyzer = PersonalColorAnalyzer() if not args.no_face_crop and PersonalColorAnalyzer is not None else None

    matrix = empty_matrix()
    predictions: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    label_counts: Counter[str] = Counter()
    predicted_counts: Counter[str] = Counter()
    face_cropped_count = 0

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
            image, face_cropped = load_rgb_image(image_path, analyzer, not args.no_face_crop)
            probs = predict_probs(model, transforms_list, image, labels, device)
        except Exception as exc:
            errors.append({"row": str(index), "image_path": str(image_path), "error": repr(exc)})
            continue

        ordered = sorted(probs.items(), key=lambda item: item[1], reverse=True)
        predicted = ordered[0][0]
        top2 = [season for season, _ in ordered[:2]]
        correct = predicted == actual
        top2_correct = actual in top2
        warmcool_correct = warmcool(predicted) == warmcool(actual)

        matrix[actual][predicted] += 1
        label_counts[actual] += 1
        predicted_counts[predicted] += 1
        face_cropped_count += int(face_cropped)
        predictions.append(
            {
                "image_path": str(image_path),
                "actual": actual,
                "predicted": predicted,
                "correct": int(correct),
                "top2_correct": int(top2_correct),
                "warmcool_correct": int(warmcool_correct),
                "top1_prob": round(float(ordered[0][1]), 4),
                "top2_prob": round(float(ordered[1][1]), 4),
                "prob_spring": round(float(probs["spring"]), 4),
                "prob_summer": round(float(probs["summer"]), 4),
                "prob_autumn": round(float(probs["autumn"]), 4),
                "prob_winter": round(float(probs["winter"]), 4),
                "raw_label": labels[[label_to_season(label) for label in labels].index(predicted)],
                "face_cropped": int(face_cropped),
            }
        )

    total = len(predictions)
    correct_total = sum(int(row["correct"]) for row in predictions)
    top2_total = sum(int(row["top2_correct"]) for row in predictions)
    warmcool_total = sum(int(row["warmcool_correct"]) for row in predictions)
    per_season = {}
    for season in SEASONS:
        season_total = label_counts[season]
        season_correct = sum(1 for row in predictions if row["actual"] == season and row["predicted"] == season)
        per_season[season] = {
            "total": season_total,
            "correct": season_correct,
            "accuracy": round(season_correct / season_total, 4) if season_total else None,
        }

    report = {
        "manifest": str(manifest),
        "hf_repo": args.hf_repo,
        "checkpoint_file": args.checkpoint_file,
        "checkpoint_path": checkpoint_path,
        "model_name": args.model_name,
        "label_order": labels,
        "tta": args.tta,
        "face_crop": not args.no_face_crop,
        "device": str(device),
        "total": total,
        "errors": len(errors),
        "accuracy": round(correct_total / total, 4) if total else 0.0,
        "top2_accuracy": round(top2_total / total, 4) if total else 0.0,
        "warmcool_accuracy": round(warmcool_total / total, 4) if total else 0.0,
        "face_cropped_rate": round(face_cropped_count / total, 4) if total else 0.0,
        "label_counts": dict(label_counts),
        "predicted_counts": dict(predicted_counts),
        "per_season": per_season,
        "confusion_matrix": matrix,
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
    print(f"predicted={dict(predicted_counts)}")
    print(f"face_cropped_rate={report['face_cropped_rate']:.4f}")
    print(f"report: {report_path}")
    print(f"matrix: {matrix_path}")
    print(f"predictions: {predictions_path}")
    if errors:
        print(f"errors: {errors_path}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
