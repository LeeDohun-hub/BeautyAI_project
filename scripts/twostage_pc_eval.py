"""2-stage personal-color prototype: Stage1 warm/cool, Stage2 depth(light/deep).

Post-hoc (no retraining): recombines the FT model's 4-way probs with color/skin
features. Tunes on validation for balanced accuracy, then reports held-out sets.
Reads cached features from scripts/dump_pc_features.py.
"""
from __future__ import annotations

import csv
import itertools
from pathlib import Path

SEASONS = ("spring", "summer", "autumn", "winter")
WARM = ("spring", "autumn")
COOL = ("summer", "winter")
EVAL_DIR = Path(__file__).resolve().parents[1] / "data" / "eval" / "_2stage"
SETS = {
    "val": "feat_val.csv",
    "holdout": "feat_holdout.csv",
    "ext40": "feat_ext40.csv",
    "capstonea": "feat_capstonea.csv",
}


def load(name: str) -> list[dict]:
    rows = []
    with (EVAL_DIR / name).open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            for k, v in r.items():
                if k not in ("image_path", "actual"):
                    r[k] = float(v)
            rows.append(r)
    return rows


def predict(r: dict, p: dict) -> str:
    a = p["a"]
    # Stage 1: tone
    m_warm = r["m_spring"] + r["m_autumn"]
    m_cool = r["m_summer"] + r["m_winter"]
    c_warm = r["c_spring"] + r["c_autumn"]
    c_cool = r["c_summer"] + r["c_winter"]
    warm_score = a * m_warm + (1 - a) * c_warm
    cool_score = a * m_cool + (1 - a) * c_cool
    tone = "warm" if warm_score >= cool_score else "cool"
    # Stage 2: depth (light vs deep). light_season is the brighter/softer of the pair.
    b = r["brightness"]
    if tone == "warm":
        light_s, deep_s, t = "spring", "autumn", p["t_warm"]
        d = p["dm"] * (r["m_spring"] - r["m_autumn"]) + p["db"] * (b - t)
    else:
        light_s, deep_s, t = "summer", "winter", p["t_cool"]
        # summer = lighter AND lower chroma (muted); winter = deeper / higher chroma (clear).
        d = (
            p["dm"] * (r["m_summer"] - r["m_winter"])
            + p["db"] * (b - t)
            + p["dc"] * (p["t_chroma"] - r["chroma"])
        )
    return light_s if d >= 0 else deep_s


def metrics(rows: list[dict], p: dict) -> dict:
    per = {s: [0, 0] for s in SEASONS}
    correct = 0
    for r in rows:
        pred = predict(r, p)
        act = r["actual"]
        per[act][1] += 1
        if pred == act:
            per[act][0] += 1
            correct += 1
    recalls = {s: (per[s][0] / per[s][1] if per[s][1] else None) for s in SEASONS}
    valid = [v for v in recalls.values() if v is not None]
    return {
        "acc": correct / len(rows) if rows else 0.0,
        "bal": sum(valid) / len(valid) if valid else 0.0,
        "recall": recalls,
    }


def model_only(rows: list[dict]) -> dict:
    per = {s: [0, 0] for s in SEASONS}
    correct = 0
    for r in rows:
        pred = max(SEASONS, key=lambda s: r[f"m_{s}"])
        per[r["actual"]][1] += 1
        if pred == r["actual"]:
            per[r["actual"]][0] += 1
            correct += 1
    recalls = {s: (per[s][0] / per[s][1] if per[s][1] else None) for s in SEASONS}
    valid = [v for v in recalls.values() if v is not None]
    return {"acc": correct / len(rows), "bal": sum(valid) / len(valid), "recall": recalls}


def fmt(m: dict) -> str:
    rc = " ".join(f"{s[:2]}={m['recall'][s]:.2f}" if m['recall'][s] is not None else f"{s[:2]}=--" for s in SEASONS)
    return f"acc={m['acc']:.3f} bal={m['bal']:.3f} | {rc}"


def main() -> None:
    data = {k: load(v) for k, v in SETS.items()}

    # sanity: model-only reconstruction
    print("=== model-only (reconstructed from features; sanity vs earlier eval) ===")
    for k, rows in data.items():
        print(f"  {k:>9} (n={len(rows):>3}): {fmt(model_only(rows))}")

    # grid search on val for best balanced accuracy
    grid = {
        "a": [0.0, 0.3, 0.5, 0.7, 1.0],
        "dm": [0.0, 0.5, 1.0],
        "db": [0.0, 2.0, 4.0, 6.0],
        "dc": [0.0, 2.0],
        "t_warm": [0.45, 0.5, 0.55, 0.6],
        "t_cool": [0.45, 0.5, 0.55, 0.6],
        "t_chroma": [0.15, 0.22],
    }
    keys = list(grid)
    best = None
    for combo in itertools.product(*[grid[k] for k in keys]):
        p = dict(zip(keys, combo))
        m = metrics(data["val"], p)
        score = (round(m["bal"], 4), round(m["acc"], 4))
        if best is None or score > best[0]:
            best = (score, p, m)
    _, bp, bm = best
    print("\n=== best config by val balanced-acc ===")
    print("  params:", {k: bp[k] for k in keys})
    print(f"  val: {fmt(bm)}")

    print("\n=== 2-STAGE (tuned) vs MODEL-ONLY across sets ===")
    print(f"{'set':>9} | {'2-stage tuned':<44} | model-only")
    for k, rows in data.items():
        print(f"{k:>9} | {fmt(metrics(rows, bp)):<44} | {fmt(model_only(rows))}")

    # named fixed variants for interpretability
    print("\n=== fixed variants (val -> holdout -> ext40 -> capstonea) ===")
    variants = {
        "model-tone+model-depth (a=1)": {"a": 1.0, "dm": 1.0, "db": 0.0, "dc": 0.0, "t_warm": 0.5, "t_cool": 0.5, "t_chroma": 0.2},
        "color-tone+bright-depth (a=0)": {"a": 0.0, "dm": 0.0, "db": 4.0, "dc": 2.0, "t_warm": 0.55, "t_cool": 0.55, "t_chroma": 0.2},
        "blend-tone+bright-depth (a=.5)": {"a": 0.5, "dm": 0.5, "db": 4.0, "dc": 2.0, "t_warm": 0.55, "t_cool": 0.55, "t_chroma": 0.2},
    }
    for name, p in variants.items():
        cells = " | ".join(f"{k}:{metrics(data[k], p)['acc']:.3f}/{metrics(data[k], p)['bal']:.3f}" for k in SETS)
        print(f"  {name:<32} {cells}")


if __name__ == "__main__":
    main()
