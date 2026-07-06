import json
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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
from app.services.body_skin_analyzer import BodySkinAnalyzer
from app.services.image_router import get_skin_image_router
from app.services.naver_client import NaverClient
from app.services.naver_kr_enricher import enrich_products_with_naver_kr
from app.services.oliveyoung_availability import prune_global_oliveyoung, unavailable_on_global_ids
from app.services.personal_color_analyzer import PersonalColorAnalyzer
from app.services.platform_resolver import dedup_by_line, resolve_product_platforms
from app.services.product_image_provider import fill_missing_images
from app.services.rakuten_client import RakutenClient
from app.services.recommender import (
    build_platform_links,
    get_scores_from_analysis,
    matched_platforms,
    personal_color_fit_score_for_text,
    recommend_personal_color_products,
    recommend_products,
)
from app.services.skin_analyzer import SkinAnalyzer, summarize_scores

router = APIRouter(prefix="/api")


# 아이템 매칭 카테고리 분류(프론트 itemMatchColumnFor와 동일 규칙). 한/영/일 토큰 모두 인식.
_ITEM_CATEGORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("blush", re.compile(r"blush|blusher|cheek|チーク|블러셔|치크|볼터치", re.I)),
    ("eye", re.compile(r"eye|eyeshadow|shadow|palette|mascara|liner|kajal|アイシャドウ|アイライナー|マスカラ|아이|섀도|쉐도", re.I)),
    ("base", re.compile(r"base|foundation|cushion|concealer|primer|powder|shading|ファンデーション|コンシーラー|パウダー|파운데이션|쿠션|베이스", re.I)),
    ("lip", re.compile(r"lip|lipstick|tint|rouge|gloss|balm|リップ|ルージュ|ティント|립|틴트", re.I)),
]


def _item_match_category(product) -> str | None:
    # 카테고리 키워드 필드를 우선 신뢰하고, 없으면 상품명까지 포함해 판정한다.
    primary = (product.keyword or "").lower()
    for category, pattern in _ITEM_CATEGORY_PATTERNS:
        if pattern.search(primary):
            return category
    text = f"{product.keyword or ''} {product.name or ''}".lower()
    for category, pattern in _ITEM_CATEGORY_PATTERNS:
        if pattern.search(text):
            return category
    return None


def _balance_item_categories(items: list, limit: int = 8, per_category: int = 2) -> list:
    """점수순 상품을 립/블러셔/아이/베이스 4개 카테고리에 고르게 배분한다.

    '모든 플랫폼'에서 라쿠텐(립/아이)이 상위를 독식해 베이스/블러셔 컬럼이 비는 문제를
    막는다. 각 카테고리 상위 per_category개를 먼저 확보하고 남은 칸은 점수순으로 채운다.
    """
    buckets: dict[str, list] = {"lip": [], "blush": [], "eye": [], "base": []}
    for item in items:  # items는 점수 내림차순 정렬 상태
        category = _item_match_category(item)
        if category:
            buckets[category].append(item)

    selected: list = []
    seen: set[int] = set()
    for category in ("lip", "blush", "eye", "base"):
        for item in buckets[category][:per_category]:
            selected.append(item)
            seen.add(id(item))
    for item in items:
        if len(selected) >= limit:
            break
        if id(item) not in seen:
            selected.append(item)
            seen.add(id(item))
    return selected[:limit]


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
        conditions, model_available, summary = BodySkinAnalyzer().analyze(image_bytes)
        return AnalyzeSkinResponse(
            analysis_mode="body",
            body_conditions=conditions,
            model_available=model_available,
            summary=summary,
        )
    if analysis_mode != "face":
        raise HTTPException(status_code=400, detail="analysis_mode must be 'auto', 'face', or 'body'.")

    scores = SkinAnalyzer().analyze(image_bytes)
    analysis = SkinAnalysis(user_id=user_id, image_name=image.filename, **scores.model_dump())
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return AnalyzeSkinResponse(
        analysis_id=analysis.id,
        analysis_mode="face",
        scores=scores,
        summary=summarize_scores(scores),
    )


@router.post("/analyze-personal-color", response_model=PersonalColorResponse)
async def analyze_personal_color(images: list[UploadFile] = File(...)) -> PersonalColorResponse:
    # 여러 장을 받으면 계절 확률·피부 지표를 평균해 여름쿨↔겨울쿨 흔들림을 줄인다(한 장도 허용).
    if not images:
        raise HTTPException(status_code=400, detail="An image file is required.")
    image_bytes: list[bytes] = []
    for image in images:
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="An image file is required.")
        image_bytes.append(await image.read())
    try:
        return PersonalColorAnalyzer().analyze_many(image_bytes)
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
def recommend(payload: RecommendationRequest, db: Session = Depends(get_db)) -> RecommendationResponse:
    region = (payload.region or "kr").strip().lower()
    # 스킨케어 상품은 글로벌 카탈로그라 지역/플랫폼과 무관하게 피부적합도로 고른다("all").
    # 지역·플랫폼 구분은 아래 입점 리졸버(버튼)와 프론트 필터에서 처리한다.
    if payload.analysis_mode == "body":
        response = recommend_products(
            db,
            payload.scores or SkinScores(
                acne=0, pore=0, wrinkle=0, redness=0, pigmentation=0, oiliness=0
            ),
            payload.survey,
            None,
            payload.user_id,
            "all",
            analysis_mode="body",
            body_conditions=payload.body_conditions,
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
    # KR 국내몰은 Cloudflare로 직접 검증이 불가하다. 올리브영은 제조사 상품을 글로벌몰·국내몰
    # 양쪽에 함께 올리는 경향이 있어, 글로벌몰 조회를 KR 입점 대리 신호로 쓴다. 반드시 네이버
    # 한글 보강 '전'(영문 정체성)에 판정해야 영문 글로벌몰과 매칭된다.
    oliveyoung_hidden_ids = (
        unavailable_on_global_ids(response.products) if region == "kr" else set()
    )
    # KR 지역: 영문 카탈로그 상품을 네이버 한글 데이터(브랜드/상품명/URL/이미지)로 보강한다.
    # 퍼스널컬러 카드처럼 한글로 표시·검색되게 해 한국 플랫폼(올리브영 등) 조회 성공률을 높인다.
    if region == "kr":
        enrich_products_with_naver_kr(response.products)
    # 퍼스널컬러 화면과 동일하게: 지역별 입점 리졸버로 플랫폼 버튼을 통일한다.
    # KR=네이버/Amazon.com/올리브영 국내몰, JP=라쿠텐/Amazon.co.jp/올리브영 글로벌.
    for product in response.products:
        resolve_product_platforms(
            product, region, hide_oliveyoung=id(product) in oliveyoung_hidden_ids
        )
    # 올리브영 글로벌몰(JP 지역): 실제 입점 검증 — 0건이면 버튼 제거, 있으면 검증된 검색어로 교체.
    # 국내몰(KR)은 Cloudflare 403으로 검증 불가라 개선 쿼리로 항상 표시한다(prune 대상 아님).
    if region == "jp":
        prune_global_oliveyoung(response.products)
    # 카드 이미지 보강(KR=네이버, JP=라쿠텐 검색 이미지, 이미 있으면 유지).
    fill_missing_images(response.products, region)
    return response


@router.post("/personal-color/item-match", response_model=PersonalColorItemMatchResponse)
def personal_color_item_match(
    payload: PersonalColorItemMatchRequest,
    db: Session = Depends(get_db),
) -> PersonalColorItemMatchResponse:
    keywords = [keyword.strip() for keyword in payload.keywords if keyword.strip()]
    region = (payload.region or "jp").strip().lower()
    platform = (payload.platform or "all").strip().lower()
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

    # 같은 상품(브랜드+라인명)으로 흩어진 소스별 카드를 하나로 병합한다(product-centric).
    products = dedup_by_line(products)

    ranked = sorted(
        products,
        key=lambda item: (item.score or 0, item.review_count or 0, item.review_average or 0),
        reverse=True,
    )
    # 립/블러셔/아이/베이스 4개 컬럼에 고르게 배분한다. 이렇게 하면 '모든 플랫폼'에서도
    # 베이스/블러셔 컬럼이 비지 않고, 각 컬럼은 카테고리 내 점수순으로 채워진다.
    products = _balance_item_categories(ranked, limit=8, per_category=2)

    # 입점 리졸버: 최종 노출 상품마다 플랫폼 전반(라쿠텐/네이버 매칭 + 마츠키요 인덱스 +
    # 아마존/올리브영 라인 검색링크)을 채운다. 네트워크 호출은 top N에만 한정한다.
    for product in products:
        resolve_product_platforms(product, region)
    # 올리브영 글로벌몰(JP): 실제 입점 검증 — 조회 0건인 상품은 올리브영 버튼을 숨긴다.
    if region == "jp":
        prune_global_oliveyoung(products)

    # 이미지가 없는 상품은 지역별 실시간 검색(KR=네이버, JP=라쿠텐)으로 대표 이미지를 보강한다.
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
