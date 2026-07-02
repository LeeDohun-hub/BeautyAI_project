import json
from urllib.parse import quote_plus

from sqlalchemy.orm import Session, selectinload

from app.models import Ingredient, Product, ProductIngredient, RecommendationHistory, SkinAnalysis, Survey
from app.services.platform_availability import unavailable_platforms_bulk
from app.services.skincare_ingredient_knowledge import (
    build_skincare_recommendation_hint,
    skincare_recommendation_context,
)
from app.schemas.api import (
    BodyConditionScore,
    IngredientOut,
    ProductOut,
    RecommendationResponse,
    SkinScores,
    SurveyInput,
)


TARGET_LABELS = {
    "acne": "트러블",
    "pore": "모공",
    "wrinkle": "주름",
    "redness": "홍조",
    "pigmentation": "색소침착",
    "oiliness": "유분",
}

SKIN_TYPE_LABELS = {
    "dry": "건성",
    "oily": "지성",
    "combination": "복합성",
    "normal": "중성",
    "sensitive": "민감성",
}

# 한국어 고민 → DB 성분 타깃 매핑
CONCERN_TARGET_MAP: dict[str, list[str]] = {
    "트러블": ["acne"], "모공": ["pore"], "주름": ["wrinkle"], "홍조": ["redness"],
    "색소침착": ["pigmentation"], "유분": ["oiliness"], "칙칙함": ["pigmentation"],
    "다크서클": ["wrinkle", "pigmentation"], "탄력저하": ["wrinkle"],
    "유분·번들거림": ["oiliness"], "면도 후 자극": ["redness"],
    # 피부 건강 고민 (성별 공통)
    "건조·수분부족": ["redness"], "기미·주근깨": ["pigmentation"],
    "피부장벽": ["redness"], "예민함": ["redness"], "화끈거림": ["redness"],
    "자극": ["redness"], "아토피": ["redness"], "알레르기": ["redness"],
    # 메이크업 베이스 고민
    "파운데이션 밀림": ["oiliness"], "들뜸": ["redness"],
    "지속력": ["oiliness"], "커버력": ["redness"],
    "다크닝": ["oiliness"], "피부톤": ["pigmentation"], "속건조": ["redness"],
    "광택": ["oiliness"], "잡티 커버": ["pigmentation"],
    "홍조 커버": ["redness"], "모공 커버": ["pore"],
    # 부위별 케어
    "눈가": ["wrinkle"], "입술": ["redness"], "목·데콜테": ["wrinkle", "pigmentation"],
    "코": ["pore", "oiliness"], "턱": ["acne"], "이마": ["acne", "oiliness"], "볼": ["redness"],
    # backward compat (영문 코드)
    "acne": ["acne"], "pore": ["pore"], "wrinkle": ["wrinkle"],
    "redness": ["redness"], "pigmentation": ["pigmentation"], "oiliness": ["oiliness"],
}

AGE_PRIORITY_MAP: dict[str, list[str]] = {
    "10s": ["acne", "oiliness"],
    "20s": ["acne", "pore"],
    "30s": ["pigmentation", "redness"],
    "40s": ["wrinkle", "pigmentation"],
    "50s": ["wrinkle"],
}

PLATFORM_ALIASES = {
    "all": "all",
    "amazon": "amazon_jp",
    "amazon_en": "amazon_us",
    "amazon_us": "amazon_us",
    "amazon_jp": "amazon_jp",
    "naver": "naver",
    "matsukiyo": "matsukiyo",
    "oliveyoung": "oliveyoung",
    "rakuten": "rakuten",
}

KBEAUTY_BRANDS = {
    "bioheal", "wakemake", "cosrx", "innisfree", "anua", "tirtir", "medicube",
    "beauty of joseon", "round lab", "torriden", "numbuzin", "skin1004", "mixsoon",
    "laneige", "sulwhasoo", "etude", "missha", "some by mi", "isntree", "purito",
    "rom&nd", "romand", "peripera", "clio", "dr.jart", "dr jart", "manyo", "abib",
    "axis-y", "heimish", "klairs", "d.alba", "mediheal", "goodal", "hince", "espoir",
    "ma:nyo", "beplain", "celimax", "skinfood", "the face shop",
}

JBEAUTY_BRANDS = {
    "shiseido", "senka", "hada labo", "hadalabo", "rohto", "melano cc", "biore",
    "kose", "kanebo", "d program", "naturie", "minon", "muji", "anessa", "curél",
    "curel", "dhc", "fancl", "transino", "sofina", "ipsa", "elixir", "canmake",
}

BODY_SAFE_INGREDIENT_PRIORITY = [
    "Ceramide",
    "Panthenol",
    "Hyaluronic Acid",
    "Centella Asiatica",
    "Green Tea",
]
BODY_SAFE_INGREDIENTS = set(BODY_SAFE_INGREDIENT_PRIORITY)
BODY_AVOID_INGREDIENTS = {
    "Retinol",
    "Salicylic Acid",
    "Glycolic Acid",
    "Lactic Acid",
    "Vitamin C",
}
BODY_CARE_CATEGORIES = {"cream", "lotion", "moisturizer", "moisturizers", "balm"}
BODY_AVOID_PRODUCT_TERMS = {
    "toner",
    "cleanser",
    "cleansing",
    "patch",
    "mask",
    "eye ",
    "sun ",
    "sunscreen",
    "serum",
    "ampoule",
    "mist",
}


def normalize_platform(platform: str | None) -> str:
    return PLATFORM_ALIASES.get((platform or "all").strip().lower(), "all")


def _brand_text(product: Product) -> str:
    return (product.brand.name if product.brand else "").lower()


def _has_brand(product: Product, brands: set[str]) -> bool:
    brand = _brand_text(product)
    return any(name in brand for name in brands)


def is_kbeauty(product: Product) -> bool:
    return _has_brand(product, KBEAUTY_BRANDS)


def is_jbeauty(product: Product) -> bool:
    return _has_brand(product, JBEAUTY_BRANDS)


def build_platform_links(product: Product) -> dict[str, str]:
    query = quote_plus(f"{product.brand.name} {product.name}".strip())
    product_url = product.product_url or ""
    links = {
        "amazon_us": f"https://www.amazon.com/s?k={query}",
        "amazon_jp": f"https://www.amazon.co.jp/s?k={query}",
        "naver": f"https://search.shopping.naver.com/search/all?query={query}",
        "matsukiyo": f"https://www.matsukiyococokara-online.com/search?text={query}",
        "oliveyoung": f"https://global.oliveyoung.com/display/search?query={query}",
    }
    if "amazon.co.jp" in product_url:
        links["amazon_jp"] = product_url
    elif "amazon." in product_url:
        links["amazon_us"] = product_url
    elif "oliveyoung." in product_url:
        links["oliveyoung"] = product_url
    elif "naver." in product_url:
        links["naver"] = product_url
    elif "matsukiyococokara" in product_url:
        links["matsukiyo"] = product_url
    return links


def matched_platforms(product: Product) -> list[str]:
    product_url = (product.product_url or "").lower()

    # 일본 채널(Amazon JP·마츠키요)은 실제 상품 URL이 그 플랫폼을 가리킬 때만
    # 노출한다. 예전에는 "K/J-뷰티 브랜드면 일본 채널에도 있겠지"라고 추측해 버튼을
    # 붙였으나(실 입점 아님), 실제 마츠키요 상품은 matsukiyococokara URL을 갖고 있으므로
    # 추측 없이도 정확히 매칭된다.
    #
    # 반대로 일본(마츠키요/J-뷰티) 상품은 한국·미국 글로벌 채널(올리브영·Amazon US·네이버)
    # 기본 노출에서 제외한다. 일본 드럭스토어 상품이 올리브영/Amazon US에 있을 가능성은
    # 낮기 때문. 그 외(K-뷰티·글로벌) 상품은 종전처럼 기본 세트를 유지한다.
    is_japanese = (
        "matsukiyococokara" in product_url
        or "amazon.co.jp" in product_url
        or is_jbeauty(product)
    )
    matches: set[str] = set() if is_japanese else {"amazon_us", "naver", "oliveyoung"}

    if "amazon.co.jp" in product_url:
        matches.add("amazon_jp")
    elif "amazon." in product_url:
        matches.add("amazon_us")
    if "oliveyoung." in product_url or is_kbeauty(product):
        matches.add("oliveyoung")
    if "matsukiyococokara" in product_url:
        matches.add("matsukiyo")
    if "naver." in product_url:
        matches.add("naver")
    return sorted(matches)


# 평점이 없는(미수집) 상품을 0점으로 묻지 않기 위한 중립 평점 점수.
# 평점이 있는 상품은 평균 4.47 → 약 8.9점을 받으므로, 미수집 상품은 0이 아닌
# 중간값을 주어 부당하게 하위로 밀리지 않게 한다(단, 고평점 상품보다는 낮게).
NEUTRAL_RATING_SCORE = 6.0


def rating_score_for(product: Product) -> float:
    if product.avg_rating and product.avg_rating > 0:
        return min(10.0, product.avg_rating * 2.0)
    return NEUTRAL_RATING_SCORE


def platform_fit_score(product: Product, platform: str) -> float:
    product_url = (product.product_url or "").lower()
    matches = matched_platforms(product)
    if platform == "all":
        # URL이 있는 실 상품은 매칭 플랫폼 '개수'와 무관하게 동일한 기본 적합도를 준다.
        # 단일 플랫폼 상품(예: 마츠키요)이 다채널 상품(K-뷰티)에 구조적으로 밀리지 않도록.
        if product.product_url:
            return 8.0
        return 5.0 if matches else 0.0
    if platform not in matches:
        return -1000.0
    direct_markers = {
        "amazon_us": "amazon.",
        "amazon_jp": "amazon.co.jp",
        "naver": "naver.",
        "matsukiyo": "matsukiyococokara",
        "oliveyoung": "oliveyoung.",
    }
    direct_bonus = 8.0 if direct_markers.get(platform, "") in product_url else 0.0
    curated_bonus = 4.0 if platform in {"oliveyoung", "matsukiyo"} and (is_kbeauty(product) or is_jbeauty(product)) else 0.0
    return direct_bonus + curated_bonus


REGION_PLATFORMS: dict[str, set[str]] = {
    "jp": {"amazon_jp", "matsukiyo", "oliveyoung"},
    "kr": {"amazon_us", "naver", "oliveyoung"},
}

PERSONAL_COLOR_MAKEUP_TERMS = {
    "lip", "lips", "lipstick", "tint", "rouge", "gloss", "balm",
    "blush", "blusher", "cheek",
    "eye", "eyeshadow", "shadow", "palette", "mascara", "liner",
    "base", "foundation", "cushion", "concealer", "primer", "powder",
    "リップ", "ティント", "チーク", "アイシャドウ", "ファンデーション",
}

PERSONAL_COLOR_SKINCARE_TERMS = {
    "serum", "toner", "essence", "cream", "moisturizer", "cleanser",
    "treatment", "retinol", "niacinamide", "bha", "aha", "mucin",
    "hyaluronic", "sunscreen", "mask", "ampoule",
    # 스킨케어 누출 차단(예: "Under Eye Patch"의 eye, 콜라겐 패드 등이 메이크업으로 오분류됨).
    "patch", "pad", "collagen", "peptide", "pdrn", "hydrogel",
    "hydrating", "vitalizing", "dark spot", "wrinkle", "lotion", "emulsion",
}

REASON_TARGET_LABELS = {
    "acne": "여드름 케어",
    "pore": "모공/피지",
    "wrinkle": "탄력/주름",
    "redness": "진정/홍조",
    "pigmentation": "톤/색소",
    "oiliness": "유분 밸런스",
}

PERSONAL_COLOR_CATEGORY_TERMS: dict[str, set[str]] = {
    "lip": {"lip", "lips", "lipstick", "tint", "rouge", "gloss", "balm", "リップ", "ルージュ", "ティント"},
    "blush": {"blush", "blusher", "cheek", "チーク"},
    "eye": {"eye", "eyeshadow", "shadow", "palette", "mascara", "liner", "kajal", "アイシャドウ", "アイライナー", "マスカラ"},
    "base": {"base", "foundation", "cushion", "concealer", "primer", "powder", "shading", "ファンデーション", "コンシーラー", "パウダー"},
}

PERSONAL_COLOR_COLOR_TERMS = {
    "warm", "cool", "light", "bright", "soft", "muted", "deep",
    "spring", "summer", "autumn", "winter",
    "coral", "peach", "pink", "rose", "mauve", "berry", "red", "brick",
    "terracotta", "orange", "beige", "brown", "ivory", "nude", "plum",
    "wine", "lavender", "cherry", "chocolate", "caramel", "mocha",
    "코랄", "피치", "핑크", "로즈", "브라운", "베이지", "아이보리", "레드",
    "체리", "초콜릿", "카라멜", "모카", "플럼", "와인", "라벤더",
    "コーラル", "ピーチ", "ピンク", "ローズ", "ブラウン", "ベージュ",
    "アイボリー", "レッド", "チェリー", "チョコレート", "カラメル", "モカ",
    "プラム", "ワイン", "ラベンダー",
}

TOKEN_ALIASES = {
    "リップ": "lip",
    "ルージュ": "lip",
    "ティント": "tint",
    "チーク": "blush",
    "アイシャドウ": "eyeshadow",
    "アイライナー": "liner",
    "ファンデーション": "foundation",
    "コーラル": "coral",
    "ピーチ": "peach",
    "ピンク": "pink",
    "ローズ": "rose",
    "ブラウン": "brown",
    "ベージュ": "beige",
    "アイボリー": "ivory",
    "レッド": "red",
    "체리": "cherry",
    "초콜릿": "chocolate",
    "카라멜": "caramel",
    "모카": "mocha",
    "코랄": "coral",
    "피치": "peach",
    "핑크": "pink",
    "로즈": "rose",
    "브라운": "brown",
    "베이지": "beige",
    "레드": "red",
}

PERSONAL_COLOR_CATALOG = [
    {
        "brand": "rom&nd",
        "name": "Juicy Lasting Tint Coral Series",
        "category": "lip",
        "price": 1320,
        "keywords": {"lip", "tint", "coral", "pink", "peach", "warm", "リップ"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "peripera",
        "name": "Ink Mood Glowy Tint",
        "category": "lip",
        "price": 1210,
        "keywords": {"lip", "tint", "rose", "coral", "pink", "cool", "リップ"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "CLIO",
        "name": "Pro Eye Palette",
        "category": "eye",
        "price": 2890,
        "keywords": {"eye", "eyeshadow", "shadow", "palette", "brown", "beige", "アイシャドウ"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "WAKEMAKE",
        "name": "Soft Blurring Eye Palette",
        "category": "eye",
        "price": 2980,
        "keywords": {"eye", "eyeshadow", "shadow", "palette", "brown", "beige", "アイシャドウ"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "peripera",
        "name": "Pure Blushed Sunshine Cheek",
        "category": "blush",
        "price": 1100,
        "keywords": {"blush", "blusher", "cheek", "coral", "pink", "peach", "チーク"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "rom&nd",
        "name": "Better Than Cheek",
        "category": "blush",
        "price": 1200,
        "keywords": {"blush", "blusher", "cheek", "rose", "pink", "muted", "チーク"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "espoir",
        "name": "Pro Tailor Foundation Be Velvet",
        "category": "base",
        "price": 3300,
        "keywords": {"base", "foundation", "ivory", "beige", "yellow", "ファンデーション"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "TIRTIR",
        "name": "Mask Fit Red Cushion",
        "category": "base",
        "price": 2970,
        "keywords": {"base", "foundation", "cushion", "ivory", "beige", "ファンデーション"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "CANMAKE",
        "name": "Cream Cheek",
        "category": "blush",
        "price": 638,
        "keywords": {"blush", "blusher", "cheek", "coral", "pink", "チーク"},
        "platforms": {"amazon_jp", "matsukiyo"},
    },
    {
        "brand": "CEZANNE",
        "name": "Natural Cheek N",
        "category": "blush",
        "price": 396,
        "keywords": {"blush", "blusher", "cheek", "coral", "pink", "チーク"},
        "platforms": {"amazon_jp", "matsukiyo"},
    },
    {
        "brand": "KATE",
        "name": "Designing Brown Eyes",
        "category": "eye",
        "price": 1320,
        "keywords": {"eye", "eyeshadow", "shadow", "brown", "beige", "アイシャドウ"},
        "platforms": {"amazon_jp", "matsukiyo"},
    },
    {
        "brand": "CANMAKE",
        "name": "Shading Powder",
        "category": "base",
        "price": 748,
        "keywords": {"base", "shading", "brown", "beige", "powder"},
        "platforms": {"amazon_jp", "matsukiyo"},
    },
]


def _keyword_fit_score(product: Product, keywords: list[str]) -> float:
    haystack = " ".join(
        [
            product.brand.name if product.brand else "",
            product.name or "",
            product.category or "",
            product.description or "",
        ]
    ).lower()
    if not keywords:
        return 4.0

    score = 0.0
    for keyword in keywords:
        normalized = keyword.strip().lower()
        if not normalized:
            continue
        tokens = [token for token in normalized.replace("/", " ").split() if len(token) >= 2]
        if normalized in haystack:
            score += 8.0
            continue
        score += min(6.0, sum(1.5 for token in tokens if token in haystack))
    return min(16.0, score)


def _tokens_from_text(text: str) -> set[str]:
    raw_tokens = {
        token
        for token in text.lower().replace("/", " ").replace("-", " ").split()
        if len(token) >= 2
    }
    raw_tokens.update(
        alias
        for original, alias in TOKEN_ALIASES.items()
        if original.lower() in text.lower()
    )
    return raw_tokens


def _keyword_tokens(keywords: list[str]) -> set[str]:
    tokens: set[str] = set()
    for keyword in keywords:
        tokens.update(_tokens_from_text(keyword))
    return tokens


def _category_tokens(tokens: set[str]) -> set[str]:
    return {
        category
        for category, terms in PERSONAL_COLOR_CATEGORY_TERMS.items()
        if tokens.intersection({term.lower() for term in terms})
    }


def _color_tokens(tokens: set[str]) -> set[str]:
    normalized_colors = {term.lower() for term in PERSONAL_COLOR_COLOR_TERMS}
    return tokens.intersection(normalized_colors)


def personal_color_fit_score_for_text(
    brand: str,
    name: str,
    category: str,
    description: str,
    keywords: list[str],
    platform_score: float = 0.0,
    rating_score: float = 0.0,
) -> float:
    query_tokens = _keyword_tokens(keywords)
    product_tokens = _tokens_from_text(" ".join([brand, name, category, description]))
    if not query_tokens:
        return round(min(99.0, 40.0 + platform_score + rating_score), 1)

    query_categories = _category_tokens(query_tokens)
    product_categories = _category_tokens(product_tokens.union(_tokens_from_text(category)))
    query_colors = _color_tokens(query_tokens)
    product_colors = _color_tokens(product_tokens)

    overlap = query_tokens.intersection(product_tokens)
    color_overlap = query_colors.intersection(product_colors)
    category_overlap = query_categories.intersection(product_categories)

    category_score = 18.0 if category_overlap else 0.0
    color_score = min(28.0, len(color_overlap) * 7.0)
    token_score = min(18.0, len(overlap) * 2.4)
    tone_score = min(10.0, len(overlap.intersection({"warm", "cool", "light", "deep", "soft", "bright", "muted"})) * 3.5)

    total = 30.0 + category_score + color_score + token_score + tone_score + min(8.0, platform_score) + min(7.0, rating_score)
    return round(min(99.0, total), 1)


def _is_personal_color_makeup_product(product: Product) -> bool:
    text = " ".join(
        [
            product.brand.name if product.brand else "",
            product.name or "",
            product.category or "",
            product.description or "",
        ]
    ).lower()
    if any(term in text for term in PERSONAL_COLOR_SKINCARE_TERMS):
        return False
    return any(term in text for term in PERSONAL_COLOR_MAKEUP_TERMS)


def _visible_product_platforms(product: Product, region: str, platform: str) -> list[str]:
    allowed = REGION_PLATFORMS.get(region, set().union(*REGION_PLATFORMS.values()))
    matches = set(matched_platforms(product)).intersection(allowed)
    if platform != "all":
        matches = matches.intersection({platform})
    return sorted(matches)


def _search_link(platform: str, brand: str, name: str) -> str:
    query = quote_plus(f"{brand} {name}".strip())
    links = {
        "amazon_us": f"https://www.amazon.com/s?k={query}",
        "amazon_jp": f"https://www.amazon.co.jp/s?k={query}",
        "naver": f"https://search.shopping.naver.com/search/all?query={query}",
        "oliveyoung": f"https://global.oliveyoung.com/display/search?query={query}",
        "matsukiyo": f"https://www.matsukiyococokara-online.com/search?text={query}",
    }
    return links[platform]


def _catalog_keyword_score(item: dict, keywords: list[str]) -> float:
    return personal_color_fit_score_for_text(
        str(item["brand"]),
        str(item["name"]),
        str(item["category"]),
        " ".join(item["keywords"]),
        keywords,
    )


def _curated_personal_color_products(
    keywords: list[str],
    region: str,
    platform: str,
    limit: int,
) -> list[ProductOut]:
    allowed = REGION_PLATFORMS.get(region, set().union(*REGION_PLATFORMS.values()))
    rows: list[tuple[float, dict, list[str]]] = []
    for index, item in enumerate(PERSONAL_COLOR_CATALOG, start=1):
        platforms = sorted(set(item["platforms"]).intersection(allowed))
        if platform != "all":
            platforms = [item_platform for item_platform in platforms if item_platform == platform]
        if not platforms:
            continue
        platform_score = 9.0 if platform != "all" else 7.0
        brand_bonus = 2.0 if str(item["brand"]).lower() in KBEAUTY_BRANDS.union(JBEAUTY_BRANDS) else 0.0
        score = round(
            min(
                99.0,
                _catalog_keyword_score(item, keywords) + platform_score + brand_bonus,
            ),
            1,
        )
        rows.append((score, {**item, "_id": index}, platforms))

    return [
        ProductOut(
            id=-int(item["_id"]),
            brand=str(item["brand"]),
            name=str(item["name"]),
            category=str(item["category"]),
            price=int(item["price"]),
            score=score,
            description="Personal color makeup catalog match.",
            ingredients=[],
            product_url=_search_link(platforms[0], str(item["brand"]), str(item["name"])),
            platform_links={
                item_platform: _search_link(item_platform, str(item["brand"]), str(item["name"]))
                for item_platform in platforms
            },
            matched_platforms=platforms,
            image_url=None,
            avg_rating=None,
            review_count=None,
        )
        for score, item, platforms in sorted(rows, key=lambda row: row[0], reverse=True)[:limit]
    ]


def recommend_personal_color_products(
    db: Session,
    keywords: list[str],
    region: str = "jp",
    platform: str = "all",
    limit: int = 8,
) -> list[ProductOut]:
    region = (region or "jp").strip().lower()
    platform = normalize_platform(platform)
    allowed_platforms = REGION_PLATFORMS.get(region, set().union(*REGION_PLATFORMS.values()))

    products = db.query(Product).options(
        selectinload(Product.brand),
        selectinload(Product.ingredients).selectinload(ProductIngredient.ingredient),
    ).all()

    scored: list[tuple[float, float, Product, list[str]]] = []
    for product in products:
        if not _is_personal_color_makeup_product(product):
            continue
        visible_platforms = _visible_product_platforms(product, region, platform)
        if not visible_platforms:
            continue

        if platform == "all":
            platform_score = max(platform_fit_score(product, item) for item in visible_platforms)
        else:
            if platform not in allowed_platforms:
                continue
            platform_score = platform_fit_score(product, platform)
            if platform_score < 0:
                continue

        rating_score = rating_score_for(product)
        total = personal_color_fit_score_for_text(
            product.brand.name if product.brand else "",
            product.name or "",
            product.category or "",
            product.description or "",
            keywords,
            platform_score=platform_score,
            rating_score=rating_score,
        )
        scored.append((total, platform_score, product, visible_platforms))

    top_products = sorted(
        scored,
        key=lambda item: (item[0], item[1], item[2].review_count or 0, item[2].avg_rating or 0.0),
        reverse=True,
    )[:limit]

    hidden_map = unavailable_platforms_bulk(
        (product.id, product.brand.name, product.name, set(platforms))
        for _score, _platform_score, product, platforms in top_products
    )

    db_results = [
        ProductOut(
            id=product.id,
            brand=product.brand.name,
            name=product.name,
            category=product.category,
            price=product.price,
            score=score,
            description=product.description,
            ingredients=[item.ingredient.name for item in product.ingredients],
            product_url=product.product_url,
            platform_links={
                key: value
                for key, value in build_platform_links(product).items()
                if key in platforms and key not in hidden_map.get(product.id, set())
            },
            matched_platforms=[
                key for key in platforms if key not in hidden_map.get(product.id, set())
            ],
            image_url=product.image_url,
            avg_rating=product.avg_rating or None,
            review_count=product.review_count or None,
        )
        for score, _platform_score, product, platforms in top_products
    ]
    catalog_results = _curated_personal_color_products(
        keywords,
        region,
        platform,
        max(0, limit - len(db_results)),
    )
    return (db_results + catalog_results)[:limit]


def infer_ingredients(db: Session, scores: SkinScores, survey: SurveyInput) -> list[Ingredient]:
    score_map = scores.model_dump()
    priorities: set[str] = {name for name, score in score_map.items() if score >= 45}

    all_concerns = (
        list(survey.concerns)
        + list(survey.makeup_concerns)
        + list(survey.area_concerns)
        + list(survey.male_extras)
    )
    for concern in all_concerns:
        for target in CONCERN_TARGET_MAP.get(concern, [concern.lower()]):
            priorities.add(target)

    for target in AGE_PRIORITY_MAP.get(survey.age_group, []):
        priorities.add(target)

    if survey.sensitivity >= 4:
        priorities.add("redness")
    if survey.skin_type in {"oily", "combination"}:
        priorities.add("oiliness")
        priorities.add("pore")

    ingredients = db.query(Ingredient).all()
    ranked = sorted(
        ingredients,
        key=lambda ingredient: len(priorities.intersection(set(ingredient.targets.split(",")))),
        reverse=True,
    )
    return [ingredient for ingredient in ranked if priorities.intersection(set(ingredient.targets.split(",")))][:5]


def recommend_products(
    db: Session,
    scores: SkinScores,
    survey: SurveyInput,
    analysis_id: int | None,
    user_id: int | None,
    platform: str = "all",
    analysis_mode: str = "face",
    body_conditions: list[BodyConditionScore] | None = None,
) -> RecommendationResponse:
    platform = normalize_platform(platform)
    body_conditions = body_conditions or []
    if analysis_mode == "body":
        ingredients = (
            db.query(Ingredient)
            .filter(Ingredient.name.in_(BODY_SAFE_INGREDIENTS))
            .all()
        )
        ingredients.sort(
            key=lambda ingredient: BODY_SAFE_INGREDIENT_PRIORITY.index(ingredient.name)
            if ingredient.name in BODY_SAFE_INGREDIENTS
            else 999
        )
    else:
        ingredients = infer_ingredients(db, scores, survey)
    ingredient_targets = {target for ingredient in ingredients for target in ingredient.targets.split(",")}

    knowledge_match = None
    knowledge_targets: set[str] = set()
    knowledge_note = ""
    if analysis_mode != "body":
        knowledge_context = {"survey": survey.model_dump(), "scores": scores.model_dump()}
        knowledge_match, knowledge_targets, knowledge_note = skincare_recommendation_context(
            " ".join(sorted(ingredient_targets)),
            knowledge_context,
        )

    products = db.query(Product).options(
        selectinload(Product.brand),
        selectinload(Product.ingredients).selectinload(ProductIngredient.ingredient),
    ).all()
    scored: list[tuple[float, float, Product, list[str], str | None]] = []
    for product in products:
        platform_score = platform_fit_score(product, platform)
        if platform_score < 0:
            continue
        product_targets = {
            target
            for product_ingredient in product.ingredients
            for target in product_ingredient.ingredient.targets.split(",")
        }
        product_ingredient_names = {
            product_ingredient.ingredient.name for product_ingredient in product.ingredients
        }
        if analysis_mode == "body":
            if product_ingredient_names.intersection(BODY_AVOID_INGREDIENTS):
                continue
            category = (product.category or "").strip().lower()
            if category not in BODY_CARE_CATEGORIES:
                continue
            product_name = (product.name or "").lower()
            if any(term in product_name for term in BODY_AVOID_PRODUCT_TERMS):
                continue
            if survey.gender == "female" and "for men" in product_name:
                continue
            safe_matches = len(product_ingredient_names.intersection(BODY_SAFE_INGREDIENTS))
            if safe_matches == 0:
                continue
            skin_type_match = 8 if survey.skin_type in product.skin_types or "all" in product.skin_types else 0
            rating_score = rating_score_for(product)
            total = round(
                min(
                    99.0,
                    20
                    + safe_matches * 12
                    + skin_type_match
                    + platform_score
                    + rating_score,
                ),
                1,
            )
            reason_tags = [f"{safe_matches}개 바디 진정 성분", "바디 보습 카테고리"]
            evidence_note = None
        else:
            matched_targets = ingredient_targets.intersection(product_targets)
            ingredient_match = len(matched_targets) * 6
            skin_type_match = 8 if survey.skin_type in product.skin_types or "all" in product.skin_types else 0
            concern_match = sum(scores.model_dump().get(target, 0) for target in product_targets) / max(1, len(product_targets)) * 0.35
            knowledge_overlap = knowledge_targets.intersection(product_targets)
            knowledge_bonus = min(10.0, len(knowledge_overlap) * 5.0)
            rating_score = rating_score_for(product)
            total = round(
                min(
                    99.0,
                    ingredient_match
                    + skin_type_match
                    + concern_match
                    + knowledge_bonus
                    + platform_score
                    + rating_score,
                ),
                1,
            )
            reason_tags = [
                REASON_TARGET_LABELS.get(target, target)
                for target in sorted(matched_targets.union(knowledge_overlap))
            ][:4]
            if skin_type_match:
                reason_tags.append("피부 타입 적합")
            if platform_score >= 8:
                reason_tags.append("선택 플랫폼 매칭")
            evidence_note = knowledge_note if knowledge_overlap and knowledge_match else None
        scored.append((total, platform_score, product, reason_tags, evidence_note))

    # When a specific platform is requested, prefer products that actually live on
    # that platform (higher platform_fit_score) before falling back to rating, so
    # e.g. platform=matsukiyo surfaces real Matsukiyo products over merely curated
    # regional ones that happen to tie at the score cap.
    top_products = sorted(
        scored,
        key=lambda item: (item[0], item[1], item[2].avg_rating or 0.0),
        reverse=True,
    )[:5]
    ingredient_names = [ingredient.name for ingredient in ingredients]
    product_names = [product.name for _, _, product, _reason_tags, _evidence_note in top_products]

    if user_id or analysis_id:
        db.add(Survey(user_id=user_id, skin_type=survey.skin_type, concerns=",".join(survey.concerns), sensitivity=survey.sensitivity, routine_level=survey.routine_level))
    history = RecommendationHistory(
        user_id=user_id,
        analysis_id=analysis_id,
        recommended_ingredients=json.dumps(ingredient_names),
        recommended_products=json.dumps(product_names),
    )
    db.add(history)
    db.commit()
    db.refresh(history)

    # 후보 플랫폼을 미리 구한 뒤, 실시간 입점 확인으로 '실제 없는' 곳만 숨긴다.
    matched_map = {product.id: matched_platforms(product) for _s, _ps, product, _reason_tags, _evidence_note in top_products}
    hidden_map = unavailable_platforms_bulk(
        (product.id, product.brand.name, product.name, set(matched_map[product.id]))
        for _s, _ps, product, _reason_tags, _evidence_note in top_products
    )

    explanation = (
        build_body_explanation(body_conditions, ingredient_names, product_names)
        if analysis_mode == "body"
        else build_explanation(scores, survey, ingredient_names, product_names)
    )
    if analysis_mode != "body":
        context = {
            "survey": survey.model_dump(),
            "scores": scores.model_dump(),
        }
        hint = build_skincare_recommendation_hint(" ".join(ingredient_targets), context)
        if hint:
            explanation = f"{explanation} {hint}"

    return RecommendationResponse(
        history_id=history.id,
        ingredients=[
            IngredientOut(id=ingredient.id, name=ingredient.name, benefit=ingredient.benefit, targets=ingredient.targets.split(","))
            for ingredient in ingredients
        ],
        products=[
            ProductOut(
                id=product.id,
                brand=product.brand.name,
                name=product.name,
                category=product.category,
                price=product.price,
                score=score,
                description=product.description,
                ingredients=[item.ingredient.name for item in product.ingredients],
                product_url=product.product_url,
                platform_links=build_platform_links(product),
                matched_platforms=[
                    platform
                    for platform in matched_map[product.id]
                    if platform not in hidden_map.get(product.id, set())
                ],
                image_url=product.image_url,
                avg_rating=product.avg_rating or None,
                review_count=product.review_count or None,
                reason_tags=reason_tags,
                evidence_note=evidence_note,
            )
            for score, _platform_score, product, reason_tags, evidence_note in top_products
        ],
        explanation=explanation,
    )


def build_body_explanation(
    body_conditions: list[BodyConditionScore],
    ingredients: list[str],
    products: list[str],
) -> str:
    if body_conditions:
        top = body_conditions[0]
        result = f"{top.label} 가능성 {top.probability:.1f}%"
    else:
        result = "몸 피부 설문 정보"
    return (
        f"{result}를 기준으로 피부 장벽과 보습 중심의 성분 "
        f"{', '.join(ingredients[:3])}을 우선했습니다. "
        "자극 가능성이 있는 레티놀과 AHA/BHA 성분 제품은 제외했습니다. "
        f"추천 제품은 {', '.join(products[:3])}입니다."
    )


def build_explanation(scores: SkinScores, survey: SurveyInput, ingredients: list[str], products: list[str]) -> str:
    score_map = scores.model_dump()
    top_scores = sorted(score_map.items(), key=lambda item: item[1], reverse=True)[:3]
    priorities = ", ".join(f"{TARGET_LABELS[name]} {value:.0f}" for name, value in top_scores)
    skin_type = SKIN_TYPE_LABELS.get(survey.skin_type, survey.skin_type)
    age_label = {"10s": "10대", "20s": "20대", "30s": "30대", "40s": "40대", "50s": "50대 이상"}.get(survey.age_group, "")
    gender_label = "여성" if survey.gender == "female" else "남성"
    context = f"{age_label} {gender_label}, {skin_type} 피부" if age_label else f"{gender_label}, {skin_type} 피부"
    return (
        f"가장 두드러진 피부 신호는 {priorities}입니다. {context}와 선택한 고민을 기준으로 "
        f"{', '.join(ingredients[:3])} 성분을 우선 추천했습니다. 추천 제품은 {', '.join(products[:3])} 등입니다."
    )


def get_scores_from_analysis(db: Session, analysis_id: int) -> SkinScores:
    analysis = db.get(SkinAnalysis, analysis_id)
    if analysis is None:
        raise ValueError("analysis_id not found")
    return SkinScores(
        acne=analysis.acne,
        pore=analysis.pore,
        wrinkle=analysis.wrinkle,
        redness=analysis.redness,
        pigmentation=analysis.pigmentation,
        oiliness=analysis.oiliness,
    )
