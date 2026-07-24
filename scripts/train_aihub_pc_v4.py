"""AI-Hub 퍼스널컬러 v4 — 정확도를 직접 가르는 축에 학습 용량을 집중한다.

배경(실측 진단, scripts/exp_* 로 확인):
  계절 규칙은 **L 과 b 만** 쓴다(a 는 안 본다). 그런데 v2/v3 학습 타깃은 9차원(3부위 x Lab)이라
  **1/3 이 a** 다. val 에서 a 오차를 통째로 0 으로 만들어도 계절 정확도는 55.4% → 55.4% 로
  **1도 안 움직인다**. 반대로 L·b 오차를 절반으로 줄이면 55.4% → **81.0%**, 1/4 이면 93.0%.
  즉 남은 개선은 전부 "L·b 오차 줄이기"에 있고, a 학습은 순수 낭비에 가깝다.

그래서 두 레버를 옵션으로 준다:
  --a-weight  a 채널 손실 가중치(기본 0.2). 0 이면 완전 제외.
              ⚠️ a 가 보조과제로 표현학습을 돕고 있을 수 있어 0 보다 0.2 부터 A/B 를 권장한다.
  --target    lab      : 기존 9차원(3부위 x Lab) 회귀 + a 가중치 적용
              decision : **ITA·언더톤잔차 2차원을 직접 회귀**. 규칙이 쓰는 값 그 자체라
                         모델 용량 100% 가 정답을 가르는 축에 쓰인다(가장 근본적인 형태).

v2 대비 또 하나 고친 것: **모델 선택 기준을 ΔE 가 아니라 계절 정확도로 바꿨다.**
  v2/v3 는 val ΔE 가 최소인 에폭을 저장했는데, ΔE 는 a 오차까지 포함하는 지표라
  목표(계절 정확도)와 어긋난다.

비교 기준(같은 인물 분리 split, seed 42):
  v1 55.0% / v2(500lux) 58.9% / v3+TTA 앙상블 57.6%

Usage:
  python scripts/train_aihub_pc_v4.py --target lab --a-weight 0.2 --epochs 30
  python scripts/train_aihub_pc_v4.py --target decision --epochs 30
  python scripts/train_aihub_pc_v4.py --target lab --a-weight 0.2 --limit 200 --epochs 1   # 스모크
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
LAB_TARGETS = [f"{s}_{c}" for s in SITES for c in "lab"]      # 9차원
DECISION_TARGETS = ["ita", "undertone_residual"]               # 2차원

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


def ita_of(L: float, b: float) -> float:
    return math.degrees(math.atan2(L - 50.0, b))


class FrameDS(Dataset):
    def __init__(self, rows, targets, tf, mean, std):
        self.rows, self.tf, self.mean, self.std = rows, tf, mean, std
        self.cache = []
        for r in rows:
            p = Path(r["image_path"])
            if not p.is_absolute():
                p = ROOT / r["image_path"]
            self.cache.append(Image.open(p).convert("RGB").resize((224, 224), Image.BILINEAR))
        self.y = np.asarray(targets, dtype=np.float32)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return self.tf(self.cache[i]), torch.from_numpy((self.y[i] - self.mean) / self.std)


def group_split(rows, val_frac=0.2, seed=42):
    uids = sorted({r["uid"] for r in rows})
    random.Random(seed).shuffle(uids)
    val = set(uids[: max(1, int(len(uids) * val_frac))])
    return [r for r in rows if r["uid"] not in val], [r for r in rows if r["uid"] in val], val


def fit_rule(train_rows):
    """계절 규칙을 **train 인물로만** 적합(val 로 적합하면 누수)."""
    people = {r["uid"]: r for r in train_rows}
    xs = np.array([float(p["ita_face"]) for p in people.values()])
    ys = np.array([float(p["face_b"]) for p in people.values()])
    slope = float(((xs - xs.mean()) * (ys - ys.mean())).sum() / ((xs - xs.mean()) ** 2).sum())
    inter = float(ys.mean() - slope * xs.mean())
    return slope, inter, float(median(xs))


def season_of(ita: float, residual: float, ita_boundary: float) -> str:
    warm = residual > 0
    light = ita > ita_boundary
    return ("spring" if light else "autumn") if warm else ("summer" if light else "winter")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["lab", "decision"], default="lab")
    ap.add_argument("--a-weight", type=float, default=0.2,
                    help="a 채널 손실 가중치(target=lab 일 때만). 0=완전 제외, 1=기존 v2/v3 동작")
    ap.add_argument("--lux", default="all", choices=["500", "all"])
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--limit", type=int, default=0, help="스모크 테스트용 상위 N 프레임만")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if DEVICE == "cpu":
        import os
        torch.set_num_threads(os.cpu_count() or 4)

    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    if args.lux == "500":
        rows = [r for r in rows if int(r["lux"]) == 500]
    if args.limit:
        rows = rows[: args.limit]
    tr, va, val_uids = group_split(rows)
    slope, inter, ita_boundary = fit_rule(tr)

    out = args.out or f"data/models/aihub_pc_v4_{args.target}" + (
        f"_a{args.a_weight:g}" if args.target == "lab" else "") + ".pt"

    print(f"device={DEVICE}  lux={args.lux}  target={args.target}"
          + (f"  a_weight={args.a_weight:g}" if args.target == "lab" else ""))
    print(f"  {len(rows)}장 / 인물 {len({r['uid'] for r in rows})}명  "
          f"→ train {len(tr)}장({len({r['uid'] for r in tr})}명) / val {len(va)}장({len(val_uids)}명)")
    print(f"  규칙(train 적합): face_b = {slope:.4f}·ITA + {inter:.2f},  ITA 경계 {ita_boundary:.2f}")

    def targets_of(rs):
        if args.target == "lab":
            return [[float(r[t]) for t in LAB_TARGETS] for r in rs]
        out_ = []
        for r in rs:
            L, b = float(r["face_l"]), float(r["face_b"])
            I = ita_of(L, b)
            out_.append([I, b - (slope * I + inter)])
        return out_

    ytr = np.asarray(targets_of(tr), dtype=np.float32)
    mean, std = ytr.mean(0), ytr.std(0) + 1e-6
    names = LAB_TARGETS if args.target == "lab" else DECISION_TARGETS
    print(f"  타깃 {len(names)}차원: {names}")

    # 손실 가중치 — target=lab 이면 a 차원만 낮춘다(정확도에 기여하지 않는 축).
    if args.target == "lab":
        w = np.array([args.a_weight if t.endswith("_a") else 1.0 for t in LAB_TARGETS], np.float32)
    else:
        w = np.ones(len(names), np.float32)
    weights = torch.from_numpy(w).to(DEVICE)
    print(f"  손실 가중치: {dict(zip(names, w.round(2)))}")
    print("  이미지 224 사전 디코드 중...", flush=True)

    net = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.IMAGENET1K_V1)
    dim = net.classifier[1].in_features
    net.classifier = nn.Identity()
    head = nn.Linear(dim, len(names))
    model = nn.ModuleDict({"feat": net, "head": head}).to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    lossf = nn.SmoothL1Loss(reduction="none")

    dl_tr = DataLoader(FrameDS(tr, targets_of(tr), TRAIN_TF, mean, std), batch_size=args.batch, shuffle=True)
    dl_va = DataLoader(FrameDS(va, targets_of(va), EVAL_TF, mean, std), batch_size=args.batch, shuffle=False)

    # val 정답 계절 — 참 Lab 을 규칙에 넣은 값(전 평가와 동일 잣대)
    va_true_season, va_uid = [], [r["uid"] for r in va]
    for r in va:
        L, b = float(r["face_l"]), float(r["face_b"])
        I = ita_of(L, b)
        va_true_season.append(season_of(I, b - (slope * I + inter), ita_boundary))

    best_acc = -1.0
    for ep in range(args.epochs):
        model.train()
        tot = 0.0
        for x, y in dl_tr:
            x, y = x.to(DEVICE), y.to(DEVICE)
            loss = (lossf(model["head"](model["feat"](x)), y) * weights).mean()
            opt.zero_grad(); loss.backward(); opt.step()
            tot += float(loss.detach())

        model.eval()
        preds = []
        with torch.no_grad():
            for x, _ in dl_va:
                preds.append(model["head"](model["feat"](x.to(DEVICE))).cpu().numpy() * std + mean)
        P = np.concatenate(preds)

        # 예측 → 계절 (+ lab 모드는 ΔE 도)
        de = float("nan")
        seasons = []
        if args.target == "lab":
            face = P.reshape(len(P), 3, 3).mean(1)                    # 3부위 평균 → 얼굴 Lab
            tface = np.asarray(targets_of(va), np.float32).reshape(len(P), 3, 3).mean(1)
            de = float(np.sqrt(((face - tface) ** 2).sum(1)).mean())
            for L, _a, b in face:
                I = ita_of(float(L), float(b))
                seasons.append(season_of(I, float(b) - (slope * I + inter), ita_boundary))
        else:
            for I, resid in P:
                seasons.append(season_of(float(I), float(resid), ita_boundary))

        acc = float(np.mean([seasons[i] == va_true_season[i] for i in range(len(seasons))]))
        # 조명 일치도 — 같은 사람의 다른 조명 프레임이 같은 계절인가
        by = {}
        for i, u in enumerate(va_uid):
            by.setdefault(u, []).append(seasons[i])
        full = [v for v in by.values() if len(v) >= 2]
        cons = float(np.mean([len(set(v)) == 1 for v in full])) if full else float("nan")

        de_txt = f"ΔE={de:.3f}  " if args.target == "lab" else ""
        print(f"  epoch {ep+1}/{args.epochs} loss={tot/max(1,len(dl_tr)):.4f}  "
              f"{de_txt}계절정확도={acc:.1%}  조명일치도={cons:.1%}", flush=True)

        # ★ 모델 선택 기준 = 계절 정확도(목표와 일치). v2/v3 는 ΔE 였다.
        if acc > best_acc:
            best_acc = acc
            p = ROOT / out
            p.parent.mkdir(parents=True, exist_ok=True)
            torch.save({
                "feat": model["feat"].state_dict(), "head": model["head"].state_dict(),
                "target_mean": mean, "target_std": std, "targets": names,
                "mode": args.target, "a_weight": args.a_weight,
                "rule": {"slope": slope, "intercept": inter, "ita_boundary": ita_boundary},
                "val_uids": sorted(val_uids),
            }, p)

    print(f"\n최고 val 계절정확도 = {best_acc:.1%} → {out}")
    print("   비교: v1 55.0% / v2(500lux) 58.9% / v3+TTA 앙상블 57.6%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
