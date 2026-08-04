import React from 'react';
import ReactDOM from 'react-dom/client';
import { CssBaseline, ThemeProvider, createTheme } from '@mui/material';
import App from './App';
import { APP_LANG_STORAGE_KEY, AppLangContext, type AppLang } from './i18n';
import './styles.css';

/** 화면 언어 상태. 선택은 localStorage 에 남겨 새로고침해도 유지된다. */
function AppLangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = React.useState<AppLang>(() => {
    const saved = typeof window !== 'undefined' ? window.localStorage.getItem(APP_LANG_STORAGE_KEY) : null;
    if (saved === 'ja' || saved === 'ko') return saved;
    // 저장값이 없으면 브라우저 언어로 첫 추정(일본어 사용자는 바로 일본어 화면).
    const nav = typeof navigator !== 'undefined' ? navigator.language.toLowerCase() : '';
    return nav.startsWith('ja') ? 'ja' : 'ko';
  });
  const setLang = React.useCallback((next: AppLang) => {
    setLangState(next);
    try {
      window.localStorage.setItem(APP_LANG_STORAGE_KEY, next);
    } catch {
      /* 프라이빗 모드 등 저장 실패는 무시 — 세션 동안은 상태로 유지된다. */
    }
    document.documentElement.lang = next;
  }, []);
  React.useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const value = React.useMemo(() => ({ lang, setLang }), [lang, setLang]);
  return <AppLangContext.Provider value={value}>{children}</AppLangContext.Provider>;
}

// YoPalette 브랜드 팔레트 — BeautyWEB(beautyweb-frontend/src/styles.css)과 값을 맞춘다.
// 스카이블루 계열: 본문 배경 #f5fbff, 잉크 #18233a, 액센트 #1d8fc7,
// 포인트(딸기요구르트) #f06f9b. Web 과 같은 색을 써야 두 서비스가 한 브랜드로 보인다.
const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#1d8fc7', dark: '#1d6eaa', light: '#2f9ed8', contrastText: '#ffffff' },
    secondary: { main: '#f06f9b', contrastText: '#ffffff' },
    background: { default: '#f5fbff', paper: '#ffffff' },
    text: { primary: '#18233a', secondary: '#657487' },
    divider: '#d8ecf8',
  },
  typography: {
    fontFamily: ['Inter', 'Segoe UI', 'Arial', 'sans-serif'].join(','),
    h4: { fontWeight: 800 },
    h6: { fontWeight: 700 },
    button: { textTransform: 'none', fontWeight: 700 },
  },
  shape: { borderRadius: 8 },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AppLangProvider>
        <App />
      </AppLangProvider>
    </ThemeProvider>
  </React.StrictMode>,
);

/*
 * 서비스워커 등록 — 홈 화면 설치(PWA)와 오프라인 폴백용.
 *
 * ⚠ **개발 서버에서는 등록하지 않는다.** vite dev 는 모듈을 매번 새로 주는데 SW 가 끼면
 *   고친 코드가 반영 안 되는 것처럼 보여 원인 찾기가 어려워진다.
 * ⚠ 등록 실패는 삼킨다. SW 는 부가 기능이라, 안 되더라도 앱은 그대로 동작해야 한다
 *   (사설 인증서·프라이빗 모드 등에서 실패할 수 있다).
 */
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => undefined);
  });
}

