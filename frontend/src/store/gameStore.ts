import { create } from 'zustand';
import * as api from '../api/client';
import type { DailyResponse, GameState, NodeInfo } from '../types';

export interface Theme {
  bg: string;
  accent: string;
  onAccent: string;
  text: string;
}

interface GameStore {
  game: GameState | null;
  theme: Theme | null;
  isLoading: boolean;
  endError: string | null;
  stepError: string | null;  // shown when actor isn't in the last movie
  dailyData: DailyResponse | null; // cached GET /daily response
  dailyDismissed: boolean; // user skipped daily this session

  fetchGame: (difficulty?: string, theme?: Theme) => Promise<void>;
  fetchDailyGame: () => Promise<DailyResponse | null>;
  prefetchDaily: () => void;
  dismissDaily: () => void;
  submitCompletion: (hops: number, timeMs?: number, optimalHops?: number) => Promise<void>;
  addNode: (node: NodeInfo) => Promise<boolean>;
  removeLastFromPath: () => void;
  flipActors: () => void;
  submit: () => Promise<boolean>;
  giveUp: () => Promise<void>;
  resetGame: () => void;
}

export const useGameStore = create<GameStore>((set, get) => ({
  game: null,
  theme: null,
  isLoading: false,
  endError: null,
  stepError: null,
  dailyData: null,
  dailyDismissed: false,

  dismissDaily: () => set({ dailyDismissed: true }),

  prefetchDaily: () => {
    // Fire-and-forget: warms the Neon connection and caches dailyData so that
    // navigating to /daily feels instant. Never touches isLoading.
    api.fetchDaily().then((daily) => set({ dailyData: daily })).catch(() => null);
  },

  fetchDailyGame: async () => {
    const cached = get().dailyData;
    if (cached) {
      if (!cached.already_completed) {
        set({
          game: {
            gameId: cached.puzzle_id,
            source: cached.source,
            target: cached.target,
            currentPath: [cached.source],
            status: 'playing',
            isOptimal: null,
            allPaths: null,
            difficulty: 'medium',
            isDailyChallenge: true,
            puzzleId: cached.puzzle_id,
            optimalHops: cached.optimal_hops,
            startedAt: Date.now(),
          },
        });
      }
      return cached;
    }
    set({ isLoading: true, endError: null, stepError: null });
    try {
      const daily = await api.fetchDaily();
      set({ dailyData: daily });
      if (!daily.already_completed) {
        set({
          game: {
            gameId: daily.puzzle_id,
            source: daily.source,
            target: daily.target,
            currentPath: [daily.source],
            status: 'playing',
            isOptimal: null,
            allPaths: null,
            difficulty: 'medium',
            isDailyChallenge: true,
            puzzleId: daily.puzzle_id,
            optimalHops: daily.optimal_hops,
            startedAt: Date.now(),
          },
          isLoading: false,
        });
      } else {
        set({ isLoading: false });
      }
      return daily;
    } catch (e: unknown) {
      set({ endError: String(e), isLoading: false });
      return null;
    }
  },

  submitCompletion: async (hops: number, timeMs?: number, optimalHops?: number) => {
    const { game } = get();
    if (!game) return;
    try {
      if (game.isDailyChallenge && game.puzzleId) {
        await api.submitComplete({ puzzle_id: game.puzzleId, hops, time_ms: timeMs });
        const d = get().dailyData;
        if (d) set({ dailyData: { ...d, already_completed: true } });
      } else {
        // optimalHops is passed from the solve response at call sites; game.optimalHops
        // is only set for daily games, so we must use the passed-in value for random games.
        const resolvedOptimalHops = optimalHops ?? game.optimalHops;
        if (!resolvedOptimalHops) return;
        await api.submitComplete({
          source_id: game.source.id,
          target_id: game.target.id,
          optimal_hops: resolvedOptimalHops,
          hops,
          time_ms: timeMs,
        });
      }
    } catch {
      // completion recording is best-effort; don't block the UI
    }
  },

  fetchGame: async (difficulty?: string, theme?: Theme) => {
    set({ isLoading: true, endError: null, stepError: null, theme: theme ?? null });
    try {
      const resp = await api.fetchGame(difficulty);
      set({
        game: {
          gameId: resp.game_id,
          source: resp.source,
          target: resp.target,
          currentPath: [resp.source],
          status: 'playing',
          isOptimal: null,
          allPaths: null,
          difficulty: resp.difficulty,
          requestedDifficulty: difficulty,
          startedAt: Date.now(),
        },
        isLoading: false,
      });
    } catch (e: unknown) {
      set({ endError: String(e), isLoading: false });
    }
  },

  addNode: async (node: NodeInfo) => {
    const { game } = get();
    if (!game || game.status !== 'playing') return false;

    // Validate the connection between the last path node and the new node
    const lastNode = game.currentPath[game.currentPath.length - 1];
    if (game.currentPath.length >= 1) {
      try {
        const { connected } = await api.checkConnected(lastNode.id, node.id);
        if (!connected) {
          const lastLabel = lastNode.year ? `${lastNode.label} (${lastNode.year})` : lastNode.label;
          const newLabel = node.year ? `${node.label} (${node.year})` : node.label;
          const msg = node.type === 'actor'
            ? `${newLabel} wasn't in ${lastLabel} — pick someone who was.`
            : `${lastNode.label} wasn't in ${newLabel} — pick a different movie.`;
          set({ stepError: msg });
          return false;
        }
      } catch {
        // Network error — let it through rather than blocking the player
      }
    }

    const newPath = [...game.currentPath, node];
    set({ game: { ...game, currentPath: newPath }, endError: null, stepError: null });

    // Only check completion when the target actor is reached
    if (node.type !== 'actor' || node.id !== game.target.id) return false;

    try {
      const resp = await api.validatePath(
        game.source.id,
        game.target.id,
        newPath.map((n) => n.id),
      );

      if (!resp.valid) {
        set({ endError: 'Some connections in your path are invalid. Remove and try again.' });
        return false;
      }

      const solveResp = await api.solve(game.source.id, game.target.id);
      const fresh = get().game!;
      const playerHops = newPath.length - 1;
      const timeMs = fresh.startedAt ? Date.now() - fresh.startedAt : undefined;
      set({
        game: {
          ...fresh,
          currentPath: newPath,
          status: 'won',
          isOptimal: resp.is_optimal ?? false,
          allPaths: solveResp.paths,
        },
      });
      get().submitCompletion(playerHops, timeMs, solveResp.hop_count);
      return true;
    } catch {
      return false;
    }
  },

  removeLastFromPath: () => {
    const { game } = get();
    if (!game || game.status !== 'playing') return;
    if (game.currentPath.length <= 1) return;
    set({
      game: { ...game, currentPath: game.currentPath.slice(0, -1) },
      endError: null,
      stepError: null,
    });
  },

  flipActors: () => {
    const { game } = get();
    if (!game || game.status !== 'playing') return;
    if (game.currentPath.length > 1) return; // can't flip once moves have been made
    set({
      game: {
        ...game,
        source: game.target,
        target: game.source,
        currentPath: [game.target],
      },
      endError: null,
      stepError: null,
    });
  },

  submit: async () => {
    const { game } = get();
    if (!game) return false;

    // If path ends on a movie, verify target actor was in it before appending
    let finalPath = game.currentPath;
    const lastNode = finalPath[finalPath.length - 1];
    if (lastNode.type === 'movie') {
      try {
        const { connected } = await api.checkConnected(lastNode.id, game.target.id);
        if (!connected) {
          const lastLabel = lastNode.year ? `${lastNode.label} (${lastNode.year})` : lastNode.label;
          set({ stepError: `${game.target.label} wasn't in ${lastLabel} — pick a different movie.` });
          return false;
        }
      } catch {
        // Network error — proceed anyway
      }
      finalPath = [...finalPath, game.target];
    }

    const pathIds = finalPath.map((n) => n.id);
    try {
      const [validateResp, solveResp] = await Promise.all([
        api.validatePath(game.source.id, game.target.id, pathIds),
        api.solve(game.source.id, game.target.id),
      ]);
      const playerHops = finalPath.length - 1;
      const timeMs = game.startedAt ? Date.now() - game.startedAt : undefined;
      set({
        game: {
          ...game,
          currentPath: finalPath,
          status: 'won',
          isOptimal: validateResp.valid ? (validateResp.is_optimal ?? false) : false,
          allPaths: solveResp.paths,
        },
      });
      get().submitCompletion(playerHops, timeMs, solveResp.hop_count);
      return true;
    } catch (e: unknown) {
      set({ endError: String(e) });
      return false;
    }
  },

  giveUp: async () => {
    const { game } = get();
    if (!game) return;
    try {
      const solveResp = await api.solve(game.source.id, game.target.id);
      set({
        game: {
          ...game,
          status: 'gave_up',
          isOptimal: false,
          allPaths: solveResp.paths,
        },
      });
    } catch (e: unknown) {
      set({ endError: String(e) });
    }
  },

  resetGame: () => set({ game: null, endError: null, stepError: null }),
}));
