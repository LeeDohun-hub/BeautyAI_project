"""실험: 피부 LAB 특징으로 웜/쿨(및 4계절)을 분류해 CNN과 같은 홀드아웃(test 912장)에서 비교.

가설: 우리 CNN의 최대 약점은 웜/쿨(tone, 67%)이다. LAB b채널(노랑↔파랑)은 웜/쿨을
직접 재는 값이라, 경량 분류기(로지스틱/RF)로도 CNN보다 웜/쿨을 잘 잡을 수 있다.
(참고: kimju-hee/ml-personal-color 가 LAB-B + RandomForest로 ~76% 보고)

- 특징 추출은 production 분석기(PersonalColorAnalyzer)의 얼굴크롭+WB+피부픽셀을 그대로 재사용
  → 추론 파이프라인과 동일 도메인.
- 느린 특징 추출은 CSV로 캐시(재실행 즉시).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import cv2  # noqa: E402
from app.services.personal_color_analyzer import PersonalColorAnalyzer  # noqa: E402

SEASONS = ("spring", "summer", "autumn", "winter")
SEASON_TONE = {"spring": "warm", "autumn": "warm", "summer": "cool", "winter": "cool"}
FEATURE_COLS = ["L", "a", "b", "brightness", "chroma", "warmth", "redness"]


def extract_features(analyzer: PersonalColorAnalyzer, path: Path):
    with open(path, "rb") as f:
        rgb = analyzer._load_rgb(f.read())
    model_rgb, face_detected = analyzer._face_crop(rgb)
    balanced, _wb = analyzer._white_balance(model_rgb)
    skin = analyzer._skin_pixels(balanced)
    if skin.size == 0:
        skin = analyzer._center_pixels(balanced)
    skin_u8 = np.clip(skin, 0, 255).astype(np.uint8).reshape(-1, 1, 3)
    lab = cv2.cvtColor(skin_u8, cv2.COLOR_RGB2LAB).reshape(-1, 3).mean(axis=0)
    mean_rgb = skin.mean(axis=0)
    brightness = float(np.mean(mean_rgb) / 255)
    chroma = float((np.max(mean_rgb) - np.min(mean_rgb)) / 255)
    warmth = float(((mean_rgb[0] - mean_rgb[2]) + 0.42 * (mean_rgb[1] - mean_rgb[2])) / 255)
    redness = float((mean_rgb[0] - mean_rgb[1]) / 255)
    feats = [float(lab[0]), float(lab[1]), float(lab[2]), brightness, chroma, warmth, redness]
    return feats, int(face_detected)


def build_or_load_features(manifest: Path, cache: Path) -> list[dict]:
    if cache.exists():
        with open(cache, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        print(f"[cache] loaded {len(rows)} feature rows from {cache}")
        return rows

    analyzer = PersonalColorAnalyzer()
    with open(manifest, newline="", encoding="utf-8") as f:
        src = list(csv.DictReader(f))
    out: list[dict] = []
    for i, r in enumerate(src):
        season = (r.get("season") or r.get("label") or "").strip()
        if season not in SEASONS:
            continue
        p = (ROOT / r["image_path"]).resolve()
        if not p.exists():
            continue
        try:
            feats, face = extract_features(analyzer, p)
        except Exception:
            continue
        row = {"season": season, "partition": (r.get("partition") or "").strip(), "face": face}
        row.update({c: feats[j] for j, c in enumerate(FEATURE_COLS)})
        out.append(row)
        if (i + 1) % 500 == 0:
            print(f"[extract] {i + 1}/{len(src)} processed, kept {len(out)}", flush=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with open(cache, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["season", "partition", "face", *FEATURE_COLS])
        w.writeheader()
        w.writerows(out)
    print(f"[cache] wrote {len(out)} feature rows -> {cache}")
    return out


def to_xy(rows: list[dict]):
    X = np.array([[float(r[c]) for c in FEATURE_COLS] for r in rows], dtype=np.float64)
    season = np.array([r["season"] for r in rows])
    tone = np.array([SEASON_TONE[s] for s in season])
    return X, season, tone


def cnn_baseline(report_path: Path):
    """기존 CNN 리포트에서 4계절/웜쿨 정확도 계산."""
    if not report_path.exists():
        return None
    rep = json.loads(report_path.read_text(encoding="utf-8"))
    cm = rep["confusion_matrix"]
    total = rep["total"]
    season_acc = rep["accuracy"]
    warm_cool_correct = 0
    for actual, preds in cm.items():
        at = SEASON_TONE[actual]
        for pred, n in preds.items():
            if SEASON_TONE[pred] == at:
                warm_cool_correct += n
    return {"season_acc": season_acc, "warm_cool_acc": warm_cool_correct / total, "total": total}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/manifests/personal_color_manifest.csv")
    ap.add_argument("--cache", default="data/eval/lab_features.csv")
    ap.add_argument("--cnn-report", default="data/eval/reports_deeparmo_test/personal_color_eval_report.json")
    args = ap.parse_args()

    rows = build_or_load_features(ROOT / args.manifest, ROOT / args.cache)
    train = [r for r in rows if r["partition"] == "train"]
    test = [r for r in rows if r["partition"] == "test"]
    print(f"train={len(train)} test={len(test)}")
    if not train or not test:
        print("ERROR: need both train and test rows"); return

    Xtr, s_tr, t_tr = to_xy(train)
    Xte, s_te, t_te = to_xy(test)

    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    print("\n================ RESULTS (test holdout) ================")
    base = cnn_baseline(ROOT / args.cnn_report)
    if base:
        print(f"CNN (EfficientNet)     : 4-season={base['season_acc']:.4f}  warm/cool={base['warm_cool_acc']:.4f}")

    # --- 웜/쿨 (2-class) ---
    for name, clf in [
        ("LAB LogisticReg", make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, class_weight="balanced"))),
        ("LAB RandomForest", RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=0)),
    ]:
        clf.fit(Xtr, t_tr)
        acc = (clf.predict(Xte) == t_te).mean()
        print(f"{name:22s} : warm/cool={acc:.4f}")

    # --- 4계절 (참고) ---
    for name, clf in [
        ("LAB RandomForest", RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=0)),
    ]:
        clf.fit(Xtr, s_tr)
        pred = clf.predict(Xte)
        acc = (pred == s_te).mean()
        wc = np.mean([SEASON_TONE[p] == SEASON_TONE[a] for p, a in zip(pred, s_te)])
        print(f"{name:22s} : 4-season={acc:.4f}  (derived warm/cool={wc:.4f})")

    # 단일 특징(LAB b) 임계값만으로 웜/쿨 — 얼마나 단순한 신호인지 확인
    b_tr = Xtr[:, 2]; b_te = Xte[:, 2]
    best_thr, best_acc = 0.0, 0.0
    for thr in np.linspace(b_tr.min(), b_tr.max(), 200):
        # LAB b: 높을수록 노랑(웜)
        acc = np.mean(np.where(b_te >= thr, "warm", "cool") == t_te)
        if acc > best_acc:
            best_acc, best_thr = acc, thr
    print(f"{'LAB b-only threshold':22s} : warm/cool={best_acc:.4f}  (thr={best_thr:.1f})")
    print("=======================================================")


if __name__ == "__main__":
    main()
