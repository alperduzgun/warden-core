/**
 * Pipeline Progress Display Component
 * Shows real-time frame execution status with duration tracking
 */

import React, {useState, useEffect} from 'react';
import {Box, Text} from 'ink';
import Spinner from 'ink-spinner';

export interface FrameProgress {
  id: string;
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'warning';
  duration?: string;
  issues?: number;
}

export interface PipelineProgressProps {
  frames: FrameProgress[];
  pipelineName?: string;
  totalDuration?: string;
}

const getStatusIcon = (status: FrameProgress['status']): string => {
  switch (status) {
    case 'completed':
      return '✓';
    case 'failed':
      return '✗';
    case 'warning':
      return '⚠';
    case 'running':
      return '';
    case 'pending':
    default:
      return ' ';
  }
};

const getStatusColor = (status: FrameProgress['status']): string => {
  switch (status) {
    case 'completed':
      return 'green';
    case 'failed':
      return 'red';
    case 'warning':
      return 'yellow';
    case 'running':
      return 'cyan';
    case 'pending':
    default:
      return 'gray';
  }
};

export function PipelineProgressDisplay({frames, pipelineName, totalDuration}: PipelineProgressProps) {
  const [dots, setDots] = useState('');

  // Animate dots for running state
  useEffect(() => {
    const interval = setInterval(() => {
      setDots(prev => prev.length >= 3 ? '' : prev + '.');
    }, 500);

    return () => clearInterval(interval);
  }, []);

  const completedCount = frames.filter(f => f.status === 'completed').length;
  const failedCount = frames.filter(f => f.status === 'failed').length;
  const warningCount = frames.filter(f => f.status === 'warning').length;
  const isRunning = frames.some(f => f.status === 'running');

  return (
    <Box flexDirection="column" borderStyle="single" borderColor="cyan" padding={1}>
      {/* Header */}
      <Box marginBottom={1}>
        <Text bold>
          {isRunning ? '⚡ Running' : '🔍'} Validation Pipeline
          {pipelineName && ` - ${pipelineName}`}
        </Text>
      </Box>

      {/* Frame List */}
      <Box flexDirection="column">
        {frames.map((frame, index) => (
          <Box key={frame.id} marginBottom={index < frames.length - 1 ? 0 : 0}>
            {/* Status Icon or Spinner */}
            <Box width={2} marginRight={1}>
              {frame.status === 'running' ? (
                <Text color="cyan">
                  <Spinner type="dots" />
                </Text>
              ) : (
                <Text color={getStatusColor(frame.status)}>
                  {getStatusIcon(frame.status)}
                </Text>
              )}
            </Box>

            {/* Frame Name */}
            <Box width={25}>
              <Text color={getStatusColor(frame.status)}>
                {frame.name}
              </Text>
            </Box>

            {/* Duration */}
            {frame.duration && (
              <Box width={8}>
                <Text dimColor>
                  [{frame.duration}]
                </Text>
              </Box>
            )}

            {/* Status */}
            <Box flexGrow={1}>
              <Text color={getStatusColor(frame.status)}>
                {frame.status === 'running'
                  ? `running${dots}`
                  : frame.status === 'completed'
                  ? 'PASSED'
                  : frame.status === 'failed'
                  ? 'FAILED'
                  : frame.status === 'warning'
                  ? `WARNING${frame.issues ? ` (${frame.issues} issues)` : ''}`
                  : 'pending'
                }
              </Text>
            </Box>
          </Box>
        ))}
      </Box>

      {/* Summary Footer */}
      {!isRunning && frames.length > 0 && (
        <Box marginTop={1} paddingTop={1} borderStyle="single" borderTop borderColor="gray">
          <Text>
            Total: {frames.length} frames |
            {completedCount > 0 && <Text color="green"> ✓ {completedCount} passed</Text>}
            {failedCount > 0 && <Text color="red"> ✗ {failedCount} failed</Text>}
            {warningCount > 0 && <Text color="yellow"> ⚠ {warningCount} warnings</Text>}
            {totalDuration && <Text dimColor> | {totalDuration}</Text>}
          </Text>
        </Box>
      )}
    </Box>
  );
}