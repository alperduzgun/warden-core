/**
 * Error handling utilities for better user experience
 * Provides user-friendly error messages and recovery suggestions
 */

import React from 'react';
import {Box, Text} from 'ink';

export interface ErrorInfo {
  title: string;
  message: string;
  suggestions?: string[];
  details?: string;
  code?: string;
}

/**
 * Convert technical errors to user-friendly messages
 */
export function getUserFriendlyError(error: Error | string): ErrorInfo {
  const errorMsg = typeof error === 'string' ? error : error.message;

  // Backend connection errors
  if (errorMsg.includes('Connection timeout') || errorMsg.includes('ECONNREFUSED')) {
    return {
      title: 'Backend Connection Failed',
      message: 'Could not connect to Warden backend service',
      suggestions: [
        'Check if Python is installed (python3 --version)',
        'Try running the backend manually: python3 src/warden/cli_bridge/server.py',
        'Check logs in /tmp/warden.log for more details',
      ],
    };
  }

  // Python not found
  if (errorMsg.includes('Python not found')) {
    return {
      title: 'Python Not Installed',
      message: 'Warden requires Python 3.9 or later to run',
      suggestions: [
        'Install Python from https://python.org',
        'On macOS: brew install python@3.11',
        'On Ubuntu: sudo apt-get install python3',
      ],
    };
  }

  // File/path errors
  if (errorMsg.includes('ENOENT') || errorMsg.includes('no such file')) {
    return {
      title: 'File Not Found',
      message: 'The specified file or directory does not exist',
      suggestions: [
        'Check if the path is correct',
        'Use relative paths from current directory',
        'Try using tab completion for file paths',
      ],
    };
  }

  // Permission errors
  if (errorMsg.includes('EACCES') || errorMsg.includes('Permission denied')) {
    return {
      title: 'Permission Denied',
      message: 'Cannot access the specified file or directory',
      suggestions: [
        'Check file permissions with ls -la',
        'Try running with appropriate permissions',
        'Ensure the file is not locked by another process',
      ],
    };
  }

  // Backend process errors
  if (errorMsg.includes('Backend process exited')) {
    const codeMatch = errorMsg.match(/code (\d+)/);
    const code = codeMatch ? codeMatch[1] : 'unknown';
    return {
      title: 'Backend Crashed',
      message: `The backend service stopped unexpectedly (exit code: ${code})`,
      suggestions: [
        'Check Python dependencies: pip install -r requirements.txt',
        'Look for import errors in the backend logs',
        'Try running the backend directly to see error details',
      ],
      details: 'Run: python3 src/warden/cli_bridge/server.py --transport socket',
    };
  }

  // Timeout errors
  if (errorMsg.includes('timeout') || errorMsg.includes('Timeout')) {
    return {
      title: 'Operation Timed Out',
      message: 'The operation took too long to complete',
      suggestions: [
        'Try analyzing smaller files or directories',
        'Check if the backend is processing other requests',
        'Restart the backend if it seems stuck',
      ],
    };
  }

  // Module not found errors
  if (errorMsg.includes('ModuleNotFoundError') || errorMsg.includes('ImportError')) {
    const moduleMatch = errorMsg.match(/No module named ['"]([^'"]+)['"]/);
    const module = moduleMatch ? moduleMatch[1] : 'required modules';
    return {
      title: 'Missing Python Dependencies',
      message: `Required Python module not installed: ${module}`,
      suggestions: [
        'Install dependencies: pip install -r requirements.txt',
        'Or install specific module: pip install ' + module,
        'Make sure you\'re using the correct Python environment',
      ],
    };
  }

  // Invalid path errors
  if (errorMsg.includes('Invalid path') || errorMsg.includes('Path traversal')) {
    return {
      title: 'Invalid Path',
      message: 'The provided path is not valid or safe',
      suggestions: [
        'Use paths relative to the current directory',
        'Avoid using .. in paths',
        'Ensure the path is within the project directory',
      ],
    };
  }

  // Generic/unknown errors
  return {
    title: 'Unexpected Error',
    message: errorMsg,
    suggestions: [
      'Check the logs for more details',
      'Try restarting the CLI',
      'Report this issue if it persists',
    ],
  };
}

/**
 * Error display component with consistent formatting
 */
export function ErrorDisplay({error, showDetails = true}: {error: Error | string; showDetails?: boolean}) {
  const errorInfo = getUserFriendlyError(error);

  return (
    <Box flexDirection="column" marginY={1}>
      {/* Error Header */}
      <Box marginBottom={1}>
        <Text color="red" bold>✗ {errorInfo.title}</Text>
      </Box>

      {/* Error Message */}
      <Box marginBottom={1}>
        <Text>{errorInfo.message}</Text>
      </Box>

      {/* Suggestions */}
      {showDetails && errorInfo.suggestions && errorInfo.suggestions.length > 0 && (
        <Box flexDirection="column" marginBottom={1}>
          <Text dimColor bold>Try these solutions:</Text>
          {errorInfo.suggestions.map((suggestion, i) => (
            <Box key={i} marginLeft={2}>
              <Text dimColor>• {suggestion}</Text>
            </Box>
          ))}
        </Box>
      )}

      {/* Additional Details */}
      {showDetails && errorInfo.details && (
        <Box marginTop={1} paddingX={1} borderStyle="single" borderColor="gray">
          <Text dimColor>{errorInfo.details}</Text>
        </Box>
      )}
    </Box>
  );
}

/**
 * Format error for logging
 */
export function formatErrorForLog(error: Error | string): string {
  if (typeof error === 'string') return error;

  let formatted = error.message;
  if (error.stack) {
    formatted += '\n' + error.stack;
  }
  return formatted;
}