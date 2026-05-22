import type {
  AutocompleteResponse,
  GameResponse,
  SolveResponse,
  ValidateResponse,
} from '../types';


const BASE = '/api';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export function fetchGame(difficulty?: string): Promise<GameResponse> {
  if (difficulty) {
    const params = new URLSearchParams({ difficulty });
    return request(`/game?${params}`);
  }
  return request('/game');
}

export function validatePath(
  source_id: string,
  target_id: string,
  path: string[],
): Promise<ValidateResponse> {
  return request('/validate', {
    method: 'POST',
    body: JSON.stringify({ source_id, target_id, path }),
  });
}

export function solve(
  source_id: string,
  target_id: string,
): Promise<SolveResponse> {
  return request('/solve', {
    method: 'POST',
    body: JSON.stringify({ source_id, target_id }),
  });
}

export function autocomplete(
  q: string,
  type: 'actor' | 'movie',
  limit = 10,
): Promise<AutocompleteResponse> {
  const params = new URLSearchParams({ q, type, limit: String(limit) });
  return request(`/autocomplete?${params}`);
}

export function checkConnected(a: string, b: string): Promise<{ connected: boolean }> {
  const params = new URLSearchParams({ a, b });
  return request(`/connected?${params}`);
}

export function autocompleteNeighbors(
  node_id: string,
  type: 'actor' | 'movie',
  q = '',
  limit = 20,
): Promise<AutocompleteResponse> {
  const params = new URLSearchParams({ node_id, type, limit: String(limit) });
  if (q.length >= 2) params.set('q', q);
  return request(`/autocomplete/neighbors?${params}`);
}
