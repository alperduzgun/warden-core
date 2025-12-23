/**
 * Centralized Error Handling Utilities
 *
 * Provides consistent error handling patterns across the CLI.
 * Inspired by Qwen Code's error handling architecture.
 *
 * Features:
 * - Type-safe error extraction
 * - Custom error classes with exit codes
 * - Formatted error messages
 * - Debug mode support
 */

/**
 * Extract error message from unknown error types
 *
 * @param error - Unknown error object
 * @returns Human-readable error message
 */
export function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === 'string') {
    return error;
  }
  return String(error);
}

/**
 * Extract stack trace from error
 *
 * @param error - Error object
 * @returns Stack trace string or undefined
 */
export function getErrorStack(error: unknown): string | undefined {
  if (error instanceof Error && error.stack) {
    return error.stack;
  }
  return undefined;
}

/**
 * Base Warden error class
 */
export class WardenError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly exitCode: number = 1
  ) {
    super(message);
    this.name = 'WardenError';

    // Maintain proper stack trace for where error was thrown (V8 only)
    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, WardenError);
    }
  }
}

/**
 * IPC connection error
 */
export class IPCConnectionError extends WardenError {
  constructor(message: string = 'Failed to connect to Warden backend') {
    super(message, 'IPC_CONNECTION_FAILED', 1);
    this.name = 'IPCConnectionError';
  }
}

/**
 * File not found error
 */
export class FileNotFoundError extends WardenError {
  constructor(
    public readonly filePath: string,
    message?: string
  ) {
    super(
      message || `File not found: ${filePath}`,
      'FILE_NOT_FOUND',
      1
    );
    this.name = 'FileNotFoundError';
  }
}

/**
 * Path resolution error
 */
export class PathResolutionError extends WardenError {
  constructor(
    message: string,
    public readonly inputPath: string
  ) {
    super(message, 'PATH_RESOLUTION_ERROR', 1);
    this.name = 'PathResolutionError';
  }
}

/**
 * Validation error
 */
export class ValidationError extends WardenError {
  constructor(message: string, public readonly field?: string) {
    super(message, 'VALIDATION_ERROR', 1);
    this.name = 'ValidationError';
  }
}

/**
 * Command execution error
 */
export class CommandExecutionError extends WardenError {
  constructor(
    message: string,
    public readonly command?: string
  ) {
    super(message, 'COMMAND_EXECUTION_ERROR', 1);
    this.name = 'CommandExecutionError';
  }
}

/**
 * Cancellation error (user cancelled operation)
 */
export class CancellationError extends WardenError {
  constructor(message: string = 'Operation cancelled by user') {
    super(message, 'CANCELLED', 130); // Standard SIGINT exit code
    this.name = 'CancellationError';
  }
}

/**
 * Error with additional context for debugging
 */
export interface ErrorContext {
  /** Component/file where error occurred */
  component?: string;
  /** Operation being performed */
  operation?: string;
  /** Additional metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Format error with context for display
 *
 * @param error - Error object
 * @param context - Additional context
 * @param debugMode - Whether to include stack trace
 * @returns Formatted error message
 */
export function formatError(
  error: unknown,
  context?: ErrorContext,
  debugMode: boolean = false
): string {
  const message = getErrorMessage(error);
  const stack = getErrorStack(error);

  let formatted = `❌ Error: ${message}`;

  if (context?.component) {
    formatted += `\n  Component: ${context.component}`;
  }

  if (context?.operation) {
    formatted += `\n  Operation: ${context.operation}`;
  }

  if (context?.metadata && Object.keys(context.metadata).length > 0) {
    formatted += '\n  Details:';
    for (const [key, value] of Object.entries(context.metadata)) {
      formatted += `\n    - ${key}: ${JSON.stringify(value)}`;
    }
  }

  if (debugMode && stack) {
    formatted += '\n\nStack Trace:\n' + stack;
  }

  return formatted;
}

/**
 * Handle error consistently across the application
 *
 * @param error - Error object
 * @param context - Error context
 * @param options - Handling options
 */
export function handleError(
  error: unknown,
  context?: ErrorContext,
  options: {
    /** Whether to re-throw after logging */
    rethrow?: boolean;
    /** Whether to exit process */
    exit?: boolean;
    /** Exit code (default: 1) */
    exitCode?: number;
    /** Whether to show stack trace */
    debugMode?: boolean;
  } = {}
): never | void {
  const { rethrow = false, exit: shouldExit = false, exitCode = 1, debugMode = false } = options;

  // Format and log error
  const formatted = formatError(error, context, debugMode);
  console.error(formatted);

  // Extract exit code from error if available
  let finalExitCode = exitCode;
  if (error instanceof WardenError) {
    finalExitCode = error.exitCode;
  }

  // Exit if requested
  if (shouldExit) {
    process.exit(finalExitCode);
  }

  // Re-throw if requested
  if (rethrow) {
    throw error;
  }
}

/**
 * Create a user-friendly error message with suggestions
 *
 * @param error - Original error
 * @param suggestions - Array of suggestion strings
 * @returns Formatted message with suggestions
 */
export function createErrorWithSuggestions(
  error: string | Error,
  suggestions: string[]
): string {
  const message = typeof error === 'string' ? error : error.message;

  let formatted = `❌ ${message}\n`;

  if (suggestions.length > 0) {
    formatted += '\n💡 Suggestions:\n';
    suggestions.forEach((suggestion, i) => {
      formatted += `  ${i + 1}. ${suggestion}\n`;
    });
  }

  return formatted.trim();
}

/**
 * Check if error is a specific Warden error type
 */
export function isWardenError(error: unknown, type?: typeof WardenError): boolean {
  if (!type) {
    return error instanceof WardenError;
  }
  return error instanceof type;
}

/**
 * Safe error wrapper for async operations
 *
 * @param fn - Async function to wrap
 * @param context - Error context
 * @returns Result or error
 */
export async function safeAsync<T>(
  fn: () => Promise<T>,
  context?: ErrorContext
): Promise<{ result?: T; error?: unknown }> {
  try {
    const result = await fn();
    return { result };
  } catch (error) {
    if (context) {
      console.error(formatError(error, context));
    }
    return { error };
  }
}

/**
 * Safe error wrapper for sync operations
 *
 * @param fn - Sync function to wrap
 * @param context - Error context
 * @returns Result or error
 */
export function safe<T>(
  fn: () => T,
  context?: ErrorContext
): { result?: T; error?: unknown } {
  try {
    const result = fn();
    return { result };
  } catch (error) {
    if (context) {
      console.error(formatError(error, context));
    }
    return { error };
  }
}
