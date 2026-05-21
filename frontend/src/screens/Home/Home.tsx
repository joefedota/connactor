import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useGameStore } from '../../store/gameStore';
import './Home.css';

function HowToPlayModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal__close" onClick={onClose}>×</button>
        <h2 className="modal__title">How to Play</h2>
        <p className="modal__text">
          Connect two actors through shared movies in as few steps as possible.
          Each step goes: <strong>actor → movie → actor</strong>.
        </p>
        <div className="modal__example">
          <div className="modal__example-title">Example</div>
          <div className="modal__example-chain">
            <span className="chip chip--actor">Matt Damon</span>
            <span className="arrow">→</span>
            <span className="chip chip--movie">Interstellar</span>
            <span className="arrow">→</span>
            <span className="chip chip--actor">Timothée Chalamet</span>
          </div>
          <p className="modal__example-note">
            That's 2 hops — one of the shortest possible connections!
          </p>
        </div>
        <ul className="modal__rules">
          <li>Search for an actor or movie at each step</li>
          <li>The search is constrained — only valid connections appear</li>
          <li>Tap <strong>Give Up</strong> to see the optimal solution</li>
          <li>Try to match or beat the optimal path count</li>
        </ul>
      </div>
    </div>
  );
}

const DIFFICULTIES = [
  { id: 'random', label: 'Random', desc: 'Fully random path length and actor pool.', color: '#888888' },
  { id: 'easy', label: 'Easy', desc: 'Connect two Super Famous stars in exactly 2 hops (1 movie).', color: '#10b981' },
  { id: 'medium', label: 'Medium', desc: 'Connect famous actors in 4 hops or fewer.', color: '#3b82f6' },
  { id: 'hard', label: 'Hard', desc: 'Connect moderately known actors in 6 hops or fewer.', color: '#f59e0b' },
  { id: 'expert', label: 'Expert', desc: 'Unrestricted paths and actor pool. Obscure names allowed!', color: '#ef4444' },
];

export function Home() {
  const navigate = useNavigate();
  const { fetchGame, isLoading, endError } = useGameStore();
  const [showHowTo, setShowHowTo] = useState(false);
  const [difficulty, setDifficulty] = useState<string>('random');

  const handleStart = async () => {
    await fetchGame(difficulty === 'random' ? undefined : difficulty);
    navigate('/game');
  };

  const activeDiff = DIFFICULTIES.find((d) => d.id === difficulty) || DIFFICULTIES[0];

  return (
    <div className="home">
      <div className="home__content">
        <h1 className="home__title">Connactor</h1>
        <p className="home__subtitle">
          Connect two actors through shared movies.
        </p>

        {endError && <div className="home__error">{endError}</div>}

        <div className="difficulty-container">
          <div className="difficulty-label">Select Difficulty</div>
          <div className="difficulty-tabs">
            {DIFFICULTIES.map((d) => (
              <button
                key={d.id}
                type="button"
                className={`difficulty-tab ${difficulty === d.id ? 'is-active' : ''}`}
                onClick={() => setDifficulty(d.id)}
              >
                {d.label}
              </button>
            ))}
          </div>
          <div className="difficulty-info-card">
            <div className="difficulty-info-card-inner">
              <span className="difficulty-badge" style={{ borderColor: activeDiff.color, color: activeDiff.color }}>
                {activeDiff.label.toUpperCase()}
              </span>
              <p className="difficulty-info-desc">
                {activeDiff.desc}
              </p>
            </div>
          </div>
        </div>

        <button
          className="btn btn--primary btn--large"
          onClick={handleStart}
          disabled={isLoading}
          style={{ width: '100%' }}
        >
          {isLoading ? 'Loading Game…' : 'Start Game'}
        </button>

        <button
          className="btn btn--ghost"
          onClick={() => setShowHowTo(true)}
        >
          How to Play
        </button>
      </div>

      {showHowTo && <HowToPlayModal onClose={() => setShowHowTo(false)} />}
    </div>
  );
}
