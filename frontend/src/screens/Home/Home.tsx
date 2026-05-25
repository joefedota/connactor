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
        </p>
        <div className="modal__example">
          <div className="modal__example-title">Example</div>
          <div className="modal__example-subtitle">Connect Leonardo DiCaprio to Timothée Chalamet</div>
          <div className="modal__example-chain">
            <span className="chip chip--actor">Leonardo DiCaprio</span>
            <span className="arrow">→</span>
            <span className="chip chip--movie">The Departed</span>
            <span className="arrow">→</span>
            <span className="chip chip--actor">Matt Damon</span>
            <span className="arrow">→</span>
            <span className="chip chip--movie">Interstellar</span>
            <span className="arrow">→</span>
            <span className="chip chip--actor">Timothée Chalamet</span>
          </div>
          <p className="modal__example-note">
            1 actor — can you do it in fewer?
          </p>
        </div>
        <ul className="modal__rules">
          <li>Search for an actor or movie at each step</li>
          <li>Hover an actor (or tap, on mobile) to peek at their photo</li>
          <li>Tap <strong>Give Up</strong> to see the optimal solution</li>
          <li>Try to match or beat the best number of actors</li>
        </ul>
      </div>
    </div>
  );
}

const DIFFICULTIES = [
  { id: 'random', label: 'Random', desc: 'Any difficulty' },
  { id: 'easy',   label: 'Easy',   desc: 'Hollywood A-listers' },
  { id: 'medium', label: 'Medium', desc: 'Well-known actors' },
  { id: 'hard',   label: 'Hard',   desc: 'Character actors' },
];

const THEME = { bg: '#FAF7F2', accent: '#E4FF3C', onAccent: '#333333', text: '#444444' };

export function Home() {
  const navigate = useNavigate();
  const { fetchGame, endError } = useGameStore();
  const [showHowTo, setShowHowTo] = useState(false);
  const [view, setView] = useState<'menu' | 'difficulty'>('menu');
  const [loadingDiff, setLoadingDiff] = useState<string | null>(null);

  const handleStart = async (diffId: string) => {
    setLoadingDiff(diffId);
    await fetchGame(diffId === 'random' ? undefined : diffId, THEME);
    document.body.style.transition = 'none';
    document.body.style.background = '#FAF7F2';
    navigate('/game');
  };

  return (
    <div className="home">
      <div className="home__content">

        {view === 'menu' ? (
          <>
            <h1 className="home__title">Connactor</h1>
            <p className="home__subtitle">
              Connect two actors through shared movies in as few steps as possible.
            </p>

            {endError && <div className="home__error">{endError}</div>}

            <button
              className="btn btn--primary btn--large"
              onClick={() => setView('difficulty')}
            >
              New Game
            </button>

            <button
              className="btn btn--ghost"
              onClick={() => setShowHowTo(true)}
            >
              How to Play
            </button>

            <button
              className="home__daily-link"
              onClick={() => navigate('/daily')}
            >
              ↩ Daily Challenge
            </button>
          </>
        ) : (
          <>
            <button className="home__back" onClick={() => setView('menu')}>
              ← Back
            </button>

            <h2 className="home__picker-title">Choose Difficulty</h2>

            <div className="home__difficulty-list">
              {DIFFICULTIES.map((d) => (
                <button
                  key={d.id}
                  className={`home__diff-btn ${loadingDiff === d.id ? 'is-loading' : ''}`}
                  disabled={loadingDiff !== null}
                  onClick={() => handleStart(d.id)}
                >
                  <span className="home__diff-label">{loadingDiff === d.id ? 'Loading…' : d.label}</span>
                  <span className="home__diff-desc">{d.desc}</span>
                </button>
              ))}
            </div>
          </>
        )}

      </div>

      {showHowTo && <HowToPlayModal onClose={() => setShowHowTo(false)} />}
    </div>
  );
}
