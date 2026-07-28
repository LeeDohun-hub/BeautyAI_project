from datetime import datetime

from pydantic import BaseModel, Field


class SurveyInput(BaseModel):
    gender: str = Field(default="female")          # "female" | "male"
    age: str | None = None
    # "baby"(0~2) | "child"(3~9) | "10s" | "20s" | "30s" | "40s" | "50s"
    # baby/child 는 바디 추천에서 안내+소아안전 큐레이션 경로로 분기한다(pediatric_care).
    age_group: str = Field(default="20s")
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


class ProductColumn(BaseModel):
    key: str                        # cleanser|toner|serum|moisturizer|sunscreen
    label: str                      # 클렌저/토너/세럼/보습/선크림
    reason: str = ""                # 컬럼 설명(주로 세럼=고민 기반)
    products: list[ProductOut] = Field(default_factory=list)   # 이 카테고리 추천 상품(여러 개)


class RecommendationResponse(BaseModel):
    history_id: int
    ingredients: list[IngredientOut]
    products: list[ProductOut]
    explanation: str
    # 카테고리별 추천 상품 컬럼(클렌저/토너/세럼/보습/선크림). face 모드에서만 채워진다.
    product_columns: list[ProductColumn] = Field(default_factory=list)


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


class NailDesignMatch(BaseModel):
    """인덱스에서 찾은 유사 디자인 한 건."""

    design_id: str
    region: str                      # "foot" | "hand"
    similarity: float                # 하이브리드 점수(코사인 − λ·ΔE/100)
    color_hex: str
    delta_e: float                   # 질의 색과의 색차(CIE76)
    thumbnail: str | None = None     # data URI(64px). 썸네일이 없으면 None


class NailSeasonFit(BaseModel):
    """이 색이 각 퍼스널컬러 시즌에 얼마나 맞는지."""

    label: str                       # "겨울 쿨 딥" 등
    tone: str
    subtype: str
    shade_name: str                  # 그 시즌에서 가장 가까운 네일 색조 이름
    shade_hex: str
    delta_e: float
    score: float                     # 0~100


class DetectedNail(BaseModel):
    index: int
    confidence: float
    bbox: list[int]                  # [x1, y1, x2, y2]
    color_hex: str
    color_lab: list[float]
    matches: list[NailDesignMatch] = Field(default_factory=list)


class AnalyzeNailDesignResponse(BaseModel):
    feature_available: bool          # 모델·인덱스가 없으면 False(에러 대신 비활성 응답)
    index_size: int
    detected: list[DetectedNail] = Field(default_factory=list)
    # 가장 크게 잡힌 네일 기준. 프론트가 시즌 배지·상품 검색어로 쓴다.
    season_fit: list[NailSeasonFit] = Field(default_factory=list)
    # PROFILES 의 네일 색이름 그대로라 item-match 라이브 검색 키워드로 바로 넘길 수 있다.
    recommended_shades: list[str] = Field(default_factory=list)
    note: str = ""

