"""WB(공막 기반 화이트밸런스) 게이팅 검증 — 실측 Lab ground-truth 대조.

AI-Hub 데이터는 한 사람을 4조명(저/고조도 × 3200K/5600K)에서 찍는다. 분광측색 실측 Lab 은
사람마다 '하나의 참값'이다. 좋은 WB 라면:
  (1) 4조명에서 나온 픽셀 추정 Lab_b 가 서로 수렴(person-내 분산↓)해야 하고
  (2) 실측 Lab_b 에 더 가까워야(오차↓) 하며
  (3) 색온도(32K vs 56K) 로 인한 추정 편차를 줄여야 한다.
white_balanced 플래그 on/off 로 나눠 이 세 가지를 측정한다.

Usage:
  backend/.venv/Scripts/python.exe scripts/verify_wb_gating.py \
      --manifest data/manifests/aihub_skincolor_full_manifest.csv \
      --images "data/01.글로벌 다인종 피부색 데이터/extracted/동북아시아" \
      --out data/eval/wb_gating_verify.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import os
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")


def light_cond(name: str) -> str:
    stem = Path(name).stem.upper()
    lux = "hi" if "5KL" in stem else ("lo" if "5L" in stem else "?")
    temp = "56K" if "56K" in stem else ("32K" if "32K" in stem else "?")
    return f"{lux}_{temp}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/manifests/aihub_skincolor_full_manifest.csv")
    ap.add_argument("--images", default="data/01.글로벌 다인종 피부색 데이터/extracted/동북아시아")
    ap.add_argument("--out", default="data/eval/wb_gating_verify.csv")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from app.services.personal_color_analyzer import PersonalColorAnalyzer

    import time
    t0 = time.time()
    img_dir = (ROOT / args.images).resolve()
    have = {p.name: p for p in img_dir.glob("*.jpg")}
    print(f"extracted images: {len(have)}", flush=True)

    # manifest: image_name -> measured
    meas = {}
    for r in csv.DictReader((ROOT / args.manifest).open(encoding="utf-8-sig")):
        if r["region"] != "동북아시아":
            continue
        nm = r["image_name"]
        if nm in have:
            meas[nm] = r
    names = sorted(meas)
    if args.limit:
        names = names[: args.limit]
    print(f"NEA images to analyze: {len(names)}", flush=True)

    print("loading analyzer (torch + mediapipe)...", flush=True)
    analyzer = PersonalColorAnalyzer()
    print(f"analyzer ready in {time.time()-t0:.1f}s, starting...", flush=True)
    rows = []
    for i, nm in enumerate(names, 1):
        r = meas[nm]
        try:
            reading = analyzer._read_one(have[nm].read_bytes(), 1.0)
        except Exception as exc:  # noqa: BLE001
            rows.append({"image_name": nm, "uid": r["uid"], "error": repr(exc)[:50]})
            continue
        cv = reading.get("color_vector") or {}
        rows.append({
            "image_name": nm, "uid": r["uid"], "cond": light_cond(nm),
            "gt_lab_a": float(r["lab_a"]), "gt_lab_b": float(r["lab_b"]),
            "gt_ita": float(r["ita_avg"]), "gt_undertone": r["undertone"],
            "est_lab_a": round(float(cv.get("lab_a", 0.0)), 3),
            "est_lab_b": round(float(cv.get("lab_b", 0.0)), 3),
            "warmth": round(float(reading.get("warmth", 0.0)), 4),
            "white_balanced": int(bool(reading.get("white_balanced"))),
            "face_detected": int(float(reading.get("face_detected", 0.0)) >= 1.0),
            "error": "",
        })
        if i % 50 == 0:
            el = time.time() - t0
            rate = i / max(1e-6, el)
            eta = (len(names) - i) / max(1e-6, rate)
            print(f"  ...{i}/{len(names)}  {rate:.1f} img/s  elapsed {el:.0f}s  ETA {eta:.0f}s", flush=True)

    out = (ROOT / args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["image_name", "uid", "cond", "gt_lab_a", "gt_lab_b", "gt_ita", "gt_undertone",
              "est_lab_a", "est_lab_b", "warmth", "white_balanced", "face_detected", "error"]
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})

    ok = [r for r in rows if not r.get("error") and r.get("face_detected")]
    print(f"\nanalyzed ok (face detected): {len(ok)}/{len(rows)}")
    if not ok:
        return 0

    def pearson(x, y):
        x, y = np.array(x, float), np.array(y, float)
        if len(x) < 3 or x.std() == 0 or y.std() == 0:
            return float("nan")
        return float(np.corrcoef(x, y)[0, 1])

    # (2) 추정 vs 실측 lab_b 오차, WB on/off
    for wb in (1, 0):
        sub = [r for r in ok if r["white_balanced"] == wb]
        if not sub:
            continue
        err = np.mean([abs(r["est_lab_b"] - r["gt_lab_b"]) for r in sub])
        r_b = pearson([r["est_lab_b"] for r in sub], [r["gt_lab_b"] for r in sub])
        print(f"  WB={wb}: n={len(sub):4d}  |est_b - gt_b| MAE={err:5.2f}  r(est_b,gt_b)={r_b:.3f}")

    # (3) 색온도별 추정 lab_b 편차 (WB가 32K↔56K 격차를 줄이나)
    print("\n== 색온도별 est_lab_b 평균 (WB on/off) ==")
    for wb in (1, 0):
        by = defaultdict(list)
        for r in ok:
            if r["white_balanced"] == wb and r["cond"] != "?_?":
                by[r["cond"]].append(r["est_lab_b"])
        if not by:
            continue
        parts = "  ".join(f"{k}:{np.mean(v):5.1f}(n{len(v)})" for k, v in sorted(by.items()))
        print(f"  WB={wb}: {parts}")

    # (1) person-내 est_lab_b 분산 (수렴도), WB on/off
    print("\n== person-내 est_lab_b 표준편차 (낮을수록 조명에 강건) ==")
    for wb in (1, 0):
        byuid = defaultdict(list)
        for r in ok:
            if r["white_balanced"] == wb:
                byuid[r["uid"]].append(r["est_lab_b"])
        spreads = [np.std(v) for v in byuid.values() if len(v) >= 2]
        if spreads:
            print(f"  WB={wb}: persons={len(spreads):4d}  mean within-person std(est_b)={np.mean(spreads):.2f}")

    # 언더톤 콜 일치 (뉴트럴 제외, warm/cool만): 분석기 warmth 부호 vs 실측 undertone
    graded = [r for r in ok if r["gt_undertone"] in ("warm", "cool")]
    if graded:
        thr = 0.035  # analyzer 기준
        acc = np.mean([((r["warmth"] >= thr) == (r["gt_undertone"] == "warm")) for r in graded])
        print(f"\n== 언더톤 콜 (warm/cool, 뉴트럴 제외) ==  n={len(graded)}  acc={acc:.3f}")
    print(f"\nwrote -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
