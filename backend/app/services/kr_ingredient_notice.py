"""올리브영 고시 전성분 '원문' 조회 (goodsNo → 한글 전성분 텍스트).

DB Product 는 검출된 표준 성분명만 갖는다(우리가 아는 23종). 하지만 소아 안전 판정은
'검출 안 된' 성분(향료·에센셜오일·색소)까지 봐야 한다. 그래서 원문 텍스트가 필요하다.

enrich_ingredients_oliveyoung.py 산출물(oliveyoung_kr_ingredients.csv)의 ingredients_ko
컬럼을 goodsNo 로 인덱싱한다.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache

from app.core.config import get_settings

_GOODS_RE = re.compile(r"goodsNo=(\w+)")


@lru_cache(maxsize=1)
def _load() -> dict[str, str]:
    path = get_settings().project_root / "data" / "manifests" / "oliveyoung_kr_ingredients.csv"
    if not path.exists():
        return {}
    table: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            text = (row.get("ingredients_ko") or "").strip()
            if text:
                table[row["goodsNo"]] = text
    return table


def clear_cache() -> None:
    _load.cache_clear()


def raw_ingredients_for_url(product_url: str | None) -> str:
    """product_url 의 goodsNo 로 전성분 원문을 찾는다. 없으면 빈 문자열."""
    match = _GOODS_RE.search(product_url or "")
    if not match:
        return ""
    return _load().get(match.group(1), "")
