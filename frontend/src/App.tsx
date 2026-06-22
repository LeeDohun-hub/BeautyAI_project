import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Container,
  Divider,
  FormControl,
  Grid,
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
  Sparkles,
  Trash2,
} from 'lucide-react';
import { analyzeSkin, chat, getHistory, recommend } from './api/client';
import type { AnalyzeSkinResponse, HistoryItem, Product, RecommendationResponse, SkinScores, SurveyInput } from './types/api';

// 상품을 외부 쇼핑몰에서 검색/열기 위한 링크. 직접 상품 URL이 아마존이면 그대로 쓰고,
// 그 외에는 브랜드+상품명으로 각 플랫폼 검색 결과를 연다 (일본 시장 타겟: 아마존/야후재팬/네이버).
function buildShopLinks(product: Product) {
  const query = encodeURIComponent(`${product.brand} ${product.name}`.trim());
  const amazon =
    product.product_url && /amazon\./i.test(product.product_url)
      ? product.product_url
      : `https://www.amazon.co.jp/s?k=${query}`;
  return {
    oliveyoung: `https://global.oliveyoung.com/display/search?query=${query}`,
    amazon,
    yahoo: `https://shopping.yahoo.co.jp/search?p=${query}`,
    naver: `https://search.shopping.naver.com/search/all?query=${query}`,
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
  { key: 'oliveyoung', label: '올리브영', domain: 'global.oliveyoung.com', bg: '#80BA27', fg: '#FFFFFF', hover: '#6FA31F', kbeautyOnly: true },
  { key: 'amazon', label: '아마존', domain: 'amazon.co.jp', bg: '#FF9900', fg: '#131A22', hover: '#E68A00', kbeautyOnly: false },
  { key: 'yahoo', label: '야후재팬', domain: 'yahoo.co.jp', bg: '#FF0033', fg: '#FFFFFF', hover: '#D9002B', kbeautyOnly: false },
  { key: 'naver', label: '네이버', domain: 'naver.com', bg: '#03C75A', fg: '#FFFFFF', hover: '#02A94C', kbeautyOnly: false },
] as const;

// 사이트 파비콘 URL (구글 파비콘 서비스 — 실제 브랜드 로고를 안정적으로 제공)
const faviconUrl = (domain: string) => `https://www.google.com/s2/favicons?domain=${domain}&sz=64`;

const ageGroups = [
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
            {opt.label}
          </ToggleButton>
        ))}
      </Box>
      {options
        .filter((o) => o.children?.length && value.includes(o.value))
        .map((parent) => (
          <Box key={parent.value} sx={{ mt: 1, ml: 1.5, pl: 1.5, borderLeft: '2px solid #e3e9f2' }}>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
              {parent.label} · 세부 선택
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
                  {child.label}
                </ToggleButton>
              ))}
            </Box>
          </Box>
        ))}
    </Box>
  );
}

const steps = ['설문', '얼굴 입력', '피부 분석', '추천', '상담'];

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

const scoreKeys = Object.keys(scoreLabels) as (keyof SkinScores)[];

function averageSkinScores(results: AnalyzeSkinResponse[]): SkinScores {
  const totals = scoreKeys.reduce(
    (acc, key) => ({ ...acc, [key]: 0 }),
    {} as SkinScores,
  );

  results.forEach((result) => {
    scoreKeys.forEach((key) => {
      totals[key] += result.scores[key];
    });
  });

  return scoreKeys.reduce(
    (acc, key) => ({ ...acc, [key]: Math.round(totals[key] / results.length) }),
    {} as SkinScores,
  );
}

export default function App() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const previewUrlsRef = useRef<string[]>([]);
  const [currentStep, setCurrentStep] = useState(0);
  const [survey, setSurvey] = useState<SurveyInput>({
    gender: 'female',
    age_group: '20s',
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
  const [cameraDevices, setCameraDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [cameraReady, setCameraReady] = useState(false);
  const [analysis, setAnalysis] = useState<AnalyzeSkinResponse | null>(null);
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [message, setMessage] = useState('제 피부 상태에 맞는 루틴을 어떻게 구성하면 좋을까요?');
  const [answer, setAnswer] = useState('');
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState('');
  const [error, setError] = useState('');

  const highestReadyStep = useMemo(() => {
    if (answer) return 4;
    if (recommendation) return 3;
    if (analysis) return 2;
    if (faceFiles.length) return 1;
    return 0;
  }, [answer, recommendation, analysis, faceFiles.length]);

  useEffect(() => {
    getHistory().then(setHistory).catch(() => undefined);
  }, [recommendation]);

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
      setError('카메라 접근 권한이 필요합니다. 브라우저에서 카메라 권한을 허용한 뒤 다시 시도해 주세요.');
    });
  }, [currentStep]);

  useEffect(() => {
    return () => {
      previewUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);

  useEffect(() => {
    previewUrlsRef.current = previewUrls;
  }, [previewUrls]);

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

  async function startCamera(deviceId = selectedDeviceId) {
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('이 브라우저는 카메라 촬영을 지원하지 않습니다.');
      return;
    }

    stopCamera();
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        deviceId: deviceId ? { exact: deviceId } : undefined,
        facingMode: deviceId ? undefined : 'user',
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
  }

  function addFaceFiles(files: File[]) {
    const imageFiles = files.filter((item) => item.type.startsWith('image/'));
    if (!imageFiles.length) {
      setError('이미지 파일만 업로드할 수 있습니다.');
      return;
    }

    const availableSlots = 5 - faceFiles.length;
    if (availableSlots <= 0) {
      setError('상담용 얼굴 사진은 최대 5장까지 선택할 수 있습니다.');
      return;
    }

    const filesToAdd = imageFiles.slice(0, availableSlots);
    setError(imageFiles.length > availableSlots ? '상담용 얼굴 사진은 최대 5장까지 선택할 수 있어 일부 파일만 추가했습니다.' : '');
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
    if (faceFiles.length < 3 || faceFiles.length > 5) {
      setError('정확한 상담을 위해 얼굴 피부 사진을 3~5장 선택해 주세요.');
      setCurrentStep(1);
      return;
    }

    setCurrentStep(2);
    setLoading('analyzing');
    setError('');
    try {
      const results = await Promise.all(faceFiles.map((item) => analyzeSkin(item)));
      const averagedScores = averageSkinScores(results);
      const result: AnalyzeSkinResponse = {
        analysis_id: results[0].analysis_id,
        scores: averagedScores,
        summary: `${results.length}장의 얼굴 사진을 분석해 평균 피부 점수를 계산했습니다.`,
      };
      setAnalysis(result);
      setRecommendation(await recommend(survey, result.analysis_id, result.scores));
    } catch {
      setError('분석에 실패했습니다. 백엔드가 실행 중인지, 얼굴 사진이 정상적으로 선택되었는지 확인해 주세요.');
    } finally {
      setLoading('');
    }
  }

  async function handleChat() {
    setLoading('chat');
    setError('');
    try {
      setAnswer(await chat(message, analysis?.scores));
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

  function canGoNext() {
    if (currentStep === 0) return survey.concerns.length > 0;
    if (currentStep === 1) return faceFiles.length >= 3 && faceFiles.length <= 5 && loading !== 'analyzing';
    if (currentStep === 2) return Boolean(analysis);
    if (currentStep === 3) return Boolean(recommendation);
    return false;
  }

  function renderSurveyPage() {
    const isFemale = survey.gender === 'female';
    const skinConcernList = isFemale ? femaleSkinConcerns : maleSkinConcerns;

    const chipGroupSx = { flexWrap: 'wrap', gap: 1 } as const;
    const chipSx = { border: '1px solid #d6deea !important' } as const;
    const sectionLabelSx = { variant: 'body2', fontWeight: 700, gutterBottom: true } as const;

    return (
      <Paper className="page-panel" elevation={0}>
        <Typography variant="h5" fontWeight={800}>피부 설문</Typography>
        <Typography color="text.secondary" sx={{ mt: 0.5 }}>
          성별과 연령대를 먼저 선택하면 맞춤 고민 항목이 펼쳐집니다.
        </Typography>

        <Stack spacing={3.5} sx={{ mt: 2.5 }}>

          {/* 성별 */}
          <Box>
            <Typography variant="body2" fontWeight={700} gutterBottom>성별</Typography>
            <ToggleButtonGroup
              value={survey.gender}
              exclusive
              onChange={(_, v) => v && setSurvey({
                ...survey, gender: v,
                concerns: [], makeup_concerns: [], area_concerns: [], male_extras: [],
              })}
              fullWidth
            >
              <ToggleButton value="female" sx={{ py: 1.5, fontWeight: 700, fontSize: '0.95rem' }}>
                여성
              </ToggleButton>
              <ToggleButton value="male" sx={{ py: 1.5, fontWeight: 700, fontSize: '0.95rem' }}>
                남성
              </ToggleButton>
            </ToggleButtonGroup>
          </Box>

          {/* 연령대 */}
          <Box>
            <Typography variant="body2" fontWeight={700} gutterBottom>연령대</Typography>
            <ToggleButtonGroup
              value={survey.age_group}
              exclusive
              onChange={(_, v) => v && setSurvey({ ...survey, age_group: v })}
              sx={chipGroupSx}
            >
              {ageGroups.map((a) => (
                <ToggleButton key={a.value} value={a.value} size="small" sx={{ px: 2.5, ...chipSx }}>
                  {a.label}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
          </Box>

          {/* 피부 타입 + 루틴 */}
          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <FormControl fullWidth size="small">
                <InputLabel>피부 타입</InputLabel>
                <Select label="피부 타입" value={survey.skin_type} onChange={(e) => setSurvey({ ...survey, skin_type: e.target.value })}>
                  {skinTypeLabels.map((t) => <MenuItem key={t.value} value={t.value}>{t.label}</MenuItem>)}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} md={6}>
              <FormControl fullWidth size="small">
                <InputLabel>루틴</InputLabel>
                <Select label="루틴" value={survey.routine_level} onChange={(e) => setSurvey({ ...survey, routine_level: e.target.value })}>
                  {routineLevelLabels.map((l) => <MenuItem key={l.value} value={l.value}>{l.label}</MenuItem>)}
                </Select>
              </FormControl>
            </Grid>
          </Grid>

          {/* 피부 고민 */}
          <Box>
            <Typography {...sectionLabelSx}>피부 고민</Typography>
            <NestedChipSelect
              options={skinConcernList}
              value={survey.concerns}
              onChange={(v) => setSurvey({ ...survey, concerns: v })}
            />
          </Box>

          {/* 여성: 메이크업 베이스 고민 */}
          {isFemale && (
            <Box>
              <Typography variant="body2" fontWeight={700} gutterBottom>메이크업 베이스 고민</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                베이스 메이크업 시 불편한 점을 선택해 주세요
              </Typography>
              <NestedChipSelect
                options={makeupConcernOptions}
                value={survey.makeup_concerns}
                onChange={(v) => setSurvey({ ...survey, makeup_concerns: v })}
              />
            </Box>
          )}

          {/* 여성: 부위별 케어 */}
          {isFemale && (
            <Box>
              <Typography variant="body2" fontWeight={700} gutterBottom>부위별 케어</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                집중적으로 케어하고 싶은 부위를 선택해 주세요
              </Typography>
              <NestedChipSelect
                options={areaConcernOptions}
                value={survey.area_concerns}
                onChange={(v) => setSurvey({ ...survey, area_concerns: v })}
              />
            </Box>
          )}

          {/* 남성: 추가 케어 영역 */}
          {!isFemale && (
            <Box>
              <Typography variant="body2" fontWeight={700} gutterBottom>추가 케어 관심 영역</Typography>
              <ToggleButtonGroup
                value={survey.male_extras}
                onChange={(_, v) => setSurvey({ ...survey, male_extras: v })}
                size="small"
                sx={chipGroupSx}
              >
                {maleExtraOptions.map((c) => (
                  <ToggleButton key={c.value} value={c.value} sx={chipSx}>{c.label}</ToggleButton>
                ))}
              </ToggleButtonGroup>
            </Box>
          )}

          {/* 민감도 */}
          <Box>
            <Typography variant="body2" fontWeight={700}>민감도</Typography>
            <Slider
              value={survey.sensitivity}
              min={1}
              max={5}
              marks={[
                { value: 1, label: '낮음' },
                { value: 3, label: '보통' },
                { value: 5, label: '높음' },
              ]}
              onChange={(_, v) => setSurvey({ ...survey, sensitivity: v as number })}
              sx={{ mt: 1 }}
            />
          </Box>

        </Stack>
      </Paper>
    );
  }

  function renderFacePage() {
    return (
      <Grid container spacing={2}>
        <Grid item xs={12} lg={7}>
          <Paper className="page-panel" elevation={0}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
              <Box>
                <Typography variant="h5" fontWeight={800}>얼굴 입력</Typography>
                <Typography color="text.secondary" sx={{ mt: 0.5 }}>
                  상담받고 싶은 얼굴 피부 사진을 3~5장 등록해 주세요.
                </Typography>
              </Box>
              <Button size="small" variant="outlined" startIcon={<RefreshCcw size={14} />} onClick={() => startCamera()}>
                새로고침
              </Button>
            </Stack>

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
                  <Typography variant="body2" color="text.secondary">카메라 권한을 기다리는 중입니다</Typography>
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
                  <InputLabel>카메라</InputLabel>
                  <Select
                    label="카메라"
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
                  웹캠으로 촬영
                </Button>
                <Button
                  fullWidth
                  component="label"
                  variant="outlined"
                  startIcon={<ImagePlus size={16} />}
                  disabled={faceFiles.length >= 5}
                >
                  사진 업로드
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
                현재 {faceFiles.length}/5장 선택됨. 분석에는 최소 3장이 필요합니다.
              </Alert>
              {!!previewUrls.length && (
                <Box className="photo-grid">
                  {previewUrls.map((url, index) => (
                    <Box className="capture-preview" key={url}>
                      <img src={url} alt={`선택한 얼굴 사진 ${index + 1}`} />
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
        <Typography variant="h5" fontWeight={800}>피부 분석</Typography>
        {loading === 'analyzing' && (
          <Stack spacing={2} sx={{ mt: 3 }}>
            <LinearProgress />
            <Typography color="text.secondary">등록한 얼굴 사진을 분석하고 추천 후보를 계산하는 중입니다.</Typography>
          </Stack>
        )}
        {!loading && analysis ? (
          <Stack spacing={1.5} sx={{ mt: 3 }}>
            {(Object.entries(analysis.scores) as [keyof SkinScores, number][]).map(([key, value]) => (
              <Box className="score-row" key={key}>
                <Typography variant="body2">{scoreLabels[key]}</Typography>
                <LinearProgress variant="determinate" value={value} sx={{ height: 10, borderRadius: 1 }} />
                <Typography variant="body2" textAlign="right">{value}</Typography>
              </Box>
            ))}
            <Alert severity="info">{analysis.summary}</Alert>
          </Stack>
        ) : !loading ? (
          <Alert severity="info" sx={{ mt: 3 }}>얼굴 사진 3~5장을 등록한 뒤 분석을 실행해 주세요.</Alert>
        ) : null}
      </Paper>
    );
  }

  function renderRecommendationPage() {
    return (
      <Grid container spacing={2}>
        <Grid item xs={12} lg={8}>
          <Paper className="page-panel" elevation={0}>
            <Typography variant="h5" fontWeight={800}>맞춤 추천</Typography>
            {recommendation ? (
              <Stack spacing={2} sx={{ mt: 2 }}>
                <Alert severity="success">{recommendation.explanation}</Alert>
                <Box>
                  <Typography variant="subtitle2" gutterBottom>추천 성분</Typography>
                  <Stack direction="row" flexWrap="wrap" gap={1}>
                    {recommendation.ingredients.map((ingredient) => (
                      <Chip key={ingredient.id} label={ingredient.name} color="primary" variant="outlined" />
                    ))}
                  </Stack>
                </Box>
                <Divider />
                {recommendation.products.map((product, index) => {
                  const links = buildShopLinks(product);
                  return (
                  <Box key={product.id} className="product-row">
                    <Typography variant="caption" color="text.secondary">추천 {index + 1}</Typography>
                    <Stack direction="row" justifyContent="space-between" alignItems="center" gap={1}>
                      <Typography fontWeight={800}>{product.name}</Typography>
                      <Chip size="small" label={`${product.score ?? 0}`} color="secondary" />
                    </Stack>
                    <Stack direction="row" alignItems="center" gap={1} flexWrap="wrap">
                      <Typography variant="body2" color="text.secondary">
                        {product.brand} · {product.category}
                        {product.price > 0 && ` · $${(product.price / 100).toFixed(2)}`}
                      </Typography>
                      {product.avg_rating != null && (
                        <Typography variant="caption" color="text.secondary">
                          ★ {product.avg_rating.toFixed(1)}
                          {product.review_count != null && ` (${product.review_count.toLocaleString()}개 리뷰)`}
                        </Typography>
                      )}
                    </Stack>
                    <Typography variant="body2" sx={{ mt: 0.5 }}>{product.description}</Typography>
                    <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mt: 1 }}>
                      {SHOP_PLATFORMS.filter((platform) => !platform.kbeautyOnly || isKBeauty(product.brand)).map((platform) => (
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
                            <Box
                              sx={{
                                width: 18,
                                height: 18,
                                borderRadius: '4px',
                                bgcolor: '#fff',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                              }}
                            >
                              <Box
                                component="img"
                                src={faviconUrl(platform.domain)}
                                alt=""
                                width={14}
                                height={14}
                                sx={{ display: 'block' }}
                              />
                            </Box>
                          }
                          sx={{
                            bgcolor: platform.bg,
                            color: platform.fg,
                            fontWeight: 700,
                            '&:hover': { bgcolor: platform.hover },
                          }}
                        >
                          {platform.label} 열기
                        </Button>
                      ))}
                    </Stack>
                  </Box>
                  );
                })}
              </Stack>
            ) : (
              <Alert severity="info" sx={{ mt: 2 }}>분석 후 추천 상품이 표시됩니다.</Alert>
            )}
          </Paper>
        </Grid>
        <Grid item xs={12} lg={4}>
          <Paper className="page-panel" elevation={0}>
            <Stack direction="row" spacing={1} alignItems="center">
              <History size={18} />
              <Typography variant="h6">추천 기록</Typography>
            </Stack>
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {history.slice(0, 5).map((item) => (
                <Box key={item.id}>
                  <Typography variant="body2" fontWeight={700}>{item.recommended_products.slice(0, 2).join(', ')}</Typography>
                  <Typography variant="caption" color="text.secondary">{new Date(item.created_at).toLocaleString('ko-KR')}</Typography>
                </Box>
              ))}
              {!history.length && <Typography color="text.secondary" variant="body2">아직 추천 기록이 없습니다.</Typography>}
            </Stack>
          </Paper>
        </Grid>
      </Grid>
    );
  }

  function renderConsultPage() {
    return (
      <Paper className="page-panel" elevation={0}>
        <Typography variant="h5" fontWeight={800}>AI 피부 상담</Typography>
        <Typography color="text.secondary" sx={{ mt: 0.5 }}>
          분석 점수를 바탕으로 루틴, 성분 사용 순서, 주의점을 질문할 수 있습니다.
        </Typography>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mt: 3 }}>
          <TextField fullWidth size="small" value={message} onChange={(event) => setMessage(event.target.value)} />
          <Button variant="contained" startIcon={<Send size={16} />} onClick={handleChat} disabled={loading === 'chat'}>
            질문
          </Button>
        </Stack>
        {answer && <Alert icon={<MessageSquare size={18} />} severity="success" sx={{ mt: 2 }}>{answer}</Alert>}
      </Paper>
    );
  }

  const pages = [
    renderSurveyPage,
    renderFacePage,
    renderAnalysisPage,
    renderRecommendationPage,
    renderConsultPage,
  ];
  const CurrentPage = pages[currentStep];

  return (
    <Box className="app-shell">
      <Container maxWidth="lg" sx={{ py: { xs: 2, md: 4 } }}>
        <Paper elevation={0} sx={{ p: { xs: 2, md: 3 }, border: '1px solid #e1e7ef' }}>
          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}>
            <Box>
              <Typography variant="h4">BeautyAI</Typography>
              <Typography color="text.secondary">AI 피부 분석 및 화장품 추천 워크스페이스</Typography>
            </Box>
            <Button
              variant="contained"
              startIcon={currentStep === 1 ? <Sparkles size={18} /> : <ArrowRight size={18} />}
              disabled={!canGoNext()}
              onClick={goNext}
            >
              {currentStep === 1 ? '분석 시작' : currentStep === 4 ? '완료' : '다음'}
            </Button>
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
                  {step}
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
              이전
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
              {currentStep === 1 ? '분석 시작' : currentStep === 4 ? '완료' : '다음'}
            </Button>
          </Stack>
        </Paper>
      </Container>
    </Box>
  );
}
