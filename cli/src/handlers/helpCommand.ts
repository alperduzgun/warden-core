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

## 📦 Provider Management
- \`/providers list\` or \`/p list\` - List installed AST providers
- \`/providers test <language>\` - Test provider availability

## ⚙️  Utility Commands
- \`/help\` or \`/h\` or \`/?\` - Show this help
- \`/status\` or \`/info\` - Show session status
- \`/clear\` or \`/cls\` - Clear chat history
- \`/quit\` or \`/exit\` or \`/q\` - Exit Warden

## ⌨️  Keyboard Shortcuts
- \`Esc\` - **Cancel active scan/analyze** (graceful shutdown)
- \`@\` - **File picker** (browse and select files)
- \`Ctrl+C\` - Quit Warden (immediate exit)

## 💡 Pro Tips
- **File Picker**: Type \`@\` to browse files, use arrows to navigate, Tab/Enter to select
- **Scan Cancellation**: Press \`Esc\` during scan to stop and save partial results
- **Aliases**: Most commands have shortcuts (e.g., \`/a\` = \`/analyze\`, \`/s\` = \`/scan\`)
- **Reports**: Scan results auto-saved to \`.warden/reports/\` (JSON + Markdown)
- **Validate Frames**: Use \`/validate --list\` to see available validation frames`;

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
