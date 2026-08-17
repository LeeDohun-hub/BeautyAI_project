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


class ChangeRegion(BaseModel):
    """시뮬레이션으로 바뀐 자리(0~1 정규화). 화면이 그 위에 표시를 얹는다."""
    x: float
    y: float
    w: float
    h: float
    strength: float = 0.0


class SkincareSimulationResponse(BaseModel):
    """케어를 이어갔을 때의 예상 모습.

    applied=False 면 화면은 이 영역을 감춘다 — 원본을 '개선 결과'라고 내보내면 안 된다.
    changed 는 실제로 손댄 항목이라, 화면이 '무엇이 달라졌는지'를 말할 수 있다.
    """
    applied: bool = False
    before: str | None = None
    after: str | None = None
    changed: list[str] = Field(default_factory=list)
    regions: list[ChangeRegion] = Field(default_factory=list)
    message: str = ""


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
    # 일본어판. 조각을 조건에 따라 이어 붙여 만들기 때문에(조합 8가지) 완성형을 프론트 사전으로
    # 옮길 수 없다 — 서버가 두 벌을 만든다. 바디 선별(SCREENING_NOTE)처럼 **고정 문장**인
    # 경로는 빈 문자열이고, 그때는 프론트가 사전으로 옮긴다.
    confidence_note_ja: str = ""
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
    # 일본어판 문장. 서버가 조립하는 문장이라 프론트의 정적 사전으로는 번역할 수 없어
    # 여기서 같이 만들어 내려준다(조합이 수십 가지라 사전에 키로 넣을 수 없다).
    # ⚠ 타입명은 `{label}` / `{alt}` 자리표시자로 남긴다 — 한국어→일본어 타입명 사전이
    #   프론트에 이미 있고, 서버에 같은 표를 또 두면 두 곳이 어긋난다.
    skin_summary_ja: str | None = None
    decision_note_ja: str | None = None
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
    # 이 상품이 들어갈 아이템매칭 컬럼(lip|blush|eye|base|nail|brow|concealer|lipbalm).
    # 백엔드가 **컬럼 배분에 쓴 그 판정**을 그대로 실어 보낸다. 예전엔 프론트가 같은 규칙을
    # TS 로 다시 구현했는데, 한쪽만 고치면 배분(백엔드)과 표시(프론트)가 어긋나 '배분은 됐는데
    # 다른 컬럼에 뜨거나 아예 안 뜨는' 컬럼 빔이 생겼다. 단일 출처로 통일한다.
    column: str | None = None


class PersonalColorItemMatchRequest(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    hits_per_keyword: int = Field(default=4, ge=1, le=8)
    region: str = Field(default="jp")
    platform: str = Field(default="all")
    gender: str = Field(default="female")          # "female" | "male" — 카테고리/밸런싱 분기
    # "instant" = 라이브 검색·네트워크 검증을 건너뛰고 로컬(DB·큐레이션 카탈로그)만으로 즉답한다.
    # 프론트가 먼저 이걸 띄우고, 이어서 "full" 결과로 교체해 체감 대기를 없앤다.
    stage: str = Field(default="full")             # "full" | "instant"


class PersonalColorItemMatchResponse(BaseModel):
    provider: str = "rakuten"
    configured: bool
    products: list[RakutenProductOut]
    message: str
    # 이 응답이 즉답(로컬 전용)인지. True 면 프론트는 뒤이어 오는 full 응답으로 교체한다.
    partial: bool = False


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


class VirtualSurgeryRecommendation(BaseModel):
    title: str
    category: str
    score: int
    summary: str
    # 사용자가 1단계에서 고른 부위에 해당하는 추천인지. 점수는 사진 측정값이라 건드리지 않고
    # 이 플래그와 정렬로만 사용자의 선택을 반영한다(고른 것만으로 근거가 세지면 안 된다).
    selected: bool = False


class ConsultationTier(BaseModel):
    """상담 후보 4분류 중 한 단계(설계안 §9).

    순서가 곧 메시지다 — 메이크업 → 피부과·쁘띠 → 성형외과 → 수술.
    "사용자가 바로 수술로 향하지 않도록" 가벼운 것부터 보여 준다.
    """

    key: str
    label: str
    items: list[str] = Field(default_factory=list)


class ConsultationPlan(BaseModel):
    """카드별 상담 후보·비용 티어·회복 범위(설계안 §7·§8·§9).

    ⚠ 비용은 **금액이 아니라 티어**다('낮음'/'중간~높음'). 설계안 §8 이 그렇게 정했고,
    실제 금액은 병원·국가·재료·마취·개인 상태에 따라 달라져 숫자로 쓸 수 없다.
    ⚠ 시술은 **후보**다. '필요하다'가 아니라 '상담에서 이야기해 볼 수 있는 것'이다.
    """

    tiers: list[ConsultationTier] = Field(default_factory=list)
    tier_note: str = ""
    cost_tier: str = ""
    cost_note: str = ""
    recovery: str = ""
    difficulty: str = ""
    caution: str = ""
    candidate_note: str = ""


class GoalEffect(BaseModel):
    """미리보기에서 실제로 바뀐 것 한 줄. 렌더에 쓴 값에서 계산한다."""

    label: str
    detail: str


class VirtualSurgeryPreviewCard(BaseModel):
    id: str
    title: str
    summary: str
    preview_image: str
    consultation: ConsultationPlan | None = None
    # 아래 둘은 '내가 고른 목표' 카드에만 채워진다.
    goals: list[str] = Field(default_factory=list)
    effects: list[GoalEffect] = Field(default_factory=list)


class BlemishPoint(BaseModel):
    """점·잡티 후보 한 곳.

    좌표는 이미지 크기에 대한 **0~1 비율**이다. 프론트가 이미지를 어떤 크기로 그리든
    그대로 얹을 수 있어야 하기 때문 — 픽셀 좌표로 주면 화면 크기마다 어긋난다.
    """

    x: float
    y: float
    r: float = 0.0


class PhotoQualityIssue(BaseModel):
    code: str
    message: str


class PhotoQuality(BaseModel):
    """사진 품질 점검 결과.

    ⚠ 결과를 **막지 않는다**. 문제가 있어도 분석은 그대로 주고 '정확도가 떨어질 수 있다'만
    알린다 — 게이트가 결과를 안 주면 사용자는 이유를 모른 채 이탈한다.
    """

    ok: bool = True
    issues: list[PhotoQualityIssue] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)


class VirtualSurgeryPreviewCardsResponse(BaseModel):
    """카드별 '내 얼굴 적용' 미리보기. 카드가 일러스트였을 때는 고르고 나서야 결과를 봤다."""

    detected: bool
    message: str
    original_image: str
    # 1단계에서 고른 목표를 그대로 적용한 카드. 고른 게 없으면 None.
    goal_card: VirtualSurgeryPreviewCard | None = None
    cards: list[VirtualSurgeryPreviewCard] = Field(default_factory=list)
    photo_quality: PhotoQuality | None = None


class MedicalReferral(BaseModel):
    """미용 추천보다 **먼저** 나가야 하는 안내. 얼굴 사진에 질환 소견이 보일 때 채워진다.

    미용 목적으로 올린 사진이라도, 진료가 필요한 소견이 보이면 그쪽을 먼저 알리는 게 맞다.
    진단이 아니라 선별이며, 미용 추천을 막지는 않는다(사용자가 판단할 정보를 더할 뿐).
    """

    urgent: bool = False
    label: str = ""
    confidence: float = 0.0
    message: str = ""


class VirtualSurgeryResponse(BaseModel):
    detected: bool
    message: str
    original_image: str
    preview_image: str
    face_shape: FaceShapeResponse | None = None
    recommendations: list[VirtualSurgeryRecommendation] = Field(default_factory=list)
    metrics: dict[str, object] = Field(default_factory=dict)
    disclaimer: str
    referral: MedicalReferral | None = None
    photo_quality: PhotoQuality | None = None
    # 상담에서 물어볼 질문(설계안 §16). 시술 추천이 아니라 **질문 목록**이라,
    # 의료광고 회신 전에도 넣을 수 있다(무엇을 하라고 말하지 않는다).
    consultation_questions: list[str] = Field(default_factory=list)
    # 점·잡티 **후보 위치**(0~1 정규화). 자동으로 지우지 않는다 — 사용자가 고른 것만 지운다.
    blemish_points: list[BlemishPoint] = Field(default_factory=list)
    # 미리보기에서 **실제로 바뀐 자리**(0~1 정규화). 결과 이미지만으로는 어디가 달라졌는지
    # 알아보기 어렵다는 지적(2026-08-14)에 따라 화면이 표시를 얹을 수 있게 좌표로 내려준다.
    change_regions: list[ChangeRegion] = Field(default_factory=list)


class VirtualSurgeryRetouchResponse(BaseModel):
    preview_image: str
    removed: int = 0


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
    # 일본어판. 수치·성분명이 끼는 조립형 문장이라 프론트 사전으로 못 옮긴다 —
    # 퍼스널컬러의 skin_summary_ja 와 같은 방식으로 서버가 두 벌을 만들어 보낸다.
    # 얼굴·바디·소아·더모 네 경로 모두 채운다(2026-08-07). None 이면 프론트가 한국어
    # 원문으로 폴백하는데, 그건 새 경로가 추가됐을 때의 안전망이지 정상 상태가 아니다.
    explanation_ja: str | None = None
    # 성분 근거 문단. 예전엔 explanation 뒤에 그대로 이어 붙여서 요약이 400자 넘는 한 덩어리가
    # 됐고, 웹·모바일 모두 읽히지 않았다(제보 2026-08-10). 요약과 근거는 읽는 목적이 다르므로
    # (요약=지금 뭘 사면 되나 / 근거=왜 그런가) 필드를 나눠 프론트가 접어둘 수 있게 한다.
    evidence: str | None = None
    evidence_ja: str | None = None
    # 카테고리별 추천 상품 컬럼(클렌저/토너/세럼/보습/선크림). face 모드에서만 채워진다.
    product_columns: list[ProductColumn] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str
    user_id: int | None = None
    context: dict | None = None
    # 답변 언어. 상담 화면은 일본어 모드에도 열려 있는데 모든 답변 경로가 한국어였다
    # (LLM 프롬프트가 한국어를 명시했고 폴백 지식베이스도 한국어뿐). 프론트가 화면 언어를
    # 그대로 보낸다. 없으면 Accept-Language 로 추정하고, 그것도 없으면 한국어.
    lang: str | None = None


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


class NailShade(BaseModel):
    """추천 네일 색조. 프론트가 스와치 표시와 '발색 미리보기'에 hex 를 그대로 쓴다."""

    name: str
    hex: str


class AnalyzeNailDesignResponse(BaseModel):
    feature_available: bool          # 모델·인덱스가 없으면 False(에러 대신 비활성 응답)
    index_size: int
    detected: list[DetectedNail] = Field(default_factory=list)
    # 가장 크게 잡힌 네일 기준. 프론트가 시즌 배지·상품 검색어로 쓴다.
    season_fit: list[NailSeasonFit] = Field(default_factory=list)
    # PROFILES 의 네일 색이름 그대로라 item-match 라이브 검색 키워드로 바로 넘길 수 있다.
    recommended_shades: list[str] = Field(default_factory=list)
    # 위와 같은 색조에 hex 를 붙인 것(스와치·미리보기용). 이름만으로는 색을 칠할 수 없다.
    recommended_palette: list[NailShade] = Field(default_factory=list)
    note: str = ""



class AuthExchangeRequest(BaseModel):
    """BeautyWEB 이 발급한 1회용 핸드오프 티켓."""

    ticket: str


class AuthUser(BaseModel):
    """AI 세션이 들고 있는 사용자. profile 값은 웹 마이페이지에서 넘어온 것이다."""

    id: int
    name: str
    role: str = "customer"
    web_member_id: int | None = None
    login_id: str | None = None
    gender: str | None = None
    age_group: str | None = None
    skin_type: str | None = None
    personal_color: str | None = None


class AuthSessionResponse(BaseModel):
    token: str
    expires_in: int                  # 초
    user: AuthUser


class AuthConfigResponse(BaseModel):
    """프론트 게이트가 쓰는 값. 로그인이 필요한지, 어디로 보낼지."""

    require_login: bool
    web_login_url: str
    # 웹 세션을 직접 조회할 API 주소(`/v1/api` 까지). 프론트가 부팅 때 여기에
    # `/account/token` 을 물어 "웹에 로그인돼 있나"를 판단한다. Settings 참조.
    web_api_base_url: str = ""
    # 일본어 화면에서 비포/애프터를 나란히 보여도 되는가.
    # False 면 프론트가 변형본만 보여준다(일본 医療広告ガイドライン 대응 스위치).
    # ⚠ **서버가 정한다.** 사용자 설정이 아니라 규제 대응이므로 클라이언트가 못 바꾼다.
    jp_before_after: bool = True


class CartHandoffItem(BaseModel):
    """결과지에 담은 상품 한 건. BeautyWEB 이 자기 카탈로그와 맞춰볼 수 있는 값만 담는다."""

    name: str
    brand: str = ""
    # 매칭 1순위. BeautyWEB items.productUrl 과 같은 방식으로 만들어진다
    # (올리브영 prdtNo/goodsNo, 아마존 /dp/ASIN 등).
    url: str = ""
    image_url: str = ""
    price: int = 0
    source: str = ""
    external_id: str = ""


class CartHandoffRequest(BaseModel):
    # 결과지 상한(5개)보다 넉넉하게. 그 이상은 QR 한 장에 담을 흐름이 아니다.
    items: list[CartHandoffItem] = Field(default_factory=list, max_length=10)


class CartHandoffResponse(BaseModel):
    code: str
    # QR 에 그대로 넣을 주소(`<web_cart_url>?ai=<code>`).
    url: str
    expires_in: int                  # 초
    item_count: int


class CartHandoffResolveRequest(BaseModel):
    code: str


class CartHandoffResolveResponse(BaseModel):
    web_member_id: int
    items: list[CartHandoffItem]


class MyDataDeletionResult(BaseModel):
    """내 데이터 삭제 결과. 테이블별로 몇 건을 지웠는지 돌려준다.

    사용자에게 '무엇이 지워졌는지' 를 보여줄 수 있어야 삭제 요청이 신뢰를 얻는다.
    """

    deleted: dict[str, int] = Field(default_factory=dict)
