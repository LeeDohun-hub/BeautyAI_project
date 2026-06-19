import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Container,
  Divider,
  FormControl,
  FormControlLabel,
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
import { Camera, History, MessageSquare, RefreshCcw, Send, Sparkles } from 'lucide-react';
import { analyzeSkin, chat, getHistory, recommend } from './api/client';
import type { AnalyzeSkinResponse, HistoryItem, RecommendationResponse, SkinScores, SurveyInput } from './types/api';

const concerns = ['acne', 'pore', 'wrinkle', 'redness', 'pigmentation', 'oiliness'];
const steps = ['Survey', 'Camera', 'Analysis', 'Recommendation', 'Consult'];

const scoreLabels: Record<keyof SkinScores, string> = {
  acne: 'Acne',
  pore: 'Pore',
  wrinkle: 'Wrinkle',
  redness: 'Redness',
  pigmentation: 'Pigmentation',
  oiliness: 'Oiliness',
};

export default function App() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [survey, setSurvey] = useState<SurveyInput>({
    skin_type: 'combination',
    concerns: ['pore'],
    sensitivity: 3,
    routine_level: 'basic',
  });
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState('');
  const [cameraDevices, setCameraDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [cameraReady, setCameraReady] = useState(false);
  const [analysis, setAnalysis] = useState<AnalyzeSkinResponse | null>(null);
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [message, setMessage] = useState('How should I build my routine?');
  const [answer, setAnswer] = useState('');
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState('');
  const [error, setError] = useState('');

  const activeStep = useMemo(() => {
    if (answer) return 4;
    if (recommendation) return 3;
    if (analysis) return 2;
    if (file) return 1;
    return 0;
  }, [answer, recommendation, analysis, file]);

  useEffect(() => {
    getHistory().then(setHistory).catch(() => undefined);
  }, [recommendation]);

  useEffect(() => {
    startCamera().catch(() => {
      setError('Camera access is required. Allow camera permission in the browser and try again.');
    });
    return () => {
      stopCamera();
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, []);

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

  async function startCamera(deviceId = selectedDeviceId) {
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('This browser does not support camera capture.');
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
    if (videoRef.current) {
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
    }
    setCameraReady(true);
    await refreshCameraDevices();
  }

  async function handleCameraChange(deviceId: string) {
    setSelectedDeviceId(deviceId);
    await startCamera(deviceId);
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
    const capturedFile = new File([blob], `beautyai-camera-${Date.now()}.jpg`, { type: 'image/jpeg' });
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setFile(capturedFile);
    setPreviewUrl(URL.createObjectURL(blob));
    setAnalysis(null);
    setRecommendation(null);
    setAnswer('');
  }

  async function handleAnalyze() {
    if (!file) return;
    setLoading('analyzing');
    setError('');
    try {
      const result = await analyzeSkin(file);
      setAnalysis(result);
      const rec = await recommend(survey, result.analysis_id, result.scores);
      setRecommendation(rec);
    } catch (err) {
      setError('Analysis failed. Check that the backend is running and the camera image was captured.');
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
      setError('Chat failed. Check the backend connection.');
    } finally {
      setLoading('');
    }
  }

  return (
    <Box className="app-shell">
      <Container maxWidth="xl" sx={{ py: { xs: 2, md: 4 } }}>
        <Paper elevation={0} sx={{ p: { xs: 2, md: 3 }, border: '1px solid #e1e7ef' }}>
          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}>
            <Box>
              <Typography variant="h4">BeautyAI</Typography>
              <Typography color="text.secondary">AI skin analysis and cosmetics recommendation workspace</Typography>
            </Box>
            <Button variant="contained" startIcon={<Sparkles size={18} />} disabled={!file || loading === 'analyzing'} onClick={handleAnalyze}>
              Analyze & Recommend
            </Button>
          </Stack>
          <Stepper activeStep={activeStep} sx={{ mt: 3 }} alternativeLabel>
            {steps.map((step) => (
              <Step key={step}>
                <StepLabel>{step}</StepLabel>
              </Step>
            ))}
          </Stepper>
        </Paper>

        {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}

        <Grid container spacing={2} sx={{ mt: 0 }}>
          <Grid item xs={12} lg={4}>
            <Paper elevation={0} sx={{ p: 2.5, border: '1px solid #e1e7ef' }}>
              <Typography variant="h6">Survey</Typography>
              <Stack spacing={2} sx={{ mt: 2 }}>
                <FormControl fullWidth size="small">
                  <InputLabel>Skin type</InputLabel>
                  <Select
                    label="Skin type"
                    value={survey.skin_type}
                    onChange={(event) => setSurvey({ ...survey, skin_type: event.target.value })}
                  >
                    {['dry', 'oily', 'combination', 'normal', 'sensitive'].map((type) => (
                      <MenuItem value={type} key={type}>{type}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Box>
                  <Typography variant="body2" color="text.secondary" gutterBottom>Concerns</Typography>
                  <ToggleButtonGroup
                    value={survey.concerns}
                    onChange={(_, value) => setSurvey({ ...survey, concerns: value })}
                    size="small"
                    sx={{ flexWrap: 'wrap', gap: 1 }}
                  >
                    {concerns.map((concern) => (
                      <ToggleButton key={concern} value={concern} sx={{ border: '1px solid #d6deea !important' }}>
                        {concern}
                      </ToggleButton>
                    ))}
                  </ToggleButtonGroup>
                </Box>
                <Box>
                  <Typography variant="body2" color="text.secondary">Sensitivity</Typography>
                  <Slider
                    value={survey.sensitivity}
                    min={1}
                    max={5}
                    marks
                    onChange={(_, value) => setSurvey({ ...survey, sensitivity: value as number })}
                  />
                </Box>
                <FormControlLabel
                  control={
                    <Select
                      size="small"
                      value={survey.routine_level}
                      onChange={(event) => setSurvey({ ...survey, routine_level: event.target.value })}
                    >
                      <MenuItem value="minimal">minimal</MenuItem>
                      <MenuItem value="basic">basic</MenuItem>
                      <MenuItem value="advanced">advanced</MenuItem>
                    </Select>
                  }
                  label="Routine"
                  labelPlacement="start"
                  sx={{ justifyContent: 'space-between', ml: 0 }}
                />
              </Stack>
            </Paper>

            <Paper elevation={0} sx={{ p: 2.5, mt: 2, border: '1px solid #e1e7ef' }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
                <Typography variant="h6">Face Camera</Typography>
                <Button size="small" variant="outlined" startIcon={<RefreshCcw size={14} />} onClick={() => startCamera()}>
                  Refresh
                </Button>
              </Stack>
              <Box className="camera-box" sx={{ mt: 2 }}>
                <video ref={videoRef} className="camera-video" playsInline muted />
                {!cameraReady && (
                  <Stack className="camera-empty" alignItems="center" spacing={1}>
                    <Camera size={32} />
                    <Typography variant="body2" color="text.secondary">Waiting for camera permission</Typography>
                  </Stack>
                )}
              </Box>
              <canvas ref={canvasRef} hidden />
              <Stack spacing={1.5} sx={{ mt: 2 }}>
                {cameraDevices.length > 1 && (
                  <FormControl fullWidth size="small">
                    <InputLabel>Camera</InputLabel>
                    <Select
                      label="Camera"
                      value={selectedDeviceId}
                      onChange={(event) => handleCameraChange(event.target.value)}
                    >
                      {cameraDevices.map((device, index) => (
                        <MenuItem key={device.deviceId} value={device.deviceId}>
                          {device.label || `Camera ${index + 1}`}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                )}
                <Button variant="contained" startIcon={<Camera size={16} />} onClick={captureFaceImage} disabled={!cameraReady}>
                  Capture face
                </Button>
                {previewUrl && (
                  <Box className="capture-preview">
                    <img src={previewUrl} alt="Captured face" />
                    <Typography variant="body2" color="text.secondary">{file?.name}</Typography>
                  </Box>
                )}
              </Stack>
            </Paper>
          </Grid>

          <Grid item xs={12} lg={5}>
            <Paper elevation={0} sx={{ p: 2.5, border: '1px solid #e1e7ef' }}>
              <Typography variant="h6">Skin Analysis</Typography>
              {loading === 'analyzing' && <LinearProgress sx={{ my: 2 }} />}
              {analysis ? (
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  {(Object.entries(analysis.scores) as [keyof SkinScores, number][]).map(([key, value]) => (
                    <Box className="score-row" key={key}>
                      <Typography variant="body2">{scoreLabels[key]}</Typography>
                      <LinearProgress variant="determinate" value={value} sx={{ height: 10, borderRadius: 1 }} />
                      <Typography variant="body2" textAlign="right">{value}</Typography>
                    </Box>
                  ))}
                  <Alert severity="info">{analysis.summary}</Alert>
                </Stack>
              ) : (
                <Typography sx={{ mt: 2 }} color="text.secondary">Capture a face image with the camera and run analysis.</Typography>
              )}
            </Paper>

            <Paper elevation={0} sx={{ p: 2.5, mt: 2, border: '1px solid #e1e7ef' }}>
              <Typography variant="h6">AI Consultation</Typography>
              <Stack direction="row" spacing={1.5} sx={{ mt: 2 }}>
                <TextField fullWidth size="small" value={message} onChange={(event) => setMessage(event.target.value)} />
                <Button variant="contained" startIcon={<Send size={16} />} onClick={handleChat} disabled={loading === 'chat'}>
                  Ask
                </Button>
              </Stack>
              {answer && <Alert icon={<MessageSquare size={18} />} severity="success" sx={{ mt: 2 }}>{answer}</Alert>}
            </Paper>
          </Grid>

          <Grid item xs={12} lg={3}>
            <Paper elevation={0} sx={{ p: 2.5, border: '1px solid #e1e7ef' }}>
              <Typography variant="h6">Recommendations</Typography>
              {recommendation ? (
                <Stack spacing={2} sx={{ mt: 2 }}>
                  <Alert severity="success">{recommendation.explanation}</Alert>
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>Ingredients</Typography>
                    <Stack direction="row" flexWrap="wrap" gap={1}>
                      {recommendation.ingredients.map((ingredient) => (
                        <Chip key={ingredient.id} label={ingredient.name} color="primary" variant="outlined" />
                      ))}
                    </Stack>
                  </Box>
                  <Divider />
                  {recommendation.products.map((product) => (
                    <Box key={product.id}>
                      <Stack direction="row" justifyContent="space-between" alignItems="center">
                        <Typography fontWeight={800}>{product.name}</Typography>
                        <Chip size="small" label={`${product.score ?? 0}`} color="secondary" />
                      </Stack>
                      <Typography variant="body2" color="text.secondary">{product.brand} · {product.category} · {product.price.toLocaleString()} KRW</Typography>
                      <Typography variant="body2" sx={{ mt: 0.5 }}>{product.description}</Typography>
                    </Box>
                  ))}
                </Stack>
              ) : (
                <Typography sx={{ mt: 2 }} color="text.secondary">Top 5 products will appear after analysis.</Typography>
              )}
            </Paper>

            <Paper elevation={0} sx={{ p: 2.5, mt: 2, border: '1px solid #e1e7ef' }}>
              <Stack direction="row" spacing={1} alignItems="center">
                <History size={18} />
                <Typography variant="h6">History</Typography>
              </Stack>
              <Stack spacing={1.5} sx={{ mt: 2 }}>
                {history.slice(0, 5).map((item) => (
                  <Box key={item.id}>
                    <Typography variant="body2" fontWeight={700}>{item.recommended_products.slice(0, 2).join(', ')}</Typography>
                    <Typography variant="caption" color="text.secondary">{new Date(item.created_at).toLocaleString()}</Typography>
                  </Box>
                ))}
                {!history.length && <Typography color="text.secondary" variant="body2">No recommendation history yet.</Typography>}
              </Stack>
            </Paper>
          </Grid>
        </Grid>
      </Container>
    </Box>
  );
}
