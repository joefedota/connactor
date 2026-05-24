import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { checkConnected } from '../../api/client';
import { EntitySearch } from '../../components/EntitySearch';
import { NodeChip } from '../../components/NodeChip';
import { useGameStore } from '../../store/gameStore';
import type { NodeInfo } from '../../types';
import './GameBoard.css';

export function GameBoard() {
  const navigate = useNavigate();
  const { game, isLoading, addNode, removeLastFromPath, submit, giveUp, endError, stepError } =
    useGameStore();

  useEffect(() => {
    document.body.style.background = '#FAF7F2';
  }, []);

  useEffect(() => {
    if (!game && !isLoading) navigate('/');
  }, [game, isLoading, navigate]);

  const [targetReachable, setTargetReachable] = useState(false);

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

  const lastNode = currentPath[currentPath.length - 1];
  const canClickTarget = targetReachable;
  const canSubmit = lastNode.type === 'movie'; // must end on a movie to submit

  const handleSelect = async (node: NodeInfo) => {
    await addNode(node);
  };

  const handleTargetClick = async () => {
    if (!canClickTarget) return;
    const won = await addNode(target);
    if (won) navigate('/results');
  };

  const handleSubmit = async () => {
    const won = await submit();
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
        </div>
        <div className="game-board__header-actions">
          {canSubmit && (
            <button className="btn btn--primary btn--sm" onClick={handleSubmit}>
              Submit
            </button>
          )}
          <button className="btn btn--ghost btn--sm" onClick={handleGiveUp}>
            Give Up
          </button>
        </div>
      </header>

      <div className="game-board__actors">
        <div className="game-board__actor-card">
          <div className="game-board__actor-label">Start</div>
          <NodeChip node={source} />
        </div>
        <div className="game-board__actor-divider">→</div>
        <div className="game-board__actor-card">
          <div className="game-board__actor-label">Reach</div>
          <div
            className={canClickTarget ? 'game-board__target--clickable' : ''}
            onClick={handleTargetClick}
          >
            <NodeChip node={target} />
          </div>
        </div>
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
              <NodeChip node={target} />
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
    </div>
  );
}
