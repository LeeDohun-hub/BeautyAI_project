"""배포용 런타임 데이터 번들 — data/ 에서 **실제로 서빙에 필요한 것만** 추린다.

`data/` 는 학습 데이터·실험 산출물까지 합쳐 15GB 가 넘는데, 서빙에 필요한 건 모델 7개와
RAG 지식파일뿐이다. 로컬 compose 는 `./data:/data` 를 통째로 마운트해서 넘어갔지만,
클라우드에는 그 볼륨이 없으므로 슬림 번들을 만들어 이미지에 굽거나 오브젝트 스토리지에 올린다.

**경로는 config 에서 읽는다.** 목록을 여기 하드코딩하면 config 가 바뀔 때 조용히 어긋난다
(예: skin 모델이 aihub03 으로 교체된 이력). 빠진 파일이 있으면 실패로 알려준다.

Usage:
    python scripts/build_runtime_bundle.py                 # dist/runtime_data/ 생성
    python scripts/build_runtime_bundle.py --tar           # + runtime_data.tar.gz
    python scripts/build_runtime_bundle.py --out /tmp/rd
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def collect_optional() -> list[Path]:
    """없어도 앱이 뜨는 자산 — 네일 디자인 기능은 빠지면 feature_available=False 로 비활성된다.

    인덱스가 77MB 라 항상 싣지는 않는다. 필수(collect)와 달리 없어도 실패시키지 않는다.
    """
    from app.core.config import get_settings

    s = get_settings()
    out = []
    for rel in (s.nail_seg_model_path, s.nail_embedder_model_path, s.nail_index_dir):
        p = Path(rel)
        out.append((p if p.is_absolute() else PROJECT_ROOT / p).resolve())
    return out


def collect() -> list[Path]:
    """config 가 참조하는 런타임 자산 경로(중복 제거, 존재 여부는 호출측에서 판정)."""
    from app.core.config import get_settings

    s = get_settings()
    paths: list[str] = [
        s.resolved_skin_model_path,
        s.resolved_body_skin_model_path,
        s.resolved_personal_color_model_path,
        s.resolved_derma_tier1_model_path,
        s.resolved_derma_tier2_model_path,
        *s.resolved_aihub_pc_ensemble_paths,
        s.resolved_aihub_pc_model_path,
    ]
    # RAG·지식 파일은 상대경로 그대로라 project_root 기준으로 푼다.
    # settings.chroma_path 는 제외한다 — 앱 어디서도 chromadb 를 import 하지 않는 죽은 설정이고
    # 가리키는 디렉터리도 존재하지 않는다(RAG 는 아래 jsonl 파일로 동작한다).
    for rel in (s.problem_skin_knowledge_path,
                s.skincare_ingredient_knowledge_path, s.otc_drug_knowledge_path):
        p = Path(rel)
        paths.append(str(p if p.is_absolute() else PROJECT_ROOT / p))

    seen: dict[str, Path] = {}
    for raw in paths:
        p = Path(raw).resolve()
        seen.setdefault(str(p), p)
    return list(seen.values())


def build(out_dir: Path, make_tar: bool, with_nail: bool) -> int:
    data_root = (PROJECT_ROOT / "data").resolve()
    assets = collect()

    missing = [p for p in assets if not p.exists()]
    present = [p for p in assets if p.exists()]

    skipped_optional: list[Path] = []
    if with_nail:
        for p in collect_optional():
            (present if p.exists() else skipped_optional).append(p)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    total = 0
    print(f"{'크기':>10}  경로")
    for src in present:
        try:
            rel = src.relative_to(data_root)
        except ValueError:
            print(f"  건너뜀(data/ 밖): {src}", file=sys.stderr)
            continue
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
        size = _size(src)
        total += size
        print(f"{size/1048576:>9.1f}M  {rel}")

    print(f"\n합계 {total/1048576:.1f} MB → {out_dir}")
    full = _size(data_root)
    print(f"(원본 data/ 는 {full/1073741824:.1f} GB — {total/full*100:.2f}% 만 담았다)")

    if make_tar:
        tar_path = out_dir.with_suffix(".tar.gz")
        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(out_dir, arcname=".")
        print(f"tar: {tar_path} ({_size(tar_path)/1048576:.1f} MB)")

    if skipped_optional:
        print("\n(선택) 없어서 건너뛴 네일 디자인 자산 — 기능은 비활성으로 응답한다:")
        for p in skipped_optional:
            print(f"   {p}")

    if missing:
        print("\n⚠️ config 가 가리키는데 없는 파일:", file=sys.stderr)
        for p in missing:
            print(f"   {p}", file=sys.stderr)
        print("이 상태로 배포하면 해당 기능이 휴리스틱 폴백으로 조용히 떨어진다.", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "dist" / "runtime_data")
    ap.add_argument("--tar", action="store_true", help="tar.gz 도 함께 만든다")
    ap.add_argument("--no-nail", action="store_true",
                    help="네일 디자인 자산(인덱스 77MB 포함)을 빼고 만든다")
    args = ap.parse_args()
    return build(args.out.resolve(), args.tar, with_nail=not args.no_nail)


if __name__ == "__main__":
    raise SystemExit(main())
