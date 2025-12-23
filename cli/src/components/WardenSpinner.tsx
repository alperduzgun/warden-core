/**
 * WardenSpinner Component
 *
 * Animated spinner for progress indication.
 * Inspired by Qwen Code's GeminiRespondingSpinner but adapted for Warden.
 */

import React from 'react';
import { Box, Text } from 'ink';
import Spinner from 'ink-spinner';
import type { SpinnerName } from 'cli-spinners';

export interface WardenSpinnerProps {
  /**
   * Text to display next to spinner
   */
  text?: string;

  /**
   * Spinner animation type
   * @default 'dots'
   */
  type?: SpinnerName;

  /**
   * Spinner color
   * @default 'cyan'
   */
  color?: string;

  /**
   * Show spinner (if false, only shows text)
   * @default true
   */
  showSpinner?: boolean;
}

/**
 * Animated spinner component for Warden CLI
 *
 * @example
 * ```tsx
 * <WardenSpinner text="Scanning files..." type="dots" />
 * <WardenSpinner text="Analyzing code" type="toggle" color="yellow" />
 * ```
 */
export const WardenSpinner: React.FC<WardenSpinnerProps> = ({
  text,
  type = 'dots',
  color = 'cyan',
  showSpinner = true,
}) => {
  return (
    <Box>
      {showSpinner && (
        <Text color={color}>
          <Spinner type={type} />
        </Text>
      )}
      {text && (
        <Text>
          {showSpinner && ' '}
          {text}
        </Text>
      )}
    </Box>
  );
};

/**
 * Status-aware spinner that shows different states
 */
export interface StatusSpinnerProps {
  status: 'pending' | 'running' | 'success' | 'error' | 'skipped';
  text?: string;
}

export const StatusSpinner: React.FC<StatusSpinnerProps> = ({
  status,
  text,
}) => {
  const icons = {
    pending: '⏳',
    running: '',
    success: '✓',
    error: '✗',
    skipped: '○',
  };

  const colors = {
    pending: 'gray',
    running: 'cyan',
    success: 'green',
    error: 'red',
    skipped: 'gray',
  };

  return (
    <Box>
      {status === 'running' ? (
        <WardenSpinner type="toggle" color={colors[status]} />
      ) : (
        <Text color={colors[status]}>{icons[status]} </Text>
      )}
      {text && <Text>{text}</Text>}
    </Box>
  );
};

export default WardenSpinner;
