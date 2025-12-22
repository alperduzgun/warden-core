/**
 * Status Command Handler
 *
 * Displays session status including:
 * - Session ID
 * - IPC connection status
 * - Active frames count
 * - LLM provider status
 *
 * Requires IPC connection to fetch configuration.
 */

import { MessageType } from '../types/index.js';
import type { CommandHandlerContext } from './types.js';

/**
 * Handle /status command
 *
 * Displays comprehensive session and configuration status
 *
 * @param args - Command arguments (ignored)
 * @param context - Handler context
 */
export async function handleStatusCommand(
  _args: string,
  context: CommandHandlerContext
): Promise<void> {
  const { addMessage, client, sessionId, projectRoot } = context;

  // Start building status message
  let statusMessage = '# 📊 Warden Session Status\n\n';

  // Session info
  statusMessage += '## Session Information\n';
  statusMessage += `- **Session ID**: ${sessionId || 'N/A'}\n`;
  statusMessage += `- **Project Root**: \`${projectRoot || process.cwd()}\`\n\n`;

  // IPC connection status
  statusMessage += '## Backend Connection\n';

  if (!client) {
    statusMessage += '- **Status**: ❌ Not connected\n';
    statusMessage += '- **Note**: IPC bridge is not initialized\n\n';
    addMessage(statusMessage, MessageType.SYSTEM, true);
    return;
  }

  // Try to ping backend
  try {
    const pingResult = await client.ping();
    statusMessage += `- **Status**: ✅ Connected\n`;
    statusMessage += `- **Backend**: Python IPC Server\n`;
    statusMessage += `- **Timestamp**: ${pingResult.timestamp}\n\n`;

    // Get configuration
    try {
      const config = await client.getConfig();

      // LLM provider info
      statusMessage += '## LLM Configuration\n';
      statusMessage += `- **Default Provider**: ${config.default_provider}\n`;
      statusMessage += `- **Enabled Providers**: ${config.llm_providers.filter((p) => p.enabled).length}/${config.llm_providers.length}\n`;

      // List enabled providers
      const enabledProviders = config.llm_providers.filter((p) => p.enabled);
      if (enabledProviders.length > 0) {
        statusMessage += '\n**Active LLM Providers:**\n';
        for (const provider of enabledProviders) {
          statusMessage += `- ${provider.name} (\`${provider.model}\`) - ${provider.endpoint}\n`;
        }
      }

      statusMessage += '\n';

      // Validation frames info
      statusMessage += '## Validation Frames\n';
      statusMessage += `- **Total Frames**: ${config.total_frames}\n`;
      statusMessage += `- **Blocker Frames**: ${config.frames.filter((f) => f.is_blocker).length}\n\n`;

      // List frames
      if (config.frames.length > 0) {
        statusMessage += '**Active Frames:**\n';
        for (const frame of config.frames) {
          const blockerBadge = frame.is_blocker ? '🔴' : '🟢';
          const priorityBadge = frame.priority === 'critical' ? '⚠️' : '✓';
          statusMessage += `- ${blockerBadge} ${priorityBadge} **${frame.name}** (\`${frame.id}\`) - ${frame.description}\n`;
          if (frame.tags && frame.tags.length > 0) {
            statusMessage += `  Tags: ${frame.tags.join(', ')}\n`;
          }
        }
      }
    } catch (configError) {
      statusMessage += '## Configuration\n';
      statusMessage += `- **Status**: ⚠️ Failed to fetch config\n`;
      statusMessage += `- **Error**: ${configError instanceof Error ? configError.message : 'Unknown error'}\n`;
    }
  } catch (pingError) {
    statusMessage += `- **Status**: ❌ Connection failed\n`;
    statusMessage += `- **Error**: ${pingError instanceof Error ? pingError.message : 'Unknown error'}\n`;
    statusMessage += '\n**Troubleshooting:**\n';
    statusMessage += '1. Check if Python IPC server is running\n';
    statusMessage += '2. Verify virtual environment is activated\n';
    statusMessage += '3. Run: `python3 start_ipc_server.py`\n';
  }

  // Display status
  addMessage(statusMessage, MessageType.SYSTEM, true);
}

/**
 * Command metadata for registration
 */
export const statusCommandMetadata = {
  name: 'status',
  aliases: ['info'],
  description: 'Show session status and configuration',
  usage: '/status',
  requiresIPC: true,
  handler: handleStatusCommand,
};
