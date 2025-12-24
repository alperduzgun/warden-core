/**
 * Command Handlers - Public API
 *
 * Exports all command handlers and routing functionality
 */

// Types
export * from './types.js';

// Command router
export { routeCommand, getAllCommands, getCommand, commandExists, getCommandAliases } from './commandRouter.js';

// Individual handlers (for testing/direct use)
export { handleHelpCommand, helpCommandMetadata } from './helpCommand.js';
export { handleClearCommand, clearCommandMetadata, handleQuitCommand, quitCommandMetadata } from './simpleCommands.js';
export { handleStatusCommand, statusCommandMetadata } from './statusCommand.js';
export { handleAnalyzeCommand, analyzeCommandMetadata } from './analyzeCommand.js';
export { handleScanCommand, scanCommandMetadata } from './scanCommand.js';
export { handleValidateCommand, validateCommandMetadata } from './validateCommand.js';
export { handleProvidersCommand, providersCommandMetadata } from './providersCommand.js';

// TODO: Export additional handlers as they are implemented
// export { handleFixCommand, fixCommandMetadata } from './fixCommand.js';
// export { handleRulesCommand, rulesCommandMetadata } from './rulesCommand.js';
