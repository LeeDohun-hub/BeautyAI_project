from datetime import datetime

from pydantic import BaseModel, Field


class SurveyInput(BaseModel):
    gender: str = Field(default="female")          # "female" | "male"
    age_group: str = Field(default="20s")          # "10s" | "20s" | "30s" | "40s" | "50s"
    skin_type: str = Field(default="combination")
    concerns: list[str] = Field(default_factory=list)          # 피부 고민 (공통)
    makeup_concerns: list[str] = Field(default_factory=list)   # 메이크업 고민 (여성)
    area_concerns: list[str] = Field(default_factory=list)     # 부위별 케어 (여성)
    male_extras: list[str] = Field(default_factory=list)       # 추가 고민 (남성)
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
    platform: str = Field(default="all")
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
    product_url: str | None = None
    platform_links: dict[str, str] = Field(default_factory=dict)
    matched_platforms: list[str] = Field(default_factory=list)
    image_url: str | None = None
    avg_rating: float | None = None
    review_count: int | None = None


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

