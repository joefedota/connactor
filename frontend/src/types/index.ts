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
  // Hints
  hintsUsed?: number;             // count of hints consumed this game
  currentHint?: NodeInfo | null;  // currently revealed hint; cleared on any move
  shownHintIds?: string[];        // all hint IDs revealed (passed as excluded_ids to /hint)
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
  gave_up?: boolean;
}

export interface DailyStats {
  answer_percentile: number;
  speed_percentile: number | null;
  path_uniqueness: number | null;
  other_players_today: number;
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
  today_stats?: DailyStats | null;
}

export interface DailyHistoryEntry {
  puzzle_date: string;
  hops: number;
  time_ms: number | null;
  is_best: boolean;
}

export interface DailyHistoryResponse {
  entries: DailyHistoryEntry[];
  bucket_1: number;
  bucket_2: number;
  bucket_3: number;
  bucket_4: number;
  bucket_5: number;
  bucket_6_plus: number;
  total: number;
}

export interface CompleteRequest {
  puzzle_id?: string;
  source_id?: string;
  target_id?: string;
  optimal_hops?: number;
  hops: number;
  time_ms?: number;
  path_ids?: string[];
  gave_up?: boolean;
}

export interface CompleteResponse {
  completion_id: string;
  puzzle_id: string;
  hops: number;
  time_ms: number | null;
  completed_at: string;
}

export interface HintResponse {
  hint: NodeInfo;
}
