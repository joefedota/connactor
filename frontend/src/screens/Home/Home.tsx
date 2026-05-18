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

export function Home() {
  const navigate = useNavigate();
  const { fetchGame, isLoading, error } = useGameStore();
  const [showHowTo, setShowHowTo] = useState(false);

  const handleStart = async () => {
    await fetchGame();
    navigate('/game');
  };

  return (
    <div className="home">
      <div className="home__content">
        <h1 className="home__title">Connactor</h1>
        <p className="home__subtitle">
          Connect two actors through shared movies.
        </p>

        {error && <div className="home__error">{error}</div>}

        <button
          className="btn btn--primary btn--large"
          onClick={handleStart}
          disabled={isLoading}
        >
          {isLoading ? 'Loading…' : 'Start Game'}
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
