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

import { existsSync, statSync, readdirSync } from 'fs';
import { resolve, relative, join } from 'path';
import { MessageType } from '../types/index.js';
import type { CommandHandlerContext, CommandMetadata } from './types.js';
import type { PipelineResult } from '../bridge/wardenClient.js';
import type { FrameProgress } from '../components/FrameStatusDisplay.js';

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
  const { addMessage, client, progressContext } = context;

  // Validate IPC client
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
  const scanPath = args.trim() || process.cwd();
  const resolvedPath = resolve(scanPath);

  // Validate directory exists
  if (!existsSync(resolvedPath)) {
    addMessage(
      `❌ **Path not found:** \`${scanPath}\`\n\n` +
        'Please check the path and try again.',
      MessageType.ERROR,
      true
    );
    return;
  }

  const stats = statSync(resolvedPath);
  if (!stats.isDirectory()) {
    addMessage(
      `❌ **Not a directory:** \`${scanPath}\`\n\n` +
        'Use `/analyze <file>` for single files.',
      MessageType.ERROR,
      true
    );
    return;
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
        `⚠️  **No Python files found** in \`${scanPath}\``,
        MessageType.WARNING,
        true
      );
      return;
    }

    addMessage(
      `📊 Found **${pyFiles.length} Python files**. Running pipeline with real-time progress UI...`,
      MessageType.SYSTEM,
      true
    );

    // Execute scan with streaming progress
    const results = await executeScanWithProgress(
      pyFiles,
      resolvedPath,
      client,
      progressContext
    );

    // Display aggregated summary
    displayScanSummary(resolvedPath, results, addMessage);
  } catch (error) {
    progressContext.failScan(error instanceof Error ? error.message : 'Unknown error');
    addMessage(
      `❌ **Scan failed**\n\n` +
        `Error: \`${error instanceof Error ? error.message : 'Unknown error'}\``,
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
      const file = files[i]!;
      const relPath = relative(scanPath, file);

      // Update files scanned count
      progressContext.updateProgress({ filesScanned: i });

      let lastResult: any = null;

      try {
        // Stream events for this file
        for await (const event of client.executePipelineStream(file)) {
          handleStreamingEvent(event, relPath, progressContext);

          // Save final result
          if (event.type === 'result') {
            lastResult = event.data;
          }
        }

        // Add result
        if (lastResult) {
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

    // Update final file count
    progressContext.updateProgress({ filesScanned: files.length });

    // Complete scan
    progressContext.completeScan();
  } catch (error) {
    progressContext.failScan(error instanceof Error ? error.message : 'Unknown error');
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
