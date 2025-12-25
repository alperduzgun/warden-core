/**
 * useInputHistory Hook
 * Provides command history navigation (↑↓, Ctrl+R search)
 */

import {useState, useCallback} from 'react';

export interface HistoryOptions {
  maxSize?: number;
  persistKey?: string;
}

export interface UseInputHistoryReturn {
  history: string[];
  currentIndex: number;
  addToHistory: (item: string) => void;
  navigateUp: () => string | null;
  navigateDown: () => string | null;
  search: (query: string) => string[];
  reset: () => void;
}

/**
 * Hook for managing command history with navigation
 *
 * Features:
 * - ↑↓ navigation through history
 * - Ctrl+R reverse search
 * - Duplicate filtering
 * - Max size limit
 *
 * @param options - Configuration options
 * @returns History management functions
 */
export function useInputHistory(options: HistoryOptions = {}): UseInputHistoryReturn {
  const {maxSize = 100} = options;

  const [history, setHistory] = useState<string[]>([]);
  const [currentIndex, setCurrentIndex] = useState(-1);

  /**
   * Add item to history (deduplicates and limits size)
   */
  const addToHistory = useCallback((item: string) => {
    if (!item.trim()) return;

    setHistory(prev => {
      // Remove duplicate if exists
      const filtered = prev.filter(h => h !== item);

      // Add to end
      const newHistory = [...filtered, item];

      // Limit size
      if (newHistory.length > maxSize) {
        return newHistory.slice(-maxSize);
      }

      return newHistory;
    });

    // Reset index after adding
    setCurrentIndex(-1);
  }, [maxSize]);

  /**
   * Navigate up in history (older)
   */
  const navigateUp = useCallback((): string | null => {
    if (history.length === 0) return null;

    setCurrentIndex(prev => {
      const newIndex = Math.min(prev + 1, history.length - 1);
      return newIndex;
    });

    const newIndex = Math.min(currentIndex + 1, history.length - 1);
    return history[history.length - 1 - newIndex] || null;
  }, [history, currentIndex]);

  /**
   * Navigate down in history (newer)
   */
  const navigateDown = useCallback((): string | null => {
    if (currentIndex <= 0) {
      setCurrentIndex(-1);
      return null;
    }

    setCurrentIndex(prev => prev - 1);

    const newIndex = currentIndex - 1;
    if (newIndex < 0) return null;

    return history[history.length - 1 - newIndex] || null;
  }, [history, currentIndex]);

  /**
   * Search history (Ctrl+R style)
   */
  const search = useCallback((query: string): string[] => {
    if (!query.trim()) return history.slice().reverse();

    const lowerQuery = query.toLowerCase();
    return history
      .filter(item => item.toLowerCase().includes(lowerQuery))
      .reverse(); // Most recent first
  }, [history]);

  /**
   * Reset navigation index
   */
  const reset = useCallback(() => {
    setCurrentIndex(-1);
  }, []);

  return {
    history,
    currentIndex,
    addToHistory,
    navigateUp,
    navigateDown,
    search,
    reset,
  };
}
