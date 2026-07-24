"""RunPod 다인종 퍼스널컬러 학습용 self-contained 패키지를 로컬에서 조립한다.

하는 일:
  1) AI-Hub '글로벌 다인종 피부색 데이터'의 유효 이미지 zip을 풀어 512px 로 다운스케일
     → runpod_pc/data/aihub/<대륙>/<파일>.jpg  (19G → ~1-2G)
  2) 실측 라벨로 multiethnic_all.csv (image_path/fitzpatrick/ita_avg/continent) 생성
  3) 계절셋(Deep Armo + CapstoneA) 이미지도 512px 로 복사 + 매니페스트 상대경로로 재작성
  4) 학습 스크립트 + requirements + run_all.sh 동봉
  5) 최종 용량 출력 + tar 명령 안내

업로드는 이 폴더(runpod_pc)를 tar.gz 로 묶어서 한다(README_RUNPOD 참고).

Usage:
  python scripts/pack_runpod_pc.py                # 전체(AIHub+계절)
  python scripts/pack_runpod_pc.py --aihub-only   # Stage1 데이터만
  python scripts/pack_runpod_pc.py --max-side 384 # 더 작게
"""
from __future__ import annotations

import argparse
import csv
import io
import shutil
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/01.글로벌 다인종 피부색 데이터"
PKG = ROOT / "runpod_pc"
CONTINENTS = ["동북아시아", "동남아시아", "유럽권", "북미권", "남아시아권", "중동권", "기타"]
WORKERS = 8          # PIL JPEG 디코딩은 GIL 해제 → 스레드로 실제 병렬
BATCH = 128          # 동시에 메모리에 올릴 원본 바이트 수 (메모리 경계)


def _downscale_save(job):
    data, dest, max_side = job
    small = downscale_bytes(data, max_side)
    if small is None:
        return None
    Path(dest).write_bytes(small)
    return dest


def _run_batch(pool, jobs) -> int:
    return sum(1 for res in pool.map(_downscale_save, jobs) if res)


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


def region_of(zip_path: Path) -> str:
    for c in CONTINENTS:
        if c in zip_path.name:
            return c
    return "기타"


def pack_aihub(max_side: int) -> dict[str, str]:
    """유효 이미지 zip을 풀어 다운스케일. 반환: image_name -> 상대 image_path."""
    out_root = PKG / "data/aihub"
    img_zips = [z for z in DATASET.rglob("*.zip")
                if "원천데이터" in str(z) and (z.name.startswith("TS_") or z.name.startswith("VS_"))]
    name_to_rel: dict[str, str] = {}
    total = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for z in sorted(img_zips):
            if z.stat().st_size == 0:
                print(f"  [skip empty] {z.name}", flush=True)
                continue
            region = region_of(z)
            outdir = out_root / region
            outdir.mkdir(parents=True, exist_ok=True)
            try:
                zf = zipfile.ZipFile(z)
            except Exception as exc:  # noqa: BLE001
                print(f"  [skip bad] {z.name}: {exc}", flush=True)
                continue
            n = 0
            jobs = []
            with zf:  # ZipFile.read 는 단일 스레드(메인)에서만 — 디코딩만 병렬
                for entry in zf.namelist():
                    if not entry.lower().endswith((".jpg", ".jpeg", ".png")):
                        continue
                    base = Path(entry).name
                    jobs.append((zf.read(entry), str(outdir / base), max_side))
                    name_to_rel[base] = f"data/aihub/{region}/{base}"
                    if len(jobs) >= BATCH:
                        n += _run_batch(pool, jobs)
                        jobs = []
                if jobs:
                    n += _run_batch(pool, jobs)
            total += n
            print(f"  {z.name}: {n} imgs -> {region}", flush=True)
    print(f"AIHub images packed: {total}")
    return name_to_rel


def write_multiethnic(name_to_rel: dict[str, str]):
    src = ROOT / "data/manifests/aihub_skincolor_full_manifest.csv"
    if not src.exists():
        print("!! full manifest 없음 — 먼저 build_aihub_skincolor_manifest.py 실행", file=sys.stderr)
        return 0
    out = PKG / "data/manifests/multiethnic_all.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in csv.DictReader(src.open(encoding="utf-8-sig")):
        rel = name_to_rel.get(r["image_name"])
        if not rel:
            continue
        rows.append({"image_path": rel, "fitzpatrick": r["fitzpatrick"] or "2",
                     "ita_avg": r["ita_avg"], "continent": r["region"], "uid": r["uid"]})
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["image_path", "fitzpatrick", "ita_avg", "continent", "uid"])
        w.writeheader()
        w.writerows(rows)
    print(f"multiethnic_all.csv rows: {len(rows)} -> {out}")
    return len(rows)


def pack_season(max_side: int):
    """Deep Armo + CapstoneA + 한국 연예인 계절셋을 512px 로 복사하고 매니페스트를 상대경로로 재작성."""
    jobs = [
        ("data/manifests/personal_color_manifest.csv", "season", "season", "deeparmo"),
        ("data/eval/capstonea_train_manifest.csv", "label", "label", "capstonea"),
        ("data/manifests/korean_celebrity_face_crop_manifest.csv", "season", "season", "korean_celeb"),
    ]
    for mf_rel, label_col, out_label, tag in jobs:
        mf = ROOT / mf_rel
        if not mf.exists():
            print(f"  [skip] {mf_rel} 없음", flush=True)
            continue
        outdir = PKG / f"data/season/{tag}"
        outdir.mkdir(parents=True, exist_ok=True)
        rows_out = []
        n = 0

        def flush(jb, jr, pool):
            nonlocal n
            for res, row in zip(pool.map(_downscale_save, jb), jr):
                if res:
                    rows_out.append(row)
                    n += 1

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            job_bytes, job_rows = [], []
            for i, r in enumerate(csv.DictReader(mf.open(encoding="utf-8-sig"))):
                ip = r["image_path"]
                p = Path(ip)
                if not p.is_absolute():
                    p = ROOT / ip
                if not p.exists():
                    continue
                try:
                    data = p.read_bytes()
                except Exception:
                    continue
                base = f"{tag}_{i:06d}.jpg"
                row = {"image_path": f"data/season/{tag}/{base}", out_label: r.get(label_col, "")}
                if "partition" in r:
                    row["partition"] = r["partition"]
                job_bytes.append((data, str(outdir / base), max_side))
                job_rows.append(row)
                if len(job_bytes) >= BATCH:
                    flush(job_bytes, job_rows, pool)
                    job_bytes, job_rows = [], []
            if job_bytes:
                flush(job_bytes, job_rows, pool)
        if rows_out:
            outmf = PKG / f"data/manifests/{tag}_manifest.csv"
            outmf.parent.mkdir(parents=True, exist_ok=True)   # --season-only 는 Stage1 매니페스트 단계를 건너뛴다
            with outmf.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
                w.writeheader()
                w.writerows(rows_out)
            print(f"  {tag}: {n} imgs -> {outmf.name}")


def copy_support(season_only: bool = False):
    (PKG / "scripts").mkdir(parents=True, exist_ok=True)
    (PKG / "backend").mkdir(parents=True, exist_ok=True)
    for s in ["train_global_personal_color.py", "evaluate_personal_color_model.py"]:
        src = ROOT / "scripts" / s
        if src.exists():
            shutil.copy2(src, PKG / "scripts" / s)
    if season_only:
        # Stage1 을 건너뛰므로 사전학습된 다인종 백본을 동봉해야 한다(pod에서 --init 으로 씀).
        (PKG / "data/models").mkdir(parents=True, exist_ok=True)
        bb = ROOT / "data/models/backbone_multiethnic.pt"
        if bb.exists():
            shutil.copy2(bb, PKG / "data/models/backbone_multiethnic.pt")
            print(f"backbone 동봉: {bb.name} ({bb.stat().st_size/1e6:.0f} MB)")
        else:
            print("  [warn] backbone_multiethnic.pt 없음 — pod에서 Stage1 부터 돌려야 함")
    # 학습 전용 requirements
    (PKG / "backend/requirements-train.txt").write_text(
        "torch==2.7.1\ntorchvision==0.22.1\nnumpy==1.26.4\nPillow==10.4.0\nscikit-learn==1.6.1\n",
        encoding="utf-8",
    )
    if season_only:
        # Stage2 전용: 백본은 동봉본 재사용, 한국 연예인 셋을 실제로 투입하는 변형들.
        # CPU 실측(2026-07-17): 한국 1123장만으로 백본 풀면 7에폭에 loss 0.31 = 과적합.
        # → 유럽 볼륨(deeparmo 4920)을 반드시 같이 넣어 받쳐준다.
        KR = "data/manifests/deeparmo_manifest.csv,data/manifests/capstonea_manifest.csv,data/manifests/korean_celeb_manifest.csv"
        run = PKG / "run_season.sh"
        run.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            "# RunPod PyTorch 템플릿의 torch+CUDA 를 그대로 쓴다(venv 만들면 torch 2.5GB 재다운로드라 낭비).\n"
            "python -c 'import torch; print(\"cuda:\", torch.cuda.is_available(), torch.__version__)'\n"
            "python -c 'import PIL, numpy' 2>/dev/null || pip install -q pillow numpy\n"
            "mkdir -p data/models\n"
            "\n# A) 유럽+capstonea+한국연예인, 전체 파인튜닝 (메인 후보)\n"
            f"python scripts/train_global_personal_color.py --stage 2 \\\n"
            f"  --season-manifests {KR} \\\n"
            "  --init data/models/backbone_multiethnic.pt \\\n"
            "  --out data/models/pc_kr_all_ft.pt --epochs 30 --batch 64\n"
            "\n# B) A + 클래스 가중치\n"
            f"python scripts/train_global_personal_color.py --stage 2 \\\n"
            f"  --season-manifests {KR} \\\n"
            "  --init data/models/backbone_multiethnic.pt --class-weight \\\n"
            "  --out data/models/pc_kr_all_ft_cw.pt --epochs 30 --batch 64\n"
            "\n# C) 대조군: 백본 동결(헤드만)\n"
            f"python scripts/train_global_personal_color.py --stage 2 \\\n"
            f"  --season-manifests {KR} \\\n"
            "  --init data/models/backbone_multiethnic.pt --freeze-backbone \\\n"
            "  --out data/models/pc_kr_all_frozen.pt --epochs 40 --batch 128 --lr 1e-3\n"
            "\n# 회수용으로 모델 3개만 묶어둔다(웹 UI 로 이것만 내려받으면 됨)\n"
            "tar czf /workspace/pc_kr.tar.gz data/models/pc_kr_*.pt\n"
            "echo '=== 완료. /workspace/pc_kr.tar.gz 를 내려받으세요 ==='\n"
            "ls -lh /workspace/pc_kr.tar.gz\n",
            encoding="utf-8",
            newline="\n",   # Windows 기본 \r\n 이면 pod bash 가 'pipefail\r' 로 읽어 죽는다
        )
        print("support files copied (scripts, requirements-train.txt, run_season.sh)")
        return
    run = PKG / "run_all.sh"
    run.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "python -m venv .venv && source .venv/bin/activate\n"
        "python -m pip install --upgrade pip\n"
        "pip install -r backend/requirements-train.txt\n"
        "mkdir -p data/models\n"
        "python scripts/train_global_personal_color.py --stage 1 \\\n"
        "  --multiethnic data/manifests/multiethnic_all.csv \\\n"
        "  --out data/models/backbone_multiethnic.pt --epochs 20 --batch 64\n"
        "python scripts/train_global_personal_color.py --stage 2 \\\n"
        "  --season-manifests data/manifests/deeparmo_manifest.csv,data/manifests/capstonea_manifest.csv \\\n"
        "  --init data/models/backbone_multiethnic.pt \\\n"
        "  --out data/models/personal_color_global.pt --epochs 30 --batch 64\n",
        encoding="utf-8",
        newline="\n",   # 위와 동일 — 셸 스크립트는 LF 로 써야 pod 에서 돈다
    )
    print("support files copied (scripts, requirements-train.txt, run_all.sh)")


def dir_size_mb(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-side", type=int, default=512)
    ap.add_argument("--aihub-only", action="store_true")
    ap.add_argument("--season-only", action="store_true",
                    help="Stage1(19GB AIHub) 건너뛰고 계절셋만. 사전학습 백본을 동봉해 Stage2만 돌릴 때.")
    ap.add_argument("--clean", action="store_true", help="기존 runpod_pc 삭제 후 새로")
    args = ap.parse_args()

    if args.clean and PKG.exists():
        shutil.rmtree(PKG)
    PKG.mkdir(parents=True, exist_ok=True)

    if not args.season_only:
        print(f"== AIHub 이미지 다운스케일({args.max_side}px)+추출 ==")
        name_to_rel = pack_aihub(args.max_side)
        write_multiethnic(name_to_rel)
    if not args.aihub_only:
        print("== 계절셋(Deep Armo + CapstoneA + 한국연예인) 패키징 ==")
        pack_season(args.max_side)
    copy_support(season_only=args.season_only)

    print(f"\n패키지 준비 완료: {PKG}")
    print(f"총 용량: {dir_size_mb(PKG):.0f} MB")
    print("\n다음: tar 로 묶어 업로드")
    print(f'  tar czf runpod_pc.tar.gz -C "{ROOT}" runpod_pc')


if __name__ == "__main__":
    raise SystemExit(main())
