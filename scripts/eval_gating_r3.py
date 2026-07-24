"""'앙상블로 ΔE 는 내려가는데 계절정확도는 안 오른다'의 원인을 정량화한다.

가설: 병목은 Lab 예측이 아니라 **4지선다 이산화**다. 참 Lab 이 이미 경계에 붙어 있는 인물은
모델을 아무리 개선해도 동전 던지기다. 두 가지를 잰다.

  1) 환원 불가 구간 — **참** Lab 기준으로 경계까지의 여유가 우리 예측 오차보다 작은 비율.
     이 구간은 모델 성능과 무관하게 맞고 틀리는 게 운이다.
  2) 신뢰도 게이팅 곡선 — **예측** 여유가 큰 것부터 답할 때의 커버리지 대 정확도.
     서비스에서 '애매하면 2개 병기'를 얼마나 써야 하는지가 여기서 나온다.

Usage:
  python scripts/eval_gating_r3.py --models a.pt,b.pt,c.pt
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np
from PIL import Image

from eval_ensemble_r3 import ROOT, TARGETS, load_member, predict, season_of

# 추론 코드(backend/app/ai/aihub_pc_model.py)가 쓰는 축별 산포 — 두 축을 같은 자로 재려면 필요하다.
UNDERTONE_SD = 1.56
ITA_SD = 9.2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--manifest", default="data/manifests/aihub_pc_multi_manifest.csv")
    ap.add_argument("--val-uids", default="data/val_uids.txt")
    args = ap.parse_args()

    members = [load_member(ROOT / p.strip()) for p in args.models.split(",") if p.strip()]
    rd = members[0][4]["rule"]
    slope, inter, bound = rd["slope"], rd["intercept"], rd["ita_boundary"]

    val_uids = {ln.strip() for ln in (ROOT / args.val_uids).read_text(encoding="utf-8").splitlines() if ln.strip()}
    rows = [r for r in csv.DictReader((ROOT / args.manifest).open(encoding="utf-8")) if r["uid"] in val_uids]
    imgs = [Image.open(ROOT / r["image_path"]).convert("RGB") for r in rows]
    pred = predict(members, imgs, tta=True)

    tface = np.array([[float(r[t]) for t in TARGETS] for r in rows], np.float32).reshape(len(rows), 3, 3).mean(1)
    b_err = float(np.abs(pred[:, 2] - tface[:, 2]).mean())

    def margins(face):
        L, b = face[:, 0], face[:, 2]
        ita = np.degrees(np.arctan2(L - 50.0, b))
        return b - (slope * ita + inter), ita - bound

    tu, td = margins(tface)
    pu, pd = margins(pred)
    true_s = [season_of(float(r["face_l"]), float(r["face_b"]), slope, inter, bound) for r in rows]
    pred_s = [season_of(L, b, slope, inter, bound) for L, _a, b in pred]
    ok = np.array([pred_s[i] == true_s[i] for i in range(len(rows))])

    print(f"val {len(rows)}장 / 인물 {len({r['uid'] for r in rows})}명")
    print(f"b* 평균절대오차 = {b_err:.2f}   (웜/쿨 판정은 이 축 하나로 갈린다)\n")

    print("── 1) 환원 불가 구간: 참 Lab 이 이미 경계에 붙어 있는 비율 ──")
    for thr in (0.5, 1.0, 1.5, 2.0):
        share = float(np.mean(np.abs(tu) < thr))
        acc_in = float(ok[np.abs(tu) < thr].mean()) if (np.abs(tu) < thr).any() else float("nan")
        print(f"  참 웜쿨 여유 < {thr:>3.1f} : {share:>5.1%} 의 사진   이 구간 정확도 {acc_in:>5.1%}")
    far = np.abs(tu) >= 2.0
    print(f"  참 웜쿨 여유 ≥ 2.0 : {float(far.mean()):>5.1%} 의 사진   이 구간 정확도 {float(ok[far].mean()):>5.1%}")

    print("\n── 2) 신뢰도 게이팅: 예측 여유가 큰 것부터 답할 때 ──")
    conf = np.minimum(np.abs(pu) / UNDERTONE_SD, np.abs(pd) / ITA_SD)
    order = np.argsort(-conf)
    print(f"  {'커버리지':<10}{'답한 장수':>9}{'정확도':>9}{'임계 여유(b*)':>14}")
    for cov in (1.0, 0.8, 0.6, 0.4, 0.2):
        k = max(1, int(len(rows) * cov))
        idx = order[:k]
        print(f"  {cov:>7.0%}   {k:>9}{float(ok[idx].mean()):>9.1%}{conf[order[k - 1]] * UNDERTONE_SD:>14.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
