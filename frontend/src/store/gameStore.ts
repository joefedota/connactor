import { create } from 'zustand';
import * as api from '../api/client';
import type { GameState, NodeInfo } from '../types';

interface GameStore {
  game: GameState | null;
  isLoading: boolean;
  endError: string | null;
  stepError: string | null;  // shown when actor isn't in the last movie

  fetchGame: (difficulty?: string) => Promise<void>;
  addNode: (node: NodeInfo) => Promise<void>;
  removeLastFromPath: () => void;
  submit: () => Promise<void>;
  giveUp: () => Promise<void>;
  resetGame: () => void;
}

export const useGameStore = create<GameStore>((set, get) => ({
  game: null,
  isLoading: false,
  endError: null,
  stepError: null,

  fetchGame: async (difficulty?: string) => {
    set({ isLoading: true, endError: null });
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
        },
        isLoading: false,
      });
    } catch (e: unknown) {
      set({ endError: String(e), isLoading: false });
    }
  },

  addNode: async (node: NodeInfo) => {
    const { game } = get();
    if (!game || game.status !== 'playing') return;

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
          return;
        }
      } catch {
        // Network error — let it through rather than blocking the player
      }
    }

    const newPath = [...game.currentPath, node];
    set({ game: { ...game, currentPath: newPath }, endError: null, stepError: null });

    // Only check completion when the target actor is reached
    if (node.type !== 'actor' || node.id !== game.target.id) return;

    try {
      const resp = await api.validatePath(
        game.source.id,
        game.target.id,
        newPath.map((n) => n.id),
      );

      if (!resp.valid) {
        // Path reached the target but chain has invalid connections — show error,
        // leave all nodes in place so the player can remove and retry
        set({ endError: 'Some connections in your path are invalid. Remove and try again.' });
        return;
      }

      const solveResp = await api.solve(game.source.id, game.target.id);
      const fresh = get().game!;
      set({
        game: {
          ...fresh,
          currentPath: newPath,
          status: 'won',
          isOptimal: resp.is_optimal ?? false,
          allPaths: solveResp.paths,
        },
      });
    } catch {
      // Network error — don't block the player
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

  submit: async () => {
    const { game } = get();
    if (!game) return;

    // If path ends on a movie, verify target actor was in it before appending
    let finalPath = game.currentPath;
    const lastNode = finalPath[finalPath.length - 1];
    if (lastNode.type === 'movie') {
      try {
        const { connected } = await api.checkConnected(lastNode.id, game.target.id);
        if (!connected) {
          const lastLabel = lastNode.year ? `${lastNode.label} (${lastNode.year})` : lastNode.label;
          set({ stepError: `${game.target.label} wasn't in ${lastLabel} — pick a different movie.` });
          return;
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
      set({
        game: {
          ...game,
          currentPath: finalPath,
          status: 'won',
          isOptimal: validateResp.valid ? (validateResp.is_optimal ?? false) : false,
          allPaths: solveResp.paths,
        },
      });
    } catch (e: unknown) {
      set({ endError: String(e) });
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
