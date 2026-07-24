"""라운드3 체크포인트의 앙상블·TTA·다중프레임 효과를 고정 val 129명에서 측정한다.

평가 로직은 scripts/train_aihub_pc_v5.py 와 **완전히 동일**하게 맞췄다(같은 val_uids, 같은
9차원→얼굴평균 환산, 같은 계절 규칙). 그래서 나오는 숫자가 학습 로그의 61.0% 와 직접 비교된다.

측정하는 것:
  단일 → +TTA(좌우반전) → +시드앙상블(3개) → +다중프레임(인물당 4조명 Lab 평균)
  마지막은 '같은 사람 사진 여러 장'을 쓸 수 있을 때의 상한이다. 단 이 데이터의 4장은
  **조명이 서로 다른** 프레임이라, 실제 서비스에서 같은 조명으로 연속 촬영한 경우와는 다르다.

Usage:
  python scripts/eval_ensemble_r3.py --models scratch/r3out/data/models/c_aux42.pt,...
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torchvision import models, transforms

ROOT = Path(__file__).resolve().parents[1]
SITES = ["forehead", "left", "right"]
TARGETS = [f"{s}_{c}" for s in SITES for c in "lab"]
TF = transforms.Compose([
    transforms.Resize((224, 224)), transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


def season_of(L: float, b: float, slope: float, inter: float, bound: float) -> str:
    ita = math.degrees(math.atan2(L - 50.0, b))
    warm, light = b - (slope * ita + inter) > 0, ita > bound
    return ("spring" if light else "autumn") if warm else ("summer" if light else "winter")


def load_member(path: Path):
    ck = torch.load(path, map_location="cpu", weights_only=False)
    net = models.efficientnet_b0(weights=None)
    dim = net.classifier[1].in_features
    net.classifier = torch.nn.Identity()
    net.load_state_dict(ck["feat"])
    head = torch.nn.Linear(dim, len(TARGETS))
    head.load_state_dict(ck["head"])
    net.eval(); head.eval()
    return net, head, np.asarray(ck["target_mean"], np.float32), np.asarray(ck["target_std"], np.float32), ck


def predict(members, imgs, tta: bool) -> np.ndarray:
    """→ (N, 3) 얼굴평균 Lab. 멤버 x TTA 뷰를 전부 평균한다."""
    x = torch.stack([TF(im) for im in imgs])
    views = [x, torch.flip(x, dims=[3])] if tta else [x]
    acc = []
    with torch.no_grad():
        for net, head, mean, std, _ in members:
            for v in views:
                out = []
                for i in range(0, len(v), 32):
                    out.append(head(net(v[i:i + 32])).numpy())
                acc.append(np.concatenate(out) * std + mean)
    return np.mean(acc, axis=0).reshape(len(imgs), 3, 3).mean(1)


def score(pred_face, rows, rule, per_person: bool):
    slope, inter, bound = rule
    uids = [r["uid"] for r in rows]
    true_s = [season_of(float(r["face_l"]), float(r["face_b"]), slope, inter, bound) for r in rows]
    tface = np.array([[float(r[t]) for t in TARGETS] for r in rows], np.float32).reshape(len(rows), 3, 3).mean(1)

    if per_person:                      # 인물당 4프레임의 예측 Lab 을 평균한 뒤 한 번 판정
        by = {}
        for i, u in enumerate(uids):
            by.setdefault(u, []).append(i)
        P = np.array([pred_face[ix].mean(0) for ix in by.values()])
        T = np.array([tface[ix].mean(0) for ix in by.values()])
        truth = [true_s[ix[0]] for ix in by.values()]
        de = float(np.sqrt(((P - T) ** 2).sum(1)).mean())
        acc = float(np.mean([season_of(L, b, slope, inter, bound) == truth[i]
                             for i, (L, _a, b) in enumerate(P)]))
        return acc, de, float("nan"), len(P)

    de = float(np.sqrt(((pred_face - tface) ** 2).sum(1)).mean())
    seasons = [season_of(L, b, slope, inter, bound) for L, _a, b in pred_face]
    acc = float(np.mean([seasons[i] == true_s[i] for i in range(len(seasons))]))
    by = {}
    for i, u in enumerate(uids):
        by.setdefault(u, []).append(seasons[i])
    full = [v for v in by.values() if len(v) >= 2]
    cons = float(np.mean([len(set(v)) == 1 for v in full])) if full else float("nan")
    return acc, de, cons, len(pred_face)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True, help="체크포인트 경로 쉼표 구분(첫 번째가 단일 기준)")
    ap.add_argument("--manifest", default="data/manifests/aihub_pc_multi_manifest.csv")
    ap.add_argument("--val-uids", default="data/val_uids.txt")
    args = ap.parse_args()

    paths = [ROOT / p.strip() for p in args.models.split(",") if p.strip()]
    members = [load_member(p) for p in paths]
    rule_d = members[0][4]["rule"]
    rule = (rule_d["slope"], rule_d["intercept"], rule_d["ita_boundary"])
    for p, m in zip(paths, members):
        r = m[4]["rule"]
        if (r["slope"], r["intercept"], r["ita_boundary"]) != rule:
            raise SystemExit(f"[오류] {p.name} 의 규칙이 다르다 — 앙상블 불가")

    val_uids = {ln.strip() for ln in (ROOT / args.val_uids).read_text(encoding="utf-8").splitlines() if ln.strip()}
    rows = [r for r in csv.DictReader((ROOT / args.manifest).open(encoding="utf-8")) if r["uid"] in val_uids]
    print(f"val {len(rows)}장 / 인물 {len({r['uid'] for r in rows})}명   규칙 {rule}")
    print(f"멤버 {len(members)}개: {', '.join(p.name for p in paths)}")
    print("  이미지 디코드 중...", flush=True)
    imgs = [Image.open(ROOT / r["image_path"]).convert("RGB") for r in rows]

    print(f"\n{'설정':<34}{'계절정확도':>10}{'ΔE':>8}{'조명일치도':>11}{'단위':>8}")
    print("-" * 71)
    cache = {}
    for label, mem, tta, per in [
        ("단일 (c_aux42)",                    members[:1], False, False),
        ("단일 + TTA",                        members[:1], True,  False),
        (f"시드앙상블 {len(members)}개",        members,     False, False),
        (f"시드앙상블 {len(members)}개 + TTA",  members,     True,  False),
        (f"위 + 다중프레임(인물당 4장)",         members,     True,  True),
    ]:
        key = (len(mem), tta)
        if key not in cache:
            cache[key] = predict(mem, imgs, tta)
        acc, de, cons, n = score(cache[key], rows, rule, per)
        cs = "  —  " if math.isnan(cons) else f"{cons:>10.1%}"
        print(f"{label:<34}{acc:>10.1%}{de:>8.3f}{cs}{n:>7}{'명' if per else '장'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
