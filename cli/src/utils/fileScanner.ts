/**
 * File scanner utility for flat file list
 */

import {readdirSync, statSync} from 'fs';
import {join, relative} from 'path';

export interface FileItem {
  label: string;
  value: string;
  isDirectory: boolean;
  relativePath: string;
}

/**
 * Recursively scan directory and return flat file list
 */
export function scanDirectory(
  rootPath: string,
  options: {
    maxDepth?: number;
    ignorePatterns?: string[];
  } = {}
): FileItem[] {
  const {maxDepth = 5, ignorePatterns = ['.git', 'node_modules', '__pycache__', '.venv', 'dist', 'build']} = options;

  const results: FileItem[] = [];

  function scan(dirPath: string, depth: number) {
    if (depth > maxDepth) return;

    try {
      const entries = readdirSync(dirPath);

      for (const entry of entries) {
        // Skip hidden files and ignored patterns
        if (entry.startsWith('.') && entry !== '.warden') continue;
        if (ignorePatterns.includes(entry)) continue;

        const fullPath = join(dirPath, entry);
        const relPath = relative(rootPath, fullPath);

        try {
          const stats = statSync(fullPath);
          const isDir = stats.isDirectory();

          // Add to results
          results.push({
            label: isDir ? `📁 ${relPath}/` : `📄 ${relPath}`,
            value: fullPath,
            isDirectory: isDir,
            relativePath: relPath,
          });

          // Recurse into directories
          if (isDir) {
            scan(fullPath, depth + 1);
          }
        } catch {
          // Skip files we can't stat
          continue;
        }
      }
    } catch {
      // Skip directories we can't read
      return;
    }
  }

  scan(rootPath, 0);

  // Sort: directories first, then files, alphabetically
  return results.sort((a, b) => {
    if (a.isDirectory && !b.isDirectory) return -1;
    if (!a.isDirectory && b.isDirectory) return 1;
    return a.relativePath.localeCompare(b.relativePath);
  });
}

/**
 * Filter file list by search query (fuzzy)
 */
export function filterFiles(files: FileItem[], query: string): FileItem[] {
  if (!query) return files;

  const lowerQuery = query.toLowerCase();

  return files.filter(file =>
    file.relativePath.toLowerCase().includes(lowerQuery)
  );
}
