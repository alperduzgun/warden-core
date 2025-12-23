/**
 * Console Patcher
 *
 * Intercepts console output and redirects to UI or custom handlers.
 * Inspired by Qwen Code's console patching architecture.
 *
 * Features:
 * - Console.log/error/warn/debug interception
 * - UI integration
 * - Debug mode filtering
 * - Original console restoration
 * - Message aggregation
 */

/**
 * Console message types
 */
export type ConsoleMessageType = 'log' | 'error' | 'warn' | 'debug' | 'info';

/**
 * Console message format
 */
export interface ConsoleMessage {
  /** Message type */
  type: ConsoleMessageType;
  /** Message content */
  content: string;
  /** Message timestamp */
  timestamp: number;
  /** Occurrence count (for aggregation) */
  count: number;
}

/**
 * Console patcher options
 */
export interface ConsolePatcherOptions {
  /** Callback for new messages */
  onNewMessage?: (message: ConsoleMessage) => void;

  /** Whether to output to stderr (for non-interactive mode) */
  stderr?: boolean;

  /** Whether debug messages should be captured */
  debugMode?: boolean;

  /** Whether to aggregate duplicate messages */
  aggregateDuplicates?: boolean;

  /** Time window for aggregation in milliseconds */
  aggregationWindow?: number;
}

/**
 * Console Patcher Class
 *
 * Intercepts console methods and provides custom handling.
 */
export class ConsolePatcher {
  /** Original console methods (for restoration) */
  private originalConsole: {
    log: typeof console.log;
    error: typeof console.error;
    warn: typeof console.warn;
    debug: typeof console.debug;
    info: typeof console.info;
  };

  /** Whether console is currently patched */
  private isPatched = false;

  /** Message aggregation cache */
  private messageCache = new Map<string, ConsoleMessage>();

  /** Aggregation timer */
  private aggregationTimer?: NodeJS.Timeout | undefined;

  constructor(private options: ConsolePatcherOptions = {}) {
    // Store original console methods
    this.originalConsole = {
      log: console.log.bind(console),
      error: console.error.bind(console),
      warn: console.warn.bind(console),
      debug: console.debug.bind(console),
      info: console.info.bind(console),
    };
  }

  /**
   * Patch console methods
   */
  patch(): void {
    if (this.isPatched) {
      return; // Already patched
    }

    // Patch console.log
    console.log = (...args: any[]) => {
      this.handleMessage('log', args);
    };

    // Patch console.error
    console.error = (...args: any[]) => {
      this.handleMessage('error', args);
      // Always output errors to stderr
      if (this.options.stderr) {
        this.originalConsole.error(...args);
      }
    };

    // Patch console.warn
    console.warn = (...args: any[]) => {
      this.handleMessage('warn', args);
    };

    // Patch console.debug
    console.debug = (...args: any[]) => {
      // Only capture debug messages in debug mode
      if (this.options.debugMode) {
        this.handleMessage('debug', args);
      }
    };

    // Patch console.info
    console.info = (...args: any[]) => {
      this.handleMessage('info', args);
    };

    this.isPatched = true;
  }

  /**
   * Restore original console methods
   */
  cleanup(): void {
    if (!this.isPatched) {
      return; // Not patched
    }

    // Restore original methods
    console.log = this.originalConsole.log;
    console.error = this.originalConsole.error;
    console.warn = this.originalConsole.warn;
    console.debug = this.originalConsole.debug;
    console.info = this.originalConsole.info;

    // Clear aggregation timer
    if (this.aggregationTimer) {
      clearTimeout(this.aggregationTimer);
    }

    // Clear cache
    this.messageCache.clear();

    this.isPatched = false;
  }

  /**
   * Handle a console message
   */
  private handleMessage(type: ConsoleMessageType, args: any[]): void {
    // Format message content
    const content = this.formatArgs(args);

    // Create message object
    const message: ConsoleMessage = {
      type,
      content,
      timestamp: Date.now(),
      count: 1,
    };

    // Handle aggregation
    if (this.options.aggregateDuplicates) {
      this.aggregateMessage(message);
    } else {
      // Emit immediately
      this.emitMessage(message);
    }

    // Output to original console in debug mode
    if (this.options.debugMode) {
      this.originalConsole[type === 'info' ? 'log' : type](...args);
    }
  }

  /**
   * Format console arguments to string
   */
  private formatArgs(args: any[]): string {
    return args
      .map((arg) => {
        if (typeof arg === 'string') {
          return arg;
        }
        if (arg instanceof Error) {
          return `${arg.message}\n${arg.stack || ''}`;
        }
        try {
          return JSON.stringify(arg, null, 2);
        } catch {
          return String(arg);
        }
      })
      .join(' ');
  }

  /**
   * Aggregate duplicate messages
   */
  private aggregateMessage(message: ConsoleMessage): void {
    const key = `${message.type}:${message.content}`;
    const existing = this.messageCache.get(key);

    if (existing) {
      // Increment count
      existing.count += 1;
      existing.timestamp = message.timestamp;
    } else {
      // Store new message
      this.messageCache.set(key, message);

      // Start aggregation window
      this.startAggregationWindow();
    }
  }

  /**
   * Start aggregation window timer
   */
  private startAggregationWindow(): void {
    if (this.aggregationTimer) {
      return; // Timer already running
    }

    const window = this.options.aggregationWindow ?? 1000; // Default 1s

    this.aggregationTimer = setTimeout(() => {
      this.flushAggregatedMessages();
      this.aggregationTimer = undefined;
    }, window);
  }

  /**
   * Flush aggregated messages
   */
  private flushAggregatedMessages(): void {
    for (const message of this.messageCache.values()) {
      this.emitMessage(message);
    }

    this.messageCache.clear();
  }

  /**
   * Emit message to callback
   */
  private emitMessage(message: ConsoleMessage): void {
    if (this.options.onNewMessage) {
      this.options.onNewMessage(message);
    }
  }

  /**
   * Get current patch status
   */
  isPatchedActive(): boolean {
    return this.isPatched;
  }

  /**
   * Manually log a message (bypass patching)
   */
  logDirect(type: ConsoleMessageType, ...args: any[]): void {
    this.originalConsole[type === 'info' ? 'log' : type](...args);
  }
}

/**
 * Create a console patcher with default options
 *
 * @param options - Patcher options
 * @returns ConsolePatcher instance
 *
 * @example
 * ```ts
 * const patcher = createConsolePatcher({
 *   onNewMessage: (msg) => {
 *     addMessageToUI(msg);
 *   },
 *   debugMode: true,
 * });
 *
 * patcher.patch();
 *
 * // Later...
 * patcher.cleanup();
 * ```
 */
export function createConsolePatcher(
  options: ConsolePatcherOptions = {}
): ConsolePatcher {
  return new ConsolePatcher(options);
}
