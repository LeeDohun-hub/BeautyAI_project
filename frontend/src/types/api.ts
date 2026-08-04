export type SkinScores = {
  acne: number;
  pore: number;
  wrinkle: number;
  redness: number;
  pigmentation: number;
  oiliness: number;
};

/** BeautyWEB 계정에서 넘어온 사용자. profile 값이 있으면 설문을 미리 채운다. */
export type AuthUser = {
  id: number;
  name: string;
  role: string;
  web_member_id?: number | null;
  login_id?: string | null;
  gender?: string | null;
  age_group?: string | null;
  skin_type?: string | null;
  // 8종 라벨(spring_bright … winter_deep). 있으면 사진 없이 결과지를 만들 수 있다.
  personal_color?: string | null;
};

export type AuthSessionResponse = {
  token: string;
  expires_in: number;
  user: AuthUser;
};

export type AuthConfigResponse = {
  require_login: boolean;
  web_login_url: string;
  /**
   * 일본어 화면에서 비포/애프터를 나란히 보여도 되는가(일본 医療広告ガイドライン 대응).
   * **서버가 정한다** — 규제 대응이므로 클라이언트 설정이 아니다.
   * 구 백엔드는 이 값을 안 보내므로 optional. undefined 면 현행(나란히) 유지.
   */
  jp_before_after?: boolean;
};

/** 결과지 QR → 웹 장바구니로 넘길 상품 한 건. url 이 매칭 1순위 키다. */
export type CartHandoffItem = {
  name: string;
  brand?: string;
  url?: string;
  image_url?: string;
  price?: number;
  source?: string;
  external_id?: string;
};

export type CartHandoffResponse = {
  code: string;
  /** QR 에 그대로 넣을 주소(`<웹 장바구니>?ai=<code>`). */
  url: string;
  expires_in: number;
  item_count: number;
};

export type AnalysisMode = 'auto' | 'face' | 'body';

export type BodyConditionScore = {
  condition: string;
  label: string;
  probability: number;
};

export type SurveyInput = {
  gender: string;          // "female" | "male"
  age?: string;
  age_group: string;       // "baby" | "child" | "10s" | "20s" | "30s" | "40s" | "50s"
  race_identity?: string;
  privacy_consent?: boolean;
  skin_type: string;
  concerns: string[];
  makeup_concerns: string[];
  area_concerns: string[];
  male_extras: string[];
  sensitivity: number;
  routine_level: string;
};

export type AnalyzeSkinResponse = {
  analysis_id?: number | null;
  analysis_mode: AnalysisMode;
  scores?: SkinScores | null;
  body_conditions: BodyConditionScore[];
  model_available: boolean;
  summary: string;
  confidence_note?: string;
  tier1_label?: string;
  tier1_confidence?: number;
  urgent?: boolean;
};

export type PersonalColorMakeup = {
  lip: string[];
  blush: string[];
  eye: string[];
  base: string[];
  nail: string[];
};

export type PersonalColorResponse = {
  season: string;
  tone: string;
  subtype: string;
  label: string;
  alternate_season?: string | null;
  alternate_label?: string | null;
  decision_note?: string | null;
  confidence: number;
  skin_summary: string;
  palette: string[];
  makeup: PersonalColorMakeup;
  advice: string[];
  metrics: Record<string, number>;
};

export type RakutenProduct = {
  id: string;
  brand: string;
  name: string;
  price: number;
  image_url?: string | null;
  product_url: string;
  review_average?: number | null;
  review_count?: number | null;
  keyword: string;
  source?: string;
  score?: number | null;
  platform_links?: Record<string, string>;
  matched_platforms?: string[];
  // 백엔드가 정한 아이템매칭 컬럼(lip|blush|eye|base|nail|brow|concealer|lipbalm).
  // 컬럼 배분과 표시가 같은 판정을 쓰도록 백엔드에서 내려준다(itemMatchColumnFor 주석 참고).
  column?: string | null;
};

export type PersonalColorItemMatchResponse = {
  provider: string;
  configured: boolean;
  products: RakutenProduct[];
  message: string;
  // true = 라이브 검색·입점 검증을 건너뛴 즉답. 뒤이어 오는 full 응답으로 교체된다.
  partial?: boolean;
};

export type Ingredient = {
  id: number;
  name: string;
  benefit: string;
  targets: string[];
};

export type Product = {
  id: number;
  brand: string;
  name: string;
  category: string;
  price: number;
  score?: number;
  description: string;
  ingredients: string[];
  product_url?: string | null;
  platform_links?: Record<string, string>;
  matched_platforms?: string[];
  image_url?: string | null;
  avg_rating?: number | null;
  review_count?: number | null;
  reason_tags?: string[];
  evidence_note?: string | null;
};

export type RecommendationPlatform =
  | 'all'
  | 'amazon_us'
  | 'amazon_jp'
  | 'naver'
  | 'matsukiyo'
  | 'oliveyoung';

// 퍼스널컬러/무드 아이템 추천용 플랫폼(라쿠텐 포함).
export type ItemPlatform = RecommendationPlatform | 'rakuten';

export type MakeupPreviewResponse = {
  mood: string;
  applied: boolean;
  message: string;
  original_image: string;
  image: string;
};

export type MoodThumbnailsResponse = {
  thumbnails: Record<string, string>;
};

export type FaceRatio = {
  label: string;
  width: number;
};

export type FaceShapeResponse = {
  detected: boolean;
  shape: string;
  tags: string[];
  summary: string;
  ratios: FaceRatio[];
  blusher_tip: string;
  shading_tip: string;
  metrics: Record<string, unknown>;
};

export type VirtualSurgeryTuning = {
  faceLine: number;
  jawBalance: number;
  noseContour: number;
  blemishCare: number;
};

export type VirtualSurgeryRecommendation = {
  title: string;
  category: string;
  score: number;
  summary: string;
  /** 1단계에서 고른 부위에 해당하는 추천인지. 점수가 아니라 정렬·표시에만 쓰인다. */
  selected?: boolean;
};

/** 미용 추천보다 **먼저** 보여야 하는 안내. 얼굴 사진에 진료가 필요한 소견이 보일 때 채워진다. */
export type MedicalReferral = {
  urgent: boolean;
  label: string;
  confidence: number;
  message: string;
};

/**
 * 사진 품질 점검. **결과를 막지 않는다** — 문제가 있어도 분석은 그대로 오고,
 * '정확도가 떨어질 수 있다'만 알린다.
 */
export type PhotoQuality = {
  ok: boolean;
  issues: { code: string; message: string }[];
  metrics: Record<string, number>;
};

export type VirtualSurgeryResponse = {
  detected: boolean;
  message: string;
  original_image: string;
  preview_image: string;
  face_shape?: FaceShapeResponse | null;
  recommendations: VirtualSurgeryRecommendation[];
  metrics: Record<string, unknown>;
  disclaimer: string;
  referral?: MedicalReferral | null;
  photo_quality?: PhotoQuality | null;
  /** 상담에서 물어볼 질문. 시술 추천이 아니라 질문 목록이다(설계안 §16). */
  consultation_questions?: string[];
  /**
   * 점·잡티 **후보 위치**(이미지 크기 대비 0~1 비율).
   * 자동으로 지우지 않는다 — 사용자가 고른 것만 retouch 로 지운다.
   */
  blemish_points?: BlemishPoint[];
};

export type BlemishPoint = { x: number; y: number; r: number };

export type VirtualSurgeryRetouchResponse = {
  preview_image: string;
  removed: number;
};

export type ProductColumn = {
  key: string;           // cleanser|toner|serum|moisturizer|sunscreen
  label: string;         // 클렌저/토너/세럼/보습/선크림
  reason?: string;
  products: Product[];
};

export type RecommendationResponse = {
  history_id: number;
  ingredients: Ingredient[];
  products: Product[];
  explanation: string;
  product_columns?: ProductColumn[];
};

export type ChatResponse = {
  answer: string;
  sources: string[];
};

export type HistoryItem = {
  id: number;
  recommended_ingredients: string[];
  recommended_products: string[];
  created_at: string;
};

/** 내 데이터 삭제 결과. 키는 테이블명, 값은 지운 건수. */
export type MyDataDeletionResult = {
  deleted: Record<string, number>;
};

export type NailDesignMatch = {
  design_id: string;
  region: string;           // 'foot' | 'hand'
  similarity: number;
  color_hex: string;
  delta_e: number;
  thumbnail?: string | null; // data URI(64px)
};

export type NailSeasonFit = {
  label: string;
  tone: string;
  subtype: string;
  shade_name: string;
  shade_hex: string;
  delta_e: number;
  score: number;
};

export type DetectedNail = {
  index: number;
  confidence: number;
  bbox: number[];
  color_hex: string;
  color_lab: number[];
  matches: NailDesignMatch[];
};

export type NailShade = { name: string; hex: string };

export type AnalyzeNailDesignResponse = {
  // 모델·인덱스가 배포에 빠지면 false로 온다(에러가 아니라 비활성).
  feature_available: boolean;
  index_size: number;
  detected: DetectedNail[];
  season_fit: NailSeasonFit[];
  // PROFILES의 네일 색이름 그대로라 item-match 검색어로 바로 넘길 수 있다.
  recommended_shades: string[];
  recommended_palette?: NailShade[];
  note: string;
};

/** 카드별 '내 얼굴 적용' 미리보기. 프리셋은 백엔드가 단일 출처다. */
/**
 * 카드별 상담 후보·비용 티어·회복 범위(설계안 §7·§8).
 * ⚠ cost_tier 는 **금액이 아니라 티어**다('낮음'/'중간~높음').
 */
export type ConsultationTier = { key: string; label: string; items: string[] };

export type ConsultationPlan = {
  /** 설계안 §9 4분류. 순서가 곧 메시지다 — 메이크업 → 피부과·쁘띠 → 성형외과 → 수술. */
  tiers: ConsultationTier[];
  tier_note: string;
  cost_tier: string;
  cost_note: string;
  recovery: string;
  difficulty: string;
  caution: string;
  candidate_note: string;
};

export type VirtualSurgeryPreviewCard = {
  id: string;
  title: string;
  summary: string;
  preview_image: string;
  consultation?: ConsultationPlan | null;
};

export type VirtualSurgeryPreviewCardsResponse = {
  detected: boolean;
  message: string;
  original_image: string;
  cards: VirtualSurgeryPreviewCard[];
  photo_quality?: PhotoQuality | null;
};

/** 변화 강도. 슬라이더 %(의학적 의미 없는 워프 강도)를 대신한다. */
export type VirtualSurgeryIntensity = 'natural' | 'balanced' | 'defined';
