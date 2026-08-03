"""이미 저장된 `skin_analyses.image_name` 의 원본 파일명을 확장자만 남기고 지운다.

왜: 이 컬럼에는 업로드 파일명이 그대로 들어가 있었다. 파일명에는 이름·날짜·기기·장소가
들어가는 일이 흔한데(예: "2026-08-03 김OO 병원상담.jpg"), **코드 어디서도 읽지 않으면서**
user_id 와 묶여 무기한 남아 있었다(개인정보 점검 2026-08-03). 수집 자체를 멈추는 건
routes.py 에서 처리했고, 이 스크립트는 **이미 쌓인 것**을 정리한다.

분석 점수는 건드리지 않는다 — 지우는 건 파일명뿐이다.

Usage:
    python scripts/scrub_image_names.py --dry-run     # 무엇이 바뀔지만 본다
    python scripts/scrub_image_names.py               # 실제 정리
    python scripts/scrub_image_names.py --database-url postgresql://...

기본 DB 는 설정(DATABASE_URL)을 따른다. **운영 DB 를 물 수 있으니 --dry-run 을 먼저.**
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="바꾸지 않고 대상만 센다")
    parser.add_argument("--database-url", default="", help="비우면 설정값(DATABASE_URL)을 쓴다")
    args = parser.parse_args()

    from sqlalchemy import create_engine, func, select, update
    from sqlalchemy.orm import Session

    from app.core.config import get_settings
    from app.models import SkinAnalysis

    url = args.database_url or get_settings().database_url
    # 어느 DB 를 만지는지 반드시 보여준다(운영/로컬 착각 방지). 자격증명은 가린다.
    shown = url.split("@")[-1] if "@" in url else url
    print(f"대상 DB: …@{shown}")

    engine = create_engine(url)
    with Session(engine) as session:
        total = session.scalar(select(func.count()).select_from(SkinAnalysis)) or 0
        rows = session.execute(
            select(SkinAnalysis.id, SkinAnalysis.image_name).where(SkinAnalysis.image_name.is_not(None))
        ).all()
        # 이미 확장자만 남은 행(".jpg")은 건너뛴다 — 다시 돌려도 안전하게.
        targets = [(rid, name) for rid, name in rows if name and not name.startswith(".")]
        print(f"전체 {total}행 / 파일명 보유 {len(rows)}행 / 정리 대상 {len(targets)}행")
        for rid, name in targets[:5]:
            print(f"   예시 id={rid}: {name!r} → {Path(name).suffix.lower()[:8] or None!r}")
        if not targets:
            print("정리할 것이 없습니다.")
            return 0
        if args.dry_run:
            print("\n(dry-run) 실제 정리는 --dry-run 없이 다시 실행하세요.")
            return 0

        for rid, name in targets:
            session.execute(
                update(SkinAnalysis).where(SkinAnalysis.id == rid).values(image_name=Path(name).suffix.lower()[:8] or None)
            )
        session.commit()
        print(f"\n완료 — {len(targets)}행의 파일명을 확장자만 남기고 지웠습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
