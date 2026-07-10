from datetime import datetime

from pydantic import BaseModel, Field


class SurveyInput(BaseModel):
    gender: str = Field(default="female")          # "female" | "male"
    age: str | None = None
    age_group: str = Field(default="20s")          # "10s" | "20s" | "30s" | "40s" | "50s"
    race_identity: str | None = None
    privacy_consent: bool = False
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


class BodyConditionScore(BaseModel):
    condition: str
    label: str
    probability: float


class AnalyzeSkinResponse(BaseModel):
    analysis_id: int | None = None
    analysis_mode: str = "face"
    scores: SkinScores | None = None
    body_conditions: list[BodyConditionScore] = Field(default_factory=list)
    model_available: bool = True
    summary: str
    # 점수 신뢰도 안내(참고용 추정치·홍조 색상측정·얼굴 미검출 등). 프론트에서 노출.
    confidence_note: str = ""
    # body(피부질환 선별) 결과: Tier1 게이트 라벨·확신도·악성의심 플래그.
    tier1_label: str = ""            # normal | benign_concern | urgent_referral
    tier1_confidence: float = 0.0
    urgent: bool = False


class PersonalColorMakeup(BaseModel):
    lip: list[str]
    blush: list[str]
    eye: list[str]
    base: list[str]
    nail: list[str] = Field(default_factory=list)


class PersonalColorResponse(BaseModel):
    season: str
    tone: str
    subtype: str
    label: str
    alternate_season: str | None = None
    alternate_label: str | None = None
    decision_note: str | None = None
    confidence: float
    skin_summary: str
    palette: list[str]
    makeup: PersonalColorMakeup
    advice: list[str]
    metrics: dict[str, float] = Field(default_factory=dict)


class RakutenProductOut(BaseModel):
    id: str
    brand: str
    name: str
    price: int
    image_url: str | None = None
    product_url: str
    review_average: float | None = None
    review_count: int | None = None
    keyword: str
    source: str = "rakuten"
    score: float | None = None
    platform_links: dict[str, str] = Field(default_factory=dict)
    matched_platforms: list[str] = Field(default_factory=list)


class PersonalColorItemMatchRequest(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    hits_per_keyword: int = Field(default=4, ge=1, le=8)
    region: str = Field(default="jp")
    platform: str = Field(default="all")
    gender: str = Field(default="female")          # "female" | "male" — 카테고리/밸런싱 분기


class PersonalColorItemMatchResponse(BaseModel):
    provider: str = "rakuten"
    configured: bool
    products: list[RakutenProductOut]
    message: str


class MakeupPreviewRequest(BaseModel):
    mood: str


class MakeupPreviewResponse(BaseModel):
    mood: str
    applied: bool
    message: str
    original_image: str
    image: str


class MoodThumbnailsResponse(BaseModel):
    thumbnails: dict[str, str]


class FaceRatioOut(BaseModel):
    label: str
    width: int


class FaceShapeResponse(BaseModel):
    detected: bool
    shape: str
    tags: list[str]
    summary: str
    ratios: list[FaceRatioOut]
    blusher_tip: str
    shading_tip: str
    metrics: dict[str, object] = Field(default_factory=dict)


class RecommendationRequest(BaseModel):
    analysis_id: int | None = None
    scores: SkinScores | None = None
    analysis_mode: str = Field(default="face")
    body_conditions: list[BodyConditionScore] = Field(default_factory=list)
    survey: SurveyInput
    region: str = Field(default="kr")
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
    reason_tags: list[str] = Field(default_factory=list)
    evidence_note: str | None = None
    # 상품 출처. KR 지역에서 네이버 한글 데이터로 보강되면 "naver"가 되어, 입점 리졸버가
    # 네이버 버튼을 실제 상품 URL로 연결한다(그 외에는 검색 링크).
    source: str = ""


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

