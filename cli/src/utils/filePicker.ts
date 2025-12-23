/**
 * File Picker Utilities
 *
 * Provides file and directory browsing functionality for @ mentions.
 */

import { readdirSync, statSync, existsSync } from 'fs';
import { join, relative, resolve, dirname } from 'path';

/**
 * File/Directory entry
 */
export interface FileEntry {
  name: string;
  path: string;
  relativePath: string;
  type: 'file' | 'directory';
  extension?: string;
  size?: number;
}

/**
 * Get files and directories in a path
 *
 * Error handling (Kural 4.4):
 * - Returns empty array on ENOENT (directory doesn't exist)
 * - Returns empty array on EACCES (permission denied)
 * - Re-throws unexpected errors for debugging
 */
export function getDirectoryContents(dirPath: string, cwd: string = process.cwd()): FileEntry[] {
  try {
    const resolvedPath = resolve(cwd, dirPath || '.');

    // Early return for non-existent paths
    if (!existsSync(resolvedPath)) {
      return [];
    }

    const stats = statSync(resolvedPath);
    if (!stats.isDirectory()) {
      return [];
    }

    const entries = readdirSync(resolvedPath);
    const fileEntries: FileEntry[] = [];

    // Add parent directory if not at root
    if (dirPath && dirPath !== '.') {
      const parentPath = dirname(dirPath);
      fileEntries.push({
        name: '..',
        path: resolve(cwd, parentPath),
        relativePath: parentPath === '.' ? '' : parentPath,
        type: 'directory',
      });
    }

    for (const entry of entries) {
      // Skip hidden files and node_modules
      if (entry.startsWith('.') || entry === 'node_modules') {
        continue;
      }

      const fullPath = join(resolvedPath, entry);

      // Gracefully handle stat errors (symlink issues, permission denied)
      let entryStats;
      try {
        entryStats = statSync(fullPath);
      } catch (statError) {
        // Skip files we can't stat (broken symlinks, permission issues)
        continue;
      }

      const relativePath = relative(cwd, fullPath);

      const fileEntry: FileEntry = {
        name: entry,
        path: fullPath,
        relativePath,
        type: entryStats.isDirectory() ? 'directory' : 'file',
      };

      if (entryStats.isFile()) {
        const ext = entry.split('.').pop();
        if (ext && ext !== entry) {
          fileEntry.extension = ext;
        }
        fileEntry.size = entryStats.size;
      }

      fileEntries.push(fileEntry);
    }

    // Sort: directories first, then files alphabetically
    fileEntries.sort((a, b) => {
      if (a.name === '..') return -1;
      if (b.name === '..') return 1;
      if (a.type === 'directory' && b.type === 'file') return -1;
      if (a.type === 'file' && b.type === 'directory') return 1;
      return a.name.localeCompare(b.name);
    });

    return fileEntries;
  } catch (error) {
    // Handle expected errors gracefully
    if (error instanceof Error) {
      const nodeError = error as NodeJS.ErrnoException;

      // Expected errors - return empty array
      if (nodeError.code === 'ENOENT' || nodeError.code === 'EACCES') {
        return [];
      }

      // Unexpected errors - log but still return empty (graceful degradation)
      // In production, this would go to proper logging system
      if (process.env.NODE_ENV === 'development') {
        console.warn(`[filePicker] Unexpected error reading directory: ${error.message}`);
      }
    }

    return [];
  }
}

/**
 * Filter entries by search query
 */
export function filterFileEntries(entries: FileEntry[], query: string): FileEntry[] {
  if (!query || query.trim().length === 0) {
    return entries;
  }

  const queryLower = query.toLowerCase();

  return entries.filter(entry => {
    const nameLower = entry.name.toLowerCase();
    return nameLower.includes(queryLower);
  });
}

/**
 * Format file size
 */
export function formatFileSize(bytes?: number): string {
  if (!bytes) return '';

  const units = ['B', 'KB', 'MB', 'GB'];
  let size = bytes;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }

  return `${size.toFixed(size < 10 ? 1 : 0)}${units[unitIndex]}`;
}

/**
 * Get file icon based on type/extension
 */
export function getFileIcon(entry: FileEntry): string {
  if (entry.name === '..') return '↩️ ';
  if (entry.type === 'directory') return '📁';

  // File type icons
  const ext = entry.extension?.toLowerCase();
  switch (ext) {
    case 'py':
      return '🐍';
    case 'ts':
    case 'tsx':
      return '📘';
    case 'js':
    case 'jsx':
      return '📙';
    case 'json':
      return '📋';
    case 'md':
      return '📝';
    case 'yaml':
    case 'yml':
      return '⚙️ ';
    case 'txt':
      return '📄';
    default:
      return '📄';
  }
}

/**
 * Parse @ mention to extract path and search query
 */
export function parseMentionPath(mention: string): { basePath: string; search: string } {
  // Remove @ prefix
  const cleaned = mention.replace(/^@/, '');

  if (!cleaned) {
    return { basePath: '', search: '' };
  }

  // Split by last slash to get directory and file search
  const lastSlash = cleaned.lastIndexOf('/');

  if (lastSlash === -1) {
    // No slash - treat as search in current directory
    return { basePath: '', search: cleaned };
  }

  const basePath = cleaned.substring(0, lastSlash + 1);
  const search = cleaned.substring(lastSlash + 1);

  return { basePath, search };
}

/**
 * Get file type description
 */
export function getFileTypeDescription(entry: FileEntry): string {
  if (entry.name === '..') return 'Parent directory';
  if (entry.type === 'directory') return 'Directory';

  const ext = entry.extension?.toLowerCase() || '';
  switch (ext) {
    case 'py':
      return 'Python file';
    case 'ts':
      return 'TypeScript file';
    case 'tsx':
      return 'TypeScript React';
    case 'js':
      return 'JavaScript file';
    case 'jsx':
      return 'JavaScript React';
    case 'json':
      return 'JSON file';
    case 'md':
      return 'Markdown file';
    case 'yaml':
    case 'yml':
      return 'YAML config';
    case 'txt':
      return 'Text file';
    default:
      return entry.extension ? `${ext.toUpperCase()} file` : 'File';
  }
}
