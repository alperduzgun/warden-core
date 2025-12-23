/**
 * ProgressIndicator Component
 *
 * Displays scan progress with file count, percentage, and elapsed time.
 * Inspired by Qwen Code's LoadingIndicator.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { WardenSpinner } from './WardenSpinner.js';
import { formatDuration, formatPercentage } from '../utils/formatters.js';

export interface ProgressIndicatorProps {
  /**
   * Current number of files scanned
   */
  current: number;

  /**
   * Total number of files to scan
   */
  total: number;

  /**
   * Elapsed time in seconds
   */
  elapsedTime: number;

  /**
   * Optional callback when user presses ESC to cancel
   */
  onCancel?: () => void;

  /**
   * Show cancel hint
   * @default true
   */
  showCancelHint?: boolean;

  /**
   * Custom text to display
   */
  customText?: string;
}

/**
 * Progress indicator with percentage bar and elapsed time
 *
 * @example
 * ```tsx
 * <ProgressIndicator
 *   current={45}
 *   total={100}
 *   elapsedTime={15}
 *   onCancel={() => console.log('Cancelled')}
 * />
 * ```
 */
export const ProgressIndicator: React.FC<ProgressIndicatorProps> = ({
  current,
  total,
  elapsedTime,
  onCancel,
  showCancelHint = true,
  customText,
}) => {
  const percentage = total > 0 ? Math.round((current / total) * 100) : 0;
  const isComplete = current >= total && total > 0;

  // Create progress bar
  const barWidth = 20;
  const filledWidth = Math.round((percentage / 100) * barWidth);
  const emptyWidth = barWidth - filledWidth;
  const progressBar = '█'.repeat(filledWidth) + '░'.repeat(emptyWidth);

  return (
    <Box flexDirection="column">
      {/* Main progress line */}
      <Box>
        {!isComplete && <WardenSpinner type="dots" color="cyan" />}
        {isComplete && <Text color="green">✓ </Text>}
        {customText ? (
          <Text>{customText}</Text>
        ) : (
          <>
            <Text> Progress: </Text>
            <Text color="yellow" bold>
              {current}/{total}
            </Text>
            <Text> ({percentage}%)</Text>
          </>
        )}
      </Box>

      {/* Progress bar */}
      <Box marginLeft={2}>
        <Text color={isComplete ? 'green' : 'cyan'}>[{progressBar}]</Text>
        <Text color="gray"> {formatPercentage(current, total)}%</Text>
      </Box>

      {/* Time and cancel hint */}
      <Box marginLeft={2}>
        <Text color="gray">
          {formatDuration(elapsedTime * 1000)} elapsed
          {showCancelHint && onCancel && !isComplete && ' - ESC to cancel'}
        </Text>
      </Box>
    </Box>
  );
};

/**
 * Compact progress indicator (single line)
 */
export interface CompactProgressProps {
  current: number;
  total: number;
  elapsedTime: number;
  showSpinner?: boolean;
}

export const CompactProgress: React.FC<CompactProgressProps> = ({
  current,
  total,
  elapsedTime,
  showSpinner = true,
}) => {
  const percentage = total > 0 ? Math.round((current / total) * 100) : 0;

  return (
    <Box>
      {showSpinner && <WardenSpinner type="dots" color="cyan" />}
      <Text color="yellow">
        {current}/{total}
      </Text>
      <Text color="gray"> ({percentage}%)</Text>
      <Text color="gray"> - {formatDuration(elapsedTime * 1000)}</Text>
    </Box>
  );
};

export default ProgressIndicator;
