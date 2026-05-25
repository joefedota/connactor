export interface NodeInfo {
  type: 'actor' | 'movie';
  id: string;     // TMDB person_id or movie_id as string
  label: string;  // actor name or movie title
  year?: string;  // movies only
  popularity?: number; // actors only
  image_path?: string | null; // TMDB profile_path / poster_path; prepend tmdbImage()
  fame_rank?: number;         // actors only — used for optimal path ranking
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
  // Daily challenge fields
  isDailyChallenge?: boolean;
  puzzleId?: string;         // set for daily games; used when submitting completion
  optimalHops?: number;      // known for daily games from GET /daily
  startedAt?: number;        // Date.now() when game started; used to compute time_ms
  completionTimeMs?: number; // elapsed ms at win; set when status transitions to 'won'
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

export interface CompletionInfo {
  hops: number;
  time_ms: number | null;
  completed_at: string;
}

export interface DailyResponse {
  puzzle_date: string;
  puzzle_id: string;
  source: NodeInfo;
  target: NodeInfo;
  optimal_hops: number;
  already_completed: boolean;
  completion: CompletionInfo | null;
  current_streak: number;
}

export interface CompleteRequest {
  puzzle_id?: string;
  source_id?: string;
  target_id?: string;
  optimal_hops?: number;
  hops: number;
  time_ms?: number;
}

export interface CompleteResponse {
  completion_id: string;
  puzzle_id: string;
  hops: number;
  time_ms: number | null;
  completed_at: string;
}
