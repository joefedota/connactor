import type { NodeInfo } from '../types';
import { NodeChip } from './NodeChip';
import './PathDisplay.css';

interface Props {
  path: NodeInfo[];
  label?: string;
  dim?: boolean;
}

export function PathDisplay({ path, label, dim }: Props) {
  const lastIndex = path.length - 1;

  return (
    <div className={`path-display${dim ? ' path-display--dim' : ''}`}>
      {label && <div className="path-display__label">{label}</div>}
      <div className="path-display__stack">
        {path.map((node, i) => {
          const isEndpoint = i === 0 || i === lastIndex;

          if (node.type === 'movie') {
            return (
              <div key={`${node.id}-${i}`} className="path-display__movie-row">
                <span className="path-display__connector" aria-hidden="true">↓</span>
                <NodeChip node={node} />
              </div>
            );
          }

          return (
            <div
              key={`${node.id}-${i}`}
              className={isEndpoint ? 'path-display__actor-row' : 'path-display__actor-row path-display__actor-row--indented'}
            >
              <NodeChip node={node} noPhoto />
            </div>
          );
        })}
      </div>
    </div>
  );
}
