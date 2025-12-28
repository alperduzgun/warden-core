/**
 * Frames command - Interactive frame manager
 * Claude Code /plugin style UI
 */

import React, {useState, useEffect} from 'react';
import {Box, Text, useInput, useApp} from 'ink';
import {Spinner} from '../components/Spinner.js';
import {useIPC} from '../hooks/useIPC.js';
import {backendManager} from '../lib/backend-manager.js';
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
  const builtInFrames = [
    'security',
    'chaos',
    'orphan',
    'architectural',
    'architecturalconsistency',
    'gitchanges',
    'fuzz',
    'property',
    'stress',
  ];

  if (builtInFrames.includes(frameId.toLowerCase())) {
    return 'Built-in';
  }

  if (frameId.toLowerCase().startsWith('custom_')) {
    return 'Custom';
  }

  return 'Community';
}

interface FramesProps {
  onExit?: () => void;
}

export function Frames({onExit}: FramesProps = {}) {
  const {exit} = useApp();
  const [isStarting, setIsStarting] = useState(true);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [frames, setFrames] = useState<Frame[]>([]);
  const [isToggling, setIsToggling] = useState(false);

  // Auto-start backend on mount
  useEffect(() => {
    const initializeBackend = async () => {
      try {
        // Use ensureRunning which handles all the startup logic
        await backendManager.ensureRunning();
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
    autoExecute: !isStarting,
  });

  // Update frames when data changes
  useEffect(() => {
    if (data) {
      setFrames(data);
    }
  }, [data]);

  // Keyboard controls
  useInput((input, key) => {
    if (key.upArrow) {
      setSelectedIndex((prev) => (prev > 0 ? prev - 1 : frames.length - 1));
    } else if (key.downArrow) {
      setSelectedIndex((prev) => (prev < frames.length - 1 ? prev + 1 : 0));
    } else if (input === ' ' && frames.length > 0) {
      // Toggle frame
      handleToggle();
    } else if (input === 'q' || key.escape) {
      // Exit frames UI (back to chat if callback provided, otherwise exit app)
      if (onExit) {
        onExit();
      } else {
        exit();
      }
    }
  });

  const handleToggle = async () => {
    if (isToggling || frames.length === 0) return;

    setIsToggling(true);
    try {
      const frame = frames[selectedIndex];
      if (!frame) return;

      const newEnabled = !(frame.enabled ?? true);

      // Call backend to update status
      await ipcClient.send('update_frame_status', {
        frame_id: frame.id,
        enabled: newEnabled,
      });

      // Update local state
      const updatedFrames = [...frames];
      updatedFrames[selectedIndex] = {...frame, enabled: newEnabled};
      setFrames(updatedFrames);
    } catch (error) {
      // Error handling - could show toast/message
    } finally {
      setIsToggling(false);
    }
  };

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

  if (!frames || frames.length === 0) {
    return (
      <Box flexDirection="column">
        <Text color="yellow">No frames available</Text>
        <Text dimColor>Check your Warden configuration</Text>
      </Box>
    );
  }

  const enabledCount = frames.filter((f) => f.enabled !== false).length;

  return (
    <Box flexDirection="column">
      {/* Header */}
      <Box borderStyle="round" borderColor="cyan" paddingX={2} paddingY={1}>
        <Text bold color="cyan">
          Warden Frame Manager
        </Text>
      </Box>

      {/* Tab navigation */}
      <Box marginTop={1}>
        <Text>
          <Text bold color="cyan">
            [Installed]
          </Text>
          <Text dimColor>  Discover  Marketplace  Errors</Text>
          <Text dimColor> (tab to cycle)</Text>
        </Text>
      </Box>

      {/* Frame count */}
      <Box marginTop={1}>
        <Text>
          Installed frames ({enabledCount}/{frames.length} enabled)
        </Text>
      </Box>

      {/* Search bar placeholder */}
      <Box marginTop={1}>
        <Text dimColor>🔍 Search frames...</Text>
      </Box>

      {/* Frame list - Single bordered box */}
      <Box marginTop={1} borderStyle="round" borderColor="gray" flexDirection="column">
        {frames.map((frame, index) => {
          const category = getFrameCategory(frame.id);
          const priorityColor = getPriorityColor(frame.priority);
          const isSelected = index === selectedIndex;
          const enabled = frame.enabled !== false;

          return (
            <Box
              key={frame.id}
              paddingX={2}
              paddingY={1}
            >
              <Box flexDirection="column" width="100%">
                {/* Frame title line */}
                <Box>
                  <Text color={isSelected ? 'cyan' : enabled ? 'green' : 'gray'}>
                    {isSelected ? '▶' : enabled ? '✓' : '○'}{' '}
                  </Text>
                  <Text bold color={isSelected ? 'white' : 'cyan'}>
                    {frame.name}
                  </Text>
                  <Text dimColor> · </Text>
                  <Text color={isSelected ? 'white' : 'green'}>{category}</Text>
                  <Text dimColor> · </Text>
                  <Text color={isSelected ? 'white' : priorityColor}>
                    {frame.priority}
                  </Text>
                  {frame.is_blocker && (
                    <>
                      <Text dimColor> · </Text>
                      <Text bold color="red">
                        ⚠ BLOCKER
                      </Text>
                    </>
                  )}
                  {!enabled && (
                    <>
                      <Text dimColor> · </Text>
                      <Text dimColor>[DISABLED]</Text>
                    </>
                  )}
                </Box>

                {/* Description */}
                <Box marginTop={1}>
                  <Text dimColor={!isSelected}>{frame.description}</Text>
                </Box>
              </Box>
            </Box>
          );
        })}
      </Box>

      {/* Controls */}
      <Box marginTop={1}>
        <Text dimColor>
          [↑↓] Navigate  [Space] Toggle  [q/Esc] {onExit ? 'Back' : 'Quit'}
          {isToggling && '  (Updating...)'}
        </Text>
      </Box>
    </Box>
  );
}
