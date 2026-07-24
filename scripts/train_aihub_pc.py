"""AI-Hub 다인종 데이터로 퍼스널컬러 분류기 학습 — 조명 불변 Lab 회귀 방식.

왜 사진 → 계절 직행이 아니라 2단인가:
  이 데이터는 같은 인물을 2x2 조명({500,5000}lux x {3200,5600}K)으로 4장 찍었다.
  동일인 4장은 육안으로 서로 다른 계절처럼 보인다(조명이 피부색을 지배). 그래서
  사진 픽셀에서 계절을 바로 배우면 조명을 배운다. 대신:
    1) 사진 → **분광측색기 참 Lab** 회귀. 정답이 기계 실측이라 조명과 무관하고,
       같은 인물의 4조명이 **같은 정답**을 가지므로 조명 불변성이 손실로 강제된다.
    2) 참 Lab → 계절 규칙(build_aihub_pc_dataset.season_from_lab 과 동일 규칙).

  덤: 라벨 없이도 검증이 된다 — 동일인 4조명이 같은 계절로 나오면 조명 불변성 달성.

인물 단위 분리(GroupSplit) 필수: 같은 uid 의 4장이 train/val 로 갈리면 누수다.

Usage:
  python scripts/train_aihub_pc.py --epochs 30 --batch 32
"""
from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifests" / "aihub_pc_manifest.csv"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Lab 정규화용(동북아 실측 범위 기준). 회귀 타깃 스케일을 맞춰 학습을 안정화한다.
LAB_MEAN = np.array([60.7, 10.4, 15.3], dtype=np.float32)
LAB_STD = np.array([3.0, 1.8, 2.1], dtype=np.float32)

# 이미지는 LabDS 가 224 로 미리 디코드해 캐시하므로 여기서 Resize 하지 않는다.
TRAIN_TF = transforms.Compose([
    transforms.RandomHorizontalFlip(),
    # ⚠️ 색 관련 증강(ColorJitter 등) 금지 — 학습 목표가 '조명을 뚫고 참 피부색을 복원'하는 것이라
    # 색을 흔들면 정답과의 대응이 깨진다. 데이터 자체가 이미 4가지 조명을 제공한다.
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])
EVAL_TF = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


class LabDS(Dataset):
    """이미지를 메모리에 224로 미리 디코드해 올려둔다.

    CPU 실측(2026-07-17): 512px JPEG 을 에폭마다 디코드하니 병렬도가 1.2x 로 주저앉아
    (8코어 중 1개꼴) 1에폭 30분대. 학습은 224 로 리사이즈해 쓰므로 512 디코드는 매 에폭
    버려지는 일이다. 2,584장 × 224×224×3 ≈ 390MB 라 통째로 상주 가능.
    """

    def __init__(self, rows, tf):
        self.rows, self.tf = rows, tf
        self.cache: list[Image.Image] = []
        for r in rows:
            p = Path(r["image_path"])
            if not p.is_absolute():
                p = ROOT / r["image_path"]
            im = Image.open(p).convert("RGB").resize((224, 224), Image.BILINEAR)
            self.cache.append(im)
        self.labs = np.array(
            [[float(r["lab_l"]), float(r["lab_a"]), float(r["lab_b"])] for r in rows],
            dtype=np.float32,
        )

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        img = self.tf(self.cache[i])
        y = (self.labs[i] - LAB_MEAN) / LAB_STD
        return img, torch.from_numpy(y)


def backbone():
    net = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.IMAGENET1K_V1)
    dim = net.classifier[1].in_features
    net.classifier = nn.Identity()
    return net, dim


def group_split(rows, val_frac=0.2, seed=42):
    """인물(uid) 단위 분리. 같은 사람의 4조명이 train/val 로 갈리면 누수."""
    uids = sorted({r["uid"] for r in rows})
    random.Random(seed).shuffle(uids)
    n_val = max(1, int(len(uids) * val_frac))
    val_uids = set(uids[:n_val])
    tr = [r for r in rows if r["uid"] not in val_uids]
    va = [r for r in rows if r["uid"] in val_uids]
    return tr, va, val_uids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--out", default="data/models/aihub_pc_lab.pt")
    args = ap.parse_args()

    if DEVICE == "cpu":
        import os
        torch.set_num_threads(os.cpu_count() or 4)   # 기본값이 1코어만 쓰는 경우가 있다

    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    tr, va, val_uids = group_split(rows)
    print(f"device={DEVICE}  전체 {len(rows)}장 / 인물 {len({r['uid'] for r in rows})}명  threads={torch.get_num_threads()}")
    print(f"  train {len(tr)}장({len({r['uid'] for r in tr})}명) / val {len(va)}장({len(val_uids)}명) — 인물 단위 분리")
    print("  이미지 224 사전 디코드 중...", flush=True)

    feat, dim = backbone()
    head = nn.Linear(dim, 3)          # L*, a*, b* 회귀
    net = nn.ModuleDict({"feat": feat, "head": head}).to(DEVICE)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-4)
    lossf = nn.SmoothL1Loss()

    dl_tr = DataLoader(LabDS(tr, TRAIN_TF), batch_size=args.batch, shuffle=True, num_workers=0)
    dl_va = DataLoader(LabDS(va, EVAL_TF), batch_size=args.batch, shuffle=False, num_workers=0)

    best = 1e9
    for ep in range(args.epochs):
        net.train()
        tot = 0.0
        for x, y in dl_tr:
            x, y = x.to(DEVICE), y.to(DEVICE)
            loss = lossf(net["head"](net["feat"](x)), y)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += float(loss)
        net.eval()
        errs = []
        with torch.no_grad():
            for x, y in dl_va:
                p = net["head"](net["feat"](x.to(DEVICE))).cpu().numpy() * LAB_STD + LAB_MEAN
                t = y.numpy() * LAB_STD + LAB_MEAN
                errs.append(np.sqrt(((p - t) ** 2).sum(axis=1)))   # ΔE (CIE76)
        de = float(np.concatenate(errs).mean())
        print(f"  epoch {ep+1}/{args.epochs} loss={tot/max(1,len(dl_tr)):.4f}  val ΔE={de:.2f}", flush=True)
        if de < best:
            best = de
            out = ROOT / args.out
            out.parent.mkdir(parents=True, exist_ok=True)
            torch.save({"feat": net["feat"].state_dict(), "head": net["head"].state_dict(),
                        "lab_mean": LAB_MEAN, "lab_std": LAB_STD,
                        "val_uids": sorted(val_uids)}, out)
    print(f"\n최고 val ΔE={best:.2f} → {args.out}")
    print("  참고: ΔE<2.3 이면 사람 눈이 구분 못하는 수준, <5 면 실용적.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
