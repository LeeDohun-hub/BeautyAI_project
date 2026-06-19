import json

from sqlalchemy.orm import Session, selectinload

from app.models import Ingredient, Product, ProductIngredient, RecommendationHistory, SkinAnalysis, Survey
from app.schemas.api import IngredientOut, ProductOut, RecommendationResponse, SkinScores, SurveyInput


TARGET_LABELS = {
    "acne": "Acne",
    "pore": "Pore",
    "wrinkle": "Wrinkle",
    "redness": "Redness",
    "pigmentation": "Pigmentation",
    "oiliness": "Oiliness",
}


def infer_ingredients(db: Session, scores: SkinScores, survey: SurveyInput) -> list[Ingredient]:
    score_map = scores.model_dump()
    priorities = {name for name, score in score_map.items() if score >= 45}
    priorities.update(concern.lower() for concern in survey.concerns)
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

    top_products = sorted(scored, key=lambda item: item[0], reverse=True)[:5]
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
            )
            for score, product in top_products
        ],
        explanation=build_explanation(scores, survey, ingredient_names, product_names),
    )


def build_explanation(scores: SkinScores, survey: SurveyInput, ingredients: list[str], products: list[str]) -> str:
    score_map = scores.model_dump()
    top_scores = sorted(score_map.items(), key=lambda item: item[1], reverse=True)[:3]
    priorities = ", ".join(f"{TARGET_LABELS[name]} {value:.0f}" for name, value in top_scores)
    return (
        f"Your strongest signals are {priorities}. For {survey.skin_type} skin, "
        f"I prioritized {', '.join(ingredients[:3])}. The top products are {', '.join(products[:3])}."
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
