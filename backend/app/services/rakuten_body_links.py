"""JP 바디 상품 → 라쿠텐 직링크 (사전 매칭 캐시).

enrich_ingredients_rakuten.py 가 각 JP 바디 상품을 라쿠텐 상품에 매칭하며 itemUrl 을
저장해 둔다(data/manifests/rakuten_jp_ingredients.csv). 여기서 그걸 이름으로 조회한다.

이 캐시가 있으면 요청 시점에 라쿠텐 API 를 다시 부르지 않아도 된다. 기존
routes._verify_rakuten_for_skincare 는 라이브 검색이라 초당 1요청 제한 때문에 상위 6개만
붙일 수 있었다 — 캐시는 그 제한 없이 매칭된 전부(≈133건)에 직링크를 준다.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache

from app.core.config import get_settings

_WS_RE = re.compile(r"\s+")
_NONWORD_RE = re.compile(r"[^0-9a-z가-힣ぁ-んァ-ヶ一-龥]+")


def _norm(name: str) -> str:
    return _NONWORD_RE.sub("", (name or "").lower())


@lru_cache(maxsize=1)
def _load() -> dict[str, str]:
    path = get_settings().project_root / "data" / "manifests" / "rakuten_jp_ingredients.csv"
    if not path.exists():
        return {}
    table: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            url = (row.get("rakuten_url") or "").strip()
            name = (row.get("name") or "").strip()
            if url and name:
                table[_norm(name)] = url
    return table


def clear_cache() -> None:
    _load.cache_clear()


def rakuten_link_for(name: str) -> str | None:
    """상품명으로 사전 매칭된 라쿠텐 직링크를 찾는다. 없으면 None."""
    return _load().get(_norm(name))
