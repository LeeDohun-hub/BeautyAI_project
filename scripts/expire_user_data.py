"""보관 기간이 지난 개인정보를 지운다.

    python scripts/expire_user_data.py --dry-run      # 몇 건인지만 본다
    python scripts/expire_user_data.py                # 실제로 지운다
    python scripts/expire_user_data.py --days 180     # 기간을 임시로 다르게

⚠ **먼저 --dry-run 으로 확인하고 돌릴 것.** 지운 데이터는 복구되지 않는다.

왜 앱 부팅 때 자동으로 안 하나: 설정을 잘못 넣은 채 배포하면 그 순간 돌이킬 수 없다.
사람이 확인하고 돌리게 하고, 정기 실행은 cron 에 맡긴다.

    # 매일 새벽 4시 (서버 crontab)
    0 4 * * * cd /home/ubuntu/BeautyAI_project && \
      docker compose -p beautyai_project exec -T backend \
      python /app/../scripts/expire_user_data.py >> /var/log/expire_user_data.log 2>&1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.services.data_retention import count_expired, expire_old_data  # noqa: E402


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=settings.data_retention_days,
                        help=f"보관 일수(기본 {settings.data_retention_days}, 0 이면 아무것도 안 함)")
    parser.add_argument("--dry-run", action="store_true", help="세기만 하고 지우지 않는다")
    args = parser.parse_args()

    if args.days <= 0:
        print("보관 기간이 0 이라 아무것도 지우지 않습니다(DATA_RETENTION_DAYS).")
        return 0

    print(f"보관 기간: {args.days}일  ({'세기만' if args.dry_run else '실제 삭제'})")
    db = SessionLocal()
    try:
        counts = count_expired(db, args.days)
        total = sum(counts.values())
        for name, n in counts.items():
            print(f"  {name:<26} {n:>6,}건")
        print(f"  {'합계':<26} {total:>6,}건")

        if args.dry_run:
            print("\n--dry-run: 아무것도 지우지 않았습니다.")
            return 0
        if total == 0:
            print("\n지울 것이 없습니다.")
            return 0

        deleted = expire_old_data(db, args.days)
        print(f"\n삭제 완료: {sum(deleted.values()):,}건")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
