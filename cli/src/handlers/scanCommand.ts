/**
 * Scan Command Handler
 *
 * Scans a directory for code issues using the full Warden pipeline.
 * Features:
 * - Directory validation
 * - File discovery (.py files)
 * - Real-time streaming progress with UI updates
 * - Frame-by-frame progress tracking
 * - Aggregated results display
 * - IPC bridge integration
 *
 * Max 500 lines (RULE)
 *
 * Reference: src/warden/tui/commands/scan.py
 */

import { readdirSync, existsSync, statSync } from 'fs';
import { relative, join, dirname, resolve } from 'path';
import { MessageType } from '../types/index.js';
import type { CommandHandlerContext, CommandMetadata } from './types.js';
import type { PipelineResult } from '../bridge/wardenClient.js';
import type { FrameProgress } from '../components/FrameStatusDisplay.js';
import { resolvePath, getSearchLocations } from '../utils/pathResolver.js';
import { appEvents, AppEvent } from '../utils/events.js';
import {
  handleError,
  getErrorMessage,
  FileNotFoundError,
} from '../utils/errors.js';
import {
  createScanReport,
  saveReport,
  getReportsDirectory,
} from '../utils/reportGenerator.js';

/**
 * Result from scanning a single file
 */
interface ScanFileResult {
  file: string;
  result: PipelineResult;
}

/**
 * Handle /scan command
 *
 * Scans a directory for Python files and runs full pipeline on each
 *
 * @param args - Directory path to scan (default: current directory)
 * @param context - Handler context
 */
export async function handleScanCommand(
  args: string,
  context: CommandHandlerContext
): Promise<void> {
  const { addMessage, client, progressContext, lastScanPath } = context;

  // Validate IPC client (fail fast - Kural 4.1)
  if (!client) {
    addMessage(
      '❌ **Backend not connected**\n\n' +
        'Scan requires IPC connection. Please start the backend:\n\n' +
        '```bash\n' +
        './warden-ipc start\n' +
        '```',
      MessageType.ERROR,
      true
    );
    return;
  }

  // Parse directory path (default: current directory)
  const inputPath = args.trim() || process.cwd();

  // Resolve path with home expansion
  let resolvedPath = resolvePath(inputPath);

  // If not absolute, make it absolute
  if (!resolvedPath.startsWith('/')) {
    resolvedPath = resolve(resolvedPath);
  }

  // Check if path exists (Kural 4.1 - Fail fast with proper error)
  if (!existsSync(resolvedPath)) {
    const searchLocations = getSearchLocations(lastScanPath);
    const error = new FileNotFoundError(resolvedPath);

    // Emit scan failed event
    appEvents.emit(AppEvent.SCAN_FAILED, {
      path: inputPath,
      error: error.message,
    });

    addMessage(
      `❌ **Path not found:** \`${inputPath}\`\n\n` +
        '**Searched in:**\n' +
        searchLocations.map((loc) => `- ${loc}`).join('\n') +
        '\n\n💡 **Tip:** Provide a valid directory path or use `/analyze <file>` for single files.',
      MessageType.ERROR,
      true
    );
    return;
  }

  // If user provided a file path, scan its parent directory instead
  const stats = statSync(resolvedPath);
  if (!stats.isDirectory()) {
    const fileDir = dirname(resolvedPath);
    addMessage(
      `💡 **File detected:** \`${inputPath}\`\n\n` +
        `Scanning parent directory: \`${fileDir}\`\n\n` +
        `(Use \`/analyze ${inputPath}\` to analyze this single file)`,
      MessageType.SYSTEM,
      true
    );
    resolvedPath = fileDir;
  }

  // Initial message
  addMessage(
    `🔍 **Scanning:** \`${resolvedPath}\`\n\n` +
      'Finding Python files and running full pipeline...',
    MessageType.SYSTEM,
    true
  );

  try {
    // Discover Python files
    const pyFiles = discoverPythonFiles(resolvedPath);

    if (pyFiles.length === 0) {
      addMessage(
        `⚠️  **No Python files found** in \`${resolvedPath}\``,
        MessageType.WARNING,
        true
      );

      // Emit scan failed event (no files found)
      appEvents.emit(AppEvent.SCAN_FAILED, {
        path: resolvedPath,
        error: 'No Python files found',
      });
      return;
    }

    addMessage(
      `📊 Found **${pyFiles.length} Python files**. Running pipeline with real-time progress UI...`,
      MessageType.SYSTEM,
      true
    );

    // Emit scan started event
    appEvents.emit(AppEvent.SCAN_STARTED, {
      path: resolvedPath,
      fileCount: pyFiles.length,
    });

    // Track start time for duration calculation
    const startTime = Date.now();

    // Execute scan with streaming progress
    const results = await executeScanWithProgress(
      pyFiles,
      resolvedPath,
      client,
      progressContext
    );

    // Calculate total duration and issues
    const duration = (Date.now() - startTime) / 1000;
    const totalIssues = results.reduce((sum, r) => sum + (r.result.total_findings || 0), 0);

    // Check if scan was cancelled
    if (progressContext.progress.isCancelled) {
      // Emit scan failed event with cancellation info
      appEvents.emit(AppEvent.SCAN_FAILED, {
        path: resolvedPath,
        error: 'Scan cancelled by user',
      });

      // Save partial report for cancelled scan
      try {
        const report = createScanReport(resolvedPath, results, {
          totalFiles: pyFiles.length,
          duration,
          status: 'cancelled',
        });

        const reportsDir = getReportsDirectory(resolvedPath);
        const { json, markdown } = saveReport(report, reportsDir);

        addMessage(
          `⚠️  **Scan Cancelled**\n\n` +
            `**Directory:** \`${resolvedPath}\`\n` +
            `**Files Scanned:** ${results.length}/${pyFiles.length}\n` +
            `**Duration:** ${duration.toFixed(1)}s\n\n` +
            `📁 **Partial report saved:**\n` +
            `- JSON: \`${json}\`\n` +
            `- Summary: \`${markdown}\`\n\n` +
            `Use \`/scan ${resolvedPath}\` to restart.`,
          MessageType.SYSTEM,
          true
        );
      } catch (error) {
        // Fallback if report saving fails
        addMessage(
          `⚠️  **Scan Cancelled**\n\n` +
            `**Directory:** \`${resolvedPath}\`\n` +
            `**Files Scanned:** ${results.length}/${pyFiles.length}\n` +
            `**Duration:** ${duration.toFixed(1)}s\n\n` +
            `Partial results available. Use \`/scan ${resolvedPath}\` to restart.`,
          MessageType.SYSTEM,
          true
        );
      }
      return;
    }

    // Emit scan completed event
    appEvents.emit(AppEvent.SCAN_COMPLETED, {
      path: resolvedPath,
      duration,
      issuesFound: totalIssues,
    });

    // Generate and save report
    try {
      const report = createScanReport(resolvedPath, results, {
        totalFiles: pyFiles.length,
        duration,
        status: 'completed',
      });

      const reportsDir = getReportsDirectory(resolvedPath);
      const { json, markdown } = saveReport(report, reportsDir);

      addMessage(
        `📁 **Reports saved:**\n` +
          `- JSON: \`${json}\`\n` +
          `- Summary: \`${markdown}\``,
        MessageType.SYSTEM,
        true
      );
    } catch (error) {
      // Report saving failed - log but don't fail the scan
      console.error('[Scan] Failed to save report:', error);
      addMessage(
        '⚠️  Report generation failed (scan results still available above)',
        MessageType.WARNING,
        true
      );
    }

    // Display aggregated summary
    displayScanSummary(resolvedPath, results, addMessage);
  } catch (error) {
    // Enhanced error handling (Kural 4.4)
    const errorMsg = getErrorMessage(error);

    // Log error with context
    handleError(error, {
      component: 'scanCommand',
      operation: 'executeScan',
      metadata: { path: resolvedPath },
    });

    // Emit scan failed event
    appEvents.emit(AppEvent.SCAN_FAILED, {
      path: resolvedPath,
      error: errorMsg,
    });

    // Update progress UI
    progressContext.failScan(errorMsg);

    // Display user-friendly error
    addMessage(
      `❌ **Scan failed**\n\n` +
        `Error: \`${errorMsg}\`\n\n` +
        '**Troubleshooting:**\n' +
        '- Check if IPC server is running\n' +
        '- Verify file permissions\n' +
        '- Try `/status` to check connection',
      MessageType.ERROR,
      true
    );
  }
}

/**
 * Execute scan with real-time streaming progress UI
 *
 * This function:
 * 1. Gets available frames from backend
 * 2. Initializes progress UI with frame list
 * 3. Streams events from backend
 * 4. Updates UI incrementally as events arrive
 * 5. Completes scan when done
 */
async function executeScanWithProgress(
  files: string[],
  scanPath: string,
  client: any,
  progressContext: any
): Promise<ScanFileResult[]> {
  const results: ScanFileResult[] = [];

  // Get available frames from backend
  let availableFrames: any[] = [];
  try {
    availableFrames = await client.getAvailableFrames();
  } catch (error) {
    // If we can't get frames, continue without progress UI
    console.error('Failed to get frames:', error);
  }

  // Initialize frame progress list
  const frameProgressList: FrameProgress[] = availableFrames.map((frame) => ({
    id: frame.id,
    name: frame.name,
    status: 'pending' as const,
  }));

  // Start scan with progress UI
  progressContext.startScan(files.length, frameProgressList);

  try {
    for (let i = 0; i < files.length; i++) {
      // Check for cancellation before processing each file
      if (progressContext.progress.isCancelled) {
        console.log('[Scan] Cancelled by user, stopping...');
        break;
      }

      const file = files[i]!;
      const relPath = relative(scanPath, file);

      // Update files scanned count
      progressContext.updateProgress({ filesScanned: i });

      let lastResult: any = null;

      try {
        // Stream events for this file
        for await (const event of client.executePipelineStream(file)) {
          // Check for cancellation during streaming
          if (progressContext.progress.isCancelled) {
            console.log('[Scan] Cancelled during file processing');
            break;
          }

          handleStreamingEvent(event, relPath, progressContext);

          // Save final result
          if (event.type === 'result') {
            lastResult = event.data;
          }
        }

        // Add result (if scan wasn't cancelled)
        if (lastResult && !progressContext.progress.isCancelled) {
          results.push({ file, result: lastResult });

          // Update issues count
          const totalIssues = lastResult.total_findings || 0;
          progressContext.updateProgress({
            issuesFound: (progressContext.progress.issuesFound || 0) + totalIssues,
          });
        }
      } catch (error) {
        console.error(`Failed to scan ${relPath}:`, error);
        // Continue with next file
      }
    }

    // Update final file count (only if not cancelled)
    if (!progressContext.progress.isCancelled) {
      progressContext.updateProgress({ filesScanned: files.length });
      // Complete scan
      progressContext.completeScan();
    }
    // If cancelled, status is already set to 'cancelled' by cancelScan()
  } catch (error) {
    // Don't override cancel status with error status
    if (!progressContext.progress.isCancelled) {
      progressContext.failScan(error instanceof Error ? error.message : 'Unknown error');
    }
    throw error;
  }

  return results;
}

/**
 * Handle streaming event from backend
 *
 * Maps backend events to UI updates
 */
function handleStreamingEvent(
  event: any,
  _filePath: string,
  progressContext: any
): void {
  if (event.type !== 'progress') {
    return;
  }

  const { event: eventName, data } = event;

  switch (eventName) {
    case 'pipeline_started':
      // Reset all frames to pending
      progressContext.progress.frames.forEach((frame: FrameProgress) => {
        progressContext.updateFrame(frame.id, { status: 'pending' });
      });
      break;

    case 'frame_started':
      {
        const frameId = data.frame_id;
        const frameName = data.frame_name;

        // Update frame to running
        progressContext.updateFrame(frameId, {
          status: 'running',
        });

        // Update current frame name
        progressContext.updateProgress({ currentFrame: frameName });
      }
      break;

    case 'frame_completed':
      {
        const frameId = data.frame_id;
        const issuesFound = data.issues_found || 0;
        const duration = data.duration || 0;
        const status = data.status || 'success';

        // Update frame to completed
        progressContext.updateFrame(frameId, {
          status: status === 'passed' ? 'success' : 'error',
          issuesFound,
          duration: Math.round(duration * 1000), // Convert to ms
        });
      }
      break;

    case 'pipeline_completed':
      // All frames completed - no action needed (completeScan will be called)
      break;

    default:
      // Unknown event - ignore
      break;
  }
}

/**
 * Discover all Python files in directory (recursively)
 */
function discoverPythonFiles(dirPath: string): string[] {
  const files: string[] = [];

  function walk(dir: string): void {
    try {
      const entries = readdirSync(dir, { withFileTypes: true });

      for (const entry of entries) {
        const fullPath = join(dir, entry.name);

        // Skip ignored patterns
        if (shouldIgnore(entry.name)) {
          continue;
        }

        if (entry.isDirectory()) {
          walk(fullPath);
        } else if (entry.isFile() && entry.name.endsWith('.py')) {
          files.push(fullPath);
        }
      }
    } catch (error) {
      // Skip directories we can't read
      return;
    }
  }

  walk(dirPath);
  return files;
}

/**
 * Check if path should be ignored
 */
function shouldIgnore(name: string): boolean {
  const ignorePatterns = [
    'node_modules',
    '.git',
    '__pycache__',
    '.venv',
    'venv',
    '.pytest_cache',
    '.mypy_cache',
    '.ruff_cache',
    'dist',
    'build',
    '.eggs',
  ];

  return ignorePatterns.includes(name) || name.endsWith('.egg-info');
}

/**
 * Display scan summary
 */
function displayScanSummary(
  scanPath: string,
  results: ScanFileResult[],
  addMessage: (content: string, type: MessageType, markdown: boolean) => void
): void {
  // Calculate totals
  let totalIssues = 0;
  let totalCritical = 0;
  let totalHigh = 0;
  let totalMedium = 0;
  let totalLow = 0;
  const fileIssues: Array<{ file: string; count: number }> = [];

  for (const { file, result } of results) {
    const count = result.total_findings || 0;

    if (count > 0) {
      const relPath = relative(scanPath, file);
      fileIssues.push({
        file: relPath,
        count,
      });
    }

    totalIssues += count;
    totalCritical += result.critical_findings || 0;
    totalHigh += result.high_findings || 0;
    totalMedium += result.medium_findings || 0;
    totalLow += result.low_findings || 0;
  }

  // Build summary message
  let summary = '## 📊 Scan Summary\n\n';
  summary += `**Directory:** \`${scanPath}\`\n`;
  summary += `**Files Scanned:** ${results.length}\n`;
  summary += `**Total Issues:** ${totalIssues}\n\n`;

  if (totalIssues > 0) {
    summary += '### Issues by Severity\n\n';
    if (totalCritical > 0) summary += `🔴 **Critical:** ${totalCritical}\n`;
    if (totalHigh > 0) summary += `🟠 **High:** ${totalHigh}\n`;
    if (totalMedium > 0) summary += `🟡 **Medium:** ${totalMedium}\n`;
    if (totalLow > 0) summary += `🟢 **Low:** ${totalLow}\n`;

    summary += '\n### Files with Issues\n\n';

    // Sort files by issue count (descending)
    fileIssues.sort((a, b) => b.count - a.count);

    for (const { file, count } of fileIssues.slice(0, 10)) {
      summary += `- \`${file}\`: ${count} issues\n`;
    }

    if (fileIssues.length > 10) {
      summary += `\n_...and ${fileIssues.length - 10} more files_\n`;
    }

    summary += '\n💡 **Tip:** Use `/analyze <file>` to see details for specific files.';
  } else {
    summary += '✅ **No issues found!** Your code looks clean.\n';
  }

  addMessage(summary, MessageType.SUCCESS, true);
}

/**
 * Command metadata for registration
 */
export const scanCommandMetadata: CommandMetadata = {
  name: 'scan',
  aliases: ['s'],
  description: 'Scan a directory for code issues with real-time progress',
  usage: '/scan [path]',
  requiresIPC: true,
  handler: handleScanCommand,
};
