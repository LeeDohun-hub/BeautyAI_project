"""글로벌(다인종) 퍼스널컬러 분류기 학습 — 2단계.

배경: 현행 EfficientNet은 학습이 전부 Deep Armocromia(유럽)라 한국/비유럽 얼굴에서 OOD로
무너진다(capstonea model-only 0.2667). AI-Hub '글로벌 다인종 피부색 데이터'(723명·7인종·
분광측색 Lab/ITA·Fitzpatrick)로 백본을 먼저 다인종 표현으로 사전학습한 뒤, 계절 라벨이 있는
Deep Armo + CapstoneA로 4계절 헤드를 파인튜닝한다.

Stage 1 (pretrain): 다인종 얼굴 → 멀티태스크(피츠패트릭 분류 + ITA 회귀 + 대륙 분류)로 백본 학습.
                    계절 라벨이 없어도 '피부색/인종 인지' 표현을 배워 OOD 일반화를 높인다.
Stage 2 (finetune): Stage1 백본 + 4계절 헤드를 Deep Armo train + CapstoneA train으로 학습.

⚠️ 데이터 요건: Stage1은 다인종 '원천 이미지'(TS_*.zip)가 필요하다. 현재 저장소엔 라벨(TL)만
있고 이미지 zip 대부분이 0바이트(다운로드 미완). AI-Hub에서 TS_*_흰피부/중간색/어두운색 zip을
다시 받아야 한다. GPU 권장(현재 환경은 CPU-only라 본학습은 비현실적, 스모크만 가능).

Usage:
  # Stage 1
  python scripts/train_global_personal_color.py --stage 1 \
      --multiethnic scratch/multiethnic/multiethnic_available.csv \
      --out data/models/backbone_multiethnic.pt --epochs 20
  # Stage 2
  python scripts/train_global_personal_color.py --stage 2 \
      --season-manifests data/manifests/personal_color_manifest.csv,data/eval/capstonea_train_manifest.csv \
      --init data/models/backbone_multiethnic.pt \
      --out data/models/personal_color_global.pt --epochs 30
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import Dataset, DataLoader
from torchvision import models, transforms

SEASONS = ["spring", "summer", "autumn", "winter"]
SEASON_ALIAS = {"fall": "autumn", "primavera": "spring", "estate": "summer",
                "autunno": "autumn", "inverno": "winter",
                "봄": "spring", "여름": "summer", "가을": "autumn", "겨울": "winter"}
CONTINENTS = ["동북아시아", "동남아시아", "유럽권", "북미권", "남아시아권", "중동권", "기타"]

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

TRAIN_TF = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.RandomHorizontalFlip(),
    transforms.ColorJitter(0.1, 0.1, 0.1, 0.02),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])
EVAL_TF = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


def _norm_season(s: str):
    s = (s or "").strip().lower()
    if s in SEASONS: return s
    for k, v in SEASON_ALIAS.items():
        if k in s: return v
    return None


class MultiEthnicDS(Dataset):
    """Stage1: image -> (fitzpatrick 0-5, ita float, continent idx)."""
    def __init__(self, rows, tf):
        self.rows, self.tf = rows, tf
    def __len__(self): return len(self.rows)
    def __getitem__(self, i):
        r = self.rows[i]
        img = Image.open(r["image_path"]).convert("RGB")
        x = self.tf(img)
        fitz = max(0, int(float(r["fitzpatrick"])) - 1)  # 1-6 -> 0-5
        ita = float(r["ita_avg"]) / 50.0  # rough scale
        cont = CONTINENTS.index(r["continent"]) if r["continent"] in CONTINENTS else len(CONTINENTS) - 1
        return x, fitz, torch.tensor(ita, dtype=torch.float32), cont


class SeasonDS(Dataset):
    def __init__(self, rows, tf):
        self.rows, self.tf = rows, tf
    def __len__(self): return len(self.rows)
    def __getitem__(self, i):
        r = self.rows[i]
        img = Image.open(r["image_path"]).convert("RGB")
        return self.tf(img), SEASONS.index(r["label"])


def backbone():
    m = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.IMAGENET1K_V1)
    feat = nn.Sequential(m.features, m.avgpool, nn.Flatten())
    return feat, 1280


def load_rows(path):
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


def stage1(args):
    rows = [r for r in load_rows(args.multiethnic) if Path(r["image_path"]).exists()]
    # dedup by image_file
    seen, uniq = set(), []
    for r in rows:
        if r["image_path"] in seen: continue
        seen.add(r["image_path"]); uniq.append(r)
    print(f"stage1 images: {len(uniq)} (device={DEVICE})")
    feat, dim = backbone()
    head_fitz = nn.Linear(dim, 6); head_ita = nn.Linear(dim, 1); head_cont = nn.Linear(dim, len(CONTINENTS))
    net = nn.ModuleDict({"feat": feat, "fitz": head_fitz, "ita": head_ita, "cont": head_cont}).to(DEVICE)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-4)
    ce, mse = nn.CrossEntropyLoss(), nn.MSELoss()
    dl = DataLoader(MultiEthnicDS(uniq, TRAIN_TF), batch_size=args.batch, shuffle=True, num_workers=0)
    for ep in range(args.epochs):
        net.train(); tot = 0.0
        for x, fitz, ita, cont in dl:
            x, fitz, ita, cont = x.to(DEVICE), fitz.to(DEVICE), ita.to(DEVICE), cont.to(DEVICE)
            f = net["feat"](x)
            loss = ce(net["fitz"](f), fitz) + 0.5 * mse(net["ita"](f).squeeze(1), ita) + ce(net["cont"](f), cont)
            opt.zero_grad(); loss.backward(); opt.step(); tot += float(loss)
        print(f"  epoch {ep+1}/{args.epochs} loss={tot/max(1,len(dl)):.4f}", flush=True)
    torch.save({"backbone_state_dict": net["feat"].state_dict()}, args.out)
    print(f"saved backbone -> {args.out}")


def _load_season_rows(manifests):
    rows = []
    for mf in manifests.split(","):
        for r in load_rows(mf):
            lab = _norm_season(r.get("season") or r.get("label") or "")
            part = (r.get("partition") or "train").strip().lower()
            if lab is None or part not in ("train", ""):
                if lab is None: continue
            p = r["image_path"]
            if not Path(p).is_absolute():
                p = str((Path.cwd() / p))
            if Path(p).exists():
                rows.append({"image_path": p, "label": lab})
    return rows


def stage2(args):
    from collections import Counter
    rows = _load_season_rows(args.season_manifests)
    dist = Counter(r["label"] for r in rows)
    print(f"stage2 season images: {len(rows)} (device={DEVICE})  dist={dict(dist)}")
    feat, dim = backbone()
    if args.init and Path(args.init).exists():
        ck = torch.load(args.init, map_location="cpu")
        feat.load_state_dict(ck["backbone_state_dict"]); print(f"init backbone from {args.init}")
    head = nn.Linear(dim, len(SEASONS))
    net = nn.ModuleDict({"feat": feat, "head": head}).to(DEVICE)

    frozen = bool(getattr(args, "freeze_backbone", False))
    if frozen:
        for p in net["feat"].parameters():
            p.requires_grad_(False)
        print("  backbone FROZEN — 헤드만 학습(다인종 표현 보존, 유럽셋 덮어쓰기 방지)")
    opt = torch.optim.AdamW([p for p in net.parameters() if p.requires_grad],
                            lr=args.lr, weight_decay=1e-4)

    weight = None
    if getattr(args, "class_weight", False):
        n, k = len(rows), len(SEASONS)
        weight = torch.tensor([n / (k * max(1, dist.get(s, 0))) for s in SEASONS],
                              dtype=torch.float32, device=DEVICE)
        print("  class weights:", {s: round(float(w), 2) for s, w in zip(SEASONS, weight)})
    ce = nn.CrossEntropyLoss(weight=weight, label_smoothing=getattr(args, "label_smoothing", 0.05))

    dl = DataLoader(SeasonDS(rows, TRAIN_TF), batch_size=args.batch, shuffle=True, num_workers=0)
    for ep in range(args.epochs):
        if frozen:
            net["feat"].eval(); net["head"].train()   # 동결 BN 통계 유지
        else:
            net.train()
        tot = 0.0
        for x, y in dl:
            x, y = x.to(DEVICE), y.to(DEVICE)
            if frozen:
                with torch.no_grad():
                    f = net["feat"](x)
                logit = net["head"](f)
            else:
                logit = net["head"](net["feat"](x))
            loss = ce(logit, y)
            opt.zero_grad(); loss.backward(); opt.step(); tot += float(loss)
        print(f"  epoch {ep+1}/{args.epochs} loss={tot/max(1,len(dl)):.4f}", flush=True)
    # save in the SAME format the app's EfficientNetSeasonClassifier expects (full efficientnet_b0)
    full = models.efficientnet_b0(weights=None)
    full.classifier[1] = nn.Linear(full.classifier[1].in_features, len(SEASONS))
    # copy features/avgpool from feat (Sequential[0]=features, [1]=avgpool)
    full.features.load_state_dict(net["feat"][0].state_dict())
    full.classifier[1].load_state_dict(net["head"].state_dict())
    torch.save({"model_state_dict": full.state_dict()}, args.out)
    print(f"saved season model (app-compatible) -> {args.out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, required=True, choices=[1, 2])
    ap.add_argument("--multiethnic", default="")
    ap.add_argument("--season-manifests", default="")
    ap.add_argument("--init", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--freeze-backbone", action="store_true", help="Stage2: 백본 동결(헤드만 학습)")
    ap.add_argument("--label-smoothing", type=float, default=0.05)
    ap.add_argument("--class-weight", action="store_true", help="Stage2: 계절 불균형 클래스 가중치")
    args = ap.parse_args()
    if args.stage == 1:
        stage1(args)
    else:
        stage2(args)


if __name__ == "__main__":
    main()
