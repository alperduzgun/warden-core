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

import { existsSync } from 'fs';
import { resolve, join, dirname } from 'path';
import { MessageType } from '../types/index.js';
import type { CommandHandlerContext } from './types.js';
import type { PipelineResult, FrameResult, Finding } from '../bridge/wardenClient.js';
import { resolvePath, isFile, hasValidExtension, getSearchLocations, COMMON_SEARCH_DIRS } from '../utils/pathResolver.js';
import {
  ValidationError,
  getErrorMessage,
  handleError,
  FileNotFoundError,
  IPCConnectionError,
} from '../utils/errors.js';
import { appEvents, AppEvent } from '../utils/events.js';

/**
 * Smart file search: tries multiple locations
 * 1. Current directory (relative or absolute)
 * 2. Common subdirectories (examples/, src/, tests/)
 * 3. Parent directories (walk up)
 * 4. Last scanned directory (if available)
 *
 * @param inputPath - File path to search
 * @param lastScanPath - Last scanned directory
 * @returns Resolved file path or null
 */
function findFile(inputPath: string, lastScanPath?: string): string | null {
  // 1. Try resolving with home expansion and normalization
  const resolved = resolvePath(inputPath);

  if (existsSync(resolved)) {
    return resolve(resolved);
  }

  // 2. Try common subdirectories
  const cwd = process.cwd();
  for (const dir of COMMON_SEARCH_DIRS) {
    const testPath = join(cwd, dir, inputPath);
    if (existsSync(testPath)) {
      return testPath;
    }
  }

  // 3. Try parent directories (walk up to root)
  let currentDir = cwd;
  for (let i = 0; i < 5; i++) {
    const testPath = join(currentDir, inputPath);
    if (existsSync(testPath)) {
      return testPath;
    }
    const parentDir = dirname(currentDir);
    if (parentDir === currentDir) break; // Reached root
    currentDir = parentDir;
  }

  // 4. Try last scanned directory
  if (lastScanPath) {
    const scanPath = join(lastScanPath, inputPath);
    if (existsSync(scanPath)) {
      return scanPath;
    }
  }

  return null;
}

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
function formatStatus(status: string | number | unknown): string {
  // Handle enum values from backend (0, 1, 2, etc.)
  if (typeof status === 'number') {
    const enumMap: Record<number, string> = {
      0: '⏳ RUNNING',
      1: '❌ FAILED',
      2: '✅ SUCCESS',
      3: '⚠️  PARTIAL',
    };
    return enumMap[status] || `Status ${status}`;
  }

  // Handle string status
  if (typeof status === 'string') {
    const statusMap: Record<string, string> = {
      success: '✅ SUCCESS',
      failed: '❌ FAILED',
      partial: '⚠️  PARTIAL',
      running: '⏳ RUNNING',
    };
    return statusMap[status.toLowerCase()] || status.toUpperCase();
  }

  // Handle unknown types safely
  return status === null || status === undefined ? 'UNKNOWN' : String(status).toUpperCase();
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

  // Only show location if line number is valid (not null/undefined)
  if (finding.line !== undefined && finding.line !== null) {
    result += `**Location**: Line ${finding.line}`;
    if (finding.column !== undefined && finding.column !== null) {
      result += `, Column ${finding.column}`;
    }
    result += '\n\n';
  }

  if (finding.code) {
    // Clean up code: backend might already include backticks
    let code = finding.code.trim();

    // Remove existing markdown code block wrapper if present
    if (code.startsWith('```') || code.startsWith('`')) {
      code = code.replace(/^`+(\w+)?\n?/, '').replace(/\n?`+$/, '').trim();
    }

    result += `**Code**:\n\`\`\`python\n${code}\n\`\`\`\n`;
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
  const { addMessage, client, lastScanPath, progressContext } = context;

  // Validate args (fail fast - Kural 4.1)
  if (!args || args.trim().length === 0) {
    throw new ValidationError('Missing file path. Usage: /analyze <file>');
  }

  // Extract input path early
  const inputPath = args.trim();

  // Validate IPC client (fail fast - Kural 4.1)
  if (!client) {
    const error = new IPCConnectionError();

    // Emit analysis failed event
    appEvents.emit(AppEvent.ANALYSIS_FAILED, {
      file: inputPath,
      error: error.message,
    });

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

  // Smart file search (path is already cleaned in InputBox)
  const filePath = findFile(inputPath, lastScanPath);

  // Check file exists
  if (!filePath) {
    const searchLocations = getSearchLocations(lastScanPath);
    const error = new FileNotFoundError(inputPath);

    // Emit analysis failed event
    appEvents.emit(AppEvent.ANALYSIS_FAILED, {
      file: inputPath,
      error: error.message,
    });

    const errorMsg =
      `❌ **File not found**: \`${inputPath}\`\n\n` +
      '**Searched in:**\n' +
      searchLocations.map((loc) => `- ${loc}`).join('\n') +
      '\n\n💡 **Tip:** Try `/scan examples/` first, then copy-paste paths from summary.';

    addMessage(errorMsg, MessageType.ERROR, true);
    return;
  }

  // Check if it's a file (not directory)
  if (!isFile(filePath)) {
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
  if (!hasValidExtension(filePath, ['.py'])) {
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

  // Emit analysis started event
  appEvents.emit(AppEvent.ANALYSIS_STARTED, {
    file: filePath,
  });

  // Track start time
  const startTime = Date.now();

  try {
    // Execute pipeline via IPC
    const result = await client.executePipeline(filePath);

    // Check if cancelled (analyze is typically fast, but still check)
    if (progressContext?.progress.isCancelled) {
      addMessage('⚠️  Analysis cancelled by user', MessageType.SYSTEM);
      appEvents.emit(AppEvent.ANALYSIS_FAILED, {
        file: filePath,
        error: 'Cancelled by user',
      });
      return;
    }

    // Calculate duration
    const duration = (Date.now() - startTime) / 1000;
    const issuesFound = result.total_findings || 0;

    // Emit analysis completed event
    appEvents.emit(AppEvent.ANALYSIS_COMPLETED, {
      file: filePath,
      duration,
      issuesFound,
    });

    // Display results
    displayPipelineResult(filePath, result, addMessage);
  } catch (error) {
    // Enhanced error handling (Kural 4.4)
    const errorMessage = getErrorMessage(error);

    // Log error with context
    handleError(error, {
      component: 'analyzeCommand',
      operation: 'executePipeline',
      metadata: { file: filePath },
    });

    // Emit analysis failed event
    appEvents.emit(AppEvent.ANALYSIS_FAILED, {
      file: filePath,
      error: errorMessage,
    });

    addMessage(
      `❌ **Pipeline execution failed**\n\n` +
        `Error: \`${errorMessage}\`\n\n` +
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
