/**
 * AI 앱의 회원 동선/선호 수집기.
 *
 * WEB(beautyweb-frontend/src/tracking.ts)과 같은 발상이지만 보내는 곳도 남기는 행동도
 * 다르다. AI 는 물건을 파는 앱이 아니라 분석해 주는 앱이라, 이탈이 '장바구니'가 아니라
 * **사진과 분석**에서 난다. 그래서 사진 준비·분석 성공·분석 실패를 따로 남긴다.
 *
 * 설계에서 지키는 것 세 가지.
 *  ① 화면을 절대 방해하지 않는다 — 실패는 전부 조용히 삼킨다. 수집이 안 되는 것보다
 *     수집 때문에 분석이 안 돌아가는 게 훨씬 나쁘다.
 *  ② 요청을 아낀다 — 모았다가 한 번에 보낸다.
 *  ③ 끄고 켤 수 있다 — localStorage 플래그 하나로 사용자가 거부할 수 있다.
 */

import { getSessionToken } from './api/client';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '');

/** 브라우저 탭 하나의 방문을 묶는 값. 탭을 닫으면 사라진다(sessionStorage). */
const SESSION_KEY = 'beautyai_journey_session';
/** 사용자가 수집을 거부하면 여기에 "1" 이 들어간다. */
const OPT_OUT_KEY = 'beautyai_journey_opt_out';

const FLUSH_DELAY_MS = 1500;
/** 이만큼 쌓이면 시간과 무관하게 바로 보낸다. 서버 상한(30)보다 낮게 잡는다. */
const FLUSH_THRESHOLD = 10;
/** 서버가 죽어 있어도 메모리가 계속 부는 일이 없도록 큐 자체에 상한을 둔다. */
const MAX_QUEUE = 60;
/** 같은 행동이 이 시간 안에 또 오면 중복으로 보고 버린다. */
const DEDUPE_WINDOW_MS = 1000;

export type JourneyType =
  | 'app_open'
  | 'gate_view'
  | 'module_open'
  | 'photo_ready'
  | 'analysis_done'
  | 'analysis_error'
  | 'recommend_view'
  | 'product_click'
  | 'cart_handoff'
  | 'survey_submit';

type QueuedEvent = {
  type: JourneyType;
  module: string;
  product_id?: number;
  category?: string;
  brand?: string;
  platform?: string;
  price?: number;
  detail?: string;
};

type TrackDetail = {
  module?: string;
  productId?: number;
  category?: string;
  brand?: string;
  platform?: string;
  price?: number;
  /** 분석 실패 사유 같은 짧은 코드. 개인정보는 절대 넣지 않는다. */
  detail?: string;
};

let queue: QueuedEvent[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;
let currentModule = 'home';
let currentLang = 'ko';
let lastSignature = '';
let lastSignatureAt = 0;
let listenersBound = false;

export function isJourneyOptedOut(): boolean {
  try {
    return localStorage.getItem(OPT_OUT_KEY) === '1';
  } catch {
    // 시크릿 모드 등에서 localStorage 가 막히면 '거부하지 않음'으로 본다.
    return false;
  }
}

export function setJourneyOptOut(optedOut: boolean): void {
  try {
    if (optedOut) {
      localStorage.setItem(OPT_OUT_KEY, '1');
      queue = [];
    } else {
      localStorage.removeItem(OPT_OUT_KEY);
    }
  } catch {
    /* 저장이 안 되면 이번 세션에만 반영되지 않는다 — 화면을 막을 일은 아니다. */
  }
}

/**
 * 세션 아이디. 비로그인 사용자의 연속된 행동을 하나로 묶는 유일한 끈이다.
 *
 * randomUUID 는 https(또는 localhost)에서만 있다. 없는 환경에서 예외가 나면 수집이
 * 통째로 죽으므로 직접 만든 값으로 대체한다.
 */
export function journeySessionId(): string {
  try {
    const saved = sessionStorage.getItem(SESSION_KEY);
    if (saved) return saved;
    const created =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    sessionStorage.setItem(SESSION_KEY, created);
    return created;
  } catch {
    return '';
  }
}

/**
 * 지금 어느 기능·언어인지 알려둔다.
 *
 * 행동마다 module 을 넘기게 하면 어딘가에서 빠뜨리고, 그러면 기능별 표에 구멍이 난다.
 * 한 번 설정해 두고 이후 행동에 자동으로 붙인다.
 */
export function setJourneyContext(next: { module?: string; lang?: string }): void {
  if (next.module) currentModule = next.module;
  if (next.lang) currentLang = next.lang;
}

/**
 * 행동 한 건 기록.
 *
 * 같은 행동이 1초 안에 두 번 들어오면 버린다. React StrictMode 는 개발 모드에서 effect 를
 * 일부러 두 번 실행하는데, 그대로 두면 개발 중 모든 진입이 2배로 잡혀 퍼널을 믿을 수 없다.
 */
export function track(type: JourneyType, detail: TrackDetail = {}): void {
  if (isJourneyOptedOut()) return;

  const moduleName = detail.module ?? currentModule;
  const signature = `${type}|${moduleName}|${detail.productId ?? ''}|${detail.category ?? ''}|${detail.detail ?? ''}`;
  const now = Date.now();
  if (signature === lastSignature && now - lastSignatureAt < DEDUPE_WINDOW_MS) return;
  lastSignature = signature;
  lastSignatureAt = now;

  queue.push({
    type,
    module: moduleName,
    product_id: detail.productId,
    category: detail.category,
    brand: detail.brand,
    platform: detail.platform,
    price: detail.price,
    detail: detail.detail,
  });
  if (queue.length > MAX_QUEUE) queue = queue.slice(-MAX_QUEUE);

  bindUnloadFlush();
  if (queue.length >= FLUSH_THRESHOLD) {
    void flushJourney();
    return;
  }
  if (flushTimer === null) {
    flushTimer = setTimeout(() => {
      flushTimer = null;
      void flushJourney();
    }, FLUSH_DELAY_MS);
  }
}

/**
 * 쌓인 행동을 보낸다.
 *
 * axios 가 아니라 fetch 를 쓰는 건 `keepalive: true` 때문이다 — 사용자가 탭을 닫거나
 * 다른 사이트로 넘어가는 순간에도 요청이 끝까지 나간다. sendBeacon 도 같은 일을 하지만
 * 헤더를 못 붙여서 세션 토큰이 빠지고, 그러면 이탈 직전 행동만 전부 비로그인으로 기록된다.
 */
export async function flushJourney(): Promise<void> {
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (queue.length === 0 || isJourneyOptedOut()) return;

  const events = queue;
  queue = [];

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = getSessionToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  try {
    await fetch(`${API_BASE}/api/journey/events`, {
      method: 'POST',
      headers,
      keepalive: true,
      body: JSON.stringify({
        session_id: journeySessionId(),
        lang: currentLang,
        events,
      }),
    });
  } catch {
    /* 수집 실패는 조용히 넘어간다. 재시도하지 않는 이유는 아래 주석 참고. */
  }
}

/**
 * 탭을 닫거나 화면을 벗어날 때 남은 것을 밀어 넣는다.
 *
 * `pagehide` 를 쓰는 이유 — 모바일 사파리는 탭을 닫아도 `beforeunload` 를 안 부른다.
 * `visibilitychange` 도 같이 듣는 이유는, 사진을 찍으려고 앱을 내렸다가 그대로 안 돌아오는
 * 경우가 이 앱 이탈의 큰 몫이기 때문이다.
 */
function bindUnloadFlush(): void {
  if (listenersBound || typeof window === 'undefined') return;
  listenersBound = true;
  window.addEventListener('pagehide', () => void flushJourney());
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void flushJourney();
  });
}

/**
 * 실패한 이벤트를 다시 보내지 않는 것은 의도다. 재시도 큐를 두면 서버가 잠깐 죽었을 때
 * 되살아나는 순간 모든 브라우저가 밀린 이벤트를 한꺼번에 쏟아붓는다(thundering herd).
 * 통계가 몇 건 비는 것보다 그게 훨씬 위험하다.
 */
