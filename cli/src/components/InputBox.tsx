/**
 * InputBox Component
 *
 * Enhanced text input with:
 * - Command detection (/, @, !)
 * - Autocomplete hints
 * - Visual feedback for command types
 * - Submit handling
 *
 * Inspired by Qwen Code's input component with Warden-specific enhancements.
 */

import React, { useState, useEffect, useRef } from 'react';
import { Box, Text, useInput } from 'ink';
import TextInput from 'ink-text-input';
import type { CommandDetection } from '../types/index.js';
import { CommandType } from '../types/index.js';
import { detectCommand, isValidCommand } from '../utils/commandDetector.js';
import { getAllCommands } from '../handlers/index.js';
import {
  getDirectoryContents,
  filterFileEntries,
  parseMentionPath,
  getFileIcon,
  formatFileSize,
  getFileTypeDescription,
  type FileEntry,
} from '../utils/filePicker.js';

/**
 * Input box props
 */
export interface InputBoxProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  placeholder?: string;
  isProcessing?: boolean;
  commandDetection?: CommandDetection;
}

/**
 * Command type colors
 */
const COMMAND_COLORS: Record<CommandType, string> = {
  slash: 'cyan',
  mention: 'magenta',
  alert: 'red',
  none: 'white',
};

/**
 * Command type indicators
 */
const COMMAND_INDICATORS: Record<CommandType, string> = {
  slash: '⚡',
  mention: '@',
  alert: '!',
  none: '',
};

/**
 * InputBox component with command detection
 */
export const InputBox: React.FC<InputBoxProps> = ({
  value,
  onChange,
  onSubmit,
  placeholder = 'Type your message or use /help for commands...',
  isProcessing = false,
}) => {
  const [detection, setDetection] = useState<CommandDetection>({ type: CommandType.NONE, raw: '' });
  const [selectedIndex, setSelectedIndex] = useState<number>(0);
  const [fileEntries, setFileEntries] = useState<FileEntry[]>([]);
  const [inputKey, setInputKey] = useState<number>(0);
  const [justNavigatedToFolder, setJustNavigatedToFolder] = useState<boolean>(false);

  // Use ref for shouldPreventSubmit to avoid race conditions with rapid Enter presses
  const shouldPreventSubmitRef = useRef<boolean>(false);

  /**
   * Handle file/directory selection
   */
  const handleSelection = (entry: FileEntry, triggerKey: 'tab' | 'enter') => {
    const isScanMode = detection.type === CommandType.SLASH &&
      (detection.command === 'scan' || detection.command === 's');

    // Always update inputKey to fix cursor position for both Tab and Enter
    if (triggerKey === 'enter') {
      shouldPreventSubmitRef.current = true;
    }
    setInputKey(prev => prev + 1);

    if (isScanMode) {
      // /scan mode - no @ prefix
      const commandPart = value.match(/^\/[^\s]+\s*/)?.[0] || '/scan ';
      const currentPath = detection.args?.trim().replace(/^@/, '') || '';

      if (entry.type === 'directory') {
        const basePath = currentPath.endsWith('/') ? currentPath : currentPath.split('/').slice(0, -1).join('/');
        const newPath = entry.name === '..'
          ? basePath.split('/').slice(0, -1).join('/') || ''
          : (basePath ? basePath + '/' + entry.name : entry.name) + '/';
        onChange(`${commandPart}${newPath}`);
        setJustNavigatedToFolder(true);
      } else {
        onChange(`${commandPart}${entry.relativePath} `);
        setJustNavigatedToFolder(false);
        setFileEntries([]);
      }
    } else {
      // @ mention mode
      const atIndex = value.lastIndexOf('@');
      const beforeAt = value.slice(0, atIndex);
      const mentionPart = value.slice(atIndex);
      const { basePath } = parseMentionPath(mentionPart);

      if (entry.type === 'directory') {
        const newPath = entry.name === '..'
          ? basePath.split('/').slice(0, -2).join('/') || ''
          : (basePath + entry.name + '/');
        onChange(`${beforeAt}@${newPath}`);
        setJustNavigatedToFolder(true);
      } else {
        onChange(`${beforeAt}@${entry.relativePath} `);
        setJustNavigatedToFolder(false);
        setFileEntries([]);
      }
    }
  };

  /**
   * Update command detection when value changes
   */
  useEffect(() => {
    // If input is empty, reset everything (including shouldPreventSubmit)
    if (value.trim().length === 0) {
      setDetection({ type: CommandType.NONE, raw: '' });
      setSelectedIndex(0);
      setFileEntries([]);
      setJustNavigatedToFolder(false);
      shouldPreventSubmitRef.current = false; // Reset submit prevention flag
      return;
    }

    const newDetection = detectCommand(value);
    const detectionChanged = newDetection.type !== detection.type ||
      newDetection.command !== detection.command;

    setDetection(newDetection);

    // Only reset selection if detection type/command changed (not just args)
    if (detectionChanged) {
      setSelectedIndex(0);
    }

    // Determine if file picker should be shown
    // Don't show file picker if:
    // 1. Args look like a complete file path (contains .py, .js, etc.)
    // 2. User is just typing a complete path
    const args = newDetection.args?.trim() || '';
    const looksLikeCompleteFile = /\.(py|js|ts|tsx|jsx|java|go|rs|c|cpp|h|rb|php|swift|kt|scala|sh|json|yaml|yml|xml|html|css|md|txt)$/i.test(args);

    const shouldShow = !looksLikeCompleteFile && (
      newDetection.type === CommandType.MENTION ||
      (newDetection.type === CommandType.SLASH &&
       (newDetection.command === 'scan' || newDetection.command === 's' || newDetection.command === 'analyze' || newDetection.command === 'a' || newDetection.command === 'check'))
    );

    if (shouldShow) {
      // Calculate search path
      let searchPath: string;

      if (newDetection.type === CommandType.MENTION) {
        // @ mention mode: use value as-is
        searchPath = value;
      } else if (newDetection.args?.includes('@')) {
        // /scan @path mode: extract @ part
        const atIndex = value.lastIndexOf('@');
        searchPath = value.slice(atIndex);
      } else {
        // /scan path mode: prepend @ for parsing
        // If args is empty, default to current directory
        const pathArg = newDetection.args?.trim() || './';
        searchPath = '@' + pathArg;
      }

      const { basePath, search } = parseMentionPath(searchPath);
      const allEntries = getDirectoryContents(basePath);
      const filtered = filterFileEntries(allEntries, search);
      setFileEntries(filtered);
    } else {
      setFileEntries([]);
    }
  }, [value]);

  /**
   * Get filtered commands based on current input
   */
  const getFilteredCommands = () => {
    const allCommands = getAllCommands();

    // If user typed something after "/", filter commands
    if (detection.command && detection.command.length > 0) {
      return allCommands.filter(cmd => {
        // Check if command name or any alias starts with typed text
        const typedLower = detection.command!.toLowerCase();
        const nameMatch = cmd.name.toLowerCase().startsWith(typedLower);
        const aliasMatch = cmd.aliases?.some(alias =>
          alias.toLowerCase().startsWith(typedLower)
        );
        return nameMatch || aliasMatch;
      });
    }

    // Otherwise show all commands
    return allCommands;
  };

  const filteredCommands = getFilteredCommands();

  /**
   * Handle keyboard navigation
   */
  useInput((_input, key) => {
    // Handle file picker navigation FIRST (higher priority than slash commands)
    // Active for: @ mentions, /scan args, or /scan @ args
    const hasFilePicker = fileEntries.length > 0 && (
      value.includes('@') ||
      (detection.type === CommandType.SLASH && (detection.command === 'scan' || detection.command === 's'))
    );

    if (hasFilePicker && (
      detection.type === CommandType.MENTION ||
      (detection.type === CommandType.SLASH && detection.args?.includes('@')) ||
      (detection.type === CommandType.SLASH && (detection.command === 'scan' || detection.command === 's'))
    )) {
      // Arrow down - move to next file
      if (key.downArrow) {
        setSelectedIndex(prev =>
          prev < fileEntries.length - 1 ? prev + 1 : 0
        );
        return;
      }

      // Arrow up - move to previous file
      if (key.upArrow) {
        setSelectedIndex(prev =>
          prev > 0 ? prev - 1 : fileEntries.length - 1
        );
        return;
      }

      // Tab - select highlighted file/directory
      if (key.tab) {
        const selectedEntry = fileEntries[selectedIndex];
        if (selectedEntry) {
          handleSelection(selectedEntry, 'tab');
        }
        return;
      }

      // Enter - smart behavior:
      // - If just navigated to folder, SECOND Enter submits
      // - Otherwise, select the highlighted entry from list
      if (key.return) {
        const args = detection.args?.trim().replace(/^@/, '') || '';

        // If args end with '/' AND we just navigated, check if it's first or second Enter
        if (args.endsWith('/')) {
          if (justNavigatedToFolder) {
            // First Enter after navigation - prevent submit, clear flag for next Enter
            setJustNavigatedToFolder(false);
            shouldPreventSubmitRef.current = true;
            return;
          } else {
            // Second Enter (or user typed the path manually) - allow submit
            return;
          }
        }

        // Otherwise, select the highlighted entry
        const selectedEntry = fileEntries[selectedIndex];
        if (selectedEntry) {
          handleSelection(selectedEntry, 'enter');
        }
        return;
      }
    }

    // Handle slash command navigation (only if NO file picker active)
    if (!hasFilePicker && detection.type === CommandType.SLASH && value.startsWith('/')) {
      // Arrow down - move to next command
      if (key.downArrow) {
        setSelectedIndex(prev =>
          prev < filteredCommands.length - 1 ? prev + 1 : 0
        );
        return;
      }

      // Arrow up - move to previous command
      if (key.upArrow) {
        setSelectedIndex(prev =>
          prev > 0 ? prev - 1 : filteredCommands.length - 1
        );
        return;
      }

      // Tab or Enter - auto-complete selected command
      if (key.tab || key.return) {
        const selectedCmd = filteredCommands[selectedIndex];
        if (selectedCmd) {
          // If Enter key, prevent submit on this cycle and reset input to move cursor
          if (key.return) {
            shouldPreventSubmitRef.current = true;
            setInputKey(prev => prev + 1);
          }
          onChange(`/${selectedCmd.name} `);
        }
        return;
      }
    }
  });

  /**
   * Handle submission
   */
  const handleSubmit = (submittedValue: string) => {
    // If we just prevented submit (Enter was used for selection), skip this submit
    // Use ref for synchronous check (no race conditions)
    if (shouldPreventSubmitRef.current) {
      shouldPreventSubmitRef.current = false;
      return;
    }

    const trimmed = submittedValue.trim();
    if (trimmed.length === 0) {
      return;
    }

    // Clean up command: remove trailing punctuation from paths/args
    // This handles copy-paste artifacts like: /analyze file.py, or /scan dir/;
    let processed = trimmed;

    // If it's a slash command with args, clean up the args
    if (processed.startsWith('/')) {
      const spaceIndex = processed.indexOf(' ');
      if (spaceIndex !== -1) {
        const command = processed.slice(0, spaceIndex);
        const args = processed.slice(spaceIndex + 1);
        // Remove trailing punctuation from args only
        const cleanedArgs = args.replace(/[,;:.!?]+$/, '');
        processed = command + ' ' + cleanedArgs;
      }
    }

    // Process @ mentions by removing @ prefix
    // Patterns:
    //   "@" → "."
    //   "@src/" → "src/"
    //   "/scan @" → "/scan ."
    //   "/scan @src/" → "/scan src/"

    // Replace all @ mentions with actual paths
    if (processed.includes('@')) {
      // Handle lone @ at the end
      if (processed.endsWith(' @') || processed === '@') {
        processed = processed.replace(/ @$/, ' .').replace(/^@$/, '.');
      } else {
        // Remove @ prefix from paths: @src/ → src/, @main.py → main.py
        processed = processed.replace(/@([^\s]+)/g, '$1');
      }
    }

    onSubmit(processed);
  };

  const commandColor = COMMAND_COLORS[detection.type];
  const commandIndicator = COMMAND_INDICATORS[detection.type];

  // File picker (@) is always valid, even without specific command
  const isFilePicker = detection.type === CommandType.MENTION && value.startsWith('@');
  // /scan with @ is valid (file picker mode)
  const isScanWithFilePicker = detection.type === CommandType.SLASH &&
    (detection.command === 'scan' || detection.command === 's') &&
    (detection.args?.includes('@') || fileEntries.length > 0);
  const isValid = detection.type === CommandType.NONE || isFilePicker || isScanWithFilePicker || isValidCommand(detection);

  return (
    <Box flexDirection="column">
      {/* Separator */}
      <Box marginTop={1}>
        <Text color="gray">{'─'.repeat(80)}</Text>
      </Box>

      {/* Input area */}
      <Box marginTop={1}>
        {/* Prompt indicator */}
        <Text color={commandColor} bold>
          {commandIndicator || '›'}{' '}
        </Text>

        {/* Input field - Always show to allow typing during processing */}
        <TextInput
          key={inputKey}
          value={value}
          onChange={onChange}
          onSubmit={handleSubmit}
          placeholder={isProcessing ? 'Processing... (you can still type)' : placeholder}
          showCursor={!isProcessing}
        />
      </Box>

      {/* Command suggestions list (Claude Code style - two column layout with keyboard navigation) */}
      {/* Only show if NO file picker is active AND not already selected (no space after command) */}
      {detection.type === CommandType.SLASH && value.startsWith('/') && !value.includes('@') && !value.includes(' ') && fileEntries.length === 0 && filteredCommands.length > 0 && (
        <Box marginTop={1} flexDirection="column">
          {filteredCommands.map((cmd, index) => {
            const isSelected = index === selectedIndex;

            // Calculate command column (left side)
            const commandText = `/${cmd.name}`;
            const aliasText = cmd.aliases && cmd.aliases.length > 0
              ? ` (${cmd.aliases.map(a => `/${a}`).join(', ')})`
              : '';

            return (
              <Box key={cmd.name} flexDirection="row">
                {/* Selection indicator */}
                <Text color={isSelected ? 'cyan' : 'gray'}>
                  {isSelected ? '❯ ' : '  '}
                </Text>

                {/* Left column: Command name */}
                <Box width={30} flexShrink={0}>
                  <Text color={isSelected ? 'cyan' : 'white'} bold={isSelected}>
                    {commandText}
                  </Text>
                  {aliasText && (
                    <Text color="gray" dimColor>{aliasText}</Text>
                  )}
                </Box>

                {/* Right column: Description */}
                <Box flexGrow={1}>
                  <Text color={isSelected ? 'white' : 'gray'}>{cmd.description}</Text>
                </Box>
              </Box>
            );
          })}

          {/* Navigation hint */}
          <Box marginTop={1}>
            <Text color="gray" dimColor>
              ↑↓ Navigate • Tab/Enter Select
            </Text>
          </Box>
        </Box>
      )}

      {/* File picker list (for @ mentions and /scan command args) */}
      {fileEntries.length > 0 && (
        value.includes('@') ||
        (detection.type === CommandType.SLASH && (detection.command === 'scan' || detection.command === 's'))
      ) && (
        <Box marginTop={1} flexDirection="column">
          {fileEntries.map((entry, index) => {
            const isSelected = index === selectedIndex;
            const icon = getFileIcon(entry);
            const typeDesc = getFileTypeDescription(entry);
            const sizeStr = entry.size ? formatFileSize(entry.size) : '';

            return (
              <Box key={entry.path} flexDirection="row">
                {/* Selection indicator */}
                <Text color={isSelected ? 'magenta' : 'gray'}>
                  {isSelected ? '❯ ' : '  '}
                </Text>

                {/* Icon + Name */}
                <Box width={40} flexShrink={0}>
                  <Text color={isSelected ? 'magenta' : 'white'} bold={isSelected}>
                    {icon} {entry.name}
                  </Text>
                </Box>

                {/* Type description */}
                <Box width={20} flexShrink={0}>
                  <Text color="gray" dimColor>
                    {typeDesc}
                  </Text>
                </Box>

                {/* File size (if file) */}
                {sizeStr && (
                  <Box width={10} flexShrink={0}>
                    <Text color="gray" dimColor>
                      {sizeStr}
                    </Text>
                  </Box>
                )}
              </Box>
            );
          })}

          {/* Navigation hint */}
          <Box marginTop={1}>
            <Text color="gray" dimColor>
              ↑↓ Navigate • Tab/Enter Select
            </Text>
          </Box>
        </Box>
      )}

      {/* Invalid command warning */}
      {detection.type !== CommandType.NONE && !isValid && (
        <Box marginTop={1} marginLeft={2}>
          <Text color="yellow">
            Unknown command. Use /help to see available commands.
          </Text>
        </Box>
      )}

      {/* Help text */}
      <Box marginTop={1}>
        <Text color="gray" dimColor>
          Press Enter to send • Ctrl+C to exit • /help for commands • @ for files
        </Text>
      </Box>
    </Box>
  );
};
