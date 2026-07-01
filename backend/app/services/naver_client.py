"""네이버 쇼핑 상품 검색 클라이언트.

한국(KR) 아이템 매칭의 상품 provider. 라쿠텐이 일본(JP)에서 하는 역할을 한국에서
네이버 쇼핑 검색이 대신한다. 색상 키워드(예: "코랄 핑크 립")를 한국어 그대로 넘기면
네이버가 실제 색상 매칭 상품을 반환한다(이미지·가격·링크 포함).

네이버 쇼핑 검색 API는 리뷰 평점/개수를 제공하지 않으므로 해당 필드는 None이다.
자격증명(NAVER_CLIENT_ID/SECRET)이 없으면 configured=False로 빈 결과를 준다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

NAVER_SHOP_API = "https://openapi.naver.com/v1/search/shop.json"
_REQUEST_TIMEOUT = 3.0
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class NaverProduct:
    id: str
    brand: str
    name: str
    price: int
    image_url: str | None
    product_url: str
    review_average: float | None
    review_count: int | None
    keyword: str


class NaverClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.client_id = settings.naver_client_id
        self.client_secret = settings.naver_client_secret
        self.last_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def search(self, keyword: str, hits: int = 6) -> list[NaverProduct]:
        keyword = (keyword or "").strip()
        if not keyword or not self.configured:
            return []
        try:
            response = httpx.get(
                NAVER_SHOP_API,
                params={"query": keyword, "display": hits, "sort": "sim"},
                headers={
                    "X-Naver-Client-Id": self.client_id,
                    "X-Naver-Client-Secret": self.client_secret,
                },
                timeout=_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            items = response.json().get("items") or []
        except Exception as exc:  # noqa: BLE001 - provider 실패가 앱을 깨지 않게 한다.
            self.last_error = str(exc)
            return []

        products: list[NaverProduct] = []
        for index, item in enumerate(items):
            name = _TAG_RE.sub("", str(item.get("title") or "")).strip()
            url = str(item.get("link") or "").strip()
            if not name or not url:
                continue
            brand = str(item.get("brand") or item.get("maker") or "").strip()
            image = str(item.get("image") or "").strip()
            products.append(
                NaverProduct(
                    id=str(item.get("productId") or f"naver-{index}"),
                    brand=brand or "네이버쇼핑",
                    name=name,
                    price=_to_int(item.get("lprice")),
                    image_url=image or None,
                    product_url=url,
                    review_average=None,
                    review_count=None,
                    keyword=keyword,
                )
            )
        self.last_error = None
        return products

    def search_many(self, keywords: list[str], hits_per_keyword: int = 4) -> list[NaverProduct]:
        seen: set[str] = set()
        products: list[NaverProduct] = []
        for keyword in keywords:
            items = self.search(keyword, hits=hits_per_keyword)
            if not items:
                # 접두 한정어(예: 톤 토큰 '웜톤')로 과도하게 좁혀 0건이면 첫 토큰을 떼고 재시도.
                parts = keyword.split()
                if len(parts) >= 3:
                    items = self.search(" ".join(parts[1:]), hits=hits_per_keyword)
            for item in items:
                if item.product_url in seen:
                    continue
                seen.add(item.product_url)
                products.append(item)
        return products


def _to_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
