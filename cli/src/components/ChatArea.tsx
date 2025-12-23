/**
 * ChatArea Component
 *
 * Displays scrollable message list with support for:
 * - Multiple message types (user, assistant, system, error)
 * - Markdown rendering
 * - Auto-scroll to bottom
 * - Streaming messages
 *
 * Adapted from Qwen Code's message display patterns.
 */

import React from 'react';
import { Box, Text } from 'ink';
import type { Message, MessageType } from '../types/index.js';
import { StreamingMessage } from './StreamingMessage.js';
import { formatMarkdown } from '../utils/markdown.js';

/**
 * Chat area props
 */
export interface ChatAreaProps {
  messages: Message[];
  autoScroll?: boolean;
}

/**
 * Message type colors
 */
const MESSAGE_COLORS: Record<MessageType, string> = {
  user: 'cyan',
  assistant: 'white',
  system: 'yellow',
  error: 'red',
  success: 'green',
  warning: 'yellow',
};

/**
 * Message type prefixes
 */
const MESSAGE_PREFIXES: Record<MessageType, string> = {
  user: 'You',
  assistant: 'Warden',
  system: 'System',
  error: 'Error',
  success: 'Success',
  warning: 'Warning',
};

/**
 * Format timestamp for display
 */
const formatTimestamp = (date: Date): string => {
  return new Date(date).toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
};

/**
 * ChatArea component with scrollable messages
 */
export const ChatArea: React.FC<ChatAreaProps> = ({
  messages,
}) => {
  if (messages.length === 0) {
    return (
      <Box flexDirection="column" padding={1}>
        <Text color="gray" dimColor>
          No messages yet. Start a conversation!
        </Text>
        <Box marginTop={1}>
          <Text color="gray" dimColor>
            Tips:
          </Text>
        </Box>
        <Box marginLeft={2} flexDirection="column">
          <Text color="gray" dimColor>• Use /help to see available commands</Text>
          <Text color="gray" dimColor>• Use @file:path to reference files</Text>
          <Text color="gray" dimColor>• Use !priority to mark urgency</Text>
        </Box>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" padding={1} overflow="hidden">
      {messages.map((message) => (
        <Box key={message.id} flexDirection="column" marginBottom={1}>
          {/* Message header */}
          <Box>
            <Text color={MESSAGE_COLORS[message.type]} bold>
              {MESSAGE_PREFIXES[message.type]}
            </Text>
            <Text color="gray" dimColor>
              {' '}[{formatTimestamp(message.timestamp)}]
            </Text>
          </Box>

          {/* Message content */}
          <Box marginLeft={2} flexDirection="column">
            {message.isStreaming ? (
              <StreamingMessage
                content={message.content}
                type={message.type}
                isComplete={false}
              />
            ) : message.metadata?.markdown ? (
              <Text>{formatMarkdown(message.content)}</Text>
            ) : (
              <Text>{message.content}</Text>
            )}
          </Box>
        </Box>
      ))}
    </Box>
  );
};
