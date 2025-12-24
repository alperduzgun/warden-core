/**
 * FramePicker Component
 *
 * Interactive multi-select frame picker for /validate command.
 *
 * Features:
 * - Multi-select checkboxes ([ ] / [x])
 * - "All Frames" toggle option
 * - Grouped by priority (Critical, High, Medium, Low)
 * - Arrow key navigation (↑↓)
 * - Space to toggle selection
 * - Enter to confirm
 * - Esc to cancel
 */

import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import type { FrameInfo } from '../bridge/wardenClient.js';

/**
 * Frame picker props
 */
export interface FramePickerProps {
  frames: FrameInfo[];
  onConfirm: (selectedFrameIds: string[]) => void;
  onCancel: () => void;
}

/**
 * Grouped frames by priority
 */
interface GroupedFrames {
  priority: string;
  label: string;
  emoji: string;
  frames: FrameInfo[];
}

/**
 * Priority order for display
 */
const PRIORITY_ORDER: Record<string, { label: string; emoji: string; order: number }> = {
  critical: { label: 'CRITICAL Priority', emoji: '🔴', order: 0 },
  high: { label: 'HIGH Priority', emoji: '🟠', order: 1 },
  medium: { label: 'MEDIUM Priority', emoji: '🟡', order: 2 },
  low: { label: 'LOW Priority', emoji: '🟢', order: 3 },
};

/**
 * Group frames by priority
 */
function groupFramesByPriority(frames: FrameInfo[]): GroupedFrames[] {
  const groups: Record<string, FrameInfo[]> = {};

  // Group frames
  for (const frame of frames) {
    const priority = frame.priority?.toLowerCase() || 'medium';
    if (!groups[priority]) {
      groups[priority] = [];
    }
    groups[priority].push(frame);
  }

  // Convert to array and sort by priority order
  const result: GroupedFrames[] = Object.entries(groups)
    .map(([priority, priorityFrames]) => ({
      priority,
      label: PRIORITY_ORDER[priority]?.label || `${priority.toUpperCase()} Priority`,
      emoji: PRIORITY_ORDER[priority]?.emoji || '⚪',
      frames: priorityFrames,
    }))
    .sort((a, b) => {
      const orderA = PRIORITY_ORDER[a.priority]?.order ?? 999;
      const orderB = PRIORITY_ORDER[b.priority]?.order ?? 999;
      return orderA - orderB;
    });

  return result;
}

/**
 * Calculate total items for navigation
 */
function calculateTotalItems(groupedFrames: GroupedFrames[]): number {
  // "All Frames" option + all frames
  return 1 + groupedFrames.reduce((sum, group) => sum + group.frames.length, 0);
}

/**
 * Get item at index (for navigation)
 * Returns: { type: 'all' } | { type: 'frame', frame: FrameInfo }
 */
function getItemAtIndex(
  groupedFrames: GroupedFrames[],
  index: number
): { type: 'all' } | { type: 'frame'; frame: FrameInfo } | null {
  // Index 0 = "All Frames"
  if (index === 0) {
    return { type: 'all' };
  }

  // Find frame at index
  let currentIndex = 1; // Start after "All Frames"
  for (const group of groupedFrames) {
    for (const frame of group.frames) {
      if (currentIndex === index) {
        return { type: 'frame', frame };
      }
      currentIndex++;
    }
  }

  return null;
}

/**
 * FramePicker component
 */
export const FramePicker: React.FC<FramePickerProps> = ({ frames, onConfirm, onCancel }) => {
  const [selectedFrames, setSelectedFrames] = useState<Set<string>>(
    new Set(frames.map(f => f.id)) // All selected by default
  );
  const [selectedIndex, setSelectedIndex] = useState<number>(0);
  const [allSelected, setAllSelected] = useState<boolean>(true);

  const groupedFrames = groupFramesByPriority(frames);
  const totalItems = calculateTotalItems(groupedFrames);

  /**
   * Toggle single frame selection
   */
  const toggleFrame = (frameId: string): void => {
    setSelectedFrames(prev => {
      const next = new Set(prev);
      if (next.has(frameId)) {
        next.delete(frameId);
      } else {
        next.add(frameId);
      }

      // Update "All Selected" state
      setAllSelected(next.size === frames.length);

      return next;
    });
  };

  /**
   * Toggle all frames
   */
  const toggleAll = (): void => {
    if (allSelected) {
      // Deselect all
      setSelectedFrames(new Set());
      setAllSelected(false);
    } else {
      // Select all
      setSelectedFrames(new Set(frames.map(f => f.id)));
      setAllSelected(true);
    }
  };

  /**
   * Handle keyboard input
   */
  useInput((input, key) => {
    // Arrow down - move to next item
    if (key.downArrow) {
      setSelectedIndex(prev => (prev < totalItems - 1 ? prev + 1 : 0));
      return;
    }

    // Arrow up - move to previous item
    if (key.upArrow) {
      setSelectedIndex(prev => (prev > 0 ? prev - 1 : totalItems - 1));
      return;
    }

    // Space - toggle selection
    if (input === ' ') {
      const item = getItemAtIndex(groupedFrames, selectedIndex);
      if (item) {
        if (item.type === 'all') {
          toggleAll();
        } else {
          toggleFrame(item.frame.id);
        }
      }
      return;
    }

    // Enter - confirm selection
    if (key.return) {
      const selectedIds = Array.from(selectedFrames);
      onConfirm(selectedIds);
      return;
    }

    // Esc - cancel
    if (key.escape) {
      onCancel();
      return;
    }
  });

  return (
    <Box flexDirection="column">
      {/* Header */}
      <Box marginTop={1} marginBottom={1}>
        <Text bold color="cyan">
          Select Frames to Validate (Space=toggle, Enter=confirm, Esc=cancel)
        </Text>
      </Box>

      {/* Separator */}
      <Box>
        <Text color="gray">{'─'.repeat(80)}</Text>
      </Box>

      {/* "All Frames" option */}
      <Box marginTop={1}>
        <Text color={selectedIndex === 0 ? 'cyan' : 'white'} bold={selectedIndex === 0}>
          {selectedIndex === 0 ? '❯ ' : '  '}
          {allSelected ? '[x]' : '[ ]'} All Frames ({frames.length} total)
        </Text>
      </Box>

      {/* Frames grouped by priority */}
      <Box marginTop={1} flexDirection="column">
        {groupedFrames.map(group => (
          <Box key={group.priority} flexDirection="column" marginTop={1}>
            {/* Priority header */}
            <Box>
              <Text color="gray" bold>
                {group.emoji} {group.label}:
              </Text>
            </Box>

            {/* Frames in this priority */}
            {group.frames.map(frame => {
              // Calculate index for this frame
              let frameIndex = 1; // Start after "All Frames"
              let found = false;
              for (const g of groupedFrames) {
                for (const f of g.frames) {
                  if (f.id === frame.id) {
                    found = true;
                    break;
                  }
                  frameIndex++;
                }
                if (found) break;
              }

              const isSelected = frameIndex === selectedIndex;
              const isChecked = selectedFrames.has(frame.id);
              const blocker = frame.is_blocker ? '🚨' : '';

              return (
                <Box key={frame.id} marginLeft={2}>
                  <Text color={isSelected ? 'cyan' : 'white'} bold={isSelected}>
                    {isSelected ? '❯ ' : '  '}
                    {isChecked ? '[x]' : '[ ]'} {frame.name} {blocker}
                  </Text>
                  {isSelected && (
                    <Text color="gray" dimColor>
                      {' '}
                      - {frame.description}
                    </Text>
                  )}
                </Box>
              );
            })}
          </Box>
        ))}
      </Box>

      {/* Footer */}
      <Box marginTop={1}>
        <Text color="gray">{'─'.repeat(80)}</Text>
      </Box>

      <Box marginTop={1}>
        <Text color={selectedFrames.size > 0 ? 'green' : 'yellow'}>
          Selected: {selectedFrames.size === frames.length
            ? `All (${frames.length} frames)`
            : `${selectedFrames.size} of ${frames.length} frames`}
        </Text>
      </Box>

      {/* Keyboard hints */}
      <Box marginTop={1}>
        <Text color="gray" dimColor>
          ↑↓ Navigate • Space Toggle • Enter Confirm • Esc Cancel
        </Text>
      </Box>
    </Box>
  );
};
