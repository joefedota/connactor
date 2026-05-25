import { useEffect, useRef, useState } from 'react';
import { BrowserRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { Home } from './screens/Home/Home';
import { GameBoard } from './screens/GameBoard/GameBoard';
import { Results } from './screens/Results/Results';
import { Daily } from './screens/Daily/Daily';
import { useGameStore } from './store/gameStore';
import './App.css';

function RootRedirect() {
  const navigate = useNavigate();
  const { dailyData, dailyDismissed, fetchDailyGame } = useGameStore();
  const [checking, setChecking] = useState(!dailyDismissed && dailyData === null);
  const ran = useRef(false);

  useEffect(() => {
    if (dailyDismissed || ran.current) return;
    ran.current = true;

    if (dailyData !== null) {
      if (!dailyData.already_completed) navigate('/daily', { replace: true });
      setChecking(false);
      return;
    }

    fetchDailyGame().then((daily) => {
      if (daily && !daily.already_completed) navigate('/daily', { replace: true });
      setChecking(false);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (checking) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100dvh', background: '#FAF7F2' }} />
    );
  }

  return <Home />;
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<RootRedirect />} />
        <Route path="/game" element={<GameBoard />} />
        <Route path="/results" element={<Results />} />
        <Route path="/daily" element={<Daily />} />
      </Routes>
    </BrowserRouter>
  );
}
