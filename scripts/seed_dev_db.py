"""개발 DB 를 로컬 CSV 만으로 채운다. **운영 DB 에 접근하지 않는다.**

왜 이렇게 하나
--------------
개발/운영 DB 분리(2026-08-04 결정)를 하려면 개발 DB 에 카탈로그가 있어야 한다. 처음에는
운영에서 복사할 생각이었지만(scripts/clone_catalog_to_dev.py), 그러려면 운영 접속 정보가
필요하고 클라우드 개발 프로젝트도 하나 더 만들어야 했다.

카탈로그의 **원본 CSV 가 이미 저장소에 있다**(data/manifests/). 운영 DB 도 이 파일들로
만들어진 것이므로, 같은 로더를 로컬 Postgres 에 돌리면 된다. 계정도 비용도 운영 접근도
필요 없고, 개인정보가 개발 DB 로 새지도 않는다(CSV 에는 사용자 데이터가 없다).

사용
----
    docker compose up -d postgres
    python scripts/seed_dev_db.py                  # 전체
    python scripts/seed_dev_db.py --only catalog   # 일부만
    python scripts/seed_dev_db.py --list           # 무엇이 들어가는지만 보기
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 개발 Postgres(docker-compose.yml). 호스트에서 돌릴 때는 5433, 컨테이너 안에서는 5432.
DEV_DATABASE_URL = "postgresql+psycopg2://beautyai:beautyai@localhost:5433/beautyai"

# (이름, 스크립트, 인자, 원본 CSV, 추가 환경변수) — 원본이 없으면 건너뛰고 이유를 말한다.
#
# body 로더는 sqlite 가 아니면 전부 '원격'으로 보고 BODY_LOAD_CONFIRM 을 요구한다.
# 그 가드는 운영 사고를 막으려는 것이고, 여기서는 _refuse_if_not_dev 로 대상이 개발 DB 임을
# 이미 확인했으므로 이 단계에만 확인값을 넘긴다(전역으로 켜두면 가드가 무의미해진다).
STEPS: list[tuple[str, str, list[str], str, dict[str, str]]] = [
    ("catalog", "load_product_catalog_to_db.py", ["--limit", "4000"],
     "data/manifests/product_catalog_candidates.csv", {}),
    ("oliveyoung", "load_oliveyoung_to_db.py", [],
     "data/manifests/oy_recommendation_products.csv", {}),
    ("body", "load_body_catalog_to_db.py", [],
     "data/manifests/body_products.csv", {"BODY_LOAD_CONFIRM": "yes"}),
    ("matsukiyo", "load_matsukiyo_to_db.py", [],
     "data/manifests/matsukiyo_products.csv", {}),
]


def _refuse_if_not_dev(url: str) -> None:
    """개발 시드를 운영에 쏟아붓는 사고를 막는다.

    이 스크립트는 카탈로그를 **덮어쓴다**. DATABASE_URL 을 안 바꾸고 돌리는 실수가
    가장 흔한 사고 경로라, 운영 마커가 보이면 시작조차 하지 않는다.
    """
    sys.path.insert(0, str(ROOT / "backend"))
    from app.core.config import get_settings

    marker = get_settings().production_db_marker.strip()
    if marker and marker in url:
        raise SystemExit(
            "거부: DATABASE_URL 이 운영 DB 를 가리킵니다.\n"
            "  이 스크립트는 카탈로그를 덮어씁니다 — 개발 DB 에만 쓰세요.\n"
            f"  기본값을 쓰려면 --database-url 을 비우고 다시 실행하세요({DEV_DATABASE_URL})."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=DEV_DATABASE_URL, help="개발 DB 접속 문자열")
    parser.add_argument("--only", nargs="*", choices=[s[0] for s in STEPS], help="일부 단계만 실행")
    parser.add_argument("--list", action="store_true", help="실행하지 않고 계획만 출력")
    args = parser.parse_args()

    _refuse_if_not_dev(args.database_url)

    steps = [s for s in STEPS if not args.only or s[0] in args.only]
    print(f"개발 DB: {args.database_url}\n")

    plan = []
    for name, script, extra, source, step_env in steps:
        exists = (ROOT / source).exists()
        plan.append((name, script, extra, source, exists, step_env))
        mark = "O" if exists else "X"
        print(f"  [{mark}] {name:<12} ← {source}")
    print()

    if args.list:
        return 0

    missing = [p for p in plan if not p[4]]
    if missing:
        print("원본 CSV 가 없는 단계는 건너뜁니다. 크롤/빌드 스크립트로 먼저 만들어야 합니다:")
        for name, script, *_ in missing:
            print(f"  - {name}: scripts/{script} 의 --help 참고")
        print()

    # ⚠ 자식 프로세스에 개발 DB 를 넘긴다. 로더들은 app.core.database 를 임포트하는데,
    #   그 모듈은 **임포트 시점에** settings 로 엔진을 만든다 — 환경변수로만 바꿀 수 있다.
    env = {**os.environ, "DATABASE_URL": args.database_url, "APP_ENV": "local"}
    failed = []
    for name, script, extra, _source, exists, step_env in plan:
        if not exists:
            continue
        print(f"── {name} ──────────────────────────────")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), *extra],
            cwd=ROOT, env={**env, **step_env}, check=False,
        )
        if result.returncode != 0:
            failed.append(name)
            print(f"  !! {name} 실패(코드 {result.returncode}) — 계속 진행합니다")
        print()

    if failed:
        print(f"실패한 단계: {', '.join(failed)}")
        return 1
    print("완료. .env 의 DATABASE_URL 을 개발 DB 로 바꾸고 ALLOW_PRODUCTION_DB 줄을 지우세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
