/**
 * Analyze Command Handler
 *
 * Executes full Warden pipeline on a single file:
 * - Validates file exists and is .py
 * - Calls IPC bridge execute_pipeline()
 * - Displays formatted results with findings
 *
 * Requires IPC connection to Python backend.
 *
 * Reference: src/warden/tui/commands/analyze.py
 */

import { existsSync, statSync } from 'fs';
import { resolve } from 'path';
import { MessageType } from '../types/index.js';
import type { CommandHandlerContext } from './types.js';
import type { PipelineResult, FrameResult, Finding } from '../bridge/wardenClient.js';

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
 * Format pipeline status
 */
function formatStatus(status: string): string {
  const statusMap: Record<string, string> = {
    success: '✅ SUCCESS',
    failed: '❌ FAILED',
    partial: '⚠️  PARTIAL',
    running: '⏳ RUNNING',
  };
  return statusMap[status.toLowerCase()] || status.toUpperCase();
}

/**
 * Format frame result for display
 */
function formatFrameResult(frame: FrameResult): string {
  const status = frame.status === 'completed' ? '✅' : '❌';
  const blocker = frame.is_blocker ? '🔴' : '🟢';

  let result = `${status} ${blocker} **${frame.frame_name}** (\`${frame.frame_id}\`)\n`;
  result += `  - Duration: ${frame.duration.toFixed(2)}s\n`;
  result += `  - Issues Found: ${frame.issues_found}\n`;

  if (frame.issues_found > 0) {
    result += `  - Status: ${frame.status}\n`;
  }

  return result;
}

/**
 * Format finding for display
 */
function formatFinding(finding: Finding, index: number): string {
  let result = `\n### Finding #${index + 1}: ${formatSeverity(finding.severity)}\n\n`;
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
 * Display pipeline result in chat
 */
function displayPipelineResult(
  filePath: string,
  result: PipelineResult,
  addMessage: (msg: string, type: MessageType, markdown?: boolean) => void
): void {
  // Build result message
  let message = `# 📊 Analysis Results: \`${filePath}\`\n\n`;

  // Pipeline summary
  message += '## Pipeline Summary\n\n';
  message += `- **Status**: ${formatStatus(result.status)}\n`;
  message += `- **Duration**: ${result.duration.toFixed(2)}s\n`;
  message += `- **Total Frames**: ${result.total_frames}\n`;
  message += `- **Frames Passed**: ${result.frames_passed} ✅\n`;
  message += `- **Frames Failed**: ${result.frames_failed} ❌\n`;

  if (result.frames_skipped > 0) {
    message += `- **Frames Skipped**: ${result.frames_skipped} ⏭️\n`;
  }

  message += '\n';

  // Findings summary
  message += '## Findings Summary\n\n';
  message += `- **Total Findings**: ${result.total_findings}\n`;

  if (result.total_findings > 0) {
    message += `- **Critical**: ${result.critical_findings} 🔴\n`;
    message += `- **High**: ${result.high_findings} 🟠\n`;
    message += `- **Medium**: ${result.medium_findings} 🟡\n`;
    message += `- **Low**: ${result.low_findings} 🟢\n`;
  }

  message += '\n';

  // Frame results
  if (result.frame_results && result.frame_results.length > 0) {
    message += '## Frame Results\n\n';
    for (const frame of result.frame_results) {
      message += formatFrameResult(frame) + '\n';
    }
    message += '\n';
  }

  // Detailed findings
  if (result.total_findings > 0) {
    message += '## Detailed Findings\n';

    for (const frame of result.frame_results) {
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
    message += 'The file passed all validation frames successfully!\n';
  }

  // Display result
  addMessage(message, MessageType.SYSTEM, true);
}

/**
 * Handle /analyze command
 *
 * @param args - File path to analyze
 * @param context - Handler context
 */
export async function handleAnalyzeCommand(
  args: string,
  context: CommandHandlerContext
): Promise<void> {
  const { addMessage, client } = context;

  // Validate args
  if (!args || args.trim().length === 0) {
    addMessage(
      '❌ **Missing file path**\n\nUsage: `/analyze <file>`\n\nExample: `/analyze src/main.py`',
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

  const filePath = resolve(args.trim());

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
        'Please provide a file path, not a directory.\n' +
        'Use `/scan <path>` to analyze directories.',
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
        'Analysis may not work correctly for other file types.',
      MessageType.ERROR,
      true
    );
    // Continue anyway for now
  }

  // Start analysis
  addMessage(
    `🔍 **Analyzing**: \`${filePath}\`\n\n` +
      'Running full Warden pipeline (Analyze → Classify → Validate → Fortify → Clean)...',
    MessageType.SYSTEM,
    true
  );

  try {
    // Execute pipeline via IPC
    const result = await client.executePipeline(filePath);

    // Display results
    displayPipelineResult(filePath, result, addMessage);
  } catch (error) {
    addMessage(
      `❌ **Pipeline execution failed**\n\n` +
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
export const analyzeCommandMetadata = {
  name: 'analyze',
  aliases: ['a', 'check'],
  description: 'Analyze a code file with full Warden pipeline',
  usage: '/analyze <file>',
  requiresIPC: true,
  handler: handleAnalyzeCommand,
};
