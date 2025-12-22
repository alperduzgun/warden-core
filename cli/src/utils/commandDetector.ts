/**
 * Command detection utilities for Warden CLI
 *
 * Detects and parses special commands in user input:
 * - Slash commands: /analyze, /validate, etc.
 * - Mentions: @file:path, @rule:name, etc.
 * - Alerts: !critical, !high, etc.
 */

import { CommandType, CommandDetection, SLASH_COMMANDS, MENTION_COMMANDS, ALERT_COMMANDS } from '../types/index.js';

/**
 * Detect command type from user input
 */
export function detectCommand(input: string): CommandDetection {
  const trimmed = input.trim();

  if (!trimmed) {
    return { type: CommandType.NONE, raw: input };
  }

  // Check for slash command
  if (trimmed.startsWith('/')) {
    // Allow just "/" to show all commands
    const match = trimmed.match(/^\/(\w*)(?:\s+(.*))?$/);
    if (match) {
      return {
        type: CommandType.SLASH,
        ...(match[1] && match[1].length > 0 && { command: match[1] }),
        ...(match[2] !== undefined && { args: match[2] }),
        raw: input,
      };
    }
  }

  // Check for mention command (file picker)
  if (trimmed.startsWith('@')) {
    // Allow @ followed by anything (for file paths)
    // Match: @, @file, @src/, @src/main.py, etc.
    const match = trimmed.match(/^@(.*)$/);
    if (match) {
      const afterAt = match[1] || '';
      return {
        type: CommandType.MENTION,
        ...(afterAt.length > 0 && { command: afterAt }),
        raw: input,
      };
    }
  }

  // Check for alert command
  if (trimmed.startsWith('!')) {
    const match = trimmed.match(/^!(\w+)(?:\s+(.*))?$/);
    if (match) {
      return {
        type: CommandType.ALERT,
        ...(match[1] !== undefined && { command: match[1] }),
        ...(match[2] !== undefined && { args: match[2] }),
        raw: input,
      };
    }
  }

  return { type: CommandType.NONE, raw: input };
}

/**
 * Get autocomplete suggestions based on current input
 */
export function getAutocompleteSuggestions(input: string) {
  const detection = detectCommand(input);

  if (detection.type === CommandType.NONE) {
    return [];
  }

  let availableCommands;
  switch (detection.type) {
    case CommandType.SLASH:
      availableCommands = SLASH_COMMANDS;
      break;
    case CommandType.MENTION:
      availableCommands = MENTION_COMMANDS;
      break;
    case CommandType.ALERT:
      availableCommands = ALERT_COMMANDS;
      break;
    default:
      return [];
  }

  if (!detection.command) {
    return availableCommands;
  }

  // Filter by partial match
  const commandLower = detection.command.toLowerCase();
  const prefix = detection.type === CommandType.SLASH ? '/' : detection.type === CommandType.MENTION ? '@' : '!';
  return availableCommands.filter((cmd) =>
    cmd.command.toLowerCase().startsWith(`${prefix}${commandLower}`)
  );
}

/**
 * Validate if a command is recognized
 */
export function isValidCommand(detection: CommandDetection): boolean {
  if (detection.type === CommandType.NONE) {
    return false;
  }

  let validCommands: string[];

  switch (detection.type) {
    case CommandType.SLASH:
      validCommands = SLASH_COMMANDS.map((cmd) => cmd.command.replace('/', ''));
      break;
    case CommandType.MENTION:
      validCommands = MENTION_COMMANDS.map((cmd) => cmd.command.replace('@', ''));
      break;
    case CommandType.ALERT:
      validCommands = ALERT_COMMANDS.map((cmd) => cmd.command.replace('!', ''));
      break;
    default:
      return false;
  }

  return detection.command ? validCommands.includes(detection.command) : false;
}

/**
 * Format command for display
 */
export function formatCommand(detection: CommandDetection): string {
  if (detection.type === CommandType.NONE) {
    return detection.raw;
  }

  const prefix = detection.type === CommandType.SLASH ? '/' : detection.type === CommandType.MENTION ? '@' : '!';
  const cmd = `${prefix}${detection.command || ''}`;
  return detection.args ? `${cmd} ${detection.args}` : cmd;
}

/**
 * Extract mentions from text
 */
export function extractMentions(text: string): string[] {
  const mentionRegex = /@(\w+)(?::([^\s]*))?/g;
  const mentions: string[] = [];
  let match;

  while ((match = mentionRegex.exec(text)) !== null) {
    mentions.push(match[0]);
  }

  return mentions;
}

/**
 * Extract alerts from text
 */
export function extractAlerts(text: string): string[] {
  const alertRegex = /!(\w+)/g;
  const alerts: string[] = [];
  let match;

  while ((match = alertRegex.exec(text)) !== null) {
    alerts.push(match[0]);
  }

  return alerts;
}

/**
 * Parse complex input with multiple command types
 */
export function parseComplexInput(input: string): {
  primaryCommand?: CommandDetection;
  mentions: string[];
  alerts: string[];
  plainText: string;
} {
  const primaryCommand = detectCommand(input);
  const mentions = extractMentions(input);
  const alerts = extractAlerts(input);

  // Remove commands to get plain text
  let plainText = input;
  if (primaryCommand.type !== CommandType.NONE) {
    plainText = plainText.replace(/^[/@!]\w+(?:\s+)?/, '');
  }
  mentions.forEach((mention) => {
    plainText = plainText.replace(mention, '');
  });
  alerts.forEach((alert) => {
    plainText = plainText.replace(alert, '');
  });

  const result: {
    mentions: string[];
    alerts: string[];
    plainText: string;
    primaryCommand?: CommandDetection;
  } = {
    mentions,
    alerts,
    plainText: plainText.trim(),
  };

  if (primaryCommand.type !== CommandType.NONE) {
    result.primaryCommand = primaryCommand;
  }

  return result;
}
