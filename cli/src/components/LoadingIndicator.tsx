/**
 * Enhanced loading indicator with context-aware messages
 * Provides better feedback during long operations
 */

import React, {useState, useEffect} from 'react';
import {Box, Text} from 'ink';
import Spinner from 'ink-spinner';

interface LoadingIndicatorProps {
  message: string;
  subMessage?: string;
  showTimer?: boolean;
  timeoutWarning?: number; // Show warning after N seconds
}

export function LoadingIndicator({
  message,
  subMessage,
  showTimer = true,
  timeoutWarning = 10
}: LoadingIndicatorProps) {
  const [elapsed, setElapsed] = useState(0);
  const [showWarning, setShowWarning] = useState(false);

  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed((prev) => {
        const newElapsed = prev + 1;
        if (newElapsed >= timeoutWarning && !showWarning) {
          setShowWarning(true);
        }
        return newElapsed;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [timeoutWarning, showWarning]);

  const formatElapsed = (seconds: number) => {
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes}m ${secs}s`;
  };

  return (
    <Box flexDirection="column">
      {/* Main loading message */}
      <Box>
        <Text color="cyan">
          <Spinner type="dots" />
        </Text>
        <Box marginLeft={1}>
          <Text>{message}</Text>
          {showTimer && elapsed > 0 && (
            <Text dimColor> ({formatElapsed(elapsed)})</Text>
          )}
        </Box>
      </Box>

      {/* Sub-message */}
      {subMessage && (
        <Box marginLeft={3}>
          <Text dimColor>{subMessage}</Text>
        </Box>
      )}

      {/* Timeout warning */}
      {showWarning && (
        <Box marginTop={1} marginLeft={3}>
          <Text color="yellow">
            ⚠ This is taking longer than expected...
          </Text>
          <Box flexDirection="column" marginLeft={2}>
            <Text dimColor>• The backend might be starting up</Text>
            <Text dimColor>• Processing large files can take time</Text>
            <Text dimColor>• Press Ctrl+C to cancel if stuck</Text>
          </Box>
        </Box>
      )}
    </Box>
  );
}

/**
 * Progress indicator for multi-step operations
 */
interface StepProgressProps {
  steps: Array<{
    name: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
  }>;
  currentStep?: number;
}

export function StepProgress({steps, currentStep = 0}: StepProgressProps) {
  const statusIcons = {
    pending: '○',
    running: '◉',
    completed: '✓',
    failed: '✗',
  };

  const statusColors = {
    pending: 'gray',
    running: 'cyan',
    completed: 'green',
    failed: 'red',
  };

  return (
    <Box flexDirection="column" marginY={1}>
      {steps.map((step, index) => {
        const textProps: any = {
          dimColor: step.status === 'pending'
        };
        if (step.status === 'running') {
          textProps.color = 'cyan';
        }

        return (
          <Box key={index}>
            <Text color={statusColors[step.status] as any}>
              {statusIcons[step.status]}
            </Text>
            <Box marginLeft={1}>
              <Text {...textProps}>
                {step.name}
              </Text>
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}

/**
 * Connection status indicator
 */
interface ConnectionStatusProps {
  isConnecting: boolean;
  isConnected: boolean;
  error?: string;
  retryCount?: number;
  maxRetries?: number;
}

export function ConnectionStatus({
  isConnecting,
  isConnected,
  error,
  retryCount = 0,
  maxRetries = 3,
}: ConnectionStatusProps) {
  if (error) {
    return (
      <Box>
        <Text color="red">✗ </Text>
        <Text>Connection failed: {error}</Text>
      </Box>
    );
  }

  if (isConnected) {
    return (
      <Box>
        <Text color="green">✓ </Text>
        <Text>Connected to backend</Text>
      </Box>
    );
  }

  if (isConnecting) {
    return (
      <Box flexDirection="column">
        <Box>
          <Text color="cyan">
            <Spinner type="dots" />
          </Text>
          <Box marginLeft={1}>
            <Text>Connecting to backend...</Text>
            {retryCount > 0 && (
              <Text dimColor> (attempt {retryCount}/{maxRetries})</Text>
            )}
          </Box>
        </Box>
        {retryCount > 1 && (
          <Box marginLeft={3}>
            <Text dimColor>Starting backend service, please wait...</Text>
          </Box>
        )}
      </Box>
    );
  }

  return null;
}