"""국내몰 카탈로그의 **비어 있는 imageUrl 만** 채운다(재크롤 없이).

왜 따로 필요한가
  crawl_oliveyoung_kr.py 는 시드(브랜드·카테고리어)로 검색해 상위 ~20개를 담는다. 이미지
  컬럼이 생기기 전에 담긴 옛 행은 `--merge` 로 다시 돌려야 채워지는데, 그러려면 **그 상품을
  다시 물어오는 쿼리**를 맞춰 던져야 한다. 실측(2026-08-07): 결손 1,575건이 101개 브랜드에
  걸쳐 있고, 라운드랩은 95건 중 74건이 비었다 — 브랜드 단독 쿼리는 top~20 만 주므로
  전체 재크롤(브랜드×카테고리어 2,800여 쿼리)을 돌려야 겨우 닿는다.

  그래서 시드가 아니라 **비어 있는 행 자체를 쿼리로 만든다.** 한 번 검색하면 그 상품뿐
  아니라 같이 온 ~20개의 결손도 함께 채워지므로, 1,575건을 1,575번 물어볼 필요가 없다
  (같은 브랜드/라인이 뭉쳐 있어 수렴이 빠르다).

  API 는 IMG_PATH_NM 을 항상 준다(probe 확인: 비레디·라끌랑·무칸 전 건 100%). 결손은
  '데이터가 없어서'가 아니라 '그때 안 받아서'다.

⚠ 헤드풀 Chrome 이 필요하다. 국내몰은 2026-07 이후 Cloudflare JS 챌린지라 curl_cffi 는
  전멸했고 headless 도 403 이다(oliveyoung_kr_browser 참고). 창이 떠 있어야 통과한다.

Usage:
    backend/.venv/Scripts/python.exe scripts/backfill_oliveyoung_kr_images.py --dry-run
    backend/.venv/Scripts/python.exe scripts/backfill_oliveyoung_kr_images.py --max-queries 400
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.services.oliveyoung_kr_browser import KRBrowserSession  # noqa: E402
from app.services.platform_resolver import oliveyoung_kr_query  # noqa: E402

FIELDNAMES = ["goodsNo", "brandName", "goodsName", "soldOut", "imageUrl"]
DEFAULT_CSV = _ROOT / "data" / "manifests" / "oliveyoung_kr_products.csv"


def _load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{k: (row.get(k) or "") for k in FIELDNAMES} for row in csv.DictReader(f)]


def _save(path: Path, rows: list[dict]) -> None:
    # 원자적으로 쓴다 — 중간에 끊겨도 원본이 반쯤 잘린 채 남지 않는다.
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--delay", type=float, default=1.0, help="요청 간 기본 지연(초). 지터가 더해진다")
    ap.add_argument("--max-queries", type=int, default=0, help="이번 실행 최대 검색 수(0=결손이 없어질 때까지)")
    ap.add_argument("--dry-run", action="store_true", help="검색 없이 결손 규모만 센다")
    ap.add_argument("--save-every", type=int, default=25, help="N 쿼리마다 중간 저장(끊겨도 그때까지 남는다)")
    # 검색으로 안 걸리는 잔여분(한정기획·단종)을 goodsNo 상세 페이지에서 직접 읽는다.
    # 검색보다 느리다(페이지 이동) — 그래서 잔여분 전용이다.
    ap.add_argument("--detail", action="store_true",
                    help="검색 대신 goodsNo 상세 페이지에서 대표 이미지를 읽는다(잔여분용)")
    args = ap.parse_args()

    path = Path(args.csv)
    rows = _load(path)
    by_goods = {r["goodsNo"]: r for r in rows if r["goodsNo"]}
    gaps = [r for r in rows if not r["imageUrl"].strip()]
    print(f"전체 {len(rows)}건 · 이미지 결손 {len(gaps)}건 ({len(gaps) / max(1, len(rows)) * 100:.1f}%)")
    if args.dry_run or not gaps:
        return 0

    session = KRBrowserSession()
    if not session.start():
        print("ERROR: 브라우저 기동/챌린지 워밍 실패(playwright + 시스템 Chrome 필요). 중단.")
        return 1

    filled = queries = 0
    started = time.time()

    if args.detail:
        # 잔여분: goodsNo 로 상세 페이지를 직접 연다. 곁가지로 채워지는 게 없으므로
        # 결손 1건당 정확히 1회다(검색 모드보다 느리지만 확실하다).
        #
        # 여기서 **죽은 상품이 드러난다.** 검색으로도 안 나오고 상세 페이지도 '상품을 찾을 수
        # 없어요'인 goodsNo 는 이미 내려간 상품이다. 그대로 두면 카탈로그가 그 상품을 카드로
        # 내보내고, 사용자는 직링크를 눌러 '상품 없음' 페이지를 만난다 — 이미지 결손보다
        # 나쁜 문제라, 판매중(soldOut) 표시를 내려 런타임 후보에서 빠지게 한다.
        # ⚠ '모름'(네트워크·챌린지 실패)은 절대 죽은 것으로 취급하지 않는다.
        dead = unknown = 0
        try:
            for gap in gaps:
                if args.max_queries and queries >= args.max_queries:
                    print(f"--max-queries {args.max_queries} 도달 — 여기까지 저장하고 멈춘다.")
                    break
                queries += 1
                image, alive = session.goods_detail(gap["goodsNo"])
                if image:
                    gap["imageUrl"] = image
                    filled += 1
                elif alive is False:
                    gap["soldOut"] = "Y"
                    dead += 1
                else:
                    unknown += 1
                if queries % 10 == 0:
                    rate = queries / max(1e-9, time.time() - started)
                    print(f"  {queries}/{len(gaps)} · 채움 {filled} · 내려간 상품 {dead}"
                          f" · 판정 불가 {unknown} · {rate * 60:.0f}건/분", flush=True)
                if queries % args.save_every == 0:
                    _save(path, rows)
                time.sleep(args.delay + random.uniform(0, args.delay))
        finally:
            session.close()
            _save(path, rows)
        left = sum(1 for r in rows if not r["imageUrl"].strip())
        print(f"\n완료: {queries}건 조회 · 이미지 채움 {filled} · 내려간 상품 {dead}(soldOut=Y 로 표시)"
              f" · 판정 불가 {unknown}")
        print(f"남은 이미지 결손 {left}건 ({(time.time() - started) / 60:.1f}분) · 저장: {path}")
        return 0

    # 이미 던진 쿼리는 다시 던지지 않는다. 한 쿼리가 ~20건을 채우므로 결손 목록을 매번
    # 다시 훑되, 쿼리 중복만 막으면 자연히 수렴한다.
    tried: set[str] = set()
    try:
        for gap in gaps:
            if gap["imageUrl"].strip():
                continue  # 앞선 쿼리가 이미 채웠다
            if args.max_queries and queries >= args.max_queries:
                print(f"--max-queries {args.max_queries} 도달 — 여기까지 저장하고 멈춘다.")
                break
            query = oliveyoung_kr_query(gap["brandName"], gap["goodsName"]).strip()
            if not query or query in tried:
                continue
            tried.add(query)
            queries += 1

            sr = session.search(query)
            if sr is not None:
                for result in sr.results:
                    row = by_goods.get(result.goods_no)
                    if row is not None and not row["imageUrl"].strip() and (result.image_url or "").strip():
                        row["imageUrl"] = result.image_url
                        filled += 1

            if queries % 10 == 0:
                left = sum(1 for r in rows if not r["imageUrl"].strip())
                rate = queries / max(1e-9, time.time() - started)
                print(f"  {queries} 쿼리 · 채움 {filled} · 남은 결손 {left} · {rate * 60:.0f}쿼리/분", flush=True)
            if queries % args.save_every == 0:
                _save(path, rows)
            time.sleep(args.delay + random.uniform(0, args.delay))
    finally:
        session.close()
        _save(path, rows)

    left = sum(1 for r in rows if not r["imageUrl"].strip())
    print(f"\n완료: {queries} 쿼리로 {filled}건 채움 · 남은 결손 {left}건 ({(time.time() - started) / 60:.1f}분)")
    print(f"저장: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
