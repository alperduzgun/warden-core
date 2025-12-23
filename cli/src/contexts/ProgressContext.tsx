/**
 * ProgressContext
 *
 * Global state management for scan/validation progress.
 * Inspired by Qwen Code's StreamingContext pattern.
 */

import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import type { FrameProgress } from '../components/FrameStatusDisplay.js';

/**
 * Progress state interface
 */
export interface ProgressState {
  /**
   * Whether a scan is currently active
   */
  isActive: boolean;

  /**
   * Current scan status
   */
  status: 'idle' | 'scanning' | 'analyzing' | 'complete' | 'error' | 'cancelled';

  /**
   * Currently executing frame name
   */
  currentFrame?: string;

  /**
   * Number of files scanned so far
   */
  filesScanned: number;

  /**
   * Total number of files to scan
   */
  totalFiles: number;

  /**
   * Total issues found across all frames
   */
  issuesFound: number;

  /**
   * Elapsed time in seconds
   */
  elapsedTime: number;

  /**
   * Validation frame progress list
   */
  frames: FrameProgress[];

  /**
   * Error message if status is 'error'
   */
  error?: string;

  /**
   * Start timestamp
   */
  startTime?: Date;

  /**
   * Cancellation flag - checked by running operations
   */
  isCancelled: boolean;
}

/**
 * Progress context value
 */
export interface ProgressContextValue {
  /**
   * Current progress state
   */
  progress: ProgressState;

  /**
   * Update progress state (partial update)
   */
  updateProgress: (update: Partial<ProgressState>) => void;

  /**
   * Start a new scan
   */
  startScan: (totalFiles: number, frames: FrameProgress[]) => void;

  /**
   * Update specific frame status
   */
  updateFrame: (frameId: string, update: Partial<FrameProgress>) => void;

  /**
   * Complete the scan
   */
  completeScan: () => void;

  /**
   * Fail the scan with error
   */
  failScan: (error: string) => void;

  /**
   * Cancel the running scan
   */
  cancelScan: () => void;

  /**
   * Reset progress to idle
   */
  resetProgress: () => void;
}

/**
 * Default progress state
 */
const DEFAULT_PROGRESS_STATE: ProgressState = {
  isActive: false,
  status: 'idle',
  filesScanned: 0,
  totalFiles: 0,
  issuesFound: 0,
  elapsedTime: 0,
  frames: [],
  isCancelled: false,
};

/**
 * Progress context
 */
const ProgressContext = createContext<ProgressContextValue | undefined>(undefined);

/**
 * Progress provider props
 */
export interface ProgressProviderProps {
  children: ReactNode;
}

/**
 * Progress provider component
 *
 * @example
 * ```tsx
 * <ProgressProvider>
 *   <App />
 * </ProgressProvider>
 * ```
 */
export const ProgressProvider: React.FC<ProgressProviderProps> = ({ children }) => {
  const [progress, setProgress] = useState<ProgressState>(DEFAULT_PROGRESS_STATE);

  /**
   * Update progress state (partial)
   */
  const updateProgress = useCallback((update: Partial<ProgressState>) => {
    setProgress((prev) => ({ ...prev, ...update }));
  }, []);

  /**
   * Start a new scan
   */
  const startScan = useCallback((totalFiles: number, frames: FrameProgress[]) => {
    setProgress({
      isActive: true,
      status: 'scanning',
      filesScanned: 0,
      totalFiles,
      issuesFound: 0,
      elapsedTime: 0,
      frames,
      startTime: new Date(),
      isCancelled: false, // Reset cancellation flag
    });
  }, []);

  /**
   * Update specific frame status
   */
  const updateFrame = useCallback((frameId: string, update: Partial<FrameProgress>) => {
    setProgress((prev) => ({
      ...prev,
      frames: prev.frames.map((frame) =>
        frame.id === frameId ? { ...frame, ...update } : frame
      ),
    }));
  }, []);

  /**
   * Complete the scan
   */
  const completeScan = useCallback(() => {
    setProgress((prev) => ({
      ...prev,
      isActive: false,
      status: 'complete',
    }));
  }, []);

  /**
   * Fail the scan with error
   */
  const failScan = useCallback((error: string) => {
    setProgress((prev) => ({
      ...prev,
      isActive: false,
      status: 'error',
      error,
    }));
  }, []);

  /**
   * Cancel the running scan
   */
  const cancelScan = useCallback(() => {
    setProgress((prev) => ({
      ...prev,
      isActive: false,
      status: 'cancelled',
      isCancelled: true,
    }));
  }, []);

  /**
   * Reset progress to idle
   */
  const resetProgress = useCallback(() => {
    setProgress(DEFAULT_PROGRESS_STATE);
  }, []);

  const value: ProgressContextValue = {
    progress,
    updateProgress,
    startScan,
    updateFrame,
    completeScan,
    failScan,
    cancelScan,
    resetProgress,
  };

  return <ProgressContext.Provider value={value}>{children}</ProgressContext.Provider>;
};

/**
 * Hook to access progress context
 *
 * @throws Error if used outside ProgressProvider
 *
 * @example
 * ```tsx
 * const { progress, startScan, updateFrame } = useProgress();
 * ```
 */
export const useProgress = (): ProgressContextValue => {
  const context = useContext(ProgressContext);
  if (!context) {
    throw new Error('useProgress must be used within ProgressProvider');
  }
  return context;
};

export default ProgressContext;
