"""학습된 2단 피부 모델 평가 — 혼동행렬 + 악성(urgent) recall 중심.

Tier1 게이트는 '악성을 놓치지 않는가(recall)'가 핵심 지표다. 전체 정확도보다
urgent_referral recall과 '악성을 정상으로 오분류(가장 위험한 오류)' 건수를 본다.

    python scripts/evaluate_dermatology.py --tier 1 \
      --manifest data/manifests/dermatology_manifest.csv \
      --model data/models/derma_tier1_gate.pt
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import torch
from PIL import Image
from sklearn.model_selection import train_test_split
from torch.utils.data import DataLoader
from torchvision import transforms

from train_dermatology import ManifestDataset, build_model, load_frame

URGENT = "urgent_referral"
NORMAL = "normal"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", type=int, choices=(1, 2), required=True)
    parser.add_argument("--manifest", default="data/manifests/dermatology_manifest.csv")
    parser.add_argument("--model", default="")
    args = parser.parse_args()

    model_path = Path(args.model or f"data/models/derma_tier{args.tier}.pt")
    ck = torch.load(model_path, map_location="cpu")
    classes = list(ck["classes"])
    frame, present = load_frame(Path(args.manifest), args.tier)
    # 학습과 동일 split 재현.
    _, val_frame = train_test_split(frame, test_size=0.2, random_state=42, stratify=frame["label"])
    val_frame = val_frame[val_frame["label"].isin(classes)]

    tf = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    model = build_model(ck.get("arch", "efficientnet_b0"), len(classes))
    model.load_state_dict(ck["model_state_dict"])
    model.eval()

    n = len(classes)
    conf = [[0] * n for _ in range(n)]
    with torch.no_grad():
        for images, targets in DataLoader(ManifestDataset(val_frame, classes, tf), batch_size=32):
            preds = model(images).argmax(dim=1)
            for t, p in zip(targets.tolist(), preds.tolist()):
                conf[t][p] += 1

    print(f"=== Tier{args.tier} 혼동행렬 (행=실제, 열=예측) ===")
    print("실제\\예측".ljust(18) + "".join(c[:10].rjust(11) for c in classes))
    total_correct = 0
    for t in range(n):
        row_total = sum(conf[t])
        total_correct += conf[t][t]
        line = classes[t][:16].ljust(18) + "".join(str(conf[t][p]).rjust(11) for p in range(n))
        line += f"   recall={conf[t][t]/max(1,row_total)*100:5.1f}%"
        print(line)
    total = sum(sum(r) for r in conf)
    print(f"\noverall acc = {total_correct/max(1,total)*100:.1f}%")

    if args.tier == 1 and URGENT in classes:
        ui = classes.index(URGENT)
        urgent_total = sum(conf[ui])
        urgent_recall = conf[ui][ui] / max(1, urgent_total)
        print(f"\n[조기발견 핵심] 악성(urgent) recall = {urgent_recall*100:.1f}% ({conf[ui][ui]}/{urgent_total})")
        if NORMAL in classes:
            ni = classes.index(NORMAL)
            missed_as_normal = conf[ui][ni]
            print(f"[최악의 오류] 악성을 '정상'으로 놓친 건수 = {missed_as_normal} "
                  f"(이 값이 0에 가까워야 함)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
