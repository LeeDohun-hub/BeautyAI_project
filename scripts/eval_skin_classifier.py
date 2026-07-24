"""피부케어 6항목 회귀기(`skin_efficientnet_b0.pt`) 점검.

⚠️ 「01. 글로벌 다인종 피부색 데이터」는 쓰지 않는다. 그건 피부색(분광측색 Lab) 데이터지
   피부상태 데이터가 아니다. 피부케어 근거는 02/03 데이터로만 잡는다(사용자 지시).

세 가지를 본다:
  ① 학습 라벨의 구조 — 이 모델이 애초에 무엇을 배울 수 있었는가
  ② 누수 보정 정확도 — 학습이 쓴 이미지 단위 분할 vs 원본(증강 묶음) 단위 분할
  ③ ★ 재현성 — **같은 순간에 연속 촬영한 사진들**에 같은 점수를 주는가.
     같은 조명·같은 얼굴이므로 점수 차이는 전부 측정 노이즈다. 외부 데이터가 필요 없는
     가장 정직한 신뢰도 시험이다.

Usage:
  python scripts/eval_skin_classifier.py --limit 700 --photos docs
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from sklearn.model_selection import train_test_split
from torchvision import models, transforms

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("acne", "pore", "wrinkle", "redness", "pigmentation", "oiliness")
LABELS = {"acne": "트러블", "pore": "모공", "wrinkle": "주름",
          "redness": "홍조", "pigmentation": "색소침착", "oiliness": "유분"}
TF = transforms.Compose([
    transforms.Resize((224, 224)), transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])
# 로보플로우 증강본은 원본 하나에서 파생된다: "100_jpg.rf.<hash>.jpg" → 원본키 "100"
RF_RE = re.compile(r"^(.*?)_jpg\.rf\.[0-9a-f]+", re.I)
# 카카오톡 연속 촬영 묶음: KakaoTalk_<날짜>_<시각ID>[_NN][(...)].jpg → 세션키 = 날짜_시각ID
SESSION_RE = re.compile(r"^KakaoTalk_(\d+_\d+)")


def origin_key(path: str) -> str:
    p = Path(path)
    m = RF_RE.match(p.name)
    return f"{p.parent}|{m.group(1) if m else p.stem}"


def load_model():
    ck = torch.load(ROOT / "data/models/skin_efficientnet_b0.pt", map_location="cpu", weights_only=False)
    net = models.efficientnet_b0(weights=None)
    net.classifier[1] = torch.nn.Linear(net.classifier[1].in_features, len(TARGETS))
    net.load_state_dict(ck["model_state_dict"])
    net.eval()
    return net, float(ck.get("label_scale", 1.0)), float(ck["val_loss"])


def predict_paths(net, scale, paths: list[Path], batch: int = 16) -> np.ndarray:
    out = []
    for i in range(0, len(paths), batch):
        imgs = torch.stack([TF(Image.open(p).convert("RGB")) for p in paths[i:i + batch]])
        with torch.no_grad():
            out.append(net(imgs).numpy() * scale)
    return np.clip(np.concatenate(out), 0, 100)


def section_labels() -> None:
    rows = list(csv.DictReader((ROOT / "data/manifests/skin_multitask_manifest.csv").open(encoding="utf-8")))
    Y = np.array([[float(r[t]) for t in TARGETS] for r in rows])
    combos = defaultdict(int)
    for row in Y:
        combos[tuple(row)] += 1
    print(f"── ① 학습 라벨 구조 (n={len(rows)}) ──")
    print(f"  서로 다른 라벨 조합: {len(combos)}종   값 종류: {sorted(set(Y.ravel().tolist()))}")
    same = [(TARGETS[i], TARGETS[j]) for i in range(6) for j in range(i + 1, 6)
            if np.array_equal(Y[:, i], Y[:, j])]
    for a, b in same:
        print(f"  ⚠️ {LABELS[a]} 와 {LABELS[b]} 는 전 행에서 값이 동일 — 모델이 구분할 수단이 없다")
    for i, t in enumerate(TARGETS):
        alone = int(((Y[:, i] > 10) & (np.delete(Y, i, axis=1) <= 10).all(axis=1)).sum())
        if alone == 0:
            print(f"  ⚠️ {LABELS[t]} 는 단독으로 등장한 적이 없다(항상 다른 항목과 함께)")


def section_accuracy(net, scale, saved_val: float, limit: int) -> None:
    rows = [r for r in csv.DictReader((ROOT / "data/manifests/skin_multitask_manifest.csv").open(encoding="utf-8"))
            if (ROOT / r["image_path"]).exists()]
    keys = [origin_key(r["image_path"]) for r in rows]
    print(f"\n── ② 정확도 (유효 {len(rows)}장 / 원본 {len(set(keys))}개) ──")
    print(f"  체크포인트 val_loss={saved_val:.5f} → RMSE {np.sqrt(saved_val) * 100:.1f}점")

    def run(name, subset):
        subset = subset[:limit]
        pred = predict_paths(net, scale, [ROOT / r["image_path"] for r in subset])
        true = np.array([[float(r[t]) for t in TARGETS] for r in subset], np.float32)
        mae = float(np.abs(pred - true).mean())
        base = float(np.abs(true - true.mean(0)).mean())
        print(f"  {name:<28} MAE {mae:>5.1f}   평균만찍기 {base:>5.1f}   비율 {mae / base:>4.2f}")

    _, val_img = train_test_split(rows, test_size=0.2, random_state=42)
    run("학습과 같은 분할(이미지)", val_img)
    _, val_keys = train_test_split(sorted(set(keys)), test_size=0.2, random_state=42)
    held = set(val_keys)
    run("원본 단위 분할(누수 차단)", [r for r, k in zip(rows, keys) if k in held])
    print("  * 비율 = 모델MAE / 평균만찍기MAE. 1에 가까울수록 배운 게 없다는 뜻.")


def section_repeatability(net, scale, photo_dir: Path) -> None:
    """같은 순간 연속 촬영본에 같은 점수를 주는가."""
    sessions: dict[str, list[Path]] = defaultdict(list)
    for p in sorted(photo_dir.glob("KakaoTalk_*.jpg")):
        m = SESSION_RE.match(p.name)
        if m:
            sessions[m.group(1)].append(p)
    sessions = {k: v for k, v in sessions.items() if len(v) >= 2}
    if not sessions:
        print("\n(연속 촬영 묶음을 찾지 못해 재현성 검사를 건너뜀)")
        return

    print(f"\n── ③ 재현성: 같은 순간 연속 촬영 {len(sessions)}세트 ──")
    print(f"  {'항목':<10}{'세트내 산포':>11}{'세트간 산포':>11}{'비율':>7}   판정")
    within, means = [], []
    for paths in sessions.values():
        pred = predict_paths(net, scale, paths)
        within.append(pred.std(axis=0))
        means.append(pred.mean(axis=0))
    within = np.array(within).mean(axis=0)
    between = np.array(means).std(axis=0)
    for i, t in enumerate(TARGETS):
        ratio = within[i] / between[i] if between[i] > 1e-6 else float("inf")
        verdict = "같은 사진끼리도 흔들림" if ratio >= 0.7 else ("주의" if ratio >= 0.4 else "안정")
        print(f"  {LABELS[t]:<10}{within[i]:>11.1f}{between[i]:>11.1f}{ratio:>7.2f}   {verdict}")
    print("  * 세트내 = 같은 순간 찍은 사진들 간 점수 산포(전부 노이즈여야 정상).")
    print("  * 세트간 = 다른 날 찍은 사진들 간 산포(피부 변화 + 촬영조건).")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=700)
    ap.add_argument("--photos", default="docs", help="연속 촬영 사진이 있는 폴더")
    args = ap.parse_args()

    net, scale, saved_val = load_model()
    section_labels()
    section_accuracy(net, scale, saved_val, args.limit)
    section_repeatability(net, scale, ROOT / args.photos)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
