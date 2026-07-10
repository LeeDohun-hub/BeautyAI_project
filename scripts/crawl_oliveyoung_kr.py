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

from app.services.oliveyoung_kr_browser import KRBrowserSession  # noqa: E402
from app.services.oliveyoung_kr_search import search_kr  # noqa: E402
from app.services.recommender import KBEAUTY_BRANDS  # noqa: E402

FIELDNAMES = ["goodsNo", "brandName", "goodsName", "soldOut"]

# 쿼리당 상위 ~20개만 나오므로 카테고리어를 붙여 브랜드별 커버리지를 넓힌다(색조 우선).
CATEGORY_TERMS = [
    "틴트", "립스틱", "립글로스", "립밤", "쿠션", "파운데이션", "컨실러", "블러셔", "치크",
    "아이섀도우", "팔레트", "마스카라", "아이라이너", "아이브로우", "프라이머", "톤업", "쉐딩",
    "토너", "세럼", "에센스", "앰플", "크림", "로션", "클렌저", "선크림", "마스크팩",
]

# 남성 아이템매칭(베이스/브로우/컨실러/립밤)용 검색 시드. 남성 상품은 브랜드가 여성쪽과 완전히
# 달라(비레디/다슈/오브제/보웰…) 여성 시드로는 하나도 안 잡힌다(실측). '남자 XXX' 카테고리
# 쿼리는 top~20의 실제 남성 베스트셀러를 그대로 담아 item-match 네이버 결과와 브랜드가 겹친다.
MEN_QUERIES = [
    "남자 쿠션", "남성 파운데이션", "맨즈 비비크림", "남성 톤업크림",
    "남성 아이브로우", "남자 눈썹", "남성 컨실러", "남자 립밤", "남자 틴트",
    "남성 쉐딩", "남성 프라이머", "남성 선크림", "그루밍",
]
# 실측(probe)으로 확인된 올영 취급 남성 브랜드(브랜드 단독 검색 시 top~20).
MEN_BRANDS = [
    "비레디", "다슈", "오브제", "보웰", "라끌랑", "블랙몬스터", "그라펜", "낫포유",
    "미닉", "나인위시스", "우르오스", "리우젤", "아이디얼포맨", "무칸", "우칸",
]


# KBEAUTY_BRANDS(추천기 분류용)는 스킨케어 편중이라 올영 취급 '메이크업' 브랜드가 여럿 빠져 있다.
# 이들이 시드에 없으면 취급 상품인데도 카탈로그에 안 담겨 버튼이 숨겨진다(카탈로그 정답지 정책의
# 누락). 한글 표기로 둔다(국내몰은 한글 검색이 안전). 색조 위주로 보강.
EXTRA_MAKEUP_BRANDS = [
    "정샘물", "헤라", "3CE", "릴리바이레드", "데이지크", "어뮤즈", "라카", "무지개",
    "포멘트", "투쿨포스쿨", "바닐라코", "삐아", "컬러그램", "홀리카홀리카", "클럽클리오",
    "포니이펙트", "롬앤", "페리페라", "클리오", "에스쁘아", "웨이크메이크", "힌스",
]


def _brand_seed() -> list[str]:
    # 대표 표기만 남긴다(같은 브랜드의 영/한 변형은 검색 결과가 겹쳐 어차피 dedup 된다).
    return sorted(set(KBEAUTY_BRANDS) | set(EXTRA_MAKEUP_BRANDS) | set(MEN_BRANDS))


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
    parser.add_argument("--expand", action="store_true", help="브랜드×카테고리어까지(커버리지↑, 색조 포함)")
    parser.add_argument("--delay", type=float, default=2.0, help="요청 간 기본 지연(초). 지터가 더해진다")
    # --browser: curl_cffi 대신 헤드풀 Chrome 으로 Cloudflare JS 챌린지를 통과한다. 2026-07 이후
    # 국내몰이 도메인 전체를 403 챌린지로 막아 curl_cffi(비-브라우저)는 전멸했다(실측). 브라우저
    # 모드는 느리지만 확실히 통과하며, fat 카탈로그를 만들어 두면 런타임은 CF 무관하게 동작한다.
    parser.add_argument("--browser", action="store_true", help="헤드풀 Chrome 으로 CF 챌린지 통과(권장)")
    # --only: 쉼표로 구분한 브랜드만 크롤(증분 보강용). --merge 와 함께 쓰면 기존 CSV에 누적된다.
    parser.add_argument("--only", default="", help="이 브랜드들만 크롤(쉼표 구분). 예: '정샘물,헤라,3CE'")
    # --men: 남성 아이템매칭용. MEN_QUERIES('남자 쿠션'…)+MEN_BRANDS를 단독 쿼리로 크롤(term 확장 없음).
    parser.add_argument("--men", action="store_true", help="남성 카테고리/브랜드 시드로 크롤(베이스/브로우/컨실러/립밤)")
    parser.add_argument("--merge", action="store_true", help="기존 out CSV를 먼저 읽어 누적(덮어쓰기 방지)")
    parser.add_argument("--out", default=str(_ROOT / "data" / "manifests" / "oliveyoung_kr_products.csv"))
    args = parser.parse_args()

    if args.men:
        # 남성 시드는 '남자 쿠션' 같은 카테고리 쿼리 자체가 핵심이라 브랜드×term 확장을 쓰지 않는다.
        queries = list(dict.fromkeys(MEN_QUERIES + MEN_BRANDS))
        brands = queries
    else:
        if args.only.strip():
            brands = [b.strip() for b in args.only.split(",") if b.strip()]
        else:
            brands = _brand_seed()
        terms = CATEGORY_TERMS if args.expand else []
        queries = []
        for brand in brands:
            queries.append(brand)
            queries.extend(f"{brand} {t}" for t in terms)

    mode = "browser(headful Chrome)" if args.browser else "curl_cffi"
    print(f"Mode: {mode} | Brands: {len(brands)} | queries: {len(queries)} | delay: ~{args.delay}s(+jitter)")

    session: KRBrowserSession | None = None
    if args.browser:
        session = KRBrowserSession()
        if not session.start():
            print("ERROR: 브라우저 기동/챌린지 워밍 실패(playwright + 시스템 Chrome 필요). 중단.")
            return 1
        fetch = session.search   # 브라우저는 CF 를 통과하므로 429 백오프 불필요.
    else:
        fetch = _fetch

    by_goods: dict[str, dict] = {}
    out_path = Path(args.out)
    if args.merge and out_path.exists():
        with out_path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                gno = (row.get("goodsNo") or "").strip()
                if gno:
                    by_goods[gno] = {k: (row.get(k) or "") for k in FIELDNAMES}
        print(f"Merge: loaded {len(by_goods)} existing goods from {out_path.name}")

    errors = 0
    try:
        for i, query in enumerate(queries, 1):
            sr = fetch(query)
            if sr is None:
                errors += 1
                if errors >= 5:
                    print("Repeated errors (rate limit / challenge). Saving partial and stopping.")
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
    finally:
        if session is not None:
            session.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(by_goods.values())

    print(f"\nDone. Saved {len(by_goods)} products to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
