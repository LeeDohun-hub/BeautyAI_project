"""런타임 번들을 만들고 S3 에 올린다 — 자동배포가 집어 갈 자리에.

왜 따로 있나: CD 는 `dist/runtime_data` 를 **S3 에서** 받아 이미지에 굽는다
(`.github/workflows/deploy.yml`). 번들의 원천인 `data/`(18GB)와 `dist/` 는 .gitignore 라
러너가 체크아웃만으로는 가질 수 없기 때문이다.

그래서 이 파이프라인의 유일한 조용한 실패 모드는 **"모델·매니페스트를 바꿨는데 S3 재업로드를
잊는 것"** 이다. 코드는 정상 배포되는데 데이터만 옛것이라, 에러 없이 커버리지만 떨어진다
(이 프로젝트에서 같은 부류로 두 번 당했다 — docs/CD_SETUP.md 참고).
빌드와 업로드를 한 명령으로 묶어 그 틈을 없앤다.

Usage:
    python scripts/publish_runtime_bundle.py                      # 빌드 + 업로드
    python scripts/publish_runtime_bundle.py --skip-build         # 이미 만든 번들만 업로드
    python scripts/publish_runtime_bundle.py --dry-run            # 무엇이 바뀌는지만 확인
    python scripts/publish_runtime_bundle.py --uri s3://버킷/runtime_data

대상 URI 는 --uri > 환경변수 RUNTIME_BUNDLE_S3_URI 순으로 정한다. GitHub Secret
`RUNTIME_BUNDLE_S3_URI` 와 **같은 값**이어야 배포가 같은 번들을 집는다.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = PROJECT_ROOT / "dist" / "runtime_data"

# Dockerfile.prod 의 빌드 가드와 같은 검사. 여기서 먼저 걸리면 원인이 명확하다
# (러너에서 걸리면 로그를 뒤져야 한다).
REQUIRED = (
    Path("models"),
    Path("manifests"),
    Path("manifests/amazon_dead_asins.txt"),
    Path("manifests/amazon_asin_status.json"),
)


def _run(cmd: list[str], hint: str = "") -> None:
    """실패하면 파이썬 트레이스백 대신 한 줄로 끝낸다 — 원인이 대개 자격증명/권한이라
    스택은 아무 정보도 주지 않는다."""
    print("+", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"실패(exit {exc.returncode}): {cmd[0]}" + (f"\n{hint}" if hint else ""))


def _aws() -> str:
    """aws 실행 파일. winget 설치본이 PATH 에 아직 안 잡히는 경우가 잦아 기본 경로도 본다."""
    found = shutil.which("aws")
    if found:
        return found
    fallback = Path(r"C:\Program Files\Amazon\AWSCLIV2\aws.exe")
    if fallback.exists():
        return str(fallback)
    sys.exit("aws CLI 를 찾을 수 없습니다. `winget install Amazon.AWSCLI` 후 새 터미널에서 다시 실행하세요.")


def _verify() -> None:
    missing = [str(rel) for rel in REQUIRED if not (BUNDLE_DIR / rel).exists()]
    if missing:
        sys.exit(f"번들이 불완전합니다(누락: {', '.join(missing)}). --skip-build 를 뺐는지 확인하세요.")
    files = [p for p in BUNDLE_DIR.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    newest = max(files, key=lambda p: p.stat().st_mtime)
    stamp = datetime.fromtimestamp(newest.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    manifests = sorted((BUNDLE_DIR / "manifests").iterdir())
    print(f"번들 {total / 1024 / 1024:,.1f} MB · 파일 {len(files)}개 · 매니페스트 {len(manifests)}개")
    print(f"가장 최근 파일: {newest.relative_to(BUNDLE_DIR)} ({stamp})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uri", default=os.environ.get("RUNTIME_BUNDLE_S3_URI", ""),
                        help="s3://버킷/경로 (기본: 환경변수 RUNTIME_BUNDLE_S3_URI)")
    parser.add_argument("--skip-build", action="store_true", help="dist/runtime_data 를 다시 만들지 않는다")
    parser.add_argument("--dry-run", action="store_true", help="업로드하지 않고 변경될 목록만 본다")
    args = parser.parse_args()

    if not args.uri:
        sys.exit("대상 S3 URI 가 없습니다. --uri s3://버킷/runtime_data 또는 환경변수 RUNTIME_BUNDLE_S3_URI 를 주세요.")
    if not args.uri.startswith("s3://"):
        sys.exit(f"S3 URI 형식이 아닙니다: {args.uri}")

    if not args.skip_build:
        _run([sys.executable, str(PROJECT_ROOT / "scripts" / "build_runtime_bundle.py")],
             hint="번들 빌드가 실패했습니다 — data/ 에 모델·매니페스트가 있는지 확인하세요.")
    _verify()

    # --delete: 로컬에서 사라진 파일은 S3 에서도 지운다. 안 그러면 옛 모델이 버킷에 남아
    # 이미지에 같이 실린다(용량만 늘고 무엇이 쓰이는지 헷갈린다).
    cmd = [_aws(), "s3", "sync", str(BUNDLE_DIR), args.uri.rstrip("/"), "--delete"]
    if args.dry_run:
        cmd.append("--dryrun")
    _run(cmd, hint="자격증명이 없으면 `aws configure` 로 먼저 설정하세요(S3 쓰기 권한 필요).")

    if args.dry_run:
        print("\n(dry-run) 실제 업로드는 --dry-run 없이 다시 실행하세요.")
    else:
        print(f"\n완료 — 다음 배포부터 이 번들이 이미지에 실립니다: {args.uri}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
