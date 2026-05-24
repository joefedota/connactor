import { useEffect, useRef, useState } from 'react';
import { autocomplete } from '../api/client';
import type { NodeInfo } from '../types';
import { tmdbImage } from '../utils/tmdbImage';
import './EntitySearch.css';

interface Props {
  mode: 'actor' | 'movie';
  onSelect: (node: NodeInfo) => void;
  disabled?: boolean;
}

export function EntitySearch({ mode, onSelect, disabled }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<NodeInfo[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const resp = await autocomplete(query, mode);
        setResults(resp.results);
        setOpen(resp.results.length > 0);
        setActiveIndex(-1);
      } catch {
        setResults([]);
        setOpen(false);
      }
    }, 300);
  }, [query, mode]);

  // Reset when mode changes (movie → actor transition)
  useEffect(() => {
    setQuery('');
    setResults([]);
    setOpen(false);
    setActiveIndex(-1);
  }, [mode]);

  const handleSelect = (node: NodeInfo) => {
    onSelect(node);
    setQuery('');
    setResults([]);
    setOpen(false);
    setActiveIndex(-1);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!open) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, -1));
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      handleSelect(results[activeIndex]);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  const placeholder = mode === 'actor' ? 'Type an actor name…' : 'Type a movie title…';

  return (
    <div className={`entity-search entity-search--${mode}`}>
      <div className="entity-search__mode-label">
        {mode === 'actor' ? 'Actor' : 'Movie'}
      </div>
      <div className="entity-search__input-wrap">
        <input
          className="entity-search__input"
          type="text"
          value={query}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          autoComplete="off"
          spellCheck={false}
          autoFocus
          aria-autocomplete="list"
          aria-expanded={open}
        />
        {open && results.length > 0 && (
          <ul className="entity-search__dropdown" role="listbox">
            {results.map((node, i) => {
              const imageUrl = tmdbImage(node.image_path, 'w92');
              const isActive = i === activeIndex;
              return (
                <li
                  key={node.id}
                  className={`entity-search__option${isActive ? ' entity-search__option--active' : ''}`}
                  role="option"
                  aria-selected={isActive}
                  onMouseDown={() => handleSelect(node)}
                  onMouseEnter={() => setActiveIndex(i)}
                >
                  <span className="entity-search__option-label">
                    {node.label}
                    {node.year && <span className="entity-search__year"> ({node.year})</span>}
                  </span>
                  {isActive && imageUrl && (
                    <span className={`entity-search__option-photo entity-search__option-photo--${node.type}`}>
                      <img src={imageUrl} alt="" draggable={false} />
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
