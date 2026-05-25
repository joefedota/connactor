import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PathDisplay } from '../../components/PathDisplay';
import { useGameStore } from '../../store/gameStore';
import { formatTime } from '../../utils/formatTime';
import './Results.css';

// intermediate actors = total actors minus start and end
function actorCount(pathLength: number): number {
  return Math.ceil(pathLength / 2) - 2;
}

function buildChain(hops: number): string {
  return Array.from({ length: hops + 1 }, (_, i) => i % 2 === 0 ? '🟡' : '🟣').join('');
}

function buildDailyShareText(
  date: string,
  source: string,
  target: string,
  hops: number,
  optimalHops: number,
  timeMs: number | undefined,
): string {
  const actors = Math.ceil(hops / 2) - 1;
  const optimalActors = Math.ceil(optimalHops / 2) - 1;
  const chain = buildChain(hops);
  const timePart = timeMs != null ? ` in ${formatTime(timeMs)}` : '';
  const statusPart = actors <= optimalActors ? ' · ✓ best answer!' : ` · (best: ${optimalActors})`;
  return `Connactor Daily · ${date}\n\n${source} → ${target}\n\n${chain}\n${actors} actor${actors !== 1 ? 's' : ''}${timePart}${statusPart}\n\nconnactor.com/daily`;
}

function buildRandomShareText(
  source: string,
  target: string,
  playerActors: number,
  optimalActors: number,
  isOptimal: boolean | null,
) {
  const statusLine = isOptimal
    ? '✓ best answer!'
    : `Best: ${optimalActors} actor${optimalActors !== 1 ? 's' : ''}`;
  return `Connactor\n${source} → ${target}\n${playerActors} actor${playerActors !== 1 ? 's' : ''} — ${statusLine}`;
}

export function Results() {
  const navigate = useNavigate();
  const { game, theme, resetGame, fetchGame, dailyData, dismissDaily } = useGameStore();
  const [showAllPaths, setShowAllPaths] = useState(false);

  useEffect(() => {
    if (!game || game.status === 'playing') navigate('/');
  }, [game, navigate]);

  useEffect(() => {
    document.body.style.background = '#FAF7F2';
  }, []);

  if (!game || game.status === 'playing') return null;

  const { source, target, currentPath, status, isOptimal, allPaths } = game;

  const playerActors = Math.max(0, currentPath.filter((n) => n.type === 'actor').length - 2);
  const optimalActors = allPaths && allPaths.length > 0 ? actorCount(allPaths[0].length) : playerActors;
  const won = status === 'won';
  const reachedTarget = currentPath[currentPath.length - 1]?.id === target.id;

  const handlePlayAgain = () => {
    const nextDifficulty = game.requestedDifficulty;
    const savedTheme = theme;
    resetGame();
    fetchGame(nextDifficulty, savedTheme ?? undefined);
    navigate('/game');
  };

  const handleGoHome = () => {
    if (game.isDailyChallenge) dismissDaily();
    resetGame();
    navigate('/');
  };

  const handleShare = async () => {
    let text: string;
    if (game.isDailyChallenge) {
      const rawDate = dailyData?.puzzle_date ?? new Date().toISOString().slice(0, 10);
      const [y, m, d] = rawDate.split('-').map(Number);
      const date = new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
      const hops = currentPath.length - 1;
      const optimalHops = dailyData?.optimal_hops ?? (optimalActors + 1) * 2;
      text = buildDailyShareText(date, source.label, target.label, hops, optimalHops, game.completionTimeMs);
    } else {
      text = buildRandomShareText(source.label, target.label, playerActors, optimalActors, isOptimal);
    }
    try {
      await navigator.clipboard.writeText(text);
      alert('Copied to clipboard!');
    } catch {
      alert(text);
    }
  };

  return (
    <div className="results">
      <header className="results__header">
        <span className="results__logo" onClick={() => { resetGame(); navigate('/'); }} style={{ cursor: 'pointer' }}>Connactor</span>
      </header>

      <div className="results__outcome">
        {won && reachedTarget ? (
          <>
            <div className="results__outcome-title">Connacted!</div>
            <div className="results__outcome-sub">
              {playerActors} actor{playerActors !== 1 ? 's' : ''}
              {isOptimal ? ' — best answer!' : ''}
            </div>
            {game.completionTimeMs != null && (
              <div className="results__time">{formatTime(game.completionTimeMs)}</div>
            )}
          </>
        ) : (
          <div className="results__outcome-title results__outcome-title--gave-up">
            {status === 'gave_up' ? 'Better luck next time' : 'Incomplete path'}
          </div>
        )}
        <div className="results__actors">
          {source.label} → {target.label}
        </div>
      </div>

      {/* Optimal answer callout */}
      {allPaths && allPaths.length > 0 && (
        <div className="results__optimal-callout">
          <span className="results__optimal-label">Best answer</span>
          <span className="results__optimal-count">
            {optimalActors} actor{optimalActors !== 1 ? 's' : ''}
          </span>
          {won && reachedTarget && (
            <span className={`results__optimal-delta ${isOptimal ? 'results__optimal-delta--even' : 'results__optimal-delta--over'}`}>
              {isOptimal ? 'You matched it!' : `You used ${playerActors - optimalActors} extra`}
            </span>
          )}
        </div>
      )}

      {/* Player's path */}
      {currentPath.length > 1 && (
        <section className="results__section">
          <PathDisplay
            path={currentPath}
            label={`Your path — ${playerActors} actor${playerActors !== 1 ? 's' : ''}`}
          />
        </section>
      )}

      {/* Optimal paths */}
      {allPaths && allPaths.length > 0 && (
        <section className="results__section">
          <div className="results__section-title">
            Best answer — {optimalActors} actor{optimalActors !== 1 ? 's' : ''}
            {allPaths.length > 1 && (
              <span className="results__path-count"> · {allPaths.length} paths</span>
            )}
          </div>
          <div className="results__paths">
            <PathDisplay path={allPaths[0]} dim={!!(won && !isOptimal)} />
            {allPaths.length > 1 && (
              <>
                {showAllPaths && allPaths.slice(1).map((path, i) => (
                  <PathDisplay key={i + 1} path={path} dim={!!(won && !isOptimal)} />
                ))}
                <button
                  className="results__expand-btn"
                  onClick={() => setShowAllPaths(v => !v)}
                >
                  {showAllPaths
                    ? 'Show less'
                    : `+${allPaths.length - 1} more path${allPaths.length - 1 !== 1 ? 's' : ''}`}
                </button>
              </>
            )}
          </div>
        </section>
      )}

      <div className="results__actions">
        {game.isDailyChallenge ? (
          <>
            <button className="btn btn--primary" onClick={handleGoHome}>
              Back to home
            </button>
            <button className="btn btn--ghost" onClick={handleShare}>
              Share
            </button>
          </>
        ) : (
          <>
            <button className="btn btn--primary" onClick={handlePlayAgain}>
              Play again
            </button>
            <button className="btn btn--ghost" onClick={handleShare}>
              Share
            </button>
          </>
        )}
      </div>
    </div>
  );
}
