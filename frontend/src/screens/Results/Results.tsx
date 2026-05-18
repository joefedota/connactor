import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { PathDisplay } from '../../components/PathDisplay';
import { useGameStore } from '../../store/gameStore';
import './Results.css';

// hop_count from API = edge count; movies = edges / 2
function movieCount(hopCount: number): number {
  return Math.floor(hopCount / 2);
}

function buildShareText(
  source: string,
  target: string,
  playerMovies: number,
  optimalMovies: number,
  isOptimal: boolean | null,
) {
  const statusLine = isOptimal
    ? '✓ Optimal!'
    : `Best: ${optimalMovies} movie${optimalMovies !== 1 ? 's' : ''}`;
  return `Connactor\n${source} → ${target}\n${playerMovies} movie${playerMovies !== 1 ? 's' : ''} — ${statusLine}`;
}

export function Results() {
  const navigate = useNavigate();
  const { game, resetGame, fetchGame } = useGameStore();

  useEffect(() => {
    if (!game || game.status === 'playing') navigate('/');
  }, [game, navigate]);

  if (!game || game.status === 'playing') return null;

  const { source, target, currentPath, status, isOptimal, allPaths } = game;

  // Count movies in player's path (every other node starting at index 1)
  const playerMovies = currentPath.filter((n) => n.type === 'movie').length;
  const optimalMovies = allPaths ? movieCount(allPaths[0].length - 1) : playerMovies;
  const won = status === 'won';
  const reachedTarget = currentPath[currentPath.length - 1]?.id === target.id;

  const handlePlayAgain = async () => {
    resetGame();
    await fetchGame();
    navigate('/game');
  };

  const handleShare = async () => {
    const text = buildShareText(source.label, target.label, playerMovies, optimalMovies, isOptimal);
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
        <span className="results__logo">Connactor</span>
      </header>

      <div className="results__outcome">
        {won && reachedTarget ? (
          <div className={`results__outcome-badge ${isOptimal ? 'results__outcome-badge--optimal' : 'results__outcome-badge--won'}`}>
            {isOptimal
              ? `★ Optimal — ${playerMovies} movie${playerMovies !== 1 ? 's' : ''}!`
              : `✓ Connected — ${playerMovies} movie${playerMovies !== 1 ? 's' : ''}`}
          </div>
        ) : (
          <div className="results__outcome-badge results__outcome-badge--gave-up">
            {status === 'gave_up' ? 'Better luck next time' : 'Incomplete path'}
          </div>
        )}
        <div className="results__actors">
          {source.label} → {target.label}
        </div>
      </div>

      {/* Optimal answer callout */}
      {allPaths && (
        <div className="results__optimal-callout">
          <span className="results__optimal-label">Best answer</span>
          <span className="results__optimal-count">
            {optimalMovies} movie{optimalMovies !== 1 ? 's' : ''}
          </span>
          {won && reachedTarget && (
            <span className={`results__optimal-delta ${isOptimal ? 'results__optimal-delta--even' : 'results__optimal-delta--over'}`}>
              {isOptimal ? 'You matched it!' : `You used ${playerMovies - optimalMovies} extra`}
            </span>
          )}
        </div>
      )}

      {/* Player's path */}
      {currentPath.length > 1 && (
        <section className="results__section">
          <PathDisplay
            path={currentPath}
            label={`Your path — ${playerMovies} movie${playerMovies !== 1 ? 's' : ''}`}
          />
        </section>
      )}

      {/* Optimal paths */}
      {allPaths && allPaths.length > 0 && (
        <section className="results__section">
          <div className="results__section-title">
            Optimal path{allPaths.length > 1 ? 's' : ''} — {optimalMovies} movie{optimalMovies !== 1 ? 's' : ''}
          </div>
          <div className="results__paths">
            {allPaths.map((path, i) => (
              <PathDisplay key={i} path={path} dim={!!(won && !isOptimal)} />
            ))}
          </div>
        </section>
      )}

      <div className="results__actions">
        <button className="btn btn--primary" onClick={handlePlayAgain}>
          Play Again
        </button>
        <button className="btn btn--ghost" onClick={handleShare}>
          Share
        </button>
      </div>
    </div>
  );
}
