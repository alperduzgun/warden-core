/**
 * StatusLine Component
 * Enhanced status bar with connection, session, tokens, and model info
 */

import React from 'react';
import {Box, Text} from 'ink';

export interface StatusInfo {
  backend: 'connected' | 'disconnected' | 'connecting';
  session?: string;
  messages?: number;
  tokens?: {
    used: number;
    limit: number;
  };
  model?: string;
  thinking?: boolean;
}

export interface StatusLineProps {
  status: StatusInfo;
  shortcuts?: string; // Optional shortcuts hint
}

/**
 * Format large numbers with K suffix
 */
function formatNumber(n: number): string {
  if (n >= 1000) {
    return `${(n / 1000).toFixed(1)}K`;
  }
  return String(n);
}

/**
 * Enhanced status line component
 *
 * Display format:
 * ✓ Backend | Session: dev-2024 | 42 msgs | 15.2K/200K tokens (7%) | GPT-4o | 💭
 *
 * @param status - Status information
 * @param shortcuts - Optional keyboard shortcuts hint
 */
export function StatusLine({status, shortcuts}: StatusLineProps) {
  const {backend, session, messages, tokens, model, thinking} = status;

  // Connection status icon
  const statusIcon =
    backend === 'connected' ? '✓' :
    backend === 'connecting' ? '⏳' :
    '⚠';

  const statusColor =
    backend === 'connected' ? 'green' :
    backend === 'connecting' ? 'yellow' :
    'red';

  // Token usage percentage
  const tokenPercentage = tokens
    ? Math.round((tokens.used / tokens.limit) * 100)
    : 0;

  const tokenColor =
    tokenPercentage > 80 ? 'red' :
    tokenPercentage > 50 ? 'yellow' :
    'green';

  return (
    <Box flexDirection="column">
      <Box borderStyle="single" borderColor="gray" paddingX={1}>
        {/* Connection status */}
        <Text color={statusColor}>{statusIcon} Backend</Text>

        {/* Session name */}
        {session && (
          <>
            <Text dimColor> | </Text>
            <Text>Session: </Text>
            <Text color="cyan">{session}</Text>
          </>
        )}

        {/* Message count */}
        {messages !== undefined && (
          <>
            <Text dimColor> | </Text>
            <Text>{messages} msgs</Text>
          </>
        )}

        {/* Token usage */}
        {tokens && (
          <>
            <Text dimColor> | </Text>
            <Text>{formatNumber(tokens.used)}/{formatNumber(tokens.limit)} tokens </Text>
            <Text color={tokenColor}>({tokenPercentage}%)</Text>
          </>
        )}

        {/* Model */}
        {model && (
          <>
            <Text dimColor> | </Text>
            <Text>{model}</Text>
          </>
        )}

        {/* Thinking indicator */}
        {thinking && (
          <>
            <Text dimColor> | </Text>
            <Text>💭</Text>
          </>
        )}
      </Box>

      {/* Shortcuts hint (optional) */}
      {shortcuts && (
        <Box paddingX={1}>
          <Text dimColor>{shortcuts}</Text>
        </Box>
      )}
    </Box>
  );
}
