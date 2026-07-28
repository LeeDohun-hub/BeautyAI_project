"""네일 대체 데이터·모델 취득 — AI-Hub 04 미다운로드 구간을 메우는 공개 소스.

AI-Hub 04 는 손(hand) 전 파일과 발 학습라벨(TL_발)이 0바이트라 손 이미지도, 마스크 라벨도
없다. 아래 두 공개 자산이 그 자리를 대신한다(둘 다 CC BY 4.0 — 출처표기 조건, 상업 이용 가능).

  1) mnemic/nails_seg_yolov8 (HuggingFace) — 손톱 학습 YOLOv8 세그 모델. 학습 없이 네일 마스크.
  2) Roboflow "Personal Projects / nails_segmentation" — 손톱 이미지 + 인스턴스 세그 라벨.
     (1)의 학습 원본이므로 이 데이터로 (1)을 평가하면 누수다. 용도는 손 이미지 확보와 마스크 라벨.

Usage:
    python scripts/fetch_nail_reference_data.py                 # 모델 + 데이터셋
    python scripts/fetch_nail_reference_data.py --model-only
    python scripts/fetch_nail_reference_data.py --version 51 --format yolov8
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = PROJECT_ROOT / "data" / "models"
DATA_DIR = PROJECT_ROOT / "data" / "nail_reference"

HF_REPO = "mnemic/nails_seg_yolov8"
HF_FILE = "nails_seg_s_yolov8_v1.pt"

RF_WORKSPACE = "personal-projects-jfbag"
RF_PROJECT = "nails_segmentation"

ATTRIBUTION = """\
출처표기(CC BY 4.0):
  - Model: mnemic/nails_seg_yolov8 — https://huggingface.co/mnemic/nails_seg_yolov8
  - Data : Personal Projects, "nails_segmentation", Roboflow Universe
           https://universe.roboflow.com/personal-projects-jfbag/nails_segmentation
"""


def load_env() -> dict:
    env = dict(os.environ)
    path = PROJECT_ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def fetch_model() -> Path:
    dest = MODELS_DIR / HF_FILE
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[모델] 이미 있음: {dest.relative_to(PROJECT_ROOT)} ({dest.stat().st_size/1048576:.1f} MB)")
        return dest
    from huggingface_hub import hf_hub_download

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    cached = hf_hub_download(HF_REPO, HF_FILE)
    shutil.copy(cached, dest)
    print(f"[모델] 받음: {dest.relative_to(PROJECT_ROOT)} ({dest.stat().st_size/1048576:.1f} MB)")
    return dest


def _api(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode())


def fetch_dataset(version: int, fmt: str, env: dict) -> Path | None:
    key = env.get("ROBOFLOW_API_KEY")
    if not key:
        print("[데이터] ROBOFLOW_API_KEY 없음 — 건너뜀", file=sys.stderr)
        return None

    out_dir = DATA_DIR / f"{RF_PROJECT}_v{version}_{fmt}"
    if (out_dir / "data.yaml").exists() or any(out_dir.glob("*/")):
        print(f"[데이터] 이미 있음: {out_dir.relative_to(PROJECT_ROOT)}")
        return out_dir

    q = urllib.parse.urlencode({"api_key": key})
    meta = _api(f"https://api.roboflow.com/{RF_WORKSPACE}/{RF_PROJECT}/{version}/{fmt}?{q}")
    export = meta.get("export", {})
    link = export.get("link")
    if not link:
        print(f"[데이터] export 링크 없음: {json.dumps(meta)[:300]}", file=sys.stderr)
        return None

    print(f"[데이터] 내려받는 중 ~{export.get('size', 0):.0f} MB · splits={meta.get('version', {}).get('splits')}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DATA_DIR / f"{RF_PROJECT}_v{version}_{fmt}.zip"
    urllib.request.urlretrieve(link, zip_path)
    print(f"[데이터] zip: {zip_path.name} ({zip_path.stat().st_size/1048576:.1f} MB)")

    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out_dir)
    zip_path.unlink()
    print(f"[데이터] 추출: {out_dir.relative_to(PROJECT_ROOT)}")
    return out_dir


def summarize(out_dir: Path) -> None:
    imgs = [p for p in out_dir.rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
    labels = [p for p in out_dir.rglob("*.txt") if p.parent.name == "labels"]
    total = sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
    print(f"\n[요약] 이미지 {len(imgs)}장 · 라벨 {len(labels)}개 · {total/1048576:.1f} MB")
    for split in ("train", "valid", "test"):
        n = len([p for p in imgs if split in p.parts])
        if n:
            print(f"        {split}: {n}장")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", type=int, default=51)
    ap.add_argument("--format", default="yolov8")
    ap.add_argument("--model-only", action="store_true")
    ap.add_argument("--data-only", action="store_true")
    args = ap.parse_args()

    if not args.data_only:
        fetch_model()
    if not args.model_only:
        out = fetch_dataset(args.version, args.format, load_env())
        if out:
            summarize(out)

    print("\n" + ATTRIBUTION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
