"""ShowMeTheColor 색 특징을 우리 데이터로 재캘리브레이션.

SMTC의 하드코딩 기준값은 한국 스튜디오 사진에 맞춰져 우리 평가셋(특히 유럽 Deep Armo)에서
autumn으로 붕괴한다. 알고리즘 구조(뺨/눈썹/눈 대표색 → Lab/HSV)는 유지하되, 그 색 특징을
'특징 추출기'로만 쓰고 분류기는 우리 train 라벨로 새로 학습한다.

- train 특징으로 LogisticRegression 학습 → test(deeparmo/capstonea) 평가.
- accuracy + warmcool 을 현행(blended 0.5362 / 0.4133)과 비교.
- 특징은 CSV로 캐시(재추출 비쌈).

Usage:
    backend/.venv/Scripts/python.exe scripts/smtc_recalibrate.py \
        --smtc-src "<...>/ShowMeTheColor/src" \
        --train data/manifests/personal_color_manifest.csv \
        --test deeparmo=data/eval/deeparmo_test_manifest.csv \
        --test capstonea=data/eval/capstonea_test_manifest.csv \
        --limit-per-class 300
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_showmethecolor as smtc  # noqa: E402

SEASONS = ("spring", "summer", "autumn", "winter")
WARM = {"spring", "autumn"}
_CACHE_DIR = ROOT / "data" / "eval" / "_smtc_features"


def _label_of(row: dict) -> str | None:
    return smtc._norm_label(row.get("season") or row.get("label") or "")


def _rows(manifest: str, limit_per_class: int, partition: str | None) -> list[dict]:
    rows = list(csv.DictReader(open(manifest, encoding="utf-8-sig")))
    if partition:
        rows = [r for r in rows if (r.get("partition") or "") == partition]
    if limit_per_class:
        by: dict[str, list] = {s: [] for s in SEASONS}
        random.Random(0).shuffle(rows)
        for r in rows:
            lab = _label_of(r)
            if lab and len(by[lab]) < limit_per_class:
                by[lab].append(r)
        rows = [r for lst in by.values() for r in lst]
    return rows


def extract(name: str, manifest: str, analyze, limit_per_class: int = 0, partition: str | None = None):
    """(feature_names, X, y). CSV 캐시."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{name}_{limit_per_class}_{partition or 'all'}"
    cache = _CACHE_DIR / f"{tag}.csv"
    if cache.exists():
        data = list(csv.DictReader(open(cache, encoding="utf-8-sig")))
        names = [c for c in data[0].keys() if c != "label"]
        X = np.array([[float(r[c]) for c in names] for r in data])
        y = [r["label"] for r in data]
        print(f"  [{name}] cache hit: {len(y)} rows")
        return names, X, y

    rows = _rows(manifest, limit_per_class, partition)
    feats_list, y = [], []
    names = None
    ok = 0
    for i, r in enumerate(rows, 1):
        lab = _label_of(r)
        if lab is None:
            continue
        img = smtc._resolve(r["image_path"])
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                _, feats = analyze(str(img))
        except Exception:
            continue
        if names is None:
            names = list(feats.keys())
        feats_list.append([feats[k] for k in names])
        y.append(lab)
        ok += 1
        if i % 200 == 0:
            print(f"  [{name}] {i}/{len(rows)} -> {ok} extracted")
    X = np.array(feats_list)
    with cache.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(names + ["label"])
        for row, lab in zip(feats_list, y):
            w.writerow(row + [lab])
    print(f"  [{name}] extracted {ok}/{len(rows)} -> cached {cache.name}")
    return names, X, y


def _warmcool(s: str) -> str:
    return "warm" if s in WARM else "cool"


def _metrics(y_true, y_pred) -> dict:
    n = len(y_true)
    acc = sum(int(a == b) for a, b in zip(y_true, y_pred)) / n
    wc = sum(int(_warmcool(a) == _warmcool(b)) for a, b in zip(y_true, y_pred)) / n
    return {"n": n, "accuracy": round(acc, 4), "warmcool_accuracy": round(wc, 4)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smtc-src", required=True)
    ap.add_argument("--train", required=True)
    ap.add_argument("--test", action="append", required=True, help="name=manifest.csv")
    ap.add_argument("--limit-per-class", type=int, default=300)
    args = ap.parse_args()

    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    analyze = smtc._load_smtc(Path(args.smtc_src).resolve())

    print("Extracting TRAIN features...")
    names, Xtr, ytr = extract("train", args.train, analyze, args.limit_per_class, partition="train")

    scaler = StandardScaler().fit(Xtr)
    clf = LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced")
    clf.fit(scaler.transform(Xtr), ytr)
    print("Train:", _metrics(ytr, clf.predict(scaler.transform(Xtr))))

    print("\n=== RECALIBRATED (LogReg on SMTC features) vs 현행 ===")
    baselines = {"deeparmo": (0.5362, 0.67), "capstonea": (0.4133, 0.6133)}
    for spec in args.test:
        name, manifest = spec.split("=", 1)
        _, Xte, yte = extract(name, manifest, analyze, 0, partition=None)
        pred = clf.predict(scaler.transform(Xte))
        m = _metrics(yte, pred)
        base = baselines.get(name)
        base_s = f" | 현행 acc={base[0]} warmcool={base[1]}" if base else ""
        print(f"  {name}: acc={m['accuracy']} warmcool={m['warmcool_accuracy']} (n={m['n']}){base_s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
