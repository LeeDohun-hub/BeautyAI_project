"""런타임 번들을 만들어 **AI 서버로 올린다**.

왜 따로 있나: 자동배포(`.github/workflows/deploy.yml`)는 저장소 소스만 서버에 반영한다.
`dist/runtime_data`(모델·매니페스트 373MB)는 원천인 `data/`(18GB)와 함께 .gitignore 라
**git 을 타지 않는다.**

그래서 이 파이프라인의 유일한 조용한 실패 모드는 **"모델·매니페스트를 바꿨는데 서버에
안 올리는 것"** 이다. 코드는 정상 배포되는데 데이터만 옛것이라, 에러 없이 커버리지만
떨어진다(이 프로젝트에서 같은 부류로 두 번 당했다 — docs/CD_SETUP.md 참고).
빌드와 업로드를 한 명령으로 묶어 그 틈을 없앤다.

Usage:
    python scripts/publish_runtime_bundle.py                 # 빌드 + 서버 업로드
    python scripts/publish_runtime_bundle.py --dry-run       # 무엇이 바뀌는지만 확인
    python scripts/publish_runtime_bundle.py --skip-build    # 이미 만든 번들만 업로드
    python scripts/publish_runtime_bundle.py --s3 s3://버킷/runtime_data   # S3 로 보낼 때

업로드 후 서버가 그 번들을 쓰려면 **재배포가 필요하다**(이미지에 COPY 되므로).
GitHub Actions 탭에서 `Deploy AI` 를 수동 실행하거나, 다음 push 때 자동 반영된다.
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

DEFAULT_HOST = "ubuntu@ai.yopalette.com"
DEFAULT_KEY = PROJECT_ROOT.parent / "YoPalAI.pem"
DEFAULT_REMOTE_DIR = "/home/ubuntu/BeautyAI_project/dist/runtime_data"

# Dockerfile.prod 의 빌드 가드와 같은 검사. 여기서 먼저 걸리면 원인이 명확하다
# (배포 중에 걸리면 Actions 로그를 뒤져야 한다).
REQUIRED = (
    Path("models"),
    Path("manifests"),
    Path("manifests/amazon_dead_asins.txt"),
    Path("manifests/amazon_asin_status.json"),
)


def _run(cmd: list[str], hint: str = "") -> None:
    """실패하면 파이썬 트레이스백 대신 한 줄로 끝낸다 — 원인이 대개 자격증명/경로라
    스택은 아무 정보도 주지 않는다."""
    print("+", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        sys.exit(f"실행 파일을 찾을 수 없습니다: {cmd[0]}" + (f"\n{hint}" if hint else ""))
    except subprocess.CalledProcessError as exc:
        sys.exit(f"실패(exit {exc.returncode}): {cmd[0]}" + (f"\n{hint}" if hint else ""))


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
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"업로드 대상 (기본: {DEFAULT_HOST})")
    parser.add_argument("--key", default=str(DEFAULT_KEY), help="SSH 키 경로")
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR, help="서버의 번들 경로")
    parser.add_argument("--s3", default=os.environ.get("RUNTIME_BUNDLE_S3_URI", ""),
                        help="S3 로 보낼 때만 (s3://버킷/경로). 주면 서버 대신 S3 로 간다.")
    parser.add_argument("--skip-build", action="store_true", help="dist/runtime_data 를 다시 만들지 않는다")
    parser.add_argument("--dry-run", action="store_true", help="전송하지 않고 변경될 목록만 본다")
    args = parser.parse_args()

    if not args.skip_build:
        _run([sys.executable, str(PROJECT_ROOT / "scripts" / "build_runtime_bundle.py")],
             hint="번들 빌드 실패 — data/ 에 모델·매니페스트가 있는지 확인하세요.")
    _verify()

    if args.s3:
        if not args.s3.startswith("s3://"):
            sys.exit(f"S3 URI 형식이 아닙니다: {args.s3}")
        aws = shutil.which("aws") or r"C:\Program Files\Amazon\AWSCLIV2\aws.exe"
        cmd = [aws, "s3", "sync", str(BUNDLE_DIR), args.s3.rstrip("/"), "--delete"]
        if args.dry_run:
            cmd.append("--dryrun")
        _run(cmd, hint="`aws configure` 로 자격증명을 먼저 설정하세요(S3 쓰기 권한 필요).")
        target = args.s3
    else:
        if not Path(args.key).exists():
            sys.exit(f"SSH 키가 없습니다: {args.key}  (--key 로 지정하세요)")
        # rsync 대신 scp 를 쓴다 — Windows 기본 OpenSSH 에 rsync 가 없다.
        # -r 은 디렉터리 통째. 변경분만 보내지 못해 매번 373MB 를 올리므로,
        # --dry-run 으로 먼저 필요 여부를 확인하는 습관이 낫다.
        if args.dry_run:
            print(f"\n(dry-run) 다음을 전송하게 됩니다:\n  {BUNDLE_DIR}  →  {args.host}:{args.remote_dir}")
            return 0
        parent = args.remote_dir.rsplit("/", 1)[0]
        _run(["ssh", "-i", args.key, "-o", "StrictHostKeyChecking=accept-new",
              args.host, f"mkdir -p {parent}"],
             hint="서버에 접속하지 못했습니다. 키 경로와 호스트를 확인하세요.")
        _run(["scp", "-i", args.key, "-o", "StrictHostKeyChecking=accept-new", "-r",
              str(BUNDLE_DIR), f"{args.host}:{parent}/"])
        target = f"{args.host}:{args.remote_dir}"

    print(f"\n완료 → {target}")
    print("⚠ 서버가 새 번들을 쓰려면 **재배포가 필요하다**(이미지에 COPY 되므로).")
    print("  GitHub Actions 탭 → Deploy AI → Run workflow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
