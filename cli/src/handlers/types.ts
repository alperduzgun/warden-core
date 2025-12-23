/**
 * Handler Types for Warden CLI Commands
 *
 * Type-safe interfaces for command handlers following project architecture rules:
 * - Full type hints (mandatory)
 * - Error handling patterns
 * - Message type safety
 */

import type { WardenClient } from '../bridge/wardenClient.js';
import type { MessageType } from '../types/index.js';
import type { ProgressContextValue } from '../contexts/ProgressContext.js';

/**
 * Message callback function type
 *
 * Used by all handlers to add messages to chat
 */
export type AddMessageFunction = (message: string, type: MessageType, markdown?: boolean) => void;

/**
 * Clear messages callback
 */
export type ClearMessagesFunction = () => void;

/**
 * Exit callback
 */
export type ExitFunction = () => void;

/**
 * Command handler context
 *
 * Provides all dependencies a handler needs
 */
export interface CommandHandlerContext {
  /** IPC client for backend communication */
  client: WardenClient | null;

  /** Add message to chat */
  addMessage: AddMessageFunction;

  /** Clear chat messages */
  clearMessages: ClearMessagesFunction;

  /** Exit application */
  exit: ExitFunction;

  /** Progress context for real-time UI updates */
  progressContext: ProgressContextValue;

  /** Project root path (optional) */
  projectRoot?: string;

  /** Session ID (optional) */
  sessionId?: string;

  /** Last scanned directory path (for smart file search) */
  lastScanPath?: string;
}

/**
 * Base command handler function type
 */
export type CommandHandler = (
  args: string,
  context: CommandHandlerContext
) => Promise<void> | void;

/**
 * Command router function type
 */
export type CommandRouter = (
  command: string,
  args: string,
  context: CommandHandlerContext
) => Promise<void>;

/**
 * Command metadata for registration
 */
export interface CommandMetadata {
  /** Command name */
  name: string;

  /** Aliases */
  aliases?: string[];

  /** Description */
  description: string;

  /** Usage example */
  usage: string;

  /** Requires IPC connection */
  requiresIPC?: boolean;

  /** Handler function */
  handler: CommandHandler;
}

/**
 * Progress callback for long-running commands
 */
export type ProgressCallback = (event: ProgressEvent) => void;

/**
 * Progress event types
 */
export interface ProgressEvent {
  type: 'started' | 'progress' | 'completed' | 'failed';
  message: string;
  current?: number;
  total?: number;
  metadata?: Record<string, any>;
}
