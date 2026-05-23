export interface NodeInfo {
  type: 'actor' | 'movie';
  id: string;     // TMDB person_id or movie_id as string
  label: string;  // actor name or movie title
  year?: string;  // movies only
  popularity?: number; // actors only
}

export type Difficulty = 'easy' | 'medium' | 'hard' | 'expert';

export interface GameState {
  gameId: string;
  source: NodeInfo;
  target: NodeInfo;
  currentPath: NodeInfo[];   // nodes selected so far, starts with source
  status: 'playing' | 'won' | 'gave_up';
  isOptimal: boolean | null; // set when game ends
  allPaths: NodeInfo[][] | null; // populated after /solve
  difficulty: string;        // classification returned by the API
  requestedDifficulty?: string; // what the player picked; undefined = random
}

export interface ValidateResponse {
  valid: boolean;
  error: string | null;
  is_complete: boolean;
  is_optimal: boolean | null;
}

export interface SolveResponse {
  hop_count: number;
  paths: NodeInfo[][];
}

export interface GameResponse {
  game_id: string;
  source: NodeInfo;
  target: NodeInfo;
  difficulty: string;
}

export interface AutocompleteResponse {
  results: NodeInfo[];
}
