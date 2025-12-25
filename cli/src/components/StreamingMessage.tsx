/**
 * StreamingMessage Component
 * Displays streaming text with typing effect and progress indication
 */

import React, {useState, useEffect} from 'react';
import {Box, Text} from 'ink';
import {ProgressBar} from './ProgressBar.js';

export interface StreamingMessageProps {
  content: string;
  isStreaming: boolean;
  showCursor?: boolean;
  progress?: number; // 0-100, optional
  elapsed?: number; // milliseconds, optional
  label?: string;
}

/**
 * Streaming message with typing effect
 *
 * Features:
 * - Token-by-token display (simulated typing)
 * - Animated cursor while streaming
 * - Optional progress bar
 * - Elapsed time display
 *
 * @param content - Text content to display
 * @param isStreaming - Whether currently streaming
 * @param showCursor - Show blinking cursor (default: true when streaming)
 * @param progress - Optional progress percentage
 * @param elapsed - Optional elapsed time in ms
 * @param label - Optional label for progress
 */
export function StreamingMessage({
  content,
  isStreaming,
  showCursor = true,
  progress,
  elapsed,
  label,
}: StreamingMessageProps) {
  const [displayedContent, setDisplayedContent] = useState('');
  const [cursorVisible, setCursorVisible] = useState(true);

  // Typing effect: gradually reveal content
  useEffect(() => {
    if (isStreaming) {
      // Real-time streaming: show content immediately
      setDisplayedContent(content);
    } else {
      // Not streaming: show full content
      setDisplayedContent(content);
    }
  }, [content, isStreaming]);

  // Blinking cursor effect (500ms interval)
  useEffect(() => {
    if (!isStreaming || !showCursor) {
      setCursorVisible(false);
      return;
    }

    const interval = setInterval(() => {
      setCursorVisible(prev => !prev);
    }, 500);

    return () => clearInterval(interval);
  }, [isStreaming, showCursor]);

  return (
    <Box flexDirection="column">
      {/* Main content with cursor */}
      <Box>
        <Text>{displayedContent}</Text>
        {isStreaming && showCursor && cursorVisible && (
          <Text color="cyan">█</Text>
        )}
      </Box>

      {/* Progress bar (if provided) */}
      {progress !== undefined && (
        <Box marginTop={0}>
          <ProgressBar
            value={progress}
            width={30}
            showPercentage={true}
            {...(label ? {label} : {})}
          />
          {elapsed !== undefined && (
            <Text dimColor> ({(elapsed / 1000).toFixed(1)}s)</Text>
          )}
        </Box>
      )}
    </Box>
  );
}
