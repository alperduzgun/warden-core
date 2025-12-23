/**
 * Report Generator
 *
 * Generates and saves scan/analysis reports in multiple formats.
 * Follows Warden Core rules: KISS, DRY, fail fast, type safety.
 */

import { writeFileSync, mkdirSync } from 'fs';
import { join } from 'path';
import type { PipelineResult } from '../bridge/wardenClient.js';

/**
 * Scan report metadata
 */
export interface ScanReport {
  /** Report ID (timestamp-based) */
  id: string;

  /** Report timestamp */
  timestamp: Date;

  /** Scan target path */
  path: string;

  /** Total files scanned */
  filesScanned: number;

  /** Total files found */
  totalFiles: number;

  /** Scan duration in seconds */
  duration: number;

  /** Total issues found */
  totalIssues: number;

  /** Issues by severity */
  severity: {
    critical: number;
    high: number;
    medium: number;
    low: number;
  };

  /** Per-file results */
  files: Array<{
    path: string;
    relativePath: string;
    issues: number;
    critical: number;
    high: number;
    medium: number;
    low: number;
    frames: Array<{
      id: string;
      name: string;
      status: string;
      duration: number;
      issues: number;
    }>;
  }>;

  /** Scan status */
  status: 'completed' | 'cancelled' | 'failed';

  /** Error message if failed */
  error?: string;
}

/**
 * Generate report ID from timestamp
 */
function generateReportId(): string {
  const now = new Date();
  return `scan-${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}-${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`;
}

/**
 * Create scan report from results
 */
export function createScanReport(
  scanPath: string,
  results: Array<{ file: string; result: PipelineResult }>,
  options: {
    totalFiles: number;
    duration: number;
    status: 'completed' | 'cancelled' | 'failed';
    error?: string;
  }
): ScanReport {
  // Calculate totals
  let totalIssues = 0;
  let totalCritical = 0;
  let totalHigh = 0;
  let totalMedium = 0;
  let totalLow = 0;

  const fileResults = results.map(({ file, result }) => {
    const issues = result.total_findings || 0;
    const critical = result.critical_findings || 0;
    const high = result.high_findings || 0;
    const medium = result.medium_findings || 0;
    const low = result.low_findings || 0;

    totalIssues += issues;
    totalCritical += critical;
    totalHigh += high;
    totalMedium += medium;
    totalLow += low;

    // Extract frame info
    const frames = (result.frame_results || []).map((frame) => ({
      id: frame.frame_id,
      name: frame.frame_name,
      status: frame.status,
      duration: frame.duration,
      issues: frame.issues_found || 0,
    }));

    return {
      path: file,
      relativePath: file.replace(scanPath, '.'),
      issues,
      critical,
      high,
      medium,
      low,
      frames,
    };
  });

  const report: ScanReport = {
    id: generateReportId(),
    timestamp: new Date(),
    path: scanPath,
    filesScanned: results.length,
    totalFiles: options.totalFiles,
    duration: options.duration,
    totalIssues,
    severity: {
      critical: totalCritical,
      high: totalHigh,
      medium: totalMedium,
      low: totalLow,
    },
    files: fileResults,
    status: options.status,
  };

  if (options.error) {
    report.error = options.error;
  }

  return report;
}

/**
 * Save report to JSON file
 */
export function saveReportJSON(report: ScanReport, outputDir: string): string {
  // Ensure output directory exists
  mkdirSync(outputDir, { recursive: true });

  const filename = `${report.id}.json`;
  const filepath = join(outputDir, filename);

  // Write JSON with pretty formatting
  const json = JSON.stringify(report, null, 2);
  writeFileSync(filepath, json, 'utf-8');

  return filepath;
}

/**
 * Generate markdown summary from report
 */
export function generateMarkdownSummary(report: ScanReport): string {
  let md = `# Warden Scan Report\n\n`;
  md += `**Report ID:** \`${report.id}\`\n`;
  md += `**Timestamp:** ${report.timestamp.toISOString()}\n`;
  md += `**Status:** ${report.status.toUpperCase()}\n\n`;

  md += `---\n\n`;

  // Summary
  md += `## Summary\n\n`;
  md += `- **Directory:** \`${report.path}\`\n`;
  md += `- **Files Scanned:** ${report.filesScanned}/${report.totalFiles}\n`;
  md += `- **Duration:** ${report.duration.toFixed(1)}s\n`;
  md += `- **Total Issues:** ${report.totalIssues}\n\n`;

  // Severity breakdown
  if (report.totalIssues > 0) {
    md += `### Issues by Severity\n\n`;
    if (report.severity.critical > 0) md += `- 🔴 **Critical:** ${report.severity.critical}\n`;
    if (report.severity.high > 0) md += `- 🟠 **High:** ${report.severity.high}\n`;
    if (report.severity.medium > 0) md += `- 🟡 **Medium:** ${report.severity.medium}\n`;
    if (report.severity.low > 0) md += `- 🟢 **Low:** ${report.severity.low}\n`;
    md += `\n`;
  }

  // Top 10 files with most issues
  const topFiles = report.files
    .filter((f) => f.issues > 0)
    .sort((a, b) => b.issues - a.issues)
    .slice(0, 10);

  if (topFiles.length > 0) {
    md += `### Top Files with Issues\n\n`;
    md += `| File | Issues | 🔴 | 🟠 | 🟡 | 🟢 |\n`;
    md += `|------|--------|----|----|----|\n`;

    topFiles.forEach((file) => {
      md += `| \`${file.relativePath}\` | ${file.issues} | ${file.critical} | ${file.high} | ${file.medium} | ${file.low} |\n`;
    });

    md += `\n`;
  }

  // Frame statistics
  const frameStats = new Map<string, { count: number; totalIssues: number; totalDuration: number }>();

  report.files.forEach((file) => {
    file.frames.forEach((frame) => {
      const existing = frameStats.get(frame.name) || { count: 0, totalIssues: 0, totalDuration: 0 };
      frameStats.set(frame.name, {
        count: existing.count + 1,
        totalIssues: existing.totalIssues + frame.issues,
        totalDuration: existing.totalDuration + frame.duration,
      });
    });
  });

  if (frameStats.size > 0) {
    md += `### Validation Frames\n\n`;
    md += `| Frame | Executions | Issues | Avg Duration |\n`;
    md += `|-------|------------|--------|-------------|\n`;

    const sortedFrames = Array.from(frameStats.entries()).sort(
      (a, b) => b[1].totalIssues - a[1].totalIssues
    );

    sortedFrames.forEach(([name, stats]) => {
      const avgDuration = stats.totalDuration / stats.count;
      md += `| ${name} | ${stats.count} | ${stats.totalIssues} | ${avgDuration.toFixed(2)}s |\n`;
    });

    md += `\n`;
  }

  // Error info if failed
  if (report.status === 'failed' && report.error) {
    md += `### Error\n\n`;
    md += `\`\`\`\n${report.error}\n\`\`\`\n\n`;
  }

  // Footer
  md += `---\n\n`;
  md += `*Generated by Warden CLI v0.1.0*\n`;

  return md;
}

/**
 * Save markdown summary
 */
export function saveReportMarkdown(report: ScanReport, outputDir: string): string {
  // Ensure output directory exists
  mkdirSync(outputDir, { recursive: true });

  const filename = `${report.id}.md`;
  const filepath = join(outputDir, filename);

  const markdown = generateMarkdownSummary(report);
  writeFileSync(filepath, markdown, 'utf-8');

  return filepath;
}

/**
 * Save complete report (JSON + Markdown)
 */
export function saveReport(
  report: ScanReport,
  outputDir: string
): { json: string; markdown: string } {
  const jsonPath = saveReportJSON(report, outputDir);
  const markdownPath = saveReportMarkdown(report, outputDir);

  return {
    json: jsonPath,
    markdown: markdownPath,
  };
}

/**
 * Get default reports directory
 */
export function getReportsDirectory(projectRoot: string): string {
  return join(projectRoot, '.warden', 'reports');
}
