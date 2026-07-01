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

export async function analyzePersonalColor(file: File): Promise<PersonalColorResponse> {
  const form = new FormData();
  form.append('image', file);
  const { data } = await api.post<PersonalColorResponse>('/api/analyze-personal-color', form);
  return data;
}

export async function matchPersonalColorItems(
  keywords: string[],
  region = 'jp',
  platform: ItemPlatform = 'all',
): Promise<PersonalColorItemMatchResponse> {
  const { data } = await api.post<PersonalColorItemMatchResponse>('/api/personal-color/item-match', {
    keywords,
    hits_per_keyword: 4,
    region,
    platform,
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
