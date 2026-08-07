import json
import re
import time
from collections import defaultdict
from urllib.parse import quote_plus

from sqlalchemy.orm import Session, selectinload

from app.models import Ingredient, Product, ProductIngredient, RecommendationHistory, SkinAnalysis, Survey
from app.services.routine_steps import classify_routine_step
from app.services.derma_condition_care import (
    GUIDE_ONLY,
    OTC_INGREDIENTS,
    PRODUCTS,
    REFERRAL,
    care_for,
    care_ja_for,
    load_otc_examples,
)
from app.services.body_categories import ALL_CATEGORIES as NON_FACE_CATEGORIES
from app.services.body_skin_analyzer import BODY_LABELS_JA
from app.services.ingredient_aliases import detect_ingredients_ko
from app.services.kr_ingredient_notice import raw_ingredients_for_url
from app.services.pediatric_care import (
    PEDIATRIC_GUIDANCE,
    PEDIATRIC_GUIDANCE_INGREDIENTS,
    PEDIATRIC_GUIDANCE_JA,
    PEDIATRIC_GUIDANCE_NO_PRODUCTS,
    PEDIATRIC_GUIDANCE_NO_PRODUCTS_JA,
    PEDIATRIC_SAFE_INGREDIENTS,
    is_pediatric,
    is_pediatric_safe,
    raw_ingredients_have_fragrance,
)
from app.services.oliveyoung_catalog import brand_in_catalog, match_oliveyoung
from app.services.platform_availability import unavailable_platforms_bulk
from app.services.skincare_ingredient_knowledge import (
    build_skincare_recommendation_hint,
    skincare_recommendation_context,
)
from app.schemas.api import (
    BodyConditionScore,
    IngredientOut,
    ProductColumn,
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

# 얼굴 분석이 내는 점수 키. 성분 targets 중 이 6개만 얼굴 랭킹에 쓴다.
FACE_SCORE_TARGETS = frozenset(TARGET_LABELS)

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
    """브랜드명이 목록의 브랜드를 '단어로' 포함하는지.

    단순 부분문자열은 오탐이 난다 — 미국 브랜드 'Danessa Myricks Beauty'가 일본 브랜드
    'anessa'를 품고 있어 J뷰티로 분류됐고(6건), 그 탓에 matched_platforms 가 올리브영·
    네이버·Amazon US 후보에서 통째로 빼버렸다. 앞뒤가 영숫자면 매칭으로 보지 않는다.
    (K뷰티 판정은 이 변경으로 바뀌는 브랜드가 0건임을 실측 확인.)
    """
    brand = _brand_text(product)
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", brand)
        for name in brands
    )


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
    brand_name = product.brand.name if product.brand else ""

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
    # 올리브영 글로벌몰은 K뷰티 전용이 아니다 — ANESSA·CEZANNE·KATE 같은 **일본 브랜드도
    # 실제로 취급한다**(카탈로그 194개 브랜드에 실재). 그래서 위에서 is_japanese 로 묶어
    # 배제했더라도, 카탈로그가 그 브랜드를 취급하면 올리브영 후보로 되살린다. 여기서 통과해도
    # 실제 버튼은 match_oliveyoung 의 라인 매칭(_oliveyoung_slot_is_real·resolve_product_platforms)을
    # 통과해야 붙으므로, 후보를 넓혀도 오탐 버튼은 생기지 않는다.
    if "oliveyoung." in product_url or is_kbeauty(product) or brand_in_catalog(brand_name):
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


# 색조(퍼스널컬러) 후보 id 캐시 — {DB URL: (만료시각, ids)}.
_PC_CANDIDATE_TTL = 600.0
_pc_candidate_cache: dict[str, tuple[float, tuple[int, ...]]] = {}


# 상품 성분 인덱스 캐시 — {DB URL: (만료시각, {product_id: (성분명 set, 타깃 set)})}.
_INGREDIENT_INDEX_TTL = 600.0
_ingredient_index_cache: dict[str, tuple[float, dict[int, tuple[frozenset[str], frozenset[str]]]]] = {}


def clear_personal_color_candidate_cache() -> None:
    """상품 임포트/시딩 후, 또는 테스트에서 후보 캐시를 비운다."""
    _pc_candidate_cache.clear()
    _ingredient_index_cache.clear()


def ingredient_index(db: Session) -> dict[int, tuple[frozenset[str], frozenset[str]]]:
    """상품 id → (성분명, 타깃) 인덱스 (10분 캐시).

    왜 캐시하나: 랭킹은 상품 7,228건 전부의 성분을 봐야 하는데, 이걸 `selectinload` 로 매 요청
    끌어오면 **요청마다** 성분 조인이 돈다. SQLAlchemy 가 500건씩 나눠 15개 쿼리를 보내고,
    원격 DB(왕복 107ms) 라 그것만 1.9초 + 객체 그래프 생성까지 합쳐 요청당 3.5초쯤 든다(실측:
    브랜드만 1.8s vs 브랜드+성분 5.2s).

    성분 구성은 상품 데이터라 요청 사이에 바뀌지 않는다. 한 번(1.16초) 만들어 두고 재사용하면
    랭킹 루프는 dict 조회만 하면 된다. TTL·DB URL 키 규약은 _personal_color_candidate_ids 와 동일.
    """
    key = str(db.get_bind().url)
    now = time.monotonic()
    cached = _ingredient_index_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]

    index: dict[int, tuple[set[str], set[str]]] = {}
    rows = (
        db.query(ProductIngredient)
        .options(selectinload(ProductIngredient.ingredient))
        .all()
    )
    for row in rows:
        names, targets = index.setdefault(row.product_id, (set(), set()))
        ingredient = row.ingredient
        if ingredient is None:
            continue
        names.add(ingredient.name)
        targets.update(target for target in (ingredient.targets or "").split(",") if target)
    frozen = {pid: (frozenset(n), frozenset(t)) for pid, (n, t) in index.items()}
    _ingredient_index_cache[key] = (now + _INGREDIENT_INDEX_TTL, frozen)
    return frozen


_EMPTY_INGREDIENTS: tuple[frozenset[str], frozenset[str]] = (frozenset(), frozenset())


def _personal_color_candidate_ids(db: Session) -> tuple[int, ...]:
    """색조 화장품 후보 상품 id (10분 캐시).

    `_is_personal_color_makeup_product` 는 키워드와 무관한 순수 분류라, 요청마다 전체 상품
    (7,228건)을 ORM 으로 올려 파이썬에서 거르는 건 낭비였다 — 이 로딩만 매 요청 4~7초를
    먹었다(실측, 아이템매칭 지연의 최대 단일 원인). 후보는 729건뿐이라 id 만 캐시해 두면
    이후 요청은 그 729건만 올린다. DB 가 바뀔 수 있는 테스트/시딩을 위해 bind URL 로 키를
    나누고 TTL 을 둔다.
    """
    key = str(db.get_bind().url)
    now = time.monotonic()
    cached = _pc_candidate_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]

    rows = db.query(Product).options(selectinload(Product.brand)).all()
    ids = tuple(p.id for p in rows if _is_personal_color_makeup_product(p))
    _pc_candidate_cache[key] = (now + _PC_CANDIDATE_TTL, ids)
    return ids


def _visible_product_platforms(product: Product, region: str, platform: str) -> list[str]:
    allowed = REGION_PLATFORMS.get(region, set().union(*REGION_PLATFORMS.values()))
    matches = set(matched_platforms(product)).intersection(allowed)
    if platform != "all":
        matches = matches.intersection({platform})
    return sorted(matches)


def _oliveyoung_slot_is_real(product: Product, region: str, platform: str) -> bool:
    """올리브영 탭에서 이 DB 상품이 자리를 차지할 자격이 있는가(JP 한정).

    `matched_platforms`는 일본 상품이 아니면 **무조건** oliveyoung 을 부여한다. 그래서
    글로벌몰이 취급하지 않는 서양 브랜드(Benefit·Givenchy·HUDA…)까지 올리브영 탭 후보가
    되고, `build_platform_links`가 붙여주는 건 상품 직링크가 아니라 **검색 URL**이다.
    이 상품들이 limit 을 다 채우면 아래 `_curated_personal_color_products`(실제 글로벌몰
    직링크가 확인된 큐레이션 목록)가 `limit - len(db_results)` = 0 슬롯만 받아 한 건도
    못 들어가고, 그 뒤 resolve_product_platforms 가 검증 안 되는 검색 URL 을 걷어내
    **JP 올리브영 탭이 통째로 0건**이 됐다.

    그래서 JP 올리브영 요청에 한해 카탈로그에 실재하는 상품만 통과시킨다. KR 은 글로벌
    카탈로그가 아니라 국내몰 라이브 검색(oliveyoung_kr_search)으로 판정하므로 건드리지
    않는다 — 여기서 막으면 국내몰에 있는 상품까지 사라진다.
    """
    if platform != "oliveyoung" or (region or "").lower() != "jp":
        return True
    brand = product.brand.name if product.brand else ""
    # 싼 브랜드 게이트로 3천여 후보 전수 스캔(상품당 ~40ms)을 피한다.
    if not brand_in_catalog(brand):
        return False
    return match_oliveyoung(brand, product.name or "") is not None


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

    # ⚠ ingredients 를 여기서 eager 로드하면 안 된다. 스코어링(_is_personal_color_makeup_product
    # ·personal_color_fit_score_for_text)은 brand/name/category/description 만 보는데,
    # 성분까지 selectinload 하면 전체 상품에 대해 조인이 돌아 쿼리가 4.2s→9.0s 가 된다
    # (실측). 성분이 실제로 필요한 건 아래 top_products 8건뿐이라 그때 지연로드된다.
    # 색조 후보(7,228→729)는 키워드와 무관하므로 id 를 캐시해 매 요청 전량 로딩을 피한다.
    products = db.query(Product).options(selectinload(Product.brand)).filter(
        Product.id.in_(_personal_color_candidate_ids(db))
    ).all()

    scored: list[tuple[float, float, Product, list[str]]] = []
    for product in products:
        visible_platforms = _visible_product_platforms(product, region, platform)
        if not visible_platforms:
            continue
        if not _oliveyoung_slot_is_real(product, region, platform):
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

    # 성분은 최종 top 상품에만 필요하다. 위 스캔에서 eager 로드를 뺐으므로 여기서 한 번에
    # 채운다 — 그냥 두면 ProductOut 만들 때 상품마다 지연로딩이 돌아 N+1 이 된다(원격 DB
    # 왕복 107ms × 8 ≈ 0.9s). identity map 에 들어가므로 아래 product.ingredients 는 재조회 없음.
    if top_products:
        db.query(Product).options(
            selectinload(Product.ingredients).selectinload(ProductIngredient.ingredient),
        ).filter(Product.id.in_([product.id for _s, _ps, product, _pl in top_products])).all()

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


# ── 카테고리별 상품 컬럼 조립 ─────────────────────────────────────────
# 클렌저/토너/세럼/보습/선크림 카테고리별로 추천 상품 여러 개(퍼스널컬러 컬럼과 동일 모델).
# 세럼만 사진 고민(total) 기반, 나머지는 품질(평점·피부타입). 근거: docs/ROUTINE_RECOMMENDATION_SPEC.md
ROUTINE_SLOTS = [
    ("cleanser", "클렌저"),
    ("toner", "토너"),
    ("serum", "세럼"),
    ("moisturizer", "보습"),
    ("sunscreen", "선크림"),
]
_SOOTHING_INGREDIENTS = {"Centella Asiatica", "Panthenol", "Green Tea"}
_AHA_BHA = {"Salicylic Acid", "Glycolic Acid", "Lactic Acid"}
_PER_COLUMN = 4   # 컬럼당 추천 상품 수


def _line_dedup_key(product) -> str:
    """제품 '라인' 단위 dedup 키. 용량/기획/프로모 토큰을 걷어낸 '브랜드+라인명'으로 정규화한다.

    카탈로그엔 같은 제품의 용량 변형이 별도 행으로 들어있어(예: 라운드랩 독도 클렌저
    120/150/200/250ml), 이름을 그대로 키로 쓰면 한 컬럼이 같은 제품 용량변형으로 다 찬다
    (사용자 지적 Bug A). build_search_query 로 사이즈/기획어를 떼어 라인 단위로 접는다.
    build_search_query 는 platform_resolver 에 있고 그쪽이 recommender 를 import 하므로(순환)
    지연 import 한다.
    """
    import re as _re

    from app.services.platform_resolver import build_search_query

    brand = product.brand.name if getattr(product, "brand", None) else ""
    key = build_search_query(brand, product.name or "").strip().lower()
    # 용량/수량 토큰을 위치 무관 제거: 같은 라인의 120/150/200/250ml 변형을 한 키로 접는다.
    # build_search_query 는 '꼬리'의 사이즈만 떼서 250ml 가 코어에 남으면 변형이 안 접혔다.
    key = _re.sub(r"\d+\s*(ml|ml\+|g|매|개|입|팩|세트|호|ea)\b", " ", key)
    key = _re.sub(r"\s+", " ", key).strip()
    return key or (product.name or "").strip().lower()


# 성분 조회는 캐시 인덱스로 한다. 정렬 비교 함수 안에서 product.ingredients 를 만지면
# 후보 수만큼 지연로딩이 걸려 N+1 이 된다(민감도 4 이상 사용자에게만 터지는 함정이었다).
def _names_of(product, ing_index) -> frozenset[str]:
    if ing_index is None:  # 인덱스를 못 받은 호출부(구 시그니처) 호환 — 이때만 관계를 읽는다.
        return frozenset(pi.ingredient.name for pi in product.ingredients)
    return ing_index.get(product.id, _EMPTY_INGREDIENTS)[0]


def _generic_quality(product, survey: SurveyInput, platform_score: float, soothing: bool, ing_index=None) -> float:
    """비-세럼 단계용 품질 점수: 평점 + 피부타입 적합 + 플랫폼 (+민감 진정 가점)."""
    score = rating_score_for(product)
    if survey.skin_type in product.skin_types or "all" in product.skin_types:
        score += 4.0
    score += min(3.0, platform_score * 0.3)
    if soothing and survey.sensitivity >= 4:
        if _names_of(product, ing_index) & _SOOTHING_INGREDIENTS:
            score += 3.0
    return score


def _serum_sort_key(x, survey: SurveyInput, ing_index=None):
    """세럼 랭킹 키: 사진 고민(total)으로 정렬하되, 민감 피부엔 강한 액티브(레티놀·AHA/BHA)를 감점."""
    product, total = x[0], x[1]
    if survey.sensitivity >= 4:
        if _names_of(product, ing_index) & (_AHA_BHA | {"Retinol"}):
            total -= 30.0
    return (total, rating_score_for(product))


def build_product_columns(scored, survey: SurveyInput, ing_index=None):
    """scored(전체 후보) → 카테고리별 추천 상품 컬럼(각 top-N).

    scored = [(total, platform_score, product, reason_tags, _evidence), ...].
    반환: ([(key, label, reason, [(product, total, reason_tags, ps), ...])], moist_step).
    세럼은 total(고민) 기반(민감시 강한 액티브 감점), 나머지는 품질(평점·피부타입).
    보습은 피부타입으로 로션/크림 택1(없으면 폴백). face·body 공용(고민의 출처만 다름).
    """
    moist_step = "lotion" if survey.skin_type in ("oily", "combination") else "cream"
    pools: dict[str, list] = defaultdict(list)
    for total, platform_score, product, reason_tags, _evidence in scored:
        step = classify_routine_step(product.category, product.name)
        if step:
            pools[step].append((product, total, reason_tags, platform_score))

    columns = []
    for key, label in ROUTINE_SLOTS:
        if key == "serum":
            cand = sorted(pools.get("serum", []), key=lambda x: _serum_sort_key(x, survey, ing_index), reverse=True)
        elif key == "moisturizer":
            pool = pools.get(moist_step) or pools.get("cream") or pools.get("lotion") or []
            cand = sorted(pool, key=lambda x: (_generic_quality(x[0], survey, x[3], True, ing_index), x[1]), reverse=True)
        else:
            soothing = key in ("cleanser", "toner")
            cand = sorted(pools.get(key, []), key=lambda x: (_generic_quality(x[0], survey, x[3], soothing, ing_index), x[1]), reverse=True)
        # 라인 기준 중복 제거(카탈로그 소스별 중복행·용량변형) 후 top-N.
        top, seen = [], set()
        for item in cand:
            nm = _line_dedup_key(item[0])
            if nm in seen:
                continue
            seen.add(nm)
            top.append(item)
            if len(top) >= _PER_COLUMN:
                break
        reason = ""
        if key == "serum" and top:
            tags = [t for t in top[0][2] if t not in ("피부 타입 적합", "선택 플랫폼 매칭")]
            reason = (" · ".join(tags[:2]) + " 케어") if tags else ""
        columns.append((key, label, reason, top))
    return columns, moist_step


# ── 바디 상품 컬럼 조립 ───────────────────────────────────────────────
# 얼굴 5슬롯(클렌저·토너·세럼·보습·선크림)은 바디에 안 맞는다. 바디엔 토너·세럼 개념이
# 없고, 얼굴 슬롯을 그대로 쓰면 classify_routine_step 이 body.* 를 모르니 컬럼이 전부
# 얼굴 제품으로 찬다. 그래서 바디 전용 슬롯을 따로 둔다.
# 근거 데이터: body.wash 191 · body.lotion 161 · body.cream 41 · body.oil 26 · body.treatment 11.
BODY_SLOTS: list[tuple[str, str, tuple[str, ...]]] = [
    ("body_wash", "바디 세정", ("body.wash",)),
    ("body_moisturizer", "바디 보습", ("body.lotion", "body.cream")),
    ("body_treatment", "바디 집중케어", ("body.treatment", "body.oil")),
]
# 슬롯에 쓰이는 카테고리 전체. 미스트·데오드란트·제모·선케어와 hand.*/foot.* 는 여기 없다
# — 카탈로그로는 갖고 있되 질환 추천에는 올리지 않는다(BODY_CATEGORY_SPEC.md §1).
BODY_CATALOG_CATEGORIES = frozenset(
    category for _key, _label, categories in BODY_SLOTS for category in categories
)

# 지역별로 '구매 가능한' 바디 상품만 추천하기 위한 시장 판정. 바디 상품은 스킨케어와 달리
# 리전 카탈로그(올영 국내몰 KR / 마츠키요·아마존JP JP)에서 왔고, product_url 도메인이
# 그 시장을 그대로 드러낸다. JP 사용자에게 KR 국내몰 상품을 추천하면 입점 리졸버가 링크를
# 전부 떼어내(after(jp)=[]) 프론트가 카드를 통째로 숨긴다 → "맞는 상품이 없어요".
# 바디 추천에서 제외할 소스(사용자 결정 2026-07-24: 마츠키요 크롤 배제).
# DB엔 옛 적재분이 남아 있으므로 추천 시점에도 걸러 즉시 반영한다(재적재 불필요).
_EXCLUDED_BODY_URL_MARKERS = ("matsukiyo",)


def is_excluded_body_source(product) -> bool:
    url = (getattr(product, "product_url", "") or "").lower()
    return any(marker in url for marker in _EXCLUDED_BODY_URL_MARKERS)


def product_market(product) -> str:
    url = (getattr(product, "product_url", "") or "").lower()
    if "oliveyoung.co.kr" in url or "naver" in url or "lotteon" in url:
        return "kr"
    if "matsukiyo" in url or "amazon.co.jp" in url or "rakuten.co.jp" in url:
        return "jp"
    if "global.oliveyoung" in url:
        return "global"
    if "amazon.com" in url:
        return "us"
    return ""


# region → 그 지역에서 실제로 살 수 있는 시장. KR=국내몰·네이버·amazon.com(ASIN),
# JP=마츠키요·amazon.co.jp·올영 글로벌.
REGION_MARKETS: dict[str, frozenset[str]] = {
    "kr": frozenset({"kr", "us"}),
    "jp": frozenset({"jp", "global"}),
}


def _body_ingredient_names(product) -> set[str]:
    return {pi.ingredient.name for pi in product.ingredients}


def _body_rank_key(item, survey: SurveyInput, want: set[str]):
    """바디 상품 랭킹 키.

    성분 일치를 '하드 게이트'가 아니라 '가점'으로 쓴다. 케어 카테고리 435건 중 성분이
    확인된 건 164건뿐이라, 교집합을 필수 조건으로 걸면 나머지가 통째로 사라진다.
    대신 성분이 확인된 상품이 항상 위로 오게 정렬한다.
    """
    product, _total, _tags, platform_score = item
    names = _body_ingredient_names(product)
    match = len(want & names)
    verified = 1 if names else 0          # 성분 정보 유무 자체가 신뢰 신호
    skin_fit = 1 if (survey.skin_type in product.skin_types or "all" in product.skin_types) else 0
    return (match, verified, skin_fit, rating_score_for(product), platform_score)


def build_body_columns(scored, survey: SurveyInput, want: set[str], strict: bool):
    """scored → 바디 슬롯별 상품 컬럼.

    ``strict`` 는 '자극 성분을 피해야 하는 질환'(avoid 목록이 있는 습진·아토피 등)일 때 True.
    이때는 **성분이 확인된 상품만** 올린다. 성분을 모르는 상품은 avoid 검사를 할 수 없어서,
    레티놀 바디로션을 아토피에 추천하는 사고가 날 수 있기 때문이다.
    """
    moist_first = "body.lotion" if survey.skin_type in ("oily", "combination") else "body.cream"
    pools: dict[str, list] = defaultdict(list)
    for _total, platform_score, product, reason_tags, _evidence in scored:
        category = (product.category or "").strip().lower()
        if category in BODY_CATALOG_CATEGORIES:
            pools[category].append((product, _total, reason_tags, platform_score))

    columns = []
    for key, label, categories in BODY_SLOTS:
        if key == "body_moisturizer":
            # 피부타입으로 로션/크림 우선순위를 바꾼다(얼굴 보습 슬롯과 같은 규칙).
            ordered = (moist_first, *(c for c in categories if c != moist_first))
        else:
            ordered = categories
        pool = [item for category in ordered for item in pools.get(category, [])]
        if strict:
            pool = [item for item in pool if _body_ingredient_names(item[0])]
        cand = sorted(pool, key=lambda x: _body_rank_key(x, survey, want), reverse=True)

        top, seen = [], set()
        for item in cand:
            name_key = _line_dedup_key(item[0])
            if name_key in seen:
                continue
            seen.add(name_key)
            top.append(item)
            if len(top) >= _PER_COLUMN:
                break
        reason = ""
        if top:
            matched = sorted(want & _body_ingredient_names(top[0][0]))
            if matched:
                reason = " · ".join(matched[:2]) + " 함유"
        columns.append((key, label, reason, top))
    return columns


def _product_out(product, score, reason_tags, evidence_note, matched_map, hidden_map) -> ProductOut:
    return ProductOut(
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
            platform for platform in matched_map.get(product.id, [])
            if platform not in hidden_map.get(product.id, set())
        ],
        image_url=product.image_url,
        avg_rating=product.avg_rating or None,
        review_count=product.review_count or None,
        reason_tags=reason_tags,
        evidence_note=evidence_note,
    )


def recommend_products(
    db: Session,
    scores: SkinScores,
    survey: SurveyInput,
    analysis_id: int | None,
    user_id: int | None,
    platform: str = "all",
    analysis_mode: str = "face",
    body_conditions: list[BodyConditionScore] | None = None,
    lang: str = "ko",
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

    # ⚠ 성분을 여기서 eager 로드하지 않는다. 랭킹은 전 상품(7,228건)의 성분을 보지만,
    # 그 정보는 요청과 무관한 상품 데이터라 ingredient_index() 로 캐시해 둔다(요청당 3.5초 절감).
    # 대신 **아래 스캔에서 product.ingredients 를 만지면 안 된다** — 지연로딩이 걸려 N+1 이 된다.
    products = db.query(Product).options(selectinload(Product.brand)).all()
    ing_index = ingredient_index(db)
    scored: list[tuple[float, float, Product, list[str], str | None]] = []
    for product in products:
        platform_score = platform_fit_score(product, platform)
        if platform_score < 0:
            continue
        # 얼굴 점수(6종)에 해당하는 타깃만 센다. 바디 보습 성분(글리세린·페트롤라툼 등)은
        # targets 가 barrier/moisture 라 여기서 걸러진다 — 안 거르면 severity_focus 가
        # 타깃 '평균'이라, 상품 82%에 든 글리세린이 0점 타깃으로 들어가 얼굴 랭킹을 뭉갠다.
        # 현재 얼굴 성분 14종은 전부 얼굴 타깃이라 이 필터는 오늘 기준 no-op 이다.
        product_ingredient_names, all_targets = ing_index.get(product.id, _EMPTY_INGREDIENTS)
        product_targets = {target for target in all_targets if target in FACE_SCORE_TARGETS}
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
            # 바디·핸드·풋 상품(body.* / hand.* / foot.*)은 얼굴 추천 후보에서 뺀다.
            # 얼굴 경로는 카테고리 화이트리스트 없이 DB 전체를 점수화하므로, 바디 카탈로그를
            # 적재한 순간 바디워시가 얼굴 Top5에 올라온다. 네임스페이스가 그 경계를 만든다.
            if (product.category or "").strip().lower() in NON_FACE_CATEGORIES:
                continue
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

    # face 모드면 카테고리별 상품 컬럼(각 여러 개)을 조립한다. body는 recommend_derma_care에서.
    column_selection: list = []
    if analysis_mode != "body":
        column_selection, _moist_step = build_product_columns(scored, survey, ing_index)

    # 후보 플랫폼을 미리 구한 뒤, 실시간 입점 확인으로 '실제 없는' 곳만 숨긴다.
    # top_products + 컬럼 상품을 합쳐(중복 제거) 한 번에 확인한다.
    union = {product.id: product for _s, _ps, product, _rt, _en in top_products}
    for _key, _label, _reason, top in column_selection:
        for prod, _t, _rt, _ps in top:
            union[prod.id] = prod
    # 응답에 실을 상품(≈25건)의 성분만 한 번에 채운다. 위 스캔에서 성분 eager 로드를 뺐으므로
    # 이걸 빼먹으면 _product_out 이 상품마다 지연로딩을 돌려 N+1 이 된다(원격 DB 왕복 107ms).
    # identity map 에 올라가므로 이후 product.ingredients 접근은 재조회가 없다.
    if union:
        db.query(Product).options(
            selectinload(Product.ingredients).selectinload(ProductIngredient.ingredient),
        ).filter(Product.id.in_(list(union))).all()
    matched_map = {pid: matched_platforms(p) for pid, p in union.items()}
    hidden_map = unavailable_platforms_bulk(
        (p.id, p.brand.name, p.name, set(matched_map[p.id])) for p in union.values()
    )

    product_columns = [
        ProductColumn(
            key=key,
            label=label,
            reason=reason,
            products=[_product_out(prod, t, rt, None, matched_map, hidden_map) for prod, t, rt, _ps in top],
        )
        for key, label, reason, top in column_selection
    ]

    explanation = (
        build_body_explanation(body_conditions, ingredient_names, product_names)
        if analysis_mode == "body"
        else build_explanation(scores, survey, ingredient_names, product_names)
    )
    explanation_ja = (
        build_body_explanation_ja(body_conditions, ingredient_names, product_names)
        if analysis_mode == "body"
        else build_explanation_ja(scores, survey, ingredient_names, product_names)
    )
    if analysis_mode != "body":
        context = {
            "survey": survey.model_dump(),
            "scores": scores.model_dump(),
        }
        hint = build_skincare_recommendation_hint(" ".join(ingredient_targets), context)
        if hint:
            explanation = f"{explanation} {hint}"
        # 일본어판에는 일본어 근거만 붙인다. 번역이 없으면 문단 자체가 빠진다
        # (한국어를 섞지 않는다 — 이번 제보의 핵심이 그것이었다).
        if explanation_ja:
            hint_ja = build_skincare_recommendation_hint(
                " ".join(ingredient_targets), context, lang="ja"
            )
            if hint_ja:
                explanation_ja = f"{explanation_ja} {hint_ja}"

    return RecommendationResponse(
        history_id=history.id,
        ingredients=[
            IngredientOut(id=ingredient.id, name=ingredient.name, benefit=ingredient.benefit, targets=ingredient.targets.split(","))
            for ingredient in ingredients
        ],
        products=[
            _product_out(product, score, reason_tags, evidence_note, matched_map, hidden_map)
            for score, _platform_score, product, reason_tags, evidence_note in top_products
        ],
        explanation=explanation,
        explanation_ja=explanation_ja,
        product_columns=product_columns,
    )


def _recommend_pediatric(
    db: Session,
    survey: SurveyInput,
    user_id: int | None,
    analysis_id: int | None,
    platform: str,
    region: str,
) -> RecommendationResponse:
    """영유아·소아 안내 + 성분검증된 순한 상품 큐레이션.

    질환별 랭킹을 하지 않는다. 소아안전 화이트리스트(순한 장벽·보습만, 액티브·향료 배제)를
    통과한 상품만 카테고리별로 소수 노출한다. 통과 상품이 부족하면 안내만 낸다.
    """
    allowed_markets = REGION_MARKETS.get(region)
    candidates = db.query(Product).options(
        selectinload(Product.brand),
        selectinload(Product.ingredients).selectinload(ProductIngredient.ingredient),
    ).filter(Product.category.in_(BODY_CATALOG_CATEGORIES)).all()

    safe: dict[str, list] = defaultdict(list)
    for product in candidates:
        if is_excluded_body_source(product):  # 마츠키요 배제
            continue
        if allowed_markets is not None and product_market(product) not in allowed_markets:
            continue
        names = {pi.ingredient.name for pi in product.ingredients}
        if not is_pediatric_safe(names, product.name or ""):
            continue
        # 전성분 원문으로 향료·에센셜오일까지 검사한다. 검출 성분(23종)만 보면 향료가
        # 어휘 밖이라 새어나간다(록시땅 시어버터오일 등). 원문이 없으면(비-KR) 이름 검사에 맡긴다.
        if raw_ingredients_have_fragrance(raw_ingredients_for_url(product.product_url)):
            continue
        safe[(product.category or "").strip().lower()].append((product, names))

    columns = []
    for key, label, categories in BODY_SLOTS:
        pool = [item for category in categories for item in safe.get(category, [])]
        pool.sort(key=lambda x: (len(x[1]), rating_score_for(x[0])), reverse=True)
        top, seen = [], set()
        for product, names in pool:
            nk = _line_dedup_key(product)
            if nk in seen:
                continue
            seen.add(nk)
            reason = " · ".join(sorted(names & PEDIATRIC_SAFE_INGREDIENTS)[:3]) + " 함유"
            top.append((product, 0.0, [reason], 0.0))
            if len(top) >= _PER_COLUMN:
                break
        if top:
            columns.append((key, f"{label} (순한 성분)", "액티브·향료 배제", top))

    total = sum(len(t) for _k, _l, _r, t in columns)
    explanation = PEDIATRIC_GUIDANCE if total else PEDIATRIC_GUIDANCE_NO_PRODUCTS
    # ⚠ 소아 경로는 안내문이 곧 결과다(성인 제품 폴백 없이 성분 우선 안내). 여기가 한국어로
    #   나가면 일본 사용자는 안전 안내를 아예 못 읽는다 — 반드시 두 벌을 만든다.
    explanation_ja = PEDIATRIC_GUIDANCE_JA if total else PEDIATRIC_GUIDANCE_NO_PRODUCTS_JA

    # 성분 우선 안내: 성인 제품을 억지로 추천하는 대신 '이런 성분을 찾으세요'를 낸다.
    # 상품이 0건이면(카탈로그가 얇은 리전·아토피 등) 이 안내가 유일한 실행 가이드가 된다.
    guidance_ingredients = [
        IngredientOut(id=-(i + 1), name=name, benefit=benefit, targets=["barrier", "moisture"])
        for i, (name, benefit) in enumerate(PEDIATRIC_GUIDANCE_INGREDIENTS)
    ]

    history = RecommendationHistory(
        user_id=user_id, analysis_id=analysis_id,
        recommended_ingredients=json.dumps([name for name, _ in PEDIATRIC_GUIDANCE_INGREDIENTS]),
        recommended_products=json.dumps([p.name for _k, _l, _r, t in columns for p, *_ in t]),
    )
    db.add(history)
    db.commit()
    db.refresh(history)

    union = {p.id: p for _k, _l, _r, t in columns for p, *_ in t}
    matched_map = {pid: matched_platforms(p) for pid, p in union.items()}
    hidden_map = unavailable_platforms_bulk(
        (p.id, p.brand.name, p.name, set(matched_map[p.id])) for p in union.values()
    )
    product_columns = [
        ProductColumn(
            key=key, label=label, reason=reason,
            products=[_product_out(p, s, rt, None, matched_map, hidden_map) for p, s, rt, _ps in top],
        )
        for key, label, reason, top in columns
    ]
    return RecommendationResponse(
        history_id=history.id, ingredients=guidance_ingredients, products=[],
        explanation=explanation, explanation_ja=explanation_ja,
        product_columns=product_columns,
    )


def recommend_derma_care(
    db: Session,
    body_conditions: list[BodyConditionScore],
    survey: SurveyInput,
    user_id: int | None,
    analysis_id: int | None = None,
    platform: str = "all",
    region: str = "all",
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

    # 영유아·소아: 질환 판정보다 먼저 가로챈다. 바디 질환 분류기는 성인 데이터로 학습돼
    # 아기 피부 판정을 신뢰할 수 없고, 성인용 액티브를 아기에게 추천하면 안 된다. 그래서
    # 질환별 랭킹 대신 '안내 + 성분검증된 순한 상품 소수 큐레이션'만 한다(사용자 결정).
    if is_pediatric(survey.age_group):
        return _recommend_pediatric(db, survey, user_id, analysis_id, platform, region)

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
            history_id=history.id, ingredients=[], products=[],
            explanation=top_care["guide"],
            explanation_ja=care_ja_for(top_condition)["guide"],
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
    column_selection: list = []
    if target_care["kind"] == PRODUCTS and want_names:
        want, avoid = set(want_names), set(target_care.get("avoid", []))
        candidates = db.query(Product).options(
            selectinload(Product.brand),
            selectinload(Product.ingredients).selectinload(ProductIngredient.ingredient),
        ).all()
        # 성분 우선 원칙: 성분 데이터가 없는 상품은 추천하지 않는다(항상 strict).
        # 성분을 모르면 (1) 질환 적합성을 판단할 수 없고 (2) 자극 성분 배제도 불가능하다.
        # 사용자 방침: "성분이 없으면 상품을 추천하면 안 된다."
        strict = True
        # 지역별로 그 시장에서 살 수 있는 상품만 남긴다. 필터 결과가 비면(카탈로그가
        # 얇은 리전) 전체로 폴백한다 — 죽은 링크보단 낫다.
        allowed_markets = REGION_MARKETS.get(region)
        if allowed_markets is not None:
            region_pool = [
                p for p in candidates
                if (p.category or "").strip().lower() in BODY_CATALOG_CATEGORIES
                and product_market(p) in allowed_markets
            ]
            if region_pool:
                candidates = region_pool
        scored: list[tuple[float, Product, list[str]]] = []
        for product in candidates:
            category = (product.category or "").strip().lower()
            # 바디 질환 추천은 바디 케어 카테고리에서만 고른다. 예전엔 카탈로그 전체를
            # 훑어서 얼굴 제품('Foaming Facial Cleanser')이 바디 추천에 올라왔다.
            if category not in BODY_CATALOG_CATEGORIES:
                continue
            if is_excluded_body_source(product):  # 마츠키요 배제
                continue
            names = {pi.ingredient.name for pi in product.ingredients}
            # 상품명도 avoid 검사에 넣는다. 성분 데이터가 없는 상품이 63% 라 성분표만
            # 보면 '레티노이드 0.1% 바디세럼' 같은 상품이 습진 추천에 그대로 올라온다.
            names_from_label = set(detect_ingredients_ko(product.name or ""))
            if avoid & (names | names_from_label):
                continue
            if strict and not names:
                continue
            # 성분 일치는 하드 게이트가 아니라 가점이다. 케어 카테고리 435건 중 성분이
            # 확인된 건 164건뿐이라, 교집합을 필수로 걸면 후보가 통째로 사라진다.
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
        # 성분이 일치하는 상품을 항상 위로(match 우선), 그다음 점수·평점.
        top = sorted(
            scored,
            key=lambda item: (
                len(want & {pi.ingredient.name for pi in item[1].ingredients}),
                item[0],
                item[1].avg_rating or 0.0,
            ),
            reverse=True,
        )[:5]

        scored_cols = [
            (total, platform_fit_score(product, platform), product, reason, None)
            for total, product, reason in scored
        ]
        column_selection = build_body_columns(scored_cols, survey, want, strict)

    # 요약문은 한국어·일본어 두 벌을 나란히 조립한다. 한 벌만 만들고 나중에 옮기려 하면
    # 라벨·안내문이 문장 한가운데 박혀 있어 옮길 수가 없다(성분·상품명도 함께 낀다).
    top_care_ja = care_ja_for(top_condition)
    target_care_ja = care_ja_for(target_condition)

    # 1순위가 제품 불가라 하위 병으로 넘어갔으면 그 사실을 먼저 알린다.
    lead = ""
    lead_ja = ""
    if target_condition != top_condition:
        lead = f"{top_care['label']}은(는) 제품으로 해결하기 어렵습니다. 함께 감지된 {target_care['label']} 기준으로 제품을 추천합니다. "
        lead_ja = (
            f"{top_care_ja['label']}は製品では対応が難しいため、"
            f"併せて検出された{target_care_ja['label']}を基準に製品をおすすめします。"
        )

    if target_care["kind"] == PRODUCTS:
        ing_text = ", ".join(ing.name for ing in ingredients[:3])
        prod_text = ", ".join(product.name for _s, product, _r in top[:3])
        body = f"{target_care['label']}에 적합한 {ing_text} 성분 중심으로 골랐습니다. {target_care['guide']}"
        # 성분명·상품명은 고유명사라 원문 그대로 둔다(옮기면 상품에서 못 찾는다).
        body_ja = (
            f"{target_care_ja['label']}に適した {'、'.join(ing.name for ing in ingredients[:3])} "
            f"の成分を中心に選びました。{target_care_ja['guide']}"
        )
        if prod_text:
            body += f" 추천 제품: {prod_text}."
            body_ja += f" おすすめ商品: {'、'.join(product.name for _s, product, _r in top[:3])}。"
    else:
        body = target_care["guide"]
        body_ja = target_care_ja["guide"]
    explanation = lead + body
    explanation_ja = lead_ja + body_ja

    # OTC 의약품 예시(무좀·사마귀 등 약이 필요한 병). 지식파일 없으면 라이브 OpenFDA로 폴백.
    otc_examples = load_otc_examples(target_condition)
    shown = ", ".join(
        f"{item['brand']}({item['ingredient']})"
        for item in otc_examples if item.get("brand")
    )
    if shown:
        explanation += f" 약국 OTC 예시(미국 FDA 기준): {shown}. 사용 전 약사와 상담하세요."
        # 브랜드·성분명(제네릭명)은 원문 그대로 — 약국에서 그 이름으로 찾아야 한다.
        explanation_ja += (
            f" 薬局のOTC例（米国FDA基準）: {shown}。ご使用前に薬剤師にご相談ください。"
        )

    history = RecommendationHistory(
        user_id=user_id,
        analysis_id=analysis_id,
        recommended_ingredients=json.dumps([ing.name for ing in ingredients]),
        recommended_products=json.dumps([product.name for _s, product, _r in top]),
    )
    db.add(history)
    db.commit()
    db.refresh(history)

    # top(평면) + 컬럼 상품을 합쳐 한 번에 입점 확인.
    union = {product.id: product for _s, product, _r in top}
    for _k, _l, _r, coltop in column_selection:
        for prod, _t, _rt, _ps in coltop:
            union[prod.id] = prod
    matched_map = {pid: matched_platforms(p) for pid, p in union.items()}
    hidden_map = unavailable_platforms_bulk(
        (p.id, p.brand.name, p.name, set(matched_map[p.id])) for p in union.values()
    )
    products_out = [
        _product_out(product, score, reason, None, matched_map, hidden_map)
        for score, product, reason in top
    ]
    product_columns = [
        ProductColumn(
            key=key,
            label=label,
            reason=reason,
            products=[_product_out(prod, t, rt, None, matched_map, hidden_map) for prod, t, rt, _ps in coltop],
        )
        for key, label, reason, coltop in column_selection
    ]
    return RecommendationResponse(
        history_id=history.id,
        ingredients=[
            IngredientOut(id=ing.id, name=ing.name, benefit=ing.benefit, targets=ing.targets.split(","))
            for ing in ingredients
        ],
        products=products_out,
        explanation=explanation,
        explanation_ja=explanation_ja,
        product_columns=product_columns,
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


def build_body_explanation_ja(
    body_conditions: list[BodyConditionScore],
    ingredients: list[str],
    products: list[str],
) -> str:
    """build_body_explanation 의 일본어판.

    라벨은 BODY_LABELS_JA 로 다시 붙인다 — body_conditions[].label 은 분석기가 한국어로
    채워 보낸 값이라 그대로 쓰면 문장 한가운데에 한국어가 남는다(이번 제보의 핵심 유형).
    성분명·상품명은 고유명사라 원문 그대로 둔다.
    """
    if body_conditions:
        top = body_conditions[0]
        label_ja = BODY_LABELS_JA.get(top.condition, top.label)
        result = f"{label_ja}の可能性 {top.probability:.1f}%"
    else:
        result = "からだの肌アンケート情報"
    return (
        f"{result}を基準に、肌バリアと保湿を中心とした成分 "
        f"{'、'.join(ingredients[:3])} を優先しました。"
        "刺激の可能性があるレチノールとAHA/BHA配合の製品は除外しています。"
        f"おすすめ商品は {'、'.join(products[:3])} です。"
    )


# 일본어 표기. 한국어 라벨과 **키가 같아야** 한 쪽만 늘어나는 사고를 막는다.
TARGET_LABELS_JA = {
    "acne": "トラブル",
    "pore": "毛穴",
    "wrinkle": "シワ",
    "redness": "赤み",
    "pigmentation": "色素沈着",
    "oiliness": "皮脂",
}

SKIN_TYPE_LABELS_JA = {
    "dry": "乾燥肌",
    "oily": "脂性肌",
    "combination": "混合肌",
    "normal": "普通肌",
    "sensitive": "敏感肌",
}

AGE_LABELS = {"10s": "10대", "20s": "20대", "30s": "30대", "40s": "40대", "50s": "50대 이상"}
AGE_LABELS_JA = {"10s": "10代", "20s": "20代", "30s": "30代", "40s": "40代", "50s": "50代以上"}


def build_explanation(scores: SkinScores, survey: SurveyInput, ingredients: list[str], products: list[str]) -> str:
    score_map = scores.model_dump()
    top_scores = sorted(score_map.items(), key=lambda item: item[1], reverse=True)[:3]
    priorities = ", ".join(f"{TARGET_LABELS[name]} {value:.0f}" for name, value in top_scores)
    skin_type = SKIN_TYPE_LABELS.get(survey.skin_type, survey.skin_type)
    age_label = AGE_LABELS.get(survey.age_group, "")
    gender_label = "여성" if survey.gender == "female" else "남성"
    context = f"{age_label} {gender_label}, {skin_type} 피부" if age_label else f"{gender_label}, {skin_type} 피부"
    return (
        f"가장 두드러진 피부 신호는 {priorities}입니다. {context}와 선택한 고민을 기준으로 "
        f"{', '.join(ingredients[:3])} 성분을 우선 추천했습니다. 추천 제품은 {', '.join(products[:3])} 등입니다."
    )


def build_explanation_ja(scores: SkinScores, survey: SurveyInput, ingredients: list[str], products: list[str]) -> str:
    """build_explanation 의 일본어판.

    수치·성분명·상품명이 끼는 조립형 문장이라 프론트 사전으로는 못 옮긴다. 그래서
    퍼스널컬러의 skin_summary_ja 와 같은 방식으로 **서버가 두 벌을 만들어 내려준다**.
    성분명·상품명은 원문 그대로 둔다(고유명사라 옮기면 오히려 못 찾는다).
    """
    score_map = scores.model_dump()
    top_scores = sorted(score_map.items(), key=lambda item: item[1], reverse=True)[:3]
    priorities = "、".join(f"{TARGET_LABELS_JA[name]} {value:.0f}" for name, value in top_scores)
    skin_type = SKIN_TYPE_LABELS_JA.get(survey.skin_type, survey.skin_type)
    age_label = AGE_LABELS_JA.get(survey.age_group, "")
    gender_label = "女性" if survey.gender == "female" else "男性"
    context = f"{age_label}{gender_label}・{skin_type}" if age_label else f"{gender_label}・{skin_type}"
    return (
        f"最も目立つ肌のサインは {priorities} です。{context}と選択されたお悩みを基準に、"
        f"{'、'.join(ingredients[:3])} の成分を優先しました。"
        f"おすすめ商品は {'、'.join(products[:3])} などです。"
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
