export type SkinScores = {
  acne: number;
  pore: number;
  wrinkle: number;
  redness: number;
  pigmentation: number;
  oiliness: number;
};

export type SurveyInput = {
  gender: string;          // "female" | "male"
  age_group: string;       // "10s" | "20s" | "30s" | "40s" | "50s"
  skin_type: string;
  concerns: string[];
  makeup_concerns: string[];
  area_concerns: string[];
  male_extras: string[];
  sensitivity: number;
  routine_level: string;
};

export type AnalyzeSkinResponse = {
  analysis_id: number;
  scores: SkinScores;
  summary: string;
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
};

export type RecommendationPlatform =
  | 'all'
  | 'amazon_us'
  | 'amazon_jp'
  | 'yahoo_japan'
  | 'naver'
  | 'matsukiyo'
  | 'oliveyoung';

export type RecommendationResponse = {
  history_id: number;
  ingredients: Ingredient[];
  products: Product[];
  explanation: string;
};

export type HistoryItem = {
  id: number;
  recommended_ingredients: string[];
  recommended_products: string[];
  created_at: string;
};

