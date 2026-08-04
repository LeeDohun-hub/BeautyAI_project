/*
 * YoPalette 서비스워커 — 설치 가능(PWA) 요건과 최소한의 오프라인 폴백만 담당한다.
 *
 * ⚠ 설계 원칙: **캐시가 배포를 막지 않게 한다.**
 *   서비스워커를 잘못 짜면 사용자가 옛 버전에 영구히 갇힌다. 실제로 겪은 배포 사고
 *   (푸시는 성공했는데 서비스는 옛 버전)와 같은 종류의 문제를, 이번엔 브라우저 쪽에서
 *   만들 수 있다. 그래서 아래를 지킨다:
 *
 *   1. HTML(내비게이션)은 **항상 네트워크 우선**. 새 배포가 즉시 반영된다.
 *      캐시는 오프라인일 때만 쓴다.
 *   2. /assets/* 만 캐시 우선. Vite 가 내용 해시를 붙이므로 같은 URL 의 내용은 불변이다.
 *      새 배포는 새 파일명을 쓰므로 옛 캐시가 새 코드를 가릴 수 없다.
 *   3. /api, /internal 은 **절대 캐시하지 않는다**. 분석 결과·상품은 매번 새로 받아야 한다.
 *   4. skipWaiting + clients.claim — 새 SW 가 다음 로드에서 바로 적용된다.
 *      (모든 탭이 닫힐 때까지 기다리면 사용자는 이유 없이 옛 버전을 계속 본다.)
 */

const VERSION = 'yopalette-v1';
const SHELL = `${VERSION}-shell`;
const ASSETS = `${VERSION}-assets`;
const OFFLINE_URL = '/index.html';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL).then((cache) => cache.add(OFFLINE_URL)).then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  // 다른 오리진(상품 이미지 CDN 등)은 손대지 않는다 — 캐시해봐야 용량만 먹고,
  // 핫링크 정책이 바뀌면 옛 이미지를 계속 보여주게 된다.
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/internal/')) return;
  if (url.pathname === '/health' || url.pathname === '/ready') return;

  // 내비게이션: 네트워크 우선. 실패(오프라인)할 때만 셸을 준다.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() => caches.match(OFFLINE_URL).then((r) => r || Response.error())),
    );
    return;
  }

  // 해시가 붙은 정적 자산만 캐시 우선.
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            // 부분 응답·오류는 캐시하면 안 된다(다음에 깨진 걸 준다).
            if (response.ok && response.status === 200) {
              const copy = response.clone();
              caches.open(ASSETS).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
  }
});
