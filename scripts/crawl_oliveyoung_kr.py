"""올리브영 국내몰(oliveyoung.co.kr) 카탈로그 배치 크롤.

런타임의 실시간 국내몰 검색(oliveyoung_kr_search)을 매번 타지 않도록, K뷰티 브랜드별로
NewMainSearchApi 를 미리 돌려 goodsNo/상품명을 로컬 CSV로 모은다. 런타임은 이 CSV를 먼저
매칭(로컬 즉시)하고, 없을 때만 라이브 검색으로 폴백한다.

검색 API는 쿼리당 상위 ~20개만 반환하고 페이지네이션이 없다(실측). 그래서 '브랜드' 단독뿐
아니라 '브랜드 + 카테고리어'(틴트/토너/세럼 …) 조합으로 커버리지를 넓힌다.

curl_cffi 로 Cloudflare 를 통과한다(수동 쿠키 불필요). 앱의 oliveyoung_kr_search.search_kr 을
그대로 재사용한다.

Usage (프로젝트 루트 BeautyAI_project 에서):
    backend/.venv/Scripts/python.exe scripts/crawl_oliveyoung_kr.py
    backend/.venv/Scripts/python.exe scripts/crawl_oliveyoung_kr.py --no-expand --delay 0.3

출력: data/manifests/oliveyoung_kr_products.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]  # BeautyAI_project
sys.path.insert(0, str(_ROOT / "backend"))

from app.services.oliveyoung_kr_search import search_kr  # noqa: E402
from app.services.recommender import KBEAUTY_BRANDS  # noqa: E402

FIELDNAMES = ["goodsNo", "brandName", "goodsName", "soldOut"]

# 쿼리당 상위 ~20개만 나오므로 카테고리어를 붙여 브랜드별 커버리지를 넓힌다(색조 우선).
CATEGORY_TERMS = [
    "틴트", "립스틱", "립글로스", "쿠션", "파운데이션", "컨실러", "블러셔", "치크",
    "아이섀도우", "팔레트", "마스카라", "아이라이너", "아이브로우", "프라이머",
    "토너", "세럼", "에센스", "앰플", "크림", "로션", "클렌저", "선크림", "마스크팩",
]


def _brand_seed() -> list[str]:
    # 대표 표기만 남긴다(같은 브랜드의 영/한 변형은 검색 결과가 겹쳐 어차피 dedup 된다).
    return sorted(KBEAUTY_BRANDS)


def _fetch(query: str, retries: int = 3):
    """search_kr 재시도(백오프). 국내몰 Cloudflare는 대량/빠른 요청에 429를 준다."""
    for attempt in range(retries):
        sr = search_kr(query)
        if sr is not None:
            return sr
        time.sleep(2 ** attempt * 3)  # 3s, 6s, 12s 백오프
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl Olive Young KR catalog via NewMainSearchApi.")
    # 주의: 국내몰 Cloudflare는 IP당 레이트리밋(429)이 빡세다. 대량/빠른 크롤은 리밋을 트리거해
    # '라이브 검색'까지 같은 IP라 함께 막힌다. 기본은 브랜드 단독(41요청)·느린 지연으로 안전하게.
    parser.add_argument("--expand", action="store_true", help="브랜드×카테고리어까지(요청 급증, 429 주의)")
    parser.add_argument("--delay", type=float, default=2.0, help="요청 간 기본 지연(초). 지터가 더해진다")
    parser.add_argument("--out", default=str(_ROOT / "data" / "manifests" / "oliveyoung_kr_products.csv"))
    args = parser.parse_args()

    brands = _brand_seed()
    terms = CATEGORY_TERMS if args.expand else []
    queries: list[str] = []
    for brand in brands:
        queries.append(brand)
        queries.extend(f"{brand} {t}" for t in terms)

    print(f"Brands: {len(brands)} | queries: {len(queries)} | delay: ~{args.delay}s(+jitter)")

    by_goods: dict[str, dict] = {}
    errors = 0
    for i, query in enumerate(queries, 1):
        sr = _fetch(query)
        if sr is None:
            errors += 1
            if errors >= 5:
                print("Repeated 429/errors — rate limited. Saving partial and stopping.")
                break
            continue
        errors = 0
        for r in sr.results:
            if r.goods_no and r.goods_no not in by_goods:
                by_goods[r.goods_no] = {
                    "goodsNo": r.goods_no,
                    "brandName": r.brand,
                    "goodsName": r.name,
                    "soldOut": "Y" if r.sold_out else "N",
                }
        if i % 20 == 0:
            print(f"  {i}/{len(queries)} queries -> {len(by_goods)} unique goods")
        time.sleep(args.delay + random.uniform(0, args.delay))  # 지터로 봇 패턴 완화

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(by_goods.values())

    print(f"\nDone. Saved {len(by_goods)} products to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
