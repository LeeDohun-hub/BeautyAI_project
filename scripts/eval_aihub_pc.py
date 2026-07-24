"""AI-Hub 조명불변 Lab 회귀 모델 채점.

세 가지를 본다:
  1) ΔE — 예측 Lab vs 분광측색 실측. 단 **평균만 찍는 기준선과 반드시 비교**한다.
     동북아 피부는 분산이 작아(L±3.0, a±1.8, b±2.1) 평균 예측만으로도 ΔE≈4 가 나온다.
     기준선을 안 보면 "ΔE 2.6 = 좋다" 로 오독한다.
  2) 계절 정확도 — 예측 Lab → 규칙 → 계절이 실측 Lab → 규칙 → 계절과 맞는가.
  3) **동일인 4조명 일치도** — 같은 사람의 조명만 다른 4장이 같은 계절로 나오는가.
     라벨이 옳은지와 무관하게 '조명 문제를 풀었는가' 를 직접 재는 지표.

Usage:
  python scripts/eval_aihub_pc.py --model data/models/aihub_pc_lab.pt
"""
from __future__ import annotations

import argparse
import csv
import collections
from pathlib import Path
from statistics import median

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torchvision import models, transforms

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifests" / "aihub_pc_manifest.csv"
DEVICE = "cpu"

TF = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


def season_from_lab(ita: float, lab_b: float, slope: float, inter: float, ita_med: float) -> str:
    warm = lab_b - (slope * ita + inter) > 0
    light = ita > ita_med
    if warm:
        return "spring" if light else "autumn"
    return "summer" if light else "winter"


def ita_from_lab(L: float, b: float) -> float:
    return float(np.degrees(np.arctan2(L - 50.0, b)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="data/models/aihub_pc_lab.pt")
    args = ap.parse_args()

    ck = torch.load(ROOT / args.model, map_location="cpu", weights_only=False)
    lab_mean = np.asarray(ck["lab_mean"], dtype=np.float32)
    lab_std = np.asarray(ck["lab_std"], dtype=np.float32)
    val_uids = set(ck["val_uids"])

    net = models.efficientnet_b0(weights=None)
    dim = net.classifier[1].in_features
    net.classifier = nn.Identity()
    net.load_state_dict(ck["feat"])
    head = nn.Linear(dim, 3)
    head.load_state_dict(ck["head"])
    net.eval(); head.eval()

    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    train_rows = [r for r in rows if r["uid"] not in val_uids]
    val_rows = [r for r in rows if r["uid"] in val_uids]
    print(f"val {len(val_rows)}장 / 인물 {len({r['uid'] for r in val_rows})}명 (학습에 안 쓰인 인물)")

    # 계절 규칙 기준선은 **train 인물로만** 적합해야 한다(val 로 적합하면 그 자체가 누수).
    tr_people = {}
    for r in train_rows:
        tr_people[r["uid"]] = r
    xs = np.array([float(p["ita_avg"]) for p in tr_people.values()])
    ys = np.array([float(p["lab_b"]) for p in tr_people.values()])
    slope = float(((xs - xs.mean()) * (ys - ys.mean())).sum() / ((xs - xs.mean()) ** 2).sum())
    inter = float(ys.mean() - slope * xs.mean())
    ita_med = float(median(xs))
    print(f"계절 규칙(train 인물 {len(tr_people)}명으로 적합): b*={slope:.4f}·ITA+{inter:.2f}, ITA경계={ita_med:.2f}\n")

    preds, trues = [], []
    with torch.no_grad():
        for i in range(0, len(val_rows), 32):
            batch = val_rows[i:i + 32]
            x = torch.stack([TF(Image.open(ROOT / r["image_path"]).convert("RGB")) for r in batch])
            p = head(net(x)).numpy() * lab_std + lab_mean
            preds.append(p)
            trues.append(np.array([[float(r["lab_l"]), float(r["lab_a"]), float(r["lab_b"])] for r in batch]))
    P = np.concatenate(preds); T = np.concatenate(trues)

    de_model = np.sqrt(((P - T) ** 2).sum(1))
    # 기준선: train 평균 Lab 을 모든 val 에 그대로 찍기
    tr_lab = np.array([[float(r["lab_l"]), float(r["lab_a"]), float(r["lab_b"])] for r in train_rows])
    de_mean = np.sqrt(((tr_lab.mean(0)[None, :] - T) ** 2).sum(1))

    print("① ΔE (낮을수록 좋음)")
    print(f"   모델          : {de_model.mean():.3f}")
    print(f"   평균만 찍기   : {de_mean.mean():.3f}   ← 기준선")
    gain = (de_mean.mean() - de_model.mean()) / de_mean.mean()
    print(f"   → 기준선 대비 {gain:+.1%} 개선\n")

    # ② 계절 정확도 (예측 Lab → 규칙  vs  실측 Lab → 규칙)
    def to_season(lab):
        L, a, b = float(lab[0]), float(lab[1]), float(lab[2])
        return season_from_lab(ita_from_lab(L, b), b, slope, inter, ita_med)

    ps = [to_season(P[i]) for i in range(len(P))]
    ts = [to_season(T[i]) for i in range(len(T))]
    acc = sum(1 for i in range(len(ps)) if ps[i] == ts[i]) / len(ps)
    print("② 계절 정확도 (예측Lab→규칙 vs 실측Lab→규칙)")
    print(f"   {acc:.4f}   (4지선다 찍기 0.25)")
    print(f"   예측 분포: {dict(collections.Counter(ps))}")
    print(f"   실측 분포: {dict(collections.Counter(ts))}\n")

    # ③ 동일인 4조명 일치도 — 이 설계의 핵심 주장을 직접 검증
    by_uid = collections.defaultdict(list)
    for i, r in enumerate(val_rows):
        by_uid[r["uid"]].append(ps[i])
    full = [v for v in by_uid.values() if len(v) == 4]
    same = sum(1 for v in full if len(set(v)) == 1)
    print("③ 동일인 4조명 계절 일치도 (조명만 다른 같은 사람 → 같은 계절이어야 함)")
    print(f"   4장 전부 일치: {same}/{len(full)} = {same/len(full):.1%}")
    dist = collections.Counter(len(set(v)) for v in full)
    print(f"   서로 다른 계절 개수 분포: {dict(sorted(dist.items()))}   (1=완전일치, 4=제각각)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
