"""후기융합(late fusion): 현행 EfficientNet 모델 확률 + 재캘리브레이션 SMTC 색 확률.

이미지마다 (1) 분석기의 model_season_probs(현행 EfficientNet, baseline 0.5362와 동일 크롭),
(2) SMTC 색 특징 → 우리 train으로 학습한 logreg 확률을 구해 가중평균으로 융합한다.
가중치 w 를 스윕해 (w=1 모델만 … w=0 색만) deeparmo/capstonea 정확도·warmcool을 낸다.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_showmethecolor as smtc  # noqa: E402
import smtc_recalibrate as recal  # noqa: E402
from app.ai.personal_color_model import EfficientNetSeasonClassifier  # noqa: E402
import app.services.personal_color_analyzer as am  # noqa: E402
from app.services.personal_color_analyzer import PersonalColorAnalyzer  # noqa: E402

SEASONS = ("spring", "summer", "autumn", "winter")
WARM = {"spring", "autumn"}
# c = 재캘SMTC색을 '현행 분석기 최종 확률'에 가산하는 비중. c=0 → 현행 그대로(정합성 체크).
WEIGHTS = [0.0, 0.1, 0.15, 0.2, 0.25, 0.35, 0.5, 1.0]


def _wc(s: str) -> str:
    return "warm" if s in WARM else "cool"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smtc-src", required=True)
    ap.add_argument("--train", required=True)
    ap.add_argument("--test", action="append", required=True, help="name=manifest.csv")
    ap.add_argument("--model", default="data/models/personal_color_efficientnet.pt")
    ap.add_argument("--limit-per-class", type=int, default=300)
    args = ap.parse_args()

    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    analyze = smtc._load_smtc(Path(args.smtc_src).resolve())

    # train 특징(캐시 히트) → logreg
    names, Xtr, ytr = recal.extract("train", args.train, analyze, args.limit_per_class, partition="train")
    scaler = StandardScaler().fit(Xtr)
    clf = LogisticRegression(max_iter=2000, class_weight="balanced").fit(scaler.transform(Xtr), ytr)
    classes = list(clf.classes_)

    am._season_classifier = EfficientNetSeasonClassifier(str((ROOT / args.model)))
    analyzer = PersonalColorAnalyzer()

    baselines = {"deeparmo": (0.5362, 0.67), "capstonea": (0.4133, 0.6133)}
    t0 = time.time()
    done = 0

    for spec in args.test:
        name, manifest = spec.split("=", 1)
        rows = list(csv.DictReader(open(manifest, encoding="utf-8-sig")))
        stats = {w: {"n": 0, "acc": 0, "wc": 0} for w in WEIGHTS}
        for i, r in enumerate(rows, 1):
            actual = smtc._norm_label(r.get("season") or r.get("label") or "")
            if actual is None:
                continue
            img = smtc._resolve(r["image_path"])

            final_probs = None  # 현행 분석기 최종 blended 확률(model + 내부 색 분기)
            try:
                reading = analyzer._read_one(img.read_bytes())
                fp = reading.get("season_probs")
                if fp:
                    final_probs = np.array([fp.get(s, 0.0) for s in SEASONS], dtype=float)
            except Exception:
                final_probs = None

            color_probs = None
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    _, feats = analyze(str(img))
                pv = clf.predict_proba(scaler.transform([[feats[k] for k in names]]))[0]
                cp = {c: pv[j] for j, c in enumerate(classes)}
                color_probs = np.array([cp.get(s, 0.0) for s in SEASONS], dtype=float)
            except Exception:
                color_probs = None

            if final_probs is None and color_probs is None:
                continue
            done += 1
            for c in WEIGHTS:
                if final_probs is None:
                    fused = color_probs
                elif color_probs is None:
                    fused = final_probs
                else:
                    fused = (1 - c) * final_probs + c * color_probs
                pred = SEASONS[int(np.argmax(fused))]
                stats[c]["n"] += 1
                stats[c]["acc"] += int(pred == actual)
                stats[c]["wc"] += int(_wc(pred) == _wc(actual))
            if i % 100 == 0:
                rate = (time.time() - t0) / max(done, 1)
                print(f"  [{name}] {i}/{len(rows)}  ({rate:.2f}s/img)", flush=True)

        base = baselines.get(name)
        print(f"\n=== {name} (n={stats[WEIGHTS[0]]['n']}) | 현행 acc={base[0] if base else '?'} warmcool={base[1] if base else '?'} ===")
        for c in WEIGHTS:
            s = stats[c]
            n = s["n"] or 1
            tag = "SMTC색만" if c == 1.0 else ("현행그대로" if c == 0.0 else "")
            print(f"  c={c:<4} acc={s['acc']/n:.4f} warmcool={s['wc']/n:.4f} {tag}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
