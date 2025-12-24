/**
 * Validate Command Handler
 *
 * Runs specific validation frames on a file:
 * - User can select which frames to run
 * - Displays frame-specific results
 * - Lighter than full pipeline analysis
 *
 * Requires IPC connection to Python backend.
 *
 * Reference: src/warden/tui/commands/validate.py
 */

import { existsSync, statSync } from 'fs';
import { resolve } from 'path';
import { MessageType } from '../types/index.js';
import type { CommandHandlerContext } from './types.js';
import type { FrameResult, Finding, FrameInfo } from '../bridge/wardenClient.js';

/**
 * Format severity with emoji
 */
function formatSeverity(severity: string): string {
  const severityMap: Record<string, string> = {
    critical: '🔴 CRITICAL',
    high: '🟠 HIGH',
    medium: '🟡 MEDIUM',
    low: '🟢 LOW',
    info: '🔵 INFO',
  };
  return severityMap[severity.toLowerCase()] || severity.toUpperCase();
}

/**
 * Format frame result for display
 */
function formatFrameResult(frame: FrameResult): string {
  const status = frame.status === 'completed' ? '✅' : '❌';
  const blocker = frame.is_blocker ? '🔴' : '🟢';

  let result = `### ${status} ${blocker} ${frame.frame_name}\n\n`;
  result += `- **Frame ID**: \`${frame.frame_id}\`\n`;
  result += `- **Duration**: ${frame.duration.toFixed(2)}s\n`;
  result += `- **Issues Found**: ${frame.issues_found}\n`;
  result += `- **Status**: ${frame.status}\n`;

  return result;
}

/**
 * Format finding for display
 */
function formatFinding(finding: Finding, index: number): string {
  let result = `\n#### Finding #${index + 1}: ${formatSeverity(finding.severity)}\n\n`;
  result += `**Message**: ${finding.message}\n\n`;

  if (finding.line !== undefined) {
    result += `**Location**: Line ${finding.line}`;
    if (finding.column !== undefined) {
      result += `, Column ${finding.column}`;
    }
    result += '\n\n';
  }

  if (finding.code) {
    result += `**Code**:\n\`\`\`python\n${finding.code}\n\`\`\`\n`;
  }

  return result;
}

/**
 * Parse frame selection from args
 * Supports: "security,orphan" or "security orphan" or just "security"
 */
function parseFrameSelection(frameArg: string): string[] {
  if (!frameArg) return [];

  // Split by comma or space
  return frameArg
    .split(/[,\s]+/)
    .map(f => f.trim().toLowerCase())
    .filter(f => f.length > 0);
}

/**
 * Display validation results
 */
function displayValidationResults(
  filePath: string,
  results: FrameResult[],
  requestedFrames: string[],
  addMessage: (msg: string, type: MessageType, markdown?: boolean) => void
): void {
  let message = `# 🎯 Validation Results: \`${filePath}\`\n\n`;

  // Summary
  message += '## Summary\n\n';
  message += `- **Frames Requested**: ${requestedFrames.length > 0 ? requestedFrames.join(', ') : 'all'}\n`;
  message += `- **Frames Executed**: ${results.length}\n`;

  const passedFrames = results.filter(f => f.status === 'completed' && f.issues_found === 0).length;
  const failedFrames = results.filter(f => f.issues_found > 0).length;

  message += `- **Passed**: ${passedFrames} ✅\n`;
  message += `- **Failed**: ${failedFrames} ❌\n`;

  const totalFindings = results.reduce((sum, r) => sum + r.issues_found, 0);
  message += `- **Total Findings**: ${totalFindings}\n\n`;

  // Frame results
  message += '## Frame Results\n\n';
  for (const frame of results) {
    message += formatFrameResult(frame) + '\n';
  }

  // Detailed findings
  if (totalFindings > 0) {
    message += '## Detailed Findings\n';

    for (const frame of results) {
      if (frame.findings && frame.findings.length > 0) {
        message += `\n### ${frame.frame_name}\n`;
        for (let i = 0; i < frame.findings.length; i++) {
          const finding = frame.findings[i];
          if (finding) {
            message += formatFinding(finding, i);
          }
        }
      }
    }
  } else {
    message += '## ✨ No Issues Found\n\n';
    message += 'All validation frames passed successfully!\n';
  }

  addMessage(message, MessageType.SYSTEM, true);
}

/**
 * Display available frames
 */
function displayAvailableFrames(
  frames: FrameInfo[],
  addMessage: (msg: string, type: MessageType, markdown?: boolean) => void
): void {
  let message = '# 📋 Available Validation Frames\n\n';
  message += `Total: ${frames.length} frames\n\n`;

  // Group by priority
  const byPriority: Record<string, FrameInfo[]> = {};
  for (const frame of frames) {
    const priority = frame.priority || 'medium';
    if (!byPriority[priority]) {
      byPriority[priority] = [];
    }
    byPriority[priority].push(frame);
  }

  // Display by priority
  for (const priority of ['critical', 'high', 'medium', 'low']) {
    const priorityFrames = byPriority[priority];
    if (!priorityFrames || priorityFrames.length === 0) continue;

    const emoji = priority === 'critical' ? '🔴' :
                  priority === 'high' ? '🟠' :
                  priority === 'medium' ? '🟡' : '🟢';

    message += `## ${emoji} ${priority.toUpperCase()} Priority\n\n`;

    for (const frame of priorityFrames) {
      const blocker = frame.is_blocker ? '🚨 BLOCKER' : '';
      message += `### \`${frame.id}\` - ${frame.name} ${blocker}\n`;
      message += `${frame.description}\n`;

      if (frame.tags && frame.tags.length > 0) {
        message += `\n**Tags**: ${frame.tags.join(', ')}\n`;
      }

      message += '\n';
    }
  }

  message += '\n---\n\n';
  message += '**Usage**: `/validate <file> [frame1,frame2,...]`\n\n';
  message += 'Examples:\n';
  message += '- `/validate file.py` - Run all frames\n';
  message += '- `/validate file.py security` - Run only security frame\n';
  message += '- `/validate file.py security,orphan` - Run security and orphan frames\n';

  addMessage(message, MessageType.SYSTEM, true);
}

/**
 * Handle /validate command
 *
 * @param args - File path and optional frame selection
 * @param context - Handler context
 */
export async function handleValidateCommand(
  args: string,
  context: CommandHandlerContext
): Promise<void> {
  const { addMessage, client } = context;

  // Special case: list available frames
  if (args.trim() === '--list' || args.trim() === '-l') {
    if (!client) {
      addMessage(
        '❌ **IPC connection not available**\n\n' +
          'Cannot list frames without backend connection.',
        MessageType.ERROR,
        true
      );
      return;
    }

    try {
      const frames = await client.getAvailableFrames();
      displayAvailableFrames(frames, addMessage);
    } catch (error) {
      addMessage(
        `❌ **Failed to get available frames**\n\n` +
          `Error: \`${error instanceof Error ? error.message : 'Unknown error'}\``,
        MessageType.ERROR,
        true
      );
    }
    return;
  }

  // Parse args: <file> [frame1,frame2,...]
  const parts = args.trim().split(/\s+/).filter(p => p.length > 0);

  if (parts.length === 0 || !parts[0]) {
    addMessage(
      '❌ **Missing file path**\n\n' +
        'Usage: `/validate <file> [frame1,frame2,...]`\n\n' +
        'Examples:\n' +
        '- `/validate file.py` - Interactive frame picker\n' +
        '- `/validate file.py security` - Run only security frame\n' +
        '- `/validate file.py security,orphan` - Run multiple frames\n' +
        '- `/validate --list` - Show available frames',
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
  const frameSelection = parts.length > 1 ? parseFrameSelection(parts.slice(1).join(' ')) : [];

  // Check file exists BEFORE showing frame picker
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
        'Validation may not work correctly for other file types.',
      MessageType.ERROR,
      true
    );
    // Don't return - continue with validation
  }

  // If no frames specified and showFramePicker is available, show interactive picker
  if (frameSelection.length === 0 && context.showFramePicker) {
    try {
      // Get available frames from backend
      const frames = await client.getAvailableFrames();

      if (frames.length === 0) {
        addMessage(
          '⚠️  **No validation frames available**\n\n' +
            'The backend did not return any validation frames.',
          MessageType.ERROR,
          true
        );
        return;
      }

      // Show interactive frame picker
      context.showFramePicker(filePath, frames);
      return; // Frame picker will handle the rest
    } catch (error) {
      addMessage(
        `❌ **Failed to get available frames**\n\n` +
          `Error: \`${error instanceof Error ? error.message : 'Unknown error'}\``,
        MessageType.ERROR,
        true
      );
      return;
    }
  }

  // Start validation
  const framesMsg = frameSelection.length > 0
    ? `frames: ${frameSelection.join(', ')}`
    : 'all frames';

  addMessage(
    `🎯 **Validating**: \`${filePath}\`\n\n` +
      `Running ${framesMsg}...`,
    MessageType.SYSTEM,
    true
  );

  try {
    // Execute validation via IPC
    // Note: We need to add validateFile method to WardenClient
    // For now, use executePipeline and filter results
    const result = await client.executePipeline(filePath);

    // Filter results by requested frames if specified
    let frameResults = result.frame_results;
    if (frameSelection.length > 0) {
      frameResults = frameResults.filter(frame => {
        const frameId = frame.frame_id.toLowerCase();
        const frameName = frame.frame_name.toLowerCase();
        return frameSelection.some(sel =>
          frameId.includes(sel) || frameName.includes(sel)
        );
      });
    }

    // Display results
    displayValidationResults(filePath, frameResults, frameSelection, addMessage);
  } catch (error) {
    addMessage(
      `❌ **Validation failed**\n\n` +
        `Error: \`${error instanceof Error ? error.message : 'Unknown error'}\`\n\n` +
        '**Troubleshooting:**\n' +
        '1. Check if the file is valid Python code\n' +
        '2. Ensure IPC server is running\n' +
        '3. Check server logs for details\n' +
        '4. Try `/status` to verify connection',
      MessageType.ERROR,
      true
    );
  }
}

/**
 * Command metadata for registration
 */
export const validateCommandMetadata = {
  name: 'validate',
  aliases: ['v'],
  description: 'Run specific validation frames on a file',
  usage: '/validate <file> [frame1,frame2,...]',
  requiresIPC: true,
  handler: handleValidateCommand,
};
