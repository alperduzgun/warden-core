/**
 * Simple File Search Utility
 *
 * Lightweight file/directory search for path completion.
 * Uses Node.js built-in fs methods for simplicity.
 */

import { readdirSync, statSync, existsSync } from 'fs';
import { join, dirname, basename, resolve } from 'path';

export interface PathSuggestion {
  path: string;
  isDirectory: boolean;
  fullPath: string;
}

/**
 * Search for files and directories matching a partial path
 *
 * @param partial - Partial path typed by user (e.g., "src/wa")
 * @param cwd - Current working directory
 * @param maxResults - Maximum number of results to return
 * @returns Array of path suggestions
 */
export function searchPaths(
  partial: string,
  cwd: string = process.cwd(),
  maxResults: number = 10
): PathSuggestion[] {
  try {
    // Handle empty input - show current directory contents
    if (!partial || partial.trim() === '') {
      return listDirectory(cwd, maxResults);
    }

    // Resolve the directory to search in
    const resolvedPartial = resolve(cwd, partial);
    const dir = existsSync(resolvedPartial) && statSync(resolvedPartial).isDirectory()
      ? resolvedPartial
      : dirname(resolvedPartial);

    const base = basename(partial).toLowerCase();

    // Get all entries in the directory
    const entries = readdirSync(dir, { withFileTypes: true });

    // Filter and map to suggestions
    const suggestions: PathSuggestion[] = entries
      .filter((entry) => {
        // Skip hidden files (starting with .)
        if (entry.name.startsWith('.')) return false;

        // Skip ignored patterns
        if (shouldIgnore(entry.name)) return false;

        // If user typed something, filter by prefix
        if (base) {
          return entry.name.toLowerCase().startsWith(base);
        }

        return true;
      })
      .map((entry) => {
        const fullPath = join(dir, entry.name);
        const relativePath = fullPath.replace(cwd + '/', '');

        return {
          path: entry.isDirectory() ? relativePath + '/' : relativePath,
          isDirectory: entry.isDirectory(),
          fullPath,
        };
      })
      .slice(0, maxResults);

    // Sort: directories first, then alphabetically
    suggestions.sort((a, b) => {
      if (a.isDirectory && !b.isDirectory) return -1;
      if (!a.isDirectory && b.isDirectory) return 1;
      return a.path.localeCompare(b.path);
    });

    return suggestions;
  } catch (error) {
    // Return empty array on errors (directory doesn't exist, no permissions, etc.)
    return [];
  }
}

/**
 * List directory contents
 */
function listDirectory(dir: string, maxResults: number): PathSuggestion[] {
  try {
    if (!existsSync(dir) || !statSync(dir).isDirectory()) {
      return [];
    }

    const entries = readdirSync(dir, { withFileTypes: true });

    return entries
      .filter((entry) => !entry.name.startsWith('.') && !shouldIgnore(entry.name))
      .map((entry) => ({
        path: entry.isDirectory() ? entry.name + '/' : entry.name,
        isDirectory: entry.isDirectory(),
        fullPath: join(dir, entry.name),
      }))
      .sort((a, b) => {
        if (a.isDirectory && !b.isDirectory) return -1;
        if (!a.isDirectory && b.isDirectory) return 1;
        return a.path.localeCompare(b.path);
      })
      .slice(0, maxResults);
  } catch {
    return [];
  }
}

/**
 * Check if a file/directory should be ignored
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
    '.DS_Store',
  ];

  return ignorePatterns.includes(name) || name.endsWith('.egg-info');
}
