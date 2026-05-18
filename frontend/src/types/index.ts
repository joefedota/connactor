export interface NodeInfo {
  type: 'actor' | 'movie';
  id: string;     // nconst or tconst
  label: string;  // actor name or movie title
  year?: string;  // movies only
}

export interface GameState {
  gameId: string;
  source: NodeInfo;
  target: NodeInfo;
  currentPath: NodeInfo[];   // nodes selected so far, starts with source
  status: 'playing' | 'won' | 'gave_up';
  isOptimal: boolean | null; // set when game ends
  allPaths: NodeInfo[][] | null; // populated after /solve
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
}

export interface AutocompleteResponse {
  results: NodeInfo[];
}
