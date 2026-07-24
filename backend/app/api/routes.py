import json
import re
from types import SimpleNamespace
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models import Product, ProductIngredient, RecommendationHistory, SkinAnalysis, User
from app.schemas.api import (
    AnalyzeSkinResponse,
    ChatRequest,
    ChatResponse,
    FaceShapeResponse,
    HistoryOut,
    MakeupPreviewRequest,
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
)
from app.services.chatbot import answer_skin_question
from app.services.dermatology_analyzer import DermatologyAnalyzer, SCREENING_NOTE
from app.services.image_router import get_skin_image_router
from app.services.naver_client import NaverClient
from app.services.naver_kr_enricher import enrich_products_with_naver_kr
from app.services.oliveyoung_availability import prune_global_oliveyoung
from app.services.oliveyoung_catalog import catalog_available, male_catalog_items
from app.services.oliveyoung_kr_search import prune_kr_oliveyoung
from app.services.personal_color_analyzer import PersonalColorAnalyzer
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

router = APIRouter(prefix="/api")


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
    ("nail", re.compile(r"nail|pedi|polish|lacquer|manicure|ネイル|ペディ|マニキュア|네일|페디|매니큐어|젤네일", re.I)),
    ("blush", re.compile(r"blush|blusher|cheek|チーク|블러셔|치크|볼터치", re.I)),
    ("eye", re.compile(r"eye|eyeshadow|shadow|palette|mascara|liner|kajal|アイシャドウ|アイライナー|マスカラ|아이|섀도|쉐도", re.I)),
    ("base", re.compile(r"base|foundation|cushion|concealer|primer|powder|shading|ファンデーション|コンシーラー|パウダー|파운데이션|쿠션|베이스", re.I)),
    ("lip", re.compile(r"lip|lipstick|tint|rouge|gloss|balm|リップ|ルージュ|ティント|립|틴트", re.I)),
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
    r"|ソックス|靴下|スニーカー|サンダル|スリッパ|ブーツ|クッションカバー|座布団|まくら|枕|マット|椅子|ソファ|寝具",
    re.I,
)


def _item_match_category(product, gender: str = "female") -> str | None:
    text = f"{product.keyword or ''} {product.name or ''}"
    if _NON_COSMETIC_RE.search(text):
        return None  # 신발/양말 등 잡화 → 화장품 컬럼에서 제외
    patterns = _item_category_patterns(gender)
    # 카테고리 키워드 필드를 우선 신뢰하고, 없으면 상품명까지 포함해 판정한다.
    primary = (product.keyword or "").lower()
    for category, pattern in patterns:
        if pattern.search(primary):
            return category
    text = text.lower()
    for category, pattern in patterns:
        if pattern.search(text):
            return category
    return None


_ITEM_CATEGORIES_FEMALE = ("lip", "blush", "eye", "base", "nail")
_ITEM_CATEGORIES_MALE = ("base", "brow", "concealer", "lipbalm")


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
        for item in buckets[category][:per_category]:
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
    상위 limit개, 라쿠텐 링크가 아직 없는 상품만 검증한다(못 찾으면 미출력)."""
    if not client.configured:
        return
    processed = 0
    for p in products:
        if processed >= limit:
            break
        if (getattr(p, "platform_links", None) or {}).get("rakuten"):
            continue  # 이미 라쿠텐 직링크 있음
        if getattr(p, "source", "") in ("rakuten", "naver"):
            continue
        processed += 1
        url = _verified_rakuten_url(client, getattr(p, "brand", "") or "", getattr(p, "name", "") or "")
        if url:
            _attach_rakuten(p, url)


@router.post("/analyze-skin", response_model=AnalyzeSkinResponse)
async def analyze_skin(
    user_id: int | None = None,
    analysis_mode: str = Form(default="auto"),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> AnalyzeSkinResponse:
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
    analysis = SkinAnalysis(user_id=user_id, image_name=image.filename, **scores.model_dump())
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
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not analyze this image.") from exc


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


@router.post("/recommend", response_model=RecommendationResponse)
def recommend(
    payload: RecommendationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RecommendationResponse:
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
        _verify_rakuten_for_skincare(enrichable, RakutenClient())
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
    # 평면 상품만 선택 플랫폼으로 필터(루틴은 전 단계 유지 — 버튼은 프론트에서 필터).
    response.products = _filter_by_requested_platform(response.products, platform)
    # 카드 이미지 보강(KR=네이버, JP=라쿠텐 검색 이미지, 이미 있으면 유지).
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

    client = RakutenClient()
    wants_rakuten = region == "jp" and platform in {"all", "rakuten"}
    if wants_rakuten and client.configured:
        rakuten_products = client.search_many(keywords, hits_per_keyword=payload.hits_per_keyword)
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
    wants_naver = region == "kr" and platform in {"all", "naver"}
    if wants_naver and naver_client.configured:
        naver_products = naver_client.search_many(keywords, hits_per_keyword=payload.hits_per_keyword)
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
    # 립/블러셔/아이/베이스 4개 컬럼에 고르게 배분한다. 이렇게 하면 '모든 플랫폼'에서도
    # 베이스/블러셔 컬럼이 비지 않고, 각 컬럼은 카테고리 내 점수순으로 채워진다.
    products = _balance_item_categories(ranked, limit=10, per_category=2, gender=gender)

    # KR: 국내몰 라이브 검색은 한글로 이뤄지므로, 입점 검증 '전에' 네이버 한글 데이터로 보강한다.
    # 영문 DB 상품명('TIRTIR Mask Fit Red Cushion')은 국내몰 검색 0건이지만, 한글 정체성
    # ('티르티르 마스크 핏 레드 쿠션')이면 매칭돼 올리브영 goodsNo 직링크가 붙는다(사용자 지적).
    if region == "kr":
        enrich_products_with_naver_kr(products)

    # 입점 리졸버: 최종 노출 상품마다 플랫폼 전반(라쿠텐/네이버 매칭 + 마츠키요 인덱스 +
    # 아마존/올리브영 라인 검색링크)을 채운다. 네트워크 호출은 top N에만 한정한다.
    for product in products:
        resolve_product_platforms(product, region)
    # JP 남성 OY 주입 상품: 라쿠텐 API로 검증해 실제 있으면 직링크 부착(미취급이면 버튼 없음).
    # 아마존은 검증 API가 없어 붙이지 않는다(올리브영 직링크 기준으로 통일 — 오탐 방지).
    if region == "jp" and gender == "male":
        _verify_rakuten_for_global(products, client)
    # 올리브영 입점 검증: JP=글로벌 카탈로그(없을 때만 라이브 prune), KR=국내몰 라이브 검색으로
    # goodsNo 직링크 교체/미취급 버튼 제거.
    if region == "jp":
        if not catalog_available():
            prune_global_oliveyoung(products)
    elif region == "kr":
        prune_kr_oliveyoung(products)

    # 이미지가 없는 상품은 지역별 실시간 검색(KR=네이버, JP=라쿠텐)으로 대표 이미지를 보강한다.
    products = _filter_by_requested_platform(products, platform)
    fill_missing_images(products, region)

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
def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    return answer_skin_question(db, payload.message, payload.user_id, payload.context)


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
def history(user_id: int | None = None, db: Session = Depends(get_db)) -> list[HistoryOut]:
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
