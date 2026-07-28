"""OpenFDA OTC 라벨에서 미국 상품의 전성분을 채운다.

배경: 성분 미보유 462건(바디/핸드/풋) 중 아마존 US 상품이 가장 큰 덩어리인데, 상품 페이지에
전성분이 없어 오랫동안 '보강 불가'로 분류돼 있었다. 그런데 **미국에서 선크림·발한억제제·
여드름/습진 치료제는 OTC '의약품'** 이라 api.fda.gov 라벨에 `inactive_ingredient`(사실상
전성분)가 붙는다. 실측: 전성분 보유 OTC 라벨 49,956건, 우리 브랜드(Neutrogena 156 ·
Aveeno 53 · CeraVe 43 · EltaMD 26 · Mitchum 14 …)도 모두 존재.

한글 사전 확장(ingredient_aliases)을 건드리지 않는 것도 장점이다 — OpenFDA 성분은 영문이라
기존 `detect_ingredients()` 의 영문 needle 로 바로 잡힌다.

⚠️ 순수 화장품(바디워시·로션·오일)은 의약품이 아니라 **대상이 아니다**. 대상 카테고리만 돈다.
⚠️ 엉뚱한 라벨의 전성분을 붙이는 건 성분이 없는 것보다 나쁘다 → 상품명 유사도 게이트를 건다
   (라쿠텐 스크립트와 같은 원칙).

Usage:
    python scripts/enrich_ingredients_openfda.py --dry-run
    python scripts/enrich_ingredients_openfda.py --dry-run --limit 30
    BODY_LOAD_CONFIRM=yes python scripts/enrich_ingredients_openfda.py
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

API = "https://api.fda.gov/drug/label.json"
AUDIT_CSV = PROJECT_ROOT / "data" / "manifests" / "openfda_ingredients.csv"

# OTC 의약품으로 분류되는 카테고리만. 바디워시·로션·오일은 화장품이라 라벨이 없다.
# (medicated 로션/크림이 일부 있지만, 유사도 게이트가 걸러줄 것이므로 후보에는 넣는다.)
OTC_CATEGORIES = ("body.sun", "body.deodorant", "body.treatment", "body.cream", "hand.cream", "foot.cream")

# 매칭 게이트.
#  - MIN_SCORE: 라벨의 '변형 토큰'(브랜드 제외)이 우리 상품명에 얼마나 들어있는지(컨테인먼트).
#    Jaccard 를 쓰면 우리 상품명이 길어서(규격·수량·프로모션) 점수가 뭉개진다(실측 0.14~0.27로
#    Mitchum·Shiseido 가 전부 탈락). 아마존 ASIN 매칭에서 쓴 컨테인먼트 방식과 같다.
#  - MIN_MARGIN: 같은 브랜드의 변형끼리 점수가 비슷하면(예: Mitchum Clear Gel vs Roll On)
#    어느 쪽인지 못 고른다. 엉뚱한 변형의 전성분을 붙이는 건 성분이 없는 것보다 나쁘므로
#    1위와 2위 차이가 이보다 작으면 '모호'로 보고 건너뛴다.
#    실측: 0.67(라벨 변형토큰 2/3 일치)은 근거가 약해 Mitchum 6종이 전부 엉뚱한 하나의
#    라벨('Revlon Mitchum Clinical Gel')에 몰렸다. 0.75 로 올리면 육안 확인상 정확한 건만 남는다.
#    재현율(13→6건)보다 정밀도를 택한다 — 잘못된 전성분은 성분이 없는 것보다 나쁘다.
MIN_SCORE = 0.75
MIN_MARGIN = 0.15

# OpenFDA 는 미국 유통 의약품만 담는다. 올리브영 글로벌의 한국 브랜드(ILLIYOON·Abib…)는
# 카테고리가 맞아도 애초에 대상이 아니므로 US 마켓 링크로 모집단을 좁힌다.
US_URL_PATTERNS = ("%amazon.com%",)

# 브랜드명을 OpenFDA 검색어에 넣기 전 정리한다. 'Dr.Jart+' 의 '+' 나 '.' 같은 문자가
# Lucene 질의 문법을 깨서 HTTP 400 이 난다(실측 40건 중 19건).
_BRAND_SAFE_RE = re.compile(r"[^A-Za-z0-9&' ]+")

_WORD_RE = re.compile(r"[a-z0-9]+")
# 상품명에서 매칭에 방해되는 규격·마케팅 토큰
_NOISE = {
    "oz", "ml", "fl", "g", "kg", "lb", "pack", "count", "ct", "size", "new", "value",
    "free", "for", "with", "and", "the", "of", "plus", "hour", "hr", "day", "night",
}


def tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall((text or "").lower()) if w not in _NOISE and len(w) > 1}


def variant_score(product_name: str, label_name_value: str, brand: str) -> float:
    """라벨의 '변형 토큰'이 우리 상품명에 얼마나 담겼는지(0~1).

    브랜드 토큰은 양쪽에서 뺀다 — 브랜드만 겹쳐 만점이 나오면 같은 브랜드의 아무 변형이나
    붙어버린다. 변형 토큰이 하나도 안 겹치면 0을 준다.
    """
    brand_tokens = tokens(brand)
    label_tokens = tokens(label_name_value) - brand_tokens
    product_tokens = tokens(product_name) - brand_tokens
    if not label_tokens:
        return 0.0
    return len(label_tokens & product_tokens) / len(label_tokens)


def api_get(params: dict, api_key: str) -> dict:
    if api_key:
        params = {**params, "api_key": api_key}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"results": []}          # OpenFDA 는 '결과 없음'도 404 로 준다
        return {"_error": f"HTTP {exc.code}"}
    except Exception as exc:  # 네트워크·타임아웃
        return {"_error": type(exc).__name__}


def label_ingredients(label: dict) -> str:
    """inactive_ingredient(전성분) + active_ingredient(유효성분)를 한 덩어리로."""
    parts = []
    for key in ("inactive_ingredient", "active_ingredient"):
        value = label.get(key)
        if isinstance(value, list):
            parts.extend(str(v) for v in value)
        elif value:
            parts.append(str(value))
    return " ".join(parts)


def label_name(label: dict) -> str:
    openfda = label.get("openfda") or {}
    for key in ("brand_name", "generic_name", "substance_name"):
        value = openfda.get(key)
        if value:
            return str(value[0] if isinstance(value, list) else value)
    return ""


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", _BRAND_SAFE_RE.sub(" ", value or "")).strip()


def find_label(brand: str, name: str, api_key: str) -> tuple[dict | None, float, str]:
    """후보 라벨을 모아 변형 점수가 가장 높은 것을 고른다.

    ⚠️ 후보 풀을 DB 브랜드만으로 뽑으면 안 된다. 우리 DB 는 모회사를 브랜드로 갖는 경우가 있어
    (Mitchum 제품들의 brand='revlon'), OpenFDA 의 brand_name 검색이 실제 제품 라인을 놓친다.
    실측 사고: Mitchum 7종이 유일하게 잡힌 'Revlon Mitchum Clinical Gel' 하나에 전부 매칭됐고,
    경쟁 후보가 없어 모호 게이트도 통과했다. → 상품명 선두 토큰으로도 후보를 받는다.
    """
    brand_q = _clean(brand)
    # 상품명 첫 두 단어(예: 'Mitchum Clinical')도 제품 라인 이름인 경우가 많다.
    name_head = " ".join(_clean(name).split()[:2])

    terms = [t for t in {brand_q, name_head} if t]
    if not terms:
        return None, 0.0, "브랜드 없음"

    results: list[dict] = []
    seen: set[str] = set()
    for term in terms:
        data = api_get({"search": f'openfda.brand_name:"{term}"', "limit": "50"}, api_key)
        if "_error" in data:
            return None, 0.0, data["_error"]
        for label in data.get("results") or []:
            key = label_name(label)
            if key and key not in seen:
                seen.add(key)
                results.append(label)
    if not results:
        return None, 0.0, "라벨 없음"

    scored = [
        (variant_score(name, label_name(label), brand_q), label)
        for label in results
        if label_ingredients(label)
    ]
    if not scored:
        return None, 0.0, "전성분 있는 라벨 없음"

    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0

    if best_score < MIN_SCORE:
        return None, best_score, f"유사도 미달({best_score:.2f})"
    if best_score - runner_up < MIN_MARGIN:
        # 같은 브랜드의 변형끼리 구분이 안 된다 → 찍지 말고 비운다.
        return None, best_score, f"변형 모호({best_score:.2f} vs {runner_up:.2f})"
    return best, best_score, ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", action="store_true", help="로컬 beautyai.db 사용")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 집계만")
    parser.add_argument("--limit", type=int, default=0, help="처리 최대 건수(0=전부)")
    parser.add_argument("--delay", type=float, default=0.3, help="요청 간격(초). 키가 있으면 여유롭다")
    args = parser.parse_args()

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    api_key = os.environ.get("OPENFDA_API_KEY", "")
    print(f"OPENFDA_API_KEY: {'있음' if api_key else '없음(무키 호출 — rate limit 낮음)'}")

    if args.sqlite:
        os.environ["DATABASE_URL"] = f"sqlite:///{(PROJECT_ROOT / 'beautyai.db').as_posix()}"

    from sqlalchemy import or_  # noqa: E402
    from sqlalchemy.orm import selectinload  # noqa: E402

    from app.core.database import SessionLocal, database_url  # noqa: E402
    from app.models import Ingredient, Product, ProductIngredient  # noqa: E402
    from load_product_catalog_to_db import (  # noqa: E402
        detect_ingredients,
        ensure_ingredient,
        infer_skin_types,
    )

    print(f"대상 DB: {database_url.split('@')[-1]}")
    if not args.sqlite and not args.dry_run and not database_url.startswith("sqlite"):
        if os.environ.get("BODY_LOAD_CONFIRM") != "yes":
            raise SystemExit("원격 DB 수정에는 BODY_LOAD_CONFIRM=yes 가 필요합니다. (--dry-run 으로 미리보기)")

    db = SessionLocal()
    try:
        ingredient_cache = {i.name: i for i in db.query(Ingredient).all()}
        products = (
            db.query(Product)
            .options(selectinload(Product.brand), selectinload(Product.ingredients))
            .filter(~Product.ingredients.any())
            .filter(Product.category.in_(OTC_CATEGORIES))
            .filter(or_(*[Product.product_url.like(p) for p in US_URL_PATTERNS]))
            .all()
        )
        print(f"성분 없는 US OTC 후보 상품: {len(products)}건")
        if args.limit:
            products = products[:args.limit]

        filled = no_match = empty = failed = 0
        detected_counts: Counter[str] = Counter()
        audit: list[dict] = []

        for index, product in enumerate(products, 1):
            brand = product.brand.name if product.brand else ""
            label, score, reason = find_label(brand, product.name or "", api_key)
            if label is None:
                if reason.startswith("HTTP") or reason in {"URLError", "TimeoutError"}:
                    failed += 1
                else:
                    no_match += 1
                audit.append({
                    "product": product.name, "brand": brand, "category": product.category,
                    "matched_label": "", "score": f"{score:.2f}", "detected": "", "reason": reason,
                })
            else:
                blob = label_ingredients(label)
                names = detect_ingredients(product.name or "", blob)
                if names:
                    for name in names:
                        ingredient = ensure_ingredient(db, ingredient_cache, name)
                        db.add(ProductIngredient(product=product, ingredient=ingredient, weight=1.0))
                    product.skin_types = infer_skin_types(names)
                    filled += 1
                    detected_counts.update(names)
                else:
                    empty += 1  # 전성분은 받았으나 우리 표준 성분에 해당 없음
                audit.append({
                    "product": product.name, "brand": brand, "category": product.category,
                    "matched_label": label_name(label), "score": f"{score:.2f}",
                    "detected": "|".join(names), "reason": "",
                })

            if index % 25 == 0:
                print(f"  {index}/{len(products)} · 채움 {filled} · 매칭실패 {no_match} · "
                      f"해당없음 {empty} · 요청실패 {failed}", flush=True)
            time.sleep(args.delay)

        if args.dry_run:
            db.rollback()
            print("(dry-run — 롤백함)")
        else:
            db.commit()

        AUDIT_CSV.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_CSV.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["product", "brand", "category", "matched_label", "score", "detected", "reason"]
            )
            writer.writeheader()
            writer.writerows(audit)

        print(f"\n성분 채운 상품: {filled}건 · 매칭 실패: {no_match}건 · "
              f"표준성분 해당없음: {empty}건 · 요청 실패: {failed}건")
        if detected_counts:
            print(f"검출 성분: {dict(detected_counts.most_common(12))}")
        print(f"감사 로그: {AUDIT_CSV}")
        hits = [a for a in audit if a["detected"]]
        for row in hits[:6]:
            print(f"  [{row['category']}] {row['product'][:44]} (score {row['score']}) -> {row['detected']}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
