/**
 * Event System
 *
 * Centralized event bus for decoupled component communication.
 * Inspired by Qwen Code's event architecture.
 *
 * Features:
 * - Type-safe event emitting and listening
 * - Decoupled component communication
 * - Event namespacing
 * - Automatic cleanup
 */

import { EventEmitter } from 'events';

/**
 * Application event types
 */
export enum AppEvent {
  /** Error occurred that should be logged */
  LOG_ERROR = 'log-error',

  /** Open debug console */
  OPEN_DEBUG_CONSOLE = 'open-debug-console',

  /** Message added to chat */
  MESSAGE_ADDED = 'message-added',

  /** IPC connection status changed */
  IPC_STATUS_CHANGED = 'ipc-status-changed',

  /** Scan started */
  SCAN_STARTED = 'scan-started',

  /** Scan completed */
  SCAN_COMPLETED = 'scan-completed',

  /** Scan failed */
  SCAN_FAILED = 'scan-failed',

  /** Analysis started */
  ANALYSIS_STARTED = 'analysis-started',

  /** Analysis completed */
  ANALYSIS_COMPLETED = 'analysis-completed',

  /** Analysis failed */
  ANALYSIS_FAILED = 'analysis-failed',

  /** Theme changed */
  THEME_CHANGED = 'theme-changed',

  /** Config reloaded */
  CONFIG_RELOADED = 'config-reloaded',

  /** Clear screen requested */
  CLEAR_SCREEN = 'clear-screen',

  /** Exit requested */
  EXIT_REQUESTED = 'exit-requested',
}

/**
 * Event payload types
 */
export interface AppEventPayloads {
  [AppEvent.LOG_ERROR]: { message: string; stack?: string };
  [AppEvent.OPEN_DEBUG_CONSOLE]: void;
  [AppEvent.MESSAGE_ADDED]: { type: string; content: string };
  [AppEvent.IPC_STATUS_CHANGED]: { connected: boolean };
  [AppEvent.SCAN_STARTED]: { path: string; fileCount: number };
  [AppEvent.SCAN_COMPLETED]: { path: string; duration: number; issuesFound: number };
  [AppEvent.SCAN_FAILED]: { path: string; error: string };
  [AppEvent.ANALYSIS_STARTED]: { file: string };
  [AppEvent.ANALYSIS_COMPLETED]: { file: string; duration: number; issuesFound: number };
  [AppEvent.ANALYSIS_FAILED]: { file: string; error: string };
  [AppEvent.THEME_CHANGED]: { theme: string };
  [AppEvent.CONFIG_RELOADED]: void;
  [AppEvent.CLEAR_SCREEN]: void;
  [AppEvent.EXIT_REQUESTED]: { code: number };
}

/**
 * Type-safe event emitter
 */
class TypedEventEmitter extends EventEmitter {
  /**
   * Emit a typed event
   */
  override emit<E extends AppEvent>(
    event: E,
    ...args: AppEventPayloads[E] extends void ? [] : [AppEventPayloads[E]]
  ): boolean {
    return super.emit(event, ...args);
  }

  /**
   * Listen to a typed event
   */
  override on<E extends AppEvent>(
    event: E,
    listener: (payload: AppEventPayloads[E]) => void
  ): this {
    return super.on(event, listener);
  }

  /**
   * Listen to a typed event once
   */
  override once<E extends AppEvent>(
    event: E,
    listener: (payload: AppEventPayloads[E]) => void
  ): this {
    return super.once(event, listener);
  }

  /**
   * Remove a typed event listener
   */
  override off<E extends AppEvent>(
    event: E,
    listener: (payload: AppEventPayloads[E]) => void
  ): this {
    return super.off(event, listener);
  }
}

/**
 * Global application event bus
 *
 * @example
 * ```ts
 * // Emit an event
 * appEvents.emit(AppEvent.LOG_ERROR, {
 *   message: 'Connection failed',
 *   stack: error.stack
 * });
 *
 * // Listen to an event
 * appEvents.on(AppEvent.IPC_STATUS_CHANGED, ({ connected }) => {
 *   console.log(`IPC ${connected ? 'connected' : 'disconnected'}`);
 * });
 * ```
 */
export const appEvents = new TypedEventEmitter();

// Increase max listeners to avoid warnings in complex apps
appEvents.setMaxListeners(50);

/**
 * Create a scoped event listener that auto-removes on cleanup
 *
 * Useful for component lifecycle management.
 *
 * @returns Cleanup function to remove listener
 *
 * @example
 * ```ts
 * // In a React component
 * useEffect(() => {
 *   return createScopedListener(AppEvent.THEME_CHANGED, ({ theme }) => {
 *     console.log('Theme changed:', theme);
 *   });
 * }, []);
 * ```
 */
export function createScopedListener<E extends AppEvent>(
  event: E,
  listener: (payload: AppEventPayloads[E]) => void
): () => void {
  appEvents.on(event, listener);

  // Return cleanup function
  return () => {
    appEvents.off(event, listener);
  };
}

/**
 * Wait for a specific event to occur
 *
 * Returns a promise that resolves when the event is emitted.
 *
 * @param event - Event to wait for
 * @param timeout - Optional timeout in milliseconds
 * @returns Promise that resolves with event payload
 *
 * @example
 * ```ts
 * // Wait for IPC connection
 * try {
 *   await waitForEvent(AppEvent.IPC_STATUS_CHANGED, 5000);
 *   console.log('IPC connected!');
 * } catch (error) {
 *   console.error('Timeout waiting for IPC');
 * }
 * ```
 */
export function waitForEvent<E extends AppEvent>(
  event: E,
  timeout?: number
): Promise<AppEventPayloads[E]> {
  return new Promise((resolve, reject) => {
    let timer: NodeJS.Timeout | undefined;

    const listener = (payload: AppEventPayloads[E]) => {
      if (timer) clearTimeout(timer);
      resolve(payload);
    };

    appEvents.once(event, listener);

    if (timeout) {
      timer = setTimeout(() => {
        appEvents.off(event, listener);
        reject(new Error(`Timeout waiting for event: ${event}`));
      }, timeout);
    }
  });
}

/**
 * Batch multiple event listeners
 *
 * Useful for setting up multiple listeners at once.
 *
 * @returns Cleanup function to remove all listeners
 *
 * @example
 * ```ts
 * const cleanup = createBatchListener([
 *   [AppEvent.SCAN_STARTED, (data) => console.log('Started', data)],
 *   [AppEvent.SCAN_COMPLETED, (data) => console.log('Completed', data)],
 *   [AppEvent.SCAN_FAILED, (data) => console.error('Failed', data)],
 * ]);
 *
 * // Later...
 * cleanup();
 * ```
 */
export function createBatchListener(
  listeners: Array<[AppEvent, (payload: any) => void]>
): () => void {
  const cleanupFunctions = listeners.map(([event, listener]) =>
    createScopedListener(event as any, listener)
  );

  return () => {
    cleanupFunctions.forEach((cleanup) => cleanup());
  };
}

/**
 * Debounce event emissions
 *
 * Useful for high-frequency events like file changes.
 *
 * @param event - Event to debounce
 * @param delay - Debounce delay in milliseconds
 * @returns Debounced emit function
 *
 * @example
 * ```ts
 * const debouncedEmit = debounceEvent(AppEvent.CONFIG_RELOADED, 1000);
 *
 * // Multiple rapid calls
 * debouncedEmit(); // Ignored
 * debouncedEmit(); // Ignored
 * debouncedEmit(); // Only this one emits (after 1s)
 * ```
 */
export function debounceEvent<E extends AppEvent>(
  event: E,
  delay: number
): (payload?: any) => void {
  let timer: NodeJS.Timeout | undefined;

  return (payload?: any) => {
    if (timer) clearTimeout(timer);

    timer = setTimeout(() => {
      if (payload !== undefined) {
        appEvents.emit(event as any, payload);
      } else {
        appEvents.emit(event as any);
      }
    }, delay);
  };
}

/**
 * Throttle event emissions
 *
 * Useful for limiting event frequency.
 *
 * @param event - Event to throttle
 * @param limit - Minimum time between emissions in milliseconds
 * @returns Throttled emit function
 *
 * @example
 * ```ts
 * const throttledEmit = throttleEvent(AppEvent.MESSAGE_ADDED, 100);
 *
 * // Rapid calls - only emits once per 100ms
 * throttledEmit({ type: 'user', content: 'msg1' }); // Emits
 * throttledEmit({ type: 'user', content: 'msg2' }); // Ignored
 * throttledEmit({ type: 'user', content: 'msg3' }); // Ignored
 * ```
 */
export function throttleEvent<E extends AppEvent>(
  event: E,
  limit: number
): (payload?: any) => void {
  let lastEmit = 0;

  return (payload?: any) => {
    const now = Date.now();

    if (now - lastEmit >= limit) {
      lastEmit = now;
      if (payload !== undefined) {
        appEvents.emit(event as any, payload);
      } else {
        appEvents.emit(event as any);
      }
    }
  };
}
