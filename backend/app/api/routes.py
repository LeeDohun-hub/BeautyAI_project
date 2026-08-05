import json
import re
from dataclasses import replace
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import enforce_login, optional_user
from app.models import (
    ChatHistory,
    Product,
    ProductIngredient,
    RecommendationHistory,
    SkinAnalysis,
    Survey,
    User,
)
from app.schemas.api import (
    AnalyzeNailDesignResponse,
    AnalyzeSkinResponse,
    ChatRequest,
    ChatResponse,
    DetectedNail,
    FaceShapeResponse,
    HistoryOut,
    NailDesignMatch,
    NailSeasonFit,
    NailShade,
    MakeupPreviewRequest,
    MyDataDeletionResult,
    MakeupPreviewResponse,
    MoodThumbnailsResponse,
    PersonalColorItemMatchRequest,
    PersonalColorItemMatchResponse,
    PersonalColorResponse,
    ProductOut,
    RakutenProductOut,
    RecommendationRequest,
    RecommendationResponse,
    SkinScores,
    VirtualSurgeryPreviewCardsResponse,
    VirtualSurgeryRetouchResponse,
    VirtualSurgeryResponse,
)
from app.services import amazon_catalog
from app.services.chatbot import answer_skin_question
from app.services.dermatology_analyzer import DermatologyAnalyzer, SCREENING_NOTE
from app.services.image_router import get_skin_image_router
from app.services.naver_client import NaverClient
from app.services.naver_kr_enricher import enrich_products_with_naver_kr
from app.services.oliveyoung_availability import prune_global_oliveyoung
from app.services.oliveyoung_catalog import catalog_available, catalog_items, male_catalog_items
from app.services.oliveyoung_kr_search import kr_catalog_items, kr_goods_url, prune_kr_oliveyoung
from app.services.personal_color_analyzer import (
    PersonalColorAnalyzer,
    UnusablePhotoError,
    declared_personal_color_result,
)
from app.services.platform_resolver import OLIVEYOUNG_GLOBAL_DETAIL, dedup_by_line, resolve_product_platforms
from app.services.product_image_provider import fill_missing_images
from app.services.rakuten_body_links import rakuten_link_for
from app.services.rakuten_client import RakutenClient
from app.services.recommender import (
    build_platform_links,
    get_scores_from_analysis,
    matched_platforms,
    normalize_platform,
    personal_color_fit_score_for_text,
    recommend_derma_care,
    recommend_personal_color_products,
    recommend_products,
)
from app.services.skin_analyzer import SkinAnalyzer, summarize_scores

# settings.require_login 이 켜져 있으면 이 라우터 전체가 세션 없이는 401 이다.
# 프론트 게이트만으로는 API 가 그대로 열려 있어서, 운영에서는 여기까지 막아야 실제 제한이 된다.
router = APIRouter(prefix="/api", dependencies=[Depends(enforce_login)])


def _resolve_region(raw_region: str | None, request: Request, fallback: str) -> str:
    region = (raw_region or "auto").strip().lower()
    if region in {"kr", "jp"}:
        return region
    for header in ("cf-ipcountry", "x-vercel-ip-country", "cloudfront-viewer-country", "x-country-code"):
        country = (request.headers.get(header) or "").strip().upper()
        if country == "KR":
            return "kr"
        if country == "JP":
            return "jp"
    accept_language = (request.headers.get("accept-language") or "").lower()
    if accept_language.startswith("ja") or ",ja" in accept_language:
        return "jp"
    if accept_language.startswith("ko") or ",ko" in accept_language:
        return "kr"
    return fallback


# 아이템 매칭 카테고리 분류(프론트 itemMatchColumnFor와 동일 규칙). 한/영/일 토큰 모두 인식.
# 브로우/컨실러 패턴은 base/eye 보다 '먼저' 봐야 한다(눈썹칼이 eye로, 컨실러가 base로 새지 않게).
_BROW_PAT = re.compile(r"brow|eyebrow|アイブロウ|眉|아이브로우|브로우|눈썹", re.I)
_CONCEALER_PAT = re.compile(r"concealer|コンシーラー|컨실러|잡티|다크서클", re.I)
_LIPBALM_PAT = re.compile(r"lip\s*balm|balm|リップバーム|립밤|립 밤", re.I)

# 여성(기본): 립/블러셔/아이/베이스/네일 5개.
_ITEM_CATEGORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # nail을 가장 먼저 판정한다: 'Cat Eye Gel Nail Polish'처럼 이름에 eye/base가 섞인
    # 네일 상품이 makeup 카테고리로 새지 않게 한다(프론트 itemMatchColumnFor와 동일 우선순위).
    # ⚠ 'nail' 은 반드시 단어 경계로 본다. 그냥 부분문자열로 두면 **'snail'/'스네일'(달팽이
    # 점액)** 이 통째로 걸린다 — 코스알엑스 '어드벤스드 스네일 96 뮤신 에센스' 같은 K뷰티
    # 대표 스킨케어가 네일 컬럼에 꽂힌다(실측). 'polish' 도 'Polishing Peel Mask'(각질제거)가
    # 걸리므로 'polishing' 은 제외한다.
    ("nail", re.compile(
        r"(?<![a-z])nail|(?<![a-z])pedi|(?<![a-z])polish(?!ing)|(?<![a-z])lacquer"
        r"|(?<![a-z])manicure|(?<!ス)ネイル|ペディ|マニキュア|(?<!스)네일|페디|매니큐어",
        re.I)),
    ("blush", re.compile(r"blush|blusher|cheek|チーク|블러셔|치크|볼터치", re.I)),
    # ⚠ '아이'는 단독 부분문자열로 두면 **'아이보리'(ivory)·'아이스'(ice)** 가 걸린다 —
    #   '바비브라운 … 파운데이션 SPF20 W026 웜 아이보리'(파운데이션)가 아이 컬럼에 꽂혔다(실측).
    #   nail/스네일과 같은 부류의 부분문자열 오탐이라 같은 방식(부정 탐색)으로 막는다.
    ("eye", re.compile(
        r"eye|eyeshadow|shadow|palette|mascara|liner|kajal|アイシャドウ|アイライナー|マスカラ"
        r"|아이(?!보리|스크림|스크|스티|솔레|허브)|섀도|쉐도", re.I)),
    ("base", re.compile(r"base|foundation|cushion|concealer|primer|powder|shading|ファンデーション|コンシーラー|パウダー|파운데이션|쿠션|베이스", re.I)),
    # ⚠ '립'/'リップ' 도 부분문자열 오탐 계열이다(nail⊂snail, 아이⊂아이보리 와 같은 부류).
    #   '튤립'/'チューリップ'(tulip)이 걸려, 라쿠텐이 '로즈 핑크 립' 검색에 물어온
    #   **캔들홀더**(キャンドルホルダー … チューリップ型 … 燭台)가 립 컬럼에 카드로 떴다(실측 2026-08-04).
    #   'lip' 영문은 tulip 이 (?<![a-z]) 로 이미 막힌다.
    ("lip", re.compile(
        r"(?<![a-z])lip|lipstick|tint|rouge|gloss|balm|(?<!チュー)リップ|ルージュ|ティント"
        r"|(?<!튤)립|틴트", re.I)),
]

# 남성(Level 2): 베이스/브로우/컨실러/립밤 4개. 색조(블러셔/아이/네일) 대신 그루밍 중심.
# 컨실러·브로우를 base/eye 보다 먼저 판정해야 정확히 분류된다(base 정규식이 concealer 포함).
_ITEM_CATEGORY_PATTERNS_MALE: list[tuple[str, re.Pattern[str]]] = [
    ("concealer", _CONCEALER_PAT),
    ("brow", _BROW_PAT),
    ("lipbalm", _LIPBALM_PAT),
    ("base", re.compile(r"base|foundation|cushion|primer|powder|bb|톤업|파운데이션|쿠션|베이스|비비", re.I)),
    ("lipbalm", re.compile(r"lip|틴트|립", re.I)),  # 립밤 외 자연 립/틴트도 립밤 컬럼으로
]


def _item_category_patterns(gender: str) -> list[tuple[str, re.Pattern[str]]]:
    return _ITEM_CATEGORY_PATTERNS_MALE if (gender or "").lower() == "male" else _ITEM_CATEGORY_PATTERNS


# 비화장품 배제: '남자 쿠션' 검색이 쿠션 신발/양말/방석 같은 잡화를 물어와 base로 오분류되는
# 문제를 막는다(사용자 지적). 상품명에 이 토큰이 있으면 어느 카테고리도 아님(제외)으로 본다.
_NON_COSMETIC_RE = re.compile(
    r"운동화|신발|슬리퍼|샌들|부츠|구두|로퍼|스니커|깔창|양말|방석|베개|매트|의자|소파|침대|러그"
    r"|쿠션커버|커버지|스카프|장갑|모자|가방|지갑|벨트|시계|이어폰|충전|케이블|거치"
    # 일본어 잡화(‘メンズ クッション’이 쿠션 양말/신발을 물어옴): 양말/신발/방석/베개/의자 등.
    r"|ソックス|靴下|スニーカー|サンダル|スリッパ|ブーツ|クッションカバー|座布団|まくら|枕|マット|椅子|ソファ|寝具"
    # 화장 '도구'·헤어 액세서리. 라쿠텐 색상 검색이 물어온 실측 오탐:
    # 'ヘアクリップ レディース … ドライローズ …'(헤어클립)이 립 컬럼에,
    # 'メイクブラシ 5本セット … チーク …'(붓 세트)가 블러셔 컬럼에 카드로 떴다.
    # ⚠ 'ブラシ' 단독으로 자르면 안 된다 — 'ドド ブラシリキッドリップ'(브러시형 립)처럼
    #   제품명 안에 붓이 들어간 **화장품**이 함께 사라진다. 그래서 붓/필은 세트·수량 표기
    #   (メイクブラシ / 化粧筆 / ○本セット)와 함께 있을 때만 도구로 본다.
    r"|ヘアクリップ|ヘアゴム|ヘアバンド|ヘアピン|헤어클립|헤어밴드|헤어핀|머리끈"
    r"|メイクブラシ|化粧筆|ブラシ\s*\d*\s*本セット|筆\s*\d*\s*本セット|메이크업\s*브러시\s*세트|화장붓"
    r"|ピンセット|毛抜き|付け爪切|ネイルチップケース|収納ケース|コスメポーチ|化粧ポーチ"
    r"|핀셋|족집게|화장품\s*케이스|화장\s*파우치"
    # 인테리어 잡화. 라쿠텐 색상 검색이 '로즈 핑크 립'에 캔들홀더를 물어왔다(실측 2026-08-04):
    # 'キャンドルホルダー 北欧 陶器 … 燭台 インテリア 雑貨 チューリップ型 …'
    r"|キャンドルホルダー|燭台|キャンドルスタンド|花瓶|置物|インテリア雑貨|캔들홀더|촛대|화병",
    re.I,
)

# 이름이 '이 카테고리가 아님'을 분명히 말하는 경우. 키워드 폴백이 이를 되살리지 못하게 한다.
#
# 왜 필요한가: 분류는 이름 → 키워드 순으로 본다. 이름이 안 걸리면 '무엇을 검색했나'(키워드)로
# 넘어가는데, 이름 쪽 정규식이 **일부러 제외한** 상품이 여기서 되살아난다.
# 실측: 코스알엑스 '스네일 뮤신 에센스'(스킨케어)가 '네일' 키워드 검색 결과로 와서,
# 이름 판정은 (?<!스)네일 로 걸러졌는데 키워드 '네일'이 그대로 nail 컬럼에 꽂았다.
_CATEGORY_NAME_ANTI_PATTERNS: dict[str, re.Pattern[str]] = {
    "nail": re.compile(r"스네일|snail|スネイル", re.I),
    "lip": re.compile(r"튤립|tulip|チューリップ", re.I),
    "eye": re.compile(r"아이보리|ivory|아이스크림", re.I),
}


def _item_match_category(product, gender: str = "female") -> str | None:
    text = f"{product.keyword or ''} {product.name or ''}"
    if _NON_COSMETIC_RE.search(text):
        return None  # 신발/양말·화장도구 등 잡화 → 화장품 컬럼에서 제외
    patterns = _item_category_patterns(gender)
    name = (product.name or "").lower()
    by_name = next((c for c, pattern in patterns if pattern.search(name)), None)
    by_keyword = next((c for c, pattern in patterns if pattern.search((product.keyword or "").lower())), None)
    # 상품명이 카테고리를 분명히 말하면 상품명을 따른다. 키워드는 '무엇을 검색했나'일 뿐이고
    # 검색 결과가 다른 카테고리 상품일 수 있어서다 — 실측: 'ドライローズ リップ'(립) 검색이
    # 물어온 'romnd ベターザンアイズ アイシャドウ'(아이섀도우)가 립 컬럼에 카드로 떴다.
    if by_name:
        return by_name

    # 이름이 '그 카테고리가 아님'을 말하면 키워드로도, 합친 텍스트로도 되살리지 않는다.
    # ⚠ 한 군데만 막으면 다음 폴백에서 다시 살아난다 — 실제로 by_keyword 만 막았더니
    #   마지막 텍스트 폴백(키워드+이름)이 키워드 쪽 '네일'을 다시 잡았다.
    def contradicted(category: str | None) -> bool:
        anti = _CATEGORY_NAME_ANTI_PATTERNS.get(category or "")
        return bool(anti and anti.search(name))

    if by_keyword and not contradicted(by_keyword):
        return by_keyword
    by_text = next((c for c, pattern in patterns if pattern.search(text.lower())), None)
    return None if contradicted(by_text) else by_text


_ITEM_CATEGORIES_FEMALE = ("lip", "blush", "eye", "base", "nail")
_ITEM_CATEGORIES_MALE = ("base", "brow", "concealer", "lipbalm")


def _interleave_by_category(keywords: list[str], gender: str, per_category: int | None = None) -> list[str]:
    """검색 키워드를 카테고리 라운드로빈으로 재정렬(+선택적으로 카테고리당 개수 제한)한다.

    라쿠텐/네이버 search_many 는 스로틀 없이 키워드를 순차 호출하는데, 라쿠텐은 ~1req/s로
    429를 주므로 뒤쪽 카테고리(입력 순서상 eye/base/nail)가 통째로 굶어 컬럼이 빈다
    (사용자 관측: JP eye 간헐 빔). 각 카테고리의 '첫 키워드'를 앞쪽에 모아 rate-limit 전에
    모든 컬럼이 검색되게 한다.

    per_category=1 이면 카테고리당 1개만 남겨 총 요청을 카테고리 수(≤5)로 묶는다 — 라쿠텐
    rate-limit 안쪽이라 모든 컬럼이 확정적으로 채워진다(색상 다양성은 약간 줄어드는 트레이드오프,
    사용자 결정 2026-07-27). DB 색상매칭은 전체 키워드를 그대로 쓰므로 영향 없다.
    """
    from collections import defaultdict

    buckets: dict[str, list[str]] = defaultdict(list)
    order: list[str] = []
    for kw in keywords:
        cat = _item_match_category(SimpleNamespace(keyword=kw, name=""), gender) or "_"
        if cat not in buckets:
            order.append(cat)
        buckets[cat].append(kw)
    rounds = max((len(b) for b in buckets.values()), default=0)
    if per_category is not None:
        rounds = min(rounds, per_category)
    out: list[str] = []
    for r in range(rounds):
        for cat in order:
            if r < len(buckets[cat]):
                out.append(buckets[cat][r])
    return out


def _pick_diverse(bucket: list, k: int) -> list:
    """컬럼 하나에서 k개를 뽑되 라쿠텐 라이브가 상위를 독식하지 않게 한다(사용자 지시 2026-07-27).

    비-라쿠텐(직링크 DB/네이버/올리브영/아마존)을 먼저 채우고 라쿠텐으로 남은 칸을 메운다.
    대안이 없으면 라쿠텐으로 채워 컬럼이 비지 않게 한다(직링크만 정책과 양립). bucket은 점수순.
    """
    non_rk = [x for x in bucket if (getattr(x, "source", "") or "") != "rakuten"]
    rk = [x for x in bucket if (getattr(x, "source", "") or "") == "rakuten"]
    picked: list = []
    i = j = 0
    while len(picked) < k and (i < len(non_rk) or j < len(rk)):
        if i < len(non_rk):
            picked.append(non_rk[i]); i += 1
        if len(picked) < k and j < len(rk):
            picked.append(rk[j]); j += 1
    return picked


def _balance_item_categories(items: list, limit: int = 10, per_category: int = 2, gender: str = "female") -> list:
    """점수순 상품을 성별 카테고리 세트에 고르게 배분한다.

    여성=립/블러셔/아이/베이스/네일, 남성=베이스/브로우/컨실러/립밤. '모든 플랫폼'에서 특정
    소스가 상위를 독식해 일부 컬럼이 비는 문제를 막는다. 각 카테고리 상위 per_category개를
    먼저 확보하고 남은 칸은 점수순으로 채운다. 단 남성 세트에선 여성 전용 카테고리(블러셔/아이/
    네일) 상품은 '남은 칸 채우기'에서도 제외한다(색조가 남성 결과에 새는 것 방지).
    """
    categories = _ITEM_CATEGORIES_MALE if (gender or "").lower() == "male" else _ITEM_CATEGORIES_FEMALE
    buckets: dict[str, list] = {c: [] for c in categories}
    for item in items:  # items는 점수 내림차순 정렬 상태
        category = _item_match_category(item, gender)
        if category in buckets:
            buckets[category].append(item)

    male = (gender or "").lower() == "male"
    selected: list = []
    seen: set[int] = set()
    for category in categories:
        for item in _pick_diverse(buckets[category], per_category):
            selected.append(item)
            seen.add(id(item))
    # 남은 칸 채우기. 여성은 기존대로 점수순 아무 상품이나(프론트가 미분류를 렌더에서 거른다).
    # 남성은 남성 카테고리(base/brow/concealer/lipbalm)에 속한 상품만 채운다 — 블러셔/아이/네일
    # 같은 색조가 '남은 칸'으로 남성 결과에 새지 않게 한다.
    in_scope = {id(item) for bucket in buckets.values() for item in bucket}
    for item in items:
        if len(selected) >= limit:
            break
        if id(item) in seen:
            continue
        if male and id(item) not in in_scope:
            continue
        selected.append(item)
        seen.add(id(item))
    return selected[:limit]


# JP 남성 아이템매칭: 글로벌몰 남성 상품을 카드로 주입한다(라쿠텐엔 한국 남성 브랜드가 안 떠서
# 이 소스가 없으면 남성 컬럼이 빈다). 카테고리→키워드로 분류를 고정하고, resolve_product_platforms가
# 이후 올리브영 글로벌 직링크 버튼을 붙인다(카탈로그 매칭). 색조 아닌 4개 카테고리만 노출.
_MALE_CAT_KEYWORD = {"base": "쿠션", "brow": "아이브로우", "concealer": "컨실러", "lipbalm": "립밤"}
_USD_TO_JPY = 150  # 글로벌몰 USD → JP 카드 표시가 근사(정밀 환율 아님).


def _inject_male_global_products(products: list, region: str = "jp", limit_per_cat: int = 6) -> None:
    seen = {(p.brand, p.name) for p in products}
    counts: dict[str, int] = {}
    for m in male_catalog_items():
        # 분류는 한글명으로(카테고리어 쿠션/아이브로우/컨실러/립밤이 한글이라 정확히 잡힌다).
        # 표기는 지역별(JP=일본어명/브랜드). keyword를 카테고리어로 고정해 분류를 안정화한다.
        cat = _item_match_category(SimpleNamespace(keyword="", name=m.name_kr or m.name_en), "male")
        name = m.localized_name(region)
        brand = m.localized_brand(region)
        if cat not in _MALE_CAT_KEYWORD or (brand, name) in seen:
            continue
        if counts.get(cat, 0) >= limit_per_cat:
            continue
        seen.add((brand, name))
        counts[cat] = counts.get(cat, 0) + 1
        url = OLIVEYOUNG_GLOBAL_DETAIL + quote_plus(m.prdt_no)
        products.append(
            RakutenProductOut(
                id=f"oyg-{m.prdt_no}",
                brand=brand,
                name=name,
                price=int(round(m.price_usd * _USD_TO_JPY)),
                image_url=m.image_url or None,
                product_url=url,
                keyword=_MALE_CAT_KEYWORD[cat],
                source="oliveyoung_global",
                # 큐레이션된 OY 남성상품이 컬럼을 우선 차지하도록 라쿠텐(여성/잡화 노이즈 포함)보다
                # 확실히 높게. JP 남성 목표는 OY 남성고객 확보라, 라쿠텐은 OY가 모자랄 때만 채운다.
                score=100.0,
                platform_links={"oliveyoung": url},
                matched_platforms=["oliveyoung"],
            )
        )


_OY_KR_NAIL_SCORE_BOOST = 60.0

# 주입 카드의 배지 라벨(사용자에게 보이는 카테고리어). 프론트는 ASCII 단일 토큰 배지를 숨기므로
# 한국어로 둔다.
_INJECT_KEYWORD = {
    "lip": "립", "blush": "블러셔", "eye": "아이섀도우", "base": "베이스", "nail": "네일",
}

# 카탈로그에는 화장품이 아닌 도구·포장재도 섞여 있다. 실측으로 '빈 화장품 용기'(ネイルアート
# パウダー丸薬コンテナ)가 카드로 나온 적이 있어, 주입 후보에서 먼저 걸러낸다.
_CATALOG_JUNK = re.compile(
    r"容器|コンテナ|空の|ケース|スタンド|ランプ|ライト|ブラシ|筆|パフ|puff"
    r"|storage|organizer|holder|container|clipper|scissor|tweezer|손톱깎|퍼프|브러쉬|브러시",
    re.I,
)


def _thin_item_categories(products: list, gender: str, minimum: int = 2) -> set[str]:
    """후보가 `minimum` 개 미만인 컬럼. 카탈로그 주입은 여기에만 한다.

    무조건 주입하면 가산점 때문에 카탈로그 상품이 모든 컬럼을 차지해, 색상 매칭이 잘 된
    라이브 상품이 밀려난다. '비어 있는 칸만' 메우는 게 목적이다.
    """
    categories = _ITEM_CATEGORIES_MALE if (gender or "").lower() == "male" else _ITEM_CATEGORIES_FEMALE
    counts: dict[str, int] = {}
    for product in products:
        category = _item_match_category(product, gender)
        if category:
            counts[category] = counts.get(category, 0) + 1
    return {c for c in categories if counts.get(c, 0) < minimum}


def _inject_kr_oliveyoung_catalog(
    products: list, keywords: list[str], wanted: set[str], per_category: int = 3
) -> None:
    """KR 올리브영 탭에서 **비어 있는 컬럼**을 카탈로그 상품으로 채운다(사용자 결정 2026-07-29).

    이 컬럼은 카탈로그를 아무리 키워도 안 채워졌다. 후보를 만드는 쪽(네이버 색상검색)이
    프롬더네일·로지힙·RARJSM 을 물어오는데 올리브영이 파는 건 데싱디바·오호라·젤로젤로라
    **두 집합이 겹치지 않아** 입점 검증이 항상 0/12 였기 때문이다(카탈로그 7→73건 확장
    전후 동일). 그래서 검증기로만 쓰던 카탈로그를 이 컬럼에 한해 **후보 소스**로도 쓴다.

    ⚠️ 트레이드오프(사용자 승인): 올영 네일은 '매직프레스 35종'·'폴리쉬 41 Colors' 같은
    다색 세트가 많아 시즌 색상 매칭이 약하다. 색은 사용자가 세트 안에서 고르는 전제다.
    그래서 점수는 색상 적합도로 정직하게 매기고(세트명에 색이 들어가면 그만큼만 올라간다),
    억지로 상위에 고정하지 않는다 — 색이 맞는 상품이 있으면 그쪽이 먼저 온다.
    """
    if not wanted:
        return
    seen = {(p.brand, p.name) for p in products}
    # 카탈로그 순서대로 앞에서 자르면 한 브랜드(웨이크메이크)로 쏠린다. 색상 적합도로 점수를
    # 매겨 정렬한 뒤 뽑고, 브랜드당 2개로 제한해 다른 취급 브랜드도 들어오게 한다.
    scored: list[tuple[float, str, object]] = []
    for item in kr_catalog_items():
        if (item.brand, item.name) in seen or _CATALOG_JUNK.search(item.name):
            continue
        # 카탈로그 상품의 카테고리는 상품명으로 판정한다(스네일 오분류는 패턴에서 차단됨).
        category = _item_match_category(SimpleNamespace(keyword="", name=item.name), "female")
        if category not in wanted:
            continue
        scored.append((
            personal_color_fit_score_for_text(
                item.brand, item.name, category, "", keywords,
                platform_score=8.0, rating_score=4.0,
            ),
            category,
            item,
        ))
    scored.sort(key=lambda row: row[0], reverse=True)

    per_brand: dict[str, int] = {}
    per_cat: dict[str, int] = {}
    for score, category, item in scored:
        if per_cat.get(category, 0) >= per_category:
            continue
        if per_brand.get(item.brand, 0) >= 2:
            continue
        per_brand[item.brand] = per_brand.get(item.brand, 0) + 1
        per_cat[category] = per_cat.get(category, 0) + 1
        url = kr_goods_url(item.goods_no)
        products.append(
            RakutenProductOut(
                id=f"oykr-{item.goods_no}",
                brand=item.brand,
                name=item.name,
                price=0,  # 카탈로그에 가격 컬럼이 없다 — 프론트가 '가격 정보 없음'으로 표시.
                image_url=item.image_url or None,
                product_url=url,
                keyword=_INJECT_KEYWORD[category],
                source="oliveyoung_kr",
                # 색상 적합도 순서는 유지하되 가산점으로 네이버 네일 후보(82~84점)보다 위에
                # 둔다. 안 그러면 balance 에서 네이버 후보가 네일 칸을 먼저 차지하고, 그게
                # 곧바로 입점 검증에서 전멸해 컬럼이 다시 빈다(실측). 올리브영 탭에서는
                # '올영 카탈로그 상품'이 정의상 가장 확실히 살 수 있는 카드다.
                # (JP 남성 _inject_male_global_products 가 score=100 을 쓰는 것과 같은 이유.)
                score=score + _OY_KR_NAIL_SCORE_BOOST,
                platform_links={"oliveyoung": url},
                matched_platforms=["oliveyoung"],
            )
        )


# 카탈로그에서 카테고리별 후보를 뽑을 때 쓰는 패턴(라우터의 분류 패턴을 그대로 재사용해
# 프론트/백엔드/주입이 같은 규칙을 쓰게 한다). 정확한 카테고리는 뽑은 뒤 _item_match_category
# 로 다시 확정한다 — 패턴끼리 겹치기 때문(예: 'Cat Eye Nail' 은 eye 패턴에도 걸린다).
_CATEGORY_PATTERN = {name: pattern for name, pattern in _ITEM_CATEGORY_PATTERNS}


# 카테고리당 채점할 상위 후보 수(리뷰순).
_AMAZON_POOL_SCAN = 600


@lru_cache(maxsize=16)
def _amazon_category_pool(catalog_region: str, category: str) -> tuple:
    """아마존 카탈로그에서 그 카테고리로 확정된 상품만 추린 풀(캐시).

    분류(`_item_match_category`)는 카탈로그 수천~수만 건에 정규식을 돌리는 무거운 작업인데
    **키워드와 무관**하다 — 매 요청 반복하면 카테고리 하나당 2초씩 든다(실측: 5개 카테고리
    9.5초). 키워드에 의존하는 건 점수뿐이라, 분류까지만 캐시하고 점수는 그때그때 매긴다.
    """
    pattern = _CATEGORY_PATTERN.get(category)
    if pattern is None:
        return ()
    entries = [
        entry
        for entry in amazon_catalog.catalog_entries(catalog_region, pattern.pattern)
        if not _CATALOG_JUNK.search(entry.title)
        # 패턴은 서로 겹치므로 최종 카테고리를 다시 확정한다(네일 패턴에 아이섀도우가 걸리는 등).
        and _item_match_category(SimpleNamespace(keyword="", name=entry.title), "female") == category
    ]
    # 리뷰 많은 순으로 둔다 — 아래에서 상위 일부만 채점하므로, 잘린 뒤쪽에 남는 건
    # 리뷰가 거의 없는 무명 리스팅이라 잘려도 손해가 작다.
    entries.sort(key=lambda entry: entry.reviews or 0, reverse=True)
    return tuple(entries)


def _inject_amazon_catalog(
    products: list, keywords: list[str], region: str, wanted: set[str], per_category: int = 3
) -> None:
    """아마존 탭에서 **비어 있는 컬럼**을 아마존 카탈로그 상품(실 ASIN)으로 채운다.

    올리브영과 같은 구조의 공백이다 — 후보를 만드는 색상검색(네이버/라쿠텐)이 물어오는
    브랜드를 아마존이 안 팔면, 브랜드/토큰 매핑을 고쳐도 그 컬럼은 비어 있다.
    ASIN 직링크가 이미 확인된 행이라 죽은 링크 위험은 없다.
    """
    if not wanted:
        return
    catalog_region = "jp" if region == "jp" else "us"
    key = "amazon_jp" if catalog_region == "jp" else "amazon_us"
    make_url = amazon_catalog.amazon_jp_url if catalog_region == "jp" else amazon_catalog.amazon_com_url
    seen = {(p.brand, p.name) for p in products}

    for category in wanted:
        scored: list[tuple[float, object]] = []
        # 풀 전체(카테고리당 최대 9천여 건)를 채점하면 요청마다 수 초가 든다(실측 5카테고리 6초).
        # 리뷰순 상위만 본다 — 여기서 못 찾을 만큼 색이 특이하면 어차피 대표 상품이 아니다.
        for entry in _amazon_category_pool(catalog_region, category)[:_AMAZON_POOL_SCAN]:
            scored.append((
                personal_color_fit_score_for_text(
                    entry.brand_key, entry.title, category, "", keywords,
                    platform_score=8.0, rating_score=4.0,
                ),
                entry,
            ))
        # 색상 적합도 우선, 동점이면 리뷰가 많은 대표 상품(죽은/희귀 리스팅 회피).
        scored.sort(key=lambda row: (row[0], row[1].reviews or 0), reverse=True)

        per_brand: dict[str, int] = {}
        added = 0
        for score, entry in scored:
            if added >= per_category:
                break
            brand = entry.brand_key or "amazon"
            title = entry.title.strip()
            if (brand, title) in seen or per_brand.get(brand, 0) >= 2:
                continue
            seen.add((brand, title))
            per_brand[brand] = per_brand.get(brand, 0) + 1
            added += 1
            url = make_url(entry.asin)
            products.append(
                RakutenProductOut(
                    id=f"amz-{entry.asin}",
                    brand=brand,
                    name=title,
                    price=0,
                    image_url=entry.image_url or None,
                    product_url=url,
                    review_count=entry.reviews or None,
                    keyword=_INJECT_KEYWORD[category],
                    source="amazon_catalog",
                    # 올영 주입과 같은 이유의 가산점(주석은 _inject_kr_oliveyoung_catalog 참조).
                    score=score + _OY_KR_NAIL_SCORE_BOOST,
                    platform_links={key: url},
                    matched_platforms=[key],
                )
            )


def _inject_jp_oliveyoung_catalog(
    products: list, keywords: list[str], wanted: set[str], per_category: int = 3
) -> None:
    """JP 올리브영 탭에서 **비어 있는 컬럼**을 글로벌몰 카탈로그 상품으로 채운다.

    KR 쪽 `_inject_kr_oliveyoung_catalog` 와 같은 구조의 공백이다: JP 후보는 라쿠텐 라이브
    검색뿐인데 라쿠텐엔 한국 색조 브랜드가 거의 안 떠, 카탈로그를 '검증기'로만 쓰면 그 컬럼이
    영원히 빈다(실측: JP+올리브영 탭 블러셔 0건·네일 0건인데 카탈로그엔 블러셔 63건·네일 10건).
    카탈로그 prdtNo 직링크라 입점 검증을 다시 거칠 필요가 없다.
    """
    if not wanted:
        return
    seen = {(p.brand, p.name) for p in products}
    scored: list[tuple[float, str, object]] = []
    for item in catalog_items():
        # 분류는 한글/영문명으로(카테고리어가 그쪽에 있다). 표기는 아래에서 지역별(JP=일본어).
        classify_name = item.name_kr or item.name_en
        if _CATALOG_JUNK.search(classify_name):
            continue
        category = _item_match_category(SimpleNamespace(keyword="", name=classify_name), "female")
        if category not in wanted:
            continue
        name = item.localized_name("jp")
        brand = item.localized_brand("jp")
        if (brand, name) in seen:
            continue
        scored.append((
            personal_color_fit_score_for_text(
                item.brand, classify_name, category, "", keywords,
                platform_score=8.0, rating_score=4.0,
            ),
            category,
            item,
        ))
    scored.sort(key=lambda row: row[0], reverse=True)

    per_brand: dict[str, int] = {}
    per_cat: dict[str, int] = {}
    for score, category, item in scored:
        if per_cat.get(category, 0) >= per_category or per_brand.get(item.brand, 0) >= 2:
            continue
        per_brand[item.brand] = per_brand.get(item.brand, 0) + 1
        per_cat[category] = per_cat.get(category, 0) + 1
        url = OLIVEYOUNG_GLOBAL_DETAIL + quote_plus(item.prdt_no)
        products.append(
            RakutenProductOut(
                id=f"oyg-{item.prdt_no}",
                brand=item.localized_brand("jp"),
                name=item.localized_name("jp"),
                price=int(round(item.price_usd * _USD_TO_JPY)),
                image_url=item.image_url or None,
                product_url=url,
                keyword=_INJECT_KEYWORD[category],
                source="oliveyoung_global",
                # KR 주입과 같은 이유의 가산점(주석은 _inject_kr_oliveyoung_catalog 참조).
                score=score + _OY_KR_NAIL_SCORE_BOOST,
                platform_links={"oliveyoung": url},
                matched_platforms=["oliveyoung"],
            )
        )


# 라쿠텐 검색은 사실상 AND 매칭이라 **복합 색상어**가 붙으면 0건이 된다(실측:
# 'ニュートラルピンク ファンデーション' 0건, 'ライトクールベージュ ファンデーション' 0건,
# 'ファンデーション' 단독 6건). 카테고리당 키워드를 1개만 보내는 구조라(rate-limit) 그 1개가
# 0건이면 컬럼이 통째로 빈다 — JP+라쿠텐 베이스 컬럼이 항상 비어 있던 원인.
# 그래서 색상어를 단계적으로 단순화한 재질의 후보를 만든다.
_JP_BASE_COLORS = (
    "ベージュ", "ピンク", "ローズ", "ブラウン", "コーラル", "レッド", "オレンジ", "ヌード",
    "モーブ", "プラム", "ワイン", "ベリー", "ピーチ", "オリーブ", "カーキ", "グレー",
    "ラベンダー", "アイボリー", "サンド",
)
_KO_BASE_COLORS = (
    "베이지", "핑크", "로즈", "브라운", "코랄", "레드", "오렌지", "누드", "모브", "플럼",
    "와인", "베리", "피치", "올리브", "카키", "그레이", "라벤더", "아이보리", "샌드",
)


def _broaden_keyword(keyword: str) -> list[str]:
    """0건 키워드의 재질의 후보(구체적 → 일반). 마지막은 카테고리어 단독."""
    tokens = (keyword or "").split()
    if len(tokens) < 2:
        return []
    color, category = " ".join(tokens[:-1]), tokens[-1]
    out: list[str] = []
    # 복합 색상어에 들어있는 '기본 색'만 남겨 재질의(ニュートラルピンク → ピンク).
    for base in (*_JP_BASE_COLORS, *_KO_BASE_COLORS):
        if base in color and base != color:
            out.append(f"{base} {category}")
            break
    out.append(category)  # 최후: 카테고리어 단독(색 매칭은 약해지지만 컬럼이 비지 않는다)
    return [c for c in dict.fromkeys(out) if c != keyword]


def _rakuten_search_with_fallback(client, keywords: list[str], hits_per_keyword: int, throttle: float) -> list:
    """카테고리별 키워드로 라쿠텐을 검색하고, 0건 카테고리만 완화된 키워드로 재질의한다.

    재질의는 `client.search`(단발)로 한다 — `search_many` 를 쓰면 내부에서 0건 키워드를
    한 번 더 재시도하고 throttle 만큼 sleep 까지 해서, 폴백 1건당 API 3회+1.1s 가 붙는다
    (실측: 이걸로 JP 아이템매칭이 7.6s → 14s 로 늘어났다).
    """
    results = client.search_many(keywords, hits_per_keyword=hits_per_keyword, throttle=throttle)
    found = {getattr(item, "keyword", "") for item in results}
    for keyword in keywords:
        if keyword in found:
            continue
        for candidate in _broaden_keyword(keyword):
            retry = client.search(candidate, hits=hits_per_keyword)
            if retry:
                # 배지/컬럼 분류는 '원래 키워드' 기준을 유지한다(완화된 질의어가 카드에 노출되면
                # 사용자가 요청한 색과 달라 보인다). RakutenProduct 는 frozen 이라 replace 로 교체.
                results.extend(replace(item, keyword=keyword) for item in retry)
                break
    return results


def _verified_rakuten_url(client, brand: str, name: str) -> str:
    """라쿠텐 API로 '브랜드 일치' 실제 리스팅을 찾아 검증된 상품 직링크를 반환한다(없으면 "").

    사용자 원칙: 직링크 있으면 버튼, 없으면 미출력(검색 폴백 없음). 재현율을 위해 전체 상품명
    (너무 구체적)뿐 아니라 '브랜드+핵심어'로도 재검색한다. 히트 중 브랜드 문자열(라틴 브랜드
    또는 DB 브랜드)이 실제로 담긴 리스팅만 채택해 엉뚱한 상품 링크를 막는다."""
    name = name or ""
    latin = re.match(r"[A-Za-z][A-Za-z0-9.&'-]+", name)
    latin_brand = latin.group() if latin else ""
    brand_keys = [k.lower() for k in (latin_brand, brand or "") if k]
    if not brand_keys:
        return ""
    # 쿼리 후보: (1) 전체명(정확도) (2) 앞 3토큰 (3) 브랜드+핵심어(재현율). 첫 브랜드매칭 히트 채택.
    core = " ".join(name.split()[:3])
    for query in (name, core, f"{latin_brand} {brand}".strip()):
        if not query.strip():
            continue
        hits = client.search(query, hits=3)
        match = next((h for h in hits if any(k in f"{h.brand} {h.name}".lower() for k in brand_keys)), None)
        if match and match.product_url:
            return match.product_url
    return ""


def _attach_rakuten(p, url: str) -> None:
    links = dict(getattr(p, "platform_links", None) or {})
    links["rakuten"] = url  # 검증된 실제 라쿠텐 상품 페이지(직링크)
    p.platform_links = links
    p.matched_platforms = sorted(links.keys())


# 상품 URL 도메인 → 프론트가 렌더하는 플랫폼 버튼 키(ITEM_PLATFORM_META).
_NATIVE_LINK_DOMAINS = (
    ("oliveyoung.co.kr", "oliveyoung"),
    ("global.oliveyoung", "oliveyoung"),
    ("matsukiyo", "matsukiyo"),
    ("amazon.co.jp", "amazon_jp"),
    ("amazon.com", "amazon_us"),
    ("naver", "naver"),
    ("lotteon", "naver"),
)


def _backfill_native_body_link(product) -> None:
    """플랫폼 링크가 통째로 빈 상품에 원산지 URL을 버튼으로 되살린다."""
    links = getattr(product, "platform_links", None) or {}
    if links:
        return
    url = (getattr(product, "product_url", "") or "").strip()
    if not url:
        return
    low = url.lower()
    for needle, key in _NATIVE_LINK_DOMAINS:
        if needle in low:
            product.platform_links = {key: url}
            product.matched_platforms = [key]
            return


_DISPLAY_NAME_NOISE = re.compile(r"[\s\[\]()（）【】/,·・…]+")
# 라쿠텐은 점포/판촉 태그를 【…】 로 붙인다 — 같은 상품인데 점포마다 【hc8】·【hc9】 처럼
# **마지막 한 글자만** 달라서 접두 규칙으로도 안 접혔다(실측). 태그는 내용째 지운다.
_RAKUTEN_SHOP_TAG = re.compile(r"【[^】]*】")


def _display_name_key(product) -> str:
    """표시명 dedup 키. 점포 태그를 지우고 공백·괄호류를 접는다(그 외는 보존)."""
    name = _RAKUTEN_SHOP_TAG.sub("", (getattr(product, "name", "") or "").strip().lower())
    return _DISPLAY_NAME_NOISE.sub("", name)


# 한쪽 이름이 다른 쪽의 '앞부분 전체'면 같은 상품으로 본다. 라쿠텐은 같은 상품을 점포마다
# 팔면서 뒤에 점포/판촉 코드만 덧붙인다 — 실측 '…しっかり発色]' vs '…しっかり発色]【hc8】'
# (브랜드 자리도 점포명이라 dedup_by_line 도 못 접는다). 너무 짧은 이름끼리 접히지 않게 하한을 둔다.
_PREFIX_DEDUP_MIN = 20
# 점포마다 '문구 한두 글자'만 다른 경우는 접두 규칙으로도 못 접는다. 실측(네일 컬럼 중복 2장):
#   '…16ml ポリッシュタイプ UV・LED対応 初心者＆プロ適用…(3022 ドライローズ)'
#   '…16ml ポリッシュタイプ UV・LED     初心者＆プロ適用…(3022 ドライローズ)'
# 차이('対応')가 **문자열 중간**이라 접두/포함 어느 쪽도 성립하지 않는다. 그래서 충분히 긴
# 이름끼리는 유사도로도 접는다(오접힘 방지를 위해 문턱을 높게 둔다).
_SIMILAR_DEDUP_MIN_LEN = 30
_SIMILAR_DEDUP_RATIO = 0.95


def _dedup_by_display_name(products: list) -> list:
    """표시명이 같은(또는 한쪽이 다른 쪽의 접두인) 카드를 접고 구매 링크는 합친다.

    입력은 점수 내림차순 가정 — 먼저 온 카드를 남긴다.
    """
    kept: dict[str, object] = {}
    order: list[str] = []

    def find_existing(key: str) -> str | None:
        if key in kept:
            return key
        for other in order:
            if len(other) < _PREFIX_DEDUP_MIN or len(key) < _PREFIX_DEDUP_MIN:
                continue
            if other.startswith(key) or key.startswith(other):
                return other
            if (
                len(other) >= _SIMILAR_DEDUP_MIN_LEN
                and len(key) >= _SIMILAR_DEDUP_MIN_LEN
                and SequenceMatcher(None, other, key).ratio() >= _SIMILAR_DEDUP_RATIO
            ):
                return other
        return None

    for product in products:
        key = _display_name_key(product)
        if not key:
            order.append(f"__blank__{len(order)}")
            kept[order[-1]] = product
            continue
        existing = find_existing(key)
        if existing is None:
            kept[key] = product
            order.append(key)
            continue
        keep = kept[existing]
        combined = dict(getattr(keep, "platform_links", None) or {})
        for name, url in (getattr(product, "platform_links", None) or {}).items():
            combined.setdefault(name, url)
        keep.platform_links = combined
        keep.matched_platforms = sorted(combined)
        if not getattr(keep, "image_url", None) and getattr(product, "image_url", None):
            keep.image_url = product.image_url
    return [kept[key] for key in order]


def _attach_links_keeping_direct(product, region: str) -> None:
    """주입 상품에 나머지 플랫폼 링크를 붙인다 — 단, 갖고 있던 **직링크는 지키면서**.

    주입 상품은 카탈로그 직링크(국내몰 goodsNo / 글로벌 prdtNo / 아마존 ASIN) 하나만 들고
    온다. 그대로 두면 '모든 플랫폼' 이 아닌 탭에서 걸러져 컬럼이 다시 빈다.
    그렇다고 `resolve_product_platforms` 를 그냥 돌리면 그 직링크를 **검색 링크로 격하**시킨다
    (KR 국내몰은 Cloudflare 때문에 검증이 불가해 resolve 가 검색 링크만 만든다) — 카탈로그가
    확정해 준 상품을 다시 추측으로 되돌리는 셈이다. 그래서 결과를 덮어쓰지 않고 병합한다.
    """
    direct = dict(getattr(product, "platform_links", None) or {})
    resolve_product_platforms(product, region)
    links = dict(getattr(product, "platform_links", None) or {})
    links.update(direct)  # 직링크가 검색 링크를 이긴다
    product.platform_links = links
    product.matched_platforms = sorted(links)


def _filter_by_requested_platform(products: list, platform: str) -> list:
    platform = normalize_platform(platform)
    if platform == "all":
        return products
    return [
        product
        for product in products
        if (getattr(product, "platform_links", None) or {}).get(platform)
    ]


def _verify_rakuten_for_global(products: list, client) -> None:
    """OY 글로벌 주입(JP 남성 아이템매칭) 상품에 라쿠텐 검증 직링크를 붙인다."""
    if not client.configured:
        return
    for p in products:
        if getattr(p, "source", "") != "oliveyoung_global":
            continue
        url = _verified_rakuten_url(client, p.brand or "", p.name or "")
        if url:
            _attach_rakuten(p, url)


def _verify_rakuten_for_skincare(products: list, client, limit: int = 6) -> None:
    """JP 스킨케어(피부상태) 추천 상품에 라쿠텐 검증 직링크를 붙인다.

    스킨케어 `/recommend` 흐름은 resolve_product_platforms만 돌아, 라쿠텐 소스 상품이 아니면
    라쿠텐 버튼이 절대 안 붙던 문제를 보완한다. 라쿠텐 API는 ~1req/s로 레이트리밋(429)되므로
    상위 limit개, 라쿠텐 링크가 아직 없는 상품만 검증한다(못 찾으면 미출력).

    ⚠ 같은 상품(브랜드+상품명)이 평면 목록과 컬럼에 **다른 인스턴스**로 들어 있다. 예산을
    인스턴스 단위로 쓰면 앞쪽 평면 목록에서 다 소진되고 컬럼 카드엔 라쿠텐 버튼이 하나도
    안 붙는다(실측: JP 바디 17장 중 rakuten 9 — 전부 평면/집중케어, 세정·보습 컬럼 0).
    그래서 (브랜드, 상품명) 키로 조회 결과를 캐시해 같은 상품의 모든 인스턴스에 함께 붙이고,
    예산은 '실제 API 조회 횟수'로만 센다.
    """
    if not client.configured:
        return
    lookups = 0
    cache: dict[tuple[str, str], str] = {}
    for p in products:
        if (getattr(p, "platform_links", None) or {}).get("rakuten"):
            continue  # 이미 라쿠텐 직링크 있음
        if getattr(p, "source", "") in ("rakuten", "naver"):
            continue
        brand = getattr(p, "brand", "") or ""
        name = getattr(p, "name", "") or ""
        key = (brand.strip().lower(), name.strip().lower())
        if key in cache:
            if cache[key]:
                _attach_rakuten(p, cache[key])
            continue
        if lookups >= limit:
            continue
        lookups += 1
        url = _verified_rakuten_url(client, brand, name)
        cache[key] = url
        if url:
            _attach_rakuten(p, url)


def _prefer_linked_products(columns: list, minimum: int = 2) -> None:
    """컬럼마다 '구매 링크가 있는' 상품을 앞으로 보내고, 링크 없는 카드는 뒤로/드롭한다.

    사용자 원칙은 '직링크 있으면 버튼, 없으면 미출력'인데, 스킨케어 `/recommend` 흐름엔
    아이템매칭과 달리 링크 없는 카드를 걸러내는 단계가 없었다. 그래서 어느 플랫폼에도 없는
    서구 브랜드(Dermalogica·Paula's Choice 등)가 **버튼이 하나도 없는 죽은 카드**로 컬럼을
    차지했다(실측: JP 세럼 4장 중 3장이 링크 0개 — 사용자가 본 '보습쪽 직링크 안 붙음').

    컬럼이 통째로 비지 않도록 링크 있는 카드가 minimum 개 미만이면 링크 없는 카드도 남긴다
    (추천 근거 자체는 유효하고, 성분 안내 가치가 있다).
    """
    for col in columns:
        products = col.products
        linked = [p for p in products if (getattr(p, "platform_links", None) or {})]
        unlinked = [p for p in products if not (getattr(p, "platform_links", None) or {})]
        if len(linked) >= minimum:
            col.products = linked
        else:
            col.products = linked + unlinked[: max(0, minimum - len(linked))]


@router.post("/analyze-skin", response_model=AnalyzeSkinResponse)
async def analyze_skin(
    user_id: int | None = None,
    analysis_mode: str = Form(default="auto"),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    session_user: User | None = Depends(optional_user),
) -> AnalyzeSkinResponse:
    # 세션이 있으면 쿼리 파라미터보다 우선한다 — 남의 user_id 를 실어 보내도 자기 이력에만 쌓인다.
    user_id = session_user.id if session_user else user_id
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="An image file is required.")
    image_bytes = await image.read()
    if analysis_mode == "auto":
        analysis_mode = get_skin_image_router().route(image_bytes).analysis_mode
    if analysis_mode == "body":
        # 기존 6종 피부염 분류를 2단 선별(정상/양성/악성의심 + 케어그룹)로 대체.
        # 악성(피부암) 조기발견 경고가 추가되는 상위호환. 진단이 아니라 선별/안내.
        result = DermatologyAnalyzer().analyze(image_bytes)
        return AnalyzeSkinResponse(
            analysis_mode="body",
            body_conditions=result["conditions"],
            model_available=result["model_available"],
            summary=result["summary"],
            confidence_note=SCREENING_NOTE if result["model_available"] else "",
            tier1_label=result["tier1_label"],
            tier1_confidence=result["tier1_confidence"],
            urgent=result["urgent"],
        )
    if analysis_mode != "face":
        raise HTTPException(status_code=400, detail="analysis_mode must be 'auto', 'face', or 'body'.")

    scores, confidence_note = SkinAnalyzer().analyze(image_bytes)
    # ⚠ 원본 파일명은 저장하지 않는다(2026-08-03). 업로드 파일명에는 이름·날짜·기기·장소가
    #   들어가는 일이 흔한데(예: "2026-08-03 김OO 병원상담.jpg"), 이 값은 **어디서도 읽지
    #   않으면서** user_id 와 묶여 무기한 남아 있었다. 쓰는 곳이 없으니 안 남기는 게 맞다.
    #   확장자만 남겨 어떤 형식이 들어왔는지는 추적할 수 있게 한다.
    suffix = Path(image.filename or "").suffix.lower()[:8]
    analysis = SkinAnalysis(user_id=user_id, image_name=suffix or None, **scores.model_dump())
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return AnalyzeSkinResponse(
        analysis_id=analysis.id,
        analysis_mode="face",
        scores=scores,
        summary=summarize_scores(scores),
        confidence_note=confidence_note,
    )


@router.post("/analyze-personal-color", response_model=PersonalColorResponse)
async def analyze_personal_color(
    images: list[UploadFile] = File(...),
    region: str | None = Form(default=None),
) -> PersonalColorResponse:
    # 여러 장을 받으면 계절 확률·피부 지표를 평균해 여름쿨↔겨울쿨 흔들림을 줄인다(한 장도 허용).
    if not images:
        raise HTTPException(status_code=400, detail="An image file is required.")
    image_bytes: list[bytes] = []
    for image in images:
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="An image file is required.")
        image_bytes.append(await image.read())
    # 마켓 게이팅: kr/jp(아시아 얼굴)는 현행 색블렌드 유지, 글로벌/서구 마켓은 model 쪽으로 축소.
    # region 미지정(현행 프론트)이면 설정 기본값 1.0 → 동작 완전 보존(무회귀).
    color_scale = PersonalColorAnalyzer.resolve_blend_scale(region)
    try:
        return PersonalColorAnalyzer().analyze_many(image_bytes, color_scale=color_scale)
    except UnusablePhotoError as exc:
        # 조명 때문에 판정할 수 없는 경우. **일반 오류와 구분해서** 사용자가 읽을 안내를 그대로 준다 —
        # "Could not analyze this image" 로 뭉뚱그리면 사용자는 같은 사진을 다시 올린다.
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not analyze this image.") from exc


@router.get("/personal-color/profile", response_model=PersonalColorResponse)
def personal_color_profile(label: str) -> PersonalColorResponse:
    """이미 아는 퍼스널컬러(웹 계정에 저장된 8종 라벨)로 결과지를 만든다.

    사진 분석 결과와 같은 모양이라 프론트가 그대로 아이템매칭 검색어로 넘길 수 있다.
    아티스트에게 진단받은 사람에게 다시 찍으라고 하지 않기 위한 경로다.
    """
    result = declared_personal_color_result(label)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown personal color label: {label}")
    return result


@router.post("/analyze-face-shape", response_model=FaceShapeResponse)
async def analyze_face_shape(image: UploadFile = File(...)) -> FaceShapeResponse:
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="An image file is required.")
    image_bytes = await image.read()
    # mediapipe/cv2는 무거우므로 요청 시점에 지연 임포트한다.
    from app.services.face_shape_analyzer import analyze as analyze_face

    try:
        return FaceShapeResponse(**analyze_face(image_bytes))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not analyze this image.") from exc


NAIL_MAX_QUERY_NAILS = 3   # 크게 잡힌 것부터 — 엄지·검지가 보통 가장 선명하다


@router.post("/virtual-surgery/simulate", response_model=VirtualSurgeryResponse)
async def simulate_virtual_surgery(
    image: UploadFile = File(...),
    face_line: int = Form(default=42),
    jaw_balance: int = Form(default=28),
    nose_contour: int = Form(default=34),
    blemish_care: int = Form(default=56),
    # 1단계에서 고른 값. 콤마 구분 문자열로 받는다(multipart 라 배열보다 단순하고,
    # 값이 화면 문구 그대로라 서버가 사전에 없는 항목을 받아도 무시될 뿐 깨지지 않는다).
    # 순서가 곧 우선순위다 — 첫 항목이 1순위.
    concerns: str = Form(default=""),
    desired_moods: str = Form(default=""),
) -> VirtualSurgeryResponse:
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="An image file is required.")
    image_bytes = await image.read()
    from app.services.virtual_surgery_simulator import simulate

    def _csv(raw: str) -> list[str]:
        return [part.strip() for part in (raw or "").split(",") if part.strip()][:6]

    try:
        return VirtualSurgeryResponse(**simulate(
            image_bytes,
            face_line=max(0, min(100, face_line)),
            jaw_balance=max(0, min(100, jaw_balance)),
            nose_contour=max(0, min(100, nose_contour)),
            blemish_care=max(0, min(100, blemish_care)),
            concerns=_csv(concerns),
            desired_moods=_csv(desired_moods),
        ))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not simulate this image.") from exc


@router.post("/virtual-surgery/preview-cards", response_model=VirtualSurgeryPreviewCardsResponse)
async def preview_virtual_surgery_cards(
    image: UploadFile = File(...),
    # 변화 강도. 슬라이더 숫자(%)를 대신한다 — 의학적 의미가 없는 워프 강도가 '62%' 처럼
    # 결과지에 실리면 수술 수치로 읽힌다.
    intensity: str = Form(default="balanced"),
    # 1단계에서 고른 값(콤마 구분, 순서가 곧 우선순위). simulate 와 같은 형식이다.
    # 이게 없으면 4단계 카드가 1단계 선택과 무관한 고정 4장이 된다(2026-08-05 제보).
    concerns: str = Form(default=""),
    desired_moods: str = Form(default=""),
) -> VirtualSurgeryPreviewCardsResponse:
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="An image file is required.")
    image_bytes = await image.read()
    from app.services.virtual_surgery_simulator import preview_cards

    picked = [item.strip() for item in concerns.split(",") if item.strip()]
    moods = [item.strip() for item in desired_moods.split(",") if item.strip()]
    try:
        return VirtualSurgeryPreviewCardsResponse(
            **preview_cards(image_bytes, intensity=intensity, concerns=picked, desired_moods=moods)
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not build previews for this image.") from exc


@router.post("/virtual-surgery/retouch", response_model=VirtualSurgeryRetouchResponse)
async def retouch_virtual_surgery(
    image: UploadFile = File(...),
    # "x,y,r;x,y,r;…" (0~1 정규화). 사용자가 화면에서 고른 지점만 온다.
    points: str = Form(default=""),
) -> VirtualSurgeryRetouchResponse:
    """사용자가 고른 점·잡티만 지운다.

    자동 제거를 하지 않는 이유(2026-08-04 결정): 자동은 오탐/미탐 줄다리기가 끝나지 않는다.
    후보만 보여주고 사용자가 고르면, 오탐이 나와도 안 고르면 그만이라 정밀도 요구가 낮아진다.

    ⚠ 원본을 다시 받는다. 서버에 사진을 들고 있지 않기 때문이다(개인정보 미저장 원칙).
      왕복이 한 번 더 늘지만, 사용자가 '적용'을 누를 때만 일어난다.
    """
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="An image file is required.")
    image_bytes = await image.read()

    parsed: list[dict] = []
    for chunk in (points or "").split(";"):
        parts = [p for p in chunk.split(",") if p.strip()]
        if len(parts) < 2:
            continue
        try:
            parsed.append({
                "x": float(parts[0]),
                "y": float(parts[1]),
                "r": float(parts[2]) if len(parts) > 2 else 0.0,
            })
        except ValueError:
            continue

    from app.services.virtual_surgery_simulator import _load_rgb, _to_data_url, remove_blemishes

    try:
        rgb = _load_rgb(image_bytes)
        out = remove_blemishes(rgb, parsed)
        return VirtualSurgeryRetouchResponse(preview_image=_to_data_url(out), removed=len(parsed))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not retouch this image.") from exc


@router.post("/analyze-nail-design", response_model=AnalyzeNailDesignResponse)
async def analyze_nail_design(
    image: UploadFile = File(...),
    top_k: int = Form(default=5),
) -> AnalyzeNailDesignResponse:
    """손·발 사진 → 네일 검출 → 유사 디자인 검색 + 퍼스널컬러 시즌 적합도.

    상품 추천은 여기서 하지 않는다. `recommended_shades` 가 PROFILES 의 네일 색이름 그대로라
    프론트가 기존 item-match 라이브 검색에 그대로 넘길 수 있다(상품 파이프라인 중복 방지).
    """
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="An image file is required.")
    image_bytes = await image.read()

    # torch·ultralytics·cv2 는 무거우므로 요청 시점에 지연 임포트한다.
    import base64

    import cv2
    import numpy as np

    from app.services.nail_design_index import (
        detect_nails,
        dominant_color,
        feature_available,
        get_embedder,
        get_index,
    )
    from app.services.nail_palette import rank_seasons, season_nail_shades

    if not feature_available():
        # 모델·인덱스가 배포에 빠졌을 때 500 대신 '비활성'으로 응답한다(다른 AI 모듈과 동일 규약).
        return AnalyzeNailDesignResponse(
            feature_available=False, index_size=0,
            note="네일 디자인 인덱스 또는 모델이 배포에 포함되지 않았습니다.",
        )

    index = get_index()
    index.load()
    settings = get_settings()

    try:
        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("decode failed")
        nails = detect_nails(img)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not analyze this image.") from exc

    if not nails:
        return AnalyzeNailDesignResponse(
            feature_available=True, index_size=index.size,
            note="사진에서 네일을 찾지 못했습니다. 손이나 발이 잘 보이도록 다시 찍어 주세요.",
        )

    embedder = get_embedder()
    detected: list[DetectedNail] = []
    for i, ((x1, y1, x2, y2), conf) in enumerate(nails[:NAIL_MAX_QUERY_NAILS]):
        crop = img[max(y1, 0):y2, max(x1, 0):x2]
        if crop.size == 0:
            continue
        lab, hex_color = dominant_color(crop)
        vec = embedder([crop])[0]
        matches = index.search(vec, lab, top_k, settings.nail_retrieval_color_weight)

        out_matches = []
        for m in matches:
            thumb = None
            if m.thumbnail_path:
                raw = Path(m.thumbnail_path).read_bytes()
                thumb = "data:image/png;base64," + base64.b64encode(raw).decode()
            out_matches.append(NailDesignMatch(
                design_id=m.design_id, region=m.region, similarity=m.similarity,
                color_hex=m.color_hex, delta_e=m.delta_e, thumbnail=thumb,
            ))
        detected.append(DetectedNail(
            index=i, confidence=round(conf, 3), bbox=[int(x1), int(y1), int(x2), int(y2)],
            color_hex=hex_color, color_lab=lab, matches=out_matches,
        ))

    if not detected:
        return AnalyzeNailDesignResponse(
            feature_available=True, index_size=index.size,
            note="네일 영역이 너무 작아 분석하지 못했습니다.",
        )

    # 시즌 적합도는 가장 크게 잡힌 네일(=가장 선명한 색) 기준으로 낸다.
    primary = detected[0]
    season_fit = [
        NailSeasonFit(label=label, tone=tone, subtype=subtype, shade_name=fit.name,
                      shade_hex=fit.hex, delta_e=fit.delta_e, score=fit.score)
        for label, tone, subtype, fit in rank_seasons(tuple(primary.color_lab))
    ]
    best = season_fit[0]
    palette = season_nail_shades(best.tone, best.subtype)
    shades = [name for name, _hex in palette]

    return AnalyzeNailDesignResponse(
        feature_available=True,
        index_size=index.size,
        detected=detected,
        season_fit=season_fit,
        recommended_shades=shades,
        recommended_palette=[NailShade(name=name, hex=hex_value) for name, hex_value in palette],
        note=f"사진 속 컬러는 '{best.label}'에 가장 가깝습니다({best.shade_name}).",
    )


@router.post("/recommend", response_model=RecommendationResponse)
def recommend(
    payload: RecommendationRequest,
    request: Request,
    db: Session = Depends(get_db),
    session_user: User | None = Depends(optional_user),
) -> RecommendationResponse:
    # 세션이 있으면 추천 이력을 그 계정에 붙인다(요청 본문의 user_id 보다 우선).
    if session_user is not None:
        payload.user_id = session_user.id
    region = _resolve_region(payload.region, request, "kr")
    platform = normalize_platform(payload.platform)
    # 스킨케어 상품은 글로벌 카탈로그라 지역/플랫폼과 무관하게 피부적합도로 고른다("all").
    # 지역·플랫폼 구분은 아래 입점 리졸버(버튼)와 프론트 필터에서 처리한다.
    if payload.analysis_mode == "body":
        # 2단 모델이 판정한 질환 그룹에 '적합한 성분' 기준으로 추천/안내한다.
        # (약이 필요한 병·악성 의심은 제품 대신 상담/진료 안내)
        response = recommend_derma_care(
            db,
            payload.body_conditions,
            payload.survey,
            payload.user_id,
            None,
            "all",
            region,
        )
    else:
        try:
            scores = payload.scores or get_scores_from_analysis(db, payload.analysis_id or 0)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        response = recommend_products(
            db,
            scores,
            payload.survey,
            payload.analysis_id,
            payload.user_id,
            "all",
        )
    # KR 지역: 영문 카탈로그 상품을 네이버 한글 데이터(브랜드/상품명/URL/이미지)로 보강한다.
    # 국내몰 라이브 검색이 한글로 이뤄지므로, 보강 '후'(한글 정체성)에 입점 검증해야 잘 맞는다.
    # 평면 추천(products)과 카테고리 컬럼 상품(product_columns[].products)을 함께 보강한다 —
    # 안 그러면 컬럼 카드의 버튼/한글화/이미지가 부실해진다(서로 다른 ProductOut 인스턴스).
    column_products = [p for col in response.product_columns for p in col.products]
    enrichable = response.products + column_products
    if region == "kr":
        enrich_products_with_naver_kr(enrichable)
    # 퍼스널컬러 화면과 동일하게: 지역별 입점 리졸버로 플랫폼 버튼을 통일한다.
    # KR=네이버/Amazon.com/올리브영 국내몰, JP=라쿠텐/Amazon.co.jp/올리브영 글로벌.
    for product in enrichable:
        resolve_product_platforms(product, region)
    # JP 스킨케어: 라쿠텐 소스가 아니면 라쿠텐 버튼이 안 붙으므로, API로 브랜드 일치 실상품을
    # 검증해 직링크를 부착한다(미취급이면 버튼 없음 — 아이템매칭 남성 흐름과 동일 원칙).
    if region == "jp":
        # 컬럼 카드를 **먼저** 검증한다. 화면에 보이는 건 컬럼이고, 평면 목록은 대개 같은 상품의
        # 다른 인스턴스라 앞에 두면 한정된 조회 예산을 거기서 다 쓴다(컬럼 라쿠텐 버튼 0개 원인).
        _verify_rakuten_for_skincare(column_products + response.products, RakutenClient())
    # 올리브영 입점 검증: JP=글로벌 카탈로그 직링크(카탈로그 없을 때만 라이브 prune). KR=국내몰
    # NewMainSearchApi 라이브 검색으로 goodsNo 직링크 교체/미취급 버튼 제거(curl_cffi).
    if region == "jp" and not catalog_available():
        prune_global_oliveyoung(enrichable)
    elif region == "kr":
        prune_kr_oliveyoung(enrichable)
    # JP 바디: 사전 매칭된 라쿠텐 직링크를 붙인다(rakuten_body_links 캐시). 라이브 검색
    # (_verify_rakuten_for_skincare)은 초당 1요청 제한 탓에 상위 6개만 붙지만, 캐시는
    # enrich 단계에서 매칭해 둔 전부(≈133건)에 직링크를 준다 — API 재호출·레이트리밋 없음.
    if payload.analysis_mode == "body" and region == "jp":
        for product in enrichable:
            url = rakuten_link_for(getattr(product, "name", "") or "")
            if url:
                links = dict(getattr(product, "platform_links", None) or {})
                links["rakuten"] = url
                product.platform_links = links
                matched = list(getattr(product, "matched_platforms", None) or [])
                if "rakuten" not in matched:
                    matched.append("rakuten")
                product.matched_platforms = matched
    # 바디 상품은 리전 카탈로그(마츠키요 등)에서 왔는데, resolve_product_platforms 가 그
    # 원산지 링크까지 지우면 프론트 카드에 구매 버튼이 하나도 안 남는다(마츠키요 상품은
    # 라쿠텐·아마존JP 매칭이 안 되기 일쑤). 링크가 통째로 빈 바디 상품엔 원산지 링크를
    # 되살려, 카드가 최소한 '살 수 있는 곳' 하나는 갖게 한다.
    if payload.analysis_mode == "body":
        for product in enrichable:
            _backfill_native_body_link(product)
    # 링크(구매처)가 확정된 뒤, 컬럼에서 '살 수 있는 곳이 없는' 카드를 정리한다.
    _prefer_linked_products(response.product_columns)
    # 평면 상품만 선택 플랫폼으로 필터(루틴은 전 단계 유지 — 버튼은 프론트에서 필터).
    response.products = _filter_by_requested_platform(response.products, platform)
    # 네이버 보강이 서로 다른 상품의 표시명을 같은 국내몰 매칭명으로 재작성하면(라운드랩 독도
    # 클렌저 용량변형들 → 동일 표시명) 컬럼에 시각적 중복이 남는다(Bug A). 최종 표시명 기준으로
    # 컬럼·평면 목록을 한 번 더 dedup 한다(선택 시점 라인 dedup 뒤에 생긴 충돌 정리).
    def _dedup_by_display_name(items: list) -> list:
        seen: set[str] = set()
        out: list = []
        for p in items:
            key = (getattr(p, "name", "") or "").strip().lower()
            if key and key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out
    for col in response.product_columns:
        col.products = _dedup_by_display_name(col.products)
    response.products = _dedup_by_display_name(response.products)
    # 카드 이미지 보강(KR=아마존 카탈로그, JP=라쿠텐→아마존JP, 이미 있으면 유지).
    fill_missing_images(enrichable, region)
    return response


@router.post("/personal-color/item-match", response_model=PersonalColorItemMatchResponse)
def personal_color_item_match(
    payload: PersonalColorItemMatchRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> PersonalColorItemMatchResponse:
    keywords = [keyword.strip() for keyword in payload.keywords if keyword.strip()]
    region = _resolve_region(payload.region, request, "jp")
    platform = (payload.platform or "all").strip().lower()
    gender = (payload.gender or "female").strip().lower()
    db_products = recommend_personal_color_products(
        db,
        keywords,
        region=region,
        platform=platform,
        limit=8,
    )

    products = [
        RakutenProductOut(
            id=f"db-{item.id}",
            brand=item.brand,
            name=item.name,
            price=item.price,
            image_url=item.image_url,
            product_url=item.product_url or next(iter(item.platform_links.values()), ""),
            review_average=item.avg_rating,
            review_count=item.review_count,
            keyword=item.category,
            source="database",
            score=item.score,
            platform_links=item.platform_links,
            matched_platforms=item.matched_platforms,
        )
        for item in db_products
    ]

    # 즉답 모드: 라이브 검색·네트워크 검증을 모두 건너뛰고 로컬 후보만 돌려준다.
    # 아이템매칭은 웜 기준 KR ~7s / JP ~9s 인데, 그 대부분이 라이브 검색과 입점 검증이다.
    # 프론트는 이 즉답을 먼저 그리고 full 응답이 오면 교체한다(체감 대기 제거).
    instant = (payload.stage or "full").strip().lower() == "instant"

    # 플랫폼 탭은 검색 결과의 대부분이 '그 플랫폼 링크 없음'으로 걸러진다(KR all 36건 중
    # amazon_us 는 10건뿐, 블러셔·네일은 0건). 그래서 특정 플랫폼일 때는 **키워드당 조회 수만**
    # 넓혀 후보를 늘린다 — 키워드 개수(=API 요청 수)는 그대로라 라쿠텐 1req/s 스로틀 비용이
    # 늘지 않는다. 키워드를 늘리면 요청이 배로 늘어 응답이 다시 느려지므로 그 방향은 피한다.
    live_hits = max(payload.hits_per_keyword, 6)
    if platform != "all":
        live_hits = max(live_hits, 24)

    client = RakutenClient()
    # 라이브 검색은 '선택 플랫폼'과 무관하게 지역 기준으로 돈다(2026-07-29).
    # 카드의 구매 버튼은 교차 플랫폼이다 — 라쿠텐/네이버에서 찾은 상품에 카탈로그 매칭으로
    # 올리브영·아마존 직링크가 붙는다. 그래서 플랫폼 선택으로 소스 검색을 꺼버리면 "그
    # 플랫폼에서 살 수 있는 상품"까지 통째로 사라져 올리브영/아마존 탭이 상시 0건이 됐다
    # (KR all=10건 중 올영링크 6건인데 KR oliveyoung=0건이던 원인). 플랫폼 선택은 아래
    # _filter_by_requested_platform 이 '링크 유무'로만 거르게 한다.
    wants_rakuten = region == "jp"
    if wants_rakuten and client.configured and not instant:
        # 카테고리당 1키워드(≤5요청)로 라쿠텐 rate-limit 안에서 모든 컬럼을 확정적으로 채운다.
        # 단일 키워드라 후보가 얇아지지 않게 키워드당 조회 수를 넉넉히(≥6) 준다.
        rakuten_products = _rakuten_search_with_fallback(
            client,
            _interleave_by_category(keywords, gender, per_category=1),
            hits_per_keyword=live_hits,
            throttle=1.1,  # 라쿠텐 ~1req/s: 요청을 벌려 뒤쪽 컬럼(nail 등)이 429로 굶지 않게.
        )
        products.extend(
            RakutenProductOut(
                id=item.id,
                brand=item.brand,
                name=item.name,
                price=item.price,
                image_url=item.image_url,
                product_url=item.product_url,
                review_average=item.review_average,
                review_count=item.review_count,
                keyword=item.keyword,
                source="rakuten",
                score=personal_color_fit_score_for_text(
                    item.brand,
                    item.name,
                    item.keyword,
                    "",
                    keywords,
                    platform_score=8.0,
                    rating_score=min(7.0, (item.review_average or 0) * 1.2 + min(item.review_count or 0, 100) * 0.015),
                ),
                # 라쿠텐 실상품 + Amazon JP는 상품명 검색으로 대부분 조회되므로 교차 버튼 제공.
                # 마츠키요/올리브영은 입점 확인 수단이 없어(특히 일본 상품) 붙이지 않는다.
                platform_links={
                    "rakuten": item.product_url,
                },
                matched_platforms=["rakuten"],
            )
            for item in rakuten_products
        )

    naver_client = NaverClient()
    wants_naver = region == "kr"  # 위 wants_rakuten 과 같은 이유로 플랫폼 게이트를 뺀다.
    if wants_naver and naver_client.configured and not instant:
        naver_products = naver_client.search_many(
            _interleave_by_category(keywords, gender, per_category=1),
            hits_per_keyword=live_hits,
        )
        products.extend(
            RakutenProductOut(
                id=f"naver-{item.id}",
                brand=item.brand,
                name=item.name,
                price=item.price,
                image_url=item.image_url,
                product_url=item.product_url,
                review_average=item.review_average,
                review_count=item.review_count,
                keyword=item.keyword,
                source="naver",
                # 네이버는 리뷰 지표가 없어 색상 매칭(검색 자체가 색상어)으로 신뢰하고,
                # DB 스킨케어 누출(약 57점)보다 위에 오도록 기본 점수를 부여한다.
                score=personal_color_fit_score_for_text(
                    item.brand,
                    item.name,
                    item.keyword,
                    "",
                    keywords,
                    platform_score=8.0,
                    rating_score=4.0 if item.image_url else 0.0,
                ),
                # 네이버 실상품 + 아마존/올리브영은 상품명 검색으로 연결(모든 플랫폼에서 노출).
                # 올리브영 실입점 검증은 데이터 확보 후 별도 예외처리 예정.
                platform_links={
                    "naver": item.product_url,
                },
                matched_platforms=["naver"],
            )
            for item in naver_products
        )

    # JP 남성: 라쿠텐엔 한국 남성 브랜드가 안 떠서 올리브영 남성 상품을 글로벌몰 카탈로그에서
    # 직접 주입한다(올리브영 JP 남성 고객 확보). catalog_available일 때만.
    if region == "jp" and gender == "male" and catalog_available():
        _inject_male_global_products(products, region)

    # 같은 상품(브랜드+라인명)으로 흩어진 소스별 카드를 하나로 병합한다(product-centric).
    products = dedup_by_line(products)

    ranked = sorted(
        products,
        key=lambda item: (item.score or 0, item.review_count or 0, item.review_average or 0),
        reverse=True,
    )
    # 표시명 기준 2차 dedup. dedup_by_line 은 (브랜드, 라인) 키라 **같은 상품을 다른 상점이
    # 파는 경우**를 못 접는다 — 라쿠텐은 brand 자리에 점포명이 들어와서(‘세븐프로’ vs
    # ‘ホームセンターセブン’) 이름이 완전히 같은 카드가 립 컬럼에 두 장 뜨는 걸 사용자가 발견했다.
    # 정렬 뒤에 돌려 점수가 높은 카드를 남기고, 링크는 합쳐 구매처를 잃지 않게 한다.
    ranked = _dedup_by_display_name(ranked)

    # 재정렬(2026-07-27, 사용자 지시): 링크를 '먼저' 확정한 뒤 컬럼을 배분한다.
    # 예전엔 balance(컬럼배분)가 링크를 모른 채 상위 점수로 컬럼을 정했고, 그 뒤 resolve/
    # seed-filter가 살 수 없는(빈링크) 카드를 드롭해 컬럼이 비었다(JP eye/nail, KR lip).
    # 이제 후보 전체에 resolve(전부 로컬 — 카탈로그 조회·URL조립, 네트워크 없음)로 링크를 부여하고
    # '살 수 있는 곳이 없는' 카드를 먼저 걸러낸 뒤, 링크 있는 상품으로 컬럼을 채운다.
    for product in ranked:
        resolve_product_platforms(product, region)
    ranked = [p for p in ranked if (getattr(p, "platform_links", None) or {})]

    # 요청 플랫폼으로 '먼저' 좁힌 뒤 컬럼을 배분한다(2026-07-29). balance 뒤에 거르면
    # 10칸을 전체 후보로 채운 다음 그 플랫폼에 없는 카드가 통째로 빠져 컬럼이 비거나 얇아진다
    # (JP amazon 이 5건·nail 0건이던 원인). 링크 확정(resolve) 뒤라 여기서 걸러도 안전하다.
    # 주의: KR 은 뒤의 네이버 보강 후 재-resolve 에서 올영 링크가 더 붙을 수 있어, 그때 생길
    # 링크는 이 시점에 알 수 없다 — 그래도 '전부 0건'보다는 낫다. 최종 필터는 아래에 그대로 둔다.
    ranked = _filter_by_requested_platform(ranked, platform)

    # 컬럼 배분: 각 컬럼에 per_category개, 라쿠텐 라이브가 상위를 독식하지 않도록 비-라쿠텐
    # (직링크 DB/네이버/올리브영/아마존)을 먼저 채우고 라쿠텐으로 남은 칸을 메운다(_pick_diverse).
    #
    # 특정 플랫폼 탭에서는 **넉넉히 뽑는다**. 뒤의 입점 검증(prune)이 링크를 떼어내면 그 카드가
    # 통째로 빠지는데, 딱 10칸만 뽑아두면 메울 예비가 없어 컬럼이 빈다 — KR 올리브영이
    # 후보 36건(전 컬럼 보유)인데도 최종 4건·네일 0이던 원인이다. 검증 뒤 아래에서 10칸으로
    # 다시 배분한다. 'all' 은 링크가 떨어져 나갈 일이 적어 종전대로 10칸만 뽑는다(비용 유지).
    overselect = platform != "all" and not instant
    products = _balance_item_categories(
        ranked,
        limit=24 if overselect else 10,
        per_category=5 if overselect else 2,
        gender=gender,
    )

    # 이하 네트워크 검증/보강은 배분된 top-N 에만 건다(라쿠텐 429 등 레이트리밋 보호).
    # 즉답 모드에서는 전부 건너뛴다 — 여기가 응답시간의 대부분이고, 뒤이어 오는 full 응답이
    # 같은 카드를 검증된 링크·이미지로 교체한다.
    # KR: 네이버 한글 데이터로 보강 후 링크를 다시 확정한다(영문 DB명 → 한글 정체성 → 올영 goodsNo 직링크).
    if region == "kr" and not instant:
        enrich_products_with_naver_kr(products)
        for product in products:
            resolve_product_platforms(product, region)
    # JP 남성 OY 주입 상품: 라쿠텐 API로 검증해 실제 있으면 직링크 부착(미취급이면 버튼 없음).
    if region == "jp" and gender == "male" and not instant:
        _verify_rakuten_for_global(products, client)
    # 올리브영 입점 검증: JP=글로벌 카탈로그(없을 때만 라이브 prune), KR=국내몰 라이브 검색.
    if region == "jp" and not instant:
        if not catalog_available():
            prune_global_oliveyoung(products)
    elif region == "kr" and not instant:
        prune_kr_oliveyoung(products)

    # 요청 플랫폼 필터 후, prune 으로 링크가 통째로 비게 된 카드는 최종 드롭(살 수 있는 곳 없음).
    products = _filter_by_requested_platform(products, platform)
    products = [p for p in products if (getattr(p, "platform_links", None) or {})]
    # ⚠ 표시명 dedup 을 **여기서 한 번 더** 돌려야 한다. 위 enrich_products_with_naver_kr 가
    # 상품명을 네이버 매칭명으로 재작성하기 때문에, 서로 다르던 두 카드가 이 단계에서 같은
    # 이름이 될 수 있다(실측: '삐아 레디 투 웨어 다우니 치크' 2장). 정렬 전 dedup 만으로는
    # 못 잡는다 — 이름을 바꾸는 보강 뒤에는 반드시 재-dedup.
    products = _dedup_by_display_name(products)

    # 플랫폼 탭에서 **비어 있는 컬럼만** 카탈로그 상품으로 메운다.
    # ⚠ 반드시 입점 검증(prune) '뒤'에서 판정해야 한다. 검증 전에는 네이버 후보가 낙관적으로
    #   올영 링크를 달고 있어 컬럼이 안 빈 것처럼 보이는데, 그 후보들이 검증에서 전멸하면
    #   결국 0이 된다(실측: 검증 전 판정으로 옮겼더니 네일이 다시 0). 주입 상품은 카탈로그
    #   출신이라 검증을 다시 거칠 필요가 없다.
    # 즉답 모드에서도 주입은 한다 — 카탈로그 조회는 전부 로컬(캐시)이라 빠르고, 안 하면
    # 즉답이 DB 폴백(영문명·색상 미매칭)만 남아 오히려 엉뚱한 카드가 깜빡인다(실측 8건 전부 DB).
    # ⚠ 주입은 **플랫폼 탭과 무관하게** 돈다(2026-08-03 수정). 예전엔 올리브영/아마존 탭에서만
    #   돌아서, '모든 플랫폼'·'네이버' 에서는 네일 컬럼이 그냥 비어 있었다(사용자 리포트).
    #   원래 KR 네일 후보를 만들던 네이버 색상검색이 2026-07-31 종료돼 후보 소스가 사라졌는데,
    #   채워줄 주입까지 탭에 막혀 있어 **이중 공백**이었다. 카탈로그엔 네일이 96건 있었다.
    #   플랫폼 탭은 '어디서 살 수 있나'를 고르는 필터지, 컬럼을 비우는 장치가 아니다.
    if gender != "male":
        normalized_platform = normalize_platform(platform)
        thin = _thin_item_categories(products, gender)
        if thin:
            before = len(products)
            if normalized_platform in {"amazon_us", "amazon_jp"}:
                _inject_amazon_catalog(products, keywords, region, thin)
            elif region == "kr":
                # 지역별 카탈로그가 다르다: KR=국내몰(goodsNo), JP=글로벌몰(prdtNo).
                _inject_kr_oliveyoung_catalog(products, keywords, thin)
            elif catalog_available():
                _inject_jp_oliveyoung_catalog(products, keywords, thin)
            # 주입은 append 라 뒤쪽이 새 상품이다. 주입 상품은 자기 카탈로그 링크 하나만 들고
            # 오므로, 나머지 플랫폼 링크를 붙인 뒤 **선택한 탭 기준으로 한 번 걸러**야 한다
            # (본 목록의 _filter_by_requested_platform 은 이 지점보다 앞에서 이미 끝났다).
            injected = products[before:]
            if injected:
                del products[before:]
                for item in injected:
                    _attach_links_keeping_direct(item, region)
                products.extend(_filter_by_requested_platform(injected, platform))
        products.sort(key=lambda item: (item.score or 0, item.review_count or 0), reverse=True)

    # 넉넉히 뽑았으면 검증에서 살아남은 것들로 컬럼을 다시 균등 배분한다(위 overselect 참고).
    # 즉답 모드도 주입으로 개수가 늘어나므로(실측 17건) 같이 다시 배분한다.
    if overselect or instant:
        products = _balance_item_categories(products, limit=10, per_category=2, gender=gender)
    # 이미지가 없거나 죽은(또는 올리브영) 이미지는 지역별 소스(KR=아마존 카탈로그, JP=라쿠텐)로 교체.
    if not instant:
        fill_missing_images(products, region)

    # 컬럼 판정을 응답에 실어 보낸다(프론트가 같은 규칙을 다시 구현하지 않게 — 위 schema 주석 참고).
    # 이미지 보강이 상품명을 바꾸는 일은 없으니 마지막에 한 번만 계산하면 된다.
    for product in products:
        product.column = _item_match_category(product, gender)

    # 분류 못 한 상품은 **보내지 않는다.**
    # 프론트에는 column 이 없을 때 쓰는 폴백 규칙이 있는데(구 응답 호환), 그게 키워드만 보고
    # 분류한다. 그래서 백엔드가 '화장품이 아니다'로 판정한 것이 되살아난다 —
    # 실측(2026-08-04): 라쿠텐이 '로즈 핑크 립' 검색에 캔들홀더(キャンドルホルダー…燭台)를
    # 물어왔고, 키워드에 '립'이 있어 **립 컬럼에 캔들홀더 카드가 떴다.**
    # 판정 주체는 백엔드 하나여야 하므로 여기서 끊는다.
    products = [p for p in products if p.column]

    if products:
        configured = True
        message = "Matched products loaded."
    elif wants_rakuten and not client.configured:
        configured = False
        message = "Rakuten API keys are not configured."
    elif wants_naver and not naver_client.configured:
        configured = False
        message = "Naver API keys are not configured."
    elif wants_rakuten and client.last_error:
        configured = True
        message = f"Rakuten API error: {client.last_error}"
    elif wants_naver and naver_client.last_error:
        configured = True
        message = f"Naver API error: {naver_client.last_error}"
    else:
        configured = True
        message = "No products matched this region/platform."

    return PersonalColorItemMatchResponse(
        provider="recommender",
        configured=configured,
        products=products,
        message=message,
        partial=instant,
    )


@router.post("/style/makeup-preview", response_model=MakeupPreviewResponse)
def style_makeup_preview(payload: MakeupPreviewRequest) -> MakeupPreviewResponse:
    # mediapipe/cv2는 무거우므로 요청 시점에 지연 임포트한다.
    from app.services.makeup_applier import apply_mood_to_model

    result = apply_mood_to_model(payload.mood)
    return MakeupPreviewResponse(mood=payload.mood, **result)


@router.post("/style/makeup-preview/photo", response_model=MakeupPreviewResponse)
async def style_makeup_preview_photo(
    mood: str = Form(...),
    gender: str = Form(default="female"),
    image: UploadFile = File(...),
) -> MakeupPreviewResponse:
    """번들 모델이 아니라 **이용자 본인 사진**에 무드를 적용한다.

    성별로 올리는 항목이 다르다(item-match 성별 분기와 같은 원칙 — 강도만 줄이는 게 아니라
    항목을 교체한다): 여성=립·볼·아이, 남성=눈썹·립밤. 남성에게 블러셔/아이섀도는 올리지 않는다.
    """
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="An image file is required.")
    # mediapipe/cv2는 무거우므로 요청 시점에 지연 임포트한다.
    from app.services.makeup_applier import apply_mood

    result = apply_mood(await image.read(), mood, gender=gender)
    return MakeupPreviewResponse(mood=mood, **result)


@router.get("/style/mood-thumbnails", response_model=MoodThumbnailsResponse)
def style_mood_thumbnails() -> MoodThumbnailsResponse:
    # 무드별 '모델에 메이크업 적용' 카드 썸네일. 결과는 캐시되어 첫 호출만 느리다.
    from app.services.makeup_applier import all_mood_thumbnails

    return MoodThumbnailsResponse(thumbnails=all_mood_thumbnails())


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    session_user: User | None = Depends(optional_user),
) -> ChatResponse:
    user_id = session_user.id if session_user else payload.user_id
    return answer_skin_question(db, payload.message, user_id, payload.context)


@router.get("/products", response_model=list[ProductOut])
def products(db: Session = Depends(get_db)) -> list[ProductOut]:
    rows = db.query(Product).options(
        selectinload(Product.brand),
        selectinload(Product.ingredients).selectinload(ProductIngredient.ingredient),
    ).all()
    return [
        ProductOut(
            id=product.id,
            brand=product.brand.name,
            name=product.name,
            category=product.category,
            price=product.price,
            description=product.description,
            ingredients=[item.ingredient.name for item in product.ingredients],
            product_url=product.product_url,
            platform_links=build_platform_links(product),
            matched_platforms=matched_platforms(product),
            image_url=product.image_url,
        )
        for product in rows
    ]


@router.get("/history", response_model=list[HistoryOut])
def history(
    user_id: int | None = None,
    db: Session = Depends(get_db),
    session_user: User | None = Depends(optional_user),
) -> list[HistoryOut]:
    # 세션이 있으면 남의 user_id 를 넣어도 자기 이력만 보인다.
    if session_user is not None:
        user_id = session_user.id
    query = db.query(RecommendationHistory)
    if user_id is not None:
        query = query.filter(RecommendationHistory.user_id == user_id)
    rows = query.order_by(RecommendationHistory.created_at.desc()).limit(20).all()
    return [
        HistoryOut(
            id=row.id,
            recommended_ingredients=json.loads(row.recommended_ingredients),
            recommended_products=json.loads(row.recommended_products),
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.delete("/me/data", response_model=MyDataDeletionResult)
def delete_my_data(
    db: Session = Depends(get_db),
    session_user: User | None = Depends(optional_user),
) -> MyDataDeletionResult:
    """내 분석·설문·추천이력·상담기록을 지운다.

    설계안 §11 이 요구하는 '사용자가 언제든 삭제 요청할 수 있게 한다' 를 **수단**으로 만든 것.
    보관 기간 자동 만료는 정책이 정해져야 하므로 여기서 정하지 않는다(설계 검토 §7).

    ⚠ **세션 사용자 것만** 지운다. user_id 를 파라미터로 받지 않는 이유는 그 순간 남의
    데이터를 지울 수 있는 API 가 되기 때문이다(같은 이유로 /history 도 세션을 우선한다).
    ⚠ 계정(users) 자체는 지우지 않는다. 웹에서 넘어온 연동 정보라 여기서 지우면 로그인
    상태와 어긋난다 — 계정 탈퇴는 웹 소관이다.
    """
    if session_user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    uid = session_user.id
    deleted = {
        "skin_analyses": db.query(SkinAnalysis).filter(SkinAnalysis.user_id == uid).delete(synchronize_session=False),
        "surveys": db.query(Survey).filter(Survey.user_id == uid).delete(synchronize_session=False),
        "recommendation_histories": db.query(RecommendationHistory).filter(
            RecommendationHistory.user_id == uid).delete(synchronize_session=False),
        "chat_histories": db.query(ChatHistory).filter(ChatHistory.user_id == uid).delete(synchronize_session=False),
    }
    db.commit()
    return MyDataDeletionResult(deleted={k: int(v or 0) for k, v in deleted.items()})


@router.get("/admin/statistics")
def admin_statistics(db: Session = Depends(get_db)) -> dict:
    total_users = db.query(func.count(User.id)).scalar() or 0
    total_analyses = db.query(func.count(SkinAnalysis.id)).scalar() or 0
    total_recommendations = db.query(func.count(RecommendationHistory.id)).scalar() or 0
    avg_scores = db.query(
        func.avg(SkinAnalysis.acne),
        func.avg(SkinAnalysis.pore),
        func.avg(SkinAnalysis.wrinkle),
        func.avg(SkinAnalysis.redness),
        func.avg(SkinAnalysis.pigmentation),
        func.avg(SkinAnalysis.oiliness),
    ).one()
    return {
        "users": total_users,
        "analyses": total_analyses,
        "recommendations": total_recommendations,
        "average_scores": {
            "acne": round(avg_scores[0] or 0, 1),
            "pore": round(avg_scores[1] or 0, 1),
            "wrinkle": round(avg_scores[2] or 0, 1),
            "redness": round(avg_scores[3] or 0, 1),
            "pigmentation": round(avg_scores[4] or 0, 1),
            "oiliness": round(avg_scores[5] or 0, 1),
        },
    }
