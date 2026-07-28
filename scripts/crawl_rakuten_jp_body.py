"""라쿠텐에서 JP 바디 집중케어(오일·세럼·에센스) 상품을 검색·수집한다.

배경: 바디 카탈로그 진단(2026-07-27) 결과 JP 집중케어(body.treatment/body.oil)가 5건뿐,
성분 0%로 사실상 비어 있었다. build_body_catalog.py 는 사전수집 CSV(올영글로벌·아마존)만
병합하고 라쿠텐 소스가 없어서 JP 집중케어를 못 채운다. 이 스크립트가 라쿠텐 검색으로
후보를 모아 매니페스트 CSV 를 만든다(→ build_body_catalog 가 병합 → 성분보강 → DB 적재).

안전: DB 에 쓰지 않는다. 로컬 CSV 만 만든다. 라쿠텐 API 는 초당 1요청 넘기면 429 이므로
1.5s + 지터로 간다(메모리 기록). 연속 실패 시 백오프·중단. 재실행 시 누적(resumable).

Usage:
    python scripts/crawl_rakuten_jp_body.py --hits 15            # 기본
    python scripts/crawl_rakuten_jp_body.py --hits 10 --keywords 4   # 소규모 트라이얼

출력: data/manifests/rakuten_jp_body.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import random
import re
import sys
import time
import unicodedata
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.body_categories import classify_by_keyword, group_of  # noqa: E402

MANIFEST_DIR = PROJECT_ROOT / "data" / "manifests"
OUTPUT = MANIFEST_DIR / "rakuten_jp_body.csv"

FIELDNAMES = [
    "category", "group", "source", "region", "match",
    "brand", "name", "name_ko", "name_ja",
    "price", "currency", "rating", "review_count",
    "product_url", "image_url", "source_category", "keyword", "shop",
]

# 집중케어(오일·세럼·에센스)를 노리는 검색어. classify_by_keyword 로 body.oil/body.treatment
# 로 분류되는 표현 위주. 보습(크림/로션)까지 넓히지 않고 진단에서 빈 슬롯만 겨냥한다.
KEYWORDS = [
    "ボディオイル",
    "ボディ美容液",
    "ボディセラム",
    "ボディエッセンス",
    "マッサージオイル ボディ",
    "ボディオイル 保湿 無香料",
    "ボディオイル オーガニック",
    "ボディ トリートメント オイル",
]

# 집중케어 슬롯만 남긴다(진단에서 비어 있던 곳). 나머지 body.* 는 참고로 세지만 저장은 전부 한다.
TARGET_CATEGORIES = {"body.oil", "body.treatment"}

# 상품명 앞의 프로모션 괄호(【..】[..]＜..＞（..）)를 걷어낸다. 라쿠텐 JP 이름은 브랜드
# 앞에 랭킹·쿠폰 뱃지가 붙는다: ＜楽天1位＞【公式】ヴェ레ダ ... 처럼.
_PROMO_RE = re.compile(r"[\[\【\＜\(（][^\]\】\＞\)）]{0,30}[\]\】\＞\)）]|[｜|].*$")
_SIZE_RE = re.compile(r"\d+\s*(ml|ｍｌ|g|ｇ|回分|個|本|セット).*$", re.I)
# 브랜드로 쓰면 안 되는 뱃지·제형·마케팅 토큰. 걸리면 다음 토큰/상점명으로 넘어간다.
_BADGE_RE = re.compile(
    r"楽天|公式|正規|送料無料|クーポン|ランキング|[0-9]+位|[0-9]+冠|ギフト|セット|"
    r"泡状|マッサージオイル|ボディオイル|ボディセラム|ボディ美容液|ボディエッセンス|"
    r"最大|限定|OFF|%|％|お買い物|ポイント|大容量|業務用|NEW|new", re.I
)

# 집중케어 카탈로그에 부적절한 오프타깃. 슬리밍·가슴·민감부위·업무용 마사지오일은
# '바디 집중케어(장벽·보습)' 의도와 다르고 일부는 뷰티 추천에 부적절해서 제외한다.
_OFF_TARGET_RE = re.compile(
    r"業務用|痩身|スリミング|セルライト|痩せ|小顔|バスト|育乳|ナイトブラ|"
    r"デリケートゾーン|膣|陰部|VIO|CBD|媚薬|セクシー", re.I
)


def is_off_target(name: str) -> bool:
    return bool(_OFF_TARGET_RE.search(name or ""))


def brand_guess(name: str, shop: str) -> str:
    """JP 화장품 itemName 은 보통 브랜드로 시작한다(ヴェレダ ...). 프로모 괄호·뱃지를 걷어내고
    앞의 '진짜' 토큰을 브랜드로 추정, 실패하면 상점명. 상점명-as-브랜드는 같은 상품이 상점마다
    다른 브랜드로 잡혀 중복되므로 가급적 이름 토큰을 쓴다."""
    head = _PROMO_RE.sub(" ", name)
    head = _SIZE_RE.sub("", head).strip()
    for token in head.split(" "):
        token = token.strip("・/-　【】[]＜＞()（）")
        if 2 <= len(token) <= 24 and not token.isdigit() and not _BADGE_RE.search(token):
            return token
    shop = (shop or "").strip()
    if shop and not _BADGE_RE.search(shop):
        return shop[:24]
    return "Rakuten"


def norm_name(name: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name or "").lower())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hits", type=int, default=15, help="키워드당 검색 건수")
    parser.add_argument("--keywords", type=int, default=0, help="사용할 키워드 수(0=전부, 트라이얼용)")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--out", default=str(OUTPUT))
    args = parser.parse_args()

    from app.services.rakuten_client import RakutenClient

    client = RakutenClient()
    if not client.configured:
        raise SystemExit("RAKUTEN_APP_ID 가 설정돼 있지 않습니다(.env).")

    out_path = Path(args.out)
    done: dict[str, dict] = {}
    if out_path.exists():
        with out_path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                done[norm_name(row.get("name_ja") or row.get("name") or "")] = row
        print(f"기존 {len(done)}건 로드(이어서 진행)")

    keywords = KEYWORDS[: args.keywords] if args.keywords else KEYWORDS
    print(f"키워드 {len(keywords)}개 · 건수/키워드 {args.hits} · 지연 ~{args.delay}s")

    kept = skipped_excluded = skipped_nonbody = skipped_offtarget = dup = failed = 0
    cat_counter: dict[str, int] = {}
    consecutive_failures = 0
    try:
        for ki, keyword in enumerate(keywords, 1):
            try:
                items = client.search(keyword, hits=args.hits)
            except Exception as exc:  # noqa: BLE001
                items = []
                print(f"  [{keyword}] 예외: {exc}")
            if not items:
                # 라쿠텐이 0건/에러면 last_error 확인
                if client.last_error:
                    failed += 1
                    consecutive_failures += 1
                    print(f"  [{keyword}] 0건/에러: {client.last_error}")
                    if consecutive_failures >= 5:
                        print("연속 실패 5건(레이트리밋 추정). 여기까지 저장하고 중단.")
                        break
                    time.sleep(min(60, 5 * consecutive_failures))
                    continue
            consecutive_failures = 0

            for it in items:
                nk = norm_name(it.name)
                if nk in done:
                    dup += 1
                    continue
                if is_off_target(it.name):
                    # 슬리밍·가슴·민감부위·업무용 마사지오일 등 집중케어 의도 밖
                    skipped_offtarget += 1
                    continue
                category = classify_by_keyword(it.name)
                if category is None:
                    # 배제(헤어/얼굴/립/도구) 혹은 바디 근거 없음
                    skipped_excluded += 1
                    continue
                if group_of(category) != "body":
                    skipped_nonbody += 1
                    continue
                row = {
                    "category": category,
                    "group": group_of(category),
                    "source": "rakuten_jp",
                    "region": "jp",
                    "match": "keyword",
                    "brand": brand_guess(it.name, it.brand),
                    "name": it.name,
                    "name_ko": "",
                    "name_ja": it.name,
                    "price": it.price or 0,
                    "currency": "JPY",
                    "rating": it.review_average or 0.0,
                    "review_count": it.review_count or 0,
                    "product_url": it.product_url,
                    "image_url": it.image_url or "",
                    "source_category": "",
                    "keyword": keyword,
                    "shop": it.brand,
                }
                done[nk] = row
                kept += 1
                cat_counter[category] = cat_counter.get(category, 0) + 1

            print(f"  [{ki}/{len(keywords)}] {keyword}: +{len(items)}건 조회 (누적 keep {kept})", flush=True)
            time.sleep(args.delay + random.uniform(0, args.delay * 0.4))
    finally:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            for row in done.values():
                writer.writerow({k: row.get(k, "") for k in FIELDNAMES})
        print(f"\n저장: {out_path} (누적 {len(done)}건)")

    print(f"이번 실행 keep {kept} · 중복 {dup} · 오프타깃 {skipped_offtarget} · "
          f"배제 {skipped_excluded} · 비-바디 {skipped_nonbody} · 요청실패 {failed}")
    print("카테고리별(이번 실행):", cat_counter)
    target = sum(1 for r in done.values() if r["category"] in TARGET_CATEGORIES)
    print(f"누적 집중케어(oil/treatment): {target}/{len(done)}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
