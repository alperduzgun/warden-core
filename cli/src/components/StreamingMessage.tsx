/**
 * StreamingMessage Component
 *
 * Displays a message that updates in real-time as content streams in.
 * Similar to Qwen Code's streaming response visualization.
 */

import React, { useState, useEffect } from 'react';
import { Box, Text } from 'ink';
import { StreamingMessageProps } from '../types/index.js';
import { messageColors } from '../theme.js';
import { formatMarkdown } from '../utils/markdown.js';

/**
 * Component for displaying streaming messages with real-time updates
 */
export const StreamingMessage: React.FC<StreamingMessageProps> = ({
  content,
  type,
  isComplete = false,
}) => {
  const [displayContent, setDisplayContent] = useState('');
  const [cursorVisible, setCursorVisible] = useState(true);

  /**
   * Update display content when content changes
   */
  useEffect(() => {
    setDisplayContent(content);
  }, [content]);

  /**
   * Animate cursor while streaming
   */
  useEffect(() => {
    if (isComplete) {
      setCursorVisible(false);
      return;
    }

    const interval = setInterval(() => {
      setCursorVisible((prev) => !prev);
    }, 500);

    return () => clearInterval(interval);
  }, [isComplete]);

  const color = messageColors[type] || messageColors.assistant;
  const formattedContent = formatMarkdown(displayContent);
  const cursor = cursorVisible ? '▊' : ' ';

  return (
    <Box flexDirection="column" paddingY={0}>
      <Box>
        <Text color={color}>
          {formattedContent}
          {!isComplete && <Text color={color}>{cursor}</Text>}
        </Text>
      </Box>
    </Box>
  );
};

export default StreamingMessage;
