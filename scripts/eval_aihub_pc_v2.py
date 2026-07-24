"""v2(부위별 9차원 + 5000lux 제외) 채점 — v1 과 동일 잣대.

세 지표: ΔE / **조명 일치도**(같은 사람 다른 조명 → 같은 계절?) / 계절 정확도.
v1 실측(같은 val 인물 129명, 500lux): ΔE 2.655 / 일치도 85.3% / 정확도 55.0%

⚠️ 규칙은 **train 인물로만** 적합한다(val 로 적합하면 그 자체가 누수).
   v2 는 얼굴 3부위 기준 ita_face 로 통일했다(v1 은 lab_b=얼굴3부위 vs ita_avg=목포함4부위 혼용).
"""
from __future__ import annotations

import argparse
import collections
import csv
import math
from pathlib import Path
from statistics import median

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torchvision import models, transforms

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifests" / "aihub_pc_sites_manifest.csv"

TF = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


def ita_of(L: float, b: float) -> float:
    return math.degrees(math.atan2(L - 50.0, b))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="data/models/aihub_pc_lab_v2.pt")
    args = ap.parse_args()

    ck = torch.load(ROOT / args.model, map_location="cpu", weights_only=False)
    mean = np.asarray(ck["target_mean"], dtype=np.float32)
    std = np.asarray(ck["target_std"], dtype=np.float32)
    targets = ck["targets"]
    val_uids = set(ck["val_uids"])

    net = models.efficientnet_b0(weights=None)
    dim = net.classifier[1].in_features
    net.classifier = nn.Identity()
    net.load_state_dict(ck["feat"]); net.eval()
    head = nn.Linear(dim, len(targets)); head.load_state_dict(ck["head"]); head.eval()

    rows = [r for r in csv.DictReader(MANIFEST.open(encoding="utf-8")) if int(r["lux"]) == 500]
    tr = [r for r in rows if r["uid"] not in val_uids]
    va = [r for r in rows if r["uid"] in val_uids]

    # 규칙: train 인물로만 적합 (얼굴 3부위 기준으로 통일)
    tp = {}
    for r in tr:
        tp[r["uid"]] = r
    xs = np.array([float(p["ita_face"]) for p in tp.values()])
    ys = np.array([float(p["face_b"]) for p in tp.values()])
    slope = float(((xs - xs.mean()) * (ys - ys.mean())).sum() / ((xs - xs.mean()) ** 2).sum())
    inter = float(ys.mean() - slope * xs.mean())
    med = float(median(xs))
    print(f"val 인물 {len({r['uid'] for r in va})}명 (학습 미사용)")
    print(f"규칙(train {len(tp)}명 적합): face_b = {slope:.4f}·ITA + {inter:.2f}, ITA경계 {med:.2f}\n")

    def seas(L: float, b: float) -> str:
        I = ita_of(L, b)
        warm = b - (slope * I + inter) > 0
        light = I > med
        return ("spring" if light else "autumn") if warm else ("summer" if light else "winter")

    per = collections.defaultdict(dict)
    true = {}
    with torch.no_grad():
        for i in range(0, len(va), 32):
            B = va[i:i + 32]
            x = torch.stack([TF(Image.open(ROOT / r["image_path"]).convert("RGB")) for r in B])
            P = head(net(x)).numpy() * std + mean
            for r, p in zip(B, P):
                face = p.reshape(3, 3).mean(0)         # 3부위 평균 → 얼굴 Lab
                per[r["uid"]][int(r["kelvin"])] = face
                true[r["uid"]] = np.array([float(r["face_l"]), float(r["face_a"]), float(r["face_b"])])

    uids = [u for u, v in per.items() if len(v) == 2]
    same = acc = 0
    des = []
    pred_dist = collections.Counter()
    for u in uids:
        ss = []
        for K in (3200, 5600):
            f = per[u][K]
            des.append(float(np.sqrt(((f - true[u]) ** 2).sum())))
            s = seas(float(f[0]), float(f[2])); ss.append(s); pred_dist[s] += 1
        if ss[0] == ss[1]:
            same += 1
        if ss[0] == seas(float(true[u][0]), float(true[u][2])):
            acc += 1

    base = np.sqrt(((np.stack([np.array([float(r["face_l"]), float(r["face_a"]), float(r["face_b"])])
                               for r in tr]).mean(0)[None, :]
                     - np.stack([true[u] for u in uids])) ** 2).sum(1)).mean()
    n = len(uids)
    print(f"{'지표':<16} {'v2':>10} {'v1':>10}")
    print("-" * 40)
    print(f"{'ΔE':<16} {np.mean(des):>10.3f} {2.655:>10.3f}   (평균찍기 {base:.3f})")
    print(f"{'조명 일치도':<14} {same/n:>10.1%} {0.853:>10.1%}")
    print(f"{'계절 정확도':<14} {acc/n:>10.1%} {0.550:>10.1%}")
    print(f"\n예측 분포: {dict(pred_dist)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
