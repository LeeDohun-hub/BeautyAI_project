export type SkinScores = {
  acne: number;
  pore: number;
  wrinkle: number;
  redness: number;
  pigmentation: number;
  oiliness: number;
};

export type SurveyInput = {
  skin_type: string;
  concerns: string[];
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
};

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

