import { useEffect, useRef, useState } from 'react';
import { formatTime } from '../../utils/formatTime';
import { useNavigate } from 'react-router-dom';
import { checkConnected } from '../../api/client';
import { EntitySearch } from '../../components/EntitySearch';
import { HowToPlayModal } from '../../components/HowToPlayModal';
import { NodeChip } from '../../components/NodeChip';
import { useGameStore } from '../../store/gameStore';
import type { NodeInfo } from '../../types';
import './GameBoard.css';

export function GameBoard() {
  const navigate = useNavigate();
  const { game, isLoading, addNode, removeLastFromPath, flipActors, giveUp, endError, stepError, requestHint } =
    useGameStore();

  useEffect(() => {
    document.body.style.background = '#FAF7F2';
  }, []);

  useEffect(() => {
    if (!game && !isLoading) navigate('/');
  }, [game, isLoading, navigate]);

  const [targetReachable, setTargetReachable] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [showHowTo, setShowHowTo] = useState(false);
  const howToChecked = useRef(false);

  useEffect(() => {
    if (howToChecked.current) return;
    howToChecked.current = true;
    if (!localStorage.getItem('connactor_howto_seen')) setShowHowTo(true);
  }, []);

  const handleCloseHowTo = () => {
    localStorage.setItem('connactor_howto_seen', '1');
    setShowHowTo(false);
  };

  useEffect(() => {
    if (!game || game.status !== 'playing' || !game.startedAt) return;
    const id = setInterval(() => setElapsed(Date.now() - game.startedAt!), 1000);
    return () => clearInterval(id);
  }, [game?.status, game?.startedAt]);

  useEffect(() => {
    if (!game) return;
    const { currentPath, target } = game;
    const nextType = currentPath.length % 2 === 0 ? 'actor' : 'movie';
    if (nextType !== 'actor' || currentPath.length < 2) {
      setTargetReachable(false);
      return;
    }
    const lastNode = currentPath[currentPath.length - 1];
    checkConnected(lastNode.id, target.id)
      .then(({ connected }) => setTargetReachable(connected))
      .catch(() => setTargetReachable(false));
  }, [game?.currentPath, game?.target]);

  if (!game) return isLoading ? <div className="game-board" /> : null;

  const { source, target, currentPath } = game;

  // pos 0 = source actor, pos 1 = movie, pos 2 = actor, ...
  const nextType: 'actor' | 'movie' =
    currentPath.length % 2 === 0 ? 'actor' : 'movie';

  const canClickTarget = targetReachable;
  const MAX_HINTS = 3;
  const hintsLeft = MAX_HINTS - (game?.hintsUsed ?? 0);

  const handleSelect = async (node: NodeInfo) => {
    const won = await addNode(node);
    if (won) navigate('/results');
  };

  const handleTargetClick = async () => {
    if (!canClickTarget) return;
    const won = await addNode(target);
    if (won) navigate('/results');
  };

  const handleGiveUp = async () => {
    await giveUp();
    navigate('/results');
  };

  const intermediateNodes = currentPath.slice(1);

  return (
    <div className="game-board">
      <header className="game-board__header">
        <div className="game-board__header-left">
          <span className="game-board__logo" onClick={() => navigate('/')} style={{ cursor: 'pointer' }}>Connactor</span>
          {game.isDailyChallenge ? (
            <span className="game-board__difficulty game-board__difficulty--daily">
              Daily
            </span>
          ) : game.difficulty && (
            <span className={`game-board__difficulty game-board__difficulty--${game.difficulty}`}>
              {game.difficulty}
            </span>
          )}
        </div>
        <div className="game-board__header-actions">
          {game.status === 'playing' && game.startedAt && (
            <span className="game-board__timer">{formatTime(elapsed)}</span>
          )}
          <button className="game-board__help-btn" onClick={() => setShowHowTo(true)} aria-label="How to play">
            ?
          </button>
        </div>
      </header>

      <div className="game-board__actors">
        <div className="game-board__actor-card">
          <div className="game-board__actor-label">Start</div>
          <NodeChip node={source} />
        </div>
        <div className="game-board__actor-divider">
          {currentPath.length === 1 ? (
            <button className="game-board__flip-btn" onClick={flipActors} title="Flip actors">⇄</button>
          ) : (
            <span>→</span>
          )}
        </div>
        <div className="game-board__actor-card">
          <div className="game-board__actor-label">Reach</div>
          <div
            className={canClickTarget ? 'game-board__target--clickable' : ''}
            onClick={handleTargetClick}
          >
            <NodeChip node={target} noPhoto={canClickTarget} />
          </div>
        </div>
      </div>

      <div className="game-board__photo-tip">
        Tap an actor to see their headshot
      </div>

      {intermediateNodes.length > 0 && (
        <div className="game-board__chain">
          <div className="game-board__chain-scroll">
            {intermediateNodes.map((node, i) => (
              <div key={`${node.id}-${i}`} className={`game-board__chain-entry game-board__chain-entry--${node.type}`}>
                <span className="game-board__chain-arrow">→</span>
                <NodeChip
                  node={node}
                  removable={i === intermediateNodes.length - 1}
                  onRemove={removeLastFromPath}
                  noPhoto
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {endError && (
        <div className="game-board__error">{endError}</div>
      )}

      <div className="game-board__search">
        <EntitySearch mode={nextType} onSelect={handleSelect} />
        {canClickTarget && (
          <div className="game-board__finish-row">
            <span className="game-board__finish-label">or finish:</span>
            <div onClick={handleTargetClick} style={{ cursor: 'pointer' }}>
              <NodeChip node={target} noPhoto />
            </div>
          </div>
        )}
      </div>

      {stepError && (
        <div className="game-board__step-error">{stepError}</div>
      )}

      <div className="game-board__hint">
        {(() => {
          const last = currentPath[currentPath.length - 1];
          const lastLabel = last.year ? `${last.label} (${last.year})` : last.label;
          return nextType === 'movie'
            ? `Type a movie that ${lastLabel} appeared in`
            : `Type an actor who appeared in ${lastLabel}`;
        })()}
      </div>

      {game.status === 'playing' && (
        <div className="game-board__hint-section">
          {game.currentHint ? (
            <div className="game-board__hint-reveal">
              <span className="game-board__hint-icon">Hint</span>
              <div onClick={() => handleSelect(game.currentHint!)} style={{ cursor: 'pointer' }}>
                <NodeChip node={game.currentHint} noPhoto />
              </div>
              {hintsLeft > 0 && (
                <button className="game-board__hint-reroll" onClick={() => requestHint()}>
                  Try another
                </button>
              )}
            </div>
          ) : hintsLeft > 0 ? (
            <button className="game-board__hint-btn" onClick={() => requestHint()}>
              Get hint ({hintsLeft} left)
            </button>
          ) : (
            <span className="game-board__hints-used">
              {game.hintsUsed} hint{game.hintsUsed !== 1 ? 's' : ''} used
            </span>
          )}
        </div>
      )}

      <div className="game-board__give-up">
        <button className="btn btn--ghost btn--sm" onClick={handleGiveUp}>
          Give up
        </button>
      </div>

      {showHowTo && <HowToPlayModal onClose={handleCloseHowTo} />}
    </div>
  );
}
