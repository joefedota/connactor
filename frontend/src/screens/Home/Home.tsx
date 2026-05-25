import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { HowToPlayModal } from '../../components/HowToPlayModal';
import { useGameStore } from '../../store/gameStore';
import './Home.css';

const DIFFICULTIES = [
  { id: 'easy',   label: 'Easy' },
  { id: 'medium', label: 'Medium' },
  { id: 'hard',   label: 'Hard' },
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
    await fetchGame(diffId, THEME);
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
              New game
            </button>

            <button
              className="btn btn--ghost"
              onClick={() => setShowHowTo(true)}
            >
              How to play
            </button>

            <button
              className="home__daily-link"
              onClick={() => navigate('/daily')}
            >
              ← Daily challenge
            </button>
          </>
        ) : (
          <>
            <button className="home__back" onClick={() => setView('menu')}>
              ← Back
            </button>

            <h2 className="home__picker-title">Choose difficulty</h2>

            <div className="home__difficulty-list">
              {DIFFICULTIES.map((d) => (
                <button
                  key={d.id}
                  className={`home__diff-btn ${loadingDiff === d.id ? 'is-loading' : ''}`}
                  disabled={loadingDiff !== null}
                  onClick={() => handleStart(d.id)}
                >
                  <span className="home__diff-label">{loadingDiff === d.id ? 'Loading…' : d.label}</span>
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
