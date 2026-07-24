"""AI-Hub 퍼스널컬러 v5 — **다인종 사전학습 → 동북아 파인튜닝**으로 과적합을 공략한다.

왜 이 구조인가 (v4 실패에서 얻은 진단):
  v4 에서 `a` 가중치 축소(59.7%)·결정변수 직접회귀(58.3%) 둘 다 대조군(59.3%) 대비 무의미했다.
  로그가 원인을 말해준다 — **train loss 0.118→0.014(10배↓) 인데 val ΔE 는 2.65~2.94 에서 미동**,
  최고점은 epoch 9~13 이후 하락. 즉 병목은 용량 배분이 아니라 **과적합**이고, 동북아 646명은 적다.
  라벨(분광측색)은 6개 권역 전부에 있으므로 2,257명으로 늘려 사전학습한 뒤 동북아로 파인튜닝한다.

⚠️ 비교 가능성 — 평가셋을 고정한다:
  다인종 매니페스트의 동북아는 726명(Training+Validation 합산)이라 기존 646명과 인물 집합이 다르다.
  그냥 재분할하면 val 이 바뀌어 기존 수치(v1 55.0% / v4 대조군 59.3%)와 비교가 무의미해진다.
  그래서 **v1 체크포인트에 저장된 정식 val 129명을 고정 평가셋으로 로드**하고,
  **사전학습에서도 그 129명을 제외**한다(안 그러면 val 인물이 사전학습에 새어 들어간다).

Usage:
  # 1단계: 전 권역 사전학습(동북아 val 129명 제외)
  python scripts/train_aihub_pc_v5.py --stage pretrain --epochs 30 --out data/models/v5_pretrain.pt
  # 2단계: 동북아만으로 파인튜닝(사전학습 가중치에서 시작, 낮은 LR)
  python scripts/train_aihub_pc_v5.py --stage finetune --init-from data/models/v5_pretrain.pt \
      --epochs 20 --lr 1e-4 --out data/models/v5_final.pt
"""
from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path
from statistics import median

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifests" / "aihub_pc_multi_manifest.csv"
VAL_UIDS_CKPT = ROOT / "data" / "models" / "aihub_pc_lab.pt"      # 정식 val 129명 출처
HOME_REGION = "동북아시아"

SITES = ["forehead", "left", "right"]
TARGETS = [f"{s}_{c}" for s in SITES for c in "lab"]              # 9차원

NORM = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])


def eval_tf(size: int):
    return transforms.Compose([transforms.Resize((size, size)), transforms.ToTensor(), NORM])


def train_tf(geom_aug: bool, size: int):
    # ⚠️ 색 증강 금지 — 참 피부색 복원이 목표라 색을 흔들면 정답 대응이 깨진다.
    # ⚠️ 공간 크롭도 금지가 기본 — 타깃이 **부위별**(이마·좌뺨·우뺨) Lab 이라 크롭이 그 부위를
    #    잘라내면 없는 정보를 맞히라고 강요하는 셈이다. v5 실측: RandomResizedCrop 이 −3.3pp.
    if geom_aug:
        return transforms.Compose([
            transforms.RandomResizedCrop(size, scale=(0.7, 1.0), ratio=(0.9, 1.1)),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(), NORM,
        ])
    return transforms.Compose([
        transforms.Resize((size, size)), transforms.RandomHorizontalFlip(),
        transforms.ToTensor(), NORM,
    ])


def build_backbone(name: str):
    """EfficientNet 계열만 지원(classifier[1].in_features 로 통일). 반환 (net, feat_dim)."""
    factory = {
        "efficientnet_b0": (models.efficientnet_b0, models.EfficientNet_B0_Weights.IMAGENET1K_V1),
        "efficientnet_b2": (models.efficientnet_b2, models.EfficientNet_B2_Weights.IMAGENET1K_V1),
        "efficientnet_b3": (models.efficientnet_b3, models.EfficientNet_B3_Weights.IMAGENET1K_V1),
    }
    if name not in factory:
        raise SystemExit(f"지원하지 않는 backbone: {name} (가능: {', '.join(factory)})")
    fn, w = factory[name]
    net = fn(weights=w)
    dim = net.classifier[1].in_features
    net.classifier = nn.Identity()
    return net, dim


def ita_of(L: float, b: float) -> float:
    return math.degrees(math.atan2(L - 50.0, b))


def season_of(ita: float, residual: float, boundary: float) -> str:
    warm, light = residual > 0, ita > boundary
    return ("spring" if light else "autumn") if warm else ("summer" if light else "winter")


def illum_class(row) -> int:
    """(lux, kelvin) → 0..3. 보조 과제용 조명 라벨."""
    return (1 if int(row["lux"]) == 5000 else 0) * 2 + (1 if int(row["kelvin"]) == 5600 else 0)


class DS(Dataset):
    def __init__(self, rows, tf, mean, std):
        self.rows, self.tf, self.mean, self.std = rows, tf, mean, std
        self.cache = []
        for r in rows:
            p = Path(r["image_path"])
            self.cache.append(Image.open(p if p.is_absolute() else ROOT / p).convert("RGB"))
        self.y = np.array([[float(r[t]) for t in TARGETS] for r in rows], dtype=np.float32)
        self.illum = np.array([illum_class(r) for r in rows], dtype=np.int64)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return (self.tf(self.cache[i]),
                torch.from_numpy((self.y[i] - self.mean) / self.std),
                int(self.illum[i]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["pretrain", "finetune"], required=True)
    ap.add_argument("--init-from", default="", help="finetune 시 시작 가중치(사전학습 체크포인트)")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--a-weight", type=float, default=1.0,
                    help="a 채널 손실 가중치. v4 실측상 0.2 로 낮춰도 이득 없었다(기본 1.0 유지)")
    ap.add_argument("--geom-aug", type=int, default=0,
                    help="1=RandomResizedCrop. ⚠️ 기본 0 — 실측 −3.3pp(부위별 타깃을 잘라먹음). 켜지 말 것")
    ap.add_argument("--limit", type=int, default=0, help="스모크 테스트용: train/val 각각 상위 N 장만")
    ap.add_argument("--val-uids", default="data/val_uids.txt",
                    help="고정 평가 인물 목록(한 줄 1개). 없으면 v1 체크포인트에서 읽는다(로컬 전용)")
    ap.add_argument("--manifest", default="data/manifests/aihub_pc_multi_manifest.csv",
                    help="448px+얼굴크롭 셋을 쓰려면 aihub_pc_multi_face_manifest.csv")
    ap.add_argument("--backbone", default="efficientnet_b0",
                    help="efficientnet_b0 | efficientnet_b2 | efficientnet_b3")
    ap.add_argument("--img-size", type=int, default=224, help="입력 해상도. 448px 데이터면 320/384 도 가능")
    ap.add_argument("--sched", default="none", choices=["none", "cosine"], help="cosine=CosineAnnealingLR")
    ap.add_argument("--seed", type=int, default=42, help="멀티시드 앙상블용")
    ap.add_argument("--ft-regions", default=HOME_REGION,
                    help="파인튜닝 학습에 쓸 권역(쉼표 구분). 예: '동북아시아,동남아시아'(1,346명). "
                         "⚠️ 계절 규칙 적합과 평가는 항상 동북아 고정이다 — 경계가 동북아 ITA 중앙값(34.88)이라 "
                         "다른 권역에 그 자를 대면 유럽권은 과반이 봄/여름, 중동남아는 전원 가을/겨울로 "
                         "뭉개져 규칙이 의미를 잃는다. 여기서 바꾸는 건 학습 데이터 범위뿐이다.")
    ap.add_argument("--aux-illum", type=float, default=0.0,
                    help="조명(lux x kelvin 4클래스) 보조 예측 손실 가중치. 0=끔, 권장 0.2. "
                         "이 과제의 본질은 '조명을 추정해 나눠내기'이므로 조명을 직접 맞히게 하면 "
                         "그 능력이 강해진다는 가설(v7 에서 얼굴크롭이 배경=조명참조를 없애 −5.6pp 였던 발견 기반)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(os.cpu_count() or 4)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    rows = list(csv.DictReader((ROOT / args.manifest).open(encoding="utf-8")))
    # 고정 평가 인물 — 목록 파일 우선(패키지용, 129줄), 없으면 v1 체크포인트에서(로컬 전용, 16MB)
    uid_file = ROOT / args.val_uids
    if uid_file.exists():
        val_uids = {ln.strip() for ln in uid_file.read_text(encoding="utf-8").splitlines() if ln.strip()}
    else:
        val_uids = set(torch.load(VAL_UIDS_CKPT, map_location="cpu", weights_only=False)["val_uids"])

    va = [r for r in rows if r["uid"] in val_uids]
    pool = [r for r in rows if r["uid"] not in val_uids]          # 평가 인물은 어느 단계에서도 학습 금지
    ft_regions = {s.strip() for s in args.ft_regions.split(",") if s.strip()}
    known = {r["region"] for r in pool}
    if unknown := ft_regions - known:
        raise SystemExit(f"[오류] 매니페스트에 없는 권역: {', '.join(sorted(unknown))}"
                         f" (가능: {', '.join(sorted(known))})")
    tr = pool if args.stage == "pretrain" else [r for r in pool if r["region"] in ft_regions]

    if not va:
        print("[오류] 고정 val 인물이 매니페스트에 없다. 다인종 매니페스트를 먼저 만들어라.")
        return 1
    if args.limit:
        tr, va = tr[: args.limit], va[: args.limit]

    # 계절 규칙은 **동북아 train 인물**로만 적합(기존 평가와 동일 기준, val 누수 없음)
    home_tr = {r["uid"]: r for r in pool if r["region"] == HOME_REGION}
    xs = np.array([float(p["ita_face"]) for p in home_tr.values()])
    ys = np.array([float(p["face_b"]) for p in home_tr.values()])
    slope = float(((xs - xs.mean()) * (ys - ys.mean())).sum() / ((xs - xs.mean()) ** 2).sum())
    inter = float(ys.mean() - slope * xs.mean())
    boundary = float(median(xs))

    print(f"device={device}  stage={args.stage}  geom_aug={bool(args.geom_aug)}  a_weight={args.a_weight:g}")
    print(f"  train {len(tr)}장 / 인물 {len({r['uid'] for r in tr})}명"
          + ("  (전 권역)" if args.stage == "pretrain" else f"  ({', '.join(sorted(ft_regions))}만)"))
    print(f"  val   {len(va)}장 / 인물 {len({r['uid'] for r in va})}명 — 고정 평가셋(기존 수치와 직접 비교 가능)")
    print(f"  규칙(동북아 train {len(home_tr)}명 적합): face_b={slope:.4f}·ITA+{inter:.2f}, ITA경계 {boundary:.2f}")

    ytr = np.array([[float(r[t]) for t in TARGETS] for r in tr], dtype=np.float32)
    mean, std = ytr.mean(0), ytr.std(0) + 1e-6

    w = np.array([args.a_weight if t.endswith("_a") else 1.0 for t in TARGETS], np.float32)
    weights = torch.from_numpy(w).to(device)

    net, dim = build_backbone(args.backbone)
    head = nn.Linear(dim, len(TARGETS))
    if args.init_from:
        ck = torch.load(ROOT / args.init_from, map_location="cpu", weights_only=False)
        if ck.get("backbone", "efficientnet_b0") != args.backbone:
            raise SystemExit(f"[오류] init-from 백본({ck.get('backbone')}) != 현재({args.backbone})")
        net.load_state_dict(ck["feat"]); head.load_state_dict(ck["head"])
        print(f"  초기 가중치 로드: {args.init_from} (사전학습 val 정확도 {ck.get('best_acc', float('nan')):.1%})")
    mods = {"feat": net, "head": head}
    if args.aux_illum > 0:
        mods["aux"] = nn.Linear(dim, 4)          # 조명 4클래스(500/5000 x 3200/5600)
    model = nn.ModuleDict(mods).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs) if args.sched == "cosine" else None
    lossf = nn.SmoothL1Loss(reduction="none")
    auxf = nn.CrossEntropyLoss()

    print(f"  backbone={args.backbone} img={args.img_size} sched={args.sched} seed={args.seed} "
          f"aux_illum={args.aux_illum:g}")
    print("  이미지 디코드 중...", flush=True)
    dl_tr = DataLoader(DS(tr, train_tf(bool(args.geom_aug), args.img_size), mean, std),
                       batch_size=args.batch, shuffle=True)
    dl_va = DataLoader(DS(va, eval_tf(args.img_size), mean, std), batch_size=args.batch, shuffle=False)

    va_uid = [r["uid"] for r in va]
    va_true = []
    for r in va:
        L, b = float(r["face_l"]), float(r["face_b"])
        I = ita_of(L, b)
        va_true.append(season_of(I, b - (slope * I + inter), boundary))

    best = -1.0
    for ep in range(args.epochs):
        model.train()
        tot = 0.0
        for x, y, il in dl_tr:
            x, y = x.to(device), y.to(device)
            f = model["feat"](x)
            loss = (lossf(model["head"](f), y) * weights).mean()
            if args.aux_illum > 0:                       # 조명 추정 보조 과제
                loss = loss + args.aux_illum * auxf(model["aux"](f), il.to(device))
            opt.zero_grad(); loss.backward(); opt.step()
            tot += float(loss.detach())
        if sched is not None:
            sched.step()

        model.eval()
        P = []
        with torch.no_grad():
            for x, _, _ in dl_va:
                P.append(model["head"](model["feat"](x.to(device))).cpu().numpy() * std + mean)
        P = np.concatenate(P)
        face = P.reshape(len(P), 3, 3).mean(1)
        tface = np.array([[float(r[t]) for t in TARGETS] for r in va], np.float32).reshape(len(P), 3, 3).mean(1)
        de = float(np.sqrt(((face - tface) ** 2).sum(1)).mean())

        seasons = [season_of(ita_of(float(L), float(b)), float(b) - (slope * ita_of(float(L), float(b)) + inter), boundary)
                   for L, _a, b in face]
        acc = float(np.mean([seasons[i] == va_true[i] for i in range(len(seasons))]))
        by = {}
        for i, u in enumerate(va_uid):
            by.setdefault(u, []).append(seasons[i])
        full = [v for v in by.values() if len(v) >= 2]
        cons = float(np.mean([len(set(v)) == 1 for v in full])) if full else float("nan")

        print(f"  epoch {ep+1}/{args.epochs} loss={tot/max(1,len(dl_tr)):.4f}  ΔE={de:.3f}  "
              f"계절정확도={acc:.1%}  조명일치도={cons:.1%}", flush=True)

        if acc > best:                       # ★ 모델 선택 = 계절 정확도(v4 에서 +1.7pp 벌어준 변경)
            best = acc
            p = ROOT / args.out
            p.parent.mkdir(parents=True, exist_ok=True)
            torch.save({"feat": model["feat"].state_dict(), "head": model["head"].state_dict(),
                        "target_mean": mean, "target_std": std, "targets": TARGETS,
                        "rule": {"slope": slope, "intercept": inter, "ita_boundary": boundary},
                        "val_uids": sorted(val_uids), "stage": args.stage, "best_acc": best,
                        "backbone": args.backbone, "img_size": args.img_size, "seed": args.seed}, p)

    print(f"\n[{args.stage}] 최고 val 계절정확도 = {best:.1%} → {args.out}")
    print("   비교: v1 55.0% / v2 58.9% / v3+TTA 57.6% / v4 대조군 59.3%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
