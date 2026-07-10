export type SkinScores = {
  acne: number;
  pore: number;
  wrinkle: number;
  redness: number;
  pigmentation: number;
  oiliness: number;
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
  age_group: string;       // "10s" | "20s" | "30s" | "40s" | "50s"
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
};

export type PersonalColorItemMatchResponse = {
  provider: string;
  configured: boolean;
  products: RakutenProduct[];
  message: string;
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

export type RecommendationResponse = {
  history_id: number;
  ingredients: Ingredient[];
  products: Product[];
  explanation: string;
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
