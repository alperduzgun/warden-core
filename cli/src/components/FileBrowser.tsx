/**
 * File Browser Component
 * Browse project files in terminal
 */

import React, {useState, useEffect} from 'react';
import {Box, Text} from 'ink';
import SelectInput from 'ink-select-input';
import {readdirSync, statSync} from 'fs';
import {join} from 'path';

interface FileItem {
  label: string;
  value: string;
  isDirectory: boolean;
}

interface FileBrowserProps {
  initialPath?: string;
  onSelect?: (path: string) => void;
  height?: number;
}

export function FileBrowser({
  initialPath = process.cwd(),
  onSelect,
  height = 15,
}: FileBrowserProps) {
  const [currentPath, setCurrentPath] = useState(initialPath);
  const [items, setItems] = useState<FileItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDirectory(currentPath);
  }, [currentPath]);

  const loadDirectory = (path: string) => {
    try {
      const entries = readdirSync(path);
      const fileItems: FileItem[] = [];

      // Add parent directory option
      if (path !== '/') {
        fileItems.push({
          label: '📁 ../',
          value: join(path, '..'),
          isDirectory: true,
        });
      }

      // Add directories first
      const dirs = entries
        .filter((entry) => {
          try {
            const fullPath = join(path, entry);
            const stats = statSync(fullPath);
            return stats.isDirectory() && !entry.startsWith('.');
          } catch {
            return false;
          }
        })
        .map((dir) => ({
          label: `📁 ${dir}/`,
          value: join(path, dir),
          isDirectory: true,
        }));

      // Add files
      const files = entries
        .filter((entry) => {
          try {
            const fullPath = join(path, entry);
            const stats = statSync(fullPath);
            return !stats.isDirectory() && !entry.startsWith('.');
          } catch {
            return false;
          }
        })
        .map((file) => {
          const ext = file.split('.').pop() || '';
          const icon = getFileIcon(ext);
          return {
            label: `${icon} ${file}`,
            value: join(path, file),
            isDirectory: false,
          };
        });

      setItems([...fileItems, ...dirs, ...files]);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load directory');
      setItems([]);
    }
  };

  const handleSelect = (item: {label: string; value: string}) => {
    const fileItem = items.find(i => i.value === item.value);
    if (fileItem?.isDirectory) {
      setCurrentPath(fileItem.value);
    } else if (fileItem) {
      onSelect?.(fileItem.value);
    }
  };

  const getFileIcon = (ext: string): string => {
    const icons: Record<string, string> = {
      ts: '🔷',
      tsx: '⚛️ ',
      js: '📜',
      jsx: '⚛️ ',
      py: '🐍',
      json: '📋',
      md: '📝',
      yml: '⚙️ ',
      yaml: '⚙️ ',
      txt: '📄',
    };
    return icons[ext] || '📄';
  };

  return (
    <Box flexDirection="column" height={height}>
      <Box borderStyle="single" borderColor="cyan" paddingX={1} marginBottom={1}>
        <Text bold>📂 {currentPath}</Text>
      </Box>

      {error ? (
        <Box paddingX={1}>
          <Text color="red">Error: {error}</Text>
        </Box>
      ) : items.length === 0 ? (
        <Box paddingX={1}>
          <Text dimColor>Empty directory</Text>
        </Box>
      ) : (
        <SelectInput
          items={items}
          onSelect={handleSelect}
          limit={height - 4}
        />
      )}

      <Box borderStyle="single" borderColor="gray" paddingX={1} marginTop={1}>
        <Text dimColor>↑↓: Navigate | Enter: Select | Esc: Back</Text>
      </Box>
    </Box>
  );
}
