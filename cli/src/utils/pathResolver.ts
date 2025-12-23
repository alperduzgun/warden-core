/**
 * Path Resolution Utilities
 *
 * Simple path resolution with home directory expansion.
 * Inspired by Qwen Code's minimal approach.
 *
 * KISS Principle: Keep it simple. Security validation moved to errors.ts.
 * File search moved to command handlers (single responsibility).
 */

import * as os from 'node:os';
import * as path from 'node:path';
import { existsSync, statSync } from 'fs';

/**
 * Resolve path with home directory expansion
 *
 * Handles:
 * - `~` and `~/path` → User home directory
 * - `%USERPROFILE%` (Windows) → User home directory
 * - Relative paths → Normalized
 * - Absolute paths → Normalized
 *
 * @param p - Path to resolve
 * @returns Resolved and normalized path
 *
 * @example
 * ```ts
 * resolvePath('~/Documents')  → '/Users/username/Documents'
 * resolvePath('./src')        → '/current/working/dir/src'
 * resolvePath('%USERPROFILE%\Documents') → 'C:\Users\username\Documents'
 * ```
 */
export function resolvePath(p: string): string {
  if (!p) {
    return '';
  }

  let expandedPath = p;

  // Handle Windows %USERPROFILE%
  if (p.toLowerCase().startsWith('%userprofile%')) {
    expandedPath = os.homedir() + p.substring('%userprofile%'.length);
  }
  // Handle Unix ~ (home directory)
  else if (p === '~' || p.startsWith('~/')) {
    expandedPath = os.homedir() + p.substring(1);
  }

  // Normalize path (resolve .. and .)
  return path.normalize(expandedPath);
}

/**
 * Check if path exists and is accessible
 *
 * @param filePath - Path to check
 * @returns True if path exists and is accessible
 */
export function pathExists(filePath: string): boolean {
  try {
    return existsSync(filePath);
  } catch {
    return false;
  }
}

/**
 * Check if path is a file
 *
 * @param filePath - Path to check
 * @returns True if path is a file
 */
export function isFile(filePath: string): boolean {
  try {
    return existsSync(filePath) && statSync(filePath).isFile();
  } catch {
    return false;
  }
}

/**
 * Check if path is a directory
 *
 * @param dirPath - Path to check
 * @returns True if path is a directory
 */
export function isDirectory(dirPath: string): boolean {
  try {
    return existsSync(dirPath) && statSync(dirPath).isDirectory();
  } catch {
    return false;
  }
}

/**
 * Get file size in bytes
 *
 * @param filePath - File path
 * @returns File size or undefined if not accessible
 */
export function getFileSize(filePath: string): number | undefined {
  try {
    if (!existsSync(filePath)) return undefined;
    const stats = statSync(filePath);
    return stats.isFile() ? stats.size : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Validate file extension
 *
 * @param filePath - File path
 * @param allowedExtensions - Array of allowed extensions (e.g., ['.py', '.js'])
 * @returns True if file has allowed extension
 */
export function hasValidExtension(
  filePath: string,
  allowedExtensions: string[]
): boolean {
  const ext = path.extname(filePath).toLowerCase();
  return allowedExtensions.some((allowed) => ext === allowed.toLowerCase());
}

/**
 * Search locations for smart file search
 */
export const COMMON_SEARCH_DIRS = ['examples', 'src', 'tests', 'test', 'lib', 'app'];

/**
 * Legacy compatibility: Get search locations (for error messages)
 *
 * @deprecated Use error handling utilities instead
 */
export function getSearchLocations(lastScanPath?: string): string[] {
  const locations = [
    `Current directory: \`${process.cwd()}\``,
    `Common subdirectories: ${COMMON_SEARCH_DIRS.map((d) => `\`${d}/\``).join(', ')}`,
    'Parent directories (up to 5 levels)',
  ];

  if (lastScanPath) {
    locations.push(`Last scanned directory: \`${lastScanPath}\``);
  }

  return locations;
}
