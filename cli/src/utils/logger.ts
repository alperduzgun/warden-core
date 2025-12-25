/**
 * Structured Logger
 * Provides structured logging with context for better debugging
 */

export type LogLevel = 'debug' | 'info' | 'warning' | 'error' | 'critical';

export interface LogContext {
  [key: string]: string | number | boolean | undefined | null;
}

class Logger {
  private level: LogLevel;

  constructor() {
    // Set log level from environment or default to 'info'
    const envLevel = process.env.WARDEN_LOG_LEVEL?.toLowerCase() as LogLevel;
    this.level = envLevel || 'info';
  }

  /**
   * Log debug message (development only)
   */
  debug(event: string, context?: LogContext): void {
    if (this.shouldLog('debug')) {
      this.log('debug', event, context);
    }
  }

  /**
   * Log info message (normal flow)
   */
  info(event: string, context?: LogContext): void {
    if (this.shouldLog('info')) {
      this.log('info', event, context);
    }
  }

  /**
   * Log warning message (potential issues)
   */
  warning(event: string, context?: LogContext): void {
    if (this.shouldLog('warning')) {
      this.log('warning', event, context);
    }
  }

  /**
   * Log error message (failures)
   */
  error(event: string, context?: LogContext): void {
    if (this.shouldLog('error')) {
      this.log('error', event, context);
    }
  }

  /**
   * Log critical message (system failures)
   */
  critical(event: string, context?: LogContext): void {
    if (this.shouldLog('critical')) {
      this.log('critical', event, context);
    }
  }

  /**
   * Internal log method
   */
  private log(level: LogLevel, event: string, context?: LogContext): void {
    const timestamp = new Date().toISOString();
    const logEntry = {
      timestamp,
      level: level.toUpperCase(),
      event,
      ...context,
    };

    // Format output based on level
    const output = JSON.stringify(logEntry);

    if (level === 'error' || level === 'critical') {
      console.error(output);
    } else {
      console.log(output);
    }
  }

  /**
   * Check if should log at this level
   */
  private shouldLog(level: LogLevel): boolean {
    const levels: LogLevel[] = ['debug', 'info', 'warning', 'error', 'critical'];
    const currentLevelIndex = levels.indexOf(this.level);
    const requestedLevelIndex = levels.indexOf(level);

    return requestedLevelIndex >= currentLevelIndex;
  }

  /**
   * Set log level
   */
  setLevel(level: LogLevel): void {
    this.level = level;
  }

  /**
   * Get current log level
   */
  getLevel(): LogLevel {
    return this.level;
  }
}

// Singleton instance
export const logger = new Logger();
