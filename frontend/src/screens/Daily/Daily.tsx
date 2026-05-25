import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchDaily, fetchDailyHistory } from '../../api/client';
import type { DailyHistoryResponse, DailyResponse } from '../../types';
import { useGameStore } from '../../store/gameStore';
import { formatTime } from '../../utils/formatTime';
import { DailyHistory } from './DailyHistory';
import './Daily.css';

function formatDate(dateStr: string): string {
  const [year, month, day] = dateStr.split('-').map(Number);
  return new Date(year, month - 1, day).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
}

function buildChain(hops: number): string {
  return Array.from({ length: hops + 1 }, (_, i) => i % 2 === 0 ? '🟡' : '🟣').join('');
}

function buildShareText(
  date: string,
  source: string,
  target: string,
  hops: number,
  optimalHops: number,
  timeMs: number | null,
): string {
  const actors = Math.ceil(hops / 2) - 1;
  const optimalActors = Math.ceil(optimalHops / 2) - 1;
  const chain = buildChain(hops);
  const timePart = timeMs != null ? ` in ${formatTime(timeMs)}` : '';
  const statusPart = actors <= optimalActors ? ' · ✓ best answer!' : ` · (best: ${optimalActors})`;
  return `Connactor Daily · ${date}\n\n${source} → ${target}\n\n${chain}\n${actors} actor${actors !== 1 ? 's' : ''}${timePart}${statusPart}\n\nconnactor.com/daily`;
}

export function Daily() {
  const navigate = useNavigate();
  const { fetchDailyGame, dismissDaily, isLoading, endError, dailyData } = useGameStore();
  const started = useRef(false);
  const [historyData, setHistoryData] = useState<DailyHistoryResponse | null>(null);
  const [freshDaily, setFreshDaily] = useState<DailyResponse | null>(null);

  const handleSkip = () => {
    dismissDaily();
    navigate('/', { replace: true });
  };

  useEffect(() => {
    document.body.style.background = '#FAF7F2';
    if (started.current) return;
    started.current = true;
    fetchDailyGame().then((daily) => {
      if (daily && !daily.already_completed) {
        navigate('/game');
      } else if (daily?.already_completed) {
        // Always re-fetch from server — cache won't have today_stats
        fetchDaily().then(setFreshDaily).catch(() => null);
        fetchDailyHistory().then(setHistoryData).catch(() => null);
      }
    });
    // started.current guards against double-invocation (React Strict Mode);
    // exhaustive-deps is intentionally suppressed — this must run once only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Merge: use dailyData as the source of truth for completion status,
  // but pull today_stats from the fresh server fetch (which has percentiles).
  const resolvedDaily = dailyData
    ? { ...dailyData, today_stats: freshDaily?.today_stats ?? dailyData.today_stats }
    : freshDaily;

  if (isLoading || (!resolvedDaily && !endError)) {
    return (
      <div className="daily">
        <div className="daily__loading">Loading today's puzzle…</div>
      </div>
    );
  }

  if (endError) {
    return (
      <div className="daily">
        <div className="daily__error">{endError}</div>
        <button className="btn btn--ghost" onClick={() => navigate('/')}>Home</button>
      </div>
    );
  }
  if (resolvedDaily?.already_completed && resolvedDaily.completion) {
    const { puzzle_date, completion, optimal_hops, source, target, current_streak } = resolvedDaily;
    // TODO: remove mock data once backend is deployed
    const today_stats = resolvedDaily.today_stats ?? {
      answer_percentile: 73,
      speed_percentile: 61,
      path_uniqueness: 18,
      total_players_today: 42,
    };
    const mockHistoryData = historyData ?? {
      entries: [
        { puzzle_date: '2026-05-25', hops: 2, time_ms: 15000, is_best: true },
        { puzzle_date: '2026-05-24', hops: 4, time_ms: 32000, is_best: true },
        { puzzle_date: '2026-05-23', hops: 6, time_ms: 58000, is_best: false },
        { puzzle_date: '2026-05-22', hops: 4, time_ms: 27000, is_best: true },
        { puzzle_date: '2026-05-21', hops: 8, time_ms: 91000, is_best: false },
      ],
      bucket_1: 3,
      bucket_2: 8,
      bucket_3: 5,
      bucket_4: 2,
      bucket_5: 1,
      bucket_6_plus: 0,
      total: 5,
    };
    const [y, m, d] = puzzle_date.split('-').map(Number);
    const formattedDate = new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
    const shareText = buildShareText(formattedDate, source.label, target.label, completion.hops, optimal_hops, completion.time_ms);
    const actors = Math.ceil(completion.hops / 2) - 1;
    const optimalActors = Math.ceil(optimal_hops / 2) - 1;

    const handleShare = () => {
      if (navigator.share) {
        navigator.share({ text: shareText }).catch(() => null);
      } else {
        navigator.clipboard.writeText(shareText).catch(() => null);
        alert('Result copied to clipboard!');
      }
    };

    return (
      <div className="daily">
        <button className="daily__back btn btn--ghost" onClick={() => navigate('/')}>← Home</button>
        <div className="daily__content">
          <div className="daily__label">Daily challenge</div>
          <h1 className="daily__date">{formatDate(puzzle_date)}</h1>
          <div className="daily__pair">
            <span className="daily__actor">{source.label}</span>
            <span className="daily__arrow">→</span>
            <span className="daily__actor">{target.label}</span>
          </div>

          <div className="daily__already-done">
            <div className="daily__done-title">Your answer</div>
            <div className="daily__stats">
              <div className="daily__stat">
                <span className="daily__stat-num">{actors}</span>
                <span className="daily__stat-label">actor{actors !== 1 ? 's' : ''}</span>
              </div>
              {completion.time_ms != null && (
                <div className="daily__stat">
                  <span className="daily__stat-num">{formatTime(completion.time_ms)}</span>
                  <span className="daily__stat-label">time</span>
                </div>
              )}
              <div className="daily__stat">
                <span className="daily__stat-num">{Math.max(current_streak, 1)}</span>
                <span className="daily__stat-label">streak</span>
              </div>
            </div>
            {actors <= optimalActors && <span className="daily__optimal-badge">Best answer!</span>}
            {actors > optimalActors && (
              <div className="daily__optimal-info">Best possible: {optimalActors} actor{optimalActors !== 1 ? 's' : ''}</div>
            )}

            {today_stats && today_stats.total_players_today >= 2 && (
              <div className="daily__percentile-row">
                <div className="daily__percentile-pill">
                  <span className="daily__percentile-label">better than</span>
                  <span className="daily__percentile-num">{today_stats.answer_percentile}%</span>
                </div>
                {today_stats.speed_percentile != null && (
                  <div className="daily__percentile-pill">
                    <span className="daily__percentile-label">faster than</span>
                    <span className="daily__percentile-num">{today_stats.speed_percentile}%</span>
                  </div>
                )}
                {today_stats.path_uniqueness != null && (
                  <div className="daily__percentile-pill">
                    <span className="daily__percentile-label">same path as</span>
                    <span className="daily__percentile-num">{today_stats.path_uniqueness}%</span>
                  </div>
                )}
              </div>
            )}
          </div>

          <button className="btn btn--daily btn--large" onClick={handleShare}>
            Share result
          </button>

          {mockHistoryData.total > 0 && (
            <DailyHistory data={mockHistoryData} />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="daily">
      <div className="daily__loading">Setting up today's puzzle…</div>
      <button className="daily__skip" onClick={handleSkip}>
        Skip today
      </button>
    </div>
  );
}
