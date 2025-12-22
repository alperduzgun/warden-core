/**
 * Command Router
 *
 * Central dispatch system for all slash commands.
 * Routes commands to appropriate handlers with error handling.
 *
 * Architecture:
 * - Type-safe command routing
 * - Alias resolution
 * - IPC requirement validation
 * - Comprehensive error handling
 */

import { MessageType } from '../types/index.js';
import type { CommandHandlerContext, CommandMetadata, CommandRouter as RouterType } from './types.js';

// Import handler metadata (handlers are registered, not directly called)
import { helpCommandMetadata } from './helpCommand.js';
import { clearCommandMetadata, quitCommandMetadata } from './simpleCommands.js';
import { statusCommandMetadata } from './statusCommand.js';
import { analyzeCommandMetadata } from './analyzeCommand.js';
import { scanCommandMetadata } from './scanCommand.js';
import { validateCommandMetadata } from './validateCommand.js';
import { fixCommandMetadata } from './fixCommand.js';
import { rulesCommandMetadata } from './rulesCommand.js';

/**
 * Command registry
 *
 * Maps command names and aliases to metadata
 */
const COMMAND_REGISTRY: Map<string, CommandMetadata> = new Map();

/**
 * Register a command with its metadata
 */
function registerCommand(metadata: CommandMetadata): void {
  // Register primary name
  COMMAND_REGISTRY.set(metadata.name, metadata);

  // Register aliases
  if (metadata.aliases) {
    for (const alias of metadata.aliases) {
      COMMAND_REGISTRY.set(alias, metadata);
    }
  }
}

/**
 * Initialize command registry
 */
function initializeRegistry(): void {
  // Register all commands
  registerCommand(helpCommandMetadata);
  registerCommand(clearCommandMetadata);
  registerCommand(quitCommandMetadata);
  registerCommand(statusCommandMetadata);
  registerCommand(analyzeCommandMetadata);
  registerCommand(scanCommandMetadata);
  registerCommand(validateCommandMetadata);
  registerCommand(fixCommandMetadata);
  registerCommand(rulesCommandMetadata);
}

// Initialize registry on module load
initializeRegistry();

/**
 * Main command router function
 *
 * Routes slash commands to appropriate handlers
 *
 * @param command - Command name (without /)
 * @param args - Command arguments
 * @param context - Handler context
 */
export const routeCommand: RouterType = async (
  command: string,
  args: string,
  context: CommandHandlerContext
): Promise<void> => {
  const { addMessage, client } = context;

  // Normalize command (lowercase)
  const normalizedCommand = command.toLowerCase().trim();

  // Look up command in registry
  const commandMetadata = COMMAND_REGISTRY.get(normalizedCommand);

  if (!commandMetadata) {
    // Unknown command
    addMessage(
      `❌ **Unknown command**: \`/${command}\`\n\n` +
        'Use `/help` to see available commands.',
      MessageType.ERROR,
      true
    );
    return;
  }

  // Check IPC requirement
  if (commandMetadata.requiresIPC && !client) {
    addMessage(
      `❌ **Command requires backend connection**: \`/${command}\`\n\n` +
        'The backend is not connected. Please ensure:\n' +
        '1. Python virtual environment is activated\n' +
        '2. IPC server is running (`python3 start_ipc_server.py`)\n' +
        '3. CLI is started with IPC enabled\n\n' +
        'Try `/status` to check connection status.',
      MessageType.ERROR,
      true
    );
    return;
  }

  // Execute handler with error handling
  try {
    await commandMetadata.handler(args, context);
  } catch (error) {
    const errorMessage =
      error instanceof Error
        ? error.message
        : typeof error === 'string'
        ? error
        : 'Unknown error';

    addMessage(
      `❌ **Command execution failed**: \`/${command}\`\n\n` +
        `Error: \`${errorMessage}\`\n\n` +
        '**Troubleshooting:**\n' +
        '1. Check command arguments are correct\n' +
        '2. Verify backend connection with `/status`\n' +
        '3. Check server logs for details\n' +
        '4. Try `/help` for usage examples',
      MessageType.ERROR,
      true
    );

    // Log error for debugging
    console.error(`[CommandRouter] Error executing /${command}:`, error);
  }
};

/**
 * Get all registered commands
 *
 * Useful for command palette, autocomplete, etc.
 */
export function getAllCommands(): CommandMetadata[] {
  const seen = new Set<string>();
  const commands: CommandMetadata[] = [];

  for (const [, metadata] of COMMAND_REGISTRY.entries()) {
    // Only return each command once (avoid duplicates from aliases)
    if (!seen.has(metadata.name)) {
      seen.add(metadata.name);
      commands.push(metadata);
    }
  }

  return commands;
}

/**
 * Get command metadata by name or alias
 */
export function getCommand(name: string): CommandMetadata | undefined {
  return COMMAND_REGISTRY.get(name.toLowerCase().trim());
}

/**
 * Check if a command exists
 */
export function commandExists(name: string): boolean {
  return COMMAND_REGISTRY.has(name.toLowerCase().trim());
}

/**
 * Get command aliases
 */
export function getCommandAliases(name: string): string[] {
  const metadata = getCommand(name);
  return metadata?.aliases || [];
}
