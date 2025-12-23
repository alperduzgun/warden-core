/**
 * ScanProgress Component
 *
 * Main overlay component that displays scan progress in real-time.
 * Combines ProgressIndicator, FrameStatusDisplay, and IssueSummary.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { useProgress } from '../contexts/ProgressContext.js';
import { ProgressIndicator } from './ProgressIndicator.js';
import { FrameStatusDisplay, FrameSummary } from './FrameStatusDisplay.js';
import { IssueSummary } from './IssueSummary.js';
import type { Finding } from '../bridge/wardenClient.js';

export interface ScanProgressProps {
  /**
   * Callback when user cancels (ESC)
   */
  onCancel?: () => void;

  /**
   * Show frame details
   * @default true
   */
  showFrames?: boolean;

  /**
   * Show issue summary
   * @default true
   */
  showIssues?: boolean;

  /**
   * Current issues (for display)
   */
  currentIssues?: Finding[];
}

/**
 * Scan progress overlay component
 *
 * Displays complete scan progress with:
 * - Progress bar and elapsed time
 * - Frame execution status
 * - Issue summary
 *
 * @example
 * ```tsx
 * {progress.isActive && (
 *   <ScanProgress
 *     onCancel={() => cancelScan()}
 *     currentIssues={issues}
 *   />
 * )}
 * ```
 */
export const ScanProgress: React.FC<ScanProgressProps> = ({
  onCancel,
  showFrames = true,
  showIssues = true,
  currentIssues = [],
}) => {
  const { progress } = useProgress();

  if (!progress.isActive) {
    return null;
  }

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="cyan"
      padding={1}
      marginY={1}
    >
      {/* Header */}
      <Box marginBottom={1}>
        <Text bold color="cyan">
          🔍 Validation Scan in Progress
        </Text>
      </Box>

      {/* Progress indicator */}
      <ProgressIndicator
        current={progress.filesScanned}
        total={progress.totalFiles}
        elapsedTime={progress.elapsedTime}
        {...(onCancel && { onCancel })}
      />

      {/* Frame status */}
      {showFrames && progress.frames.length > 0 && (
        <Box marginTop={1} flexDirection="column">
          <Text bold color="gray">
            Validation Frames:
          </Text>
          <Box marginLeft={2}>
            <FrameStatusDisplay frames={progress.frames} />
          </Box>
          <Box marginLeft={2} marginTop={1}>
            <FrameSummary frames={progress.frames} />
          </Box>
        </Box>
      )}

      {/* Issue summary */}
      {showIssues && currentIssues.length > 0 && (
        <Box marginTop={1} flexDirection="column">
          <IssueSummary issues={currentIssues} maxDisplay={5} />
        </Box>
      )}

      {/* Status message */}
      {progress.status === 'error' && progress.error && (
        <Box marginTop={1}>
          <Text color="red">❌ Error: {progress.error}</Text>
        </Box>
      )}
    </Box>
  );
};

/**
 * Compact scan progress (single box)
 */
export interface CompactScanProgressProps {
  onCancel?: () => void;
}

export const CompactScanProgress: React.FC<CompactScanProgressProps> = ({
  onCancel,
}) => {
  const { progress } = useProgress();

  if (!progress.isActive) {
    return null;
  }

  const percentage =
    progress.totalFiles > 0
      ? Math.round((progress.filesScanned / progress.totalFiles) * 100)
      : 0;

  return (
    <Box borderStyle="round" borderColor="cyan" padding={1}>
      <Text>🔍 Scanning: </Text>
      <Text color="yellow">
        {progress.filesScanned}/{progress.totalFiles}
      </Text>
      <Text color="gray"> ({percentage}%)</Text>
      {progress.currentFrame && (
        <Text color="cyan"> - {progress.currentFrame}</Text>
      )}
      {onCancel && (
        <Text color="gray"> - ESC to cancel</Text>
      )}
    </Box>
  );
};

export default ScanProgress;
