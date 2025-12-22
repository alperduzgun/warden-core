/**
 * Fix Command Handler
 *
 * Auto-fixes issues found in code:
 * - Backs up original file
 * - Applies AI-suggested fixes
 * - Shows diff of changes
 * - Requires confirmation before applying
 *
 * Requires IPC connection to Python backend.
 *
 * IMPORTANT: Warden is a REPORTER, not a code modifier by default.
 * This command is an exception and requires explicit user confirmation.
 */

import { existsSync, statSync } from 'fs';
import { resolve, basename } from 'path';
import { MessageType } from '../types/index.js';
import type { CommandHandlerContext } from './types.js';

/**
 * Parse issue IDs from args
 * Supports: "1,2,3" or "1 2 3" or just "1"
 */
function parseIssueIds(issueArg: string): string[] {
  if (!issueArg) return [];

  // Split by comma or space
  return issueArg
    .split(/[,\s]+/)
    .map(id => id.trim())
    .filter(id => id.length > 0);
}

// Note: These helper functions are preserved for future implementation
// when the Python backend supports fix_issues() method

/**
 * Create backup of file
 */
// function createBackup(filePath: string): string {
//   const backupPath = `${filePath}.bak`;
//   copyFileSync(filePath, backupPath);
//   return backupPath;
// }

/**
 * Generate diff between two strings (simple line-by-line diff)
 */
// function generateSimpleDiff(original: string, modified: string): string {
//   const originalLines = original.split('\n');
//   const modifiedLines = modified.split('\n');
//
//   let diff = '';
//   const maxLines = Math.max(originalLines.length, modifiedLines.length);
//
//   for (let i = 0; i < maxLines; i++) {
//     const origLine = originalLines[i] || '';
//     const modLine = modifiedLines[i] || '';
//
//     if (origLine !== modLine) {
//       if (origLine) {
//         diff += `- ${origLine}\n`;
//       }
//       if (modLine) {
//         diff += `+ ${modLine}\n`;
//       }
//     } else if (origLine) {
//       diff += `  ${origLine}\n`;
//     }
//   }
//
//   return diff;
// }

/**
 * Handle /fix command
 *
 * @param args - File path and optional issue IDs
 * @param context - Handler context
 */
export async function handleFixCommand(
  args: string,
  context: CommandHandlerContext
): Promise<void> {
  const { addMessage, client } = context;

  // Parse args: <file> [issue_id1,issue_id2,...]
  const parts = args.trim().split(/\s+/).filter(p => p.length > 0);

  if (parts.length === 0 || !parts[0]) {
    addMessage(
      '❌ **Missing file path**\n\n' +
        'Usage: `/fix <file> [issue_id1,issue_id2,...]`\n\n' +
        'Examples:\n' +
        '- `/fix file.py` - Fix all issues in file\n' +
        '- `/fix file.py W001` - Fix only issue W001\n' +
        '- `/fix file.py W001,W002` - Fix issues W001 and W002',
      MessageType.ERROR,
      true
    );
    return;
  }

  // Validate IPC client
  if (!client) {
    addMessage(
      '❌ **IPC connection not available**\n\n' +
        'The backend is not connected. Please ensure:\n' +
        '1. Python virtual environment is activated\n' +
        '2. IPC server is running (`python3 start_ipc_server.py`)\n' +
        '3. CLI is started with IPC enabled',
      MessageType.ERROR,
      true
    );
    return;
  }

  const filePath = resolve(parts[0]);
  const issueIds = parts.length > 1 ? parseIssueIds(parts.slice(1).join(' ')) : [];

  // Check file exists
  if (!existsSync(filePath)) {
    addMessage(
      `❌ **File not found**: \`${filePath}\`\n\n` +
        'Please check the file path and try again.',
      MessageType.ERROR,
      true
    );
    return;
  }

  // Check if it's a file (not directory)
  const stats = statSync(filePath);
  if (!stats.isFile()) {
    addMessage(
      `❌ **Not a file**: \`${filePath}\`\n\n` +
        'Please provide a file path, not a directory.',
      MessageType.ERROR,
      true
    );
    return;
  }

  // Check file extension (currently only .py supported)
  if (!filePath.endsWith('.py')) {
    addMessage(
      `⚠️  **Warning**: Only Python files (\`.py\`) are currently supported.\n\n` +
        `File: \`${filePath}\`\n\n` +
        'Fix suggestions may not work correctly for other file types.',
      MessageType.ERROR,
      true
    );
  }

  // Important warning about auto-fixing
  addMessage(
    `⚠️  **IMPORTANT: Auto-Fix Warning**\n\n` +
      'Warden is primarily a **reporter**, not a code modifier.\n\n' +
      'This command will:\n' +
      '1. Create a backup of your file (.bak)\n' +
      '2. Analyze and suggest fixes\n' +
      '3. Show you a diff of proposed changes\n' +
      '4. Require your confirmation before applying\n\n' +
      '**No changes will be made without your explicit approval.**',
    MessageType.SYSTEM,
    true
  );

  // Start fix process
  const issuesMsg = issueIds.length > 0
    ? `issues: ${issueIds.join(', ')}`
    : 'all issues';

  addMessage(
    `🔧 **Analyzing**: \`${basename(filePath)}\`\n\n` +
      `Generating fix suggestions for ${issuesMsg}...`,
    MessageType.SYSTEM,
    true
  );

  try {
    // Note: This is a placeholder implementation
    // The actual fix_issues method needs to be added to the Python backend
    //
    // For now, we'll show a message explaining the feature is coming soon
    // and demonstrate the workflow

    addMessage(
      `🚧 **Feature Under Development**\n\n` +
        '**Status**: The auto-fix feature is currently being implemented.\n\n' +
        '**Planned Workflow**:\n' +
        '1. **Backup**: Original file copied to \`.bak\`\n' +
        '2. **Analysis**: AI analyzes issues and generates fixes\n' +
        '3. **Preview**: Show diff of proposed changes\n' +
        '4. **Confirmation**: Ask user to approve/reject\n' +
        '5. **Apply**: Apply changes if approved\n\n' +
        '**Security Principles**:\n' +
        '- ✅ Always backup before changes\n' +
        '- ✅ Show full diff before applying\n' +
        '- ✅ Require explicit user confirmation\n' +
        '- ✅ Never modify code without approval\n' +
        '- ✅ Preserve original file as .bak\n\n' +
        '**Current Workaround**:\n' +
        '1. Use `/analyze` to see issues\n' +
        '2. Manually fix issues in your editor\n' +
        '3. Use `/validate` to verify fixes\n\n' +
        '**Coming Soon**: Full auto-fix with interactive diff preview!',
      MessageType.SYSTEM,
      true
    );

    // Example of what the implementation would look like:
    /*
    // Execute fix via IPC
    const fixResult = await client.fixIssues(filePath, issueIds);

    if (!fixResult.has_changes) {
      addMessage(
        '✅ **No fixes needed**\n\n' +
          'All specified issues are already resolved or cannot be auto-fixed.',
        MessageType.SYSTEM,
        true
      );
      return;
    }

    // Read original file
    const originalContent = readFileSync(filePath, 'utf-8');

    // Show diff
    const diff = generateSimpleDiff(originalContent, fixResult.modified_content);

    addMessage(
      `📋 **Proposed Changes**\n\n` +
        `File: \`${basename(filePath)}\`\n` +
        `Issues Fixed: ${fixResult.issues_fixed.join(', ')}\n\n` +
        '**Diff**:\n' +
        '```diff\n' +
        diff +
        '```\n\n' +
        '⚠️  **Review the changes carefully before applying!**\n\n' +
        'Would you like to apply these changes? (y/n)',
      MessageType.SYSTEM,
      true
    );

    // In a real implementation, we would:
    // 1. Wait for user confirmation (requires interactive input in CLI)
    // 2. Create backup
    // 3. Apply changes
    // 4. Show success message with backup path
    */

  } catch (error) {
    addMessage(
      `❌ **Fix generation failed**\n\n` +
        `Error: \`${error instanceof Error ? error.message : 'Unknown error'}\`\n\n` +
        '**Troubleshooting:**\n' +
        '1. Ensure IPC server is running\n' +
        '2. Check server logs for details\n' +
        '3. Try `/analyze` first to see issues\n' +
        '4. Verify file is valid Python code',
      MessageType.ERROR,
      true
    );
  }
}

/**
 * Command metadata for registration
 */
export const fixCommandMetadata = {
  name: 'fix',
  aliases: ['f'],
  description: 'Auto-fix issues in code (with confirmation)',
  usage: '/fix <file> [issue_id1,issue_id2,...]',
  requiresIPC: true,
  handler: handleFixCommand,
};
