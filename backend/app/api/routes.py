import json

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
from app.services.personal_color_analyzer import PersonalColorAnalyzer
from app.services.rakuten_client import RakutenClient
from app.services.recommender import (
    build_platform_links,
    get_scores_from_analysis,
    matched_platforms,
    recommend_personal_color_products,
    recommend_products,
)
from app.services.skin_analyzer import SkinAnalyzer, summarize_scores

router = APIRouter(prefix="/api")


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
async def analyze_personal_color(image: UploadFile = File(...)) -> PersonalColorResponse:
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="An image file is required.")
    image_bytes = await image.read()
    try:
        return PersonalColorAnalyzer().analyze(image_bytes)
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
    if payload.analysis_mode == "body":
        return recommend_products(
            db,
            payload.scores or SkinScores(
                acne=0, pore=0, wrinkle=0, redness=0, pigmentation=0, oiliness=0
            ),
            payload.survey,
            None,
            payload.user_id,
            payload.platform,
            analysis_mode="body",
            body_conditions=payload.body_conditions,
        )
    try:
        scores = payload.scores or get_scores_from_analysis(db, payload.analysis_id or 0)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return recommend_products(
        db,
        scores,
        payload.survey,
        payload.analysis_id,
        payload.user_id,
        payload.platform,
    )


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
                score=round(min(99.0, 40.0 + (item.review_average or 0) * 8 + min(item.review_count or 0, 100) * 0.08), 1),
                platform_links={"rakuten": item.product_url},
                matched_platforms=["rakuten"],
            )
            for item in rakuten_products
        )

    products = sorted(
        products,
        key=lambda item: (item.score or 0, item.review_count or 0, item.review_average or 0),
        reverse=True,
    )[:8]

    configured = True if products or not wants_rakuten else client.configured
    if products:
        message = "Matched products loaded."
    elif wants_rakuten and not client.configured:
        message = "Rakuten API keys are not configured."
    elif wants_rakuten and client.last_error:
        message = f"Rakuten API error: {client.last_error}"
    else:
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
