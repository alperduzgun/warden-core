/**
 * FrameStatusDisplay Component
 *
 * Displays validation frame execution status in real-time.
 * Shows which frames are pending, running, completed, or failed.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { StatusSpinner } from './WardenSpinner.js';
import { formatDuration } from '../utils/formatters.js';

export type FrameStatus = 'pending' | 'running' | 'success' | 'error' | 'skipped';

export interface FrameProgress {
  /**
   * Frame identifier
   */
  id: string;

  /**
   * Frame display name
   */
  name: string;

  /**
   * Current execution status
   */
  status: FrameStatus;

  /**
   * Number of issues found (optional)
   */
  issuesFound?: number;

  /**
   * Execution duration in milliseconds (optional)
   */
  duration?: number;

  /**
   * Error message if status is 'error' (optional)
   */
  error?: string;
}

export interface FrameStatusDisplayProps {
  /**
   * List of validation frames with their current status
   */
  frames: FrameProgress[];

  /**
   * Show duration for completed frames
   * @default true
   */
  showDuration?: boolean;

  /**
   * Show issue count for completed frames
   * @default true
   */
  showIssueCount?: boolean;

  /**
   * Compact mode (single line per frame)
   * @default false
   */
  compact?: boolean;
}

/**
 * Display validation frame execution status
 *
 * @example
 * ```tsx
 * const frames = [
 *   { id: '1', name: 'Security', status: 'success', issuesFound: 5, duration: 1200 },
 *   { id: '2', name: 'Chaos', status: 'running' },
 *   { id: '3', name: 'Orphan', status: 'pending' }
 * ];
 * <FrameStatusDisplay frames={frames} />
 * ```
 */
export const FrameStatusDisplay: React.FC<FrameStatusDisplayProps> = ({
  frames,
  showDuration = true,
  showIssueCount = true,
  compact = false,
}) => {
  if (frames.length === 0) {
    return (
      <Box>
        <Text color="gray">No validation frames configured</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      {compact ? (
        // Compact mode: all frames in one line
        <Box>
          {frames.map((frame, idx) => (
            <React.Fragment key={frame.id}>
              <FrameStatusIcon status={frame.status} />
              {idx < frames.length - 1 && <Text color="gray"> · </Text>}
            </React.Fragment>
          ))}
        </Box>
      ) : (
        // Detailed mode: one line per frame
        frames.map((frame) => (
          <FrameStatusLine
            key={frame.id}
            frame={frame}
            showDuration={showDuration}
            showIssueCount={showIssueCount}
          />
        ))
      )}
    </Box>
  );
};

/**
 * Single frame status line
 */
const FrameStatusLine: React.FC<{
  frame: FrameProgress;
  showDuration: boolean;
  showIssueCount: boolean;
}> = ({ frame, showDuration, showIssueCount }) => {
  return (
    <Box>
      {/* Status icon/spinner */}
      <StatusSpinner status={frame.status} />

      {/* Frame name */}
      <Text bold={frame.status === 'running'}> {frame.name}</Text>

      {/* Issue count (if completed and has issues) */}
      {showIssueCount &&
        frame.status === 'success' &&
        frame.issuesFound !== undefined && (
          <Text color={frame.issuesFound > 0 ? 'yellow' : 'green'}>
            {' '}
            - {frame.issuesFound} issue{frame.issuesFound !== 1 ? 's' : ''}
          </Text>
        )}

      {/* Duration (if completed) */}
      {showDuration &&
        frame.duration !== undefined &&
        (frame.status === 'success' || frame.status === 'error') && (
          <Text color="gray"> ({formatDuration(frame.duration)})</Text>
        )}

      {/* Error message */}
      {frame.status === 'error' && frame.error && (
        <Text color="red"> - {frame.error}</Text>
      )}
    </Box>
  );
};

/**
 * Status icon only (for compact mode)
 */
const FrameStatusIcon: React.FC<{ status: FrameStatus }> = ({ status }) => {
  const icons = {
    pending: '○',
    running: '◐',
    success: '●',
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

  return <Text color={colors[status]}>{icons[status]}</Text>;
};

/**
 * Frame summary (completed/total)
 */
export interface FrameSummaryProps {
  frames: FrameProgress[];
}

export const FrameSummary: React.FC<FrameSummaryProps> = ({ frames }) => {
  const completed = frames.filter(
    (f) => f.status === 'success' || f.status === 'error' || f.status === 'skipped'
  ).length;
  const total = frames.length;
  const success = frames.filter((f) => f.status === 'success').length;
  const failed = frames.filter((f) => f.status === 'error').length;

  return (
    <Box>
      <Text>Frames: </Text>
      <Text color="cyan">
        {completed}/{total}
      </Text>
      {success > 0 && (
        <Text color="green"> ({success} passed)</Text>
      )}
      {failed > 0 && <Text color="red"> ({failed} failed)</Text>}
    </Box>
  );
};

export default FrameStatusDisplay;
