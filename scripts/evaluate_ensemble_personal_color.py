"""여러 EfficientNet 체크포인트를 softmax 평균 앙상블해 현행 blend 파이프라인으로 평가.

분석기가 쓰는 분류기 인터페이스(available/load/predict/predict_probs)를 그대로 구현한 앙상블
래퍼를 analyzer_module._season_classifier 에 주입하고, 기존 evaluate_personal_color_model 의
평가 로직(모델+색상 blend, warmcool 등)을 그대로 재사용한다.

Usage:
    backend/.venv/Scripts/python.exe scripts/evaluate_ensemble_personal_color.py \
        --models data/models/personal_color_efficientnet.pt,data/models/personal_color_retrain_try1_no_mixup_no_smooth.pt \
        --manifest data/eval/deeparmo_test_manifest.csv \
        --out-dir data/eval/reports_ensemble_deeparmo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.ai.personal_color_model import SEASONS, EfficientNetSeasonClassifier  # noqa: E402
import app.services.personal_color_analyzer as analyzer_module  # noqa: E402


class EnsembleSeasonClassifier:
    """N개 체크포인트의 predict_probs(각자 TTA 내장)를 평균낸다."""

    def __init__(self, model_paths: list[str]) -> None:
        self.subs = [EfficientNetSeasonClassifier(p) for p in model_paths]

    @property
    def available(self) -> bool:
        return any(s.available for s in self.subs)

    def load(self) -> bool:
        return any(s.load() for s in self.subs)

    def predict_probs(self, image: Image.Image, *, tta: bool = True) -> dict[str, float] | None:
        acc: dict[str, float] | None = None
        n = 0
        for s in self.subs:
            p = s.predict_probs(image, tta=tta)
            if p is None:
                continue
            if acc is None:
                acc = {k: 0.0 for k in p}
            for k, v in p.items():
                acc[k] += v
            n += 1
        if not n or acc is None:
            return None
        return {k: v / n for k, v in acc.items()}

    def predict(self, image: Image.Image) -> tuple[str, float] | None:
        probs = self.predict_probs(image)
        if probs is None:
            return None
        season = max(probs, key=probs.get)
        return season, probs[season]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True, help="쉼표로 구분한 .pt 경로들")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    paths = []
    for m in args.models.split(","):
        m = m.strip()
        if not m:
            continue
        p = Path(m)
        paths.append(str(p if p.is_absolute() else ROOT / m))
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        raise SystemExit(f"model(s) not found: {missing}")

    analyzer_module._season_classifier = EnsembleSeasonClassifier(paths)
    print(f"Ensemble of {len(paths)} models:")
    for p in paths:
        print("  -", Path(p).name)

    import evaluate_personal_color_model as ev

    # --model-path 를 주지 않으면 ev 는 위에서 주입한 앙상블 분류기를 그대로 쓴다.
    sys.argv = ["evaluate_personal_color_model", "--manifest", args.manifest, "--out-dir", args.out_dir]
    return ev.main()


if __name__ == "__main__":
    raise SystemExit(main())
