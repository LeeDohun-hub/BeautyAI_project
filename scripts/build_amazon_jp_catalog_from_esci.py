"""Amazon ESCI(Shopping Queries) JP 코퍼스 → 아마존 JP 카탈로그 보강.

왜: `amazon_beauty_jp.csv`(3,868건)는 한국 화장품 위주라, 라쿠텐·마츠키요에서 온 **일본
드럭스토어 바디 상품**(큐렐·비오레·미노 등)과 겹치지 않는다. 그래서 지역을 JP로 두고
아마존을 고르면 보습·집중케어 컬럼이 **0건**이 된다(2026-07-28 실측).

ESCI 는 아마존이 공개한 검색 데이터셋으로 **JP 로케일 상품 337,391건**(ASIN + 일본어 제목 +
브랜드)을 담고 있다. 크롤 없이 JP 커버리지를 넓히는 유일한 공개 경로였다.
(HuggingFace/Kaggle 을 뒤져도 다른 아마존 JP 상품 데이터셋은 사실상 없다.)

⚠️ 라이선스: ESCI 원본은 amazon-science/esci-data 배포 조건을 따른다. 상용 서비스에 싣기 전
   반드시 확인할 것. 여기서는 **카탈로그 매칭용 ASIN·제목**만 쓴다.

출력(loader 스키마 동일): data/manifests/amazon_beauty_jp_esci.csv
  → build_body_catalog.py 의 amazon_jp 소스에 추가하면 직링크 후보가 넓어진다.

Usage:
    python scripts/build_amazon_jp_catalog_from_esci.py            # 바디케어만(권장)
    python scripts/build_amazon_jp_catalog_from_esci.py --all      # 필터 없이 전부
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

HF_REPO = "spacemanidol/ESCI-product-dataset-corpus-jp"
HF_FILE = "collection.jsonl.gz"
OUTPUT = PROJECT_ROOT / "data" / "manifests" / "amazon_beauty_jp_esci.csv"
FIELDNAMES = ["asin", "brand", "title", "stars", "reviews", "imageUrl"]

# 바디/핸드/풋 케어로 보이는 제목만 남긴다. ESCI 는 전 카테고리(노트·가전 포함)라
# 필터 없이 넣으면 매칭이 느려지고 오매칭 위험만 커진다.
BODY_KEYWORDS = (
    "ボディ", "ハンド", "フット", "ローション", "クリーム", "ソープ", "ウォッシュ",
    "オイル", "ミルク", "スクラブ", "日焼け止め", "デオドラント", "制汗", "保湿",
    "body", "hand", "foot", "lotion", "cream", "wash", "scrub", "deodorant",
)
# 명백히 화장품이 아닌 것(제목에 위 키워드가 섞여도 제외)
EXCLUDE = ("ノート", "電池", "ケーブル", "スマホ", "カバー", "手袋", "タオル", "洗濯",
           "食器", "シャンプー台", "掃除", "ペット", "自動車", "工具")


def looks_body_care(title: str) -> bool:
    if not title:
        return False
    if any(x in title for x in EXCLUDE):
        return False
    return any(k in title for k in BODY_KEYWORDS)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="바디케어 필터 없이 전부 담는다(비권장)")
    ap.add_argument("--out", type=Path, default=OUTPUT)
    args = ap.parse_args()

    from huggingface_hub import hf_hub_download

    path = hf_hub_download(HF_REPO, HF_FILE, repo_type="dataset")
    print(f"ESCI JP 코퍼스: {Path(path).stat().st_size/1048576:.1f} MB")

    seen: set[str] = set()
    rows: list[dict] = []
    total = 0
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            total += 1
            d = json.loads(line)
            asin = (d.get("docid") or "").strip()
            title = (d.get("title") or "").strip()
            if not asin or not title or asin in seen:
                continue
            if not args.all and not looks_body_care(title):
                continue
            seen.add(asin)
            rows.append({
                "asin": asin,
                "brand": (d.get("brand") or "").strip(),
                "title": re.sub(r"\s+", " ", title),
                # ESCI 에는 평점·리뷰수·이미지가 없다. 로더 스키마를 맞추되 빈 값으로 둔다
                # (평점은 아마존 US 카탈로그에만 있다는 기존 제약과 동일).
                "stars": "",
                "reviews": "",
                "imageUrl": "",
            })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    brands = {r["brand"] for r in rows if r["brand"]}
    print(f"전체 {total:,}건 → 담은 상품 {len(rows):,}건 (고유 브랜드 {len(brands):,}개)")
    print(f"저장: {args.out.relative_to(PROJECT_ROOT)}")
    print("\n다음: build_body_catalog.py 의 amazon_jp 소스 목록에 이 파일을 추가하면"
          "\n      아마존 JP 직링크 후보가 넓어진다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
