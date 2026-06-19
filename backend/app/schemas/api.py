from datetime import datetime

from pydantic import BaseModel, Field


class SurveyInput(BaseModel):
    skin_type: str = Field(default="combination")
    concerns: list[str] = Field(default_factory=list)
    sensitivity: int = Field(default=2, ge=1, le=5)
    routine_level: str = Field(default="basic")


class SkinScores(BaseModel):
    acne: float
    pore: float
    wrinkle: float
    redness: float
    pigmentation: float
    oiliness: float


class AnalyzeSkinResponse(BaseModel):
    analysis_id: int
    scores: SkinScores
    summary: str


class RecommendationRequest(BaseModel):
    analysis_id: int | None = None
    scores: SkinScores | None = None
    survey: SurveyInput
    user_id: int | None = None


class IngredientOut(BaseModel):
    id: int
    name: str
    benefit: str
    targets: list[str]


class ProductOut(BaseModel):
    id: int
    brand: str
    name: str
    category: str
    price: int
    score: float | None = None
    description: str
    ingredients: list[str]


class RecommendationResponse(BaseModel):
    history_id: int
    ingredients: list[IngredientOut]
    products: list[ProductOut]
    explanation: str


class ChatRequest(BaseModel):
    message: str
    user_id: int | None = None
    context: dict | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list)


class HistoryOut(BaseModel):
    id: int
    recommended_ingredients: list[str]
    recommended_products: list[str]
    created_at: datetime

