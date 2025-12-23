/**
 * Utility Exports
 *
 * Central export point for all utility functions
 */

// Logging
export { logger, LogLevel } from './logger.js';

// Validation
export {
  sanitizeInput,
  isValidApiUrl,
  isValidCommand,
  parseCommand,
  userInputSchema,
  sessionIdSchema,
  envSchema,
} from './validation.js';

// Path Resolution (Simplified - Qwen Pattern)
export {
  resolvePath,
  pathExists,
  isFile,
  isDirectory,
  getFileSize,
  hasValidExtension,
  getSearchLocations,
  COMMON_SEARCH_DIRS,
} from './pathResolver.js';

// Error Handling (NEW - Phase 1)
export {
  getErrorMessage,
  getErrorStack,
  formatError,
  handleError,
  createErrorWithSuggestions,
  isWardenError,
  safeAsync,
  safe,
  // Error classes
  WardenError,
  IPCConnectionError,
  FileNotFoundError,
  PathResolutionError,
  ValidationError,
  CommandExecutionError,
  CancellationError,
  type ErrorContext,
} from './errors.js';

// Cleanup System (NEW - Phase 1)
export {
  registerCleanup,
  runExitCleanup,
  clearCleanupFunctions,
  getCleanupFunctionCount,
  setupCleanupHandlers,
  cleanupAndExit,
  saveCheckpoint,
  loadCheckpoint,
  deleteCheckpoint,
  cleanupCheckpoints,
  type CleanupFunction,
} from './cleanup.js';

// Event System (NEW - Phase 1)
export {
  appEvents,
  AppEvent,
  createScopedListener,
  waitForEvent,
  createBatchListener,
  debounceEvent,
  throttleEvent,
  type AppEventPayloads,
} from './events.js';

// Console Patcher (NEW - Phase 1)
export {
  ConsolePatcher,
  createConsolePatcher,
  type ConsoleMessage,
  type ConsoleMessageType,
  type ConsolePatcherOptions,
} from './ConsolePatcher.js';
