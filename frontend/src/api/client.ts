import axios from 'axios';
import type { AnalyzeSkinResponse, HistoryItem, RecommendationPlatform, RecommendationResponse, SkinScores, SurveyInput } from '../types/api';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
});

export async function analyzeSkin(file: File): Promise<AnalyzeSkinResponse> {
  const form = new FormData();
  form.append('image', file);
  const { data } = await api.post<AnalyzeSkinResponse>('/api/analyze-skin', form);
  return data;
}

export async function recommend(
  survey: SurveyInput,
  analysisId?: number,
  scores?: SkinScores,
  platform: RecommendationPlatform = 'all',
): Promise<RecommendationResponse> {
  const { data } = await api.post<RecommendationResponse>('/api/recommend', {
    analysis_id: analysisId,
    scores,
    survey,
    platform,
  });
  return data;
}

export async function chat(message: string, scores?: SkinScores): Promise<string> {
  const { data } = await api.post<{ answer: string }>('/api/chat', {
    message,
    context: scores ? { scores } : undefined,
  });
  return data.answer;
}

export async function getHistory(): Promise<HistoryItem[]> {
  const { data } = await api.get<HistoryItem[]>('/api/history');
  return data;
}
