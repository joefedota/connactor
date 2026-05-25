import './HowToPlayModal.css';

export function HowToPlayModal({ onClose }: { onClose: () => void }) {
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
          <li>Tap an actor to peek at their photo</li>
          <li>Tap <strong>Give Up</strong> to see the optimal solution</li>
          <li>Try to match or beat the best number of actors</li>
        </ul>
      </div>
    </div>
  );
}
