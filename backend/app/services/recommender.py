import json

from sqlalchemy.orm import Session, selectinload

from app.models import Ingredient, Product, ProductIngredient, RecommendationHistory, SkinAnalysis, Survey
from app.schemas.api import IngredientOut, ProductOut, RecommendationResponse, SkinScores, SurveyInput


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
    "파운데이션 밀림": ["oiliness"], "들뜸": ["redness"],
    "지속력": ["oiliness"], "커버력": ["redness"],
    "눈가": ["wrinkle"], "입술": ["redness"], "목·데콜테": ["wrinkle", "pigmentation"],
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
) -> RecommendationResponse:
    ingredients = infer_ingredients(db, scores, survey)
    ingredient_targets = {target for ingredient in ingredients for target in ingredient.targets.split(",")}

    products = db.query(Product).options(
        selectinload(Product.brand),
        selectinload(Product.ingredients).selectinload(ProductIngredient.ingredient),
    ).all()
    scored: list[tuple[float, Product]] = []
    for product in products:
        product_targets = {
            target
            for product_ingredient in product.ingredients
            for target in product_ingredient.ingredient.targets.split(",")
        }
        ingredient_match = len(ingredient_targets.intersection(product_targets)) * 18
        skin_type_match = 12 if survey.skin_type in product.skin_types or "all" in product.skin_types else 0
        concern_match = sum(scores.model_dump().get(target, 0) for target in product_targets) / max(1, len(product_targets)) * 0.35
        scored.append((round(min(100.0, ingredient_match + skin_type_match + concern_match), 1), product))

    top_products = sorted(scored, key=lambda item: (item[0], item[1].avg_rating), reverse=True)[:5]
    ingredient_names = [ingredient.name for ingredient in ingredients]
    product_names = [product.name for _, product in top_products]

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
                image_url=product.image_url,
                avg_rating=product.avg_rating or None,
                review_count=product.review_count or None,
            )
            for score, product in top_products
        ],
        explanation=build_explanation(scores, survey, ingredient_names, product_names),
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
