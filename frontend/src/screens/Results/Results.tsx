import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { PathDisplay } from '../../components/PathDisplay';
import { useGameStore } from '../../store/gameStore';
import './Results.css';

// intermediate actors = total actors minus start and end
function actorCount(pathLength: number): number {
  return Math.ceil(pathLength / 2) - 2;
}

function buildShareText(
  source: string,
  target: string,
  playerActors: number,
  optimalActors: number,
  isOptimal: boolean | null,
) {
  const statusLine = isOptimal
    ? '✓ Optimal!'
    : `Best: ${optimalActors} actor${optimalActors !== 1 ? 's' : ''}`;
  return `Connactor\n${source} → ${target}\n${playerActors} actor${playerActors !== 1 ? 's' : ''} — ${statusLine}`;
}

export function Results() {
  const navigate = useNavigate();
  const { game, theme, resetGame, fetchGame } = useGameStore();

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

  const handleShare = async () => {
    const text = buildShareText(source.label, target.label, playerActors, optimalActors, isOptimal);
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
          <div className={`results__outcome-badge ${isOptimal ? 'results__outcome-badge--optimal' : 'results__outcome-badge--won'}`}>
            {isOptimal
              ? `★ Optimal — ${playerActors} actor${playerActors !== 1 ? 's' : ''}!`
              : `✓ Connected — ${playerActors} actor${playerActors !== 1 ? 's' : ''}`}
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
