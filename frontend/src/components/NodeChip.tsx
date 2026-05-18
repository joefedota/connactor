import type { NodeInfo } from '../types';
import './NodeChip.css';

interface Props {
  node: NodeInfo;
  removable?: boolean;
  onRemove?: () => void;
  faded?: boolean;
}

export function NodeChip({ node, removable, onRemove, faded }: Props) {
  return (
    <div
      className={`node-chip node-chip--${node.type}${faded ? ' node-chip--faded' : ''}`}
    >
      <span className="node-chip__label">
        {node.label}
        {node.year && <span className="node-chip__year"> ({node.year})</span>}
      </span>
      {removable && onRemove && (
        <button
          className="node-chip__remove"
          onClick={onRemove}
          aria-label={`Remove ${node.label}`}
        >
          ×
        </button>
      )}
    </div>
  );
}
