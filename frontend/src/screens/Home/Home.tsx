import { useState, useEffect } from 'react';
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
  { id: 'random', label: 'Random', desc: 'Fully random path length and actor pool.',            bg: '#FAF7F2', accent: '#E4FF3C', onAccent: '#333333', text: '#444444' },
  { id: 'easy',   label: 'Easy',   desc: 'Connect two Super Famous stars in exactly 2 hops.',   bg: '#FAF7F2', accent: '#E4FF3C', onAccent: '#333333', text: '#444444' },
  { id: 'medium', label: 'Medium', desc: 'Connect famous actors in 4 hops or fewer.',            bg: '#FAF7F2', accent: '#E4FF3C', onAccent: '#333333', text: '#444444' },
  { id: 'hard',   label: 'Hard',   desc: 'Connect moderately known actors in 6 hops or fewer.',  bg: '#FAF7F2', accent: '#E4FF3C', onAccent: '#333333', text: '#444444' },
];

export function Home() {
  const navigate = useNavigate();
  const { fetchGame, isLoading, endError } = useGameStore();
  const [showHowTo, setShowHowTo] = useState(false);
  const [difficulty, setDifficulty] = useState<string>('random');

  const handleStart = async () => {
    await fetchGame(difficulty === 'random' ? undefined : difficulty, { bg: activeDiff.bg, accent: activeDiff.accent, onAccent: activeDiff.onAccent, text: activeDiff.text });
    document.body.style.transition = 'none';
    document.body.style.background = '#FAF7F2';
    navigate('/game');
  };

  const activeDiff = DIFFICULTIES.find((d) => d.id === difficulty) || DIFFICULTIES[0];

  useEffect(() => {
    document.body.style.background = activeDiff.bg;
    document.body.style.transition = 'background 0.4s ease';
  }, [activeDiff.bg]);

  const theme = {
    '--color-bg': activeDiff.bg,
    '--color-accent': activeDiff.accent,
    '--color-on-accent': activeDiff.onAccent,
    '--color-text': activeDiff.text,
  } as React.CSSProperties;

  return (
    <div className="home" style={theme}>
      <div className="home__content">
        <h1 className="home__title">Connactor</h1>
        <p className="home__subtitle">
          Connect two actors through shared movies in as few steps as possible.
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
        </div>

        <button
          className="btn btn--daily btn--large"
          onClick={() => navigate('/daily')}
        >
          Daily Challenge
        </button>

        <button
          className="btn btn--primary btn--large"
          onClick={handleStart}
          disabled={isLoading}
        >
          {isLoading ? 'Loading Game…' : 'Random Game'}
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
