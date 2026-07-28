"""AI-Hub 04(네일·페디큐어) 데이터셋 실태 검사 — 다운로드 후 원격에서 실행.

전체 추출 없이 zip 내부만 읽어(메모리 절약) 라벨 포맷·택소노미·규모를 파악하고
`docs/nail_dataset_inspection_report.md` 로 리포트를 쓴다. 이 리포트를 로컬로 가져오면
후속 파이프라인(build_nail_design_dataset.py)을 설계한다.

Usage:
    python scripts/inspect_nail_dataset.py
    python scripts/inspect_nail_dataset.py --root "data/04.네일 및 페디큐어 데이터"
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT_ROOT / "data" / "04.네일 및 페디큐어 데이터"
REPORT = PROJECT_ROOT / "docs" / "nail_dataset_inspection_report.md"

# 네일 '디자인' 트랙만 본다(손발포즈×피부톤 트랙은 별개·초대용량이라 제외).
DESIGN_ONLY = ("디자인데이터", "디자인_", "_디자인")


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name and not name.endswith("/") else "dir"


def _safe_zip(path: Path):
    try:
        return zipfile.ZipFile(path)
    except Exception as exc:  # 0바이트/손상 zip
        return exc


def _dump_structured(zf: zipfile.ZipFile, member: str, out: list[str]) -> None:
    """json/csv 라벨의 스키마·택소노미(범주 고유값)를 추출한다."""
    raw = zf.read(member)
    if member.lower().endswith(".json"):
        try:
            d = json.loads(raw.decode("utf-8", "ignore"))
        except Exception as exc:
            out.append(f"    - json 파싱 실패: {exc}")
            return
        out.append(f"    - json 최상위 타입: {type(d).__name__}")
        sample = d[0] if isinstance(d, list) and d else d
        if isinstance(sample, dict):
            out.append(f"    - 키: {list(sample.keys())}")
            out.append(f"    - 샘플: {json.dumps(sample, ensure_ascii=False)[:600]}")
    elif member.lower().endswith(".csv"):
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8", "ignore"))))
        if rows:
            out.append(f"    - csv 헤더: {rows[0]}")
            if len(rows) > 1:
                out.append(f"    - 샘플행: {rows[1]}")


def inspect_zip(path: Path, out: list[str]) -> None:
    size = path.stat().st_size if path.exists() else 0
    out.append(f"\n### {path.name}  ({size/1048576:.2f} MB)")
    if size == 0:
        out.append("  - ⚠️ 0바이트 — 미다운로드/미전송.")
        return
    zf = _safe_zip(path)
    if not isinstance(zf, zipfile.ZipFile):
        out.append(f"  - ⚠️ zip 아님/손상: {zf}")
        return
    names = [n for n in zf.namelist() if not n.endswith("/")]
    exts = Counter(_ext(n) for n in names)
    out.append(f"  - 엔트리 {len(names)}개 · 확장자 {dict(exts)}")
    out.append(f"  - 샘플 경로: {names[:4]}")

    # 디자인ID(D#####)와 디자인당 파일 수 분포(텍스처/RGB 구조 파악용)
    import re
    ids = [m.group(1) for n in names if (m := re.search(r"(D\d+)", n))]
    if ids:
        per = Counter(ids)
        out.append(f"  - 디자인ID(D#####) 수: {len(set(ids))} · 디자인당 파일 중앙값≈{sorted(per.values())[len(per)//2]}")

    # 구조화 라벨(json/csv)이 있으면 스키마·택소노미 덤프 — '범주 라벨' 유무 판정 핵심
    structured = [n for n in names if n.lower().endswith((".json", ".csv"))][:1]
    for member in structured:
        out.append(f"  - 구조화 라벨 발견: {member}")
        _dump_structured(zf, member, out)
    if not structured and exts:
        top = exts.most_common(1)[0][0]
        if top in ("png", "jpg", "jpeg"):
            out.append("  - (구조화 라벨 없음 — 이미지/마스크만. 범주 라벨은 메타데이터 zip 확인 필요)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--all", action="store_true", help="손발포즈(피부톤) 트랙까지 전부 검사")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"경로 없음: {root}")
        return 1

    zips = sorted(root.rglob("*.zip"))
    if not args.all:
        zips = [z for z in zips if any(tag in z.name for tag in DESIGN_ONLY)]

    out: list[str] = []
    out.append("# AI-Hub 04(네일·페디큐어) 데이터셋 검사 리포트")
    out.append(f"\n생성 스크립트: `scripts/inspect_nail_dataset.py` · 대상: `{root}`")
    out.append(f"\n검사 대상 zip {len(zips)}개 (디자인 트랙만; 손발포즈는 --all 로 포함)\n")

    present = [z for z in zips if z.stat().st_size > 0]
    empty = [z for z in zips if z.stat().st_size == 0]
    out.append(f"- 존재(>0B): {len(present)}개 · 0바이트(미전송): {len(empty)}개")
    out.append(f"- 총 용량: {sum(z.stat().st_size for z in present)/1073741824:.2f} GB")

    for z in zips:
        inspect_zip(z, out)

    out.append("\n---\n## 판정 체크리스트 (이 리포트로 확인할 것)")
    out.append("1. 메타데이터_디자인데이터_손/발 안에 **범주(디자인 카테고리) 라벨**이 있는가? (json/csv 스키마 위 참고)")
    out.append("2. TL/VL_디자인 라벨은 텍스처 PNG인가, 세그멘테이션 마스크인가, 좌표(json)인가?")
    out.append("3. 손/발 각각 디자인ID 수·디자인당 텍스처 수 → 리트리벌 라이브러리 규모 산정.")
    out.append("4. RGB 원천(TS/VS) 해상도·네일 크롭 가능성(디자인당 RGB 1장인지).")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n\n[리포트 저장] {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
