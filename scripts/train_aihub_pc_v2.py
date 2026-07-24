"""AI-Hub 퍼스널컬러 분류기 v2 — v1 대비 두 가지를 고쳤다.

v1(`train_aihub_pc.py`) 실측: ΔE 2.655 / 조명일치도 85.3% / 계절정확도 55.0% (val 129명).

개선 ①: **5000lux 사진 제외**.
  5000lux 는 피부가 포화(클리핑)된다 — 피부 픽셀의 4.0%(3200K) / **16.8%(5600K)** 가 255.
  255 에 붙은 픽셀은 원본 정보가 파괴된 것이라 어떤 모델로도 복원 못 한다.
  v1 은 학습 데이터의 **절반(1,292장)이 이 손상 입력**이었다. (같은 v1 모델을 4조명 전부로 채점하면
  일치도가 85.3%→50.4% 로 떨어지는데, 이 격차가 손상의 크기다.)

개선 ②: **부위별 지도신호(3배)**.
  분광측색기는 이마/좌뺨/우뺨을 따로 쟀는데 v1 은 평균 하나(3차원)만 타깃으로 썼다.
  9차원(3부위 x Lab)으로 주면 부위 간 관계까지 배운다. 목은 검은 상의에 가려 사진에 없어 제외.

  덤: v1 규칙의 불일치를 바로잡는다 — 매니페스트 `lab_*`은 얼굴 3부위 평균인데 `ita_avg`는
  **목 포함 4부위**라 규칙이 두 측정을 섞고 있었다(평균 1.32도, 최대 5.99도 차이). v2 는
  얼굴 3부위로 계산한 `ita_face` 하나로 통일한다.

Usage:
  python scripts/train_aihub_pc_v2.py --epochs 30 --batch 64
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path
from statistics import median

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifests" / "aihub_pc_sites_manifest.csv"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

SITES = ["forehead", "left", "right"]
TARGETS = [f"{s}_{c}" for s in SITES for c in "lab"]          # 9차원

TRAIN_TF = transforms.Compose([
    transforms.RandomHorizontalFlip(),
    # ⚠️ 색 증강 금지 — 참 피부색 복원이 목표라 색을 흔들면 정답 대응이 깨진다.
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])
EVAL_TF = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


class SiteDS(Dataset):
    def __init__(self, rows, tf, mean, std):
        self.rows, self.tf, self.mean, self.std = rows, tf, mean, std
        self.cache = []
        for r in rows:
            p = Path(r["image_path"])
            if not p.is_absolute():
                p = ROOT / r["image_path"]
            self.cache.append(Image.open(p).convert("RGB").resize((224, 224), Image.BILINEAR))
        self.y = np.array([[float(r[t]) for t in TARGETS] for r in rows], dtype=np.float32)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return self.tf(self.cache[i]), torch.from_numpy((self.y[i] - self.mean) / self.std)


def group_split(rows, val_frac=0.2, seed=42):
    uids = sorted({r["uid"] for r in rows})
    random.Random(seed).shuffle(uids)
    val = set(uids[: max(1, int(len(uids) * val_frac))])
    return [r for r in rows if r["uid"] not in val], [r for r in rows if r["uid"] in val], val


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--out", default="data/models/aihub_pc_lab_v2.pt")
    ap.add_argument("--lux", default="500", choices=["500", "all"],
                    help="500=클리핑 없는 저조도만(v2) / all=4조명 전부(v3). "
                         "v2 실측: 500 만 쓰면 정확도는 오르나(55.0→58.9%) **조명 일치도가 떨어진다"
                         "(85.3→79.1%)** — 5000lux 가 손상 입력이긴 해도 조명 다양성을 제공해 "
                         "불변성 학습에 기여하고 있었다. v3=all 로 둘 다 노린다.")
    args = ap.parse_args()

    if DEVICE == "cpu":
        import os
        torch.set_num_threads(os.cpu_count() or 4)

    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    if args.lux == "500":
        rows = [r for r in rows if int(r["lux"]) == 500]
    tr, va, val_uids = group_split(rows)
    lux_note = "500lux 만(5000lux 클리핑분 제외)" if args.lux == "500" else "4조명 전부(조명 다양성 확보)"
    print(f"device={DEVICE}  {lux_note}: {len(rows)}장 / 인물 {len({r['uid'] for r in rows})}명")
    print(f"  train {len(tr)}장({len({r['uid'] for r in tr})}명) / val {len(va)}장({len(val_uids)}명) — 인물 단위 분리")

    ytr = np.array([[float(r[t]) for t in TARGETS] for r in tr], dtype=np.float32)
    mean, std = ytr.mean(0), ytr.std(0) + 1e-6
    print(f"  타깃 {len(TARGETS)}차원(3부위 x Lab) — v1 은 3차원이었다")
    print("  이미지 224 사전 디코드 중...", flush=True)

    net = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.IMAGENET1K_V1)
    dim = net.classifier[1].in_features
    net.classifier = nn.Identity()
    head = nn.Linear(dim, len(TARGETS))
    model = nn.ModuleDict({"feat": net, "head": head}).to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    lossf = nn.SmoothL1Loss()

    dl_tr = DataLoader(SiteDS(tr, TRAIN_TF, mean, std), batch_size=args.batch, shuffle=True)
    dl_va = DataLoader(SiteDS(va, EVAL_TF, mean, std), batch_size=args.batch, shuffle=False)

    best = 1e9
    for ep in range(args.epochs):
        model.train()
        tot = 0.0
        for x, y in dl_tr:
            x, y = x.to(DEVICE), y.to(DEVICE)
            loss = lossf(model["head"](model["feat"](x)), y)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += float(loss.detach())
        model.eval()
        errs = []
        with torch.no_grad():
            for x, y in dl_va:
                p = model["head"](model["feat"](x.to(DEVICE))).cpu().numpy() * std + mean
                t = y.numpy() * std + mean
                # 얼굴 평균 Lab 로 환산한 ΔE (v1 과 같은 척도로 비교 가능)
                pf = p.reshape(len(p), 3, 3).mean(1)
                tf_ = t.reshape(len(t), 3, 3).mean(1)
                errs.append(np.sqrt(((pf - tf_) ** 2).sum(1)))
        de = float(np.concatenate(errs).mean())
        print(f"  epoch {ep+1}/{args.epochs} loss={tot/max(1,len(dl_tr)):.4f}  val ΔE(얼굴평균)={de:.3f}", flush=True)
        if de < best:
            best = de
            out = ROOT / args.out
            out.parent.mkdir(parents=True, exist_ok=True)
            torch.save({"feat": model["feat"].state_dict(), "head": model["head"].state_dict(),
                        "target_mean": mean, "target_std": std, "targets": TARGETS,
                        "val_uids": sorted(val_uids)}, out)
    print(f"\n최고 val ΔE={best:.3f} → {args.out}   (v1: 2.655)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
