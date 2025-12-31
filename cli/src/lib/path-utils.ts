/**
 * Path utilities for CLI
 * Handles relative and absolute path resolution
 */

import path from 'path';
import fs from 'fs';

/**
 * Resolve a file path to absolute path
 * Handles relative paths, home directory expansion, etc.
 */
export function resolvePath(filePath: string): string {
  // Handle empty path
  if (!filePath || filePath.trim() === '') {
    throw new Error('Path cannot be empty');
  }

  // Handle home directory expansion (~/...)
  if (filePath.startsWith('~/')) {
    const homeDir = process.env.HOME || process.env.USERPROFILE || '';
    filePath = path.join(homeDir, filePath.slice(2));
  }

  // If already absolute path, return as is
  if (path.isAbsolute(filePath)) {
    return filePath;
  }

  // For relative paths, resolve from current working directory
  // This ensures the path is resolved relative to where the user runs the command
  const absolutePath = path.resolve(process.cwd(), filePath);

  return absolutePath;
}

/**
 * Validate that a path exists
 */
export function validatePath(filePath: string): { valid: boolean; error?: string } {
  try {
    const resolvedPath = resolvePath(filePath);

    if (!fs.existsSync(resolvedPath)) {
      return {
        valid: false,
        error: `Path does not exist: ${resolvedPath}`
      };
    }

    return { valid: true };
  } catch (error) {
    return {
      valid: false,
      error: error instanceof Error ? error.message : 'Invalid path'
    };
  }
}

/**
 * Get file info with resolved path
 */
export function getFileInfo(filePath: string) {
  const resolvedPath = resolvePath(filePath);
  const stats = fs.statSync(resolvedPath);

  return {
    absolutePath: resolvedPath,
    relativePath: path.relative(process.cwd(), resolvedPath),
    isFile: stats.isFile(),
    isDirectory: stats.isDirectory(),
    size: stats.size,
    extension: path.extname(resolvedPath),
    name: path.basename(resolvedPath),
  };
}

/**
 * Convert path to forward slashes (for consistency)
 */
export function normalizePathSeparators(filePath: string): string {
  return filePath.replace(/\\/g, '/');
}