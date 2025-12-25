/**
 * Frames command
 * Shows available validation frames (Claude Code style)
 */

import React, {useState, useEffect} from 'react';
import {Box, Text} from 'ink';
import {Spinner} from '../components/Spinner.js';
import {useIPC} from '../hooks/useIPC.js';
import {backendManager} from '../utils/backendManager.js';
import {ipcClient} from '../lib/ipc-client.js';
import type {Frame} from '../lib/types.js';

/**
 * Get priority color based on priority level
 */
function getPriorityColor(priority: string): string {
  switch (priority) {
    case 'CRITICAL':
      return 'red';
    case 'HIGH':
      return 'yellow';
    case 'MEDIUM':
      return 'blue';
    case 'LOW':
      return 'gray';
    default:
      return 'white';
  }
}

/**
 * Get frame category based on ID (Built-in, Custom, Community)
 */
function getFrameCategory(frameId: string): string {
  // Built-in frames from warden.validation.frames
  const builtInFrames = [
    'security',
    'chaos',
    'orphan',
    'architectural',
    'gitchanges',
    'fuzz',
    'property',
    'stress',
  ];

  if (builtInFrames.includes(frameId.toLowerCase())) {
    return 'Built-in';
  }

  // Custom frames start with "custom_"
  if (frameId.toLowerCase().startsWith('custom_')) {
    return 'Custom';
  }

  return 'Community';
}

export function Frames() {
  const [isStarting, setIsStarting] = useState(true);
  const [startupError, setStartupError] = useState<string | null>(null);

  // Auto-start backend on mount
  useEffect(() => {
    const initializeBackend = async () => {
      try {
        // Start backend if not running
        if (!backendManager.isRunning()) {
          await backendManager.start();
        }

        // Connect to backend
        if (!ipcClient.isConnected()) {
          await ipcClient.connect();
        }

        setIsStarting(false);
      } catch (error) {
        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        setStartupError(`Backend startup failed: ${errorMsg}`);
        setIsStarting(false);
      }
    };

    initializeBackend();
  }, []);

  const {data, loading, error} = useIPC<Frame[]>({
    command: 'get_available_frames',
    autoExecute: !isStarting, // Only execute after backend is ready
  });

  // Show startup spinner
  if (isStarting) {
    return <Spinner message="Starting Warden backend..." />;
  }

  // Show startup error
  if (startupError) {
    return (
      <Box flexDirection="column">
        <Text color="red">✗ Failed to start backend</Text>
        <Text dimColor>Error: {startupError}</Text>
        <Text dimColor>Make sure start_ipc_server.py exists in project root</Text>
      </Box>
    );
  }

  if (loading) {
    return <Spinner message="Loading frames..." />;
  }

  if (error) {
    return (
      <Box flexDirection="column">
        <Text color="red">✗ Failed to load frames</Text>
        <Text dimColor>Error: {error.message}</Text>
        <Text dimColor>Backend connection failed</Text>
      </Box>
    );
  }

  if (!data || data.length === 0) {
    return (
      <Box flexDirection="column">
        <Text color="yellow">No frames available</Text>
        <Text dimColor>Check your Warden configuration</Text>
      </Box>
    );
  }

  const frames = data;
  const activeCount = frames.length;

  return (
    <Box flexDirection="column">
      {/* Header */}
      <Box borderStyle="round" borderColor="cyan" paddingX={2} paddingY={1}>
        <Text bold color="cyan">
          Warden Frame Manager
        </Text>
      </Box>

      {/* Tab navigation (static for now) */}
      <Box marginTop={1}>
        <Text>
          <Text bold color="cyan">
            [Installed]
          </Text>
          <Text dimColor>  Discover  Community  Errors</Text>
          <Text dimColor> (tab to cycle)</Text>
        </Text>
      </Box>

      {/* Frame count */}
      <Box marginTop={1}>
        <Text>
          Installed frames ({activeCount}/{activeCount} active)
        </Text>
      </Box>

      {/* Search bar (static placeholder) */}
      <Box marginTop={1}>
        <Text dimColor>🔍 Search frames...</Text>
      </Box>

      {/* Frame list */}
      <Box marginTop={1} flexDirection="column">
        {frames.map((frame) => {
          const category = getFrameCategory(frame.id);
          const priorityColor = getPriorityColor(frame.priority);

          return (
            <Box
              key={frame.id}
              borderStyle="round"
              paddingX={2}
              paddingY={1}
              marginY={1}
            >
              <Box flexDirection="column">
                {/* Frame title line */}
                <Box>
                  <Text color="green">✓ </Text>
                  <Text bold color="cyan">
                    {frame.name}
                  </Text>
                  <Text dimColor> · </Text>
                  <Text color="green">{category}</Text>
                  <Text dimColor> · </Text>
                  <Text color={priorityColor}>{frame.priority}</Text>
                  {frame.is_blocker && (
                    <>
                      <Text dimColor> · </Text>
                      <Text bold color="red">
                        ⚠ BLOCKER
                      </Text>
                    </>
                  )}
                </Box>

                {/* Description */}
                <Box marginTop={1}>
                  <Text>{frame.description}</Text>
                </Box>

                {/* Metadata */}
                <Box marginTop={1}>
                  <Text dimColor>ID: {frame.id} · Version: 1.0.0</Text>
                  {frame.tags && frame.tags.length > 0 && (
                    <Text dimColor> · Tags: {frame.tags.join(', ')}</Text>
                  )}
                </Box>
              </Box>
            </Box>
          );
        })}
      </Box>

      {/* Footer help text */}
      <Box marginTop={1}>
        <Text dimColor>
          ↓ Use warden frame info &lt;id&gt; for detailed information
        </Text>
      </Box>

      {/* Controls */}
      <Box marginTop={1}>
        <Text dimColor>
          [↑↓] Navigate  [Space] Toggle  [Enter] Details  [/] Search  [q] Quit
        </Text>
      </Box>
    </Box>
  );
}
