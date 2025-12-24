/**
 * Providers Command Handler
 *
 * Manages AST providers for different programming languages:
 * - List installed providers
 * - Test provider availability
 *
 * Requires IPC connection to Python backend.
 *
 * Reference: src/warden/cli/providers.py
 */

import { MessageType } from '../types/index.js';
import type { CommandHandlerContext } from './types.js';
import type { ProviderInfo, ProviderTestResult } from '../bridge/wardenClient.js';

/**
 * Convert priority name to star rating
 */
function formatPriority(priority: string): string {
  const priorityMap: Record<string, string> = {
    NATIVE: '⭐⭐⭐',
    SPECIALIZED: '⭐⭐⭐',
    TREE_SITTER: '⭐⭐',
    COMMUNITY: '⭐',
    FALLBACK: '⭐',
  };
  return priorityMap[priority.toUpperCase()] || '⭐';
}

/**
 * Display provider list as markdown table
 */
function displayProviderList(
  providers: ProviderInfo[],
  addMessage: (msg: string, type: MessageType, markdown?: boolean) => void
): void {
  let message = '# 📦 Installed AST Providers\n\n';

  if (providers.length === 0) {
    message += 'No providers found.\n\n';
    message += '**Install providers with**: `warden providers install <language>`\n\n';
    message += 'Available languages: python, java, typescript, rust, go, etc.\n';
    addMessage(message, MessageType.SYSTEM, true);
    return;
  }

  // Create markdown table
  message += '| Provider | Languages | Priority | Version | Source |\n';
  message += '|----------|-----------|----------|---------|--------|\n';

  // Sort by priority (lower value = higher priority)
  const priorityOrder: Record<string, number> = {
    NATIVE: 1,
    SPECIALIZED: 2,
    TREE_SITTER: 3,
    COMMUNITY: 4,
    FALLBACK: 5,
  };

  const sortedProviders = providers.sort((a, b) => {
    const orderA = priorityOrder[a.priority.toUpperCase()] || 999;
    const orderB = priorityOrder[b.priority.toUpperCase()] || 999;
    return orderA - orderB;
  });

  for (const provider of sortedProviders) {
    const name = provider.name;
    const languages = provider.languages.join(', ');
    const priority = formatPriority(provider.priority);
    const version = provider.version;
    const source = provider.source;

    message += `| ${name} | ${languages} | ${priority} | ${version} | ${source} |\n`;
  }

  message += `\n**Total**: ${providers.length} provider(s)\n\n`;

  // Priority legend
  message += '---\n\n';
  message += '**Priority Legend**:\n';
  message += '- ⭐⭐⭐ Native/Specialized (highest quality)\n';
  message += '- ⭐⭐ Tree-sitter (universal parser)\n';
  message += '- ⭐ Community/Fallback\n';

  addMessage(message, MessageType.SYSTEM, true);
}

/**
 * Display provider test result
 */
function displayProviderTestResult(
  language: string,
  result: ProviderTestResult,
  addMessage: (msg: string, type: MessageType, markdown?: boolean) => void
): void {
  if (!result.available) {
    // Provider not found
    let message = `❌ **No provider available for ${language}**\n\n`;

    if (result.error) {
      message += `Error: ${result.error}\n\n`;

      if (result.supportedLanguages && result.supportedLanguages.length > 0) {
        message += '**Supported languages**:\n';
        for (const lang of result.supportedLanguages) {
          message += `- ${lang}\n`;
        }
        message += '\n';
      }
    } else {
      message += `**Install one with**:\n\`warden providers install ${language}\`\n`;
    }

    addMessage(message, MessageType.ERROR, true);
    return;
  }

  if (!result.validated) {
    // Provider found but validation failed
    const message =
      `⚠️  **Provider found but not functional for ${language}**\n\n` +
      `- **Provider**: ${result.providerName}\n` +
      `- **Priority**: ${formatPriority(result.priority || '')} (${result.priority})\n` +
      `- **Version**: ${result.version}\n` +
      `- **Status**: Validation failed\n\n` +
      '**Troubleshooting**:\n' +
      '1. Reinstall the provider\n' +
      '2. Check provider dependencies\n' +
      '3. Check error logs';

    addMessage(message, MessageType.ERROR, true);
    return;
  }

  // Provider available and validated
  const message =
    `✅ **Provider available for ${language}**\n\n` +
    `- **Provider**: ${result.providerName}\n` +
    `- **Priority**: ${formatPriority(result.priority || '')} (${result.priority})\n` +
    `- **Version**: ${result.version}\n` +
    `- **Status**: Ready`;

  addMessage(message, MessageType.SYSTEM, true);
}

/**
 * Handle provider list subcommand
 */
async function handleProvidersList(
  context: CommandHandlerContext
): Promise<void> {
  const { addMessage, client } = context;

  if (!client) {
    addMessage(
      '❌ **IPC connection not available**\n\n' +
        'Cannot list providers without backend connection.',
      MessageType.ERROR,
      true
    );
    return;
  }

  try {
    const providers = await client.getAvailableProviders();
    displayProviderList(providers, addMessage);
  } catch (error) {
    addMessage(
      `❌ **Failed to get providers**\n\n` +
        `Error: \`${error instanceof Error ? error.message : 'Unknown error'}\`\n\n` +
        '**Troubleshooting**:\n' +
        '1. Check IPC server is running\n' +
        '2. Try `/status` to verify connection\n' +
        '3. Check server logs for details',
      MessageType.ERROR,
      true
    );
  }
}

/**
 * Handle provider test subcommand
 */
async function handleProvidersTest(
  language: string | undefined,
  context: CommandHandlerContext
): Promise<void> {
  const { addMessage, client } = context;

  if (!language) {
    addMessage(
      '❌ **Missing language**\n\n' +
        'Usage: `/providers test <language>`\n\n' +
        'Examples:\n' +
        '- `/providers test python`\n' +
        '- `/providers test java`\n' +
        '- `/providers test typescript`',
      MessageType.ERROR,
      true
    );
    return;
  }

  if (!client) {
    addMessage(
      '❌ **IPC connection not available**\n\n' +
        'Cannot test provider without backend connection.',
      MessageType.ERROR,
      true
    );
    return;
  }

  try {
    addMessage(
      `🧪 **Testing provider for ${language}...**`,
      MessageType.SYSTEM,
      true
    );

    const result = await client.testProvider(language);
    displayProviderTestResult(language, result, addMessage);
  } catch (error) {
    addMessage(
      `❌ **Provider test failed**\n\n` +
        `Language: ${language}\n\n` +
        `Error: \`${error instanceof Error ? error.message : 'Unknown error'}\`\n\n` +
        '**Troubleshooting**:\n' +
        '1. Check IPC server is running\n' +
        '2. Verify language name is correct\n' +
        '3. Try `/status` to verify connection',
      MessageType.ERROR,
      true
    );
  }
}

/**
 * Handle /providers command
 *
 * @param args - Subcommand and arguments
 * @param context - Handler context
 */
export async function handleProvidersCommand(
  args: string,
  context: CommandHandlerContext
): Promise<void> {
  const { addMessage } = context;

  // Parse subcommand
  const parts = args.trim().split(/\s+/).filter(p => p.length > 0);
  const subcommand = parts[0] || 'list';

  if (subcommand === 'list') {
    await handleProvidersList(context);
  } else if (subcommand === 'test') {
    const language = parts[1];
    await handleProvidersTest(language, context);
  } else {
    addMessage(
      '❌ **Unknown subcommand**\n\n' +
        'Available commands:\n' +
        '- `/providers list` - List installed providers\n' +
        '- `/providers test <language>` - Test provider availability\n\n' +
        'Examples:\n' +
        '- `/providers list`\n' +
        '- `/providers test python`',
      MessageType.ERROR,
      true
    );
  }
}

/**
 * Command metadata for registration
 */
export const providersCommandMetadata = {
  name: 'providers',
  aliases: ['provider', 'p'],
  description: 'Manage AST providers',
  usage: '/providers [list|test]',
  requiresIPC: true,
  handler: handleProvidersCommand,
};
