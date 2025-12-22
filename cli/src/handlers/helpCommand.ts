/**
 * Help Command Handler
 *
 * Displays comprehensive help information for all Warden CLI commands.
 * No IPC connection required - pure UI command.
 *
 * Reference: src/warden/tui/commands/help.py
 */

import { MessageType } from '../types/index.js';
import type { CommandHandlerContext } from './types.js';

/**
 * Full help text matching Textual TUI version
 *
 * Kept identical to Python version for consistency
 */
const HELP_TEXT = `# 📖 Warden Commands

## 🔍 Analysis Commands
- \`/analyze <file>\` or \`/a <file>\` - Analyze a code file
- \`/scan [path]\` or \`/s [path]\` - Scan project or directory
- \`/validate <file>\` or \`/v <file>\` - Run validation frames

## 🔧 Fixing Commands
- \`/fix <file>\` or \`/f <file>\` - Auto-fix issues in code

## 📜 Rules Management
- \`/rules\` or \`/r\` - List all custom validation rules
- \`/rules show <id>\` - Show detailed rule information
- \`/rules stats\` - Display rules statistics

## ⚙️  Utility Commands
- \`/help\` or \`/h\` or \`/?\` - Show this help
- \`/status\` or \`/info\` - Show session status
- \`/clear\` or \`/cls\` - Clear chat history
- \`/quit\` or \`/exit\` or \`/q\` - Exit Warden

## ⌨️  Keyboard Shortcuts
- \`Ctrl+P\` or \`/\` - **Open command palette** (shows all commands)
- \`Ctrl+Q\` - Quit Warden
- \`Ctrl+L\` - Clear chat
- \`Ctrl+S\` - Save session

## 💡 Pro Tips
- **Command Palette**: Press \`Ctrl+P\` or type \`/\` to see all commands in a searchable list
- **Chat Naturally**: You can also chat without slash commands (e.g., "analyze my code")
- **Aliases**: Most commands have shortcuts (e.g., \`/a\` = \`/analyze\`, \`/s\` = \`/scan\`)
- **Markdown Support**: Messages support rich formatting with **bold**, \`code\`, and more`;

/**
 * Handle /help command
 *
 * @param args - Command arguments (ignored)
 * @param context - Handler context
 */
export async function handleHelpCommand(
  _args: string,
  context: CommandHandlerContext
): Promise<void> {
  const { addMessage } = context;

  // Display help text with markdown rendering
  addMessage(HELP_TEXT, MessageType.SYSTEM, true);
}

/**
 * Command metadata for registration
 */
export const helpCommandMetadata = {
  name: 'help',
  aliases: ['h', '?'],
  description: 'Show help information',
  usage: '/help',
  requiresIPC: false,
  handler: handleHelpCommand,
};
