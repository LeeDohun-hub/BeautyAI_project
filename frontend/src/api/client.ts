import axios from 'axios';
import type { AnalysisMode, AnalyzeSkinResponse, BodyConditionScore, ChatResponse, FaceShapeResponse, HistoryItem, ItemPlatform, MoodThumbnailsResponse, PersonalColorItemMatchResponse, PersonalColorResponse, RecommendationPlatform, RecommendationResponse, SkinScores, SurveyInput } from '../types/api';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
});

export async function analyzeSkin(file: File, analysisMode: AnalysisMode): Promise<AnalyzeSkinResponse> {
  const form = new FormData();
  form.append('image', file);
  form.append('analysis_mode', analysisMode);
  const { data } = await api.post<AnalyzeSkinResponse>('/api/analyze-skin', form);
  return data;
}

export async function analyzePersonalColor(files: File | File[]): Promise<PersonalColorResponse> {
  const form = new FormData();
  // 여러 장을 보내면 백엔드가 계절 확률을 평균해 판정을 안정화한다.
  const list = Array.isArray(files) ? files : [files];
  for (const file of list) form.append('images', file);
  const { data } = await api.post<PersonalColorResponse>('/api/analyze-personal-color', form);
  return data;
}

export async function matchPersonalColorItems(
  keywords: string[],
  region = 'jp',
  platform: ItemPlatform = 'all',
  gender: 'female' | 'male' = 'female',
): Promise<PersonalColorItemMatchResponse> {
  const { data } = await api.post<PersonalColorItemMatchResponse>('/api/personal-color/item-match', {
    keywords,
    // 네일이 검색어 수가 많아졌고(전 색상), 색상당 상품 풀도 넓히려 4→6으로 상향(백엔드 상한 8).
    hits_per_keyword: 6,
    region,
    platform,
    gender,   // 남성이면 백엔드가 베이스/브로우/컨실러/립밤으로 밸런싱한다.
  });
  return data;
}

export async function analyzeFaceShape(file: File): Promise<FaceShapeResponse> {
  const form = new FormData();
  form.append('image', file);
  const { data } = await api.post<FaceShapeResponse>('/api/analyze-face-shape', form);
  return data;
}

export async function getMoodThumbnails(): Promise<MoodThumbnailsResponse> {
  const { data } = await api.get<MoodThumbnailsResponse>('/api/style/mood-thumbnails');
  return data;
}

export async function recommend(
  survey: SurveyInput,
  analysisId?: number,
  scores?: SkinScores,
  platform: ItemPlatform = 'all',
  analysisMode: AnalysisMode = 'face',
  bodyConditions: BodyConditionScore[] = [],
  region: 'jp' | 'kr' = 'kr',
): Promise<RecommendationResponse> {
  const { data } = await api.post<RecommendationResponse>('/api/recommend', {
    analysis_id: analysisId,
    scores,
    analysis_mode: analysisMode,
    body_conditions: bodyConditions,
    survey,
    region,
    platform,
  });
  return data;
}

export async function chat(message: string, scores?: SkinScores, survey?: SurveyInput): Promise<ChatResponse> {
  const { data } = await api.post<ChatResponse>('/api/chat', {
    message,
    context: scores || survey ? { scores, survey } : undefined,
  });
  return data;
}

export async function getHistory(): Promise<HistoryItem[]> {
  const { data } = await api.get<HistoryItem[]>('/api/history');
  return data;
}
