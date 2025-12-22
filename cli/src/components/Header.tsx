/**
 * Header Component
 *
 * Displays the Warden CLI title with gradient styling and session information.
 * Shows project context, configuration, and LLM status.
 *
 * Inspired by Qwen Code's header but adapted for Warden's security-focused identity.
 */

import React from 'react';
import { Box, Text } from 'ink';
import Gradient from 'ink-gradient';
import type { SessionInfo } from '../types/index.js';

/**
 * Shield emoji for branding
 */
const SHIELD = '🛡️';

/**
 * Header props interface
 */
export interface HeaderProps {
  sessionInfo: SessionInfo;
  version?: string;
}

/**
 * Status color mapping
 */
const STATUS_COLORS = {
  connected: 'green',
  disconnected: 'gray',
  error: 'red',
} as const;

/**
 * Status icon mapping
 */
const STATUS_ICONS = {
  connected: '●',
  disconnected: '○',
  error: '✗',
} as const;

/**
 * Header component with title and session info
 */
export const Header: React.FC<HeaderProps> = ({ sessionInfo, version = '0.1.0' }) => {
  const { projectPath, configFile, llmProvider, llmModel, llmStatus, validationMode } = sessionInfo;

  // Status display
  const statusColor = STATUS_COLORS[llmStatus];
  const statusIcon = STATUS_ICONS[llmStatus];

  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* Title with gradient */}
      <Box marginBottom={1}>
        <Gradient colors={['#4A90E2', '#7B68EE']}>
          <Text bold>
            {SHIELD} Warden - AI Code Guardian
          </Text>
        </Gradient>
        <Text color="gray" dimColor> v{version}</Text>
      </Box>

      {/* Session information */}
      <Box flexDirection="column" paddingLeft={2}>
        {/* Project path */}
        {projectPath && (
          <Box>
            <Text color="gray">Project: </Text>
            <Text color="white">{projectPath}</Text>
          </Box>
        )}

        {/* Configuration */}
        {configFile && (
          <Box>
            <Text color="gray">Config: </Text>
            <Text color="white">{configFile}</Text>
          </Box>
        )}

        {/* LLM Status */}
        <Box>
          <Text color="gray">LLM: </Text>
          <Text color={statusColor}>{statusIcon}</Text>
          <Text> </Text>
          {llmProvider && (
            <Text color="white">
              {llmProvider}
              {llmModel && <Text color="gray"> ({llmModel})</Text>}
            </Text>
          )}
          {!llmProvider && <Text color="gray">Not configured</Text>}
        </Box>

        {/* Validation mode */}
        {validationMode && (
          <Box>
            <Text color="gray">Mode: </Text>
            <Text color="magenta">{validationMode}</Text>
          </Box>
        )}
      </Box>

      {/* Bottom border */}
      <Box marginTop={1}>
        <Text color="gray">{'─'.repeat(80)}</Text>
      </Box>
    </Box>
  );
};
