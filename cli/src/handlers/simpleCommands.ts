/**
 * Simple Command Handlers
 *
 * Handlers for commands that don't require complex logic:
 * - /clear - Clear chat history
 * - /quit - Exit application
 *
 * No IPC connection required.
 */

import { MessageType } from '../types/index.js';
import type { CommandHandlerContext } from './types.js';

/**
 * Handle /clear command
 *
 * Clears all messages from chat history
 *
 * @param args - Command arguments (ignored)
 * @param context - Handler context
 */
export async function handleClearCommand(
  _args: string,
  context: CommandHandlerContext
): Promise<void> {
  const { clearMessages, addMessage } = context;

  // Clear all messages
  clearMessages();

  // Confirm action
  addMessage('✨ Chat history cleared.', MessageType.SYSTEM);
}

/**
 * Handle /quit command
 *
 * Gracefully exits the application
 *
 * @param args - Command arguments (ignored)
 * @param context - Handler context
 */
export async function handleQuitCommand(
  _args: string,
  context: CommandHandlerContext
): Promise<void> {
  const { addMessage, exit, client } = context;

  // Say goodbye
  addMessage('👋 Goodbye! Thanks for using Warden CLI.', MessageType.SYSTEM);

  // Disconnect IPC client if connected
  if (client) {
    try {
      await client.disconnect();
    } catch (error) {
      // Ignore disconnect errors on exit
    }
  }

  // Exit after brief delay for message display
  setTimeout(() => {
    exit();
  }, 500);
}

/**
 * Command metadata for /clear
 */
export const clearCommandMetadata = {
  name: 'clear',
  aliases: ['cls'],
  description: 'Clear chat history',
  usage: '/clear',
  requiresIPC: false,
  handler: handleClearCommand,
};

/**
 * Command metadata for /quit
 */
export const quitCommandMetadata = {
  name: 'quit',
  aliases: ['exit', 'q'],
  description: 'Exit Warden CLI',
  usage: '/quit',
  requiresIPC: false,
  handler: handleQuitCommand,
};
