"""RunPod 피부케어 6항목 분류기(EfficientNet-B0) 재학습용 self-contained 번들을 조립한다.

데이터 근거: AI-Hub '03.스킨케어 성분-효능 추천 데이터'의 원천 CSV 육안평가 등급.
  ⚠️ '01.글로벌 다인종 피부색 데이터'는 쓰지 않는다(피부색 != 피부상태). 근거는 02/03 뿐.

하는 일:
  1) TS_/VS_ 원천 zip에서 이미지를 max-side 로 다운스케일 추출
       → runpod_skin/data/images/{train,val}/<split>_<idx>.jpg  (7GB → ~0.5GB)
  2) 같은 폴더의 CSV 육안평가를 6타깃 0~100 밴드로 매핑해 매니페스트(split 컬럼 포함) 생성
       acne←여드름(A=100/else0) · pore←모공(VP=100/NVP0) · redness←붉어짐(R=100/NR0)
       wrinkle←주름(W0/1/2=0/50/100) · pigmentation←미백(P0/1/2=0/50/100)
       oiliness←피부타입(지성100/복합성60/중성30/건성0)  ※03 직접등급 없어 프록시(약한 라벨)
     공식 분할 사용: TS_→train(8000), VS_→val(1000).
  3) 학습 스크립트(train_skin.py) + requirements-train.txt + run.sh(LF) + README 동봉
  4) 라벨 분포 요약 + 총 용량 + tar 명령 출력

Usage:
  python scripts/pack_runpod_skin.py                 # 384px
  python scripts/pack_runpod_skin.py --max-side 320  # 더 작게
  python scripts/pack_runpod_skin.py --clean         # 기존 runpod_skin 지우고 새로
"""
from __future__ import annotations

import argparse
import csv
import io
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/03.스킨케어 성분-효능 추천 데이터/3.개방데이터/2.데이터(NIA)"
PKG = ROOT / "runpod_skin"
TARGETS = ("acne", "pore", "wrinkle", "redness", "pigmentation", "oiliness")
WORKERS = 8
BATCH = 128


# ---------- 라벨 매핑 ----------
def _cell(rowd: dict[str, str], key_nospace: str) -> str:
    for h, v in rowd.items():
        if h and key_nospace in h.replace(" ", ""):
            return (v or "").strip()
    return ""


def labels_from_csv(rowd: dict[str, str]) -> dict[str, float]:
    acne = 100.0 if _cell(rowd, "여드름") == "A" else 0.0
    pore = 100.0 if _cell(rowd, "모공") == "VP" else 0.0          # VP=visible / NVP=not
    redness = 100.0 if _cell(rowd, "붉어짐") == "R" else 0.0       # R / NR
    wrinkle = {"W0": 0.0, "W1": 50.0, "W2": 100.0}.get(_cell(rowd, "주름"), 0.0)
    pigment = {"P0": 0.0, "P1": 50.0, "P2": 100.0}.get(_cell(rowd, "미백"), 0.0)
    # oiliness는 03에 직접 유분등급이 없어 '얼굴 피부 타입'을 프록시로 쓴다(약한 라벨).
    # pore/acne 와 블렌딩하지 않는다 — 그러면 출력 채널간 상관이 올라가 6항목 구분력이 훼손된다.
    # 대신 학습에서 손실 다운웨이트(--oiliness-weight)로 저신뢰 취급. 매핑은 전형적 피지량 순서로 재보정.
    skin_type = _cell(rowd, "피부타입")                            # 얼굴 피부 타입
    oili = {"지성": 100.0, "복합성": 65.0, "중성": 35.0, "건성": 10.0}.get(skin_type, 35.0)
    return {"acne": acne, "pore": pore, "wrinkle": wrinkle,
            "redness": redness, "pigmentation": pigment, "oiliness": oili}


# ---------- 다운스케일 ----------
def downscale_bytes(data: bytes, max_side: int) -> bytes | None:
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None
    w, h = im.size
    s = max_side / max(w, h)
    if s < 1.0:
        im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=88)
    return out.getvalue()


def _save_job(job):
    data, dest, max_side = job
    small = downscale_bytes(data, max_side)
    if small is None:
        return None
    Path(dest).write_bytes(small)
    return dest


def pack(max_side: int, no_images: bool = False):
    (PKG / "data/manifests").mkdir(parents=True, exist_ok=True)
    rows = []
    dist = defaultdict(lambda: defaultdict(Counter))  # split -> target -> Counter(score)
    counters = Counter()
    idx = {"train": 0, "val": 0}

    zips = sorted(DATASET.rglob("TS_*.zip")) + sorted(DATASET.rglob("VS_*.zip"))
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for z in zips:
            if "원천데이터" not in str(z):
                continue
            split = "train" if z.name.startswith("TS_") else "val"
            outdir = PKG / "data/images" / split
            outdir.mkdir(parents=True, exist_ok=True)
            try:
                zf = zipfile.ZipFile(z)
            except Exception as exc:
                print(f"  [skip bad] {z.name}: {exc}", flush=True)
                continue
            # 폴더별로 csv/jpg 짝
            pair: dict[str, dict[str, str]] = defaultdict(dict)
            with zf:
                for entry in zf.namelist():
                    low = entry.lower()
                    folder = Path(entry).parts[0] if Path(entry).parts else entry
                    if low.endswith(".csv"):
                        pair[folder]["csv"] = entry
                    elif low.endswith((".jpg", ".jpeg", ".png")):
                        pair[folder]["img"] = entry
                jobs = []
                pending = []  # (rowdict-without-path, dest_relpath)
                n = 0
                for folder, pr in pair.items():
                    if "csv" not in pr or "img" not in pr:
                        continue
                    txt = zf.read(pr["csv"]).decode("utf-8-sig", errors="replace")
                    recs = list(csv.reader(io.StringIO(txt)))
                    if len(recs) < 2:
                        continue
                    rowd = dict(zip(recs[0], recs[1]))
                    labels = labels_from_csv(rowd)
                    idx[split] += 1
                    fname = f"{split}_{idx[split]:06d}.jpg"
                    rel = f"data/images/{split}/{fname}"
                    row = {"image_path": rel, "split": split,
                           **{t: labels[t] for t in TARGETS}}
                    if no_images:  # 이미지 재추출 없이 매니페스트만 갱신(기존 파일명과 결정적으로 일치)
                        if (PKG / rel).exists():
                            pending.append(row)
                            n += 1
                            for t in TARGETS:
                                dist[split][t][labels[t]] += 1
                        continue
                    jobs.append((zf.read(pr["img"]), str(outdir / fname), max_side))
                    pending.append(row)
                    for t in TARGETS:
                        dist[split][t][labels[t]] += 1
                    if len(jobs) >= BATCH:
                        n += sum(1 for r in pool.map(_save_job, jobs) if r)
                        jobs = []
                if jobs:
                    n += sum(1 for r in pool.map(_save_job, jobs) if r)
            rows.extend(pending)
            counters[split] += n
            print(f"  {z.name}: {n} imgs -> {split}", flush=True)

    # 매니페스트
    out = PKG / "data/manifests/skin03.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["image_path", "split", *TARGETS])
        w.writeheader()
        w.writerows(rows)
    print(f"\nmanifest rows: {len(rows)}  (train={counters['train']} val={counters['val']}) -> {out}")

    print("\n=== 라벨 분포 (positive/score 카운트) ===")
    for split in ("train", "val"):
        print(f"[{split}]")
        for t in TARGETS:
            d = dict(sorted(dist[split][t].items()))
            print(f"  {t:12s} {d}")
    return len(rows)


def write_support():
    (PKG / "scripts").mkdir(parents=True, exist_ok=True)
    (PKG / "backend").mkdir(parents=True, exist_ok=True)

    (PKG / "backend/requirements-train.txt").write_text(
        "torch==2.7.1\ntorchvision==0.22.1\nnumpy==1.26.4\nPillow==10.4.0\ntqdm==4.66.5\n",
        encoding="utf-8",
    )

    (PKG / "scripts/train_skin.py").write_text(TRAIN_SKIN_PY, encoding="utf-8", newline="\n")

    (PKG / "run.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# RunPod PyTorch 템플릿의 torch+CUDA 를 그대로 쓴다(venv 만들면 torch 재다운로드라 낭비).\n"
        "python -c 'import torch; print(\"cuda:\", torch.cuda.is_available(), torch.__version__)'\n"
        "pip install -q tqdm pillow 2>/dev/null || true\n"
        "mkdir -p data/models\n"
        "# v2 개선: --class-weight(밴드 역빈도 가중) --aug(셀카 도메인 강건화 증강) --oiliness-weight(프록시 다운웨이트)\n"
        "python scripts/train_skin.py \\\n"
        "  --manifest data/manifests/skin03.csv \\\n"
        "  --out data/models/skin_efficientnet_b0_aihub03_v2.pt \\\n"
        "  --epochs 20 --batch-size 64 --lr 5e-4 \\\n"
        "  --class-weight --aug --oiliness-weight 0.5\n"
        "tar czf /workspace/skin03_v2.tar.gz data/models/skin_efficientnet_b0_aihub03_v2.pt\n"
        "echo '=== 완료. /workspace/skin03_v2.tar.gz 를 내려받으세요 ==='\n"
        "ls -lh /workspace/skin03_v2.tar.gz\n",
        encoding="utf-8", newline="\n",
    )

    (PKG / "README_RUNPOD.md").write_text(README_MD, encoding="utf-8", newline="\n")
    print("support files: train_skin.py, requirements-train.txt, run.sh, README_RUNPOD.md")


def dir_size_mb(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6


TRAIN_SKIN_PY = r'''"""피부케어 6항목 회귀기 학습 (AI-Hub 03).  v2 개선:
  --class-weight   타깃별·밴드별 역빈도 가중(희소 등급 upweight, mean=1 정규화)
  --aug            셀카 도메인 강건화 증강(색상지터/블러/랜덤크롭/이레이징)
  --oiliness-weight 유분(피부타입 프록시) 손실 다운웨이트(기본 0.5, 저신뢰)
pandas/sklearn 미의존(csv+수동분할)이라 CPU 환경에서도 스모크 가능.
"""
from __future__ import annotations

import argparse
import csv
import random
from collections import Counter
from pathlib import Path

import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

try:
    from tqdm import tqdm
except Exception:  # tqdm 없어도 동작
    def tqdm(x, **k):
        return x

TARGETS = ("acne", "pore", "wrinkle", "redness", "pigmentation", "oiliness")


def read_manifest(path: str) -> list[dict]:
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8")) if Path(r["image_path"]).exists()]
    for r in rows:
        for t in TARGETS:
            r[t] = float(r[t])
    return rows


def attach_weights(rows: list[dict], class_weight: bool, oili_weight: float) -> None:
    base = {t: 1.0 for t in TARGETS}
    base["oiliness"] = oili_weight
    valw = {t: {} for t in TARGETS}
    for t in TARGETS:
        cnt = Counter(round(r[t], 3) for r in rows)
        n, k = sum(cnt.values()), len(cnt)
        for v, c in cnt.items():
            valw[t][v] = (n / (k * c)) if class_weight else 1.0   # 역빈도, mean=1 정규화
    for r in rows:
        r["_w"] = [base[t] * valw[t][round(r[t], 3)] for t in TARGETS]


class SkinDataset(Dataset):
    def __init__(self, rows: list[dict], transform) -> None:
        self.rows = rows
        self.transform = transform

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int):
        r = self.rows[index]
        image = Image.open(r["image_path"]).convert("RGB")
        target = torch.tensor([r[t] / 100.0 for t in TARGETS], dtype=torch.float32)
        weight = torch.tensor(r["_w"], dtype=torch.float32)
        return self.transform(image), target, weight


def build_model() -> nn.Module:
    model = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.DEFAULT)
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, len(TARGETS))
    return model


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/manifests/skin03.csv")
    ap.add_argument("--out", default="data/models/skin_efficientnet_b0_aihub03_v2.pt")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--class-weight", action="store_true")
    ap.add_argument("--oiliness-weight", type=float, default=0.5)
    ap.add_argument("--aug", action="store_true")
    ap.add_argument("--max-samples", type=int, default=0, help="스모크용: split별 상한(0=전체)")
    args = ap.parse_args()

    rows = read_manifest(args.manifest)
    if rows and "split" in rows[0]:
        train_rows = [r for r in rows if r["split"] == "train"]
        val_rows = [r for r in rows if r["split"] == "val"]
    else:
        random.seed(42)
        random.shuffle(rows)
        cut = int(len(rows) * 0.8)
        train_rows, val_rows = rows[:cut], rows[cut:]
    if args.max_samples:
        train_rows, val_rows = train_rows[:args.max_samples], val_rows[:args.max_samples]
    attach_weights(train_rows, args.class_weight, args.oiliness_weight)
    attach_weights(val_rows, False, 1.0)   # val 은 가중 없이(공정 비교, 이전 run 과 apples-to-apples)
    print(f"train={len(train_rows)} val={len(val_rows)} class_weight={args.class_weight} "
          f"aug={args.aug} oili_w={args.oiliness_weight}")

    norm = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    if args.aug:
        train_tf = transforms.Compose([
            transforms.RandomResizedCrop(224, scale=(0.75, 1.0), ratio=(0.85, 1.18)),
            transforms.RandomHorizontalFlip(),
            transforms.ColorJitter(0.3, 0.3, 0.3, 0.05),
            transforms.RandomApply([transforms.GaussianBlur(3, (0.1, 1.6))], p=0.3),
            transforms.ToTensor(),
            transforms.RandomErasing(p=0.2, scale=(0.02, 0.12)),
            norm,
        ])
    else:
        train_tf = transforms.Compose([
            transforms.Resize((224, 224)), transforms.RandomHorizontalFlip(),
            transforms.ToTensor(), norm,
        ])
    val_tf = transforms.Compose([transforms.Resize((224, 224)), transforms.ToTensor(), norm])

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    criterion = nn.SmoothL1Loss(reduction="none")
    nw = 4 if device.type == "cuda" else 0
    train_loader = DataLoader(SkinDataset(train_rows, train_tf), batch_size=args.batch_size,
                              shuffle=True, num_workers=nw, pin_memory=(device.type == "cuda"))
    val_loader = DataLoader(SkinDataset(val_rows, val_tf), batch_size=args.batch_size,
                            shuffle=False, num_workers=nw, pin_memory=(device.type == "cuda"))

    best = float("inf")
    for epoch in range(1, args.epochs + 1):
        model.train()
        tl = 0.0
        for images, targets, weights in tqdm(train_loader, desc=f"epoch {epoch} train"):
            images, targets, weights = images.to(device), targets.to(device), weights.to(device)
            optimizer.zero_grad()
            loss = (criterion(model(images), targets) * weights).mean()
            loss.backward()
            optimizer.step()
            tl += loss.item() * len(images)

        model.eval()
        vl = 0.0
        mae = torch.zeros(len(TARGETS))
        with torch.no_grad():
            for images, targets, _ in tqdm(val_loader, desc=f"epoch {epoch} val"):
                pred = model(images.to(device)).cpu()
                vl += nn.functional.smooth_l1_loss(pred, targets, reduction="mean").item() * len(images)
                mae += (pred - targets).abs().sum(0)
        tl /= max(1, len(train_rows))
        vl /= max(1, len(val_rows))
        mae = (mae / max(1, len(val_rows)) * 100.0)
        per = "  ".join(f"{t}={mae[i]:.1f}" for i, t in enumerate(TARGETS))
        print(f"epoch={epoch} train_loss={tl:.4f} val_loss={vl:.4f}  val_MAE(0-100): {per}")
        if vl < best:
            best = vl
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            torch.save({
                "model_state_dict": model.state_dict(),
                "targets": TARGETS,
                "val_loss": best,
                "epochs": epoch,
                "label_scale": 100.0,
                "source": "aihub_03_skincare",
                "class_weight": args.class_weight,
                "aug": args.aug,
                "oiliness_weight": args.oiliness_weight,
            }, out)
            print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


README_MD = """# RunPod 피부케어 6항목 분류기 재학습 번들 (AI-Hub 03)

이 폴더만 RunPod(GPU)에 올려 실행하는 self-contained 패키지.

**모델**: EfficientNet-B0 회귀, 6타깃(acne/pore/wrinkle/redness/pigmentation/oiliness) 0~100.
**데이터**: AI-Hub '03.스킨케어 성분-효능 추천 데이터' 원천 CSV 육안평가 → 밴드 매핑.
공식 분할 사용(Train 8,000 / Val 1,000). 인물ID 카테고리 간 중복 0(누수 없음).

## 라벨 매핑
| target | 출처 컬럼 | 매핑 |
|---|---|---|
| acne | 여드름 | A=100, NA/공백=0 |
| pore | 모공 | VP=100, NVP=0 |
| redness | 붉어짐 | R=100, NR=0 |
| wrinkle | 주름 | W0/W1/W2 = 0/50/100 |
| pigmentation | 미백 | P0/P1/P2 = 0/50/100 |
| oiliness | 얼굴 피부 타입 | 지성/복합성/중성/건성 = 100/60/30/0 (프록시·약한 라벨) |

## v2 개선(2026-07-23)
- **클래스 불균형 가중**(`--class-weight`): 타깃별·밴드별 역빈도 가중(mean=1). 희소 등급(acne=100 22%, redness=100 30%, pigment=0 등) upweight.
- **셀카 도메인 강건화 증강**(`--aug`): 색상지터/가우시안블러/랜덤크롭/랜덤이레이징. 라벨된 셀카가 없어 진짜 파인튜닝 대신, 스튜디오→셀카 도메인 갭에 강건하게. → 같은-순간 재현성 개선 기대.
- **oiliness 프록시 다운웨이트**(`--oiliness-weight 0.5`): 피부타입 유추라 저신뢰 → 손실 기여 축소. pore/acne 와 블렌딩은 안 함(출력 채널 상관 상승 방지).

## 실행 (이 폴더에서, GPU 필수)
```bash
bash run.sh
```
끝나면 `/workspace/skin03_v2.tar.gz`(= `skin_efficientnet_b0_aihub03_v2.pt`)를 내려받아
로컬 `data/models/`에 두고 **신(v2) vs 구(v1) vs Kaggle** 3자 비교(03 val MAE·출력상관·연속촬영 재현성).

## 검증 포인트
1. **재현성이 핵심 지표** — v1 대비 세트내/세트간 비율이 내려가야(증강 효과). MAE만 보지 말 것.
2. **pore VP가 84%** — '모공 보임'이 다수라 pore 라벨이 대부분 100. 구분력 확인.
3. **oiliness는 프록시** — 직접 유분등급 아님. v2에서 손실 다운웨이트됨. 신뢰도 낮게 취급.
4. 저장은 **새 파일**(`_v2.pt`) — 검증 전까지 서빙(.env SKIN_MODEL_PATH) 교체 금지. 더 나으면 그때 교체.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-side", type=int, default=384)
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--no-images", action="store_true",
                    help="이미지 재추출 없이 매니페스트+스크립트만 갱신(기존 runpod_skin/data/images 재사용)")
    args = ap.parse_args()

    import shutil
    if args.clean and PKG.exists():
        shutil.rmtree(PKG)
    PKG.mkdir(parents=True, exist_ok=True)

    if args.no_images:
        print("== 매니페스트+스크립트만 갱신(이미지 재사용) ==")
        pack(args.max_side, no_images=True)
    else:
        print(f"== AI-Hub 03 이미지 다운스케일({args.max_side}px)+추출 & 매니페스트 ==")
        pack(args.max_side)
    write_support()

    print(f"\n번들 준비 완료: {PKG}")
    print(f"총 용량: {dir_size_mb(PKG):.0f} MB")
    print("\n다음: tar 로 묶어 업로드")
    print(f'  tar czf runpod_skin.tar.gz -C "{ROOT}" runpod_skin')


if __name__ == "__main__":
    raise SystemExit(main())
