// ESLint 설정 — **훅 규칙을 잡는 것**이 도입 목적이다.
//
// 계기(2026-08-03): 카드 미리보기용 useEffect 를 조건부로 호출되는 렌더 함수 안에 넣어
// 가상 성형 화면이 운영에서 **빈 화면으로 죽었다**. 그런데 `tsc -b` 도, CI 도, 백엔드
// 테스트 382건도 전부 초록불이었다 — 이 프로젝트에 ESLint 가 아예 없어서 Rules of Hooks
// 를 보는 것이 하나도 없었기 때문이다.
//
// ⚠ 스타일 규칙은 켜지 않는다. 기존 코드가 크고(App.tsx 6천 줄+) 스타일 위반이 쏟아지면
//   경고에 묻혀 **진짜 버그 규칙까지 무시하게 된다**. 지금은 '화면을 죽이는 부류'만
//   error 로 두고, 나머지는 필요할 때 하나씩 켜는 편이 실제로 지켜진다.
import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'src/**/*.bak-*'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      // ── 이것들이 도입 이유다(화면이 죽는 부류) ──────────────────────────────
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',

      // ── 기존 코드를 존중해 끄는 것들 ────────────────────────────────────────
      // any 는 이 코드베이스에 이미 많고, 바꾸려면 런타임 동작 확인이 필요하다.
      '@typescript-eslint/no-explicit-any': 'off',
      // catch {} 로 의도적으로 삼키는 패턴이 곳곳에 있다(폴백이 있는 자리).
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'no-empty': ['warn', { allowEmptyCatch: true }],
    },
  },
  {
    // i18n.ts 는 한국어 원문을 키로 쓰는 큰 사전이라 @ts-nocheck 가 의도적으로 붙어 있다.
    files: ['src/i18n.ts'],
    rules: { '@typescript-eslint/ban-ts-comment': 'off' },
  },
);
