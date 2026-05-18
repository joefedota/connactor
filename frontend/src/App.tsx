import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Home } from './screens/Home/Home';
import { GameBoard } from './screens/GameBoard/GameBoard';
import { Results } from './screens/Results/Results';
import './App.css';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/game" element={<GameBoard />} />
        <Route path="/results" element={<Results />} />
      </Routes>
    </BrowserRouter>
  );
}
