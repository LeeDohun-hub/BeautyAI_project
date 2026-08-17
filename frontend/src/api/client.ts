import axios from 'axios';
import type { AnalysisMode, AnalyzeNailDesignResponse, AnalyzeSkinResponse, AuthConfigResponse, AuthSessionResponse, AuthUser, BodyConditionScore, CartHandoffItem, CartHandoffResponse, ChatResponse, FaceShapeResponse, HistoryItem, ItemPlatform, MakeupPreviewResponse, MoodThumbnailsResponse, MyDataDeletionResult, PersonalColorItemMatchResponse, PersonalColorResponse, RecommendationResponse, SkincareSimulationResponse, SkinScores, SurveyInput, VirtualSurgeryIntensity, VirtualSurgeryPreviewCardsResponse, VirtualSurgeryResponse, VirtualSurgeryRetouchResponse, VirtualSurgeryTuning } from '../types/api';

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

// ── 웹(BeautyWEB) 세션 직접 조회 ───────────────────────────────────────────────
// AI 오리진(ai.…)과 웹 API 호스트(www.…)는 오리진이 다르지만 **같은 사이트**(eTLD+1 이
// yopalette.com 으로 같다)다. 그래서 웹의 리프레시 쿠키(HttpOnly·Domain 미설정·SameSite
// 미지정=Lax)가 credentials:'include' 요청에 그대로 실려 간다 — 일본몰↔한국몰에서 이미
// 쓰고 있는 것과 같은 원리다. 웹 API 쪽 CORS 허용 목록에 AI 오리진이 있어야 한다.

/** 웹 로그인 상태 조회 결과.
 *
 *  - `active`     : 웹에 로그인돼 있고 액세스 토큰을 받았다.
 *  - `signed-out` : 웹이 **명확히** '로그인 아님'이라고 답했다.
 *  - `unknown`    : 물어보지 못했다(네트워크·CORS·5xx·타임아웃).
 *
 *  ⚠ `unknown` 과 `signed-out` 을 절대 같이 취급하면 안 된다. 웹 API 가 잠깐 삐끗한 것을
 *    '로그아웃'으로 읽으면 멀쩡히 쓰던 사용자의 AI 세션을 끊어버린다.
 */
export type WebSessionProbe =
  | { status: 'active'; accessToken: string }
  | { status: 'signed-out' }
  | { status: 'unknown' };

/** 부팅을 오래 붙잡지 않도록 하는 상한. 웹 API 가 죽어도 게이트까지는 즉시 가야 한다. */
const WEB_PROBE_TIMEOUT_MS = 6000;
/** JWT 모양(헤더.페이로드.서명). 응답이 토큰인지 엉뚱한 HTML 인지 가른다. */
const JWT_SHAPE = /^[\w-]+\.[\w-]+\.[\w-]+$/;

async function webFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), WEB_PROBE_TIMEOUT_MS);
  try {
    return await fetch(url, { ...init, credentials: 'include', signal: controller.signal });
  } finally {
    window.clearTimeout(timer);
  }
}

/** 웹에 로그인돼 있는지 묻는다(`GET {web}/account/token`).
 *
 * ⚠ 웹은 **로그인이 아니어도 200** 을 돌려주고 본문만 빈 문자열이다
 *   (AccountController#regenerate). 상태코드로 판단하면 전원 로그인으로 보인다.
 */
export async function probeWebSession(webApiBase: string): Promise<WebSessionProbe> {
  const base = (webApiBase || '').replace(/\/$/, '');
  if (!base) return { status: 'unknown' };
  try {
    const res = await webFetch(`${base}/account/token`);
    if (!res.ok) return { status: 'unknown' };
    const body = (await res.text()).trim();
    if (!body) return { status: 'signed-out' };
    // 주소를 잘못 잡으면(예: API 가 아니라 웹 **프론트** 주소) 200 + index.html 이 온다.
    // 그걸 토큰으로 착각하면 '로그인됨'으로 오판하고 다음 호출에서 401 로 튕긴다.
    if (!JWT_SHAPE.test(body)) return { status: 'unknown' };
    return { status: 'active', accessToken: body };
  } catch {
    return { status: 'unknown' };
  }
}

/** 웹에서 1회용 핸드오프 티켓을 받아온다(120초). 웹의 AI 버튼이 하는 일과 같다. */
export async function requestWebAiTicket(webApiBase: string, accessToken: string): Promise<string> {
  const res = await webFetch(`${(webApiBase || '').replace(/\/$/, '')}/account/ai-ticket`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) throw new Error(`ai-ticket ${res.status}`);
  const data = (await res.json()) as { ticket?: string };
  if (!data.ticket) throw new Error('ai-ticket empty');
  return data.ticket;
}

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

export async function simulateVirtualSurgery(
  file: File,
  tuning: VirtualSurgeryTuning,
  // 1단계에서 고른 값. **순서가 우선순위**라 배열 그대로 콤마로 잇는다.
  // 이게 없으면 사용자가 무엇을 골라도 추천이 똑같다(2026-08-03 이전 동작).
  choices: { concerns?: string[]; desiredMoods?: string[] } = {},
): Promise<VirtualSurgeryResponse> {
  const form = new FormData();
  form.append('image', file);
  form.append('face_line', String(tuning.faceLine));
  form.append('jaw_balance', String(tuning.jawBalance));
  form.append('nose_contour', String(tuning.noseContour));
  form.append('blemish_care', String(tuning.blemishCare));
  form.append('concerns', (choices.concerns ?? []).join(','));
  form.append('desired_moods', (choices.desiredMoods ?? []).join(','));
  const { data } = await api.post<VirtualSurgeryResponse>('/api/virtual-surgery/simulate', form);
  return data;
}

/**
 * 사용자가 고른 점·잡티만 지운다.
 *
 * ⚠ 원본 파일을 다시 보낸다. 서버가 사진을 들고 있지 않기 때문이다(개인정보 미저장).
 *   왕복이 한 번 더 늘지만 '적용'을 누를 때만 일어난다.
 */
export async function retouchBlemishes(
  file: File,
  points: { x: number; y: number; r: number }[],
): Promise<VirtualSurgeryRetouchResponse> {
  const form = new FormData();
  form.append('image', file);
  form.append('points', points.map((p) => `${p.x},${p.y},${p.r}`).join(';'));
  const { data } = await api.post<VirtualSurgeryRetouchResponse>('/api/virtual-surgery/retouch', form);
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

/** 케어를 이어갔을 때의 예상 모습. 분석 점수를 함께 보내 **걸린 항목만** 손대게 한다. */
export async function simulateSkincare(
  file: File,
  scores?: SkinScores,
  strength = 1,
  // 바디는 얼굴 랜드마크가 없어 서버가 살색 범위로 피부를 고른다.
  mode: AnalysisMode = 'face',
): Promise<SkincareSimulationResponse> {
  const form = new FormData();
  form.append('image', file);
  // ⚠ 원본을 다시 보낸다 — 서버가 사진을 들고 있지 않다(개인정보 미저장 원칙).
  (['acne', 'pore', 'wrinkle', 'redness', 'pigmentation', 'oiliness'] as const).forEach((key) => {
    form.append(key, String(scores?.[key] ?? 0));
  });
  form.append('strength', String(strength));
  form.append('mode', mode);
  const { data } = await api.post<SkincareSimulationResponse>('/api/skin/care-simulation', form);
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

/** 상담 질문. `lang` 은 **화면 언어**를 그대로 보낸다.
 *
 * 서버의 답변 경로가 전부 한국어라 일본어 모드에서 한국어 답이 돌아왔다(실측 2026-08-07).
 * 지역(region)과는 다른 축이라 따로 보낸다 — 지역은 '어디서 사나', 언어는 '무엇으로 읽나'다.
 */
export async function chat(
  message: string,
  scores?: SkinScores,
  survey?: SurveyInput,
  lang?: string,
): Promise<ChatResponse> {
  const { data } = await api.post<ChatResponse>('/api/chat', {
    message,
    context: scores || survey ? { scores, survey } : undefined,
    lang,
  });
  return data;
}

export async function getHistory(): Promise<HistoryItem[]> {
  const { data } = await api.get<HistoryItem[]>('/api/history');
  return data;
}

/**
 * 내 분석·설문·추천이력·상담기록을 지운다. **되돌릴 수 없다.**
 *
 * 계정 자체는 지우지 않는다 — 웹에서 넘어온 연동 정보라 여기서 지우면 로그인 상태와
 * 어긋난다(탈퇴는 웹 소관). 테이블별 삭제 건수를 돌려주므로 무엇이 지워졌는지 보여줄 수 있다.
 */
export async function deleteMyData(): Promise<MyDataDeletionResult> {
  const { data } = await api.delete<MyDataDeletionResult>('/api/me/data');
  return data;
}

/**
 * 카드별 미리보기. 서버가 Face Mesh 를 1회만 돌리고 워프만 카드 수만큼 반복하므로
 * 카드 4장이 단일 시뮬레이션보다 오히려 빠르다(실측 1.07s vs 3.74s).
 */
export async function previewVirtualSurgeryCards(
  file: File,
  intensity: VirtualSurgeryIntensity = 'balanced',
  // 1단계 선택. 안 보내면 4단계 카드가 1단계와 무관한 고정 4장이 된다.
  choices: { concerns?: string[]; desiredMoods?: string[] } = {},
): Promise<VirtualSurgeryPreviewCardsResponse> {
  const form = new FormData();
  form.append('image', file);
  form.append('intensity', intensity);
  form.append('concerns', (choices.concerns ?? []).join(','));
  form.append('desired_moods', (choices.desiredMoods ?? []).join(','));
  const { data } = await api.post<VirtualSurgeryPreviewCardsResponse>(
    '/api/virtual-surgery/preview-cards',
    form,
  );
  return data;
}
