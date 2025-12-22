/**
 * Logger Utility
 *
 * Provides structured logging for the CLI application
 */

export enum LogLevel {
  DEBUG = 'debug',
  INFO = 'info',
  WARN = 'warn',
  ERROR = 'error',
}

const LOG_LEVELS: Record<LogLevel, number> = {
  [LogLevel.DEBUG]: 0,
  [LogLevel.INFO]: 1,
  [LogLevel.WARN]: 2,
  [LogLevel.ERROR]: 3,
};

class Logger {
  private level: LogLevel;
  private enabled: boolean;

  constructor() {
    this.level = this.parseLogLevel(process.env.WARDEN_LOG_LEVEL);
    this.enabled = process.env.NODE_ENV !== 'production';
  }

  private parseLogLevel(level?: string): LogLevel {
    if (!level) return LogLevel.INFO;

    const normalized = level.toLowerCase() as LogLevel;
    return Object.values(LogLevel).includes(normalized)
      ? normalized
      : LogLevel.INFO;
  }

  private shouldLog(level: LogLevel): boolean {
    return (
      this.enabled && LOG_LEVELS[level] >= LOG_LEVELS[this.level]
    );
  }

  private formatMessage(level: LogLevel, message: string, data?: unknown): string {
    const timestamp = new Date().toISOString();
    const dataStr = data ? ` ${JSON.stringify(data)}` : '';
    return `[${timestamp}] [${level.toUpperCase()}] ${message}${dataStr}`;
  }

  debug(message: string, data?: unknown): void {
    if (this.shouldLog(LogLevel.DEBUG)) {
      console.debug(this.formatMessage(LogLevel.DEBUG, message, data));
    }
  }

  info(message: string, data?: unknown): void {
    if (this.shouldLog(LogLevel.INFO)) {
      console.info(this.formatMessage(LogLevel.INFO, message, data));
    }
  }

  warn(message: string, data?: unknown): void {
    if (this.shouldLog(LogLevel.WARN)) {
      console.warn(this.formatMessage(LogLevel.WARN, message, data));
    }
  }

  error(message: string, error?: Error | unknown): void {
    if (this.shouldLog(LogLevel.ERROR)) {
      const errorData = error instanceof Error
        ? { message: error.message, stack: error.stack }
        : error;
      console.error(this.formatMessage(LogLevel.ERROR, message, errorData));
    }
  }
}

// Export singleton instance
export const logger = new Logger();
