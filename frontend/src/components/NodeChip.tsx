import { useEffect, useRef, useState } from 'react';
import type { NodeInfo } from '../types';
import { tmdbImage } from '../utils/tmdbImage';
import './NodeChip.css';

interface Props {
  node: NodeInfo;
  removable?: boolean;
  onRemove?: () => void;
  faded?: boolean;
  noPhoto?: boolean;  // suppress hover/tap reveal — used for path chain chips
}

export function NodeChip({ node, removable, onRemove, faded, noPhoto }: Props) {
  const imageUrl = noPhoto ? null : tmdbImage(node.image_path);
  const peekable = !!imageUrl;

  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const chipRef = useRef<HTMLDivElement>(null);

  // Outside-click dismiss when the photo is pinned by a tap.
  useEffect(() => {
    if (!pinned) return;
    const handler = (e: PointerEvent) => {
      if (chipRef.current && !chipRef.current.contains(e.target as Node)) {
        setPinned(false);
      }
    };
    document.addEventListener('pointerdown', handler);
    return () => document.removeEventListener('pointerdown', handler);
  }, [pinned]);

  const showPhoto = peekable && (hovered || pinned);

  const handleClick = () => {
    if (peekable) setPinned((p) => !p);
  };

  return (
    <div
      ref={chipRef}
      className={`node-chip node-chip--${node.type}${faded ? ' node-chip--faded' : ''}${peekable ? ' node-chip--peekable' : ''}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={handleClick}
    >
      <span className="node-chip__label">
        {node.label}
        {node.year && <span className="node-chip__year"> ({node.year})</span>}
      </span>
      {removable && onRemove && (
        <button
          className="node-chip__remove"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          aria-label={`Remove ${node.label}`}
        >
          ×
        </button>
      )}
      {showPhoto && (
        <div className={`node-chip__photo node-chip__photo--${node.type}`}>
          <img src={imageUrl!} alt={node.label} draggable={false} />
        </div>
      )}
    </div>
  );
}
