from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class RakutenProduct:
    id: str
    brand: str
    name: str
    price: int
    image_url: str | None
    product_url: str
    review_average: float | None
    review_count: int | None
    keyword: str


class RakutenClient:
    current_endpoint = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401"
    legacy_endpoint = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20170706"

    def __init__(self) -> None:
        settings = get_settings()
        self.app_id = settings.rakuten_app_id
        self.access_key = settings.rakuten_access_key
        self.referer = settings.rakuten_referer
        self.last_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.app_id)

    def search(self, keyword: str, hits: int = 6) -> list[RakutenProduct]:
        keyword = keyword.strip()
        if not keyword or not self.configured:
            return []

        errors: list[Exception] = []
        for endpoint, params in self._request_candidates(keyword, hits):
            try:
                response = httpx.get(endpoint, params=params, headers=self._headers(), timeout=8.0)
                response.raise_for_status()
                products = self._parse_items(response.json(), keyword)
                if products:
                    self.last_error = None
                    return products[:hits]
            except Exception as exc:  # noqa: BLE001 - provider failures should not break the app
                self.last_error = self._error_message(exc)
                errors.append(exc)
                continue
        return []

    def search_many(
        self, keywords: list[str], hits_per_keyword: int = 4, throttle: float = 0.0
    ) -> list[RakutenProduct]:
        """여러 키워드를 검색해 상품을 모은다(URL 기준 dedup).

        throttle>0 이면 요청 사이에 그만큼 sleep 한다. 라쿠텐 openapi 는 ~1req/s 로 429 를
        주므로(연속 발사하면 뒤쪽 키워드가 통째로 굶어 아이템매칭 컬럼이 빈다), 컬럼을 확정적으로
        채워야 하는 호출부는 throttle≈1.1 로 요청을 벌린다. 그래도 429 로 0건이 나온 키워드는
        간격을 두고 한 번 더 재시도해 컬럼 굶김을 없앤다.
        """
        import time

        seen: set[str] = set()
        products: list[RakutenProduct] = []
        empties: list[str] = []

        def _collect(items: list[RakutenProduct]) -> None:
            for item in items:
                if item.product_url in seen:
                    continue
                seen.add(item.product_url)
                products.append(item)

        for index, keyword in enumerate(keywords):
            if throttle and index:
                time.sleep(throttle)
            items = self.search(keyword, hits=hits_per_keyword)
            if not items:
                # 접두 한정어(예: 톤 토큰 'イエベ')로 과도하게 좁혀 0건이면 첫 토큰을 떼고 재시도.
                parts = keyword.split()
                if len(parts) >= 3:
                    items = self.search(" ".join(parts[1:]), hits=hits_per_keyword)
            if not items:
                empties.append(keyword)
            _collect(items)

        # 429 등으로 0건이던 키워드는 간격을 두고 한 번 더(그동안 rate-limit 이 회복됨).
        for keyword in empties:
            if throttle:
                time.sleep(throttle)
            _collect(self.search(keyword, hits=hits_per_keyword))
        return products

    def _request_candidates(self, keyword: str, hits: int) -> list[tuple[str, dict[str, str | int]]]:
        current_params: dict[str, str | int] = {
            "applicationId": self.app_id or "",
            "keyword": keyword,
            "format": "json",
            "formatVersion": 2,
            "hits": hits,
            "imageFlag": 1,
        }
        if self.access_key:
            return [(self.current_endpoint, current_params)]

        legacy_params: dict[str, str | int] = {
            "applicationId": self.app_id or "",
            "keyword": keyword,
            "format": "json",
            "formatVersion": 2,
            "hits": hits,
            "imageFlag": 1,
        }
        return [(self.current_endpoint, current_params), (self.legacy_endpoint, legacy_params)]

    def _headers(self) -> dict[str, str]:
        parsed = urlparse(self.referer)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else self.referer.rstrip("/")
        return {
            "Accept": "application/json",
            "Referer": self.referer,
            "Origin": origin,
            "User-Agent": "BeautyAI/0.1",
            **({"accessKey": self.access_key} if self.access_key else {}),
        }

    def _error_message(self, exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            try:
                payload = exc.response.json()
            except ValueError:
                return f"Rakuten HTTP {exc.response.status_code}"
            errors = payload.get("errors") if isinstance(payload, dict) else None
            if isinstance(errors, dict):
                return str(errors.get("errorMessage") or errors.get("errorCode") or payload)
            return str(payload)
        return str(exc)

    def _parse_items(self, payload: dict, keyword: str) -> list[RakutenProduct]:
        raw_items = payload.get("items") or payload.get("Items") or []
        products: list[RakutenProduct] = []
        for index, row in enumerate(raw_items):
            item = row.get("Item", row) if isinstance(row, dict) else {}
            if not isinstance(item, dict):
                continue
            name = str(item.get("itemName") or item.get("title") or "").strip()
            url = str(item.get("itemUrl") or item.get("affiliateUrl") or "").strip()
            if not name or not url:
                continue
            images = item.get("mediumImageUrls") or item.get("smallImageUrls") or []
            image_url = None
            if images:
                first = images[0]
                raw = first.get("imageUrl") if isinstance(first, dict) else str(first)
                image_url = _upsize_rakuten_image(raw)
            shop_name = str(item.get("shopName") or "Rakuten").strip()
            products.append(
                RakutenProduct(
                    id=str(item.get("itemCode") or item.get("itemId") or f"rakuten-{quote_plus(name)}-{index}"),
                    brand=shop_name,
                    name=name,
                    price=int(item.get("itemPrice") or 0),
                    image_url=image_url,
                    product_url=url,
                    review_average=_optional_float(item.get("reviewAverage")),
                    review_count=_optional_int(item.get("reviewCount")),
                    keyword=keyword,
                )
            )
        return products


_RAKUTEN_EX_RE = re.compile(r"_ex=\d+x\d+")


def _upsize_rakuten_image(url: object) -> str | None:
    """라쿠텐 썸네일 URL의 `_ex=128x128`을 더 큰 크기로 올려 카드 화질을 개선한다.

    thumbnail.image.rakuten.co.jp는 `_ex` 파라미터로 크기를 즉석 리사이즈하므로
    128x128 → 300x300으로 교체해도 유효한 이미지가 반환된다. `_ex`가 없거나
    다른 호스트면 원본을 그대로 둔다.
    """
    text = str(url or "").strip()
    if not text:
        return None
    return _RAKUTEN_EX_RE.sub("_ex=300x300", text)


def _optional_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _optional_int(value: object) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None
