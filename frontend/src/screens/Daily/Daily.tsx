import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useGameStore } from '../../store/gameStore';
import { formatTime } from '../../utils/formatTime';
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
      }
    });
    // started.current guards against double-invocation (React Strict Mode);
    // exhaustive-deps is intentionally suppressed — this must run once only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (isLoading) {
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

  if (dailyData?.already_completed && dailyData.completion) {
    const { puzzle_date, completion, optimal_hops, source, target } = dailyData;
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
            <div className="daily__done-title">You've already played today</div>
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
            </div>
            {actors <= optimalActors && <span className="daily__optimal-badge">Best answer!</span>}
            <div className="daily__optimal-info">Best possible: {optimalActors} actor{optimalActors !== 1 ? 's' : ''}</div>
          </div>

          <button className="btn btn--daily btn--large" onClick={handleShare}>
            Share result
          </button>
          <button className="btn btn--ghost btn--large" onClick={() => navigate('/')}>
            Play a random game
          </button>
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
