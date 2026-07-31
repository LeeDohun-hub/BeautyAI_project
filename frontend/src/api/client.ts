import axios from 'axios';
import type { AnalysisMode, AnalyzeNailDesignResponse, AnalyzeSkinResponse, AuthConfigResponse, AuthSessionResponse, AuthUser, BodyConditionScore, CartHandoffItem, CartHandoffResponse, ChatResponse, FaceShapeResponse, HistoryItem, ItemPlatform, MakeupPreviewResponse, MoodThumbnailsResponse, PersonalColorItemMatchResponse, PersonalColorResponse, RecommendationPlatform, RecommendationResponse, SkinScores, SurveyInput, VirtualSurgeryResponse, VirtualSurgeryTuning } from '../types/api';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
});

/** AI 세션 토큰 보관 키. 웹 로그인과 별개로 AI 가 자체 발급한 토큰이다(기본 12시간). */
export const SESSION_STORAGE_KEY = 'beautyai_session_token';

export function getSessionToken(): string | null {
  try {
    return window.localStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setSessionToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(SESSION_STORAGE_KEY, token);
    else window.localStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // 시크릿 모드 등에서 localStorage 가 막혀 있어도 이번 세션은 그대로 쓸 수 있게 무시한다.
  }
}

// 모든 요청에 세션을 붙인다. 붙지 않으면 분석 결과가 계정에 안 쌓이고,
// REQUIRE_LOGIN 이 켜진 배포에서는 전부 401 이 된다.
api.interceptors.request.use((config) => {
  const token = getSessionToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

/** 웹 핸드오프 티켓을 AI 세션으로 교환한다. 성공하면 토큰을 저장하고 사용자 정보를 돌려준다. */
export async function exchangeTicket(ticket: string): Promise<AuthSessionResponse> {
  const { data } = await api.post<AuthSessionResponse>('/api/auth/exchange', { ticket });
  setSessionToken(data.token);
  return data;
}

/** 저장된 세션이 아직 유효한지 확인하고 최신 프로필을 가져온다. 만료면 401 이 난다. */
export async function fetchMe(): Promise<AuthUser> {
  const { data } = await api.get<AuthUser>('/api/auth/me');
  return data;
}

export async function fetchAuthConfig(): Promise<AuthConfigResponse> {
  const { data } = await api.get<AuthConfigResponse>('/api/auth/config');
  return data;
}

/** 결과지에 담은 상품으로 1회용 장바구니 코드를 만든다. QR 은 이 응답의 url 을 담는다. */
export async function createCartHandoff(items: CartHandoffItem[]): Promise<CartHandoffResponse> {
  const { data } = await api.post<CartHandoffResponse>('/api/cart/handoff', { items });
  return data;
}

/** 이미 아는 퍼스널컬러(웹 계정 저장값)로 결과지를 만든다 — 사진 촬영 없이. */
export async function personalColorProfile(label: string): Promise<PersonalColorResponse> {
  const { data } = await api.get<PersonalColorResponse>('/api/personal-color/profile', {
    params: { label },
  });
  return data;
}

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
  // 'instant' = 라이브 검색·입점 검증을 건너뛴 즉답(로컬 카탈로그만). 먼저 띄우고
  // 이어서 'full' 결과로 교체해 체감 대기를 줄인다.
  stage: 'full' | 'instant' = 'full',
): Promise<PersonalColorItemMatchResponse> {
  const { data } = await api.post<PersonalColorItemMatchResponse>('/api/personal-color/item-match', {
    keywords,
    // 네일이 검색어 수가 많아졌고(전 색상), 색상당 상품 풀도 넓히려 4→6으로 상향(백엔드 상한 8).
    hits_per_keyword: 6,
    region,
    platform,
    gender,   // 남성이면 백엔드가 베이스/브로우/컨실러/립밤으로 밸런싱한다.
    stage,
  });
  return data;
}

export async function analyzeNailDesign(file: File, topK = 5): Promise<AnalyzeNailDesignResponse> {
  const form = new FormData();
  form.append('image', file);
  form.append('top_k', String(topK));
  const { data } = await api.post<AnalyzeNailDesignResponse>('/api/analyze-nail-design', form);
  return data;
}

export async function analyzeFaceShape(file: File): Promise<FaceShapeResponse> {
  const form = new FormData();
  form.append('image', file);
  const { data } = await api.post<FaceShapeResponse>('/api/analyze-face-shape', form);
  return data;
}

export async function simulateVirtualSurgery(file: File, tuning: VirtualSurgeryTuning): Promise<VirtualSurgeryResponse> {
  const form = new FormData();
  form.append('image', file);
  form.append('face_line', String(tuning.faceLine));
  form.append('jaw_balance', String(tuning.jawBalance));
  form.append('nose_contour', String(tuning.noseContour));
  form.append('blemish_care', String(tuning.blemishCare));
  const { data } = await api.post<VirtualSurgeryResponse>('/api/virtual-surgery/simulate', form);
  return data;
}

export async function getMoodThumbnails(): Promise<MoodThumbnailsResponse> {
  const { data } = await api.get<MoodThumbnailsResponse>('/api/style/mood-thumbnails');
  return data;
}

export async function previewMakeupOnPhoto(
  file: File,
  mood: string,
  gender: 'female' | 'male' = 'female',
): Promise<MakeupPreviewResponse> {
  const form = new FormData();
  form.append('image', file);
  form.append('mood', mood);
  // 성별로 '강도'가 아니라 **올리는 항목**이 바뀐다 — 여성 립·볼·아이 / 남성 눈썹·립밤.
  form.append('gender', gender);
  const { data } = await api.post<MakeupPreviewResponse>('/api/style/makeup-preview/photo', form);
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
