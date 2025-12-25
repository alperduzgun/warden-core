/**
 * ProgressBar Component
 * Visual progress indicator with percentage and custom colors
 */

import React from 'react';
import {Box, Text} from 'ink';

export interface ProgressBarProps {
  value: number; // 0-100
  width?: number;
  showPercentage?: boolean;
  label?: string;
  color?: string;
}

/**
 * Progress bar component
 *
 * @param value - Progress value (0-100)
 * @param width - Width in characters (default: 20)
 * @param showPercentage - Show percentage text (default: true)
 * @param label - Optional label text
 * @param color - Bar color (default: 'green', 'yellow' if >50%, 'red' if >80%)
 */
export function ProgressBar({
  value,
  width = 20,
  showPercentage = true,
  label,
  color,
}: ProgressBarProps) {
  // Clamp value between 0 and 100
  const clampedValue = Math.max(0, Math.min(100, value));

  // Calculate filled and empty portions
  const filled = Math.round((clampedValue / 100) * width);
  const empty = width - filled;

  // Auto color based on percentage if not specified
  const barColor = color || (
    clampedValue > 80 ? 'red' :
    clampedValue > 50 ? 'yellow' :
    'green'
  );

  return (
    <Box>
      {label && <Text>{label} </Text>}
      <Text color={barColor}>{'█'.repeat(filled)}</Text>
      <Text dimColor>{'░'.repeat(empty)}</Text>
      {showPercentage && (
        <Text dimColor> {clampedValue.toFixed(0)}%</Text>
      )}
    </Box>
  );
}
