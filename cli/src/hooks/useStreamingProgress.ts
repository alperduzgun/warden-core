/**
 * useStreamingProgress Hook
 *
 * Custom hook for managing streaming progress updates.
 * Handles timer, frame updates, and progress calculations.
 */

import { useEffect, useRef, useCallback } from 'react';
import { useProgress } from '../contexts/ProgressContext.js';
import type { FrameProgress } from '../components/FrameStatusDisplay.js';

export interface StreamingProgressOptions {
  /**
   * Timer interval in milliseconds
   * @default 1000
   */
  timerInterval?: number;

  /**
   * Auto-reset on completion
   * @default false
   */
  autoReset?: boolean;

  /**
   * Callback when progress completes
   */
  onComplete?: () => void;

  /**
   * Callback when progress fails
   */
  onError?: (error: string) => void;
}

/**
 * Hook for managing streaming progress with auto-updating timer
 *
 * @param options - Configuration options
 * @returns Progress state and control functions
 *
 * @example
 * ```tsx
 * const { progress, startProgress, updateFrameProgress, completeProgress } = useStreamingProgress({
 *   onComplete: () => console.log('Scan completed'),
 *   onError: (err) => console.error('Scan failed:', err)
 * });
 *
 * // Start scan
 * startProgress(100, [
 *   { id: '1', name: 'Security', status: 'pending' },
 *   { id: '2', name: 'Chaos', status: 'pending' }
 * ]);
 *
 * // Update frame
 * updateFrameProgress('1', { status: 'running' });
 * updateFrameProgress('1', { status: 'success', issuesFound: 5, duration: 1200 });
 * ```
 */
export const useStreamingProgress = (options: StreamingProgressOptions = {}) => {
  const { timerInterval = 1000, autoReset = false, onComplete, onError } = options;

  const {
    progress,
    updateProgress,
    startScan,
    updateFrame,
    completeScan,
    failScan,
    resetProgress,
  } = useProgress();

  const timerRef = useRef<NodeJS.Timeout | null>(null);

  /**
   * Start progress with timer
   */
  const startProgress = useCallback(
    (totalFiles: number, frames: FrameProgress[]) => {
      // Start scan
      startScan(totalFiles, frames);

      // Start timer
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }

      timerRef.current = setInterval(() => {
        updateProgress({ elapsedTime: Date.now() });
      }, timerInterval);
    },
    [startScan, updateProgress, timerInterval]
  );

  /**
   * Update frame progress
   */
  const updateFrameProgress = useCallback(
    (frameId: string, update: Partial<FrameProgress>) => {
      updateFrame(frameId, update);

      // Update issue count if frame completed with issues
      // Note: This would need proper implementation with state management
      // For now, issue counts are managed separately
    },
    [updateFrame, updateProgress]
  );

  /**
   * Update file progress
   */
  const updateFileProgress = useCallback(
    (filesScanned: number) => {
      updateProgress({ filesScanned });
    },
    [updateProgress]
  );

  /**
   * Complete progress
   */
  const completeProgress = useCallback(() => {
    // Stop timer
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    completeScan();

    // Callback
    if (onComplete) {
      onComplete();
    }

    // Auto-reset if enabled
    if (autoReset) {
      setTimeout(resetProgress, 2000);
    }
  }, [completeScan, onComplete, autoReset, resetProgress]);

  /**
   * Fail progress
   */
  const failProgress = useCallback(
    (error: string) => {
      // Stop timer
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }

      failScan(error);

      // Callback
      if (onError) {
        onError(error);
      }

      // Auto-reset if enabled
      if (autoReset) {
        setTimeout(resetProgress, 3000);
      }
    },
    [failScan, onError, autoReset, resetProgress]
  );

  /**
   * Cancel progress
   */
  const cancelProgress = useCallback(() => {
    failProgress('Cancelled by user');
  }, [failProgress]);

  /**
   * Cleanup timer on unmount
   */
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, []);

  return {
    progress,
    startProgress,
    updateFrameProgress,
    updateFileProgress,
    completeProgress,
    failProgress,
    cancelProgress,
    resetProgress,
  };
};

export default useStreamingProgress;
