/**
 * useKillRing Hook
 * Provides Emacs-style kill/yank functionality (Ctrl+K, Ctrl+Y, Alt+Y)
 */

import {useState, useCallback} from 'react';

export interface UseKillRingReturn {
  killRing: string[];
  kill: (text: string) => void;
  yank: () => string | null;
  yankPop: () => string | null;
  append: (text: string) => void;
  clear: () => void;
}

/**
 * Hook for managing kill ring (Emacs-style copy/paste)
 *
 * Features:
 * - Ctrl+K: Kill text to end of line
 * - Ctrl+Y: Yank (paste) most recent kill
 * - Alt+Y: Cycle through kill ring
 * - Kill ring rotation
 *
 * @param maxSize - Maximum number of kills to remember (default: 20)
 * @returns Kill ring management functions
 */
export function useKillRing(maxSize = 20): UseKillRingReturn {
  const [killRing, setKillRing] = useState<string[]>([]);
  const [yankIndex, setYankIndex] = useState(0);

  /**
   * Add text to kill ring
   */
  const kill = useCallback((text: string) => {
    if (!text) return;

    setKillRing(prev => {
      const newRing = [text, ...prev];

      // Limit size
      if (newRing.length > maxSize) {
        return newRing.slice(0, maxSize);
      }

      return newRing;
    });

    // Reset yank index
    setYankIndex(0);
  }, [maxSize]);

  /**
   * Append text to most recent kill (for consecutive Ctrl+K)
   */
  const append = useCallback((text: string) => {
    if (!text) return;

    setKillRing(prev => {
      if (prev.length === 0) {
        return [text];
      }

      // Append to most recent kill
      const [latest, ...rest] = prev;
      return [latest + text, ...rest];
    });
  }, []);

  /**
   * Yank (paste) most recent kill
   */
  const yank = useCallback((): string | null => {
    if (killRing.length === 0) return null;

    setYankIndex(0);
    return killRing[0] || null;
  }, [killRing]);

  /**
   * Yank-pop: cycle to next kill in ring
   */
  const yankPop = useCallback((): string | null => {
    if (killRing.length === 0) return null;

    const newIndex = (yankIndex + 1) % killRing.length;
    setYankIndex(newIndex);

    return killRing[newIndex] || null;
  }, [killRing, yankIndex]);

  /**
   * Clear kill ring
   */
  const clear = useCallback(() => {
    setKillRing([]);
    setYankIndex(0);
  }, []);

  return {
    killRing,
    kill,
    yank,
    yankPop,
    append,
    clear,
  };
}
