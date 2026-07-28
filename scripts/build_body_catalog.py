"""바디/핸드/풋 상품을 전 소스에서 모아 단일 매니페스트로 만든다.

기존 load_body_products.py는 세포라 후보 CSV(구매 링크·이미지 없음)만 봤고, 이름에
'body'가 든 것만 골라서 정작 대표 바디 상품(ILLIYOON 세라마이드 아토로션 등)을
놓쳤다. 이 스크립트가 그걸 대체한다.

수집 기준은 backend/app/services/body_categories.py 한 곳에 있다.
  - 소스가 공식 카테고리를 주면 그게 '바디/핸드/풋인지'를 결정한다(match=official).
  - 공식 카테고리가 없는 소스(아마존·올영 KR 검색)만 키워드로 판정하고,
    립/헤어/도구/얼굴전용 배제 규칙을 먼저 통과해야 한다(match=keyword).

Usage:
    python scripts/build_body_catalog.py
    python scripts/build_body_catalog.py --report      # 표본까지 출력
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.body_categories import (  # noqa: E402
    BODY,
    FOOT,
    HAND,
    classify_by_keyword,
    classify_kr_with_brand,
    classify_within_group,
    group_of,
)

MANIFEST_DIR = PROJECT_ROOT / "data" / "manifests"
OUTPUT = MANIFEST_DIR / "body_products.csv"

FIELDNAMES = [
    "category", "group", "source", "region", "match",
    "brand", "name", "name_ko", "name_ja",
    "price", "currency", "rating", "review_count",
    "product_url", "image_url", "source_category",
]

# 소스 우선순위(중복 시 앞선 소스를 남긴다). 공식 카테고리 > 검색 크롤 > 키워드.
# rakuten_jp 는 실상품 URL·이미지·리뷰를 갖춘 직링크 소스라 amazon_jp(키워드 검색링크)보다
# 앞에 둔다. JP 집중케어 물량을 메우려고 crawl_rakuten_jp_body.py 로 모은 것.
SOURCE_PRIORITY = {
    "oliveyoung_global": 0,
    "oliveyoung_kr": 1,
    "rakuten_jp": 2,
    "matsukiyo": 3,
    "amazon_jp": 4,
    "amazon_us": 5,
    "amazon_hf": 6,
}

# 올리브영 글로벌 공식 서브카테고리 → 기본 카테고리. 제형은 이름으로 더 좁힌다.
OY_SUBCATEGORY = {
    ("Bath & Body", "Body Moisturizers"): "body.lotion",
    ("Bath & Body", "Bath & Shower"): "body.wash",
    ("Bath & Body", "Hands Care"): "hand.cream",
    ("Bath & Body", "Deodorant"): "body.deodorant",
    ("Bath & Body", "Hair Removal"): "body.hair_removal",
    ("Bath & Body", "Fragrance"): "body.mist",
    ("Wellness", "Foot Care"): "foot.cream",
}

_WS_RE = re.compile(r"\s+")
_NONWORD_RE = re.compile(r"[^0-9a-z가-힣ぁ-んァ-ヶ一-龥]+")


def dedup_key(region: str, brand: str, name: str) -> tuple[str, str]:
    text = _NONWORD_RE.sub("", f"{brand}{name}".lower())
    return region, text


def clean(value: str | None) -> str:
    return _WS_RE.sub(" ", (value or "").replace("&amp;", "&")).strip()


def to_int(value: str | None) -> int:
    digits = re.sub(r"[^\d]", "", str(value or ""))
    return int(digits) if digits else 0


def to_float(value: str | None) -> float:
    try:
        return float(str(value or "").strip() or 0)
    except ValueError:
        return 0.0


def read_csv(path: Path, encoding: str = "utf-8") -> list[dict]:
    if not path.exists():
        print(f"  (건너뜀 - 파일 없음) {path.name}")
        return []
    with path.open(encoding=encoding, errors="ignore", newline="") as f:
        return list(csv.DictReader(f))


def collect_oliveyoung_global() -> list[dict]:
    """공식 카테고리 보유. 바디 판정을 전적으로 카테고리에 맡긴다."""
    out = []
    for row in read_csv(MANIFEST_DIR / "oliveyoung_global_products.csv"):
        key = (clean(row.get("category")), clean(row.get("subCategory")))
        default = OY_SUBCATEGORY.get(key)
        if not default:
            continue
        name_en = clean(row.get("prdtNameEn"))
        name_ko = clean(row.get("korPrdtName"))
        name_ja = clean(row.get("jpPrdtName"))
        category = classify_within_group(group_of(default), default, name_en, name_ko, name_ja)
        out.append({
            "category": category,
            "group": group_of(category),
            "source": "oliveyoung_global",
            "region": "global",
            "match": "official",
            "brand": clean(row.get("brandName")),
            "name": name_en,
            "name_ko": name_ko,
            "name_ja": name_ja,
            "price": to_int(row.get("saleAmt") or row.get("nrmlAmt")),
            "currency": clean(row.get("currency")) or "USD",
            "rating": 0.0,
            "review_count": 0,
            "product_url": clean(row.get("productUrl")),
            "image_url": clean(row.get("imageUrl")),
            "source_category": " > ".join(k for k in key if k),
        })
    return out


def collect_oliveyoung_kr() -> list[dict]:
    """공식 카테고리 없음(검색 크롤). 한국어 이름으로 키워드 판정."""
    out = []
    for row in read_csv(MANIFEST_DIR / "oliveyoung_kr_products.csv"):
        name = clean(row.get("goodsName"))
        # 일반 키워드 판정 → 실패 시 '바디 브랜드' 폴백(존슨즈베이비 로션 등 바디접두어 없는 것).
        category = classify_kr_with_brand(clean(row.get("brandName")), name)
        if not category:
            continue
        goods_no = clean(row.get("goodsNo"))
        out.append({
            "category": category,
            "group": group_of(category),
            "source": "oliveyoung_kr",
            "region": "kr",
            "match": "keyword",
            "brand": clean(row.get("brandName")),
            "name": name,
            "name_ko": name,
            "name_ja": "",
            "price": 0,
            "currency": "KRW",
            "rating": 0.0,
            "review_count": 0,
            "product_url": (
                "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do"
                f"?goodsNo={goods_no}" if goods_no else ""
            ),
            "image_url": clean(row.get("imageUrl")),
            "source_category": "search",
        })
    return out


def collect_matsukiyo() -> list[dict]:
    """크롤 카테고리 코드(cat:004/NN)는 스킨케어 트리라 바디 근거가 못 된다.
    일본어 상품명은 제형 표기가 명시적이라 키워드 판정이 잘 듣는다."""
    out = []
    for row in read_csv(MANIFEST_DIR / "matsukiyo_products.csv", "utf-8-sig"):
        name = clean(row.get("prdtName"))
        category = classify_by_keyword(name)
        if not category:
            continue
        out.append({
            "category": category,
            "group": group_of(category),
            "source": "matsukiyo",
            "region": "jp",
            "match": "keyword",
            "brand": clean(row.get("brandName")),
            "name": name,
            "name_ko": "",
            "name_ja": name,
            "price": to_int(row.get("saleAmt")),
            "currency": clean(row.get("currency")) or "JPY",
            "rating": to_float(row.get("avgRating")),
            "review_count": to_int(row.get("reviewCount")),
            "product_url": clean(row.get("productUrl")),
            "image_url": clean(row.get("imageUrl")),
            "source_category": clean(row.get("category")),
        })
    return out


AMAZON_SOURCES = [
    ("amazon_us", "amazon_beauty_us.csv", "us", "https://www.amazon.com/dp/"),
    ("amazon_hf", "amazon_beauty_hf.csv", "us", "https://www.amazon.com/dp/"),
    ("amazon_jp", "amazon_beauty_jp.csv", "jp", "https://www.amazon.co.jp/dp/"),
]


def collect_amazon() -> list[dict]:
    """공식 카테고리가 전혀 없고 타이틀이 SEO 키워드로 오염돼 있다.
    배제 규칙 + 복합어(단순 'body'가 아니라 'body lotion') 요구로 걸러낸다."""
    out = []
    for source, filename, region, url_base in AMAZON_SOURCES:
        for row in read_csv(MANIFEST_DIR / filename):
            title = clean(row.get("title"))
            category = classify_by_keyword(title)
            if not category:
                continue
            asin = clean(row.get("asin"))
            if not asin:
                continue
            out.append({
                "category": category,
                "group": group_of(category),
                "source": source,
                "region": region,
                "match": "keyword",
                "brand": clean(row.get("brand")),
                "name": title,
                "name_ko": "",
                "name_ja": title if region == "jp" else "",
                "price": 0,
                "currency": "JPY" if region == "jp" else "USD",
                "rating": to_float(row.get("stars")),
                "review_count": to_int(row.get("reviews")),
                "product_url": url_base + asin,
                "image_url": clean(row.get("imageUrl")),
                "source_category": "",
            })
    return out


def collect_rakuten_jp() -> list[dict]:
    """라쿠텐 JP 바디 크롤 결과(crawl_rakuten_jp_body.py 산출물).

    다른 소스와 달리 카테고리가 크롤 시점에 classify_by_keyword 로 이미 판정돼 있고,
    오프타깃(슬리밍·가슴·민감부위·업무용)도 그 단계에서 걸러졌다. 여기서는 그대로 읽는다."""
    out = []
    for row in read_csv(MANIFEST_DIR / "rakuten_jp_body.csv"):
        name = clean(row.get("name"))
        category = clean(row.get("category"))
        if not name or not category:
            continue
        out.append({
            "category": category,
            "group": group_of(category),
            "source": "rakuten_jp",
            "region": "jp",
            "match": "keyword",
            "brand": clean(row.get("brand")),
            "name": name,
            "name_ko": "",
            "name_ja": clean(row.get("name_ja")) or name,
            "price": to_int(row.get("price")),
            "currency": clean(row.get("currency")) or "JPY",
            "rating": to_float(row.get("rating")),
            "review_count": to_int(row.get("review_count")),
            "product_url": clean(row.get("product_url")),
            "image_url": clean(row.get("image_url")),
            "source_category": clean(row.get("keyword")),
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true", help="카테고리별 표본까지 출력")
    parser.add_argument("--out", default=str(OUTPUT))
    args = parser.parse_args()

    print("소스별 수집:")
    rows: list[dict] = []
    for label, fn in [
        ("올리브영 글로벌", collect_oliveyoung_global),
        ("올리브영 KR", collect_oliveyoung_kr),
        # 마츠키요 크롤은 배제(사용자 결정 2026-07-24). 크롤 경로가 스킨케어 트리라 바디
        # 근거가 약하고, 개별 상품 페이지 대신 검색 링크만 나와 구매 신뢰도가 낮았다.
        # ("마츠키요", collect_matsukiyo),
        ("라쿠텐 JP", collect_rakuten_jp),
        ("아마존", collect_amazon),
    ]:
        collected = fn()
        print(f"  {label}: {len(collected)}건")
        rows.extend(collected)

    rows.sort(key=lambda r: SOURCE_PRIORITY.get(r["source"], 99))
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for row in rows:
        if not row["name"]:
            continue
        key = dedup_key(row["region"], row["brand"], row["name"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    print(f"\n중복 제거: {len(rows)} -> {len(unique)}건")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(unique)
    print(f"저장: {out_path}")

    by_group: Counter[str] = Counter()
    by_category: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    grid: dict[str, Counter[str]] = defaultdict(Counter)
    samples: dict[str, list[str]] = defaultdict(list)
    for row in unique:
        by_group[row["group"]] += 1
        by_category[row["category"]] += 1
        by_source[row["source"]] += 1
        grid[row["category"]][row["source"]] += 1
        if len(samples[row["category"]]) < 4:
            samples[row["category"]].append(f"[{row['source']}] {row['name'][:62]}")

    print("\n그룹별:", dict(by_group))
    print("\n카테고리 x 소스")
    sources = [s for s, _ in sorted(SOURCE_PRIORITY.items(), key=lambda x: x[1])]
    header = "  {:<20}".format("category") + "".join(f"{s[:9]:>10}" for s in sources) + f"{'합계':>8}"
    print(header)
    for category in sorted(by_category, key=lambda c: -by_category[c]):
        line = "  {:<20}".format(category)
        line += "".join(f"{grid[category].get(s, 0) or '':>10}" for s in sources)
        line += f"{by_category[category]:>8}"
        print(line)

    with_url = sum(1 for r in unique if r["product_url"])
    with_image = sum(1 for r in unique if r["image_url"])
    with_price = sum(1 for r in unique if r["price"])
    total = len(unique) or 1
    print(f"\n구매링크 {with_url}/{total} ({with_url*100//total}%) · "
          f"이미지 {with_image}/{total} ({with_image*100//total}%) · "
          f"가격 {with_price}/{total} ({with_price*100//total}%)")

    if args.report:
        print("\n표본")
        for category in sorted(samples):
            print(f"\n  {category}")
            for s in samples[category]:
                print(f"      {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
