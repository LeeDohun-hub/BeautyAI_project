import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models import Product, ProductIngredient, RecommendationHistory, SkinAnalysis, User
from app.schemas.api import (
    AnalyzeSkinResponse,
    ChatRequest,
    ChatResponse,
    HistoryOut,
    ProductOut,
    RecommendationRequest,
    RecommendationResponse,
)
from app.services.chatbot import answer_skin_question
from app.services.recommender import build_platform_links, get_scores_from_analysis, matched_platforms, recommend_products
from app.services.skin_analyzer import SkinAnalyzer, summarize_scores

router = APIRouter(prefix="/api")


@router.post("/analyze-skin", response_model=AnalyzeSkinResponse)
async def analyze_skin(
    user_id: int | None = None,
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> AnalyzeSkinResponse:
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="An image file is required.")
    scores = SkinAnalyzer().analyze(await image.read())
    analysis = SkinAnalysis(user_id=user_id, image_name=image.filename, **scores.model_dump())
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return AnalyzeSkinResponse(analysis_id=analysis.id, scores=scores, summary=summarize_scores(scores))


@router.post("/recommend", response_model=RecommendationResponse)
def recommend(payload: RecommendationRequest, db: Session = Depends(get_db)) -> RecommendationResponse:
    try:
        scores = payload.scores or get_scores_from_analysis(db, payload.analysis_id or 0)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return recommend_products(db, scores, payload.survey, payload.analysis_id, payload.user_id, payload.platform)


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
