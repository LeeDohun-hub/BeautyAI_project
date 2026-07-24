"""AI-Hub 퍼스널컬러(조명 불변 Lab 회귀) 학습 패키지 → RunPod.

로컬 CPU 로는 비현실적이라(실측: 병렬도 1.2x, 1에폭 30분대 → 30에폭 15시간+) GPU 로 보낸다.
이미 224 로 다운스케일해 둔 aihub_pc 이미지와 매니페스트, 학습 스크립트만 담는다.

Usage:
  python scripts/pack_runpod_aihub.py --max-side 256
  tar czf ../runpod_aihub.tar.gz -C . runpod_aihub
"""
from __future__ import annotations

import argparse
import csv
import io
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "runpod_aihub"
# v2: 부위별 실측 Lab 이 붙은 매니페스트. 5000lux 는 학습 스크립트가 걸러낸다.
MANIFEST = ROOT / "data" / "manifests" / "aihub_pc_sites_manifest.csv"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-side", type=int, default=256,
                    help="학습이 224 로 리사이즈하므로 256 이면 충분. 업로드 크기를 줄인다.")
    ap.add_argument("--clean", action="store_true")
    args = ap.parse_args()

    if args.clean and PKG.exists():
        shutil.rmtree(PKG)
    (PKG / "data/datasets/aihub_pc").mkdir(parents=True, exist_ok=True)
    (PKG / "data/manifests").mkdir(parents=True, exist_ok=True)
    (PKG / "scripts").mkdir(parents=True, exist_ok=True)

    # v3 는 4조명 전부를 쓴다 — 5000lux 는 피부가 포화된 손상 입력이지만 **조명 다양성**을 제공해
    # 불변성 학습에 기여한다(v2 실측: 빼니 일치도 85.3→79.1% 하락). 그래서 전부 담는다.
    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    print(f"이미지 {len(rows)}장 다운스케일({args.max_side}px) 중... (4조명 전부)")

    def work(r: dict) -> bool:
        src = ROOT / r["image_path"]
        if not src.exists():
            return False
        im = Image.open(src).convert("RGB")
        im.thumbnail((args.max_side, args.max_side))
        im.save(PKG / r["image_path"], quality=92)
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        ok = sum(1 for r in pool.map(work, rows) if r)
    print(f"  {ok}/{len(rows)}장 복사")

    shutil.copy2(MANIFEST, PKG / "data/manifests/aihub_pc_sites_manifest.csv")
    shutil.copy2(ROOT / "scripts/train_aihub_pc_v2.py", PKG / "scripts/train_aihub_pc_v2.py")
    shutil.copy2(ROOT / "scripts/train_aihub_pc_v4.py", PKG / "scripts/train_aihub_pc_v4.py")

    (PKG / "requirements-train.txt").write_text(
        "torch==2.7.1\ntorchvision==0.22.1\nnumpy==1.26.4\nPillow==10.4.0\n",
        encoding="utf-8", newline="\n",
    )
    (PKG / "run.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "# RunPod PyTorch 템플릿의 torch+CUDA 를 그대로 쓴다(venv 파면 torch 2.5GB 재다운로드).\n"
        "python -c 'import torch; print(\"cuda:\", torch.cuda.is_available(), torch.__version__)'\n"
        "python -c 'import PIL, numpy' 2>/dev/null || pip install -q pillow numpy\n"
        "mkdir -p data/models\n"
        "\n"
        "# ── v4 A/B: '정확도에 기여하지 않는 축(a)에 학습 용량을 쓰지 말자' 가설 검증 ──\n"
        "# 실측 진단: 계절 규칙은 L·b 만 쓴다. val 에서 a 오차를 0 으로 만들어도 정확도 55.4%→55.4%\n"
        "#            (변화 0). 반면 L·b 오차 절반이면 81.0%. 그런데 타깃 9차원 중 3개가 a 다.\n"
        "# 세 설정을 같은 split(seed 42)으로 돌려 비교한다. 기준: v1 55.0% / v2 58.9% / v3+TTA 57.6%\n"
        "\n"
        "echo '=== [1/3] 대조군: a-weight 1.0 (기존 v3 와 동일 조건) ==='\n"
        "python -u scripts/train_aihub_pc_v4.py --target lab --a-weight 1.0 --lux all \\\n"
        "  --epochs 30 --batch 64 --lr 3e-4 --out data/models/v4_lab_a1.pt 2>&1 | tee train_a1.log\n"
        "\n"
        "echo '=== [2/3] 실험 A: a-weight 0.2 (a 축 용량 회수) ==='\n"
        "python -u scripts/train_aihub_pc_v4.py --target lab --a-weight 0.2 --lux all \\\n"
        "  --epochs 30 --batch 64 --lr 3e-4 --out data/models/v4_lab_a02.pt 2>&1 | tee train_a02.log\n"
        "\n"
        "echo '=== [3/3] 실험 B: decision (ITA·언더톤잔차 2차원 직접 회귀) ==='\n"
        "python -u scripts/train_aihub_pc_v4.py --target decision --lux all \\\n"
        "  --epochs 30 --batch 64 --lr 3e-4 --out data/models/v4_decision.pt 2>&1 | tee train_dec.log\n"
        "\n"
        "echo; echo '================ 최종 비교 ================'\n"
        "grep -h '최고 val' train_a1.log train_a02.log train_dec.log || true\n"
        "\n"
        "tar czf /workspace/aihub_pc_v4_out.tar.gz data/models/v4_*.pt train_a1.log train_a02.log train_dec.log\n"
        "echo '=== 완료. /workspace/aihub_pc_v4_out.tar.gz 내려받으세요 ==='\n"
        "ls -lh /workspace/aihub_pc_v4_out.tar.gz\n",
        encoding="utf-8", newline="\n",
    )
    size = sum(f.stat().st_size for f in PKG.rglob("*") if f.is_file()) / 1e6
    print(f"\n패키지: {PKG}  ({size:.0f} MB)")
    print(f'  tar czf "{ROOT.parent}/runpod_aihub.tar.gz" -C "{ROOT}" runpod_aihub')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
