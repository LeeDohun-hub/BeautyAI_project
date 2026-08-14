import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 개발 서버가 대신 백엔드를 부른다. 브라우저 입장에선 같은 출처라 CORS 가 생기지 않는다
    // — VITE_API_BASE_URL 로 다른 호스트를 직접 가리키면 운영 서버의 허용 목록에 로컬이
    // 없어서 전부 막힌다(실측 2026-08-14). 대상은 DEV_API_TARGET 으로 바꿀 수 있다.
    proxy: {
      '/api': {
        target: process.env.DEV_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: process.env.DEV_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});

