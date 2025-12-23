/**
 * Cleanup System
 *
 * Centralized resource cleanup management for graceful shutdown.
 * Inspired by Qwen Code's cleanup architecture.
 *
 * Features:
 * - Register cleanup functions globally
 * - Automatic execution on process exit
 * - Error handling during cleanup
 * - Async cleanup support
 * - Ordered cleanup (LIFO - Last In First Out)
 */

/** Cleanup function type (sync or async) */
export type CleanupFunction = () => void | Promise<void>;

/** Registered cleanup functions */
const cleanupFunctions: CleanupFunction[] = [];

/** Track if cleanup is in progress */
let isCleaningUp = false;

/** Track if cleanup is complete */
let cleanupComplete = false;

/**
 * Register a cleanup function to be called on exit
 *
 * Cleanup functions are called in reverse order (LIFO).
 * This ensures dependencies are cleaned up in correct order.
 *
 * @param fn - Cleanup function (sync or async)
 *
 * @example
 * ```ts
 * // Register IPC disconnect
 * registerCleanup(async () => {
 *   await client.disconnect();
 * });
 *
 * // Register file close
 * registerCleanup(() => {
 *   fileHandle.close();
 * });
 * ```
 */
export function registerCleanup(fn: CleanupFunction): void {
  if (cleanupComplete) {
    console.warn('[Cleanup] Warning: Attempting to register cleanup after cleanup completed');
    return;
  }

  cleanupFunctions.push(fn);
}

/**
 * Run all registered cleanup functions
 *
 * Executes in reverse order (LIFO).
 * Catches and logs errors without stopping cleanup chain.
 *
 * @returns Promise that resolves when all cleanup is complete
 */
export async function runExitCleanup(): Promise<void> {
  // Prevent multiple cleanup runs
  if (isCleaningUp || cleanupComplete) {
    return;
  }

  isCleaningUp = true;

  // Execute cleanup functions in reverse order
  const functions = [...cleanupFunctions].reverse();

  for (const fn of functions) {
    try {
      await fn();
    } catch (error) {
      // Log error but continue cleanup
      console.error('[Cleanup] Error during cleanup:', error);
    }
  }

  cleanupComplete = true;
  isCleaningUp = false;
}

/**
 * Clear all registered cleanup functions
 *
 * Useful for testing or manual cleanup management.
 */
export function clearCleanupFunctions(): void {
  cleanupFunctions.length = 0;
  isCleaningUp = false;
  cleanupComplete = false;
}

/**
 * Get count of registered cleanup functions
 *
 * Useful for debugging and testing.
 */
export function getCleanupFunctionCount(): number {
  return cleanupFunctions.length;
}

/**
 * Setup automatic cleanup on process exit signals
 *
 * Call this once in your main application entry point.
 *
 * Handles:
 * - SIGINT (Ctrl+C)
 * - SIGTERM (kill)
 * - SIGQUIT (Ctrl+\)
 * - Uncaught exceptions
 * - Unhandled rejections
 *
 * @param options - Configuration options
 */
export function setupCleanupHandlers(options: {
  /** Whether to handle uncaught exceptions (default: true) */
  handleExceptions?: boolean;
  /** Whether to handle unhandled rejections (default: true) */
  handleRejections?: boolean;
  /** Whether to exit after cleanup (default: true) */
  exitAfterCleanup?: boolean;
  /** Custom exit code (default: 0 for signals, 1 for errors) */
  exitCode?: number;
} = {}): void {
  const {
    handleExceptions = true,
    handleRejections = true,
    exitAfterCleanup = true,
    exitCode,
  } = options;

  // Handle SIGINT (Ctrl+C)
  process.on('SIGINT', async () => {
    console.log('\n[Cleanup] Received SIGINT signal, cleaning up...');
    await runExitCleanup();
    if (exitAfterCleanup) {
      process.exit(exitCode ?? 0);
    }
  });

  // Handle SIGTERM (kill)
  process.on('SIGTERM', async () => {
    console.log('\n[Cleanup] Received SIGTERM signal, cleaning up...');
    await runExitCleanup();
    if (exitAfterCleanup) {
      process.exit(exitCode ?? 0);
    }
  });

  // Handle SIGQUIT (Ctrl+\)
  process.on('SIGQUIT', async () => {
    console.log('\n[Cleanup] Received SIGQUIT signal, cleaning up...');
    await runExitCleanup();
    if (exitAfterCleanup) {
      process.exit(exitCode ?? 0);
    }
  });

  // Handle uncaught exceptions
  if (handleExceptions) {
    process.on('uncaughtException', async (error) => {
      console.error('[Cleanup] Uncaught exception:', error);
      await runExitCleanup();
      if (exitAfterCleanup) {
        process.exit(exitCode ?? 1);
      }
    });
  }

  // Handle unhandled promise rejections
  if (handleRejections) {
    process.on('unhandledRejection', async (reason, promise) => {
      console.error('[Cleanup] Unhandled rejection at:', promise, 'reason:', reason);
      await runExitCleanup();
      if (exitAfterCleanup) {
        process.exit(exitCode ?? 1);
      }
    });
  }

  // Handle normal exit
  process.on('exit', (code) => {
    if (!cleanupComplete) {
      console.log(`[Cleanup] Process exiting with code ${code}`);
    }
  });
}

/**
 * Execute cleanup and exit process
 *
 * Convenience function for manual exit with cleanup.
 *
 * @param exitCode - Exit code (default: 0)
 */
export async function cleanupAndExit(exitCode: number = 0): Promise<never> {
  await runExitCleanup();
  process.exit(exitCode);
}

/**
 * Checkpoint management for long-running operations
 *
 * Allows saving state periodically and cleaning up checkpoints on exit.
 */
const checkpoints = new Map<string, string>();

/**
 * Save a checkpoint
 *
 * @param id - Checkpoint identifier
 * @param data - Data to save
 */
export function saveCheckpoint(id: string, data: string): void {
  checkpoints.set(id, data);
}

/**
 * Load a checkpoint
 *
 * @param id - Checkpoint identifier
 * @returns Checkpoint data or undefined
 */
export function loadCheckpoint(id: string): string | undefined {
  return checkpoints.get(id);
}

/**
 * Delete a checkpoint
 *
 * @param id - Checkpoint identifier
 */
export function deleteCheckpoint(id: string): void {
  checkpoints.delete(id);
}

/**
 * Clean up all checkpoints
 *
 * Call this on exit to clean up temporary state.
 */
export async function cleanupCheckpoints(): Promise<void> {
  checkpoints.clear();
}
