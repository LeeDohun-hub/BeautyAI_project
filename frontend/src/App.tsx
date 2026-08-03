import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Container,
  Divider,
  FormControlLabel,
  FormControl,
  Grid,
  IconButton,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Slider,
  Stack,
  Step,
  StepLabel,
  Stepper,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import {
  ArrowLeft,
  ArrowRight,
  Camera,
  History,
  ImagePlus,
  MessageSquare,
  RefreshCcw,
  Send,
  ScanFace,
  Sparkles,
  SlidersHorizontal,
  Trash2,
  X,
  Loader2,
} from 'lucide-react';
import { analyzeFaceShape, analyzeNailDesign, analyzePersonalColor, analyzeSkin, chat, createCartHandoff, exchangeTicket, fetchAuthConfig, fetchMe, getHistory, getMoodThumbnails, getSessionToken, matchPersonalColorItems, personalColorProfile as fetchDeclaredPersonalColor, previewMakeupOnPhoto, previewVirtualSurgeryCards, recommend, setSessionToken, simulateVirtualSurgery } from './api/client';
import { useAppLang, useT, type AppLang } from './i18n';
import type { AnalysisMode, DetectedNail, NailShade, AnalyzeNailDesignResponse, AnalyzeSkinResponse, AuthConfigResponse, AuthUser, BodyConditionScore, CartHandoffItem, FaceShapeResponse, HistoryItem, ItemPlatform, PersonalColorItemMatchResponse, PersonalColorResponse, Product, RakutenProduct, RecommendationPlatform, RecommendationResponse, SkinScores, SurveyInput, VirtualSurgeryResponse, VirtualSurgeryTuning, VirtualSurgeryIntensity, VirtualSurgeryPreviewCard } from './types/api';

// 상품을 외부 쇼핑몰에서 검색/열기 위한 링크. 직접 상품 URL이 아마존이면 그대로 쓰고,
// 그 외에는 브랜드+상품명으로 각 플랫폼 검색 결과를 연다.
function buildShopLinks(product: Product) {
  const query = encodeURIComponent(`${product.brand} ${product.name}`.trim());
  const amazonUs =
    product.product_url && /amazon\.com/i.test(product.product_url)
      ? product.product_url
      : `https://www.amazon.com/s?k=${query}`;
  const amazonJp =
    product.product_url && /amazon\.co\.jp/i.test(product.product_url)
      ? product.product_url
      : `https://www.amazon.co.jp/s?k=${query}`;
  return {
    oliveyoung: `https://global.oliveyoung.com/display/search?query=${query}`,
    amazon_us: amazonUs,
    amazon_jp: amazonJp,
    naver: `https://search.shopping.naver.com/search/all?query=${query}`,
    matsukiyo: `https://www.matsukiyococokara-online.com/search?text=${query}`,
    ...product.platform_links,
  };
}

// K-뷰티 브랜드 판별용(부분 일치, 소문자). 올리브영은 이 브랜드일 때만 노출한다.
const KBEAUTY_BRANDS = [
  'bioheal', 'wakemake', 'cosrx', 'innisfree', 'anua', 'tirtir', 'medicube',
  'beauty of joseon', 'round lab', 'torriden', 'numbuzin', 'skin1004', 'mixsoon',
  'laneige', 'sulwhasoo', 'etude', 'missha', 'some by mi', 'isntree', 'purito',
  'rom&nd', 'romand', 'peripera', 'clio', 'dr.jart', 'dr jart', 'manyo', 'abib',
  'axis-y', 'heimish', 'klairs', 'd.alba', 'mediheal', 'goodal', 'hince', 'espoir',
];
const isKBeauty = (brand: string) => {
  const b = (brand || '').toLowerCase();
  return KBEAUTY_BRANDS.some((k) => b.includes(k));
};

// 각 쇼핑몰 버튼: 브랜드 시그니처 컬러 + 실제 사이트 파비콘으로 매칭.
// kbeautyOnly가 true인 채널은 K-뷰티 브랜드 상품에만 노출한다.
const SHOP_PLATFORMS = [
  { key: 'amazon_us', label: 'Amazon(EN)', domain: 'amazon.com', bg: '#FF9900', fg: '#131A22', hover: '#E68A00', kbeautyOnly: false },
  { key: 'amazon_jp', label: 'Amazon(JP)', domain: 'amazon.co.jp', bg: '#FFB020', fg: '#131A22', hover: '#E69D1C', kbeautyOnly: false },
  { key: 'naver', label: '네이버', domain: 'naver.com', bg: '#03C75A', fg: '#FFFFFF', hover: '#02A94C', kbeautyOnly: false },
  { key: 'matsukiyo', label: '마츠키요', domain: 'matsukiyococokara-online.com', bg: '#174EA6', fg: '#FFFFFF', hover: '#123F86', kbeautyOnly: false },
  { key: 'oliveyoung', label: '올리브영', domain: 'global.oliveyoung.com', bg: '#80BA27', fg: '#FFFFFF', hover: '#6FA31F', kbeautyOnly: false },
] as const;

const PLATFORM_FILTERS: { value: RecommendationPlatform; label: string }[] = [
  { value: 'all', label: '모든 플랫폼' },
  { value: 'amazon_us', label: 'Amazon(EN)' },
  { value: 'amazon_jp', label: 'Amazon(JP)' },
  { value: 'naver', label: '네이버' },
  { value: 'matsukiyo', label: '마츠키요' },
  { value: 'oliveyoung', label: '올리브영' },
];

// 라쿠텐(퍼스널컬러/무드 아이템 추천 전용). 라쿠텐 상품은 실제 상품 URL을 직링크로 제공한다.
const RAKUTEN_PLATFORM = {
  key: 'rakuten', label: '라쿠텐', domain: 'rakuten.co.jp', bg: '#BF0000', fg: '#FFFFFF', hover: '#A00000',
} as const;

const ITEM_PLATFORM_META: Record<ItemPlatform, { key: ItemPlatform; label: string; domain: string; bg: string; fg: string; hover: string }> = {
  all: { key: 'all', label: 'All', domain: 'google.com', bg: '#111827', fg: '#FFFFFF', hover: '#020617' },
  rakuten: RAKUTEN_PLATFORM,
  amazon_us: { key: 'amazon_us', label: 'Amazon.com', domain: 'amazon.com', bg: '#232F3E', fg: '#FFFFFF', hover: '#111827' },
  amazon_jp: { key: 'amazon_jp', label: 'Amazon JP', domain: 'amazon.co.jp', bg: '#232F3E', fg: '#FFFFFF', hover: '#111827' },
  naver: { key: 'naver', label: 'Naver', domain: 'naver.com', bg: '#03C75A', fg: '#FFFFFF', hover: '#029E48' },
  matsukiyo: { key: 'matsukiyo', label: 'Matsukiyo 검색', domain: 'matsukiyococokara-online.com', bg: '#F4C400', fg: '#111827', hover: '#DEB200' },
  oliveyoung: { key: 'oliveyoung', label: 'Olive Young', domain: 'global.oliveyoung.com', bg: '#6FBA2C', fg: '#FFFFFF', hover: '#5CA322' },
};

type ItemRegion = 'jp' | 'kr';

function detectInitialRegion(): ItemRegion {
  if (typeof window === 'undefined') return 'kr';
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  const languages = [navigator.language, ...Array.from(navigator.languages || [])]
    .filter(Boolean)
    .map((value) => value.toLowerCase());
  if (timeZone === 'Asia/Tokyo' || languages.some((value) => value.startsWith('ja'))) {
    return 'jp';
  }
  if (timeZone === 'Asia/Seoul' || languages.some((value) => value.startsWith('ko'))) {
    return 'kr';
  }
  return 'kr';
}

const ITEM_REGION_FILTERS: { value: ItemRegion; label: string }[] = [
  { value: 'jp', label: '일본(JP)' },
  { value: 'kr', label: '한국(KR)' },
];

const JP_ITEM_PLATFORM_FILTERS: { value: ItemPlatform; label: string }[] = [
  { value: 'all', label: '모든 플랫폼' },
  { value: 'amazon_jp', label: 'Amazon(JP)' },
  { value: 'rakuten', label: '라쿠텐' },
  { value: 'oliveyoung', label: '올리브영' },
];

const KR_ITEM_PLATFORM_FILTERS: { value: ItemPlatform; label: string }[] = [
  { value: 'all', label: '모든 플랫폼' },
  { value: 'amazon_us', label: 'Amazon.com' },
  { value: 'naver', label: '네이버' },
  { value: 'oliveyoung', label: '올리브영' },
];

// 라쿠텐 검색 결과 상품의 플랫폼 링크: 라쿠텐은 실제 상품 URL, 나머지는 브랜드+상품명 검색 URL.
function buildRakutenShopLinks(product: RakutenProduct): Record<string, string> {
  const links = product.platform_links && Object.keys(product.platform_links).length
    ? product.platform_links
    : { rakuten: product.product_url };

  return Object.entries(links).reduce<Record<string, string>>((acc, [platform, url]) => {
    if (url) acc[platform] = url;
    return acc;
  }, {});
}

// 사이트 파비콘 URL (구글 파비콘 서비스 — 실제 브랜드 로고를 안정적으로 제공)
const faviconUrl = (domain: string) => `https://www.google.com/s2/favicons?domain=${domain}&sz=64`;
// 실제 스캔 가능한 QR 이미지(외부 생성기). data 에 URL/텍스트를 넣으면 QR PNG를 돌려준다.
// BeautyWEB 주소. 배포마다 다르므로 환경변수로 빼고, 없으면 로컬 개발 기본값을 쓴다.
const WEB_BASE_URL = (import.meta.env.VITE_WEB_BASE_URL as string | undefined) || 'http://localhost:5174';

/** URL 프래그먼트(#t=...)에서 핸드오프 티켓을 꺼내고, 주소창에서 지운다.
 *
 * 웹이 티켓을 쿼리(?t=)가 아니라 프래그먼트로 실어 보낸다 — 쿼리는 서버 접근로그와
 * Referer 헤더에 남지만 프래그먼트는 브라우저 밖으로 나가지 않는다. 읽은 뒤에는
 * replaceState 로 지워 새로고침·공유 때 티켓이 따라다니지 않게 한다. */
function takeHandoffTicket(): string | null {
  if (typeof window === 'undefined') return null;
  const hash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : window.location.hash;
  if (!hash) return null;
  const ticket = new URLSearchParams(hash).get('t');
  if (!ticket) return null;
  window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
  return ticket;
}
// BeautyWEB 은 언어별로 다른 포트에 뜬다(사용자 운영 방식): 한국어 5174 · 일본어 5175.
const WEB_URL_BY_LANG: Record<AppLang, string> = {
  ko: (import.meta.env.VITE_WEB_BASE_URL_KO as string | undefined) || 'http://localhost:5174',
  ja: (import.meta.env.VITE_WEB_BASE_URL_JA as string | undefined) || 'http://localhost:5175',
};

/** 카드에 붙은 구매 링크 중 하나를 고른다(선호 순서 → 없으면 남은 것 아무거나 → 원산지 URL).
 *
 * 장바구니 딥링크는 상품마다 '살 수 있는 URL' 이 하나는 있어야 의미가 있다.
 */
function firstPurchaseUrl(links: Record<string, string> | undefined, fallback?: string | null): string {
  const preferred = ['naver', 'rakuten', 'oliveyoung', 'amazon_us', 'amazon_jp', 'matsukiyo'];
  for (const key of preferred) {
    const url = links?.[key];
    if (url) return url;
  }
  const any = Object.values(links ?? {}).find(Boolean);
  return any || fallback || '';
}

/** AI 상품 id 에서 BeautyWEB 카탈로그의 external_id 를 뽑는다.
 *
 * 카탈로그에서 온 상품만 대상이다(`oyg-`=올리브영 글로벌 prdtNo, `oykr-`=국내몰 goodsNo,
 * `amz-`=ASIN). 라쿠텐·네이버 라이브 검색 결과나 AI DB 내부 id(`db-3824`)는 뽑지 않는다 —
 * 특히 숫자만인 id 는 다른 소스의 JAN 코드 같은 것과 우연히 겹쳐 **엉뚱한 상품이 장바구니에
 * 담긴다**(이 프로젝트에서 느슨한 매칭이 오탐을 낸 전례가 여러 번 있다).
 */
function catalogExternalId(productId?: string): string {
  if (!productId) return '';
  for (const prefix of ['oyg-', 'oykr-', 'amz-']) {
    if (productId.startsWith(prefix)) {
      const value = productId.slice(prefix.length);
      return /^\d+$/.test(value) ? '' : value;
    }
  }
  return '';
}

/** 결과지에 담은 상품 → 장바구니 핸드오프 항목.
 *
 * url 은 **카탈로그 상세 URL(product_url)을 우선**한다. platform_links 의 버튼 링크는
 * 검색 결과 페이지인 경우가 있어 BeautyWEB items.productUrl 과 안 맞는다. 다만 올리브영·
 * 아마존 전용 카드처럼 product_url 이 빈 경우가 있어, 그때만 버튼 링크로 폴백한다.
 */
function cartHandoffItems(
  products: { id?: string | number; name: string; brand: string; product_url?: string | null; image_url?: string | null; price?: number; source?: string; platform_links?: Record<string, string> }[],
  limit: number,
): CartHandoffItem[] {
  return products.slice(0, limit).map((product) => ({
    name: product.name,
    brand: product.brand,
    url: product.product_url || firstPurchaseUrl(product.platform_links, product.product_url),
    image_url: product.image_url ?? '',
    price: typeof product.price === 'number' ? product.price : 0,
    source: product.source ?? '',
    external_id: catalogExternalId(typeof product.id === 'string' ? product.id : ''),
  }));
}

const qrImageUrl = (data: string, size = 160) =>
  `https://api.qrserver.com/v1/create-qr-code/?size=${size}x${size}&margin=0&data=${encodeURIComponent(data)}`;

/**
 * 결과지의 '장바구니 담기' QR.
 *
 * 상품 목록을 QR 에 통째로 싣지 않는다 — 5개만 담아도 base64 가 1KB 를 넘겨 QR 이 아주
 * 조밀해지고 출력물에서 인식이 잘 안 된다. 서버에서 1회용 코드를 받아 짧은 주소만 싣는다.
 * 코드에 회원이 들어 있어서 **폰이 로그인 상태가 아니어도** 본인 장바구니에 담긴다.
 */
function CartHandoffQr({
  items,
  linked,
  size = 132,
}: {
  items: CartHandoffItem[];
  /** 웹 계정과 연동된 세션인지. 아니면 담을 장바구니가 없다. */
  linked: boolean;
  size?: number;
}) {
  const t = useT();
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  // 상품이 바뀔 때만 새 코드를 받는다 — 렌더마다 부르면 코드를 계속 새로 태운다.
  const signature = items.map((item) => `${item.name}|${item.url}`).join('');
  useEffect(() => {
    if (!linked || items.length === 0) {
      setUrl('');
      return;
    }
    let cancelled = false;
    setError('');
    createCartHandoff(items)
      .then((response) => {
        if (!cancelled) setUrl(response.url);
      })
      .catch(() => {
        if (!cancelled) setError('장바구니 QR 을 만들지 못했습니다.');
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, linked]);

  if (!linked) {
    return (
      <Typography variant="caption" color="text.secondary" sx={{ maxWidth: 132, display: 'block' }}>
        {t('웹 계정으로 로그인하면 QR 로 장바구니에 담을 수 있습니다.')}
      </Typography>
    );
  }
  if (error) {
    return <Typography variant="caption" color="error">{t(error)}</Typography>;
  }
  if (!url) {
    return <Box sx={{ width: size, height: size }}><LinearProgress /></Box>;
  }
  return <img src={qrImageUrl(url, size)} alt={t('장바구니 담기 QR')} width={size} height={size} />;
}

const ageGroups = [
  { value: 'baby', label: '영유아(0~2)' },
  { value: 'child', label: '아동(3~9)' },
  { value: '10s', label: '10대' },
  { value: '20s', label: '20대' },
  { value: '30s', label: '30대' },
  { value: '40s', label: '40대' },
  { value: '50s', label: '50대+' },
];

// 칩 옵션: children가 있으면 부모 선택 시 세부 항목이 펼쳐집니다.
type ChipOption = { value: string; label: string; children?: ChipOption[] };

// 성별 무관 공통 피부 건강 고민 (건조/장벽/아토피/알레르기 등)
const commonSkinConcerns: ChipOption[] = [
  { value: '건조·수분부족', label: '건조·수분부족' },
  { value: '기미·주근깨', label: '기미·주근깨' },
  {
    value: '피부장벽',
    label: '피부장벽 약화',
    children: [
      { value: '예민함', label: '예민함' },
      { value: '화끈거림', label: '화끈거림' },
      { value: '자극', label: '자극' },
    ],
  },
  { value: '아토피', label: '아토피' },
  { value: '알레르기', label: '알레르기' },
];

const femaleSkinConcerns: ChipOption[] = [
  { value: '트러블', label: '트러블' },
  { value: '모공', label: '모공' },
  { value: '주름', label: '주름' },
  { value: '홍조', label: '홍조' },
  { value: '색소침착', label: '색소침착' },
  { value: '유분', label: '유분' },
  { value: '칙칙함', label: '칙칙함' },
  { value: '다크서클', label: '다크서클' },
  { value: '탄력저하', label: '탄력저하' },
  ...commonSkinConcerns,
];

const maleSkinConcerns: ChipOption[] = [
  { value: '트러블', label: '트러블' },
  { value: '모공', label: '모공' },
  { value: '유분·번들거림', label: '유분·번들거림' },
  { value: '면도 후 자극', label: '면도 후 자극' },
  { value: '주름', label: '주름' },
  { value: '다크서클', label: '다크서클' },
  ...commonSkinConcerns,
];

const makeupConcernOptions: ChipOption[] = [
  { value: '파운데이션 밀림', label: '파운데이션 밀림' },
  { value: '들뜸', label: '들뜸' },
  { value: '지속력', label: '지속력 부족' },
  { value: '다크닝', label: '다크닝(산화)' },
  { value: '피부톤', label: '피부톤 안 맞음' },
  { value: '속건조', label: '속건조' },
  { value: '광택', label: '광택 표현' },
  {
    value: '커버력',
    label: '커버력 부족',
    children: [
      { value: '잡티 커버', label: '잡티 커버' },
      { value: '홍조 커버', label: '홍조 커버' },
      { value: '모공 커버', label: '모공 커버' },
    ],
  },
];

const areaConcernOptions: ChipOption[] = [
  { value: '눈가', label: '눈가' },
  { value: '입술', label: '입술' },
  { value: '목·데콜테', label: '목·데콜테' },
  { value: '코', label: '코' },
  { value: '턱', label: '턱' },
  { value: '이마', label: '이마' },
  { value: '볼', label: '볼' },
];

const maleExtraOptions = [
  { value: '두피·헤어', label: '두피·헤어' },
  { value: '바디', label: '바디' },
];

// 다중선택 칩. 부모를 고르면 children이 들여쓰기되어 펼쳐지고, 부모를 끄면 자식도 함께 해제됩니다.
function NestedChipSelect({
  options,
  value,
  onChange,
}: {
  options: ChipOption[];
  value: string[];
  onChange: (next: string[]) => void;
}) {
  // 표시는 번역하고 값(opt.value)은 한국어 그대로 넘긴다 — 값은 백엔드 매칭 키다.
  const t = useT();
  const groupSx = { display: 'flex', flexWrap: 'wrap', gap: 1 } as const;
  const itemSx = { border: '1px solid #d6deea !important', borderRadius: '8px !important' } as const;

  const toggle = (v: string, opt?: ChipOption) => {
    const has = value.includes(v);
    let next = has ? value.filter((x) => x !== v) : [...value, v];
    if (has && opt?.children?.length) {
      const kids = opt.children.map((c) => c.value);
      next = next.filter((x) => !kids.includes(x));
    }
    onChange(next);
  };

  return (
    <Box>
      <Box sx={groupSx}>
        {options.map((opt) => (
          <ToggleButton
            key={opt.value}
            value={opt.value}
            selected={value.includes(opt.value)}
            onClick={() => toggle(opt.value, opt)}
            size="small"
            sx={itemSx}
          >
            {t(opt.label)}
          </ToggleButton>
        ))}
      </Box>
      {options
        .filter((o) => o.children?.length && value.includes(o.value))
        .map((parent) => (
          <Box key={parent.value} sx={{ mt: 1, ml: 1.5, pl: 1.5, borderLeft: '2px solid #e3e9f2' }}>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
              {t(parent.label)} · {t('세부 선택')}
            </Typography>
            <Box sx={groupSx}>
              {parent.children!.map((child) => (
                <ToggleButton
                  key={child.value}
                  value={child.value}
                  selected={value.includes(child.value)}
                  onClick={() => toggle(child.value)}
                  size="small"
                  sx={itemSx}
                >
                  {t(child.label)}
                </ToggleButton>
              ))}
            </Box>
          </Box>
        ))}
    </Box>
  );
}

// 상담은 결과지까지 본 뒤 질문하는 흐름이라 마지막에 둔다(사용자 지시 2026-07-29).
const steps = ['설문', '피부 입력', '피부 분석', '추천', '결과지 출력', '상담'];
// 결과지에 담을 수 있는 최대 개수. 추천 카테고리가 5개(클렌저·토너·세럼·보습·선크림)라
// 카테고리당 하나씩 고를 수 있게 5로 둔다.
const SKIN_REPORT_MAX = 5;
// 퍼스널컬러 결과지도 같은 상한을 쓴다. 예전엔 4였고, 5번째를 체크하면 안내 없이 첫 선택이
// 조용히 밀려나(slice(-4)) 사용자가 "5개 담기 실패"로 관측했다. 컬럼도 5개(립·블러셔·아이·
// 베이스·네일)라 카테고리당 하나씩 고를 수 있는 게 자연스럽다.
const PC_REPORT_MAX = SKIN_REPORT_MAX;

// 추천 컬럼 헤더가 라벨만 있어 비어 보인다는 지적(2026-07-29). 백엔드가 reason 을 주는 건
// 세럼(고민 기반)뿐이라, 나머지는 이 기본 설명으로 채운다. reason 이 있으면 그쪽이 우선.
const SKIN_COLUMN_HINT: Record<string, string> = {
  cleanser: '순한 세정 · 잔여물 정리',
  toner: '수분 공급 · 결 정돈',
  serum: '고민 집중 케어',
  moisturizer: '장벽 보습 · 진정',
  sunscreen: '자외선 차단 · 색소 예방',
};

const scoreLabels: Record<keyof SkinScores, string> = {
  acne: '트러블',
  pore: '모공',
  wrinkle: '주름',
  redness: '홍조',
  pigmentation: '색소침착',
  oiliness: '유분',
};

const skinTypeLabels = [
  { value: 'dry', label: '건성' },
  { value: 'oily', label: '지성' },
  { value: 'combination', label: '복합성' },
  { value: 'normal', label: '중성' },
  { value: 'sensitive', label: '민감성' },
];

const routineLevelLabels = [
  { value: 'minimal', label: '간단한 루틴' },
  { value: 'basic', label: '기본 루틴' },
  { value: 'advanced', label: '집중 관리 루틴' },
];

const raceIdentityOptions = [
  '동아시아 (한국·중국·일본·대만)',
  '동남아시아 (베트남·태국·필리핀·인도네시아)',
  '남아시아 (인도·파키스탄·방글라데시·네팔)',
  '중동/북아프리카',
  '흑인/아프리카계',
  '백인/유럽계',
  '라틴계',
  '혼혈/다인종',
  '기타',
  '응답하지 않음',
];

type AppModule = 'home' | 'skin-care' | 'personal-color' | 'nail-design' | 'virtual-surgery';

const scoreKeys = Object.keys(scoreLabels) as (keyof SkinScores)[];

// 3구간 표시: 이 점수의 학습 라벨이 원래 2~3단계(없음/약간/많음)뿐이라 정밀한 숫자는
// 촬영 노이즈로 흔들린다. 구간(양호/보통/관리 필요)으로 보여주면 ±몇 점 흔들려도 같은 구간에
// 머물러 결과가 안정적이고, 데이터에도 솔직하다. 높을수록 심각(관리 필요).
function scoreBand(value: number): { label: string; color: 'success' | 'warning' | 'error' } {
  if (value < 34) return { label: '양호', color: 'success' };
  if (value < 67) return { label: '보통', color: 'warning' };
  return { label: '관리 필요', color: 'error' };
}

function ageToAgeGroup(age: string): string {
  const numericAge = Number.parseInt(age, 10);
  if (Number.isNaN(numericAge)) return '20s';
  // 영유아·아동: 바디 추천이 안내+소아안전 큐레이션으로 분기한다(성인 액티브·향료 배제).
  if (numericAge <= 2) return 'baby';
  if (numericAge < 10) return 'child';
  if (numericAge < 20) return '10s';
  if (numericAge < 30) return '20s';
  if (numericAge < 40) return '30s';
  if (numericAge < 50) return '40s';
  return '50s';
}

function averageSkinScores(results: AnalyzeSkinResponse[]): SkinScores {
  const totals = scoreKeys.reduce(
    (acc, key) => ({ ...acc, [key]: 0 }),
    {} as SkinScores,
  );

  results.forEach((result) => {
    scoreKeys.forEach((key) => {
      totals[key] += result.scores?.[key] ?? 0;
    });
  });

  return scoreKeys.reduce(
    (acc, key) => ({ ...acc, [key]: Math.round(totals[key] / results.length) }),
    {} as SkinScores,
  );
}

function averageBodyConditions(results: AnalyzeSkinResponse[]): BodyConditionScore[] {
  const totals = new Map<string, BodyConditionScore>();
  results.flatMap((result) => result.body_conditions ?? []).forEach((item) => {
    const current = totals.get(item.condition);
    totals.set(item.condition, {
      ...item,
      probability: (current?.probability ?? 0) + item.probability,
    });
  });
  return Array.from(totals.values())
    .map((item) => ({ ...item, probability: Math.round((item.probability / results.length) * 10) / 10 }))
    .sort((a, b) => b.probability - a.probability);
}

type StyleMood = {
  id: string;
  label: string;
  vibe: string;
  thumbClass: string;
  // 마켓 언어별 검색 키워드: jp는 라쿠텐(일본어), kr은 네이버(한국어).
  keywords: { jp: string[]; kr: string[] };
};

const STYLE_MOODS: StyleMood[] = [
  {
    id: 'cherry-chocolate',
    label: '진한 체리 초콜릿',
    vibe: '딥한 체리와 초콜릿 브라운으로 시크하고 무게감 있는 무드',
    thumbClass: 'cherry-chocolate',
    keywords: {
      jp: ['チェリー リップ', 'ボルドー リップ', 'ブラウン アイシャドウ', 'チョコレート メイク'],
      kr: ['체리 립', '버건디 립', '브라운 아이섀도우', '초콜릿 메이크업'],
    },
  },
  {
    id: 'tomato-red',
    label: '생기 토마토 레드',
    vibe: '주황빛이 도는 토마토 레드로 생기 있고 발랄한 무드',
    thumbClass: 'tomato-red',
    keywords: {
      jp: ['トマトレッド リップ', 'オレンジレッド リップ', 'レッド チーク', 'オレンジ アイシャドウ'],
      kr: ['토마토 레드 립', '오렌지 레드 립', '레드 블러셔', '오렌지 아이섀도우'],
    },
  },
  {
    id: 'rose-wine',
    label: '우아한 로즈 와인',
    vibe: '깊은 와인과 버건디로 우아하고 무드 있는 분위기',
    thumbClass: 'rose-wine',
    keywords: {
      jp: ['ワインレッド リップ', 'ボルドー リップ', 'ローズ チーク', 'バーガンディ アイシャドウ'],
      kr: ['와인 레드 립', '버건디 립', '로즈 블러셔', '버건디 아이섀도우'],
    },
  },
  {
    id: 'plum-creme',
    label: '매혹적인 자두 크림슈',
    vibe: '자두빛 플럼과 모브 톤으로 우아하고 매혹적인 무드',
    thumbClass: 'plum-creme',
    keywords: {
      jp: ['プラム リップ', 'すもも リップ', 'モーブ チーク', 'プラム アイシャドウ'],
      kr: ['플럼 립', '자두 립', '모브 블러셔', '플럼 아이섀도우'],
    },
  },
  {
    id: 'berry-sorbet',
    label: '상큼 베리 소르베',
    vibe: '상큼한 베리와 핑크 톤으로 화사하고 발랄한 무드',
    thumbClass: 'berry-sorbet',
    keywords: {
      jp: ['ベリー リップ', 'ピンク リップ', 'ベリー チーク', 'ピンク アイシャドウ'],
      kr: ['베리 립', '핑크 립', '베리 블러셔', '핑크 아이섀도우'],
    },
  },
  {
    id: 'peach-latte',
    label: '사랑스러운 복숭아 라떼',
    vibe: '부드러운 피치 핑크로 사랑스럽고 화사한 무드',
    thumbClass: 'peach-latte',
    keywords: {
      jp: ['ピーチ リップ', 'ピーチピンク リップ', 'ピーチ チーク', 'ピーチ アイシャドウ'],
      kr: ['피치 립', '피치 핑크 립', '피치 블러셔', '피치 아이섀도우'],
    },
  },
  {
    id: 'coral',
    label: '싱그러운 산호 코랄',
    vibe: '싱그러운 코랄로 생기 넘치는 따뜻한 무드',
    thumbClass: 'coral',
    keywords: {
      jp: ['コーラル リップ', 'サンゴ リップ', 'コーラル チーク', 'コーラル アイシャドウ'],
      kr: ['코랄 립', '산호 립', '코랄 블러셔', '코랄 아이섀도우'],
    },
  },
  {
    id: 'caramel-mocha',
    label: '차분한 카라멜 모카',
    vibe: '카라멜과 모카 브라운으로 차분한 데일리 무드',
    thumbClass: 'caramel-mocha',
    keywords: {
      jp: ['キャラメル リップ', 'ブラウン リップ', 'モカ チーク', 'ブラウン アイシャドウ'],
      kr: ['카라멜 립', '브라운 립', '모카 블러셔', '브라운 아이섀도우'],
    },
  },
];

type StyleMoodRecommendation = {
  mood: StyleMood;
  score: number;
  reason: string;
};

const STYLE_MOOD_SCORE_MAP: Record<string, Partial<Record<string, number>>> = {
  'cool-soft': { 'plum-creme': 5, 'berry-sorbet': 4.5, 'rose-wine': 4, 'cherry-chocolate': 2.5 },
  'cool-light': { 'berry-sorbet': 5, 'plum-creme': 4, 'rose-wine': 3.5, 'peach-latte': 2 },
  'cool-bright': { 'cherry-chocolate': 5, 'berry-sorbet': 4.5, 'rose-wine': 4, 'plum-creme': 3.5 },
  'cool-deep': { 'cherry-chocolate': 5, 'rose-wine': 4.5, 'plum-creme': 4, 'berry-sorbet': 3 },
  'warm-light': { 'peach-latte': 5, coral: 4.5, 'tomato-red': 3.5, 'caramel-mocha': 2 },
  'warm-soft': { 'caramel-mocha': 5, coral: 3.5, 'peach-latte': 3, 'rose-wine': 2.5 },
  'warm-deep': { 'caramel-mocha': 5, 'cherry-chocolate': 4.5, 'rose-wine': 3.5, 'tomato-red': 2.5 },
};

function moodRecommendationReason(result: PersonalColorResponse | null, mood: StyleMood): string {
  if (!result) return '퍼스널컬러 분석 전 기본 무드 후보입니다.';
  const season = displaySeasonLabel(result.label);
  if (result.tone === 'cool') {
    return `${season}의 차가운 색감과 ${mood.label}의 로즈·베리 계열 포인트가 잘 맞습니다.`;
  }
  return `${season}의 따뜻한 색감과 ${mood.label}의 피치·브라운 계열 포인트가 잘 맞습니다.`;
}

function recommendStyleMoods(
  result: PersonalColorResponse | null,
  face: FaceShapeResponse | null,
): StyleMoodRecommendation[] {
  const key = result ? `${result.tone}-${result.subtype}` : 'cool-soft';
  const baseScores = STYLE_MOOD_SCORE_MAP[key] ?? STYLE_MOOD_SCORE_MAP[`${result?.tone ?? 'cool'}-soft`] ?? {};
  const faceShape = faceShapeLabel(face?.detected ? face.shape : undefined);

  return STYLE_MOODS
    .map((mood) => {
      let score = baseScores[mood.id] ?? 1;
      if (/둥근|하트|계란/.test(faceShape) && ['berry-sorbet', 'peach-latte', 'plum-creme'].includes(mood.id)) score += 0.35;
      if (/각진|긴/.test(faceShape) && ['cherry-chocolate', 'rose-wine', 'caramel-mocha'].includes(mood.id)) score += 0.35;
      if (result?.metrics?.season_consistency && result.metrics.season_consistency >= 0.8) score += 0.25;
      return { mood, score, reason: moodRecommendationReason(result, mood) };
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);
}

// 퍼스널컬러 세부타입(`${tone}-${subtype}`)별 블러셔/쉐딩 큐레이션.
// 블러셔 '색'은 분석 결과(makeup.blush)를 그대로 쓰고, 여기서는 톤에 맞는 브랜드·쉐딩 색·
// 스와치 색만 타입별로 분기한다.
type FaceProductSet = {
  blushBrands: string[];
  shadingColors: string[];
  shadingBrands: string[];
  blushSwatch: string;
  shadingSwatch: string;
};

const FACE_PRODUCT_MAP: Record<string, FaceProductSet> = {
  'warm-light': { blushBrands: ['디어달리아', '롬앤'], shadingColors: ['소프트 카멜', '라이트 베이지 브라운'], shadingBrands: ['페리페라', '웨이크메이크'], blushSwatch: '#F7A98C', shadingSwatch: '#B98A63' },
  'warm-deep': { blushBrands: ['투쿨포스쿨', '롬앤'], shadingColors: ['딥 카멜', '초콜릿 브라운'], shadingBrands: ['투쿨포스쿨', '캔메이크'], blushSwatch: '#D77B53', shadingSwatch: '#7A5236' },
  'warm-soft': { blushBrands: ['힌스', '롬앤'], shadingColors: ['뮤트 베이지', '소프트 모카'], shadingBrands: ['힌스', '웨이크메이크'], blushSwatch: '#E0997A', shadingSwatch: '#9C7A5C' },
  'cool-light': { blushBrands: ['릴리바이레드', '클리오'], shadingColors: ['애쉬 베이지', '라이트 그레이 브라운'], shadingBrands: ['페리페라', '클리오'], blushSwatch: '#EBA6BE', shadingSwatch: '#A38C7E' },
  'cool-deep': { blushBrands: ['맥', '클리오'], shadingColors: ['애쉬 브라운', '쿨 다크 브라운'], shadingBrands: ['맥', '클리오'], blushSwatch: '#C76A86', shadingSwatch: '#6E5A52' },
  'cool-bright': { blushBrands: ['에스쁘아', '클리오'], shadingColors: ['그레이 브라운', '쿨 토프'], shadingBrands: ['에스쁘아', '클리오'], blushSwatch: '#E86C92', shadingSwatch: '#897066' },
  'cool-soft': { blushBrands: ['페리페라', '힌스'], shadingColors: ['그레이시 토프', '뮤트 애쉬'], shadingBrands: ['페리페라', '힌스'], blushSwatch: '#D89CAE', shadingSwatch: '#9A867E' },
};

const DEFAULT_FACE_PRODUCT_SET = FACE_PRODUCT_MAP['warm-light'];

// 카드 배지는 '로즈 핑크 립'처럼 사용자가 고른 색상 키워드일 때만 뜻이 있다. DB 상품은
// keyword 자리에 내부 카테고리('skincare','base','blush','body.scrub')가 들어와서, 립스틱
// 카드에 'skincare' 배지가 붙는 식으로 오히려 오해를 준다 — 그런 내부 토큰은 숨긴다.
// 실제 색상 키워드는 '로즈 핑크 립'/'ローズピンク リップ'처럼 반드시 비-ASCII를 포함한다.
// 반대로 내부 카테고리는 'skincare','Face','body.scrub','lip' 같은 ASCII 단일 토큰이다.
const INTERNAL_CATEGORY_BADGE = /^[a-z][a-z._-]*$/i;

/** 화면 언어 토글(KO/JA)과 연동 계정 표시. 어느 화면에서나 우상단에 고정으로 보인다. */
function AppLangToggle({ authUser }: { authUser?: AuthUser | null }) {
  const { lang, setLang } = useAppLang();
  const t = useT();
  return (
    <Stack direction="row" spacing={0.5} alignItems="center" className="lang-toggle">
      {/* 모듈마다 헤더가 달라서 여기 두면 홈·퍼스널컬러·네일 어디서나 연동 상태가 보인다. */}
      {authUser && (
        <Chip size="small" variant="outlined" label={`${authUser.name} ${t('님으로 연동됨')}`} sx={{ mr: 0.5 }} />
      )}
      {(['ko', 'ja'] as const).map((code) => (
        <Button
          key={code}
          size="small"
          variant={lang === code ? 'contained' : 'outlined'}
          onClick={() => setLang(code)}
          sx={{ minWidth: 44, px: 1 }}
        >
          {code === 'ko' ? '한국어' : '日本語'}
        </Button>
      ))}
    </Stack>
  );
}

function itemMatchBadgeLabel(keyword?: string | null): string | null {
  const label = (keyword || '').trim();
  if (!label) return null;
  return INTERNAL_CATEGORY_BADGE.test(label) ? null : label;
}

// KR 검색은 커버리지를 위해 키워드를 **[한국어, 영어] 쌍**으로 보낸다(`로즈 핑크 립`,
// `rose pink lipstick`). 그런데 배지는 '매칭된 키워드'를 그대로 보여주므로, 영어 쪽이
// 걸린 카드만 `ivory beige foundation` 처럼 튄다. 쌍을 되짚어 한국어로 되돌린다.
// 배지 문구 결정: (1) 한/영 쌍으로 되짚어 한국어가 있으면 그것, (2) KR 화면인데 끝내
// 영어만 남으면 **숨긴다**(색상은 컬럼 헤더가 이미 알려주므로 영어 배지는 튀기만 한다),
// (3) 그 외에는 상품 키워드 그대로(JP 는 일본어라 정상).
function itemMatchBadgeFor(
  product: RakutenProduct,
  koByEn: Record<string, string>,
  region: ItemRegion,
): string | null | undefined {
  const keyword = (product.keyword || '').trim();
  const korean = koByEn[keyword.toLowerCase()];
  if (korean) return korean;
  if (region === 'kr' && keyword && !/[가-힣]/.test(keyword)) return null;
  return undefined;
}

function koreanKeywordByEnglish(keywords: string[]): Record<string, string> {
  const map: Record<string, string> = {};
  for (let i = 0; i + 1 < keywords.length; i += 2) {
    const ko = keywords[i];
    const en = keywords[i + 1];
    // 쌍의 두 번째만 라틴문자일 때가 실제 [한국어, 영어] 쌍이다.
    if (/[가-힣]/.test(ko) && !/[가-힣]/.test(en)) map[en.trim().toLowerCase()] = ko;
  }
  return map;
}

// 상품 대표 이미지. 죽은 URL(올리브영 403, 라쿠텐/마츠키요 404, 네트워크 오류 등)이면
// 깨진 이미지 아이콘 대신 placeholder로 폴백한다. src가 바뀌면 오류 상태를 초기화한다.
function ProductImage({
  src,
  alt,
  fallback,
}: {
  src?: string | null;
  alt: string;
  fallback: ReactNode;
}) {
  const [errored, setErrored] = useState(false);
  useEffect(() => {
    setErrored(false);
  }, [src]);
  if (!src || errored) {
    return <>{fallback}</>;
  }
  return <img src={src} alt={alt} loading="lazy" onError={() => setErrored(true)} />;
}

// region prop 은 가격 표기(통화 포맷) 전용이었는데 가격을 없애면서 함께 제거했다.
function RakutenProductCard({
  product,
  selectedPlatform = 'all',
  badgeLabel,
  checked = false,
  disabled = false,
  onCheckedChange,
}: {
  product: RakutenProduct;
  selectedPlatform?: ItemPlatform;
  badgeLabel?: string | null;   // 지정하면 배지를 이 값으로 그린다(한국어 되돌리기용).
  checked?: boolean;
  disabled?: boolean;           // 결과지 담기 상한 도달 시 새 체크를 막는다.
  onCheckedChange?: (checked: boolean) => void;
}) {
  const t = useT();
  const { lang } = useAppLang();
  const links = buildRakutenShopLinks(product);
  const matchedPlatforms = product.matched_platforms?.length
    ? product.matched_platforms
    : Object.keys(links);
  const visiblePlatforms = matchedPlatforms
    .filter((key): key is ItemPlatform => key !== 'all' && key in ITEM_PLATFORM_META && Boolean(links[key]))
    .filter((key) => selectedPlatform === 'all' || key === selectedPlatform)
    .map((key) => ITEM_PLATFORM_META[key]);
  const rawBadge = itemMatchBadgeLabel(badgeLabel === undefined ? product.keyword : badgeLabel);
  // 사전에 있으면 사전 문구, 없으면 단어 단위로 옮긴다('쿨 아이보리 남성 쿠션 팩트'처럼
  // 색상+카테고리가 조합된 키워드는 문장 사전으로 못 덮는다). 한국어 모드에선 원문 그대로.
  const badgeText = !rawBadge
    ? null
    : t(rawBadge) !== rawBadge
      ? t(rawBadge)
      : lang === 'ja'
        ? localizePcPhraseToJa(rawBadge)
        : rawBadge;
  return (
    <Box className="rakuten-product-card">
      {onCheckedChange && (
        <FormControlLabel
          className="report-pick-control"
          control={
            <Checkbox
              checked={checked}
              disabled={disabled}
              onChange={(event) => onCheckedChange(event.target.checked)}
              size="small"
            />
          }
          label={t('결과지에 담기')}
        />
      )}
      <Box className="rakuten-product-image">
        <ProductImage src={product.image_url} alt={product.name} fallback={<Sparkles size={26} />} />
      </Box>
      {/* badgeLabel: 지정 없으면(undefined) 상품 키워드를 쓰고, null 이면 배지를 숨긴다.
          배지는 '검색 키워드'라 원문이 한국어다(KR 검색은 한국어여야 결과가 나오므로 키워드
          자체는 절대 바꾸지 않는다). 화면에 보이는 문구만 번역한다. */}
      {badgeText && (
        <Chip label={badgeText} size="small" sx={{ width: 'fit-content' }} />
      )}
      <Typography fontWeight={900} className="rakuten-product-title">{product.name}</Typography>
      <Typography variant="body2" color="text.secondary" noWrap>{product.brand}</Typography>
      {/* 가격은 일부러 표시하지 않는다(2026-07-29 실측 근거).
          카드 하나에 구매 버튼이 여러 개인데 가격은 하나뿐이라, 어느 버튼을 누르든 최소
          하나는 틀린 값이 된다. 올리브영 버튼이 붙은 카드 5건을 실제 국내몰 판매가와 대조하니
          **일치 0건, ±10% 이내 0건, 최대 오차 118%**(표시 3,670 → 실제 8,000; 헤라
          41,400 → 56,700)였다. 차이의 상당 부분은 단순 가격차가 아니라 **구성이 다른 상품**
          (네이버 '2개 세트' ↔ 올영 '단품')이라 출처를 병기해도 오해가 남는다.
          가격은 클릭 후 실제 판매처에서 확인하는 것이 정확하다. */}
      {product.review_average ? (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
          ★ {product.review_average}
          {product.review_count ? ` (${product.review_count.toLocaleString()})` : ''}
        </Typography>
      ) : null}
      <Stack direction="row" gap={0.8} flexWrap="wrap" sx={{ mt: 'auto', pt: 1.2 }}>
        {visiblePlatforms.map((platform) => (
          <Button
            key={platform.key}
            component="a"
            href={links[platform.key]}
            target="_blank"
            rel="noreferrer"
            size="small"
            variant="contained"
            disableElevation
            startIcon={
              <Box sx={{ width: 16, height: 16, borderRadius: '4px', bgcolor: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Box component="img" src={faviconUrl(platform.domain)} alt="" width={12} height={12} sx={{ display: 'block' }} />
              </Box>
            }
            sx={{ bgcolor: platform.bg, color: platform.fg, fontWeight: 700, minWidth: 0, '&:hover': { bgcolor: platform.hover } }}
          >
            {platform.label}
          </Button>
        ))}
      </Stack>
    </Box>
  );
}

// 여성=립/블러셔/아이/베이스/네일, 남성(Level 2)=베이스/브로우/컨실러/립밤(그루밍 중심).
// 실제 컬럼 구성/헤더는 renderPersonalColorPage의 itemMatchGroups가 성별에 맞춰 정한다.
type ItemMatchColumnKey = 'lip' | 'blush' | 'eye' | 'base' | 'nail' | 'brow' | 'concealer' | 'lipbalm';

// 비화장품 배제: '남자 쿠션' 검색이 쿠션 신발/양말/방석 같은 잡화를 물어와 base로 오분류되는
// 문제를 막는다. 이 토큰이 있으면 어느 컬럼에도 넣지 않는다(백엔드 _NON_COSMETIC_RE와 동일).
const NON_COSMETIC_RE = /(운동화|신발|슬리퍼|샌들|부츠|구두|로퍼|스니커|깔창|양말|방석|베개|매트|의자|소파|침대|러그|쿠션커버|커버지|스카프|장갑|모자|가방|지갑|벨트|시계|이어폰|충전|케이블|거치|ソックス|靴下|スニーカー|サンダル|スリッパ|ブーツ|クッションカバー|座布団|まくら|枕|マット|椅子|ソファ|寝具)/i;

const ITEM_MATCH_COLUMN_KEYS: ItemMatchColumnKey[] = ['lip', 'blush', 'eye', 'base', 'nail', 'brow', 'concealer', 'lipbalm'];

/** 지역·구매 플랫폼 선택 드롭다운.
 *
 * 퍼스널컬러 아이템매칭에만 있던 UI라 네일 화면에서는 지역/플랫폼을 바꿀 방법이 없었다
 * (기본값이 라쿠텐 쪽이라 '이 컬러로 살 수 있는 상품'이 라쿠텐만 나왔다 — 사용자 지적).
 * 두 화면이 같은 상태(itemRegion/itemPlatform)를 쓰므로 컴포넌트로 뽑아 공유한다.
 */
function ItemMarketFilter({
  region,
  platform,
  onRegionChange,
  onPlatformChange,
  size = 'small',
}: {
  region: ItemRegion;
  platform: ItemPlatform;
  onRegionChange: (next: ItemRegion) => void;
  onPlatformChange: (next: ItemPlatform) => void;
  size?: 'small' | 'medium';
}) {
  const t = useT();
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
      <FormControl size={size} sx={{ minWidth: 140 }}>
        <InputLabel>{t('지역')}</InputLabel>
        <Select
          label={t('지역')}
          value={region}
          onChange={(event) => onRegionChange(event.target.value as ItemRegion)}
        >
          {ITEM_REGION_FILTERS.map((item) => (
            <MenuItem key={item.value} value={item.value}>{t(item.label)}</MenuItem>
          ))}
        </Select>
      </FormControl>
      <FormControl size={size} sx={{ minWidth: 160 }}>
        <InputLabel>{t('구매 플랫폼')}</InputLabel>
        <Select
          label={t('구매 플랫폼')}
          value={platform}
          onChange={(event) => onPlatformChange(event.target.value as ItemPlatform)}
        >
          {(region === 'jp' ? JP_ITEM_PLATFORM_FILTERS : KR_ITEM_PLATFORM_FILTERS).map((item) => (
            <MenuItem key={item.value} value={item.value}>{t(item.label)}</MenuItem>
          ))}
        </Select>
      </FormControl>
    </Stack>
  );
}

function itemMatchColumnFor(product: RakutenProduct, isMale = false): ItemMatchColumnKey | null {
  // 1순위: 백엔드가 실어 보낸 컬럼 판정. 컬럼 '배분'을 한 주체와 '표시'를 하는 주체가 같은
  // 판정을 쓰게 하려면 이게 유일한 방법이다 — 예전엔 아래 정규식을 TS로 다시 구현해 두고
  // 백엔드만 고치는 일이 반복돼, 배분된 카드가 다른 컬럼에 뜨거나 사라졌다.
  // (아래 폴백은 백엔드가 column 을 안 주는 경우 — 무드 추천 등 구 응답 호환용.)
  const fromBackend = product.column;
  if (fromBackend && (ITEM_MATCH_COLUMN_KEYS as string[]).includes(fromBackend)) {
    return fromBackend as ItemMatchColumnKey;
  }

  // 상품명/키워드로 카테고리를 판별한다. 상품명(name)은 브랜드명 등 노이즈가 섞여
  // 오분류를 유발하므로, DB 상품이 넘겨주는 카테고리 키워드(keyword)를 우선 신뢰한다.
  const primary = (product.keyword || '').toLowerCase();
  const text = [product.keyword, product.name].join(' ').toLowerCase();
  if (NON_COSMETIC_RE.test(text)) return null;  // 신발/양말 등 잡화 제외

  const isBlush = (t: string) => /(blush|blusher|cheek|チーク|블러셔|치크|볼터치)/i.test(t);
  const isEye = (t: string) => /(eye|eyeshadow|shadow|palette|mascara|liner|kajal|アイシャドウ|アイライナー|マスカラ|아이|섀도|쉐도)/i.test(t);
  const isBase = (t: string) => /(base|foundation|cushion|concealer|primer|powder|shading|ファンデーション|コンシーラー|パウダー|파운데이션|쿠션|베이스)/i.test(t);
  const isLip = (t: string) => /(lip|lipstick|tint|rouge|gloss|balm|リップ|ルージュ|ティント|립|틴트)/i.test(t);
  // ⚠ 'nail'/'네일'은 단어 경계로 본다 — 부분문자열이면 'snail'/'스네일'(달팽이 점액)이
  // 걸려 코스알엑스 스네일 뮤신 같은 스킨케어가 네일 컬럼에 꽂힌다(백엔드 _ITEM_CATEGORY_PATTERNS
  // 와 동일 규칙 유지). 'polishing'(각질제거)도 제외.
  const isNail = (t: string) => /(?<![a-z])nail|(?<![a-z])pedi|(?<![a-z])polish(?!ing)|(?<![a-z])lacquer|(?<![a-z])manicure|(?<!ス)ネイル|ペディ|マニキュア|(?<!스)네일|페디|매니큐어/i.test(t);
  // 남성 전용: 브로우/컨실러는 base/eye 보다 먼저 판정(눈썹칼이 eye로, 컨실러가 base로 새지 않게).
  const isBrow = (t: string) => /(brow|eyebrow|アイブロウ|眉|아이브로우|브로우|눈썹)/i.test(t);
  const isConcealer = (t: string) => /(concealer|コンシーラー|컨실러|잡티|다크서클)/i.test(t);
  const isMaleBase = (t: string) => /(base|foundation|cushion|primer|powder|bb|톤업|파운데이션|쿠션|베이스|비비)/i.test(t);

  if (isMale) {
    // 남성 세트: concealer → brow → base → lipbalm(립 전반). 키워드 필드 우선, 없으면 상품명까지.
    for (const t of [primary, text]) {
      if (isConcealer(t)) return 'concealer';
      if (isBrow(t)) return 'brow';
      if (isMaleBase(t)) return 'base';
      if (isLip(t)) return 'lipbalm';
    }
    return null;
  }

  // 여성 세트(기존). 1순위: 카테고리 키워드 필드로 판정.
  if (isNail(primary)) return 'nail';
  if (isBlush(primary)) return 'blush';
  if (isEye(primary)) return 'eye';
  if (isBase(primary)) return 'base';
  if (isLip(primary)) return 'lip';

  // 2순위: 상품명 포함 전체 텍스트로 판정.
  if (isNail(text)) return 'nail';
  if (isBlush(text)) return 'blush';
  if (isEye(text)) return 'eye';
  if (isBase(text)) return 'base';
  if (isLip(text)) return 'lip';

  // 어느 카테고리에도 확실히 맞지 않으면 베이스로 몰지 않고 제외한다.
  return null;
}

function groupItemMatchProducts(products: RakutenProduct[], isMale = false): Record<ItemMatchColumnKey, RakutenProduct[]> {
  return products.reduce<Record<ItemMatchColumnKey, RakutenProduct[]>>(
    (groups, product) => {
      const key = itemMatchColumnFor(product, isMale);
      if (key) groups[key].push(product);
      return groups;
    },
    { lip: [], blush: [], eye: [], base: [], nail: [], brow: [], concealer: [], lipbalm: [] },
  );
}

/** 상품 동일성 키(id 무관). 브랜드+상품명만 본다.
 *
 * 아이템매칭은 2단 로딩(instant 즉답 → full 교체)이라 **같은 상품의 id 가 단계별로 다르다**
 * (즉답은 DB `db-…`, full 은 라이브 `naver-…`/라쿠텐). 예전 담기 키는 id 를 포함해서
 * 교체 순간 체크가 통째로 풀렸다 — 사용자가 "결과지에 담기 5개 실패"로 본 현상. 담은 상품을
 * 이 키로 대조해 단계 교체를 넘어 선택이 유지되게 한다.
 */
function productIdentityKey(product: RakutenProduct): string {
  const norm = (value: string) => value.toLowerCase().replace(/[\s[\]()（）【】/,·・…]+/g, '');
  return `${norm(product.brand || '')}::${norm(product.name || '')}`;
}

/** 웹 계정에 저장된 8종 라벨 → 화면 표기. 백엔드 WEB_LABEL_TO_PROFILE_KEY 와 짝이다. */
const WEB_PERSONAL_COLOR_LABELS: Record<string, string> = {
  spring_bright: '봄 웜 브라이트',
  spring_warm: '봄 웜',
  summer_light: '여름 쿨 라이트',
  summer_mute: '여름 쿨 뮤트',
  autumn_warm: '가을 웜 딥',
  autumn_mute: '가을 웜 뮤트',
  winter_clear: '겨울 쿨 브라이트',
  winter_deep: '겨울 쿨 딥',
};

function displaySeasonLabel(label?: string): string {
  if (!label) return '퍼스널컬러';
  if (/[가-힣]/.test(label)) return label;
  if (/winter|cool-deep|cool-bright/i.test(label)) return '겨울 쿨';
  if (/summer/i.test(label)) return '여름 쿨';
  if (/spring/i.test(label)) return '봄 웜';
  if (/autumn|fall/i.test(label)) return '가을 웜';
  return label;
}

function faceShapeLabel(shape?: string): string {
  if (!shape) return '얼굴형분석전';
  if (/[가-힣]/.test(shape)) return shape;
  const normalized = shape.toLowerCase();
  if (normalized.includes('oval')) return '계란형';
  if (normalized.includes('round')) return '둥근형';
  if (normalized.includes('square')) return '각진형';
  if (normalized.includes('heart')) return '하트형';
  if (normalized.includes('long')) return '긴형';
  return shape;
}

function reportSeasonProfile(result?: PersonalColorResponse | null) {
  const label = result?.label ?? '';
  const seasonText = `${result?.season ?? ''} ${label}`.toLowerCase();
  const detailText = `${result?.tone ?? ''} ${result?.subtype ?? ''} ${label}`.toLowerCase();
  if (/가을|autumn|fall/.test(seasonText) || (!/봄|spring|여름|summer|겨울|winter/.test(seasonText) && /warm.*(mute|deep)|autumn|fall/.test(detailText))) {
    return {
      moodLine: '차분하고 세련된 분위기를 가지고 있어요.',
      tags: ['#차분한', '#고급스러운', '#부드러운'],
      colorLine: '부드럽고 탁도가 살짝 있는 웜 컬러가 잘 어울리며, 베이지와 브라운 계열을 더하면 분위기가 안정적으로 살아나요.',
      finishLine: '따뜻하고 차분한 대비감을 살려 자연스러운 깊이와 분위기를 함께 정리했어요.',
    };
  }
  if (/봄|spring/.test(seasonText) || (!/가을|autumn|fall|여름|summer|겨울|winter/.test(seasonText) && /warm.*(light|bright)|spring/.test(detailText))) {
    return {
      moodLine: '밝고 생기 있는 분위기를 가지고 있어요.',
      tags: ['#맑은', '#상큼한', '#화사한'],
      colorLine: '맑고 따뜻한 코랄, 피치, 라이트 베이지 계열이 잘 어울리며 과하게 탁한 컬러는 덜어내는 편이 좋아요.',
      finishLine: '가볍고 맑은 색감을 중심으로 얼굴의 생기와 투명감을 함께 정리했어요.',
    };
  }
  if (/여름|summer/.test(seasonText) || (!/봄|spring|가을|autumn|fall|겨울|winter/.test(seasonText) && /cool.*(light|mute|soft)|summer|rose|mauve/.test(detailText))) {
    return {
      moodLine: '부드럽고 깨끗한 분위기를 가지고 있어요.',
      tags: ['#청초한', '#은은한', '#소프트한'],
      colorLine: '차분한 로즈, 라벤더, 모브 계열이 잘 어울리며 노란기가 강한 색보다 부드러운 쿨 컬러가 안정적이에요.',
      finishLine: '은은한 쿨 톤을 중심으로 피부의 맑음과 부드러운 인상을 함께 정리했어요.',
    };
  }
  if (/겨울|winter/.test(seasonText) || (!/봄|spring|가을|autumn|fall|여름|summer/.test(seasonText) && /cool.*(deep|clear|strong|bright)|winter/.test(detailText))) {
    return {
      moodLine: '당당하고 또렷한 분위기를 가지고 있어요.',
      tags: ['#선명한', '#존재감있는', '#시크한'],
      colorLine: '선명하고 단정한 차가운 컬러가 잘 어울리며, 대비감 있는 포인트를 더하면 얼굴선과 분위기가 또렷하게 살아나요.',
      finishLine: '맑고 차가운 대비감을 살려 생기와 존재감을 함께 정리했어요.',
    };
  }
  return {
    moodLine: result?.skin_summary ?? '분석 결과에 맞춰 어울리는 분위기를 정리했어요.',
    tags: ['#균형있는', '#자연스러운', '#맞춤형'],
    colorLine: result?.advice?.[0] ?? '분석된 퍼스널컬러에 맞춰 어울리는 컬러와 메이크업 톤을 정리했어요.',
    finishLine: result?.advice?.[1] ?? '사진 분석 결과와 선택한 무드를 함께 반영했어요.',
  };
}

function faceImpressionTag(face?: FaceShapeResponse | null): string {
  const shape = faceShapeLabel(face?.detected ? face.shape : undefined);
  if (/둥근|계란|oval|round/i.test(shape)) return '#부드러운인상';
  if (/하트|heart/i.test(shape)) return '#러블리상';
  if (/각진|square/i.test(shape)) return '#시크한인상';
  if (/긴|long/i.test(shape)) return '#성숙한인상';
  return '#인상분석전';
}

/** 결과지 무드 문구. **조립은 렌더에서** 한다 — 여기서 문자열을 합쳐 버리면 사전(원문=키)이
 *  그 조합을 못 덮어 일본어 모드에서 한국어가 그대로 나온다(실측). composed=true 면
 *  label/description 이 '조각'이고, 렌더가 뒤에 공통 문구를 붙인다. */
function reportMoodCopy(mood: StyleMood): { label: string; description: string; composed: boolean } {
  if (mood.id === 'berry-sorbet') {
    return {
      label: '상큼 베리 소르베 무드 메이크업',
      description: '차가운 베리 소르베처럼 상큼하면서도 도화적인 컬러감이, 강한 대비로 생기를 불어넣는 메이크업이에요.',
      composed: false,
    };
  }
  return { label: mood.label, description: mood.vibe, composed: true };
}

// 퍼스널컬러 색상어(한국어)를 일본 마켓(라쿠텐) 검색어로 번역한다. 한국어 색상어는
// 라쿠텐/아마존에서 0건이 나오므로, 색상 매칭이 실제로 되도록 일본어로 현지화한다.
// (예: "코랄 핑크" → "コーラルピンク"). KR은 네이버가 한국어를 그대로 이해하므로 원문 사용.
const PC_COLOR_ATOMS_JA: Record<string, string> = {
  코랄: 'コーラル', 핑크: 'ピンク', 피치: 'ピーチ', 베이지: 'ベージュ', 브릭: 'ブリック',
  레드: 'レッド', 테라코타: 'テラコッタ', 누드: 'ヌード', 로즈: 'ローズ', 브라운: 'ブラウン',
  쿨: 'クール', 버건디: 'バーガンディ', 체리: 'チェリー', 클리어: 'クリア', 말린: 'ドライ',
  장미: 'ローズ', 모브: 'モーブ', 살구: 'アプリコット', 라이트: 'ライト', 시나몬: 'シナモン',
  웜: 'ウォーム', 소프트: 'ソフト', 라벤더: 'ラベンダー', 맑은: 'クリア', 플럼: 'プラム',
  더스티: 'ダスティ', 샴페인: 'シャンパン', 카멜: 'キャメル', 카키: 'カーキ', 뮤트: 'ミュート',
  올리브: 'オリーブ', 차콜: 'チャコール', 딥: 'ディープ', 네이비: 'ネイビー', 블랙: 'ブラック',
  실버: 'シルバー', 그레이: 'グレー', 아이보리: 'アイボリー', 옐로우: 'イエロー',
  내추럴: 'ナチュラル', 뉴트럴: 'ニュートラル', 샌드: 'サンド', 베이스: 'ベース',
  푸시아: 'フクシア',
  // 결과지 '메이크업 톤'에 실제로 나오는데 빠져 있던 색상어(실측 확인).
  와인: 'ワイン', 페일: 'ペール', 베리: 'ベリー', 라일락: 'ライラック',
};

function localizeColorToJa(koPhrase: string): string {
  return koPhrase
    .split(/\s+/)
    .map((atom) => PC_COLOR_ATOMS_JA[atom] ?? atom)
    .join('');
}

// 제품 종류·성별 등 '색상 외' 단어의 일본어. 색상 사전(PC_COLOR_ATOMS_JA)과 짝을 이룬다.
// 쓰임: ①컬럼 헤더의 추천 색상/문구 ②카드 배지(검색 키워드).
// 배지는 '쿨 아이보리 남성 쿠션 팩트'처럼 색상+카테고리가 섞인 조합이라 사전 하나로는 못 덮고,
// 단어 단위로 갈아끼워야 한다(색상 부분은 위 사전이 담당).
// ⚠ 표시만 번역한다 — 검색에 실제로 쓰는 키워드는 한국어 그대로여야 네이버에서 결과가 나온다.
const PC_TERM_ATOMS_JA: Record<string, string> = {
  남성: 'メンズ', 남자: 'メンズ', 여성: 'レディース',
  쿠션: 'クッション', 팩트: 'パクト', 파운데이션: 'ファンデーション',
  비비크림: 'BBクリーム', 톤업크림: 'トーンアップクリーム', 크림: 'クリーム',
  아이브로우: 'アイブロウ', 눈썹: 'まゆげ', 펜슬: 'ペンシル',
  컨실러: 'コンシーラー', 잡티: 'シミ', 다크서클: 'くま',
  립밤: 'リップバーム', 립: 'リップ', 틴트: 'ティント', 립스틱: 'リップスティック',
  블러셔: 'チーク', 치크: 'チーク',
  아이섀도우: 'アイシャドウ', 섀도우: 'アイシャドウ', 아이: 'アイ',
  젤네일: 'ジェルネイル', 네일: 'ネイル', 페디큐어: 'ペディキュア',
  커버: 'カバー', 메이크업: 'メイク', 코스메틱: 'コスメ',
  // 색상 앞에 붙는 형용사(추천 색상 문구에 자주 나온다).
  생기: '生き生き', 맑은: 'クリア', 은은한: 'ほのか', 부드러운: 'ソフト',
};

/** 색상/카테고리 조합 문구를 일본어로. 사전에 없는 단어는 그대로 둔다(안전 실패).
 *
 * 색상만으로 이뤄진 문구는 붙여 쓰고('말린 장미' → 'ドライローズ'), 카테고리어가 섞이면
 * 띄어 쓴다('쿨 아이보리 남성 쿠션 팩트' → 'クールアイボリー メンズ クッション パクト').
 * 일본어 화장품 표기 관행이 색상은 붙이고 종류는 띄우는 쪽이라 읽기 편하다.
 */
function localizePcPhraseToJa(koPhrase: string): string {
  const atoms = (koPhrase || '').split(/\s+/).filter(Boolean);
  if (!atoms.length) return koPhrase;
  const translate = (atom: string): string => {
    if (PC_COLOR_ATOMS_JA[atom] || PC_TERM_ATOMS_JA[atom]) {
      return PC_COLOR_ATOMS_JA[atom] ?? PC_TERM_ATOMS_JA[atom];
    }
    // '잡티·다크서클' 처럼 가운뎃점으로 묶인 복합어는 쪼개서 각각 번역한다.
    if (atom.includes('·')) {
      return atom
        .split('·')
        .map((part) => PC_COLOR_ATOMS_JA[part] ?? PC_TERM_ATOMS_JA[part] ?? part)
        .join('・');
    }
    return atom;
  };
  const allColors = atoms.every((atom) => PC_COLOR_ATOMS_JA[atom]);
  return atoms.map(translate).join(allColors ? '' : ' ');
}

// 색상어(한국어) → 영어. 네이버에 영어로도 검색하면 수입/럭셔리(샤넬·맥·나스 등)까지
// 함께 잡혀 K뷰티(한국어 검색)와 상호 보완된다.
const PC_COLOR_ATOMS_EN: Record<string, string> = {
  코랄: 'coral', 핑크: 'pink', 피치: 'peach', 베이지: 'beige', 브릭: 'brick',
  레드: 'red', 테라코타: 'terracotta', 누드: 'nude', 로즈: 'rose', 브라운: 'brown',
  쿨: 'cool', 버건디: 'burgundy', 체리: 'cherry', 클리어: 'clear', 말린: 'dried',
  장미: 'rose', 모브: 'mauve', 살구: 'apricot', 라이트: 'light', 시나몬: 'cinnamon',
  웜: 'warm', 소프트: 'soft', 라벤더: 'lavender', 맑은: 'clear', 플럼: 'plum',
  더스티: 'dusty', 샴페인: 'champagne', 카멜: 'camel', 카키: 'khaki', 뮤트: 'muted',
  올리브: 'olive', 차콜: 'charcoal', 딥: 'deep', 네이비: 'navy', 블랙: 'black',
  실버: 'silver', 그레이: 'gray', 아이보리: 'ivory', 옐로우: 'yellow',
  내추럴: 'natural', 뉴트럴: 'neutral', 샌드: 'sand', 베이스: 'base',
  푸시아: 'fuchsia',
};

function localizeColorToEn(koPhrase: string): string {
  return koPhrase
    .split(/\s+/)
    .map((atom) => PC_COLOR_ATOMS_EN[atom] ?? atom)
    .join(' ');
}

export default function App() {
  const { lang: appLang } = useAppLang();
  const t = useT();
  /** 추천 색상·카테고리 문구 표시용 번역. 사전(t)에 있으면 그걸 쓰고, 없으면 단어 단위로 옮긴다.
   *
   * 이 값들은 분석 결과로 조합돼 나오기 때문에(예: '쿨 아이보리', '잡티·다크서클 커버',
   * '말린 장미 립') 문장 단위 사전으로는 다 못 덮는다. 상품명/브랜드는 대상이 아니다. */
  const tPhrase = (value: string): string => {
    const dict = t(value);
    if (dict !== value || appLang !== 'ja') return dict;
    return localizePcPhraseToJa(value);
  };
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const previewUrlsRef = useRef<string[]>([]);
  const personalColorPreviewsRef = useRef<string[]>([]);
  const [appModule, setAppModule] = useState<AppModule>('home');
  // ── 웹 계정 연동 ─────────────────────────────────────────────────────────────
  // 부팅 순서: #t= 티켓 교환 → 저장된 세션 확인 → 둘 다 없으면 비로그인.
  // 세션은 AI 가 자체 발급한 토큰(기본 12시간)이라 새로고침해도 유지된다.
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authConfig, setAuthConfig] = useState<AuthConfigResponse | null>(null);
  const [authBooting, setAuthBooting] = useState(true);
  const [authError, setAuthError] = useState('');
  const [virtualSurgeryTuning, setVirtualSurgeryTuning] = useState<VirtualSurgeryTuning>({
    faceLine: 42,
    jawBalance: 28,
    noseContour: 34,
    blemishCare: 56,
  });
  const [virtualSurgeryFile, setVirtualSurgeryFile] = useState<File | null>(null);
  const [virtualSurgeryPreview, setVirtualSurgeryPreview] = useState('');
  const [virtualSurgeryResult, setVirtualSurgeryResult] = useState<VirtualSurgeryResponse | null>(null);
  const [virtualSurgeryLoading, setVirtualSurgeryLoading] = useState(false);
  const [virtualSurgeryDragOver, setVirtualSurgeryDragOver] = useState(false);
  const [virtualSurgeryStep, setVirtualSurgeryStep] = useState(0);
  // 부위·변화 이미지는 **복수 선택**이고 배열 순서가 곧 우선순위다(첫 항목이 1순위).
  // 예전엔 문자열 하나라 새로 누르면 이전 선택이 사라졌고, 그 값이 백엔드로 가지도 않아
  // 사용자가 무엇을 골라도 추천이 똑같았다(사용자 지적 2026-08-03).
  const [virtualSurgeryProfile, setVirtualSurgeryProfile] = useState<{
    gender: string;
    ageGroup: string;
    concerns: string[];
    desiredMoods: string[];
    privacyConsent: boolean;
  }>({
    gender: 'female',
    ageGroup: '20s',
    concerns: ['윤곽·얼굴형'],
    desiredMoods: ['자연스러운 변화'],
    privacyConsent: false,
  });
  /** 선택 토글. 이미 있으면 빼고, 없으면 뒤에 붙인다(=나중에 고를수록 후순위). */
  const toggleSurgeryChoice = (key: 'concerns' | 'desiredMoods', option: string, max: number) =>
    setVirtualSurgeryProfile((prev) => {
      const current = prev[key];
      if (current.includes(option)) return { ...prev, [key]: current.filter((v) => v !== option) };
      // 상한을 넘으면 **추가하지 않는다**. 오래된 걸 조용히 버리면 1순위가 뒤바뀐다.
      if (current.length >= max) return prev;
      return { ...prev, [key]: [...current, option] };
    });
  const [virtualSurgeryTarget, setVirtualSurgeryTarget] = useState('oval');
  // 카드별 '내 얼굴 적용' 미리보기. 예전 카드는 일러스트라 고르고 나서야 결과를 봤다.
  const [surgeryCards, setSurgeryCards] = useState<VirtualSurgeryPreviewCard[]>([]);
  const [surgeryCardsLoading, setSurgeryCardsLoading] = useState(false);
  // 변화 강도 — 슬라이더 %(의학적 의미 없는 워프 강도)를 대신한다.
  const [surgeryIntensity, setSurgeryIntensity] = useState<VirtualSurgeryIntensity>('balanced');
  // ⚠ 이 훅은 **컴포넌트 최상위**에 있어야 한다. 처음에 renderVirtualSurgeryFlowPage() 안에
  //   넣었다가 화면이 통째로 빈 채로 떴다 — 그 함수는 조건부로 호출돼서 훅 호출 순서가
  //   렌더마다 달라지고, React 가 즉시 throw 한다(Rules of Hooks). 실측으로 잡았다.
  //   카드 화면(3단계)에 들어오면 미리보기를 한 번 받아온다. 강도 버튼이 다시 부른다.
  useEffect(() => {
    if (virtualSurgeryStep === 3 && virtualSurgeryFile && !surgeryCards.length && !surgeryCardsLoading) {
      void loadSurgeryCards(surgeryIntensity);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [virtualSurgeryStep, virtualSurgeryFile]);
  // 네일 디자인 분석(리트리벌). 인덱스·모델이 배포에 없으면 결과의 feature_available 이 false 로 온다.
  const [nailPreview, setNailPreview] = useState<string>('');
  const [nailDragOver, setNailDragOver] = useState(false);
  const [nailCameraOn, setNailCameraOn] = useState(false);
  const [nailShade, setNailShade] = useState<NailShade | null>(null);
  const [nailTryOn, setNailTryOn] = useState<string>('');
  const [nailProducts, setNailProducts] = useState<RakutenProduct[]>([]);
  const [nailProductsLoading, setNailProductsLoading] = useState(false);
  const [nailResult, setNailResult] = useState<AnalyzeNailDesignResponse | null>(null);
  const [nailLoading, setNailLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>('face');
  const [survey, setSurvey] = useState<SurveyInput>({
    gender: 'female',
    age: '',
    age_group: '20s',
    race_identity: '',
    privacy_consent: false,
    skin_type: 'combination',
    concerns: [],
    makeup_concerns: [],
    area_concerns: [],
    male_extras: [],
    sensitivity: 3,
    routine_level: 'basic',
  });
  const [faceFiles, setFaceFiles] = useState<File[]>([]);
  const [previewUrls, setPreviewUrls] = useState<string[]>([]);
  const [personalColorFiles, setPersonalColorFiles] = useState<File[]>([]);
  const [personalColorPreviews, setPersonalColorPreviews] = useState<string[]>([]);
  const [personalColorIndex, setPersonalColorIndex] = useState(0);
  const [personalColorResult, setPersonalColorResult] = useState<PersonalColorResponse | null>(null);
  const [faceShape, setFaceShape] = useState<FaceShapeResponse | null>(null);
  const [personalColorStep, setPersonalColorStep] = useState(0);
  const [personalColorItems, setPersonalColorItems] = useState<PersonalColorItemMatchResponse | null>(null);
  // 아이템매칭 조회 순번. 지역/플랫폼/무드를 바꾸면 새 요청이 나가는데 응답이 4~8초 걸려서,
  // **먼저 보낸 요청이 늦게 도착해 새 결과를 덮어쓰는** 경쟁 상태가 있었다. 그러면 화면엔
  // 이전 조건(예: 모든 플랫폼)의 카드가 남은 채 새 필터(올리브영)만 적용돼, 구매 버튼이
  // 사라진 '죽은 카드'처럼 보인다(실측). 최신 요청의 응답만 반영한다.
  const itemMatchRequestId = useRef(0);
  const [selectedMood, setSelectedMood] = useState<string | null>(null);
  const [moodItems, setMoodItems] = useState<PersonalColorItemMatchResponse | null>(null);
  const [moodThumbnails, setMoodThumbnails] = useState<Record<string, string>>({});
  const [moodThumbsLoading, setMoodThumbsLoading] = useState(false);
  // 내 사진에 무드 적용 — 퍼스널컬러 분석에 쓴 사진을 그대로 재사용해 다시 올리지 않게 한다.
  const [myFaceMakeup, setMyFaceMakeup] = useState<{ mood: string; image: string } | null>(null);
  const [myFaceLoading, setMyFaceLoading] = useState(false);
  const [myFaceError, setMyFaceError] = useState('');
  const [itemRegion, setItemRegion] = useState<ItemRegion>(() => detectInitialRegion());
  const [itemPlatform, setItemPlatform] = useState<ItemPlatform>('all');
  // 결과지에 담은 상품을 **객체로** 들고 있는다(키 목록이 아니라).
  // 키(id 포함) 목록으로 들고 있으면 instant→full 교체 때 id 가 바뀌어 선택이 통째로 풀렸다.
  // 아래 useEffect 가 새 응답에서 같은 상품(브랜드+상품명)을 찾아 최신 인스턴스로 갱신한다
  // (검증된 링크·이미지를 반영하려면 최신 쪽이 정확하다).
  const [reportPicks, setReportPicks] = useState<RakutenProduct[]>([]);
  // 퍼스널컬러 결과지에서 여는 LLM 상담 패널. 결과지를 본 직후 질문하는 흐름이라 같은 화면에 편다.
  const [pcConsultOpen, setPcConsultOpen] = useState(false);
  // 피부 케어 결과지에 담을 상품(최대 4개). 퍼스널컬러와 상품 타입이 달라 상태를 따로 둔다.
  const [skinReportIds, setSkinReportIds] = useState<number[]>([]);
  // 카메라 실패는 '차단 오류'가 아니다 — 파일 업로드로 계속 진행할 수 있다.
  // 그래서 페이지 상단 빨간 Alert(error)가 아니라 촬영 영역 옆 안내로만 띄운다.
  const [cameraNotice, setCameraNotice] = useState('');
  const [personalColorProfile, setPersonalColorProfile] = useState({
    age: '',
    gender: 'female',
    raceIdentity: '',
    consent: false,
  });
  const [cameraDevices, setCameraDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [cameraReady, setCameraReady] = useState(false);
  const [analysis, setAnalysis] = useState<AnalyzeSkinResponse | null>(null);
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [skinRegion, setSkinRegion] = useState<ItemRegion>(() => detectInitialRegion());
  const [selectedPlatform, setSelectedPlatform] = useState<ItemPlatform>('all');
  const [message, setMessage] = useState('제 피부 상태에 맞는 루틴을 어떻게 구성하면 좋을까요?');
  const [answer, setAnswer] = useState('');
  const [answerSources, setAnswerSources] = useState<string[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState('');
  const [error, setError] = useState('');
  const styleMoodRecommendations = useMemo(
    () => recommendStyleMoods(personalColorResult, faceShape),
    [personalColorResult, faceShape],
  );

  // 퍼스널컬러 다중 사진: files/previews는 인덱스로 정렬되며, 화살표로 순회한다.
  // 현재 인덱스를 벗어나지 않도록 정규화한 '현재 사진/미리보기'를 파생값으로 노출한다.
  const personalColorCount = personalColorFiles.length;
  const safePersonalColorIndex =
    personalColorCount === 0 ? 0 : Math.min(personalColorIndex, personalColorCount - 1);
  const personalColorFile = personalColorFiles[safePersonalColorIndex] ?? null;
  const personalColorPreview = personalColorPreviews[safePersonalColorIndex] ?? '';

  const highestReadyStep = useMemo(() => {
    if (answer) return 4;
    if (recommendation) return 3;
    if (analysis) return 2;
    if (faceFiles.length) return 1;
    return 0;
  }, [answer, recommendation, analysis, faceFiles.length]);

  // 계정 연동 부팅. 웹에서 넘어왔으면 티켓을 세션으로 바꾸고, 아니면 저장된 세션을 확인한다.
  //
  // ⚠ 여기에 취소 플래그(cleanup 에서 cancelled=true)를 두면 안 된다. StrictMode 는
  //   mount → cleanup → mount 로 이펙트를 두 번 돌리는데, 아래 ref 가드 때문에 두 번째가
  //   즉시 반환되므로 **첫 번째 실행의 cancelled 만 true 로 남는다.** 그러면 await 뒤의
  //   setAuthBooting(false) 가 영원히 안 불려 로딩 막대에서 멈춘다(실측: 티켓을 달고 들어온
  //   경우에만 재현 — 티켓이 없으면 await 없이 동기 완료라 멀쩡해 보인다).
  //   루트 컴포넌트라 언마운트되지 않으므로 취소 자체가 필요 없다.
  const authBootRef = useRef(false);
  useEffect(() => {
    if (authBootRef.current) return;
    authBootRef.current = true;
    void (async () => {
      // 게이트 문구·링크에 쓸 설정. 실패해도 앱은 뜬다(로그인 강제만 못 한다).
      fetchAuthConfig().then(setAuthConfig).catch(() => undefined);
      const ticket = takeHandoffTicket();
      try {
        if (ticket) {
          setAuthUser((await exchangeTicket(ticket)).user);
        } else if (getSessionToken()) {
          setAuthUser(await fetchMe());
        }
      } catch {
        // 만료·재사용된 티켓이나 죽은 세션. 토큰을 지워 다음 진입이 깨끗하게 시작되게 한다.
        setSessionToken(null);
        setAuthUser(null);
        setAuthError(ticket ? '연동에 실패했습니다. 웹에서 다시 시도해주세요.' : '');
      } finally {
        setAuthBooting(false);
      }
    })();
  }, []);

  useEffect(() => {
    // 세션이 붙은 뒤에 다시 부른다 — 비로그인 때 받은 이력은 남의 것이 섞인 전체 목록이다.
    if (authBooting) return;
    getHistory().then(setHistory).catch(() => undefined);
  }, [recommendation, authBooting, authUser?.id]);

  // 웹 마이페이지에 저장한 값으로 설문을 미리 채운다. 값이 없는 항목은 손대지 않아
  // 기본값(또는 사용자가 이미 고른 값)이 남는다 — 화면에서 언제든 바꿀 수 있다.
  useEffect(() => {
    if (!authUser) return;
    setSurvey((current) => ({
      ...current,
      gender: authUser.gender ?? current.gender,
      age_group: authUser.age_group ?? current.age_group,
      skin_type: authUser.skin_type ?? current.skin_type,
    }));
    setPersonalColorProfile((current) => ({
      ...current,
      gender: authUser.gender ?? current.gender,
    }));
  }, [authUser?.id, authUser?.gender, authUser?.age_group, authUser?.skin_type]);

  useEffect(() => {
    return () => {
      stopCamera();
    };
  }, []);

  useEffect(() => {
    if (currentStep !== 1) return;

    if (streamRef.current) {
      attachCameraStream();
      return;
    }

    startCamera().catch(() => {
      setCameraNotice('카메라를 쓸 수 없어요. 아래에서 사진을 선택해 진행할 수 있습니다.');
    });
  }, [currentStep]);

  useEffect(() => {
    return () => {
      previewUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
      personalColorPreviewsRef.current.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);

  useEffect(() => {
    previewUrlsRef.current = previewUrls;
  }, [previewUrls]);

  useEffect(() => {
    personalColorPreviewsRef.current = personalColorPreviews;
  }, [personalColorPreviews]);

  // 아이템매칭 응답이 갱신되면(즉답 → full 교체, 재조회) 담아둔 상품을 최신 인스턴스로 바꿔둔다.
  // 담기 상태는 객체로 들고 있어 교체 자체로 사라지진 않지만, 최신 응답 쪽이 검증된 구매 링크와
  // 살아있는 이미지를 갖고 있어 결과지·장바구니 QR 이 정확해진다. 최신 목록에 없는 상품은
  // 사용자가 고른 그대로 남긴다(선택을 임의로 지우지 않는다).
  useEffect(() => {
    const latest = [...(personalColorItems?.products ?? []), ...(moodItems?.products ?? [])];
    if (!latest.length) return;
    setReportPicks((current) => {
      let changed = false;
      const next = current.map((pick) => {
        const fresh = latest.find((product) => productIdentityKey(product) === productIdentityKey(pick));
        if (fresh && fresh !== pick) {
          changed = true;
          return fresh;
        }
        return pick;
      });
      return changed ? next : current;
    });
  }, [personalColorItems, moodItems]);

  useEffect(() => {
    if (appModule !== 'personal-color' || personalColorStep !== 4 || !personalColorResult) return;
    // Step 4 아이템 매칭은 무드가 아니라 '얼굴분석(퍼스널컬러)' 기반으로 추천한다.
    if (personalColorItems) return;
    loadPersonalColorItems();
  }, [appModule, personalColorStep, personalColorResult, personalColorItems, selectedMood, itemRegion, itemPlatform]);

  useEffect(() => {
    if (appModule !== 'personal-color' || personalColorStep !== 4 || !selectedMood) return;
    if (moodItems || loading === 'style-mood-items') return;
    const activeMood = STYLE_MOODS.find((mood) => mood.id === selectedMood);
    if (activeMood) selectStyleMood(activeMood);
  }, [appModule, personalColorStep, selectedMood, moodItems, loading, itemRegion, itemPlatform]);

  useEffect(() => {
    if (appModule !== 'personal-color' || personalColorStep !== 3) return;
    if (Object.keys(moodThumbnails).length || moodThumbsLoading) return;
    setMoodThumbsLoading(true);
    getMoodThumbnails()
      .then((res) => setMoodThumbnails(res.thumbnails))
      .catch(() => undefined)
      .finally(() => setMoodThumbsLoading(false));
  }, [appModule, personalColorStep, moodThumbnails, moodThumbsLoading]);

  useEffect(() => {
    if (appModule !== 'personal-color' || personalColorStep !== 3) return;
    if (selectedMood || loading === 'style-mood-items') return;
    const firstRecommendation = styleMoodRecommendations[0]?.mood;
    if (firstRecommendation) selectStyleMood(firstRecommendation);
  }, [appModule, personalColorStep, selectedMood, loading, styleMoodRecommendations]);

  async function refreshCameraDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    const devices = await navigator.mediaDevices.enumerateDevices();
    const videoDevices = devices.filter((device) => device.kind === 'videoinput');
    setCameraDevices(videoDevices);
    if (!selectedDeviceId && videoDevices[0]?.deviceId) {
      setSelectedDeviceId(videoDevices[0].deviceId);
    }
  }

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setCameraReady(false);
  }

  async function attachCameraStream() {
    if (!videoRef.current || !streamRef.current) return;
    const video = videoRef.current;
    video.srcObject = streamRef.current;
    video.muted = true;
    video.playsInline = true;
    await video.play();
    setCameraReady(true);
  }

  // facing: 얼굴 촬영은 전면('user'), 네일은 손·발을 찍으므로 후면('environment')이 자연스럽다.
  async function startCamera(deviceId = selectedDeviceId, facing: 'user' | 'environment' = 'user') {
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('이 브라우저는 카메라 촬영을 지원하지 않습니다.');
      return;
    }

    stopCamera();
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        deviceId: deviceId ? { exact: deviceId } : undefined,
        facingMode: deviceId ? undefined : facing,
        width: { ideal: 1280 },
        height: { ideal: 720 },
      },
      audio: false,
    });
    streamRef.current = stream;
    await attachCameraStream();
    await refreshCameraDevices();
  }

  async function handleCameraChange(deviceId: string) {
    setSelectedDeviceId(deviceId);
    await startCamera(deviceId);
  }

  function resetResults() {
    setAnalysis(null);
    setRecommendation(null);
    setAnswer('');
    setAnswerSources([]);
  }

  function startSkinCareAnalysis() {
    setAppModule('skin-care');
    setCurrentStep(0);
    setError('');
  }

  function startPersonalColorAnalysis() {
    stopCamera();
    setAppModule('personal-color');
    setPersonalColorStep(0);
    setError('');
  }

  function startNailDesign() {
    stopCamera();
    setAppModule('nail-design');
    setNailResult(null);
    setNailPreview('');
    setError('');
  }

  function startVirtualSurgery() {
    stopCamera();
    setAppModule('virtual-surgery');
    setVirtualSurgeryStep(0);
    setError('');
  }

  async function handleVirtualSurgeryUpload(file: File) {
    if (!file.type.startsWith('image/')) {
      setError('가상 성형 추천에 사용할 얼굴 사진을 선택해 주세요.');
      return;
    }
    setVirtualSurgeryFile(file);
    setVirtualSurgeryPreview(URL.createObjectURL(file));
    setVirtualSurgeryResult(null);
    setVirtualSurgeryLoading(true);
    setError('');
    try {
      const result = await simulateVirtualSurgery(file, virtualSurgeryTuning, virtualSurgeryProfile);
      setVirtualSurgeryResult(result);
      if (result.detected) setVirtualSurgeryStep((step) => Math.max(step, 2));
      if (!result.detected) setError(result.message);
    } catch {
      setError('가상 성형 추천을 생성하지 못했습니다. 정면 얼굴 사진과 밝은 조명의 이미지를 다시 선택해 주세요.');
    } finally {
      setVirtualSurgeryLoading(false);
    }
  }

  /** 카드 4장의 '내 얼굴 적용' 미리보기를 받아온다. 서버가 얼굴 탐지를 1회만 하므로 빠르다. */
  async function loadSurgeryCards(intensity: VirtualSurgeryIntensity) {
    if (!virtualSurgeryFile) return;
    setSurgeryCardsLoading(true);
    try {
      const res = await previewVirtualSurgeryCards(virtualSurgeryFile, intensity);
      setSurgeryCards(res.detected ? res.cards : []);
    } catch {
      // 미리보기는 보조 정보다 — 실패해도 카드 선택 자체는 계속할 수 있어야 한다.
      setSurgeryCards([]);
    } finally {
      setSurgeryCardsLoading(false);
    }
  }

  async function rerunVirtualSurgery() {
    if (!virtualSurgeryFile) {
      setError('가상 성형 추천에 사용할 얼굴 사진을 먼저 선택해 주세요.');
      return;
    }
    setVirtualSurgeryLoading(true);
    setError('');
    try {
      const result = await simulateVirtualSurgery(virtualSurgeryFile, virtualSurgeryTuning, virtualSurgeryProfile);
      setVirtualSurgeryResult(result);
      if (result.detected) setVirtualSurgeryStep((step) => Math.max(step, 2));
      if (!result.detected) setError(result.message);
    } catch {
      setError('가상 성형 추천을 다시 생성하지 못했습니다.');
    } finally {
      setVirtualSurgeryLoading(false);
    }
  }

  async function handleNailUpload(file: File) {
    setNailLoading(true);
    setError('');
    setNailResult(null);
    const previewUrl = URL.createObjectURL(file);
    setNailPreview(previewUrl);
    try {
      const result = await analyzeNailDesign(file, 5);
      setNailResult(result);
      // 예전엔 스와치를 눌러야만 미리보기·상품이 떴다 — 결과 화면이 비어 보였다(사용자 지적).
      // 분석 직후 1순위 추천 색을 자동 적용해 바로 보이게 한다.
      const top = result.recommended_palette?.[0];
      if (top) void applyNailShade(top, result.detected, previewUrl);
    } catch {
      setError('네일 사진을 분석하지 못했습니다. 다른 사진으로 다시 시도해 주세요.');
    } finally {
      setNailLoading(false);
    }
  }

  function goHome() {
    stopCamera();
    setAppModule('home');
    setCurrentStep(0);
    setError('');
  }

  const PERSONAL_COLOR_MAX = 5;

  function clearPersonalColorResults() {
    setPersonalColorResult(null);
    setPersonalColorItems(null);
    setSelectedMood(null);
    setMoodItems(null);
    setFaceShape(null);
    // 담아둔 상품도 함께 비운다. 안 그러면 앞선 진단(예: 여성)에서 담은 상품이 남아,
    // 다음 진단(남성) 결과지에 그대로 실린다 — 컬럼 구성이 아예 다른데도.
    setReportPicks([]);
  }

  function handlePersonalColorUpload(files: FileList | null) {
    // 여러 장 허용(누적): 이미 담긴 사진에 새로 고른 사진을 이어 붙인다. 최대 5장.
    // 현재 보고 있는 사진(화살표 순회)이 얼굴형 분석·미리보기 기준이 된다.
    const images = Array.from(files ?? []).filter((item) => item.type.startsWith('image/'));
    if (images.length === 0) {
      setError('퍼스널컬러 분석에 사용할 얼굴 사진을 선택해 주세요.');
      return;
    }
    const availableSlots = PERSONAL_COLOR_MAX - personalColorFiles.length;
    if (availableSlots <= 0) {
      setError(`퍼스널컬러 사진은 최대 ${PERSONAL_COLOR_MAX}장까지 선택할 수 있습니다.`);
      return;
    }
    const filesToAdd = images.slice(0, availableSlots);
    setError(
      images.length > availableSlots
        ? `퍼스널컬러 사진은 최대 ${PERSONAL_COLOR_MAX}장까지 선택할 수 있어 일부만 추가했습니다.`
        : '',
    );
    setPersonalColorFiles((current) => [...current, ...filesToAdd]);
    setPersonalColorPreviews((current) => [...current, ...filesToAdd.map((item) => URL.createObjectURL(item))]);
    setPersonalColorIndex(personalColorFiles.length); // 새로 추가한 첫 장을 보여준다.
    clearPersonalColorResults();
  }

  function removePersonalColorFile(index: number) {
    URL.revokeObjectURL(personalColorPreviews[index]);
    setPersonalColorFiles((current) => current.filter((_, itemIndex) => itemIndex !== index));
    setPersonalColorPreviews((current) => current.filter((_, itemIndex) => itemIndex !== index));
    setPersonalColorIndex((current) => (current > index ? current - 1 : current));
    clearPersonalColorResults();
  }

  function clearPersonalColorFiles() {
    personalColorPreviews.forEach((url) => URL.revokeObjectURL(url));
    setPersonalColorFiles([]);
    setPersonalColorPreviews([]);
    setPersonalColorIndex(0);
    clearPersonalColorResults();
    setError('');
  }

  function stepPersonalColorImage(delta: number) {
    if (personalColorCount === 0) return;
    setPersonalColorIndex((current) => (current + delta + personalColorCount) % personalColorCount);
  }

  /** 웹 계정에 저장된 퍼스널 컬러로 결과지를 바로 만든다 — 사진 촬영을 건너뛴다.
   *
   * 아티스트에게 진단받았거나 이미 자기 톤을 아는 사람에게 다시 찍으라고 하지 않기 위한
   * 경로다. 결과 모양이 분석 결과와 같아서 이후 아이템매칭·무드 흐름이 그대로 이어진다. */
  // ⚠ 이름을 use... 로 두면 안 된다. 훅이 아닌데 ESLint(react-hooks)도 사람도 훅으로 읽어
  //   '콜백 안에서 훅 호출' 오류가 난다. 실제로 그 경고가 떠서 바꿨다(2026-08-03).
  async function applySavedPersonalColor() {
    const label = authUser?.personal_color;
    if (!label) return;
    setLoading('personal-color');
    setError('');
    setPersonalColorItems(null);
    setSelectedMood(null);
    setMoodItems(null);
    // 사진을 안 받았으므로 얼굴형 분석은 없다(무드 추천은 퍼스널컬러만으로도 동작한다).
    setFaceShape(null);
    try {
      setPersonalColorResult(await fetchDeclaredPersonalColor(label));
      // 단계를 넘기지 않는다 — 다음 단계(얼굴형)는 사진이 있어야 하고, 결과 패널은 이 단계에 있다.
    } catch {
      setError('저장된 퍼스널 컬러를 불러오지 못했습니다. 사진으로 분석해 주세요.');
    } finally {
      setLoading('');
    }
  }

  async function handlePersonalColorAnalyze() {
    if (!personalColorFile) {
      setError('퍼스널컬러 분석에 사용할 얼굴 사진을 먼저 선택해 주세요.');
      return;
    }
    setLoading('personal-color');
    setError('');
    setPersonalColorItems(null);
    setSelectedMood(null);
    setMoodItems(null);
    setFaceShape(null);

    // 같은 사진으로 얼굴형 분석을 병렬 실행한다(실패해도 퍼스널컬러 결과는 유지).
    analyzeFaceShape(personalColorFile)
      .then((result) => setFaceShape(result))
      .catch(() => setFaceShape(null));

    try {
      const files = personalColorFiles.length > 0 ? personalColorFiles : [personalColorFile];
      setPersonalColorResult(await analyzePersonalColor(files));
    } catch {
      setError('퍼스널컬러 분석에 실패했습니다. 정면 얼굴 사진과 조명이 충분한 이미지를 다시 선택해 주세요.');
    } finally {
      setLoading('');
    }
  }

  function personalColorItemKeywords(region: ItemRegion = itemRegion) {
    if (!personalColorResult) return [];
    const makeup = personalColorResult.makeup;

    // 남성(Level 2): 색조(블러셔/아이/네일) 대신 베이스/브로우/컨실러/립밤 그루밍 중심으로 검색.
    // 퍼스널컬러(톤)는 베이스·브로우·립밤 색상 힌트로만 반영한다(색조 제품은 검색하지 않음).
    if (personalColorProfile.gender === 'male') {
      const warm = /웜|warm|가을|봄|autumn|spring/i.test(`${personalColorResult.tone} ${personalColorResult.label}`);
      const browTone = warm ? '소프트 브라운' : '그레이 브라운';
      const baseColor = makeup.base?.[0] ?? '';
      const lipColor = makeup.lip?.[0] ?? '';
      if (region === 'jp') {
        return [
          'メンズ クッション', 'メンズ BBクリーム', 'メンズ 化粧下地',
          'メンズ アイブロウ', 'メンズ 眉ペンシル',
          'メンズ コンシーラー',
          'メンズ リップバーム', 'メンズ リップ',
        ].slice(0, 16);
      }
      return [
        // 베이스: 화장품 특화어로(‘남자 쿠션’ 단독은 쿠션 신발/양말을 물어와 제외).
        '남성 쿠션 팩트', '남성 비비크림', '남성 톤업크림', '남성 파운데이션',
        ...(baseColor ? [`${baseColor} 남성 쿠션 팩트`] : []),
        // 브로우: 남성 아이브로우 (+ 톤에 맞는 브로우 컬러)
        '남자 아이브로우', '남성 눈썹 펜슬', `${browTone} 아이브로우`,
        // 컨실러: 잡티/다크서클
        '남자 컨실러', '남성 잡티 컨실러',
        // 립밤: 자연 립밤/틴트 (+ 톤 힌트)
        '남자 립밤', '남성 틴트 립밤',
        ...(lipColor ? [`${lipColor} 립밤`] : []),
      ].slice(0, 16);
    }

    if (region === 'jp') {
      // JP: 라쿠텐 = 일본어 색상어 + 일본어 카테고리어.
      // 네일은 실제 검색어인 'ジェルネイル'(젤네일)로, 립·블러셔와 달리 전 색상을 검색한다(색이 다 동등하게 중요).
      const cat = { lip: 'リップ', blush: 'チーク', eye: 'アイシャドウ', base: 'ファンデーション', nail: 'ジェルネイル' } as const;
      const build = (values: string[], key: keyof typeof cat) =>
        values.map((item) => `${localizeColorToJa(item)} ${cat[key]}`);
      return [
        ...build(makeup.lip, 'lip'),
        ...build(makeup.blush, 'blush'),
        ...build(makeup.eye, 'eye'),
        ...build(makeup.base, 'base'),
        ...build(makeup.nail ?? [], 'nail'),
      ].slice(0, 16);
    }
    // KR: 네이버에 한국어(K뷰티)와 영어(수입/럭셔리)를 함께 검색해 커버리지를 넓힌다.
    // 네일 카테고리는 한국인 실제 검색어인 '젤네일'을 쓴다.
    const koCat = { lip: '립', blush: '블러셔', eye: '아이섀도우', base: '파운데이션', nail: '젤네일' } as const;
    const enCat = { lip: 'lipstick', blush: 'blush', eye: 'eyeshadow', base: 'foundation', nail: 'nail polish' } as const;
    const bilingual = (values: string[], key: keyof typeof koCat) =>
      values[0] ? [`${values[0]} ${koCat[key]}`, `${localizeColorToEn(values[0])} ${enCat[key]}`] : [];
    // 네일은 대표색 하나가 아니라 시즌 팔레트 전 색을 검색한다(립/블러셔는 대표색 1개로 충분하지만
    // 네일은 3색이 다 동등하게 쓰여, 네이버 커버리지를 색 수만큼 넓힌다).
    const bilingualAll = (values: string[], key: keyof typeof koCat) =>
      values.flatMap((value) => [`${value} ${koCat[key]}`, `${localizeColorToEn(value)} ${enCat[key]}`]);
    return [
      ...bilingual(makeup.lip, 'lip'),
      ...bilingual(makeup.blush, 'blush'),
      ...bilingual(makeup.eye, 'eye'),
      ...bilingual(makeup.base, 'base'),
      ...bilingualAll(makeup.nail ?? [], 'nail'),
    ].slice(0, 16);
  }

  function combinedPersonalColorMoodKeywords(mood: StyleMood, region: ItemRegion = itemRegion) {
    const toneKeywords = personalColorItemKeywords(region);
    const moodKeywords = region === 'jp' ? mood.keywords.jp : mood.keywords.kr;
    const profileKeywords = personalColorResult
      ? region === 'jp'
        ? [
            `${personalColorResult.label} コスメ`,
            `${personalColorResult.tone} ${personalColorResult.subtype} メイク`,
          ]
        : [
            `${personalColorResult.label} 코스메틱`,
            `${personalColorResult.tone} ${personalColorResult.subtype} 메이크업`,
          ]
      : [];
    return Array.from(new Set([...toneKeywords, ...moodKeywords, ...profileKeywords])).slice(0, 14);
  }

  async function loadPersonalColorItems(region: ItemRegion = itemRegion, platform: ItemPlatform = itemPlatform) {
    const keywords = personalColorItemKeywords(region);
    if (!keywords.length) return;
    const requestId = ++itemMatchRequestId.current;
    const isStale = () => itemMatchRequestId.current !== requestId;
    const gender = personalColorProfile.gender === 'male' ? 'male' : 'female';
    setLoading('personal-color-items');
    // 2단계 로딩: 로컬 카탈로그만으로 만든 즉답을 먼저 그려 빈 화면 시간을 줄이고,
    // 라이브 검색까지 끝난 full 결과가 오면 통째로 교체한다. 즉답이 실패하거나 늦으면
    // 그냥 건너뛴다(아래 full 이 정답이므로 즉답은 어디까지나 보조).
    matchPersonalColorItems(keywords, region, platform, gender, 'instant')
      .then((preview) => {
        // full 이 이미 도착했으면(partial=false 로 채워졌으면) 덮어쓰지 않는다.
        if (isStale() || !preview.products.length) return;
        setPersonalColorItems((current) => (current && !current.partial ? current : preview));
      })
      .catch(() => undefined);
    try {
      const data = await matchPersonalColorItems(keywords, region, platform, gender);
      if (isStale()) return;  // 더 새 요청이 나갔다 — 이 응답은 버린다.
      setPersonalColorItems(data);
    } catch {
      if (isStale()) return;
      setPersonalColorItems({
        provider: 'recommender',
        configured: true,
        products: [],
        message: '상품 추천 검색에 실패했습니다.',
      });
    } finally {
      // 늦게 끝난 옛 요청이 '로딩 중'을 꺼서 새 요청의 진행 표시를 지우면 안 된다.
      if (!isStale()) setLoading('');
    }
  }

  async function selectStyleMood(mood: StyleMood, region: ItemRegion = itemRegion, platform: ItemPlatform = itemPlatform) {
    setSelectedMood(mood.id);
    setMoodItems(null);
    // 무드 조회도 같은 순번을 쓴다 — 화면엔 둘 중 하나만 보이므로, 새 조회가 시작되면
    // 종류와 무관하게 이전 응답은 버려야 한다.
    const requestId = ++itemMatchRequestId.current;
    const isStale = () => itemMatchRequestId.current !== requestId;
    setLoading('style-mood-items');
    try {
      const data = await matchPersonalColorItems(combinedPersonalColorMoodKeywords(mood, region), region, platform, personalColorProfile.gender === 'male' ? 'male' : 'female');
      if (isStale()) return;
      setMoodItems(data);
    } catch {
      if (isStale()) return;
      setMoodItems({
        provider: 'recommender',
        configured: true,
        products: [],
        message: '상품 추천 검색에 실패했습니다.',
      });
    } finally {
      if (!isStale()) setLoading('');
    }
  }

  async function applyMoodToMyFace(moodId: string) {
    // 이미 내 사진이 떠 있으면 토글로 모델 사진으로 되돌린다.
    if (myFaceMakeup?.mood === moodId) {
      setMyFaceMakeup(null);
      return;
    }
    if (!personalColorFile) return;
    setMyFaceLoading(true);
    setMyFaceError('');
    try {
      const result = await previewMakeupOnPhoto(
        personalColorFile,
        moodId,
        personalColorProfile.gender === 'male' ? 'male' : 'female',
      );
      if (result.applied) setMyFaceMakeup({ mood: moodId, image: result.image });
      else setMyFaceError(result.message);
    } catch {
      setMyFaceError('내 사진에 적용하지 못했어요. 잠시 후 다시 시도해 주세요.');
    } finally {
      setMyFaceLoading(false);
    }
  }

  function addFaceFiles(files: File[]) {
    setCameraNotice('');   // 사진을 넣었으면 카메라 안내는 더 이상 필요 없다.
    const imageFiles = files.filter((item) => item.type.startsWith('image/'));
    if (!imageFiles.length) {
      setError('이미지 파일만 업로드할 수 있습니다.');
      return;
    }

    const availableSlots = 5 - faceFiles.length;
    if (availableSlots <= 0) {
      setError('피부 케어 분석 사진은 최대 5장까지 선택할 수 있습니다.');
      return;
    }

    const filesToAdd = imageFiles.slice(0, availableSlots);
    setError(imageFiles.length > availableSlots ? '피부 케어 분석 사진은 최대 5장까지 선택할 수 있어 일부 파일만 추가했습니다.' : '');
    setFaceFiles((current) => [...current, ...filesToAdd]);
    setPreviewUrls((current) => [...current, ...filesToAdd.map((item) => URL.createObjectURL(item))]);
    resetResults();
  }

  function handleUploadFiles(files: FileList | null) {
    if (!files) return;
    addFaceFiles(Array.from(files));
  }

  function removeFaceFile(index: number) {
    URL.revokeObjectURL(previewUrls[index]);
    setFaceFiles((current) => current.filter((_, itemIndex) => itemIndex !== index));
    setPreviewUrls((current) => current.filter((_, itemIndex) => itemIndex !== index));
    resetResults();
  }

  /** 피부케어 사진 전체 삭제(퍼스널컬러의 clearPersonalColorFiles 와 같은 역할).
   *  미리보기 URL 을 반드시 해제한다 — 안 하면 blob 이 메모리에 남는다. */
  function clearFaceFiles() {
    previewUrls.forEach((url) => URL.revokeObjectURL(url));
    setFaceFiles([]);
    setPreviewUrls([]);
    resetResults();
    setError('');
  }

  // 네일 촬영: 얼굴 쪽 카메라 로직(videoRef/canvasRef/startCamera)을 그대로 재사용한다.
  // 한 번에 한 페이지만 렌더되므로 ref 공유가 안전하다.
  async function openNailCamera() {
    setError('');
    setNailCameraOn(true);
    try {
      await startCamera(undefined, 'environment');
    } catch {
      setNailCameraOn(false);
      setError('카메라를 열지 못했습니다. 브라우저 권한을 확인해 주세요.');
    }
  }

  function closeNailCamera() {
    stopCamera();
    setNailCameraOn(false);
  }

  /** 검출된 손·발톱 영역에 선택한 색을 입혀 '발색 미리보기'를 만든다.
   *
   * 캔버스 합성 모드 'color' 를 쓰면 **원본의 명암(광택·그림자)은 그대로 두고 색상/채도만**
   * 교체된다 — 단색으로 덮어칠하는 것보다 훨씬 실제 발색에 가깝다. 검출 결과가 bbox 뿐이라
   * 손톱 모양은 타원으로 근사한다(폴리곤 마스크가 생기면 그대로 교체 가능).
   */
  async function applyNailShade(shade: NailShade, detected?: DetectedNail[], previewUrl?: string) {
    setNailShade(shade);
    // ⚠ 분석 직후 자동 적용할 때는 setNailResult/setNailPreview 가 아직 이 클로저에 반영되지
    //   않아 둘 다 비어 있다(실측: 자동 적용이 조용히 아무것도 안 했다). 그래서 호출부가
    //   검출 결과와 사진 URL 을 직접 넘길 수 있게 한다.
    const nails = detected ?? nailResult?.detected ?? [];
    const source = previewUrl ?? nailPreview;
    if (!source || !nails.length) return;
    const image = new Image();
    image.src = source;
    await new Promise((resolve) => {
      if (image.complete) resolve(null);
      else image.onload = () => resolve(null);
    });
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(image, 0, 0);
    nails.forEach((nail) => {
      const [x1, y1, x2, y2] = nail.bbox;
      const cx = (x1 + x2) / 2;
      const cy = (y1 + y2) / 2;
      const rx = Math.max(2, (x2 - x1) / 2);
      const ry = Math.max(2, (y2 - y1) / 2);
      ctx.save();
      ctx.beginPath();
      ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
      ctx.clip();
      ctx.globalCompositeOperation = 'color';   // 명암 유지, 색상만 교체
      ctx.fillStyle = shade.hex;
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
      ctx.globalCompositeOperation = 'source-atop';
      ctx.globalAlpha = 0.22;                   // 발색을 살짝 진하게(젤 도포 느낌)
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
      ctx.restore();
    });
    setNailTryOn(canvas.toDataURL('image/jpeg', 0.92));
    void loadNailProducts(shade);
  }

  /** 선택한 색조로 실제 구매 가능한 네일 상품을 찾는다(아이템매칭 라이브 검색 재사용).
   *  지역/플랫폼은 인자로 받는다 — 드롭다운에서 바꾼 값은 setState 직후엔 아직 반영되지 않아
   *  itemRegion/itemPlatform 을 그대로 읽으면 '한 번 늦은' 조건으로 조회된다. */
  async function loadNailProducts(shade: NailShade, region: ItemRegion = itemRegion, platform: ItemPlatform = itemPlatform) {
    setNailProductsLoading(true);
    try {
      // ⚠ JP 는 색이름까지 일본어로 바꿔야 한다. 한글 색이름 + 일본어 카테고리어를 섞어
      //   보내면 라쿠텐이 0건을 준다(실측: '로즈 브라운 ジェルネイル' → 0건).
      const keywords = region === 'jp'
        ? [`${localizeColorToJa(shade.name)} ジェルネイル`, `${localizeColorToJa(shade.name)} マニキュア`]
        : [`${shade.name} 젤네일`, `${shade.name} 네일 폴리쉬`];
      const data = await matchPersonalColorItems(keywords, region, platform, 'female');
      // 네일 컬럼 상품만 남긴다(색상어가 립/블러셔 상품을 물어오는 경우 방지).
      setNailProducts(data.products.filter((item) => itemMatchColumnFor(item) === 'nail').slice(0, 6));
    } catch {
      setNailProducts([]);
    } finally {
      setNailProductsLoading(false);
    }
  }

  async function captureNailImage() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !cameraReady) return;
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    const context = canvas.getContext('2d');
    if (!context) return;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
    if (!blob) return;
    closeNailCamera();  // 촬영 후에는 카메라를 꺼서 스트림을 놓아준다.
    await handleNailUpload(new File([blob], `yopalette-nail-${Date.now()}.jpg`, { type: 'image/jpeg' }));
  }

  async function captureFaceImage() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !cameraReady) return;

    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    const context = canvas.getContext('2d');
    if (!context) return;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
    if (!blob) return;
    addFaceFiles([new File([blob], `beautyai-camera-${Date.now()}.jpg`, { type: 'image/jpeg' })]);
  }

  async function handleAnalyze() {
    const minimumImages = 1;
    if (faceFiles.length < minimumImages || faceFiles.length > 5) {
      setError('피부 케어 분석에는 사진을 1~5장 선택해 주세요.');
      setCurrentStep(1);
      return;
    }

    setCurrentStep(2);
    setLoading('analyzing');
    setError('');
    try {
      const results = await Promise.all(faceFiles.map((item) => analyzeSkin(item, analysisMode)));
      const faceResults = results.filter((item) => item.analysis_mode === 'face' && item.scores);
      const bodyResults = results.filter((item) => item.analysis_mode === 'body');
      const resultMode: Exclude<AnalysisMode, 'auto'> = faceResults.length >= bodyResults.length ? 'face' : 'body';
      const result: AnalyzeSkinResponse = resultMode === 'face'
        ? {
            ...(faceResults[0] ?? results[0]),
            analysis_mode: 'face',
            scores: averageSkinScores(faceResults.length ? faceResults : results),
            summary: `${faceResults.length || results.length}장의 피부 케어 사진을 얼굴 피부로 평균 분석했습니다.`,
          }
        : {
            ...(bodyResults[0] ?? results[0]),
            analysis_mode: 'body',
            body_conditions: averageBodyConditions(bodyResults.length ? bodyResults : results),
            // 여러 장 중 하나라도 악성 의심이면 경고를 유지(안전 방향). 선별 요약도 보존.
            urgent: (bodyResults.length ? bodyResults : results).some((item) => item.urgent),
            summary: (bodyResults[0] ?? results[0]).summary,
          };
      setAnalysis(result);
      setRecommendation(await recommend(
        survey,
        result.analysis_id ?? undefined,
        result.scores ?? undefined,
        selectedPlatform,
        result.analysis_mode,
        result.body_conditions,
        skinRegion,
      ));
    } catch {
      setError('분석에 실패했습니다. 백엔드가 실행 중인지, 피부 사진이 정상적으로 선택되었는지 확인해 주세요.');
    } finally {
      setLoading('');
    }
  }

  async function reloadRecommendation(region: ItemRegion, platform: ItemPlatform) {
    if (!analysis) return;
    setLoading('recommend');
    setError('');
    try {
      setRecommendation(await recommend(
        survey,
        analysis.analysis_id ?? undefined,
        analysis.scores ?? undefined,
        platform,
        analysis.analysis_mode,
        analysis.body_conditions,
        region,
      ));
    } catch {
      setError('추천을 다시 계산하지 못했습니다. 백엔드 연결을 확인해 주세요.');
    } finally {
      setLoading('');
    }
  }

  async function handlePlatformChange(platform: ItemPlatform) {
    setSelectedPlatform(platform);
    await reloadRecommendation(skinRegion, platform);
  }

  async function handleSkinRegionChange(region: ItemRegion) {
    setSkinRegion(region);
    setSelectedPlatform('all');
    await reloadRecommendation(region, 'all');
  }

  /** 퍼스널컬러 결과지에서 여는 상담. 피부 점수가 아니라 **퍼스널컬러 판정 결과**를
   *  문맥으로 보내야 톤·팔레트에 맞는 답이 나온다. */
  async function handlePersonalColorChat() {
    setLoading('chat');
    setError('');
    try {
      const context = {
        ...survey,
        personal_color: personalColorResult?.label ?? '',
        tone: personalColorResult?.tone ?? '',
        subtype: personalColorResult?.subtype ?? '',
      };
      const result = await chat(message, undefined, context as typeof survey);
      setAnswer(result.answer);
      setAnswerSources(result.sources);
    } catch {
      setError('상담 요청에 실패했습니다. 백엔드 연결을 확인해 주세요.');
    } finally {
      setLoading('');
    }
  }

  async function handleChat() {
    setLoading('chat');
    setError('');
    try {
      const result = await chat(message, analysis?.scores ?? undefined, survey);
      setAnswer(result.answer);
      setAnswerSources(result.sources);
    } catch {
      setError('상담 요청에 실패했습니다. 백엔드 연결을 확인해 주세요.');
    } finally {
      setLoading('');
    }
  }

  function goNext() {
    if (currentStep === 1) {
      handleAnalyze();
      return;
    }
    setCurrentStep((step) => Math.min(step + 1, steps.length - 1));
  }

  /** 결과지에 담을 피부 케어 상품 토글(최대 4개, 넘치면 오래된 것부터 밀어낸다). */
  function toggleSkinReportProduct(id: number, checked: boolean) {
    setSkinReportIds((current) => {
      if (!checked) return current.filter((item) => item !== id);
      if (current.includes(id)) return current;
      // ⚠ 예전엔 `.slice(-4)` 로 잘라서, 상한을 넘기면 **먼저 고른 게 말없이 해제**됐다
      //    (사용자 지적: "하나 더 누르면 하나가 풀려요"). 지금은 가득 차면 그냥 무시하고,
      //    아래 체크박스를 비활성화해 왜 안 되는지 화면에서 보이게 한다.
      if (current.length >= SKIN_REPORT_MAX) return current;
      return [...current, id];
    });
  }

  function canGoNext() {
    if (currentStep === 0) {
      return Boolean(survey.age?.trim()) && Boolean(survey.race_identity?.trim()) && survey.privacy_consent === true;
    }
    if (currentStep === 1) {
      return faceFiles.length >= 1 && faceFiles.length <= 5 && loading !== 'analyzing';
    }
    if (currentStep === 2) return Boolean(analysis);
    if (currentStep === 3) return Boolean(recommendation);
    if (currentStep === 4) return Boolean(recommendation);  // 상담 → 결과지 출력
    return false;
  }

  function renderSurveyPage() {
    return (
      <Paper className="page-panel" elevation={0}>
        <Typography variant="h5" fontWeight={800}>{t('기본 정보 입력')}</Typography>
        <Typography color="text.secondary" sx={{ mt: 0.5 }}>
          {t('분석을 시작하기 전에 기본 정보와 개인정보 활용 동의를 확인합니다.')}
        </Typography>

        <Stack spacing={3.5} sx={{ mt: 2.5 }}>
          <TextField
            label={t('나이를 알려주세요')}
            placeholder={t('여기를 눌러서 입력')}
            value={survey.age ?? ''}
            onChange={(event) => {
              const age = event.target.value;
              setSurvey({ ...survey, age, age_group: ageToAgeGroup(age) });
            }}
            inputProps={{ inputMode: 'numeric' }}
            fullWidth
          />

          <Box>
            <Typography variant="body2" fontWeight={700} gutterBottom>{t('성별')}</Typography>
            <ToggleButtonGroup
              value={survey.gender}
              exclusive
              onChange={(_, v) => v && setSurvey({ ...survey, gender: v })}
              fullWidth
            >
              <ToggleButton value="female" sx={{ py: 1.5, fontWeight: 700, fontSize: '0.95rem' }}>
                {t('여성')}
              </ToggleButton>
              <ToggleButton value="male" sx={{ py: 1.5, fontWeight: 700, fontSize: '0.95rem' }}>
                {t('남성')}
              </ToggleButton>
            </ToggleButtonGroup>
          </Box>

          <FormControl fullWidth>
            <InputLabel>{t('본인이 인식하는 인종 정체성을 알려주세요')}</InputLabel>
            <Select
              label={t('본인이 인식하는 인종 정체성을 알려주세요')}
              value={survey.race_identity ?? ''}
              onChange={(event) => setSurvey({ ...survey, race_identity: event.target.value })}
              displayEmpty
            >
              {/* value 는 한국어 원문 유지(백엔드로 전송되는 값), 표시만 번역. */}
              {raceIdentityOptions.map((option) => (
                <MenuItem key={option} value={option}>{t(option)}</MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControlLabel
            control={
              <Checkbox
                checked={survey.privacy_consent === true}
                onChange={(event) => setSurvey({ ...survey, privacy_consent: event.target.checked })}
              />
            }
            label={t('개인정보 활용에 동의합니다.')}
          />

          <Alert severity="info">
            {t('다음 단계에서 얼굴 사진을 촬영하거나 업로드합니다. 피부 고민과 메이크업 고민은 사진 분석 이후 추천 단계에서 다룹니다.')}
          </Alert>
        </Stack>
      </Paper>
    );
  }

  function renderHomePage() {
    return (
      <Box className="app-shell">
      <AppLangToggle authUser={authUser} />
        <Container maxWidth="lg" sx={{ py: { xs: 2, md: 4 } }}>
          <Paper elevation={0} className="home-hero">
            <Stack spacing={1}>
              <Chip label="YoPalette" color="primary" variant="outlined" sx={{ width: 'fit-content' }} />
              <Typography variant="h3" fontWeight={900}>
                {t('원하는 AI 뷰티 분석을 선택해 주세요.')}
              </Typography>
              <Typography color="text.secondary" sx={{ maxWidth: 720, lineHeight: 1.7 }}>
                {t('YoPalette는 기능별로 분리된 분석 워크스페이스입니다. 지금은 피부 케어 분석을 사용할 수 있고, 퍼스널컬러와 추가 분석 기능은 같은 홈 화면에서 확장됩니다.')}
              </Typography>
              {/* 쇼핑몰(BeautyWEB)로 나가는 입구. 화면 언어에 따라 포트가 갈린다(ko 5174 / ja 5175). */}
              <Button
                component="a"
                href={WEB_URL_BY_LANG[appLang]}
                target="_blank"
                rel="noreferrer"
                variant="contained"
                endIcon={<ArrowRight size={18} />}
                sx={{ alignSelf: 'flex-start', mt: 1 }}
              >
                {t('YoPalette 홈으로 이동')}
              </Button>
            </Stack>
          </Paper>

          <Grid container spacing={2} sx={{ mt: 2 }}>
            <Grid item xs={12} sm={6} md={3}>
              <Paper elevation={0} className="module-card active-module">
                <Stack spacing={1.5}>
                  <Box className="module-icon"><Sparkles size={24} /></Box>
                  <Typography variant="h5" fontWeight={900}>{t('퍼스널컬러')}</Typography>
                  <Typography color="text.secondary">
                    {t('얼굴 이미지를 바탕으로 톤, 팔레트, 메이크업 컬러를 추천하는 기능입니다.')}
                  </Typography>
                  <Button variant="contained" endIcon={<ArrowRight size={16} />} onClick={startPersonalColorAnalysis}>
                    {t('시작하기')}
                  </Button>
                </Stack>
              </Paper>
            </Grid>

            <Grid item xs={12} sm={6} md={3}>
              <Paper elevation={0} className="module-card active-module">
                <Stack spacing={1.5}>
                  <Box className="module-icon"><Camera size={24} /></Box>
                  <Typography variant="h5" fontWeight={900}>{t('피부 케어 분석')}</Typography>
                  <Typography color="text.secondary">
                    {t('얼굴 피부와 바디 피부 사진을 같은 케어 흐름 안에서 분석하고, 성분과 상품을 추천합니다.')}
                  </Typography>
                  <Button variant="contained" endIcon={<ArrowRight size={16} />} onClick={startSkinCareAnalysis}>
                    {t('시작하기')}
                  </Button>
                </Stack>
              </Paper>
            </Grid>

            <Grid item xs={12} sm={6} md={3}>
              <Paper elevation={0} className="module-card active-module">
                <Stack spacing={1.5}>
                  <Box className="module-icon"><ImagePlus size={24} /></Box>
                  <Typography variant="h5" fontWeight={900}>{t('네일·페디 디자인')}</Typography>
                  <Typography color="text.secondary">
                    {t('손·발 사진에서 네일을 찾아 비슷한 디자인을 검색하고, 퍼스널컬러 시즌 적합도를 알려줍니다.')}
                  </Typography>
                  <Button variant="contained" endIcon={<ArrowRight size={16} />} onClick={startNailDesign}>
                    {t('시작하기')}
                  </Button>
                </Stack>
              </Paper>
            </Grid>

            <Grid item xs={12} sm={6} md={3}>
              <Paper elevation={0} className="module-card active-module virtual-module-card">
                <Stack spacing={1.5}>
                  <Box className="module-icon"><ScanFace size={24} /></Box>
                  <Typography variant="h5" fontWeight={900}>{t('가상 성형 추천')}</Typography>
                  <Typography color="text.secondary">
                    {t('얼굴 비율과 고민 부위를 읽고, 과하지 않은 변화 방향과 점 제거·윤곽 미리보기를 추천합니다.')}
                  </Typography>
                  <Button variant="contained" endIcon={<ArrowRight size={16} />} onClick={startVirtualSurgery}>
                    {t('시작하기')}
                  </Button>
                </Stack>
              </Paper>
            </Grid>
          </Grid>
        </Container>
      </Box>
    );
  }

  function renderPersonalColorPage() {
    // 퍼스널컬러 결과 메이크업 카드(성별 분기). 남성=베이스/아이브로우/컨실러/립밤(그루밍),
    // 여성=립/블러셔/아이/베이스/네일. 아이템매칭 컬럼과 같은 카테고리 세트를 따른다.
    const makeupGroups = personalColorResult
      ? personalColorProfile.gender === 'male'
        ? (() => {
            const warm = /웜|warm|가을|봄|autumn|spring/i.test(`${personalColorResult.tone} ${personalColorResult.label}`);
            return [
              { label: '베이스', values: personalColorResult.makeup.base },
              { label: '아이브로우', values: [warm ? '소프트 브라운' : '그레이 브라운'] },
              { label: '컨실러', values: ['잡티·다크서클 커버'] },
              { label: '립밤', values: personalColorResult.makeup.lip },
            ];
          })()
        : [
            { label: '립', values: personalColorResult.makeup.lip },
            { label: '블러셔', values: personalColorResult.makeup.blush },
            { label: '아이', values: personalColorResult.makeup.eye },
            { label: '베이스', values: personalColorResult.makeup.base },
            { label: '네일', values: personalColorResult.makeup.nail ?? [] },
          ]
      : [];
    // 아이템매칭 컬럼(성별 분기). 남성=베이스/브로우/컨실러/립밤(그루밍), 여성=기존 5컬럼.
    // key로 groupedProducts를 조회하고, showColor로 헤더에 'color' 표기 여부를 정한다.
    const isMaleItems = personalColorProfile.gender === 'male';
    const itemMatchGroups: { key: ItemMatchColumnKey; label: string; values: string[]; showColor: boolean }[] =
      personalColorResult
        ? isMaleItems
          ? (() => {
              const warm = /웜|warm|가을|봄|autumn|spring/i.test(`${personalColorResult.tone} ${personalColorResult.label}`);
              return [
                { key: 'base', label: '베이스', values: personalColorResult.makeup.base, showColor: true },
                { key: 'brow', label: '아이브로우', values: [warm ? '소프트 브라운' : '그레이 브라운'], showColor: true },
                { key: 'concealer', label: '컨실러', values: ['잡티·다크서클 커버'], showColor: false },
                { key: 'lipbalm', label: '립밤', values: personalColorResult.makeup.lip, showColor: true },
              ];
            })()
          : [
              { key: 'lip', label: '립', values: personalColorResult.makeup.lip, showColor: true },
              { key: 'blush', label: '블러셔', values: personalColorResult.makeup.blush, showColor: true },
              { key: 'eye', label: '아이', values: personalColorResult.makeup.eye, showColor: true },
              { key: 'base', label: '베이스', values: personalColorResult.makeup.base, showColor: true },
              { key: 'nail', label: '네일', values: personalColorResult.makeup.nail ?? [], showColor: true },
            ]
        : [];
    // 네일 화면과 같은 컴포넌트를 쓴다(선택지·번역이 한쪽만 바뀌는 걸 막는다).
    const itemPlatformFilter = (
      <ItemMarketFilter
        region={itemRegion}
        platform={itemPlatform}
        onRegionChange={(next) => {
          setItemRegion(next);
          setItemPlatform('all');
          setPersonalColorItems(null);
          setMoodItems(null);
          setReportPicks([]);
        }}
        onPlatformChange={(next) => {
          setItemPlatform(next);
          setPersonalColorItems(null);
          setMoodItems(null);
          setReportPicks([]);
        }}
      />
    );
    const personalColorSteps = [
      '개인정보 입력',
      'AI 퍼스널컬러 분석',
      '얼굴형 분석',
      '메이크업 무드 선택',
      '아이템 매칭',
      '결과지 출력',
    ];
    const canMoveNext =
      personalColorStep === 0
        ? personalColorProfile.consent
        : personalColorStep === 1
          ? Boolean(personalColorResult)
          : true;

    const setProfile = (key: keyof typeof personalColorProfile, value: string | boolean) => {
      setPersonalColorProfile((profile) => ({ ...profile, [key]: value }));
    };

    const reportSourceProducts = (selectedMood && moodItems?.products.length ? moodItems.products : personalColorItems?.products) ?? [];
    const pickedIdentities = new Set(reportPicks.map(productIdentityKey));
    // 담을 수 있는 최대 개수 = **컬럼 수**. 남성은 4컬럼(베이스/브로우/컨실러/립밤)이라 4개다.
    // 컬럼 수보다 크게 두면 사용자가 다 담아도 칸이 남아, 아래 자동 채우기가 '담지 않은 상품'을
    // 결과지에 올린다(실측: 남성이 4개를 담았는데 5번째로 엉뚱한 쿠션팩트가 실렸다).
    const reportMax = Math.min(PC_REPORT_MAX, itemMatchGroups.length || PC_REPORT_MAX);
    // 결과지에는 **담은 상품만** 싣는다. 자동 채우기는 없다(사용자 지시 2026-08-03).
    // 2026-07-30 에 '모자란 칸만 채우던 것'을 '하나도 안 담았을 때만 채우기'로 좁혔는데,
    // 그마저도 담은 적 없는 상품이 '장바구니' 제목 아래 실려 내가 고른 것처럼 보였다.
    // 아무것도 안 담았으면 빈 자리표시(아래 report-product empty)만 나온다.
    const reportItems = reportPicks.slice(0, reportMax);
    const isPicked = (product: RakutenProduct) => pickedIdentities.has(productIdentityKey(product));
    const toggleReportProduct = (product: RakutenProduct, checked: boolean) => {
      const identity = productIdentityKey(product);
      setReportPicks((current) => {
        if (!checked) return current.filter((item) => productIdentityKey(item) !== identity);
        if (current.some((item) => productIdentityKey(item) === identity)) return current;
        // 상한을 넘으면 **추가하지 않는다**. 예전엔 slice(-4) 로 첫 선택을 조용히 버려서,
        // 5번째를 체크하면 이미 담아둔 카드의 체크가 저절로 풀렸다(체크포인트 없이 사라짐).
        if (current.length >= reportMax) return current;
        return [...current, product];
      });
    };

    const renderPersonalStepContent = () => {
      if (personalColorStep === 0) {
        return (
          <Grid container spacing={2}>
            <Grid item xs={12} md={5}>
              <Box className="kiosk-device-panel">
                <Typography variant="overline">Beauty diagnosis</Typography>
                <Typography variant="h4" fontWeight={900}>{t('뷰티 진단서 받기')}</Typography>
                <Typography color="text.secondary" sx={{ mt: 1 }}>
                  {t('퍼스널컬러, 메이크업, 헤어컬러, 주얼리, 스타일 컨설팅을 한 흐름으로 확인합니다.')}
                </Typography>
                <Box className="kiosk-face-placeholder">
                  <Sparkles size={34} />
                  <Typography fontWeight={900}>AI Makeup</Typography>
                </Box>
              </Box>
            </Grid>
            <Grid item xs={12} md={7}>
              <Stack spacing={2}>
                <Typography variant="h5" fontWeight={900}>{t('개인정보 입력')}</Typography>
                <Grid container spacing={1.5}>
                  <Grid item xs={12}>
                    <TextField
                      fullWidth
                      label={t('나이')}
                      value={personalColorProfile.age}
                      onChange={(event) => setProfile('age', event.target.value)}
                    />
                  </Grid>
                  <Grid item xs={12}>
                    <ToggleButtonGroup
                      color="primary"
                      exclusive
                      fullWidth
                      value={personalColorProfile.gender}
                      onChange={(_event, value) => {
                        if (!value || value === personalColorProfile.gender) return;
                        setProfile('gender', value);
                        // 성별이 바뀌면 컬럼 구성(여성 5 / 남성 4)과 추천 상품이 통째로 달라진다.
                        // 담아둔 상품·조회 결과를 비워 이전 성별 상품이 섞이지 않게 한다.
                        setPersonalColorItems(null);
                        setMoodItems(null);
                        setReportPicks([]);
                      }}
                    >
                      <ToggleButton value="female">{t('여성')}</ToggleButton>
                      <ToggleButton value="male">{t('남성')}</ToggleButton>
                    </ToggleButtonGroup>
                  </Grid>
                  <Grid item xs={12}>
                    <FormControl fullWidth>
                      <InputLabel>{t('인종정체성')}</InputLabel>
                      <Select
                        label={t('인종정체성')}
                        value={personalColorProfile.raceIdentity}
                        onChange={(event) => setProfile('raceIdentity', event.target.value)}
                      >
                        {[
                          '동아시아 (한국·중국·일본·대만)',
                          '동남아시아 (베트남·태국·필리핀·인도네시아)',
                          '남아시아 (인도·파키스탄·방글라데시·네팔)',
                          '백인/유럽계',
                          '흑인/아프리카계',
                          '라틴/히스패닉',
                          '중동/북아프리카',
                          '혼혈/다인종',
                          '선택 안 함',
                        ].map((option) => (
                          <MenuItem key={option} value={option}>{option}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                </Grid>
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={personalColorProfile.consent}
                      onChange={(event) => setProfile('consent', event.target.checked)}
                    />
                  }
                  label={t('분석을 위한 이미지 및 입력 정보 활용에 동의합니다.')}
                />
                <Alert severity="info">
                  {t('문서의 키오스크처럼 개인정보 입력 후 AI 퍼스널컬러 분석 단계로 이동합니다.')}
                </Alert>
              </Stack>
            </Grid>
          </Grid>
        );
      }

      if (personalColorStep === 1) {
        return (
          <Grid container spacing={2}>
            <Grid item xs={12} md={5}>
              <Stack spacing={2}>
                <Typography variant="h5" fontWeight={900}>{t('Step 1. AI 퍼스널컬러 분석')}</Typography>
                <Typography color="text.secondary">
                  {t('정면 얼굴 사진을 넣으면 피부 밝기, 웜쿨, 채도 경향을 분석해 타입을 판정합니다. 여러 장(다른 각도·조명)을 함께 넣으면 결과가 더 안정적입니다.')}
                </Typography>
                <Box className="personal-color-preview kiosk-preview" sx={{ position: 'relative' }}>
                  {personalColorPreview ? (
                    <>
                      <img src={personalColorPreview} alt={`퍼스널컬러 분석 미리보기 ${safePersonalColorIndex + 1}`} />
                      {personalColorCount > 1 && (
                        <>
                          <IconButton
                            aria-label={t('이전 사진')}
                            onClick={() => stepPersonalColorImage(-1)}
                            sx={{
                              position: 'absolute', top: '50%', left: 8, transform: 'translateY(-50%)',
                              bgcolor: 'rgba(0,0,0,0.5)', color: '#fff', '&:hover': { bgcolor: 'rgba(0,0,0,0.7)' },
                            }}
                          >
                            <ArrowLeft size={20} />
                          </IconButton>
                          <IconButton
                            aria-label={t('다음 사진')}
                            onClick={() => stepPersonalColorImage(1)}
                            sx={{
                              position: 'absolute', top: '50%', right: 8, transform: 'translateY(-50%)',
                              bgcolor: 'rgba(0,0,0,0.5)', color: '#fff', '&:hover': { bgcolor: 'rgba(0,0,0,0.7)' },
                            }}
                          >
                            <ArrowRight size={20} />
                          </IconButton>
                        </>
                      )}
                      <Box
                        sx={{
                          position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)',
                          bgcolor: 'rgba(0,0,0,0.6)', color: '#fff', borderRadius: 10,
                          px: 1.2, py: 0.3, fontSize: 13, fontWeight: 700,
                        }}
                      >
                        {safePersonalColorIndex + 1} / {personalColorCount}
                      </Box>
                      <IconButton
                        aria-label={t('이 사진 삭제')}
                        onClick={() => removePersonalColorFile(safePersonalColorIndex)}
                        sx={{
                          position: 'absolute', top: 8, right: 8,
                          bgcolor: 'rgba(0,0,0,0.5)', color: '#fff', '&:hover': { bgcolor: 'rgba(211,47,47,0.85)' },
                        }}
                      >
                        <Trash2 size={16} />
                      </IconButton>
                    </>
                  ) : (
                    <Stack alignItems="center" spacing={1}>
                      <ImagePlus size={34} />
                      <Typography>{t('얼굴 사진을 선택해 주세요.')}</Typography>
                    </Stack>
                  )}
                </Box>
                {personalColorCount > 0 && (
                  <Stack direction="row" spacing={1} sx={{ overflowX: 'auto', pb: 0.5 }}>
                    {personalColorPreviews.map((url, index) => (
                      <Box
                        key={url}
                        onClick={() => setPersonalColorIndex(index)}
                        sx={{
                          position: 'relative', flex: '0 0 auto', width: 56, height: 56, borderRadius: 1.5,
                          overflow: 'hidden', cursor: 'pointer',
                          border: (theme) =>
                            `2px solid ${index === safePersonalColorIndex ? theme.palette.primary.main : 'transparent'}`,
                        }}
                      >
                        <img src={url} alt={`선택한 사진 ${index + 1}`} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                        <IconButton
                          aria-label={`${index + 1}번 사진 삭제`}
                          onClick={(event) => { event.stopPropagation(); removePersonalColorFile(index); }}
                          sx={{
                            position: 'absolute', top: 0, right: 0, p: 0.2,
                            bgcolor: 'rgba(0,0,0,0.55)', color: '#fff', '&:hover': { bgcolor: 'rgba(211,47,47,0.9)' },
                          }}
                        >
                          <X size={12} />
                        </IconButton>
                      </Box>
                    ))}
                  </Stack>
                )}
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                  <Button
                    fullWidth
                    variant="outlined"
                    component="label"
                    startIcon={<ImagePlus size={18} />}
                    disabled={personalColorCount >= PERSONAL_COLOR_MAX}
                  >
                    {personalColorCount > 0 ? '사진 추가' : '사진 선택'}
                    <input hidden multiple type="file" accept="image/*" onChange={(event) => { handlePersonalColorUpload(event.target.files); event.target.value = ''; }} />
                  </Button>
                  <Button
                    fullWidth
                    variant="contained"
                    disabled={!personalColorFile || loading === 'personal-color'}
                    onClick={handlePersonalColorAnalyze}
                    endIcon={<Sparkles size={18} />}
                  >
                    {loading === 'personal-color' ? '분석 중...' : '분석 시작'}
                  </Button>
                </Stack>
                {/* 웹 계정에 퍼스널 컬러를 저장해 둔 사람은 촬영 없이 바로 결과를 볼 수 있다. */}
                {authUser?.personal_color && (
                  <Stack spacing={0.5}>
                    <Button
                      fullWidth
                      variant="outlined"
                      color="secondary"
                      disabled={loading === 'personal-color'}
                      onClick={() => void applySavedPersonalColor()}
                    >
                      {t('저장된 퍼스널 컬러로 바로 보기')} ·{' '}
                      {tPhrase(WEB_PERSONAL_COLOR_LABELS[authUser.personal_color] ?? authUser.personal_color)}
                    </Button>
                    <Typography variant="caption" color="text.secondary">
                      {t('회원 정보에 저장된 값을 사용합니다. 사진으로 다시 진단하려면 위에서 사진을 선택하세요.')}
                    </Typography>
                  </Stack>
                )}
                {personalColorCount > 0 && (
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Typography variant="caption" color="text.secondary">
                      {personalColorCount}/{PERSONAL_COLOR_MAX}장 선택됨{personalColorCount === 1 ? ' · 2~3장을 함께 넣으면 판정이 더 안정적입니다.' : ' · 여러 장 평균으로 판정합니다.'}
                    </Typography>
                    <Button size="small" color="inherit" startIcon={<Trash2 size={14} />} onClick={clearPersonalColorFiles}>
                      {t('전체 삭제')}
                    </Button>
                  </Stack>
                )}
                {loading === 'personal-color' && <LinearProgress />}
              </Stack>
            </Grid>
            <Grid item xs={12} md={7}>
              {!personalColorResult ? (
                <Box className="kiosk-result-empty">
                  <Typography variant="h5" fontWeight={900}>{t('내 퍼스널 컬러')}</Typography>
                  <Typography color="text.secondary" sx={{ mt: 1 }}>
                    {t('분석 결과가 나오면 문서 예시처럼 타입, 팔레트, 메이크업 컬러가 표시됩니다.')}
                  </Typography>
                </Box>
              ) : (
                <Stack spacing={2.5}>
                  <Box
                    className="kiosk-season-card"
                    sx={{
                      // 배경을 진단된 퍼스널컬러 팔레트로 물들인다. 어두운 스크림을 덧대
                      // 흰 글씨 가독성은 유지하면서 계절색이 은은하게 비치게 한다.
                      background: `linear-gradient(140deg, rgba(11,17,32,0.82), rgba(11,17,32,0.9)), linear-gradient(140deg, ${personalColorResult.palette.join(', ')})`,
                    }}
                  >
                    <Typography variant="overline">Personal color result</Typography>
                    <Typography variant="h3" fontWeight={900}>{personalColorResult.label}</Typography>
                    <Typography color="text.secondary" sx={{ mt: 1 }}>
                      {personalColorResult.skin_summary}
                    </Typography>
                    {personalColorResult.decision_note && (
                      <Typography color="rgba(255,255,255,0.76)" sx={{ mt: 0.75, fontSize: 13 }}>
                        {personalColorResult.decision_note}
                      </Typography>
                    )}
                    {(() => {
                      // 단일 라벨은 여름쿨↔겨울쿨 등에서 흔들려, 가능성 높은 2개 타입을 확률과 함께 노출한다.
                      //
                      // ⚠️ season_margin 으로 "근소한 차이"를 게이팅하지 않는다(2026-07-17 실측).
                      // margin 이 클수록(=모델과 색휴리스틱이 일치할수록) 오히려 덜 맞는다:
                      //   margin<0.16 : top-1 0.500 / top-2 0.740  (n=50)
                      //   margin>=0.16: top-1 0.354 / top-2 0.615  (n=65)
                      // 현행 정확도의 원천이 model(winter편향)×color(spring편향) 상쇄라, 둘이 일치하면
                      // 공유편향으로 같이 틀린다. 즉 margin 은 확신이 아니라 "같은 방향으로 틀릴 위험"의
                      // 지표다. 뒤집어 쓰는 것도 원리가 없으므로 게이팅 자체를 없애고 항상 2개를 준다.
                      // (top-2 0.72~0.74 가 이 파이프라인에서 유일하게 쓸 만한 수치다.)
                      // 확률이 아예 없으면(저장된 퍼스널컬러로 들어온 경우) null — 0% 로 표시하면
                      // 본인이 신고한 값을 "0% 확률"이라고 말하는 꼴이 된다.
                      const pct = (s?: string | null) => {
                        if (!s) return null;
                        const prob = personalColorResult.metrics[`prob_${s}`];
                        return prob == null ? null : Math.round(prob * 100);
                      };
                      const p1 = pct(personalColorResult.season);
                      if (p1 == null) return null;
                      const p2 = pct(personalColorResult.alternate_season);
                      return (
                        <Box sx={{ mt: 1.5 }}>
                          <Typography sx={{ fontSize: 12, color: 'rgba(255,255,255,0.6)', mb: 0.5 }}>
                            {t('가장 가까운 타입')}
                          </Typography>
                          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
                            <Chip
                              size="small"
                              label={`${personalColorResult.label} · ${p1}%`}
                              sx={{ bgcolor: 'rgba(255,255,255,0.18)', color: 'common.white', fontWeight: 700 }}
                            />
                            {personalColorResult.alternate_label && (
                              <>
                                <Typography component="span" sx={{ color: 'rgba(255,255,255,0.6)', fontSize: 13 }}>
                                  {t('또는')}
                                </Typography>
                                <Chip
                                  size="small"
                                  variant="outlined"
                                  label={`${personalColorResult.alternate_label}${p2 != null ? ` · ${p2}%` : ''}`}
                                  sx={{ color: 'common.white', borderColor: 'rgba(255,255,255,0.45)' }}
                                />
                              </>
                            )}
                          </Stack>
                          {personalColorResult.alternate_label && (
                            <Typography sx={{ mt: 0.75, fontSize: 13, color: 'rgba(255,255,255,0.85)' }}>
                              {t('두 타입 중 하나예요 — 둘 다 대보고 더 어울리는 쪽을 고르세요.')}
                            </Typography>
                          )}
                        </Box>
                      );
                    })()}
                    {/* 촬영 품질 배지는 사진을 분석했을 때만 의미가 있다. 저장된 퍼스널컬러로
                        들어오면 metrics 가 비어 있어, 그대로 두면 '얼굴 crop 제한 / 휴리스틱 보조 /
                        조명 보정 제한' 이 찍혀 찍지도 않은 사진을 탓하는 것처럼 보인다(실측). */}
                    <Stack
                      direction="row"
                      spacing={1}
                      flexWrap="wrap"
                      useFlexGap
                      sx={{ mt: 1.5, display: Object.keys(personalColorResult.metrics).length ? 'flex' : 'none' }}
                    >
                      {/* 촬영 품질(이미지 상태)과 confidence(계절 확신)는 다른 값이라 폴백으로 섞지 않는다.
                          confidence 는 실측상 정확도와 음의 상관이라 품질로 대신 보여주면 오도한다. */}
                      {personalColorResult.metrics.capture_quality != null && (
                        <Chip
                          size="small"
                          label={`촬영 품질 ${Math.round(personalColorResult.metrics.capture_quality * 100)}%`}
                          color={personalColorResult.metrics.capture_quality >= 0.72 ? 'success' : 'warning'}
                        />
                      )}
                      <Chip
                        size="small"
                        label={personalColorResult.metrics.face_detected ? '얼굴 crop 적용' : '얼굴 crop 제한'}
                        variant="outlined"
                        sx={{ color: 'common.white', borderColor: 'rgba(255,255,255,0.45)' }}
                      />
                      <Chip
                        size="small"
                        label={personalColorResult.metrics.model_used ? '딥러닝 모델 사용' : '휴리스틱 보조'}
                        variant="outlined"
                        sx={{ color: 'common.white', borderColor: 'rgba(255,255,255,0.45)' }}
                      />
                      <Chip
                        size="small"
                        label={personalColorResult.metrics.white_balanced ? '조명 보정 적용' : '조명 보정 제한'}
                        variant="outlined"
                        sx={{ color: 'common.white', borderColor: 'rgba(255,255,255,0.45)' }}
                      />
                    </Stack>
                  </Box>

                  <Box>
                    <Typography variant="h6" fontWeight={900} sx={{ mb: 1 }}>{t('추천 팔레트')}</Typography>
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                      {personalColorResult.palette.map((color) => (
                        <Box className="palette-swatch" key={color} sx={{ backgroundColor: color }}>
                          <span>{color}</span>
                        </Box>
                      ))}
                    </Stack>
                  </Box>

                  <Grid container spacing={1.5}>
                    {makeupGroups.map((group) => (
                      <Grid item xs={12} sm={6} key={t(group.label)}>
                        <Box className="makeup-box">
                          <Typography fontWeight={900}>{t(group.label)}</Typography>
                          <Typography color="text.secondary">{group.values.map(tPhrase).join(', ')}</Typography>
                        </Box>
                      </Grid>
                    ))}
                  </Grid>
                </Stack>
              )}
            </Grid>
          </Grid>
        );
      }

      if (personalColorStep === 2) {
        const personalColorKey = personalColorResult
          ? `${personalColorResult.tone}-${personalColorResult.subtype}`
          : '';
        const faceProductSet = FACE_PRODUCT_MAP[personalColorKey] ?? DEFAULT_FACE_PRODUCT_SET;
        const shapeTags = faceShape?.detected ? faceShape.tags.join(' ') : null;
        const shapeSummary = faceShape?.detected
          ? faceShape.summary
          : faceShape
            ? faceShape.summary
            // 저장된 퍼스널 컬러로 들어오면 사진이 없다 — '분석 중'으로 두면 영영 안 끝난다.
            : personalColorResult && personalColorCount === 0
              ? '저장된 퍼스널 컬러로 진행 중이라 얼굴형 분석은 건너뛰었습니다. 사진을 넣으면 얼굴형까지 함께 분석합니다.'
              : personalColorResult
                ? '얼굴형을 분석하고 있어요…'
                : 'AI 퍼스널컬러 분석을 먼저 진행하면 사진을 바탕으로 얼굴형이 표시됩니다.';
        const ratioRows = faceShape?.detected && faceShape.ratios.length
          ? faceShape.ratios
          : [
              { label: '상/중/하안부 비율', width: 80 },
              { label: '눈 사이/눈 크기', width: 72 },
              { label: '얼굴 가로/세로', width: 78 },
              { label: '턱선/광대 대비', width: 64 },
            ];
        const blusherTip = faceShape?.detected
          ? faceShape.blusher_tip
          : '웃을 때 볼 중앙보다 살짝 바깥에 생기 있게 올려 부드러운 인상을 살려주세요.';
        const shadingTip = faceShape?.detected
          ? faceShape.shading_tip
          : '턱선 양옆과 광대 외곽에 부드럽게 넣어 얼굴 윤곽을 자연스럽게 정리해 보세요.';

        const toneMatchLabel = personalColorResult
          ? `${t(personalColorResult.label)} ${t('매치')}`
          : t('추천');
        const blushColors = personalColorResult?.makeup.blush ?? [];
        const blusherRows = (blushColors.length ? blushColors.slice(0, 2) : ['생기 코랄', '맑은 핑크']).map(
          (color, i) => ({
            brand: faceProductSet.blushBrands[i] ?? faceProductSet.blushBrands[0],
            desc: `${color} 톤으로 생기 강조`,
          }),
        );
        const shadingRows = faceProductSet.shadingColors.map((color, i) => ({
          brand: faceProductSet.shadingBrands[i] ?? faceProductSet.shadingBrands[0],
          desc: `${color} 음영으로 턱선·광대 외곽 정리`,
        }));

        return (
          <Box className="face-shape-screen">
            <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', sm: 'center' }} spacing={1.5}>
              <Stack direction="row" spacing={1} className="kiosk-sub-tabs">
                {['내 퍼스널 컬러', '내 얼굴형 분석', '메이크업 무드 선택', '아이템 매칭'].map((tab) => (
                  <Chip key={tab} label={tab} className={tab === '내 얼굴형 분석' ? 'selected' : ''} />
                ))}
              </Stack>
              <Button variant="text" color="inherit">{t('나가기')}</Button>
            </Stack>

            <Box sx={{ mt: 3 }}>
              <Typography variant="caption" color="primary" fontWeight={900}>{t('내 얼굴형 분석')}</Typography>
              <Typography variant="h5" fontWeight={900} sx={{ mt: 0.8 }}>
                {shapeTags ? `내 얼굴형 유형은 ${shapeTags}` : '내 얼굴형 분석'}
              </Typography>
              <Typography color="text.secondary" sx={{ mt: 0.6 }}>
                {shapeSummary}
              </Typography>
            </Box>

            <Grid container spacing={3} sx={{ mt: 1 }}>
              <Grid item xs={12} md={4}>
                <Box className="face-diagram">
                  <Box className="face-outline">
                    <Box className="hair-line" />
                    <Box className="brow left" />
                    <Box className="brow right" />
                    <Box className="eye left" />
                    <Box className="eye right" />
                    <Box className="nose" />
                    <Box className="mouth" />
                  </Box>
                  <Box className="measure-line horizontal top" />
                  <Box className="measure-line horizontal mid" />
                  <Box className="measure-line vertical left" />
                  <Box className="measure-line vertical right" />
                </Box>
              </Grid>
              <Grid item xs={12} md={8}>
                <Box className="face-ratio-panel">
                  <Typography fontWeight={900}>{t('얼굴 비율 측정')}</Typography>
                  {ratioRows.map((row) => (
                    <Box className="face-ratio-row" key={t(row.label)}>
                      <Typography variant="body2">{t(row.label)}</Typography>
                      <Box className="face-ratio-track">
                        <Box sx={{ width: `${row.width}%` }} />
                      </Box>
                    </Box>
                  ))}
                </Box>
              </Grid>
            </Grid>

            <Box sx={{ mt: 3 }}>
              <Typography variant="h5" fontWeight={900}>{t('얼굴형에 맞춘 메이크업 제안이에요!')}</Typography>
              <Typography color="text.secondary" sx={{ mt: 0.5 }}>
                {t('AI가 얼굴형이나 피부톤에 맞는 메이크업 팁과 추천템을 제안해드려요.')}
              </Typography>

              <Stack direction="row" spacing={1} sx={{ mt: 2 }} className="makeup-tabs">
                <Chip label={t('블러셔')} className="selected" />
                <Chip label={t('쉐딩')} />
              </Stack>

              <Grid container spacing={2} sx={{ mt: 0.5 }}>
                <Grid item xs={12} md={6}>
                  <Box className="face-makeup-section">
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Box className="section-index">1</Box>
                      <Typography fontWeight={900}>{t('블러셔')}</Typography>
                    </Stack>
                    <Typography color="text.secondary" sx={{ mt: 1 }}>
                      {blusherTip}
                    </Typography>
                    <Stack spacing={1.2} sx={{ mt: 2 }}>
                      {blusherRows.map((row) => (
                        <Box className="face-product-row" key={row.brand}>
                          <Box className="product-swatch" sx={{ backgroundColor: faceProductSet.blushSwatch }} />
                          <Box>
                            <Typography fontWeight={900}>{row.brand}</Typography>
                            <Typography variant="body2" color="text.secondary">{row.desc}</Typography>
                            <Typography variant="caption" color="error">● {toneMatchLabel}</Typography>
                          </Box>
                        </Box>
                      ))}
                    </Stack>
                  </Box>
                </Grid>
                <Grid item xs={12} md={6}>
                  <Box className="face-makeup-section">
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Box className="section-index">2</Box>
                      <Typography fontWeight={900}>{t('쉐딩')}</Typography>
                    </Stack>
                    <Typography color="text.secondary" sx={{ mt: 1 }}>
                      {shadingTip}
                    </Typography>
                    <Stack spacing={1.2} sx={{ mt: 2 }}>
                      {shadingRows.map((row) => (
                        <Box className="face-product-row" key={row.brand}>
                          <Box className="product-swatch" sx={{ backgroundColor: faceProductSet.shadingSwatch }} />
                          <Box>
                            <Typography fontWeight={900}>{row.brand}</Typography>
                            <Typography variant="body2" color="text.secondary">{row.desc}</Typography>
                            <Typography variant="caption" color="error">● {toneMatchLabel}</Typography>
                          </Box>
                        </Box>
                      ))}
                    </Stack>
                  </Box>
                </Grid>
              </Grid>
            </Box>

            <Button fullWidth variant="contained" className="print-card-button" sx={{ mt: 3 }}>
              {t('진단카드 출력하기')}
            </Button>
          </Box>
        );
      }

      if (personalColorStep === 3) {
        const activeRecommendation =
          styleMoodRecommendations.find((item) => item.mood.id === selectedMood) ?? styleMoodRecommendations[0] ?? null;
        const activeMood = activeRecommendation?.mood ?? null;
        return (
          <Box className="style-consult-screen">
            <Typography variant="caption" color="primary" fontWeight={900}>{t('메이크업 무드 선택')}</Typography>
            <Typography variant="h5" fontWeight={900} sx={{ mt: 0.8 }}>
              AI 스타일 컨설턴트가<br />추천하는 메이크업 무드에요!
            </Typography>
            <Chip className="style-consult-hint" label={t('퍼스널컬러 분석 결과로 상위 3개 무드를 골랐습니다')} sx={{ mt: 2 }} />

            <Grid container spacing={2} sx={{ mt: 0.5 }}>
              {styleMoodRecommendations.map(({ mood, reason }, index) => (
                <Grid item xs={12} sm={4} key={mood.id}>
                  <Box
                    className={`style-mood-card${selectedMood === mood.id ? ' selected' : ''}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => selectStyleMood(mood)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        selectStyleMood(mood);
                      }
                    }}
                  >
                    {moodThumbnails[mood.id] ? (
                      <Box className="style-mood-thumb photo">
                        <img src={moodThumbnails[mood.id]} alt={`${t(mood.label)} 적용`} />
                      </Box>
                    ) : (
                      <Box className={`style-mood-thumb ${mood.thumbClass}`} />
                    )}
                    <Typography className="style-mood-label" fontWeight={900}>{t(mood.label)}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {index + 1}순위 · {reason}
                    </Typography>
                  </Box>
                </Grid>
              ))}
            </Grid>

            {activeMood && (
              <Box sx={{ mt: 3 }}>
                <Alert severity="success" icon={<Sparkles size={18} />}>
                  {t('AI가')} ‘{t(activeMood.label)}’ {t('무드를 우선 추천했어요.')} {t(activeRecommendation?.reason ?? activeMood.vibe)}
                </Alert>

                <Button
                  variant="contained"
                  sx={{ mt: 2 }}
                  onClick={() => setPersonalColorStep(4)}
                  disabled={loading === 'style-mood-items'}
                >
                  {loading === 'style-mood-items'
                    ? '추천 제품 불러오는 중…'
                    : '아이템 매칭에서 추천 제품 보기 →'}
                </Button>
              </Box>
            )}
          </Box>
        );
      }

      if (personalColorStep === 4) {
        // Step 4는 얼굴분석(퍼스널컬러) 기반 추천으로 고정한다. 무드는 Step 3 메이크업
        // 미리보기 전용이며 아이템 매칭에는 관여하지 않는다.
        const activeMood = STYLE_MOODS.find((mood) => mood.id === selectedMood) ?? null;
        const items = activeMood ? moodItems : personalColorItems;
        const itemsLoading = loading === (activeMood ? 'style-mood-items' : 'personal-color-items');
        const refreshItems = () => (activeMood ? selectStyleMood(activeMood) : loadPersonalColorItems());
        const isJapanRegion = itemRegion === 'jp';
        const groupedProducts = groupItemMatchProducts(items?.products ?? [], isMaleItems);
        // 영어 키워드로 매칭된 카드의 배지를 한국어로 되돌린다(KR 한/영 쌍 검색의 부작용).
        const koBadgeByEn = koreanKeywordByEnglish(personalColorItemKeywords(itemRegion));
        return (
          <Box>
            <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', sm: 'center' }} spacing={1.5}>
              <Box>
                <Typography variant="h5" fontWeight={900}>{t('Step 4. 아이템 매칭')}</Typography>
                <Typography color="text.secondary" sx={{ mt: 0.5 }}>
                  {t(isJapanRegion
                    ? itemPlatform === 'matsukiyo'
                      ? '마츠키요 상품 연동은 준비 중입니다. 실제 입점 확인 후 이 탭에만 표시합니다.'
                      : itemPlatform === 'oliveyoung'
                        ? '올리브영 글로벌 상품 연동은 준비 중입니다. 일본/한국 양쪽에서 선택할 수 있게 열어두었습니다.'
                        : '얼굴분석(퍼스널컬러) 결과에 맞춰 일본 라쿠텐 뷰티 상품을 추천합니다.'
                    : '얼굴분석(퍼스널컬러) 결과에 맞춰 한국(네이버) 뷰티 상품을 추천합니다.')}
                </Typography>
              </Box>
              <Stack direction="row" spacing={1.5} alignItems="center">
                {itemPlatformFilter}
                <Button
                  variant="outlined"
                  onClick={refreshItems}
                  disabled={!personalColorResult || itemsLoading}
                >
                  {t('상품 불러오기')}
                </Button>
              </Stack>
            </Stack>

            {activeMood && personalColorResult && (
              <Alert severity="success" sx={{ mt: 2 }}>
                {t(displaySeasonLabel(personalColorResult.label))}{t('분석 결과와')} ‘{t(activeMood.label)}’ {t('무드를 함께 반영해 색상 적합도 순으로 추천합니다.')}
              </Alert>
            )}

            {/* 상한은 컬럼 수를 따르므로(남성 4 / 여성 5) 문구도 숫자를 박지 않고 조립한다. */}
            <Alert severity="info" sx={{ mt: 2 }}>
              {t('결과지에 담을 상품을 최대')} {reportMax}{t('개까지 체크할 수 있어요.')}{' '}
              {t('현재')} {reportPicks.length}{t('개 선택됨.')}
            </Alert>

            <Grid container spacing={1.5} className="item-match-columns" sx={{ mt: 2 }}>
              {itemMatchGroups.map((group) => (
                <Grid item xs={12} sm={6} md={12 / itemMatchGroups.length} key={group.key}>
                  <Box className="item-match-column">
                    <Box className="kiosk-match-card compact">
                      <Typography fontWeight={900}>{t(group.label)}{group.showColor ? ' color' : ''}</Typography>
                      <Typography color="text.secondary" sx={{ mt: 1 }}>{group.values.map(tPhrase).join(', ')}</Typography>
                    </Box>
                    <Stack spacing={2} className="item-match-product-stack">
                      {groupedProducts[group.key].map((product) => (
                        <RakutenProductCard
                          key={`${product.id}-${product.keyword}`}
                          product={product}
                          selectedPlatform={itemPlatform}
                          badgeLabel={itemMatchBadgeFor(product, koBadgeByEn, itemRegion)}
                          checked={isPicked(product)}
                          // 상한에 도달하면 새 체크를 막는다(피부케어 결과지와 동일 UX).
                          disabled={!isPicked(product) && reportPicks.length >= reportMax}
                          onCheckedChange={(checked) => toggleReportProduct(product, checked)}
                        />
                      ))}
                    </Stack>
                  </Box>
                </Grid>
              ))}
            </Grid>

            {itemsLoading && <LinearProgress sx={{ mt: 2 }} />}

            {items && !items.configured && (
              <Alert severity="warning" sx={{ mt: 2 }}>
                {t('라쿠텐 API 키가 백엔드에 설정되지 않았습니다. Docker 재시작 시 .env 값이 전달되는지 확인해 주세요.')}
              </Alert>
            )}

            {items && items.configured && !items.products.length && !itemsLoading && (
              <Alert severity="info" sx={{ mt: 2 }}>{items.message}</Alert>
            )}

          </Box>
        );
      }

      const activeMood = STYLE_MOODS.find((mood) => mood.id === selectedMood) ?? styleMoodRecommendations[0]?.mood ?? STYLE_MOODS[0];
      const reportDate = new Date().toISOString().slice(0, 10);
      const quality = Math.round((personalColorResult?.metrics.capture_quality ?? 0.72) * 100);
      const seasonTag = displaySeasonLabel(personalColorResult?.label);
      const faceTag = faceShapeLabel(faceShape?.detected ? faceShape.shape : undefined);
      const reportProfile = reportSeasonProfile(personalColorResult);
      const faceTypeTags = [
        `#${t(seasonTag).replace(/\s+/g, '')}`,
        t(faceImpressionTag(faceShape)),
        `#${t(faceTag)}`,
      ];
      const moodCopy = reportMoodCopy(activeMood);
      const reportMakeupRows = [
        { label: '립 메이크업', values: personalColorResult?.makeup.lip ?? ['와인 로즈', '말린 장미', '뮤트 플럼'] },
        { label: '블러셔', values: personalColorResult?.makeup.blush ?? ['페일 체리', '푸시아 로즈', '로즈 핑크'] },
        { label: '아이 메이크업', values: personalColorResult?.makeup.eye ?? ['뮤트 플럼', '베리 로즈', '말린 라일락'] },
        { label: '네일', values: personalColorResult?.makeup.nail ?? ['버건디', '체리 레드', '딥 플럼'] },
      ];

      return (
        <Box className="print-report-stage">
          <Box className="print-report-card">
            <Box className="report-top">
              <Box>
                <Typography className="report-kicker">Date /</Typography>
                <Typography className="report-date">{reportDate}</Typography>
              </Box>
              <Box>
                <Typography className="report-kicker">Face Type /</Typography>
                <Typography className="report-face">{faceTypeTags.join(' ')}</Typography>
              </Box>
              <Typography className="report-brand">YoPalette</Typography>
            </Box>

            <Box className="report-grid">
              <Box className="report-left">
                <Box className="report-photo">
                  {personalColorPreview ? <img src={personalColorPreview} alt={t('분석 사진')} /> : <Sparkles size={34} />}
                </Box>
                <Typography className="report-section-title">{t('진단 요약')}</Typography>
                <Typography className="report-copy">
                  {t(reportProfile.moodLine)}
                </Typography>
                <Box className="report-tags">
                  {reportProfile.tags.map((tag) => (
                    <span key={tag}>{t(tag)}</span>
                  ))}
                </Box>
                <Typography className="report-copy">
                  {personalColorResult?.advice?.[0] ?? t(reportProfile.colorLine)}
                </Typography>
                <Stack direction="row" spacing={0.8} sx={{ mt: 1.2 }} flexWrap="wrap" useFlexGap>
                  {personalColorResult?.alternate_label && (
                    <Chip size="small" label={`${t('또는')} ${t(personalColorResult.alternate_label)}`} />
                  )}
                  <Chip size="small" label={`${t('품질')} ${quality}%`} variant="outlined" />
                </Stack>
                <Box className="report-palette">
                  {(personalColorResult?.palette ?? ['#E0A6B1', '#C95C7E', '#A9B5C8', '#4D5D77']).map((color) => (
                    <Box key={color} sx={{ backgroundColor: color }} />
                  ))}
                </Box>
              </Box>

              <Box className="report-main">
                <Box className="report-title-row">
                  <Box>
                    <Typography className="report-section-title">{t('선택한 무드')}</Typography>
                    <Typography className="report-title">
                      {moodCopy.composed ? `${t(moodCopy.label)} ${t('무드 메이크업')}` : t(moodCopy.label)}
                    </Typography>
                  </Box>
                  <Box>
                    <Box className="report-mood-thumb">
                      {myFaceMakeup?.mood === activeMood.id ? (
                        <img src={myFaceMakeup.image} alt={`내 사진에 ${activeMood.label} 적용`} />
                      ) : moodThumbnails[activeMood.id] ? (
                        <img src={moodThumbnails[activeMood.id]} alt={activeMood.label} />
                      ) : (
                        <Box className={`style-mood-thumb ${activeMood.thumbClass}`} />
                      )}
                    </Box>
                    {personalColorFile ? (
                      <Button
                        size="small"
                        fullWidth
                        disabled={myFaceLoading}
                        onClick={() => applyMoodToMyFace(activeMood.id)}
                        sx={{ mt: 0.6, fontSize: 12 }}
                      >
                        {myFaceLoading
                          ? '적용 중…'
                          : myFaceMakeup?.mood === activeMood.id
                            ? '모델 사진 보기'
                            : '내 사진으로 보기'}
                      </Button>
                    ) : null}
                    {myFaceError ? (
                      <Typography sx={{ mt: 0.4, fontSize: 11, color: 'error.main', textAlign: 'center' }}>
                        {myFaceError}
                      </Typography>
                    ) : null}
                  </Box>
                </Box>
                <Typography className="report-copy strong">
                  {moodCopy.composed
                    ? `${t(moodCopy.description)} ${t('분위기를 살려 퍼스널 컬러와 어울리는 메이크업으로 정리했어요.')}`
                    : t(moodCopy.description)}
                </Typography>
                <Typography className="report-copy">
                  {t(seasonTag)} {t('타입의 특성과 선택한 무드를 바탕으로')} {t(reportProfile.finishLine)}
                </Typography>

                <Divider sx={{ my: 1.6 }} />

                <Typography className="report-section-title">{t('메이크업 톤')}</Typography>
                <Box className="report-makeup-grid">
                  {reportMakeupRows.map((group) => (
                    <Box key={t(group.label)}>
                      <Typography className="report-mini-title">{t(group.label)}</Typography>
                      <Typography className="report-copy">{group.values.slice(0, 3).map(tPhrase).join(' / ')}</Typography>
                    </Box>
                  ))}
                </Box>

                <Typography className="report-section-title product-title">{t('장바구니')}</Typography>
                <Box className={`report-product-grid${reportItems.length > 4 ? ' dense' : ''}`}>
                  {reportItems.length ? reportItems.map((product, index) => (
                    <Box className="report-product" key={`${product.id}-${product.keyword}-${index}`}>
                      <Box className="report-product-image">
                        <ProductImage
                          src={product.image_url}
                          alt={product.name}
                          fallback={<span>{String(index + 1).padStart(2, '0')}</span>}
                        />
                      </Box>
                      <Box className="report-product-info">
                        <span>{String(index + 1).padStart(2, '0')}</span>
                        <Typography>{product.brand} {product.name}</Typography>
                      </Box>
                    </Box>
                  )) : ['립 메이크업 추천템', '블러셔 추천템', '아이 메이크업 추천템', '베이스 추천템'].map((item, index) => (
                    <Box className="report-product empty" key={item}>
                      <Box className="report-product-image">
                        <span>{String(index + 1).padStart(2, '0')}</span>
                      </Box>
                      <Box className="report-product-info">
                        <span>{String(index + 1).padStart(2, '0')}</span>
                        <Typography>{item}</Typography>
                      </Box>
                    </Box>
                  ))}
                </Box>

                <Box className="report-bottom">
                  <Box>
                    <Box
                      component="img"
                      className="report-qr-img"
                      src={qrImageUrl(`${window.location.origin}/#report`)}
                      alt={t('모바일 레포트 QR')}
                      sx={{ width: 74, height: 74, display: 'block', border: '6px solid #fff', background: '#fff', borderRadius: '4px' }}
                    />
                    <Typography className="report-qr-label">{t('모바일 레포트에서 자세한 진단결과 보기')}</Typography>
                  </Box>
                  <Box>
                    <Box className="report-qr-img" sx={{ display: 'block', border: '6px solid #fff', background: '#fff', borderRadius: '4px', width: 74, height: 74 }}>
                      <CartHandoffQr items={cartHandoffItems(reportItems, PC_REPORT_MAX)} linked={Boolean(authUser?.web_member_id)} size={74} />
                    </Box>
                    <Typography className="report-qr-label">{t('QR 을 찍으면 내 계정 장바구니에 담깁니다')}</Typography>
                  </Box>
                </Box>
              </Box>
            </Box>
          </Box>
          <Typography color="text.secondary" sx={{ mt: 2, textAlign: 'center' }}>
            {t(reportPicks.length
              ? 'Step 4에서 결과지에 담은 상품만 표시됩니다.'
              : 'Step 4에서 상품을 담으면 여기에 표시됩니다.')}
          </Typography>

          {/* 결과지를 본 뒤 바로 질문할 수 있게 상담을 같은 화면에서 연다. */}
          <Stack alignItems="center" sx={{ mt: 2 }}>
            <Button
              variant={pcConsultOpen ? 'outlined' : 'contained'}
              startIcon={<MessageSquare size={18} />}
              onClick={() => setPcConsultOpen((open) => !open)}
            >
              {pcConsultOpen ? t('상담 닫기') : t('AI 상담하기')}
            </Button>
          </Stack>

          {pcConsultOpen && (
            <Paper elevation={0} className="pc-consult" sx={{ mt: 2 }}>
              <Typography variant="h6" fontWeight={800}>{t('AI 뷰티 상담')}</Typography>
              <Typography color="text.secondary" variant="body2" sx={{ mt: 0.5 }}>
                {t('진단 결과를 바탕으로 메이크업, 컬러 활용, 제품 사용법을 질문할 수 있습니다.')}
              </Typography>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mt: 2 }}>
                <TextField
                  fullWidth
                  size="small"
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  placeholder={t('예: 이 퍼스널컬러에 어울리는 립 발색은 어떻게 고르나요?')}
                />
                <Button
                  variant="contained"
                  startIcon={<Send size={16} />}
                  onClick={handlePersonalColorChat}
                  disabled={loading === 'chat'}
                >
                  {t('질문')}
                </Button>
              </Stack>
              {loading === 'chat' && <LinearProgress sx={{ mt: 1.5 }} />}
              {answer && (
                <Stack spacing={1} sx={{ mt: 2 }}>
                  <Alert icon={<MessageSquare size={18} />} severity="success">{answer}</Alert>
                  {!!answerSources.length && (
                    <Box>
                      <Typography variant="caption" color="text.secondary">{t('참고 근거')}</Typography>
                      <Stack direction="row" flexWrap="wrap" gap={0.75} sx={{ mt: 0.5 }}>
                        {answerSources.map((source) => (
                          <Chip key={source} label={source} size="small" variant="outlined" />
                        ))}
                      </Stack>
                    </Box>
                  )}
                </Stack>
              )}
            </Paper>
          )}
        </Box>
      );
    };

    return (
      <Box className="app-shell">
      <AppLangToggle authUser={authUser} />
        <Container maxWidth="lg" sx={{ py: { xs: 2, md: 4 } }}>
          <Paper elevation={0} className="page-panel kiosk-header">
            <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}>
              <Box>
                <Chip label="YoPalette" color="primary" variant="outlined" sx={{ width: 'fit-content', mb: 1 }} />
                <Typography variant="h4" fontWeight={900}>{t('뷰티 진단서 받기')}</Typography>
                <Typography color="text.secondary" sx={{ mt: 0.5 }}>
                  {t('문서의 키오스크 화면 순서에 맞춰 개인정보 입력부터 퍼스널컬러, 얼굴형, 스타일, 아이템, 출력까지 이어집니다.')}
                </Typography>
              </Box>
              <Button variant="outlined" onClick={goHome}>{t('홈으로')}</Button>
            </Stack>
            <Stepper activeStep={personalColorStep} alternativeLabel sx={{ mt: 3 }}>
              {personalColorSteps.map((step, index) => (
                <Step key={step} completed={index < personalColorStep}>
                  <StepLabel
                    onClick={() => {
                      if (index <= personalColorStep || (index === personalColorStep + 1 && canMoveNext)) {
                        setPersonalColorStep(index);
                      }
                    }}
                    sx={{ cursor: index <= personalColorStep + 1 ? 'pointer' : 'default' }}
                  >
                    {t(step)}
                  </StepLabel>
                </Step>
              ))}
            </Stepper>
          </Paper>

          {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}

          <Paper elevation={0} className="page-panel kiosk-flow-panel" sx={{ mt: 2 }}>
            {renderPersonalStepContent()}
          </Paper>

          <Paper elevation={0} className="page-panel kiosk-nav" sx={{ mt: 2 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
              <Button
                variant="outlined"
                startIcon={<ArrowLeft size={16} />}
                disabled={personalColorStep === 0}
                onClick={() => setPersonalColorStep((step) => Math.max(step - 1, 0))}
              >
                {t('이전')}
              </Button>
              <Typography variant="body2" color="text.secondary">
                {personalColorStep + 1} / {personalColorSteps.length}
              </Typography>
              <Button
                variant="contained"
                endIcon={<ArrowRight size={16} />}
                disabled={personalColorStep >= personalColorSteps.length - 1 || !canMoveNext}
                onClick={() => setPersonalColorStep((step) => Math.min(step + 1, personalColorSteps.length - 1))}
              >
                {t('다음')}
              </Button>
            </Stack>
          </Paper>
        </Container>
      </Box>
    );
  }

  function renderFacePage() {
    return (
      <Grid container spacing={2}>
        <Grid item xs={12} lg={7}>
          <Paper className="page-panel" elevation={0}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
              <Box>
                <Typography variant="h5" fontWeight={800}>
                  {t('피부 케어 입력')}
                </Typography>
                <Typography color="text.secondary" sx={{ mt: 0.5 }}>
                  {t('분석할 부위를 선택하고 사진을 1~5장 등록해 주세요.')}
                </Typography>
              </Box>
              <Button size="small" variant="outlined" startIcon={<RefreshCcw size={14} />} onClick={() => startCamera()}>
                {t('새로고침')}
              </Button>
            </Stack>

            <ToggleButtonGroup
              color="primary"
              exclusive
              fullWidth
              size="small"
              value={analysisMode}
              onChange={(_event, value) => {
                if (value) setAnalysisMode(value as AnalysisMode);
              }}
              sx={{ mt: 2 }}
            >
              <ToggleButton value="face">{t('얼굴 피부 케어')}</ToggleButton>
              <ToggleButton value="body">{t('바디 피부 케어')}</ToggleButton>
            </ToggleButtonGroup>

            <Box className="camera-box large-camera" sx={{ mt: 2 }}>
              <video
                ref={videoRef}
                className="camera-video"
                autoPlay
                playsInline
                muted
                onLoadedMetadata={() => {
                  videoRef.current?.play().catch(() => undefined);
                }}
              />
              {!cameraReady && (
                <Stack className="camera-empty" alignItems="center" spacing={1}>
                  <Camera size={32} />
                  <Typography variant="body2" color="text.secondary">{t('카메라 권한을 기다리는 중입니다')}</Typography>
                </Stack>
              )}
            </Box>
            <canvas ref={canvasRef} hidden />
          </Paper>
        </Grid>

        <Grid item xs={12} lg={5}>
          <Paper className="page-panel" elevation={0}>
            <Stack spacing={1.5}>
              {cameraDevices.length > 1 && (
                <FormControl fullWidth size="small">
                  <InputLabel>{t('카메라')}</InputLabel>
                  <Select
                    label={t('카메라')}
                    value={selectedDeviceId}
                    onChange={(event) => handleCameraChange(event.target.value)}
                  >
                    {cameraDevices.map((device, index) => (
                      <MenuItem key={device.deviceId} value={device.deviceId}>
                        {device.label || `카메라 ${index + 1}`}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                <Button
                  fullWidth
                  variant="contained"
                  startIcon={<Camera size={16} />}
                  onClick={captureFaceImage}
                  disabled={!cameraReady || faceFiles.length >= 5}
                >
                  {t('웹캠으로 촬영')}
                </Button>
                {cameraNotice && (
                  <Alert severity="info" sx={{ py: 0.4 }}>{t(cameraNotice)}</Alert>
                )}
                <Button
                  fullWidth
                  component="label"
                  variant="outlined"
                  startIcon={<ImagePlus size={16} />}
                  disabled={faceFiles.length >= 5}
                >
                  {t('사진 업로드')}
                  <input
                    hidden
                    accept="image/*"
                    multiple
                    type="file"
                    onChange={(event) => {
                      handleUploadFiles(event.target.files);
                      event.target.value = '';
                    }}
                  />
                </Button>
              </Stack>
              <Alert severity={faceFiles.length >= 3 ? 'success' : 'info'}>
                현재 {faceFiles.length}/5장 선택됨. 분석에는 최소 1장이 필요합니다.
              </Alert>
              {!!faceFiles.length && (
                <Stack direction="row" justifyContent="flex-end">
                  <Button
                    size="small"
                    color="inherit"
                    startIcon={<Trash2 size={14} />}
                    onClick={clearFaceFiles}
                  >
                    {t('전체 삭제')}
                  </Button>
                </Stack>
              )}
              {!!previewUrls.length && (
                <Box className="photo-grid">
                  {previewUrls.map((url, index) => (
                    <Box className="capture-preview" key={url}>
                      <img src={url} alt={`선택한 피부 사진 ${index + 1}`} />
                      <Box minWidth={0}>
                        <Typography variant="body2" noWrap>{faceFiles[index]?.name}</Typography>
                        <Typography variant="caption" color="text.secondary">사진 {index + 1}</Typography>
                      </Box>
                      <Button
                        variant="text"
                        color="inherit"
                        size="small"
                        aria-label={`${index + 1}번째 사진 삭제`}
                        onClick={() => removeFaceFile(index)}
                        sx={{ minWidth: 36 }}
                      >
                        <Trash2 size={16} />
                      </Button>
                    </Box>
                  ))}
                </Box>
              )}
            </Stack>
          </Paper>
        </Grid>
      </Grid>
    );
  }

  function renderAnalysisPage() {
    return (
      <Paper className="page-panel" elevation={0}>
        <Typography variant="h5" fontWeight={800}>{t('피부 분석')}</Typography>
        {loading === 'analyzing' && (
          <Stack spacing={2} sx={{ mt: 3 }}>
            <LinearProgress />
            <Typography color="text.secondary">{t('등록한 피부 사진을 분석하고 추천 후보를 계산하는 중입니다.')}</Typography>
          </Stack>
        )}
        {!loading && analysis ? (
          <Stack spacing={1.5} sx={{ mt: 3 }}>
            {analysis.analysis_mode === 'face' && analysis.scores && (
              <>
                <Box className="score-row">
                  <Box />
                  <Box />
                  <Typography variant="caption" color="text.secondary" textAlign="right" fontWeight={700}>
                    {t('심각도')}
                  </Typography>
                </Box>
                {(Object.entries(analysis.scores) as [keyof SkinScores, number][]).map(([key, value]) => {
                  const band = scoreBand(value);
                  return (
                    <Box className="score-row" key={key}>
                      <Typography variant="body2">{t(scoreLabels[key])}</Typography>
                      <LinearProgress variant="determinate" value={value} color={band.color} sx={{ height: 10, borderRadius: 1 }} />
                      <Typography variant="body2" textAlign="right" color={`${band.color}.main`} fontWeight={700}>{t(band.label)}</Typography>
                    </Box>
                  );
                })}
              </>
            )}
            {analysis.analysis_mode === 'body' && analysis.body_conditions.map((item) => (
              <Box className="score-row" key={item.condition}>
                <Typography variant="body2">{t(item.label)}</Typography>
                <LinearProgress variant="determinate" value={item.probability} sx={{ height: 10, borderRadius: 1 }} />
                <Typography variant="body2" textAlign="right">{item.probability}%</Typography>
              </Box>
            ))}
            <Alert severity={analysis.urgent ? 'error' : analysis.model_available ? 'info' : 'warning'}>{analysis.summary}</Alert>
            {analysis.confidence_note && (
              <Typography variant="caption" color="text.secondary">{analysis.confidence_note}</Typography>
            )}
          </Stack>
        ) : !loading ? (
          <Alert severity="info" sx={{ mt: 3 }}>{t('피부 사진을 등록한 뒤 분석을 실행해 주세요.')}</Alert>
        ) : null}
      </Paper>
    );
  }

  function renderRecommendationPage() {
    // 컬럼(product_columns)이 있으면 카테고리별 컬럼으로 통일해 보여준다(face·body 공통).
    // 컬럼 없음(예: 악성의심 안내·카탈로그 부족): 기존 상품 그리드 유지.
    const showColumns = !!recommendation?.product_columns?.length;
    return (
      <Grid container spacing={2}>
        {/* 추천 영역은 전체폭(컬럼이 좁아지지 않게). 추천 기록은 아래로 스택. */}
        <Grid item xs={12}>
          <Paper className="page-panel" elevation={0}>
            <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', sm: 'center' }} gap={1.5}>
              <Typography variant="h5" fontWeight={800}>{t('맞춤 추천')}</Typography>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                <FormControl size="small" sx={{ minWidth: 130 }}>
                  <InputLabel>{t('지역')}</InputLabel>
                  <Select
                    label={t('지역')}
                    value={skinRegion}
                    onChange={(event) => handleSkinRegionChange(event.target.value as ItemRegion)}
                    disabled={loading === 'recommend' || loading === 'analyzing'}
                  >
                    {ITEM_REGION_FILTERS.map((region) => (
                      <MenuItem key={region.value} value={region.value}>{region.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <FormControl size="small" sx={{ minWidth: 160 }}>
                  <InputLabel>{t('구매 플랫폼')}</InputLabel>
                  <Select
                    label={t('구매 플랫폼')}
                    value={selectedPlatform}
                    onChange={(event) => handlePlatformChange(event.target.value as ItemPlatform)}
                    disabled={loading === 'recommend' || loading === 'analyzing'}
                  >
                    {(skinRegion === 'jp' ? JP_ITEM_PLATFORM_FILTERS : KR_ITEM_PLATFORM_FILTERS).map((platform) => (
                      <MenuItem key={platform.value} value={platform.value}>{platform.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Stack>
            </Stack>
            {loading === 'recommend' && <LinearProgress sx={{ mt: 2 }} />}
            {recommendation ? (
              <Stack spacing={2} sx={{ mt: 2 }}>
                <Alert severity={analysis?.urgent ? 'error' : analysis?.analysis_mode === 'body' && !recommendation.products.length ? 'warning' : 'success'}>{recommendation.explanation}</Alert>
                {recommendation.ingredients.length > 0 && (
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>{t('추천 성분')}</Typography>
                    <Stack direction="row" flexWrap="wrap" gap={1}>
                      {recommendation.ingredients.map((ingredient) => (
                        <Chip key={ingredient.id} label={ingredient.name} color="primary" variant="outlined" />
                      ))}
                    </Stack>
                  </Box>
                )}
                <Divider />
                {/* 상품 카테고리 컬럼(퍼스널컬러 립/아이/베이스처럼): 카테고리별 추천 상품 여러 개. */}
                {showColumns && (
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>{t('카테고리별 추천 상품')}</Typography>
                    <Alert severity="info" sx={{ mb: 1.5, py: 0.4 }}>
                      {t('결과지에 담을 상품을 최대 5개까지 체크할 수 있어요.')}{' '}
                      {t('현재')} {skinReportIds.length}{t('개 선택됨.')}
                    </Alert>
                    <Grid container spacing={1.5} className="item-match-columns">
                      {recommendation.product_columns!.map((col) => (
                        <Grid item xs={12} sm={6} md={12 / recommendation.product_columns!.length} key={col.key}>
                          <Box className="item-match-column">
                            <Box className="kiosk-match-card compact" sx={{ minHeight: 66 }}>
                              <Typography fontWeight={900}>{t(col.label)}</Typography>
                              <Typography color="text.secondary" variant="body2" sx={{ mt: 0.5 }}>
                                {col.reason || t(SKIN_COLUMN_HINT[col.key] ?? '')}
                              </Typography>
                            </Box>
                            <Stack spacing={2} className="item-match-product-stack">
                              {col.products.length ? col.products.map((rp) => {
                                const rlinks = rp.platform_links ?? {};
                                const rplatforms = (rp.matched_platforms?.length ? rp.matched_platforms : Object.keys(rlinks))
                                  .filter((key): key is ItemPlatform => key !== 'all' && key in ITEM_PLATFORM_META && Boolean(rlinks[key]))
                                  .filter((key) => selectedPlatform === 'all' || key === selectedPlatform)
                                  .map((key) => ITEM_PLATFORM_META[key]);
                                return (
                                  <Box className="rakuten-product-card" key={rp.id}>
                                    <FormControlLabel
                                      className="report-pick-control"
                                      control={
                                        <Checkbox
                                          size="small"
                                          checked={skinReportIds.includes(rp.id)}
                                          disabled={!skinReportIds.includes(rp.id) && skinReportIds.length >= SKIN_REPORT_MAX}
                                          onChange={(event) => toggleSkinReportProduct(rp.id, event.target.checked)}
                                        />
                                      }
                                      label={t('결과지에 담기')}
                                    />
                                    <Box className="rakuten-product-image">
                                      <ProductImage src={rp.image_url} alt={rp.name} fallback={<Sparkles size={26} />} />
                                    </Box>
                                    <Typography fontWeight={900} className="rakuten-product-title">{rp.name}</Typography>
                                    {/* 가격 미표시 — 아이템매칭 카드와 같은 이유(카드 하나에 판매처가
                                        여럿이라 표시가가 어느 곳에서도 맞지 않는다). */}
                                    <Typography variant="body2" color="text.secondary" noWrap>
                                      {rp.brand}
                                    </Typography>
                                    {rp.avg_rating != null && (
                                      <Typography variant="caption" color="text.secondary">
                                        ★ {rp.avg_rating.toFixed(1)}
                                        {rp.review_count != null && ` (${rp.review_count.toLocaleString()})`}
                                      </Typography>
                                    )}
                                    {!!rp.reason_tags?.length && (
                                      <Stack direction="row" gap={0.5} flexWrap="wrap" sx={{ mt: 0.5 }}>
                                        {rp.reason_tags.slice(0, 2).map((tag) => (
                                          <Chip key={tag} size="small" label={tag} variant="outlined" />
                                        ))}
                                      </Stack>
                                    )}
                                    <Stack direction="row" gap={0.8} flexWrap="wrap" sx={{ mt: 'auto', pt: 1.2 }}>
                                      {rplatforms.map((platform) => (
                                        <Button
                                          key={platform.key}
                                          component="a"
                                          href={rlinks[platform.key]}
                                          target="_blank"
                                          rel="noreferrer"
                                          size="small"
                                          variant="contained"
                                          disableElevation
                                          startIcon={
                                            <Box sx={{ width: 16, height: 16, borderRadius: '4px', bgcolor: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                              <Box component="img" src={faviconUrl(platform.domain)} alt="" width={12} height={12} sx={{ display: 'block' }} />
                                            </Box>
                                          }
                                          sx={{ bgcolor: platform.bg, color: platform.fg, fontWeight: 700, minWidth: 0, '&:hover': { bgcolor: platform.hover } }}
                                        >
                                          {platform.label}
                                        </Button>
                                      ))}
                                    </Stack>
                                  </Box>
                                );
                              }) : (
                                <Typography variant="body2" color="text.secondary">{t('이 카테고리에 맞는 상품이 없어요.')}</Typography>
                              )}
                            </Stack>
                          </Box>
                        </Grid>
                      ))}
                    </Grid>
                  </Box>
                )}
                {/* body(피부질환) 안내형은 의도적으로 상품이 없으므로 '카탈로그 부족' 문구를 띄우지 않는다. */}
                {!recommendation.products.length && analysis?.analysis_mode !== 'body' && (
                  <Alert severity="info">{t('선택한 플랫폼에 맞는 추천 후보가 아직 부족합니다. 모든 플랫폼으로 넓혀 보거나 상품 카탈로그를 보강해 주세요.')}</Alert>
                )}
                <Grid container spacing={1.5}>
                  {/* 컬럼이 있으면 위 카테고리 컬럼으로 통일하고 평면 그리드는 비운다(중복 방지). */}
                  {(showColumns ? [] : recommendation.products).map((product, index) => {
                    // 퍼스널컬러 카드와 동일한 버튼 체계: 입점 리졸버가 채운 platform_links를
                    // ITEM_PLATFORM_META(라쿠텐 포함)로 렌더하고, 선택 플랫폼으로 필터한다.
                    const links = product.platform_links ?? {};
                    const matched = product.matched_platforms?.length
                      ? product.matched_platforms
                      : Object.keys(links);
                    const visiblePlatforms = matched
                      .filter((key): key is ItemPlatform => key !== 'all' && key in ITEM_PLATFORM_META && Boolean(links[key]))
                      .filter((key) => selectedPlatform === 'all' || key === selectedPlatform)
                      .map((key) => ITEM_PLATFORM_META[key]);
                    return (
                      <Grid item xs={12} sm={6} key={product.id}>
                        <Box className="rakuten-product-card">
                          <Box className="rakuten-product-image">
                            <ProductImage src={product.image_url} alt={product.name} fallback={<Sparkles size={26} />} />
                          </Box>
                          <Stack direction="row" justifyContent="space-between" alignItems="center">
                            <Chip label={`추천 ${index + 1} · ${product.category}`} size="small" sx={{ width: 'fit-content' }} />
                            <Chip size="small" label={`${product.score ?? 0}`} color="secondary" />
                          </Stack>
                          <Typography fontWeight={900} className="rakuten-product-title">{product.name}</Typography>
                          {/* 가격 미표시 — 위와 동일한 이유. */}
                          <Typography variant="body2" color="text.secondary" noWrap>
                            {product.brand}
                          </Typography>
                          {product.avg_rating != null && (
                            <Typography variant="caption" color="text.secondary">
                              ★ {product.avg_rating.toFixed(1)}
                              {product.review_count != null && ` (${product.review_count.toLocaleString()})`}
                            </Typography>
                          )}
                           <Typography
                             variant="body2"
                             sx={{ mt: 0.5, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}
                           >
                             {product.description}
                           </Typography>
                          {!!product.reason_tags?.length && (
                            <Stack direction="row" gap={0.6} flexWrap="wrap" sx={{ mt: 1 }}>
                              {product.reason_tags.slice(0, 4).map((tag) => (
                                <Chip key={tag} size="small" label={tag} variant="outlined" />
                              ))}
                            </Stack>
                          )}
                          {product.evidence_note && (
                            <Typography
                              variant="caption"
                              color="text.secondary"
                              sx={{ mt: 0.8, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}
                            >
                              {product.evidence_note}
                            </Typography>
                          )}
                          <Stack direction="row" gap={0.8} flexWrap="wrap" sx={{ mt: 'auto', pt: 1.2 }}>
                            {visiblePlatforms.map((platform) => (
                              <Button
                                key={platform.key}
                                component="a"
                                href={links[platform.key]}
                                target="_blank"
                                rel="noreferrer"
                                size="small"
                                variant="contained"
                                disableElevation
                                startIcon={
                                  <Box sx={{ width: 16, height: 16, borderRadius: '4px', bgcolor: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                    <Box component="img" src={faviconUrl(platform.domain)} alt="" width={12} height={12} sx={{ display: 'block' }} />
                                  </Box>
                                }
                                sx={{ bgcolor: platform.bg, color: platform.fg, fontWeight: 700, minWidth: 0, '&:hover': { bgcolor: platform.hover } }}
                              >
                                {platform.label}
                              </Button>
                            ))}
                          </Stack>
                        </Box>
                      </Grid>
                    );
                  })}
                </Grid>
              </Stack>
            ) : (
              <Alert severity="info" sx={{ mt: 2 }}>{t('분석 후 추천 상품이 표시됩니다.')}</Alert>
            )}
          </Paper>
        </Grid>
        <Grid item xs={12}>
          <Paper className="page-panel" elevation={0}>
            <Stack direction="row" spacing={1} alignItems="center">
              <History size={18} />
              <Typography variant="h6">{t('추천 기록')}</Typography>
            </Stack>
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {history.slice(0, 5).map((item) => (
                <Box key={item.id}>
                  <Typography variant="body2" fontWeight={700}>{item.recommended_products.slice(0, 2).join(', ')}</Typography>
                  <Typography variant="caption" color="text.secondary">{new Date(item.created_at).toLocaleString('ko-KR')}</Typography>
                </Box>
              ))}
              {!history.length && <Typography color="text.secondary" variant="body2">{t('아직 추천 기록이 없습니다.')}</Typography>}
            </Stack>
          </Paper>
        </Grid>
      </Grid>
    );
  }

  function renderConsultPage() {
    return (
      <Paper className="page-panel" elevation={0}>
        <Typography variant="h5" fontWeight={800}>{t('AI 피부 상담')}</Typography>
        <Typography color="text.secondary" sx={{ mt: 0.5 }}>
          {t('분석 점수를 바탕으로 루틴, 성분 사용 순서, 주의점을 질문할 수 있습니다.')}
        </Typography>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mt: 3 }}>
          <TextField fullWidth size="small" value={message} onChange={(event) => setMessage(event.target.value)} />
          <Button variant="contained" startIcon={<Send size={16} />} onClick={handleChat} disabled={loading === 'chat'}>
            {t('질문')}
          </Button>
        </Stack>
        {answer && (
          <Stack spacing={1} sx={{ mt: 2 }}>
            <Alert icon={<MessageSquare size={18} />} severity="success">{answer}</Alert>
            {!!answerSources.length && (
              <Box>
                <Typography variant="caption" color="text.secondary">{t('참고 근거')}</Typography>
                <Stack direction="row" flexWrap="wrap" gap={0.75} sx={{ mt: 0.5 }}>
                  {answerSources.map((source) => (
                    <Chip key={source} label={source} size="small" variant="outlined" />
                  ))}
                </Stack>
              </Box>
            )}
          </Stack>
        )}
      </Paper>
    );
  }

  function renderVirtualSurgeryPage() {
    const tuningItems = [
      { key: 'faceLine', label: '얼굴 프레임', helper: '광대와 얼굴 폭을 자연스럽게 정리' },
      { key: 'jawBalance', label: '턱 밸런스', helper: '하관 길이와 턱끝 인상을 부드럽게 조정' },
      { key: 'noseContour', label: '코 라인', helper: '콧대와 코끝의 입체감을 과하지 않게 제안' },
      { key: 'blemishCare', label: '점·잡티 제거', helper: '클릭 제거형 피부 보정 후보로 분리' },
    ] as const;

    const recommendationCards = [
      ['01', '얼굴형 균형', '얼굴 폭 대비 하관 비율을 먼저 확인하고, 과한 축소보다 윤곽 정리 중심으로 추천합니다.'],
      ['02', '포인트 보정', '점·잡티처럼 되돌릴 수 있는 보정부터 보여주고, 시술성 변화는 참고 단계로 분리합니다.'],
      ['03', '자연스러움 점수', '변화 강도가 올라갈수록 원래 인상과의 차이를 표시해 소비자가 직접 조절하게 합니다.'],
    ];

    const previewStyle = {
      '--face-line': `${virtualSurgeryTuning.faceLine}%`,
      '--jaw-balance': `${virtualSurgeryTuning.jawBalance}%`,
      '--nose-contour': `${virtualSurgeryTuning.noseContour}%`,
      '--blemish-care': `${virtualSurgeryTuning.blemishCare}%`,
    } as CSSProperties;
    const displayedRecommendationCards = virtualSurgeryResult?.recommendations.length
      ? virtualSurgeryResult.recommendations.map((item, index) => [
          String(index + 1).padStart(2, '0'),
          item.title,
          item.summary,
          item.score,
        ] as const)
      : recommendationCards.map(([no, title, copy]) => [no, title, copy, null] as const);

    return (
      <Box className="app-shell">
        <AppLangToggle authUser={authUser} />
        <Container maxWidth="lg" sx={{ py: { xs: 2, md: 4 } }}>
          <Stack spacing={3}>
            <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }} spacing={2}>
              <Box>
                <Chip label="Beauty Plan Lab" color="primary" variant="outlined" sx={{ mb: 1 }} />
                <Typography variant="h4" fontWeight={900}>{t('가상 성형 추천 시스템')}</Typography>
                <Typography color="text.secondary">
                  {t('사진을 올리기 전에도 추천 흐름을 이해할 수 있도록, 얼굴 비율 분석·자연스러운 변화 강도·점 제거 후보를 한 화면에서 보여줍니다.')}
                </Typography>
              </Box>
              <Button startIcon={<ArrowLeft size={16} />} onClick={goHome}>{t('홈으로')}</Button>
            </Stack>

            <Paper elevation={0} className="virtual-upload-panel">
              <Grid container spacing={2} alignItems="center">
                <Grid item xs={12} md={5}>
                  <Box
                    component="label"
                    className={`virtual-upload-drop${virtualSurgeryDragOver ? ' is-over' : ''}`}
                    onDragOver={(event: React.DragEvent) => { event.preventDefault(); setVirtualSurgeryDragOver(true); }}
                    onDragLeave={() => setVirtualSurgeryDragOver(false)}
                    onDrop={(event: React.DragEvent) => {
                      event.preventDefault();
                      setVirtualSurgeryDragOver(false);
                      const file = event.dataTransfer.files?.[0];
                      if (file) void handleVirtualSurgeryUpload(file);
                    }}
                  >
                    {virtualSurgeryPreview ? (
                      <img src={virtualSurgeryPreview} alt={t('가상 성형 추천에 사용할 얼굴 사진')} />
                    ) : (
                      <Stack alignItems="center" spacing={1.2} sx={{ textAlign: 'center', px: 2 }}>
                        <Box className="virtual-upload-icon"><ImagePlus size={30} /></Box>
                        <Typography variant="h6" fontWeight={900}>{t('얼굴 사진 업로드')}</Typography>
                        <Typography variant="body2" color="text.secondary">
                          {t('정면 얼굴과 밝은 조명의 JPG·PNG 사진을 권장합니다.')}
                        </Typography>
                      </Stack>
                    )}
                    <input
                      hidden
                      type="file"
                      accept="image/*"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void handleVirtualSurgeryUpload(file);
                        event.target.value = '';
                      }}
                    />
                  </Box>
                </Grid>
                <Grid item xs={12} md={7}>
                  <Stack spacing={1.5}>
                    <Typography variant="h6" fontWeight={900}>{t('내 얼굴 기준 추천 생성')}</Typography>
                    <Typography color="text.secondary">
                      {t('업로드하면 얼굴형 지표, 자연스러움 점수, 점·잡티 후보와 전후 미리보기를 생성합니다.')}
                    </Typography>
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                      <Button
                        variant="contained"
                        component="label"
                        startIcon={<ImagePlus size={18} />}
                        disabled={virtualSurgeryLoading}
                      >
                        {virtualSurgeryPreview ? t('다른 사진 선택') : t('사진 선택')}
                        <input
                          hidden
                          type="file"
                          accept="image/*"
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            if (file) void handleVirtualSurgeryUpload(file);
                            event.target.value = '';
                          }}
                        />
                      </Button>
                      <Button
                        variant="outlined"
                        startIcon={<RefreshCcw size={18} />}
                        disabled={!virtualSurgeryFile || virtualSurgeryLoading}
                        onClick={() => void rerunVirtualSurgery()}
                      >
                        {t('현재 강도로 다시 생성')}
                      </Button>
                    </Stack>
                    {virtualSurgeryLoading && <LinearProgress />}
                    {virtualSurgeryResult && (
                      <Alert severity={virtualSurgeryResult.detected ? 'success' : 'warning'}>
                        {virtualSurgeryResult.message}
                      </Alert>
                    )}
                  </Stack>
                </Grid>
              </Grid>
            </Paper>

            <Grid container spacing={2}>
              <Grid item xs={12} md={7}>
                <Paper elevation={0} className="virtual-preview-panel">
                  {virtualSurgeryResult?.detected ? (
                    <Grid container spacing={1.5}>
                      <Grid item xs={12} sm={6}>
                        <Box className="virtual-result-image">
                          <span>Before</span>
                          <img src={virtualSurgeryResult.original_image} alt={t('원본 얼굴 사진')} />
                        </Box>
                      </Grid>
                      <Grid item xs={12} sm={6}>
                        <Box className="virtual-result-image">
                          <span>Recommended</span>
                          <img src={virtualSurgeryResult.preview_image} alt={t('가상 성형 추천 미리보기')} />
                        </Box>
                      </Grid>
                      <Grid item xs={12}>
                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                          {virtualSurgeryResult.face_shape?.shape && (
                            <Chip label={virtualSurgeryResult.face_shape.shape} color="primary" variant="outlined" />
                          )}
                          <Chip label={`자연스러움 ${virtualSurgeryResult.metrics.naturalness_score ?? '-'}점`} variant="outlined" />
                          <Chip label={`점·잡티 후보 ${virtualSurgeryResult.metrics.blemish_candidates ?? 0}개`} variant="outlined" />
                        </Stack>
                      </Grid>
                    </Grid>
                  ) : (
                    <Box className="virtual-face-stage" style={previewStyle}>
                      <Box className="virtual-before">
                        <span>Before</span>
                      </Box>
                      <Box className="virtual-after">
                        <span>Recommended</span>
                      </Box>
                      <Box className="virtual-face-outline">
                        <Box className="virtual-eye virtual-eye-left" />
                        <Box className="virtual-eye virtual-eye-right" />
                        <Box className="virtual-nose" />
                        <Box className="virtual-mouth" />
                        <Box className="virtual-blemish one" />
                        <Box className="virtual-blemish two" />
                      </Box>
                      <Box className="virtual-scan-line" />
                    </Box>
                  )}
                </Paper>
              </Grid>

              <Grid item xs={12} md={5}>
                <Paper elevation={0} className="virtual-control-panel">
                  <Stack spacing={2.25}>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Box className="module-icon"><SlidersHorizontal size={22} /></Box>
                      <Box>
                        <Typography variant="h6" fontWeight={900}>{t('추천 강도')}</Typography>
                        <Typography variant="body2" color="text.secondary">{t('의료 판단이 아닌 비의료 미용 시뮬레이션 기준입니다.')}</Typography>
                      </Box>
                    </Stack>
                    {tuningItems.map((item) => (
                      <Box key={item.key}>
                        <Stack direction="row" justifyContent="space-between" spacing={1}>
                          <Typography fontWeight={800}>{t(item.label)}</Typography>
                          <Typography color="primary" fontWeight={900}>{virtualSurgeryTuning[item.key]}%</Typography>
                        </Stack>
                        <Slider
                          size="small"
                          value={virtualSurgeryTuning[item.key]}
                          min={0}
                          max={100}
                          onChange={(_, value) => setVirtualSurgeryTuning((prev) => ({ ...prev, [item.key]: value as number }))}
                        />
                        <Typography variant="caption" color="text.secondary">{t(item.helper)}</Typography>
                      </Box>
                    ))}
                  </Stack>
                </Paper>
              </Grid>
            </Grid>

            <Grid container spacing={2}>
              {displayedRecommendationCards.map(([no, title, copy, score]) => (
                <Grid item xs={12} md={4} key={no}>
                  <Paper elevation={0} className="virtual-reco-card">
                    <span className="virtual-reco-no">{no}</span>
                    {score !== null && (
                      <Chip label={`${score}점`} size="small" color="primary" variant="outlined" sx={{ mb: 1 }} />
                    )}
                    <Typography variant="h6" fontWeight={900}>{t(title)}</Typography>
                    <Typography color="text.secondary">{t(copy)}</Typography>
                  </Paper>
                </Grid>
              ))}
            </Grid>

            <Alert severity="info">
              {t('다음 단계에서는 얼굴 사진 업로드 후 기존 Face Mesh 분석을 연결해 사용자별 추천과 전후 비교 이미지를 생성할 수 있습니다.')}
            </Alert>
          </Stack>
        </Container>
      </Box>
    );
  }

  function renderVirtualSurgeryFlowPage() {
    // '비율 조절' 단계를 뺐다(2026-08-03). 슬라이더 4개 중 2개는 내부에서 합산돼 자유도가 1개였고,
    // '코 라인 62%' 같은 숫자는 의학적 의미가 없는데 결과지에 실려 수술 수치로 읽힌다.
    // 강도는 카드 화면의 3단계(자연스럽게/적당히/또렷하게)가 대신한다.
    const flowSteps = ['기본정보·목표 설정', '사진 업로드·AI 분석', '얼굴 비율 분석', '개선 방향 선택', '상담용 리포트'];
    const targetCards = [
      {
        id: 'oval',
        title: '계란형 밸런스',
        copy: '전체 얼굴선은 유지하면서 턱선과 광대 폭을 부드럽게 정리합니다.',
        tuning: { faceLine: 44, jawBalance: 32, noseContour: 28, blemishCare: 50 },
      },
      {
        id: 'vline',
        title: 'V라인 윤곽',
        copy: '하관과 턱끝 중심으로 갸름한 인상을 강조합니다.',
        tuning: { faceLine: 68, jawBalance: 64, noseContour: 32, blemishCare: 45 },
      },
      {
        id: 'soft',
        title: '부드러운 동안형',
        copy: '각진 인상을 줄이고 볼륨감과 부드러운 얼굴선을 우선합니다.',
        tuning: { faceLine: 34, jawBalance: 22, noseContour: 24, blemishCare: 58 },
      },
      {
        id: 'defined',
        title: '입체 세련형',
        copy: '코 라인과 중안부 입체감을 살려 또렷한 인상을 만듭니다.',
        tuning: { faceLine: 46, jawBalance: 34, noseContour: 62, blemishCare: 42 },
      },
    ] as const;
    const concernOptions = [
      '윤곽·얼굴형',
      '턱끝·하관',
      '광대·볼 폭',
      '코 라인',
      '중안부 비율',
      '점·잡티 제거',
    ];
    const desiredMoodOptions = [
      '자연스러운 변화',
      'V라인처럼 갸름하게',
      '부드러운 동안 이미지',
      '또렷하고 세련된 인상',
      '좌우 균형 개선',
      '피부결까지 깨끗하게',
    ];
    const tuningItems = [
      { key: 'faceLine', label: '얼굴 프레임', helper: '광대와 얼굴 폭을 자연스럽게 정리' },
      { key: 'jawBalance', label: '턱 밸런스', helper: '하관 길이와 턱끝 인상을 부드럽게 조정' },
      { key: 'noseContour', label: '코 라인', helper: '콧대와 코끝의 입체감을 과하지 않게 제안' },
      { key: 'blemishCare', label: '점·잡티 제거', helper: '클릭 제거형 피부 보정 후보로 분리' },
    ] as const;
    const selectedTarget = targetCards.find((item) => item.id === virtualSurgeryTarget) ?? targetCards[0];
    const resultCards = virtualSurgeryResult?.recommendations.length
      ? virtualSurgeryResult.recommendations
      : [
          { title: '윤곽 균형 추천', score: 80, summary: selectedTarget.copy, category: 'face_frame' },
          { title: '자연스러움 기준', score: 76, summary: '변화 강도를 높일수록 전후 차이는 커지고 원래 인상 보존 점수는 낮아집니다.', category: 'naturalness' },
          { title: '점·잡티 제거 후보', score: 70, summary: '사진 분석 후 작은 점과 잡티 후보를 분리해 사용자가 확인할 수 있게 합니다.', category: 'blemish' },
        ];

    const canContinue =
      virtualSurgeryStep === 0 ? virtualSurgeryProfile.privacyConsent
      : virtualSurgeryStep === 1 ? Boolean(virtualSurgeryResult?.detected)
      : virtualSurgeryStep === 2 ? Boolean(virtualSurgeryResult?.detected)
      : virtualSurgeryStep === 3 ? Boolean(virtualSurgeryTarget)
      : true;

    const goNextVirtualStep = () => setVirtualSurgeryStep((step) => Math.min(step + 1, flowSteps.length - 1));
    const goPrevVirtualStep = () => setVirtualSurgeryStep((step) => Math.max(step - 1, 0));

    const uploadBox = (
      <Box
        component="label"
        className={`virtual-upload-drop${virtualSurgeryDragOver ? ' is-over' : ''}`}
        onDragOver={(event: React.DragEvent) => { event.preventDefault(); setVirtualSurgeryDragOver(true); }}
        onDragLeave={() => setVirtualSurgeryDragOver(false)}
        onDrop={(event: React.DragEvent) => {
          event.preventDefault();
          setVirtualSurgeryDragOver(false);
          const file = event.dataTransfer.files?.[0];
          if (file) void handleVirtualSurgeryUpload(file);
        }}
      >
        {virtualSurgeryPreview ? (
          <img src={virtualSurgeryPreview} alt={t('가상 성형 분석용 얼굴 사진')} />
        ) : (
          <Stack alignItems="center" spacing={1.2} sx={{ textAlign: 'center', px: 2 }}>
            <Box className="virtual-upload-icon"><ImagePlus size={30} /></Box>
            <Typography variant="h6" fontWeight={900}>{t('얼굴 사진 업로드')}</Typography>
            <Typography variant="body2" color="text.secondary">{t('정면 얼굴과 밝은 조명의 JPG·PNG 사진을 권장합니다.')}</Typography>
          </Stack>
        )}
        <input
          hidden
          type="file"
          accept="image/*"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void handleVirtualSurgeryUpload(file);
            event.target.value = '';
          }}
        />
      </Box>
    );

    const beforeAfter = virtualSurgeryResult?.detected ? (
      <Grid container spacing={1.5}>
        <Grid item xs={12} sm={6}>
          <Box className="virtual-result-image">
            <span>Before</span>
            <img src={virtualSurgeryResult.original_image} alt={t('원본 얼굴 사진')} />
          </Box>
        </Grid>
        <Grid item xs={12} sm={6}>
          <Box className="virtual-result-image">
            <span>Recommended</span>
            <img src={virtualSurgeryResult.preview_image} alt={t('가상 성형 추천 미리보기')} />
          </Box>
        </Grid>
      </Grid>
    ) : uploadBox;

    const renderFlowStep = () => {
      if (virtualSurgeryStep === 0) {
        return (
          <Paper elevation={0} className="virtual-upload-panel">
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <Stack spacing={2}>
                  <Typography variant="h5" fontWeight={900}>{t('기본정보·목표 설정')}</Typography>
                  <Typography color="text.secondary">{t('성형 추천은 얼굴 비율과 사용자가 원하는 개선 방향을 함께 봅니다.')}</Typography>
                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                    <FormControl fullWidth size="small">
                      <InputLabel>{t('성별')}</InputLabel>
                      <Select
                        label={t('성별')}
                        value={virtualSurgeryProfile.gender}
                        onChange={(event) => setVirtualSurgeryProfile((prev) => ({ ...prev, gender: event.target.value }))}
                      >
                        <MenuItem value="female">{t('여성')}</MenuItem>
                        <MenuItem value="male">{t('남성')}</MenuItem>
                      </Select>
                    </FormControl>
                    <FormControl fullWidth size="small">
                      <InputLabel>{t('나이대')}</InputLabel>
                      <Select
                        label={t('나이대')}
                        value={virtualSurgeryProfile.ageGroup}
                        onChange={(event) => setVirtualSurgeryProfile((prev) => ({ ...prev, ageGroup: event.target.value }))}
                      >
                        {ageGroups.filter((item) => !['baby', 'child'].includes(item.value)).map((item) => (
                          <MenuItem key={item.value} value={item.value}>{t(item.label)}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Stack>
                  <Box>
                    <Typography fontWeight={900} sx={{ mb: 0.5 }}>{t('개선하고 싶은 부위')}</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                      {t('여러 개 고를 수 있어요. 먼저 고른 순서가 우선순위입니다.')}
                    </Typography>
                    <Box className="virtual-choice-grid">
                      {concernOptions.map((option) => {
                        const rank = virtualSurgeryProfile.concerns.indexOf(option);
                        return (
                          <Button
                            key={option}
                            variant={rank >= 0 ? 'contained' : 'outlined'}
                            onClick={() => toggleSurgeryChoice('concerns', option, 3)}
                          >
                            {/* 순위를 숫자로 보여줘야 '먼저 고른 게 1순위'라는 규칙이 눈에 보인다. */}
                            {rank >= 0 ? `${rank + 1}. ` : ''}{t(option)}
                          </Button>
                        );
                      })}
                    </Box>
                  </Box>
                  <Box>
                    <Typography fontWeight={900} sx={{ mb: 0.5 }}>{t('원하는 변화 이미지')}</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                      {t('최대 2개까지 고를 수 있어요.')}
                    </Typography>
                    <Box className="virtual-choice-grid">
                      {desiredMoodOptions.map((option) => (
                        <Button
                          key={option}
                          variant={virtualSurgeryProfile.desiredMoods.includes(option) ? 'contained' : 'outlined'}
                          // 서로 모순되는 조합('자연스러운 변화' + '또렷하고 세련된 인상')을 다 고르면
                          // 추천이 갈피를 못 잡는다. 2개로 묶어 방향이 남게 한다.
                          onClick={() => toggleSurgeryChoice('desiredMoods', option, 2)}
                        >
                          {t(option)}
                        </Button>
                      ))}
                    </Box>
                  </Box>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={virtualSurgeryProfile.privacyConsent}
                        onChange={(event) => setVirtualSurgeryProfile((prev) => ({ ...prev, privacyConsent: event.target.checked }))}
                      />
                    }
                    label={t('비의료 참고용 가상 성형 분석 및 이미지 처리에 동의합니다.')}
                  />
                </Stack>
              </Grid>
              <Grid item xs={12} md={6}>
                <Paper elevation={0} className="virtual-step-guide">
                  <Typography variant="h6" fontWeight={900}>{t('분석 기준')}</Typography>
                  <Stack spacing={1.2} sx={{ mt: 2 }}>
                    {['얼굴형과 상·중·하안부 비율', '턱·광대·코 라인 개선 후보', '원하는 얼굴형 카드 기반 추천', '결과지 출력용 Before / After'].map((item, index) => (
                      <Stack direction="row" spacing={1} alignItems="center" key={item}>
                        <span className="virtual-reco-no">{String(index + 1).padStart(2, '0')}</span>
                        <Typography>{t(item)}</Typography>
                      </Stack>
                    ))}
                  </Stack>
                </Paper>
              </Grid>
            </Grid>
          </Paper>
        );
      }

      if (virtualSurgeryStep === 1) {
        return (
          <Paper elevation={0} className="virtual-upload-panel">
            <Grid container spacing={2} alignItems="center">
              <Grid item xs={12} md={5}>{uploadBox}</Grid>
              <Grid item xs={12} md={7}>
                <Stack spacing={1.5}>
                  <Typography variant="h5" fontWeight={900}>{t('AI 성형 분석')}</Typography>
                  <Typography color="text.secondary">{t('얼굴 사진을 업로드하면 얼굴형, 비율, 윤곽 추천 후보를 분석합니다.')}</Typography>
                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                    <Button variant="contained" component="label" startIcon={<ImagePlus size={18} />} disabled={virtualSurgeryLoading}>
                      {virtualSurgeryPreview ? t('다른 사진 선택') : t('사진 선택')}
                      <input hidden type="file" accept="image/*" onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void handleVirtualSurgeryUpload(file);
                        event.target.value = '';
                      }} />
                    </Button>
                    <Button variant="outlined" startIcon={<RefreshCcw size={18} />} disabled={!virtualSurgeryFile || virtualSurgeryLoading} onClick={() => void rerunVirtualSurgery()}>
                      {t('AI 성형 분석 실행')}
                    </Button>
                  </Stack>
                  {virtualSurgeryLoading && <LinearProgress />}
                  {virtualSurgeryResult && <Alert severity={virtualSurgeryResult.detected ? 'success' : 'warning'}>{virtualSurgeryResult.message}</Alert>}
                </Stack>
              </Grid>
            </Grid>
          </Paper>
        );
      }

      if (virtualSurgeryStep === 2) {
        const ratios = virtualSurgeryResult?.face_shape?.ratios ?? [];
        return (
          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <Paper elevation={0} className="virtual-preview-panel">{beforeAfter}</Paper>
            </Grid>
            <Grid item xs={12} md={6}>
              <Paper elevation={0} className="virtual-control-panel">
                <Typography variant="h5" fontWeight={900}>{t('얼굴형 분석결과')}</Typography>
                <Typography color="text.secondary" sx={{ mt: 1 }}>{virtualSurgeryResult?.face_shape?.summary}</Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
                  <Chip label={virtualSurgeryResult?.face_shape?.shape || '분석 전'} color="primary" variant="outlined" />
                  <Chip label={`자연스러움 ${virtualSurgeryResult?.metrics.naturalness_score ?? '-'}점`} variant="outlined" />
                  <Chip label={`점·잡티 후보 ${virtualSurgeryResult?.metrics.blemish_candidates ?? 0}개`} variant="outlined" />
                </Stack>
                <Stack spacing={1.3} sx={{ mt: 2 }}>
                  {ratios.map((ratio) => (
                    <Box key={ratio.label}>
                      <Stack direction="row" justifyContent="space-between">
                        <Typography variant="body2" fontWeight={800}>{ratio.label}</Typography>
                        <Typography variant="body2" color="text.secondary">{ratio.width}%</Typography>
                      </Stack>
                      <LinearProgress variant="determinate" value={Math.min(100, ratio.width)} sx={{ height: 8, borderRadius: 4 }} />
                    </Box>
                  ))}
                </Stack>
              </Paper>
            </Grid>
          </Grid>
        );
      }

      if (virtualSurgeryStep === 3) {
        return (
          <Paper elevation={0} className="virtual-upload-panel">
            <Typography variant="h5" fontWeight={900}>{t('원하는 개선된 얼굴형 카드 선택')}</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.5 }}>
              {t('각 카드를 내 사진에 적용한 미리보기입니다. 참고용이며 실제 결과를 보장하지 않습니다.')}
            </Typography>

            {/* 변화 강도 — 예전 '비율 조절' 단계의 슬라이더를 대신한다. 숫자(%)를 없앤 이유는
                의학적 의미가 없는 워프 강도가 '62%' 처럼 수술 수치로 읽히기 때문이다. */}
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 2 }} flexWrap="wrap" useFlexGap>
              <Typography fontWeight={900}>{t('변화 강도')}</Typography>
              {([
                ['natural', '자연스럽게'],
                ['balanced', '적당히 변화'],
                ['defined', '또렷하게'],
              ] as const).map(([value, label]) => (
                <Button
                  key={value}
                  size="small"
                  variant={surgeryIntensity === value ? 'contained' : 'outlined'}
                  disabled={surgeryCardsLoading}
                  onClick={() => {
                    setSurgeryIntensity(value);
                    void loadSurgeryCards(value);
                  }}
                >
                  {t(label)}
                </Button>
              ))}
              {surgeryCardsLoading && <Loader2 size={18} className="spin" />}
            </Stack>

            <Grid container spacing={2} sx={{ mt: 1 }}>
              {targetCards.map((card) => {
                const preview = surgeryCards.find((item) => item.id === card.id);
                return (
                  <Grid item xs={12} sm={6} md={3} key={card.id}>
                    <Paper
                      elevation={0}
                      className={`virtual-target-card${virtualSurgeryTarget === card.id ? ' selected' : ''}`}
                      onClick={() => {
                        setVirtualSurgeryTarget(card.id);
                        setVirtualSurgeryTuning(card.tuning);
                      }}
                    >
                      {/* 미리보기가 오면 실제 얼굴을, 아직이면 기존 일러스트를 보여준다.
                          실패해도 카드 선택 자체는 계속돼야 하므로 폴백을 남긴다. */}
                      {preview ? (
                        <Box
                          component="img"
                          src={preview.preview_image}
                          alt={t(card.title)}
                          className="virtual-target-preview"
                          sx={{ width: '100%', borderRadius: 2, display: 'block', aspectRatio: '1 / 1', objectFit: 'cover' }}
                        />
                      ) : (
                        <Box className={`virtual-target-face ${card.id}`} />
                      )}
                      <Typography variant="h6" fontWeight={900}>{t(card.title)}</Typography>
                      <Typography variant="body2" color="text.secondary">{t(card.copy)}</Typography>
                    </Paper>
                  </Grid>
                );
              })}
            </Grid>
          </Paper>
        );
      }

      return (
        <Box>
          <Box className="virtual-report-stage">
            <Paper elevation={0} className="virtual-report-card">
              <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}>
                <Box>
                  <Typography className="report-brand">YoPalette</Typography>
                  <Typography variant="h4" fontWeight={900}>{t('상담용 리포트')}</Typography>
                  <Typography color="text.secondary">{new Date().toISOString().slice(0, 10)}</Typography>
                </Box>
                <Chip label={t('비의료 참고용')} color="primary" variant="outlined" sx={{ alignSelf: { xs: 'flex-start', md: 'center' } }} />
              </Stack>
              <Grid container spacing={2} sx={{ mt: 1 }}>
                <Grid item xs={12} md={7}>{beforeAfter}</Grid>
                <Grid item xs={12} md={5}>
                  <Stack spacing={1.5}>
                    <Paper elevation={0} className="virtual-report-summary">
                      <Typography fontWeight={900}>{t('선택한 개선 얼굴형')}</Typography>
                      <Typography variant="h6" fontWeight={900}>{t(selectedTarget.title)}</Typography>
                      <Typography color="text.secondary">{t(selectedTarget.copy)}</Typography>
                    </Paper>
                    {/* 결과지에서 '조절 퍼센티지'를 뺐다. 의학적 의미가 없는 워프 강도인데, 병원에
                        들고 가면 '62% 해주세요'가 된다. 대신 고른 강도만 말로 적는다. */}
                    <Paper elevation={0} className="virtual-report-summary">
                      <Typography fontWeight={900}>{t('변화 강도')}</Typography>
                      <Typography color="text.secondary">
                        {t(surgeryIntensity === 'natural' ? '자연스럽게' : surgeryIntensity === 'defined' ? '또렷하게' : '적당히 변화')}
                      </Typography>
                    </Paper>
                  </Stack>
                </Grid>
              </Grid>
              <Grid container spacing={1.5} sx={{ mt: 1 }}>
                {resultCards.map((card, index) => (
                  <Grid item xs={12} md={4} key={`${card.category}-${index}`}>
                    <Paper elevation={0} className="virtual-reco-card">
                      <span className="virtual-reco-no">{String(index + 1).padStart(2, '0')}</span>
                      <Chip label={`${card.score}점`} size="small" color="primary" variant="outlined" sx={{ mb: 1 }} />
                      {/* 1단계에서 고른 부위임을 표시한다. 백엔드가 selected 로 알려주고 정렬도
                          해 주는데, 결과지에 아무 표시가 없으면 '내 선택이 반영됐나'를 알 수 없다.
                          ⚠ 예전엔 이 배지를 displayedRecommendationCards(다른 렌더러)에만 넣어서
                          결과지에는 끝내 안 보였다 — 이 화면이 쓰는 건 resultCards 다. */}
                      {'selected' in card && card.selected && (
                        <Chip label={t('선택하신 부위')} size="small" color="secondary" sx={{ mb: 1, ml: 0.5 }} />
                      )}
                      <Typography variant="h6" fontWeight={900}>{t(card.title)}</Typography>
                      <Typography color="text.secondary">{t(card.summary)}</Typography>
                    </Paper>
                  </Grid>
                ))}
              </Grid>
              {/* 진료 안내는 미용 고지보다 **위**에 둔다. 아래에 묻히면 못 본다. */}
              {virtualSurgeryResult?.referral?.urgent && (
                <Alert severity="warning" sx={{ mt: 2 }}>{virtualSurgeryResult.referral.message}</Alert>
              )}
              <Alert severity="info" sx={{ mt: 2 }}>{virtualSurgeryResult?.disclaimer || t('비의료 참고용 가상 성형 시뮬레이션입니다. 실제 시술 여부는 전문 의료진 상담이 필요합니다.')}</Alert>
              {/* 한국 의료법 제56조(의료광고)·일본 医療広告ガイドライン 은 비포/애프터 이미지를
                  별도로 규제한다. AI 미리보기가 정확히 그 형태라, 성격을 명시해 둔다.
                  ⚠ 이 문구로 규제를 만족한다고 단정할 수 없다 — 법무 확인이 필요하다(설계 검토 §6). */}
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                {t('AI 미리보기는 사진을 참고용으로 변형한 이미지이며, 시술 전후를 비교한 사진이 아닙니다. 특정 의료기관·시술을 광고하지 않습니다.')}
              </Typography>
            </Paper>
          </Box>
        </Box>
      );
    };

    return (
      <Box className="app-shell">
        <AppLangToggle authUser={authUser} />
        <Container maxWidth="lg" sx={{ py: { xs: 2, md: 4 } }}>
          <Stack spacing={2}>
            <Paper elevation={0} className="virtual-flow-header">
              <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}>
                <Box>
                  <Chip label="AI Surgery Plan" color="primary" variant="outlined" sx={{ mb: 1 }} />
                  <Typography variant="h4" fontWeight={900}>{t('가상 성형 추천 시스템')}</Typography>
                  <Typography color="text.secondary">{t('기본정보 입력부터 상담용 리포트까지 단계별로 진행합니다.')}</Typography>
                </Box>
                <Button startIcon={<ArrowLeft size={16} />} onClick={goHome}>{t('홈으로')}</Button>
              </Stack>
              <Stepper activeStep={virtualSurgeryStep} alternativeLabel sx={{ mt: 3 }}>
                {flowSteps.map((step, index) => (
                  <Step key={step} completed={index < virtualSurgeryStep}>
                    <StepLabel
                      onClick={() => {
                        if (index <= virtualSurgeryStep || (index === 1 && virtualSurgeryProfile.privacyConsent) || (index <= 5 && virtualSurgeryResult?.detected)) {
                          setVirtualSurgeryStep(index);
                        }
                      }}
                      sx={{ cursor: index <= virtualSurgeryStep || virtualSurgeryResult?.detected ? 'pointer' : 'default' }}
                    >
                      {t(step)}
                    </StepLabel>
                  </Step>
                ))}
              </Stepper>
            </Paper>
            {error && <Alert severity="error">{error}</Alert>}
            {renderFlowStep()}
            <Paper elevation={0} className="virtual-flow-footer">
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Button variant="outlined" startIcon={<ArrowLeft size={16} />} disabled={virtualSurgeryStep === 0} onClick={goPrevVirtualStep}>
                  {t('이전')}
                </Button>
                <Typography variant="body2" color="text.secondary">{virtualSurgeryStep + 1} / {flowSteps.length}</Typography>
                <Button variant="contained" endIcon={<ArrowRight size={16} />} disabled={!canContinue || virtualSurgeryStep === flowSteps.length - 1} onClick={goNextVirtualStep}>
                  {t('다음')}
                </Button>
              </Stack>
            </Paper>
          </Stack>
        </Container>
      </Box>
    );
  }

  function renderNailDesignPage() {
    const primary = nailResult?.detected?.[0];
    const bestSeason = nailResult?.season_fit?.[0];
    return (
      <Box className="app-shell">
      <AppLangToggle authUser={authUser} />
        <Container maxWidth="lg" sx={{ py: { xs: 2, md: 4 } }}>
          <Stack spacing={3}>
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Box>
                <Typography variant="h4" fontWeight={900}>{t('네일·페디 디자인')}</Typography>
                <Typography color="text.secondary">
                  {t('손이나 발 사진을 올리면 비슷한 네일 디자인을 찾아 주고, 퍼스널컬러 시즌과 얼마나 맞는지 알려줍니다.')}
                </Typography>
              </Box>
              <Button startIcon={<ArrowLeft size={16} />} onClick={goHome}>{t('홈으로')}</Button>
            </Stack>

            {error && <Alert severity="error">{error}</Alert>}

            {/* 업로드 영역. 예전엔 전폭 버튼 하나만 있어 결과 전 화면이 텅 비어 보였다(사용자 지적)
                → 드롭존 + 사용법/촬영팁/시즌 안내로 '결과 전에도 읽을 것'이 있게 만든다. */}
            {/* 퍼스널컬러 Step1 과 같은 2단 구성: 왼쪽=입력(미리보기+버튼), 오른쪽=안내/결과.
                예전엔 전폭 드롭존 하나뿐이라 업로드 후 사진만 덩그러니 남아 어색했다(사용자 지적). */}
            <Grid container spacing={2}>
              <Grid item xs={12} md={5}>
                <Stack spacing={2}>
                  <Box
                    component="label"
                    className={`nail-preview kiosk-preview${nailDragOver ? ' is-over' : ''}`}
                    onDragOver={(event: React.DragEvent) => { event.preventDefault(); setNailDragOver(true); }}
                    onDragLeave={() => setNailDragOver(false)}
                    onDrop={(event: React.DragEvent) => {
                      event.preventDefault();
                      setNailDragOver(false);
                      const file = event.dataTransfer.files?.[0];
                      if (file) void handleNailUpload(file);
                    }}
                  >
                    {nailPreview ? (
                      <img src={nailPreview} alt={t('업로드한 네일 사진')} />
                    ) : (
                      <Stack alignItems="center" spacing={1} sx={{ px: 2, textAlign: 'center' }}>
                        <Box className="nail-dropzone-icon"><ImagePlus size={30} /></Box>
                        <Typography variant="h6" fontWeight={900}>{t('손·발 사진을 올려 주세요')}</Typography>
                        <Typography color="text.secondary" variant="body2">
                          {t('여기로 끌어다 놓거나 눌러서 사진을 선택할 수 있어요. JPG·PNG')}
                        </Typography>
                      </Stack>
                    )}
                    <input
                      hidden
                      type="file"
                      accept="image/*"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void handleNailUpload(file);
                        event.target.value = '';
                      }}
                    />
                  </Box>

                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                    <Button
                      fullWidth
                      variant="outlined"
                      component="label"
                      startIcon={<ImagePlus size={18} />}
                      disabled={nailLoading}
                    >
                      {nailPreview ? t('다른 사진 선택') : t('사진 선택')}
                      <input
                        hidden
                        type="file"
                        accept="image/*"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) void handleNailUpload(file);
                          event.target.value = '';
                        }}
                      />
                    </Button>
                    <Button
                      fullWidth
                      variant="contained"
                      startIcon={<Camera size={18} />}
                      disabled={nailLoading}
                      onClick={() => void openNailCamera()}
                    >
                      {t('카메라로 촬영')}
                    </Button>
                  </Stack>

                  {nailCameraOn && (
                    <Box className="nail-camera">
                      <Box component="video" ref={videoRef} className="nail-camera-view" autoPlay muted playsInline />
                      <Stack direction="row" spacing={1} justifyContent="center" sx={{ mt: 1.5 }}>
                        <Button
                          variant="contained"
                          startIcon={<Camera size={18} />}
                          disabled={!cameraReady || nailLoading}
                          onClick={() => void captureNailImage()}
                        >
                          {t('촬영하기')}
                        </Button>
                        <Button variant="outlined" onClick={closeNailCamera}>{t('닫기')}</Button>
                      </Stack>
                      {!cameraReady && (
                        <Typography color="text.secondary" variant="body2" align="center" sx={{ mt: 1 }}>
                          {t('카메라 권한을 기다리는 중입니다')}
                        </Typography>
                      )}
                    </Box>
                  )}
                  <Box component="canvas" ref={canvasRef} sx={{ display: 'none' }} />
                  {nailLoading && <LinearProgress />}
                </Stack>
              </Grid>

              <Grid item xs={12} md={7}>
                {primary ? (
                  <Paper elevation={0} className="nail-guide">
                    <Typography variant="h6" fontWeight={900}>{t('사진 속 컬러')}</Typography>
                    <Stack direction="row" spacing={2} alignItems="center" sx={{ mt: 2 }}>
                      <Box sx={{ width: 56, height: 56, borderRadius: 2, bgcolor: primary.color_hex, border: '1px solid var(--yp-line)' }} />
                      <Box>
                        <Typography fontWeight={700}>{primary.color_hex}</Typography>
                        <Typography color="text.secondary" variant="body2">
                          네일 {nailResult.detected.length}개 검출 · 신뢰도 {Math.round(primary.confidence * 100)}%
                        </Typography>
                      </Box>
                    </Stack>
                    {bestSeason && <Alert severity="success" sx={{ mt: 2 }}>{nailResult.note}</Alert>}
                  </Paper>
                ) : (
                  <Paper elevation={0} className="nail-guide">
                    <Typography variant="h6" fontWeight={900}>{t('이렇게 동작해요')}</Typography>
                    <Stack spacing={1.5} sx={{ mt: 2 }}>
                      {[
                        ['1', t('사진 업로드'), t('손톱이 잘 보이는 사진 한 장이면 됩니다.')],
                        ['2', t('네일 검출·대표색 추출'), t('AI가 손톱 영역을 찾아 젤 광택을 뺀 대표 색을 뽑습니다.')],
                        ['3', t('비슷한 디자인·시즌 적합도'), t('닮은 디자인을 찾아 주고, 7개 퍼스널컬러 시즌과의 궁합을 점수로 보여줍니다.')],
                      ].map(([no, title, body]) => (
                        <Stack key={no} direction="row" spacing={1.5} alignItems="flex-start">
                          <Box className="nail-step-no">{no}</Box>
                          <Box>
                            <Typography fontWeight={800}>{title}</Typography>
                            <Typography color="text.secondary" variant="body2">{body}</Typography>
                          </Box>
                        </Stack>
                      ))}
                    </Stack>
                    <Typography variant="body2" fontWeight={800} sx={{ mt: 3 }}>{t('사진 촬영 팁')}</Typography>
                    <Stack spacing={1} sx={{ mt: 1 }}>
                      {[
                        t('밝은 곳에서 그림자 없이 찍어 주세요.'),
                        t('손 전체보다 손톱이 크게 나오게 찍으면 정확합니다.'),
                        t('색이 잘 보이도록 정면에서 찍어 주세요.'),
                      ].map((tip) => (
                        <Stack key={tip} direction="row" spacing={1} alignItems="flex-start">
                          <Box className="nail-tip-dot" />
                          <Typography color="text.secondary" variant="body2">{tip}</Typography>
                        </Stack>
                      ))}
                    </Stack>
                    <Typography variant="body2" fontWeight={800} sx={{ mt: 2.5 }}>{t('확인할 수 있는 시즌')}</Typography>
                    <Stack direction="row" flexWrap="wrap" gap={0.8} sx={{ mt: 1 }}>
                      {['봄 웜 라이트', '봄 웜 브라이트', '여름 쿨 라이트', '여름 쿨 뮤트',
                        '가을 웜 뮤트', '가을 웜 딥', '겨울 쿨 딥'].map((season) => (
                        <Chip key={season} label={t(season)} size="small" variant="outlined" />
                      ))}
                    </Stack>
                  </Paper>
                )}
              </Grid>
            </Grid>

            {nailResult && !nailResult.feature_available && (
              <Alert severity="info">{nailResult.note}</Alert>
            )}

            {nailResult?.feature_available && !primary && (
              <Alert severity="warning">{nailResult.note}</Alert>
            )}

            {primary && (
              <>
                {/* 발색 미리보기 — 추천 색을 고르면 검출된 손·발톱에 그 색을 입혀 보여준다. */}
                {!!nailResult.recommended_palette?.length && (
                  <Paper elevation={0} sx={{ p: 3, border: '1px solid var(--yp-line)' }}>
                    <Stack spacing={2}>
                      <Box>
                        <Typography variant="h6" fontWeight={800}>{t('발라보기')}</Typography>
                        <Typography color="text.secondary" variant="body2">
                          {t('추천 색을 고르면 사진 속 손톱에 그 색을 입혀 보여드려요.')}
                        </Typography>
                      </Box>
                      <Stack direction="row" flexWrap="wrap" gap={1}>
                        {nailResult.recommended_palette.map((shade) => (
                          <Stack
                            key={shade.name}
                            alignItems="center"
                            spacing={0.5}
                            className={`nail-swatch${nailShade?.name === shade.name ? ' is-active' : ''}`}
                            onClick={() => void applyNailShade(shade)}
                          >
                            <Box className="nail-swatch-dot" sx={{ bgcolor: shade.hex }} />
                            <Typography variant="caption">{t(shade.name)}</Typography>
                          </Stack>
                        ))}
                      </Stack>
                      {nailTryOn && (
                        <Grid container spacing={2}>
                          <Grid item xs={12} sm={6}>
                            <Typography variant="caption" color="text.secondary">{t('원본')}</Typography>
                            <Box component="img" src={nailPreview} alt={t('업로드한 네일 사진')} className="nail-tryon-img" />
                          </Grid>
                          <Grid item xs={12} sm={6}>
                            <Typography variant="caption" color="text.secondary">
                              {t('발색 미리보기')}{nailShade ? ` · ${t(nailShade.name)}` : ''}
                            </Typography>
                            <Box component="img" src={nailTryOn} alt={t('발색 미리보기')} className="nail-tryon-img" />
                          </Grid>
                        </Grid>
                      )}
                      {nailTryOn && (
                        <Alert severity="info" sx={{ py: 0.5 }}>
                          {t('검출된 손톱 영역을 타원으로 근사해 색을 입힌 결과라 실제 발색과 다를 수 있어요.')}
                        </Alert>
                      )}
                    </Stack>
                  </Paper>
                )}

                {/* 선택한 색으로 살 수 있는 실제 상품 */}
                {/* 분석 결과가 있으면 항상 노출한다 — 예전엔 0건일 때 영역째 사라져
                    '상품추천이 아예 없는 화면'처럼 보였다. */}
                {(nailProductsLoading || nailShade !== null) && (
                  <Paper elevation={0} sx={{ p: 3, border: '1px solid var(--yp-line)' }}>
                    <Stack spacing={2}>
                      <Stack
                        direction={{ xs: 'column', sm: 'row' }}
                        justifyContent="space-between"
                        alignItems={{ xs: 'stretch', sm: 'center' }}
                        spacing={1.5}
                      >
                        <Typography variant="h6" fontWeight={800}>
                          {t('이 컬러로 살 수 있는 상품')}
                        </Typography>
                        {/* 지역/플랫폼을 바꾸면 선택한 색으로 즉시 다시 조회한다. */}
                        <ItemMarketFilter
                          region={itemRegion}
                          platform={itemPlatform}
                          onRegionChange={(next) => {
                            setItemRegion(next);
                            setItemPlatform('all');
                            if (nailShade) void loadNailProducts(nailShade, next, 'all');
                          }}
                          onPlatformChange={(next) => {
                            setItemPlatform(next);
                            if (nailShade) void loadNailProducts(nailShade, itemRegion, next);
                          }}
                        />
                      </Stack>
                      {nailProductsLoading && <LinearProgress />}
                      <Grid container spacing={1.5}>
                        {nailProducts.map((product) => (
                          <Grid item xs={12} sm={6} md={4} key={product.id}>
                            <RakutenProductCard product={product} selectedPlatform={itemPlatform} />
                          </Grid>
                        ))}
                      </Grid>
                      {!nailProductsLoading && !nailProducts.length && (
                        <Typography color="text.secondary" variant="body2">
                          {t('이 카테고리에 맞는 상품이 없어요.')}
                        </Typography>
                      )}
                    </Stack>
                  </Paper>
                )}

                <Paper elevation={0} sx={{ p: 3, border: '1px solid #e1e7ef' }}>
                  <Stack spacing={2}>
                    <Typography variant="h6" fontWeight={800}>{t('비슷한 디자인')}</Typography>
                    {nailResult.detected.map((nail) => (
                      <Stack key={nail.index} spacing={1}>
                        <Typography variant="body2" color="text.secondary">
                          검출 #{nail.index + 1} · {nail.color_hex}
                        </Typography>
                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                          {nail.matches.map((match, i) => (
                            <Stack key={`${nail.index}-${match.design_id}-${i}`} alignItems="center" spacing={0.5}>
                              {match.thumbnail ? (
                                <Box
                                  component="img"
                                  src={match.thumbnail}
                                  alt={match.design_id}
                                  sx={{ width: 72, height: 72, borderRadius: 1.5, border: '1px solid #e1e7ef' }}
                                />
                              ) : (
                                <Box sx={{ width: 72, height: 72, borderRadius: 1.5, bgcolor: match.color_hex, border: '1px solid #e1e7ef' }} />
                              )}
                              <Typography variant="caption" color="text.secondary">
                                {match.region === 'foot' ? '발' : '손'} · ΔE {match.delta_e}
                              </Typography>
                            </Stack>
                          ))}
                        </Stack>
                      </Stack>
                    ))}
                  </Stack>
                </Paper>

                <Paper elevation={0} sx={{ p: 3, border: '1px solid #e1e7ef' }}>
                  <Stack spacing={2}>
                    <Typography variant="h6" fontWeight={800}>{t('퍼스널컬러 시즌 적합도')}</Typography>
                    <Stack spacing={1}>
                      {nailResult.season_fit.map((fit) => (
                        <Stack key={fit.label} direction="row" spacing={2} alignItems="center">
                          <Box sx={{ width: 24, height: 24, borderRadius: '50%', bgcolor: fit.shade_hex, border: '1px solid #e1e7ef' }} />
                          <Typography sx={{ minWidth: 130 }} fontWeight={fit.label === bestSeason?.label ? 800 : 400}>
                            {fit.label}
                          </Typography>
                          <Typography variant="body2" color="text.secondary" sx={{ minWidth: 90 }}>
                            {fit.shade_name}
                          </Typography>
                          <Box sx={{ flex: 1 }}>
                            <LinearProgress variant="determinate" value={fit.score} />
                          </Box>
                          <Typography variant="body2" sx={{ minWidth: 48, textAlign: 'right' }}>
                            {fit.score}점
                          </Typography>
                        </Stack>
                      ))}
                    </Stack>
                    {nailResult.recommended_shades.length > 0 && (
                      <Box>
                        <Typography variant="body2" color="text.secondary" gutterBottom>
                          {t('이 시즌에 어울리는 네일 컬러')}
                        </Typography>
                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                          {nailResult.recommended_shades.map((shade) => (
                            <Chip key={shade} label={shade} size="small" />
                          ))}
                        </Stack>
                      </Box>
                    )}
                  </Stack>
                </Paper>
              </>
            )}
          </Stack>
        </Container>
      </Box>
    );
  }

  /** 피부 케어 결과지. 퍼스널컬러 결과지와 같은 카드 레이아웃을 쓰되 내용은 피부 기준
   *  (진단 요약·추천 성분·선택 상품·QR)으로 채운다. */
  /** 피부 케어 결과지. 퍼스널컬러 결과지와 **같은 클래스 체계**를 쓴다
   *  (print-report-stage > print-report-card > report-top / report-grid).
   *  자체 클래스를 만들면 CSS 가 없어 사진이 원본 크기로 터진다 — 실제로 그랬다. */
  function renderSkinReportPage() {
    const allProducts = [
      ...(recommendation?.product_columns?.flatMap((col) => col.products) ?? []),
      ...(recommendation?.products ?? []),
    ];
    const picked = skinReportIds
      .map((id) => allProducts.find((product) => product.id === id))
      .filter((product): product is Product => Boolean(product));
    // 담은 게 하나라도 있으면 **담은 것만** 싣는다(퍼스널컬러 결과지와 같은 규칙).
    // 모자란 칸을 추천 상위로 채우면, 담은 적 없는 상품이 '내가 고른 것'처럼 결과지에 섞인다
    // (사용자 지적 2026-07-30). 하나도 안 담았을 때만 추천 상위로 채워 빈 결과지를 막는다.
    const hasPicked = picked.length > 0;
    // 담은 상품만 싣는다 — 추천 상위로 자동 채우지 않는다(사용자 지시 2026-08-03).
    // 퍼스널컬러 결과지와 같은 규칙이다.
    const reportProducts = picked.slice(0, SKIN_REPORT_MAX);
    const reportDate = new Date().toISOString().slice(0, 10);

    return (
      <Box>
        <Box className="print-report-stage">
          <Box className="print-report-card">
            <Box className="report-top">
              <Box>
                <Typography className="report-kicker">Date /</Typography>
                <Typography className="report-date">{reportDate}</Typography>
              </Box>
              <Box>
                <Typography className="report-kicker">Skin /</Typography>
                <Typography className="report-face">
                  {analysis?.analysis_mode === 'body' ? t('바디 피부 케어') : t('얼굴 피부 케어')}
                </Typography>
              </Box>
              <Typography className="report-brand">YoPalette</Typography>
            </Box>

            <Box className="report-grid">
              <Box className="report-left">
                <Box className="report-photo">
                  {previewUrls[0] ? <img src={previewUrls[0]} alt={t('분석 사진')} /> : <Sparkles size={34} />}
                </Box>
                <Typography className="report-section-title">{t('진단 요약')}</Typography>
                <Typography className="report-copy">{analysis?.summary || '-'}</Typography>
                {analysis?.scores && (
                  <Stack spacing={0.5} sx={{ mt: 1 }}>
                    {scoreKeys.map((key) => (
                      <Box key={key} className="score-row">
                        <Typography variant="caption">{t(scoreLabels[key])}</Typography>
                        <LinearProgress
                          variant="determinate"
                          value={Math.min(100, analysis.scores![key])}
                          sx={{ height: 6, borderRadius: 3 }}
                        />
                        <Typography variant="caption">{Math.round(analysis.scores![key])}</Typography>
                      </Box>
                    ))}
                  </Stack>
                )}
              </Box>

              <Box className="report-main">
                <Typography className="report-kicker">{t('추천 성분')}</Typography>
                <Box className="report-tags" sx={{ mb: 2 }}>
                  {(recommendation?.ingredients ?? []).slice(0, 6).map((ing) => (
                    <Chip key={ing.id} size="small" label={ing.name} variant="outlined" />
                  ))}
                </Box>

                <Typography className="report-section-title">
                  {t('장바구니')}
                </Typography>
                <Box className="report-products">
                  {!reportProducts.length && (
                    // 담은 게 없으면 추천 상위로 채우지 않는다 — '장바구니' 제목 아래 담은 적
                    // 없는 상품이 실리면 내가 고른 것처럼 보인다(사용자 지적 2026-08-03).
                    <Typography className="report-empty">{t('담은 상품이 없습니다.')}</Typography>
                  )}
                  {reportProducts.map((product, index) => (
                    <Box className="report-product" key={product.id}>
                      <Box className="report-product-thumb">
                        <ProductImage src={product.image_url} alt={product.name} fallback={<Sparkles size={18} />} />
                      </Box>
                      <Box className="report-product-body">
                        <span className="report-product-no">{String(index + 1).padStart(2, '0')}</span>
                        <Typography className="report-product-name">{product.name}</Typography>
                        <Typography className="report-product-brand">{product.brand}</Typography>
                      </Box>
                    </Box>
                  ))}
                </Box>

                <Box className="report-bottom">
                  <Box>
                    <Box
                      component="img"
                      className="report-qr-img"
                      src={qrImageUrl(`${window.location.origin}/#report`)}
                      alt={t('모바일 레포트 QR')}
                      sx={{ width: 74, height: 74, display: 'block', border: '6px solid #fff', background: '#fff', borderRadius: '4px' }}
                    />
                    <Typography className="report-qr-label">{t('모바일 레포트에서 자세한 진단결과 보기')}</Typography>
                  </Box>
                  <Box>
                    <Box className="report-qr-img" sx={{ display: 'block', border: '6px solid #fff', background: '#fff', borderRadius: '4px', width: 74, height: 74 }}>
                      <CartHandoffQr items={cartHandoffItems(reportProducts, SKIN_REPORT_MAX)} linked={Boolean(authUser?.web_member_id)} size={74} />
                    </Box>
                    <Typography className="report-qr-label">{t('QR 을 찍으면 내 계정 장바구니에 담깁니다')}</Typography>
                  </Box>
                </Box>
              </Box>
            </Box>
          </Box>
        </Box>
        <Typography color="text.secondary" sx={{ mt: 2, textAlign: 'center' }}>
          {t(hasPicked
            ? '추천 단계에서 결과지에 담은 상품만 표시됩니다.'
            : '추천 단계에서 상품을 담으면 여기에 표시됩니다.')}
        </Typography>
      </Box>
    );
  }

  const pages = [
    renderSurveyPage,
    renderFacePage,
    renderAnalysisPage,
    renderRecommendationPage,
    renderSkinReportPage,
    renderConsultPage,
  ];
  const CurrentPage = pages[currentStep];

  // ⚠ 로그인 게이트는 모듈 분기(home/personal-color/…)보다 **위**에 있어야 한다.
  // 아래에 두면 홈·퍼스널컬러·네일·가상성형이 각자 먼저 return 해버려 스킨케어 흐름만 막힌다(실측).
  // 세션 확인 중에는 빈 셸만 — 게이트를 먼저 그렸다가 로그인 상태로 바뀌면 화면이 튄다.
  if (authBooting) {
    return (
      <Box className="app-shell">
        <Container maxWidth="lg" sx={{ py: { xs: 2, md: 4 } }}>
          <LinearProgress />
        </Container>
      </Box>
    );
  }

  // 백엔드가 REQUIRE_LOGIN 으로 켜져 있을 때만 막는다(로컬 개발은 그대로 열림).
  if (authConfig?.require_login && !authUser) {
    const loginUrl = authConfig.web_login_url || `${WEB_BASE_URL.replace(/\/$/, '')}/login`;
    return (
      <Box className="app-shell">
        <AppLangToggle authUser={authUser} />
        <Container maxWidth="sm" sx={{ py: { xs: 4, md: 8 } }}>
          <Paper elevation={0} sx={{ p: { xs: 3, md: 4 }, border: '1px solid #e1e7ef', textAlign: 'center' }}>
            <Stack spacing={2.5} alignItems="center">
              <Typography variant="h4">YoPalette</Typography>
              <Typography color="text.secondary">
                {t('AI 분석은 웹 계정으로 로그인한 뒤 이용할 수 있습니다.')}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('로그인하면 회원 정보와 저장한 퍼스널 컬러가 함께 넘어와 설문을 다시 입력하지 않아도 됩니다.')}
              </Typography>
              {authError && <Alert severity="warning" sx={{ width: '100%' }}>{t(authError)}</Alert>}
              <Button
                variant="contained"
                size="large"
                endIcon={<ArrowRight size={18} />}
                onClick={() => window.location.assign(loginUrl)}
              >
                {t('웹에서 로그인하기')}
              </Button>
            </Stack>
          </Paper>
        </Container>
      </Box>
    );
  }

  if (appModule === 'home') {
    return renderHomePage();
  }

  if (appModule === 'personal-color') {
    return renderPersonalColorPage();
  }

  if (appModule === 'nail-design') {
    return renderNailDesignPage();
  }

  if (appModule === 'virtual-surgery') {
    return renderVirtualSurgeryFlowPage();
  }

  return (
    <Box className="app-shell">
      <AppLangToggle authUser={authUser} />
      <Container maxWidth="lg" sx={{ py: { xs: 2, md: 4 } }}>
        <Paper elevation={0} sx={{ p: { xs: 2, md: 3 }, border: '1px solid #e1e7ef' }}>
          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}>
            <Box>
              <Typography variant="h4">YoPalette</Typography>
              <Typography color="text.secondary">{t('피부 케어 분석 워크스페이스')}</Typography>
              {authUser && (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {authUser.name} {t('님으로 연동됨')}
                </Typography>
              )}
            </Box>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
              <Button variant="outlined" onClick={goHome}>
                {t('홈으로')}
              </Button>
              <Button
                variant="contained"
                startIcon={currentStep === 1 ? <Sparkles size={18} /> : <ArrowRight size={18} />}
                disabled={!canGoNext()}
                onClick={goNext}
              >
                {currentStep === 1 ? '분석 시작' : currentStep === 5 ? '완료' : '다음'}
              </Button>
            </Stack>
          </Stack>
          <Stepper activeStep={currentStep} sx={{ mt: 3 }} alternativeLabel>
            {steps.map((step, index) => (
              <Step key={step} completed={index < highestReadyStep}>
                <StepLabel
                  onClick={() => {
                    if (index <= highestReadyStep + 1) setCurrentStep(index);
                  }}
                  sx={{ cursor: index <= highestReadyStep + 1 ? 'pointer' : 'default' }}
                >
                  {t(step)}
                </StepLabel>
              </Step>
            ))}
          </Stepper>
        </Paper>

        {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}

        <Box sx={{ mt: 2 }}>
          {CurrentPage()}
        </Box>

        <Paper elevation={0} sx={{ mt: 2, p: 2, border: '1px solid #e1e7ef' }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
            <Button
              variant="outlined"
              startIcon={<ArrowLeft size={16} />}
              disabled={currentStep === 0}
              onClick={() => setCurrentStep((step) => Math.max(step - 1, 0))}
            >
              {t('이전')}
            </Button>
            <Typography variant="body2" color="text.secondary">
              {currentStep + 1} / {steps.length}
            </Typography>
            <Button
              variant="contained"
              endIcon={currentStep === 1 ? <Sparkles size={16} /> : <ArrowRight size={16} />}
              disabled={!canGoNext()}
              onClick={goNext}
            >
              {currentStep === 1 ? '분석 시작' : currentStep === 5 ? '완료' : '다음'}
            </Button>
          </Stack>
        </Paper>
      </Container>
    </Box>
  );
}
