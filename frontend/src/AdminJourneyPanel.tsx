import { useEffect, useState } from 'react';
import { Alert, Box, Button, Chip, Grid, LinearProgress, Paper, Stack, Typography } from '@mui/material';

import { fetchJourneyFunnel, fetchJourneySessions, fetchJourneyTrail } from './api/client';
import { useT } from './i18n';
import type { JourneyFunnel, JourneyLabelCount, JourneyTrail } from './types/api';

/**
 * 관리자용 회원 동선 패널. 홈 화면 아래에 붙고 **관리자에게만** 보인다.
 *
 * WEB 관리자 화면과 표의 뜻이 같다. 다만 AI 는 물건을 파는 앱이 아니라 분석해 주는
 * 앱이라, 이탈의 큰 몫이 '분석 실패' 에서 나온다 — 그래서 퍼널 옆에 실패 사유를 나란히
 * 둔다. 사진 안내를 고칠 문제인지 모델을 고칠 문제인지는 사유를 봐야 갈린다.
 *
 * App.tsx 안에 두지 않은 이유: 그 파일이 이미 6,000줄이 넘는다. 관리자만 보는 화면이라
 * 사용자 흐름과 얽히는 곳도 없어 따로 두는 편이 읽기 쉽다.
 */
export default function AdminJourneyPanel() {
  const t = useT();
  const [days, setDays] = useState(7);
  const [funnel, setFunnel] = useState<JourneyFunnel | null>(null);
  const [sessions, setSessions] = useState<JourneyLabelCount[]>([]);
  const [trail, setTrail] = useState<JourneyTrail | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle');

  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    Promise.all([fetchJourneyFunnel(days), fetchJourneySessions(days, 20)])
      .then(([funnelData, sessionList]) => {
        if (cancelled) return;
        setFunnel(funnelData);
        setSessions(sessionList);
        setStatus('idle');
      })
      .catch(() => {
        if (cancelled) return;
        setFunnel(null);
        setSessions([]);
        setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  const stepLabel = (type: string) =>
    ({
      app_open: t('AI 앱 진입'),
      module_open: t('기능 선택'),
      photo_ready: t('사진 준비'),
      analysis_done: t('분석 완료'),
      analysis_error: t('분석 실패'),
      recommend_view: t('추천 확인'),
      product_click: t('상품 클릭'),
      cart_handoff: t('장바구니 담기'),
      gate_view: t('로그인 안내'),
      survey_submit: t('설문 제출'),
    })[type] ?? type;

  /** 초 단위 간격을 읽기 쉬운 단위로. 어디서 오래 붙잡혔는지가 한눈에 보여야 한다. */
  const gapText = (seconds?: number | null) => {
    if (seconds === null || seconds === undefined) return '—';
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 360) / 10}h`;
  };

  const cell = { p: 1.2, borderBottom: '1px solid #f0f7fc' } as const;

  return (
    <Paper elevation={0} sx={{ mt: 3, p: { xs: 2, md: 3 }, border: '1px solid #e1e7ef' }}>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        justifyContent="space-between"
        alignItems={{ sm: 'center' }}
        spacing={1.5}
      >
        <Box>
          <Typography variant="h6" fontWeight={800}>
            {t('회원 동선 · 이탈')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('진입에서 상품 클릭까지 단계별로 몇 명이 남는지 봅니다. 단위는 세션이라 한 사람이 열 번 눌러도 1로 셉니다.')}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          {[1, 7, 30, 90].map((value) => (
            <Button
              key={value}
              size="small"
              variant={days === value ? 'contained' : 'outlined'}
              onClick={() => setDays(value)}
            >
              {value}
              {t('일')}
            </Button>
          ))}
        </Stack>
      </Stack>

      {status === 'loading' && <LinearProgress sx={{ mt: 2 }} />}
      {status === 'error' && (
        <Alert severity="info" sx={{ mt: 2 }}>
          {t('동선 통계는 관리자만 볼 수 있습니다.')}
        </Alert>
      )}
      {funnel && funnel.total_events === 0 && (
        <Alert severity="info" sx={{ mt: 2 }}>
          {t('아직 쌓인 동선 데이터가 없습니다.')}
        </Alert>
      )}

      {funnel && funnel.total_events > 0 && (
        <>
          <Box sx={{ overflowX: 'auto', mt: 2 }}>
            <Box component="table" sx={{ width: '100%', minWidth: 560, borderCollapse: 'collapse', fontSize: 13 }}>
              <Box component="thead">
                <Box component="tr">
                  {[t('단계'), t('세션'), t('직전 대비'), t('이탈'), t('진입 대비'), t('순서 무관')].map((head) => (
                    <Box
                      component="th"
                      key={head}
                      sx={{ ...cell, textAlign: 'left', borderBottom: '1px solid #e6f1f8', color: '#52667a' }}
                    >
                      {head}
                    </Box>
                  ))}
                </Box>
              </Box>
              <Box component="tbody">
                {funnel.steps.map((step, index) => (
                  <Box component="tr" key={step.type}>
                    <Box component="td" sx={cell}>
                      {stepLabel(step.type)}
                    </Box>
                    <Box component="td" sx={cell}>
                      {step.sessions.toLocaleString()}
                    </Box>
                    {/* 첫 단계는 '직전'이 없다. 100% 라고 쓰면 아무도 안 빠진 것처럼 읽힌다. */}
                    <Box component="td" sx={cell}>
                      {index === 0 ? '—' : `${step.from_previous_percent}%`}
                    </Box>
                    <Box component="td" sx={cell}>
                      {index === 0 ? '—' : `${step.drop_off_percent}%`}
                    </Box>
                    <Box component="td" sx={cell}>
                      {step.from_start_percent}%
                    </Box>
                    {/* 순서 무관 수치가 더 크면 그 단계를 건너뛴 사람이 있다는 뜻이다. */}
                    <Box component="td" sx={cell}>
                      {step.sessions_any_order.toLocaleString()}
                      {step.sessions_any_order > step.sessions
                        ? ` (+${step.sessions_any_order - step.sessions})`
                        : ''}
                    </Box>
                  </Box>
                ))}
              </Box>
            </Box>
          </Box>

          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid item xs={12} md={6}>
              <Typography variant="subtitle2" sx={{ mb: 0.8 }}>
                {t('기능별 진입')}
              </Typography>
              <Stack spacing={0.5}>
                {funnel.modules.length === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    {t('아직 없습니다.')}
                  </Typography>
                ) : (
                  funnel.modules.map((row) => (
                    <Stack key={row.label} direction="row" justifyContent="space-between">
                      <Typography variant="body2" color="text.secondary">
                        {row.label}
                      </Typography>
                      <Typography variant="body2" fontWeight={700}>
                        {row.total}
                      </Typography>
                    </Stack>
                  ))
                )}
              </Stack>
            </Grid>
            <Grid item xs={12} md={6}>
              <Typography variant="subtitle2" sx={{ mb: 0.8 }}>
                {t('분석 실패 사유')}
              </Typography>
              <Stack spacing={0.5}>
                {funnel.errors.length === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    {t('실패 기록이 없습니다.')}
                  </Typography>
                ) : (
                  funnel.errors.map((row) => (
                    <Stack key={row.label} direction="row" justifyContent="space-between" gap={2}>
                      <Typography variant="body2" color="text.secondary" noWrap>
                        {row.label}
                      </Typography>
                      <Typography variant="body2" fontWeight={700}>
                        {row.total}
                      </Typography>
                    </Stack>
                  ))
                )}
              </Stack>
            </Grid>
          </Grid>

          <Typography variant="subtitle2" sx={{ mt: 2.5, mb: 0.8 }}>
            {t('최근 세션')}
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={0.8}>
            {sessions.map((row) => (
              <Chip
                key={row.label}
                label={`${row.label.slice(0, 8)} · ${row.total}`}
                size="small"
                variant={trail?.session_id === row.label ? 'filled' : 'outlined'}
                color={trail?.session_id === row.label ? 'primary' : 'default'}
                onClick={() => {
                  fetchJourneyTrail(row.label)
                    .then(setTrail)
                    .catch(() => setTrail(null));
                }}
              />
            ))}
          </Stack>

          {trail && trail.steps.length > 0 && (
            <Box sx={{ overflowX: 'auto', mt: 1.5 }}>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.8 }}>
                {trail.user_id ? `${t('회원')} #${trail.user_id}` : t('비로그인')}
              </Typography>
              <Box component="table" sx={{ width: '100%', minWidth: 460, borderCollapse: 'collapse', fontSize: 13 }}>
                <Box component="tbody">
                  {trail.steps.map((step, index) => (
                    <Box component="tr" key={`${step.at}-${index}`}>
                      <Box component="td" sx={cell}>
                        {stepLabel(step.type)}
                      </Box>
                      <Box component="td" sx={{ ...cell, color: '#52667a' }}>
                        {step.product_name || step.detail || step.module || '—'}
                      </Box>
                      <Box component="td" sx={{ ...cell, color: '#52667a' }}>
                        {gapText(step.seconds_from_previous)}
                      </Box>
                    </Box>
                  ))}
                </Box>
              </Box>
            </Box>
          )}
        </>
      )}
    </Paper>
  );
}
