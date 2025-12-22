/**
 * Scan Command Handler
 *
 * Scans a directory for code issues using the full Warden pipeline.
 * Features:
 * - Directory validation
 * - File discovery (.py files)
 * - Live progress tracking
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
  const { addMessage, client } = context;

  // Validate IPC client
  if (!client) {
    addMessage(
      'L **Backend not connected**\n\n' +
        'Scan requires IPC connection. Please start the backend:\n\n' +
        '```bash\n' +
        'python3 start_ipc_server.py\n' +
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
      `L **Path not found:** \`${scanPath}\`\n\n` +
        'Please check the path and try again.',
      MessageType.ERROR,
      true
    );
    return;
  }

  const stats = statSync(resolvedPath);
  if (!stats.isDirectory()) {
    addMessage(
      `L **Not a directory:** \`${scanPath}\`\n\n` +
        'Use `/analyze <file>` for single files.',
      MessageType.ERROR,
      true
    );
    return;
  }

  // Initial message
  addMessage(
    `= **Scanning:** \`${resolvedPath}\`\n\n` +
      'Finding Python files and running full pipeline...',
    MessageType.SYSTEM,
    true
  );

  try {
    // Discover Python files
    const pyFiles = discoverPythonFiles(resolvedPath);

    if (pyFiles.length === 0) {
      addMessage(
        `�  **No Python files found** in \`${scanPath}\``,
        MessageType.WARNING,
        true
      );
      return;
    }

    addMessage(
      `=� Found **${pyFiles.length} Python files**. Running pipeline...`,
      MessageType.SYSTEM,
      true
    );

    // Execute scan on all files
    const results = await executeScan(
      pyFiles,
      resolvedPath,
      addMessage,
      client
    );

    // Display aggregated summary
    displayScanSummary(resolvedPath, results, addMessage);
  } catch (error) {
    addMessage(
      `L **Scan failed**\n\n` +
        `Error: \`${error instanceof Error ? error.message : 'Unknown error'}\``,
      MessageType.ERROR,
      true
    );
  }
}

/**
 * Execute scan on all files with progress updates
 */
async function executeScan(
  files: string[],
  scanPath: string,
  addMessage: (msg: string, type: MessageType, markdown?: boolean) => void,
  client: any
): Promise<ScanFileResult[]> {
  const results: ScanFileResult[] = [];

  for (let i = 0; i < files.length; i++) {
    const file = files[i]!; // Non-null assertion - we know the array has elements
    const progress = `[${i + 1}/${files.length}]`;
    const relPath = relative(scanPath, file);

    addMessage(
      `� ${progress} Analyzing \`${relPath}\`...`,
      MessageType.SYSTEM,
      false
    );

    try {
      const result = await client.executePipeline(file);
      results.push({ file, result });

      const issueCount = result.total_findings || 0;
      const status = issueCount > 0 ? '�' : '';
      addMessage(
        `${status} ${progress} \`${relPath}\` - ${issueCount} issues`,
        MessageType.SYSTEM,
        true
      );
    } catch (error) {
      addMessage(
        `L ${progress} Failed: \`${relPath}\` - ${error instanceof Error ? error.message : 'Unknown error'}`,
        MessageType.ERROR,
        true
      );
    }
  }

  return results;
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
  let summary = '## =� Scan Summary\n\n';
  summary += `**Directory:** \`${scanPath}\`\n`;
  summary += `**Files Scanned:** ${results.length}\n`;
  summary += `**Total Issues:** ${totalIssues}\n\n`;

  if (totalIssues > 0) {
    summary += '### Issues by Severity\n\n';
    if (totalCritical > 0) summary += `=4 **Critical:** ${totalCritical}\n`;
    if (totalHigh > 0) summary += `=� **High:** ${totalHigh}\n`;
    if (totalMedium > 0) summary += `=� **Medium:** ${totalMedium}\n`;
    if (totalLow > 0) summary += `=� **Low:** ${totalLow}\n`;

    summary += '\n### Files with Issues\n\n';

    // Sort files by issue count (descending)
    fileIssues.sort((a, b) => b.count - a.count);

    for (const { file, count } of fileIssues.slice(0, 10)) {
      summary += `- \`${file}\`: ${count} issues\n`;
    }

    if (fileIssues.length > 10) {
      summary += `\n_...and ${fileIssues.length - 10} more files_\n`;
    }

    summary += '\n=� **Tip:** Use `/analyze <file>` to see details for specific files.';
  } else {
    summary += ' **No issues found!** Your code looks clean.\n';
  }

  addMessage(summary, MessageType.SUCCESS, true);
}

/**
 * Command metadata for registration
 */
export const scanCommandMetadata: CommandMetadata = {
  name: 'scan',
  aliases: ['s'],
  description: 'Scan a directory for code issues',
  usage: '/scan [path]',
  requiresIPC: true,
  handler: handleScanCommand,
};
