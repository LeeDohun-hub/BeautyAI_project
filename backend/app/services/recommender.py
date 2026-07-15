import json
from urllib.parse import quote_plus

from sqlalchemy.orm import Session, selectinload

from app.models import Ingredient, Product, ProductIngredient, RecommendationHistory, SkinAnalysis, Survey
from app.services.derma_condition_care import (
    GUIDE_ONLY,
    OTC_INGREDIENTS,
    PRODUCTS,
    REFERRAL,
    care_for,
    load_otc_examples,
)
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
    "burgundy", "olive", "khaki", "camel", "charcoal", "navy", "silver",
    "gray", "grey", "fuchsia", "cinnamon", "champagne", "apricot", "sand",
    "dusty", "amber", "clear",
    "버건디", "올리브", "카키", "카멜", "차콜", "네이비", "실버", "그레이",
    "푸시아", "시나몬", "샴페인", "살구", "샌드", "브릭", "테라코타", "모브", "장미",
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
    "버건디": "burgundy",
    "올리브": "olive",
    "카키": "khaki",
    "카멜": "camel",
    "차콜": "charcoal",
    "네이비": "navy",
    "실버": "silver",
    "그레이": "gray",
    "푸시아": "fuchsia",
    "시나몬": "cinnamon",
    "샴페인": "champagne",
    "살구": "apricot",
    "샌드": "sand",
    "브릭": "brick",
    "테라코타": "terracotta",
    "모브": "mauve",
    "장미": "rose",
    "플럼": "plum",
    "와인": "wine",
    "라벤더": "lavender",
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
    # --- 딥/뮤트/브라이트 색 보강 (타입별 다양성) ---
    {
        "brand": "rom&nd",
        "name": "Zero Velvet Tint Burgundy",
        "category": "lip",
        "price": 1180,
        "keywords": {"lip", "tint", "burgundy", "wine", "plum", "cool", "deep", "リップ"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "MERZY",
        "name": "The First Velvet Tint Brick",
        "category": "lip",
        "price": 990,
        "keywords": {"lip", "tint", "brick", "terracotta", "orange", "warm", "deep", "リップ"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "rom&nd",
        "name": "Blur Fudge Tint Mauve Nude",
        "category": "lip",
        "price": 1210,
        "keywords": {"lip", "tint", "mauve", "rose", "nude", "muted", "soft", "リップ"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "3CE",
        "name": "Velvet Lip Tint Fuchsia",
        "category": "lip",
        "price": 1650,
        "keywords": {"lip", "tint", "fuchsia", "cherry", "red", "bright", "clear", "cool", "リップ"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "ETUDE",
        "name": "Lovely Cookie Blusher Mauve",
        "category": "blush",
        "price": 880,
        "keywords": {"blush", "cheek", "mauve", "rose", "dusty", "muted", "cool", "チーク"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "CLIO",
        "name": "Prism Air Blusher Plum",
        "category": "blush",
        "price": 1690,
        "keywords": {"blush", "cheek", "plum", "berry", "rose", "cool", "deep", "チーク"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "DASIQUE",
        "name": "Shadow Palette Olive Khaki",
        "category": "eye",
        "price": 2490,
        "keywords": {"eye", "eyeshadow", "palette", "olive", "khaki", "camel", "brown", "warm", "deep", "アイシャドウ"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "DASIQUE",
        "name": "Shadow Palette Mauve Gray",
        "category": "eye",
        "price": 2490,
        "keywords": {"eye", "eyeshadow", "palette", "mauve", "gray", "rose", "cool", "muted", "アイシャドウ"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "hince",
        "name": "New Depth Eyeshadow Palette Charcoal Navy",
        "category": "eye",
        "price": 2790,
        "keywords": {"eye", "eyeshadow", "palette", "charcoal", "navy", "silver", "cool", "deep", "アイシャドウ"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
    },
    {
        "brand": "espoir",
        "name": "Pro Tailor Cushion Cool Pink",
        "category": "base",
        "price": 3300,
        "keywords": {"base", "cushion", "foundation", "pink", "rose", "cool", "ivory", "ファンデーション"},
        "platforms": {"oliveyoung", "amazon_us", "amazon_jp", "matsukiyo", "naver"},
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


# 톤(warm/cool=톤축, light/deep/soft/bright/muted=뎁스 부사)은 hue(색상)가 아니다.
# 색상 오버랩에서 분리하지 않으면 "Light Reflecting Foundation"·"Deep Hydration"의
# light/deep가 퍼스널컬러 색상 매칭으로 오인돼, 웜/쿨 정반대인 봄·여름 추천이 겹친다.
PERSONAL_COLOR_TONE_TERMS = {"warm", "cool", "light", "bright", "soft", "muted", "deep"}
PERSONAL_COLOR_WARMCOOL_TERMS = {"warm", "cool"}
# 웜/쿨 상반 감점용 hue 그룹(중립색 beige/brown/pink/red 등은 어느 쪽도 아님 → 제외).
PERSONAL_COLOR_WARM_HUES = {
    "coral", "peach", "apricot", "terracotta", "brick", "camel", "caramel",
    "cinnamon", "amber", "olive", "khaki", "orange", "sand",
}
PERSONAL_COLOR_COOL_HUES = {
    "rose", "mauve", "lavender", "plum", "burgundy", "wine", "fuchsia",
    "berry", "navy", "silver", "charcoal",
}


def _color_tokens(tokens: set[str]) -> set[str]:
    # 톤 부사는 hue가 아니므로 색상 오버랩에서 제외(제품명 'Light/Deep' 오매칭 방지).
    normalized_colors = {term.lower() for term in PERSONAL_COLOR_COLOR_TERMS} - PERSONAL_COLOR_TONE_TERMS
    return tokens.intersection(normalized_colors)


def _warmcool_lean(tokens: set[str]) -> str | None:
    """토큰의 웜/쿨 성향(warm/cool 명시어 + hue 그룹)을 판정. 판단 불가 시 None."""
    warm = len(tokens.intersection(PERSONAL_COLOR_WARM_HUES))
    cool = len(tokens.intersection(PERSONAL_COLOR_COOL_HUES))
    if "warm" in tokens:
        warm += 2
    if "cool" in tokens:
        cool += 2
    if warm > cool:
        return "warm"
    if cool > warm:
        return "cool"
    return None


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
    # 톤축(warm/cool)과 뎁스축(light/deep/soft/bright/muted)을 각각 유의미하게 반영한다.
    # 뎁스 부사는 hue 색상매칭에서만 제외했을 뿐(더블카운트 방지), 서브톤(라이트/뮤트/딥/브라이트)
    # 구분에 필수라 tone_score에서는 제대로 가중한다. 크로스톤 붕괴는 아래 웜/쿨 게이트가 막는다.
    warmcool_overlap = overlap.intersection(PERSONAL_COLOR_WARMCOOL_TERMS)
    depth_overlap = overlap.intersection(PERSONAL_COLOR_TONE_TERMS - PERSONAL_COLOR_WARMCOOL_TERMS)
    tone_score = min(8.0, len(warmcool_overlap) * 4.0) + min(6.0, len(depth_overlap) * 3.0)

    # 웜/쿨 게이트: 쿼리와 제품의 톤 성향이 정반대면 감점(봄 추천에 쿨전용 상품이 오르는 것 방지).
    query_lean = _warmcool_lean(query_tokens)
    product_lean = _warmcool_lean(product_tokens)
    opposition_penalty = 12.0 if query_lean and product_lean and query_lean != product_lean else 0.0

    total = (
        30.0 + category_score + color_score + token_score + tone_score
        + min(8.0, platform_score) + min(7.0, rating_score) - opposition_penalty
    )
    return round(min(99.0, max(0.0, total)), 1)


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
    # 사용자의 '실제' 피부 고민 타깃 = 사진 점수가 유의미한 타깃 ∪ 설문에서 고른 고민 타깃.
    # 이걸로 랭킹을 몰아줘야 사진이 달라지면 추천도 달라진다(예전엔 infer_ingredients가
    # 사실상 6개 타깃 전부를 반환해 '타깃 많은 브로드 상품'만 상위 독식했다).
    score_map = scores.model_dump()
    user_concern_targets: set[str] = {name for name, value in score_map.items() if value >= 40}
    for concern in list(survey.concerns) + list(survey.makeup_concerns) + list(survey.area_concerns) + list(survey.male_extras):
        for target in CONCERN_TARGET_MAP.get(concern, [concern.lower()]):
            if target in score_map:
                user_concern_targets.add(target)
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
            skin_type_match = 8 if survey.skin_type in product.skin_types or "all" in product.skin_types else 0
            # ── 사진 점수 지배 랭킹 ──────────────────────────────────────────────
            # severity_focus: 제품이 다루는 타깃들의 '평균' 사용자 심각도(0-100).
            # 합계가 아니라 평균이라, 온갖 타깃을 다 나열한 브로드 상품이 무관한 저점 타깃까지
            # 끌고 오면 오히려 점수가 내려간다 → 사용자의 '강한 고민'에 집중한 제품이 상위로.
            severity_focus = (
                sum(score_map.get(target, 0) for target in product_targets) / len(product_targets)
                if product_targets
                else 0.0
            )
            # concern_hits: 제품이 실제로 커버하는 '사용자 고민' 타깃(사진>=40 또는 설문 고민).
            concern_hits = product_targets & user_concern_targets
            concern_coverage = len(concern_hits)
            knowledge_overlap = knowledge_targets.intersection(product_targets)
            rating_score = rating_score_for(product)
            total = round(
                min(
                    99.0,
                    severity_focus * 0.55            # 0..55  사진 점수(지배적)
                    + concern_coverage * 6.0         # 0..~18 사용자 고민 커버 보너스
                    + skin_type_match                # 0/8
                    + min(6.0, rating_score * 0.6)   # 0..6   품질(부차)
                    + min(4.0, platform_score * 0.5) # 0..4   플랫폼 적합(부차)
                    + (2.0 if knowledge_overlap else 0.0),
                ),
                1,
            )
            # 이유표시는 '사용자가 실제로 겪는 고민 ∩ 제품 타깃' 우선(없으면 성분 근거로 폴백).
            reason_source = concern_hits or matched_targets.union(knowledge_overlap)
            reason_tags = [
                REASON_TARGET_LABELS.get(target, target)
                for target in sorted(reason_source, key=lambda t: score_map.get(t, 0), reverse=True)
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


def recommend_derma_care(
    db: Session,
    body_conditions: list[BodyConditionScore],
    survey: SurveyInput,
    user_id: int | None,
    analysis_id: int | None = None,
    platform: str = "all",
) -> RecommendationResponse:
    """2단 모델의 질환 그룹(tier2)에 '적합한 성분' 기준으로 제품/안내를 낸다.

    - 화장품으로 다룰 수 있는 병(습진·여드름·건선) → 적합 성분 함유 DB 제품 추천.
    - 약이 필요한 병(무좀·옴·바이러스·점) → 제품 대신 성분/상담 안내(가짜 제품 X).
    - 악성 의심 → 제품 없이 진료 안내.
    """
    platform = normalize_platform(platform)
    conditions = [c.condition for c in body_conditions] or ["other"]
    top_condition = conditions[0]
    top_care = care_for(top_condition)

    # 악성 의심만 안전상 제품 대신 진료 안내로 남긴다(제품 폴백 금지).
    if top_care["kind"] == REFERRAL:
        history = RecommendationHistory(
            user_id=user_id, analysis_id=analysis_id,
            recommended_ingredients=json.dumps([]), recommended_products=json.dumps([]),
        )
        db.add(history)
        db.commit()
        db.refresh(history)
        return RecommendationResponse(
            history_id=history.id, ingredients=[], products=[], explanation=top_care["guide"]
        )

    # '제품/성분으로 해결 가능한 가장 상위 병'을 고른다. 1순위가 점·지루각화처럼 제품으로
    # 다룰 수 없으면(GUIDE_ONLY·OTC없음), 함께 감지된 하위 병(예: 습진)으로 넘어간다.
    target_condition, target_care = top_condition, top_care
    if top_care["kind"] != PRODUCTS and top_condition not in OTC_INGREDIENTS:
        for cond in conditions[1:]:
            cand = care_for(cond)
            if cand["kind"] == PRODUCTS or cond in OTC_INGREDIENTS:
                target_condition, target_care = cond, cand
                break

    want_names: list[str] = list(target_care.get("ingredients", []))
    ingredients = (
        db.query(Ingredient).filter(Ingredient.name.in_(want_names)).all() if want_names else []
    )
    order = {name: index for index, name in enumerate(want_names)}
    ingredients.sort(key=lambda ing: order.get(ing.name, 99))

    top: list[tuple[float, Product, list[str]]] = []
    if target_care["kind"] == PRODUCTS and want_names:
        want, avoid = set(want_names), set(target_care.get("avoid", []))
        candidates = db.query(Product).options(
            selectinload(Product.brand),
            selectinload(Product.ingredients).selectinload(ProductIngredient.ingredient),
        ).all()
        scored: list[tuple[float, Product, list[str]]] = []
        for product in candidates:
            names = {pi.ingredient.name for pi in product.ingredients}
            if avoid & names or not (want & names):
                continue
            match = len(want & names)
            skin_type_match = 8 if survey.skin_type in product.skin_types or "all" in product.skin_types else 0
            rating_score = rating_score_for(product)
            total = round(
                min(99.0, 30 + match * 15 + skin_type_match
                    + min(6.0, rating_score * 0.6)
                    + min(4.0, platform_fit_score(product, platform) * 0.5)),
                1,
            )
            reason = [target_care["label"]] + [f"{name} 함유" for name in want_names if name in names][:3]
            scored.append((total, product, reason))
        top = sorted(scored, key=lambda item: (item[0], item[1].avg_rating or 0.0), reverse=True)[:5]

    # 1순위가 제품 불가라 하위 병으로 넘어갔으면 그 사실을 먼저 알린다.
    lead = ""
    if target_condition != top_condition:
        lead = f"{top_care['label']}은(는) 제품으로 해결하기 어렵습니다. 함께 감지된 {target_care['label']} 기준으로 제품을 추천합니다. "

    if target_care["kind"] == PRODUCTS:
        ing_text = ", ".join(ing.name for ing in ingredients[:3])
        prod_text = ", ".join(product.name for _s, product, _r in top[:3])
        body = f"{target_care['label']}에 적합한 {ing_text} 성분 중심으로 골랐습니다. {target_care['guide']}"
        if prod_text:
            body += f" 추천 제품: {prod_text}."
    else:
        body = target_care["guide"]
    explanation = lead + body

    # OTC 의약품 예시(무좀·사마귀 등 약이 필요한 병). 지식파일 없으면 라이브 OpenFDA로 폴백.
    otc_examples = load_otc_examples(target_condition)
    shown = ", ".join(
        f"{item['brand']}({item['ingredient']})"
        for item in otc_examples if item.get("brand")
    )
    if shown:
        explanation += f" 약국 OTC 예시(미국 FDA 기준): {shown}. 사용 전 약사와 상담하세요."

    history = RecommendationHistory(
        user_id=user_id,
        analysis_id=analysis_id,
        recommended_ingredients=json.dumps([ing.name for ing in ingredients]),
        recommended_products=json.dumps([product.name for _s, product, _r in top]),
    )
    db.add(history)
    db.commit()
    db.refresh(history)

    matched_map = {product.id: matched_platforms(product) for _s, product, _r in top}
    hidden_map = unavailable_platforms_bulk(
        (product.id, product.brand.name, product.name, set(matched_map[product.id]))
        for _s, product, _r in top
    )
    products_out = [
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
            matched_platforms=[p for p in matched_map[product.id] if p not in hidden_map.get(product.id, set())],
            image_url=product.image_url,
            avg_rating=product.avg_rating or None,
            review_count=product.review_count or None,
            reason_tags=reason,
            evidence_note=None,
        )
        for score, product, reason in top
    ]
    return RecommendationResponse(
        history_id=history.id,
        ingredients=[
            IngredientOut(id=ing.id, name=ing.name, benefit=ing.benefit, targets=ing.targets.split(","))
            for ing in ingredients
        ],
        products=products_out,
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
