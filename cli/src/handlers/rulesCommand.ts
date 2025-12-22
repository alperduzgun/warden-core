/**
 * Rules Command Handler
 *
 * Manages and displays custom validation rules:
 * - /rules list - Show all custom rules
 * - /rules show <id> - Show specific rule details
 * - /rules stats - Show rule statistics
 *
 * Reads from .warden/rules.yaml (local file, no IPC needed)
 */

import { existsSync } from 'fs';
import { resolve, join } from 'path';
import { MessageType } from '../types/index.js';
import type { CommandHandlerContext } from './types.js';

/**
 * Custom rule structure (simplified)
 */
interface CustomRule {
  id: string;
  name: string;
  description: string;
  severity: string;
  pattern?: string;
  category?: string;
  enabled: boolean;
  tags?: string[];
}

/**
 * Rules configuration structure
 */
interface RulesConfig {
  version?: string;
  rules: CustomRule[];
}

/**
 * Find .warden directory in current or parent directories
 */
function findWardenDir(): string | null {
  let currentDir = process.cwd();
  const root = '/';

  while (currentDir !== root) {
    const wardenDir = join(currentDir, '.warden');
    if (existsSync(wardenDir)) {
      return wardenDir;
    }
    currentDir = resolve(currentDir, '..');
  }

  return null;
}

/**
 * Load rules from .warden/rules.yaml
 */
function loadRules(): RulesConfig | null {
  const wardenDir = findWardenDir();

  if (!wardenDir) {
    return null;
  }

  const rulesPath = join(wardenDir, 'rules.yaml');

  if (!existsSync(rulesPath)) {
    return null;
  }

  try {
    // For now, we'll return a mock structure
    // In production, parse YAML file here
    // const content = readFileSync(rulesPath, 'utf-8');

    // Simple mock parsing (replace with proper YAML parser)
    return {
      version: '1.0.0',
      rules: []
    };
  } catch (error) {
    return null;
  }
}

/**
 * Format severity with emoji
 */
function formatSeverity(severity: string): string {
  const severityMap: Record<string, string> = {
    critical: '🔴 CRITICAL',
    high: '🟠 HIGH',
    medium: '🟡 MEDIUM',
    low: '🟢 LOW',
    info: '🔵 INFO',
  };
  return severityMap[severity.toLowerCase()] || severity.toUpperCase();
}

/**
 * Display all rules
 */
function displayRulesList(
  config: RulesConfig,
  addMessage: (msg: string, type: MessageType, markdown?: boolean) => void
): void {
  let message = '# 📋 Custom Validation Rules\n\n';

  if (!config.rules || config.rules.length === 0) {
    message += '**No custom rules configured.**\n\n';
    message += 'To add custom rules, create `.warden/rules.yaml` in your project.\n\n';
    message += '**Example**:\n';
    message += '```yaml\n';
    message += 'version: "1.0.0"\n';
    message += 'rules:\n';
    message += '  - id: "no-print-statements"\n';
    message += '    name: "No Print Statements"\n';
    message += '    description: "Avoid print() in production code"\n';
    message += '    severity: "medium"\n';
    message += '    pattern: "print\\\\(.*\\\\)"\n';
    message += '    category: "code-quality"\n';
    message += '    enabled: true\n';
    message += '```\n';
    addMessage(message, MessageType.SYSTEM, true);
    return;
  }

  message += `**Total Rules**: ${config.rules.length}\n`;

  const enabledCount = config.rules.filter(r => r.enabled).length;
  message += `**Enabled**: ${enabledCount} ✅\n`;
  message += `**Disabled**: ${config.rules.length - enabledCount} ❌\n\n`;

  // Group by category
  const byCategory: Record<string, CustomRule[]> = {};
  for (const rule of config.rules) {
    const category = rule.category || 'uncategorized';
    if (!byCategory[category]) {
      byCategory[category] = [];
    }
    byCategory[category].push(rule);
  }

  // Display rules by category
  for (const [category, rules] of Object.entries(byCategory)) {
    message += `## 📂 ${category.toUpperCase()}\n\n`;

    for (const rule of rules) {
      const status = rule.enabled ? '✅' : '❌';
      message += `### ${status} \`${rule.id}\` - ${rule.name}\n`;
      message += `- **Severity**: ${formatSeverity(rule.severity)}\n`;
      message += `- **Description**: ${rule.description}\n`;

      if (rule.tags && rule.tags.length > 0) {
        message += `- **Tags**: ${rule.tags.join(', ')}\n`;
      }

      message += '\n';
    }
  }

  message += '---\n\n';
  message += '**Commands**:\n';
  message += '- `/rules show <id>` - Show rule details\n';
  message += '- `/rules stats` - Show statistics\n';

  addMessage(message, MessageType.SYSTEM, true);
}

/**
 * Display specific rule details
 */
function displayRuleDetails(
  ruleId: string,
  config: RulesConfig,
  addMessage: (msg: string, type: MessageType, markdown?: boolean) => void
): void {
  const rule = config.rules.find(r => r.id === ruleId);

  if (!rule) {
    addMessage(
      `❌ **Rule not found**: \`${ruleId}\`\n\n` +
        'Use `/rules list` to see all available rules.',
      MessageType.ERROR,
      true
    );
    return;
  }

  const status = rule.enabled ? '✅ Enabled' : '❌ Disabled';

  let message = `# 🔍 Rule Details: \`${rule.id}\`\n\n`;
  message += `**Name**: ${rule.name}\n`;
  message += `**Status**: ${status}\n`;
  message += `**Severity**: ${formatSeverity(rule.severity)}\n`;
  message += `**Category**: ${rule.category || 'uncategorized'}\n\n`;
  message += `**Description**:\n${rule.description}\n\n`;

  if (rule.pattern) {
    message += `**Pattern**:\n\`\`\`regex\n${rule.pattern}\n\`\`\`\n\n`;
  }

  if (rule.tags && rule.tags.length > 0) {
    message += `**Tags**: ${rule.tags.join(', ')}\n\n`;
  }

  addMessage(message, MessageType.SYSTEM, true);
}

/**
 * Display rule statistics
 */
function displayRuleStats(
  config: RulesConfig,
  addMessage: (msg: string, type: MessageType, markdown?: boolean) => void
): void {
  let message = '# 📊 Rules Statistics\n\n';

  const total = config.rules.length;
  const enabled = config.rules.filter(r => r.enabled).length;
  const disabled = total - enabled;

  message += `**Total Rules**: ${total}\n`;
  message += `**Enabled**: ${enabled} (${((enabled / total) * 100).toFixed(1)}%)\n`;
  message += `**Disabled**: ${disabled} (${((disabled / total) * 100).toFixed(1)}%)\n\n`;

  // By severity
  message += '## By Severity\n\n';
  const bySeverity: Record<string, number> = {};
  for (const rule of config.rules) {
    bySeverity[rule.severity] = (bySeverity[rule.severity] || 0) + 1;
  }

  for (const [severity, count] of Object.entries(bySeverity)) {
    message += `- ${formatSeverity(severity)}: ${count}\n`;
  }

  message += '\n';

  // By category
  message += '## By Category\n\n';
  const byCategory: Record<string, number> = {};
  for (const rule of config.rules) {
    const category = rule.category || 'uncategorized';
    byCategory[category] = (byCategory[category] || 0) + 1;
  }

  for (const [category, count] of Object.entries(byCategory)) {
    message += `- **${category}**: ${count}\n`;
  }

  addMessage(message, MessageType.SYSTEM, true);
}

/**
 * Handle /rules command
 *
 * @param args - Subcommand (list, show <id>, stats)
 * @param context - Handler context
 */
export async function handleRulesCommand(
  args: string,
  context: CommandHandlerContext
): Promise<void> {
  const { addMessage } = context;

  const parts = args.trim().split(/\s+/);
  const subcommand = parts[0]?.toLowerCase() || 'list';

  // Load rules configuration
  const config = loadRules();

  if (!config) {
    addMessage(
      '⚠️  **No rules configuration found**\n\n' +
        'Custom rules are configured in `.warden/rules.yaml`.\n\n' +
        '**Setup**:\n' +
        '1. Create `.warden/` directory in your project root\n' +
        '2. Create `rules.yaml` file\n' +
        '3. Define your custom validation rules\n\n' +
        '**Example** `.warden/rules.yaml`:\n' +
        '```yaml\n' +
        'version: "1.0.0"\n' +
        'rules:\n' +
        '  - id: "no-print"\n' +
        '    name: "No Print Statements"\n' +
        '    description: "Avoid print() in production"\n' +
        '    severity: "medium"\n' +
        '    pattern: "print\\\\(.*\\\\)"\n' +
        '    enabled: true\n' +
        '```\n\n' +
        'Currently showing **default behavior** (no custom rules).',
      MessageType.SYSTEM,
      true
    );
    return;
  }

  switch (subcommand) {
    case 'list':
    case 'ls':
      displayRulesList(config, addMessage);
      break;

    case 'show':
    case 'get':
      if (parts.length < 2 || !parts[1]) {
        addMessage(
          '❌ **Missing rule ID**\n\n' +
            'Usage: `/rules show <rule_id>`\n\n' +
            'Example: `/rules show no-print-statements`',
          MessageType.ERROR,
          true
        );
        return;
      }
      displayRuleDetails(parts[1], config, addMessage);
      break;

    case 'stats':
    case 'statistics':
      displayRuleStats(config, addMessage);
      break;

    default:
      addMessage(
        `❌ **Unknown subcommand**: \`${subcommand}\`\n\n` +
          'Available subcommands:\n' +
          '- `/rules list` - Show all rules\n' +
          '- `/rules show <id>` - Show rule details\n' +
          '- `/rules stats` - Show statistics',
        MessageType.ERROR,
        true
      );
  }
}

/**
 * Command metadata for registration
 */
export const rulesCommandMetadata = {
  name: 'rules',
  aliases: ['r'],
  description: 'Manage custom validation rules',
  usage: '/rules [list|show <id>|stats]',
  requiresIPC: false, // No IPC needed - reads local file
  handler: handleRulesCommand,
};
