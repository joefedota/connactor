import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useGameStore } from '../../store/gameStore';
import './Daily.css';

function formatDate(dateStr: string): string {
  const [year, month, day] = dateStr.split('-').map(Number);
  return new Date(year, month - 1, day).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
}

function buildShareText(date: string, hops: number, optimalHops: number): string {
  const actors = Math.ceil(hops / 2) - 1;
  const optimalActors = Math.ceil(optimalHops / 2) - 1;
  const tag = actors <= optimalActors ? ' ✓' : '';
  return `Connactor Daily — ${date}\n${actors} actor${actors !== 1 ? 's' : ''}${tag}\nconnactor.com/daily`;
}

export function Daily() {
  const navigate = useNavigate();
  const { fetchDailyGame, isLoading, endError, dailyData } = useGameStore();
  const started = useRef(false);

  useEffect(() => {
    document.body.style.background = '#FAF7F2';
    if (started.current) return;
    started.current = true;
    fetchDailyGame().then((daily) => {
      if (daily && !daily.already_completed) {
        navigate('/game');
      }
    });
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
    const shareText = buildShareText(puzzle_date, completion.hops, optimal_hops);
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
          <div className="daily__label">Daily Challenge</div>
          <h1 className="daily__date">{formatDate(puzzle_date)}</h1>
          <div className="daily__pair">
            <span className="daily__actor">{source.label}</span>
            <span className="daily__arrow">→</span>
            <span className="daily__actor">{target.label}</span>
          </div>

          <div className="daily__already-done">
            <div className="daily__done-title">You've already played today</div>
            <div className="daily__result">
              <span className="daily__result-num">{actors}</span>
              <span className="daily__result-label">actor{actors !== 1 ? 's' : ''}</span>
              {actors <= optimalActors && <span className="daily__optimal-badge">Optimal!</span>}
            </div>
            <div className="daily__optimal-info">Best possible: {optimalActors} actor{optimalActors !== 1 ? 's' : ''}</div>
          </div>

          <button className="btn btn--daily btn--large" onClick={handleShare}>
            Share Result
          </button>
          <button className="btn btn--ghost btn--large" onClick={() => navigate('/')}>
            Play a Random Game
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="daily">
      <div className="daily__loading">Setting up today's puzzle…</div>
    </div>
  );
}
