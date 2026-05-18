import type { NodeInfo } from '../types';
import { NodeChip } from './NodeChip';
import './PathDisplay.css';

interface Props {
  path: NodeInfo[];
  label?: string;
  dim?: boolean;
}

export function PathDisplay({ path, label, dim }: Props) {
  return (
    <div className={`path-display${dim ? ' path-display--dim' : ''}`}>
      {label && <div className="path-display__label">{label}</div>}
      <div className="path-display__chain">
        {path.map((node, i) => (
          <span key={`${node.id}-${i}`} className="path-display__entry">
            <NodeChip node={node} />
            {i < path.length - 1 && (
              <span className="path-display__arrow" aria-hidden="true">→</span>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}
