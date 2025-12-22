/**
 * Markdown rendering utilities for Warden CLI
 *
 * Provides utilities for rendering markdown in terminal with syntax highlighting.
 */

/**
 * Simple markdown to styled text converter for terminal
 * This is a basic implementation - for production, consider using a library like marked-terminal
 */

/**
 * Strip markdown formatting for plain text display
 */
export function stripMarkdown(markdown: string): string {
  return markdown
    .replace(/`{3}[\s\S]*?`{3}/g, (match) => match.replace(/`/g, '')) // Code blocks
    .replace(/`([^`]+)`/g, '$1') // Inline code
    .replace(/\*\*([^*]+)\*\*/g, '$1') // Bold
    .replace(/\*([^*]+)\*/g, '$1') // Italic
    .replace(/^#+\s+/gm, '') // Headers
    .replace(/^\s*[-*+]\s+/gm, '• ') // Lists
    .replace(/^\s*\d+\.\s+/gm, '') // Numbered lists
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1'); // Links
}

/**
 * Detect if text contains code blocks
 */
export function hasCodeBlocks(text: string): boolean {
  return /`{3}/.test(text);
}

/**
 * Extract code blocks from markdown
 */
export function extractCodeBlocks(markdown: string): Array<{
  language: string;
  code: string;
  startIndex: number;
  endIndex: number;
}> {
  const blocks: Array<{
    language: string;
    code: string;
    startIndex: number;
    endIndex: number;
  }> = [];
  const regex = /```(\w*)\n([\s\S]*?)```/g;
  let match;

  while ((match = regex.exec(markdown)) !== null) {
    blocks.push({
      language: match[1] !== undefined ? match[1] : 'text',
      code: match[2] !== undefined ? match[2] : '',
      startIndex: match.index,
      endIndex: match.index + match[0].length,
    });
  }

  return blocks;
}

/**
 * Format inline code
 */
export function formatInlineCode(text: string): string {
  return text.replace(/`([^`]+)`/g, (_, code) => `\x1b[36m${code}\x1b[0m`);
}

/**
 * Format bold text
 */
export function formatBold(text: string): string {
  return text.replace(/\*\*([^*]+)\*\*/g, (_, content) => `\x1b[1m${content}\x1b[0m`);
}

/**
 * Format italic text
 */
export function formatItalic(text: string): string {
  return text.replace(/\*([^*]+)\*/g, (_, content) => `\x1b[3m${content}\x1b[0m`);
}

/**
 * Format headers
 */
export function formatHeaders(text: string): string {
  return text.replace(/^(#{1,6})\s+(.+)$/gm, (_, hashes, content) => {
    const level = hashes.length;
    if (level === 1) {
      return `\x1b[1;34m${content}\x1b[0m`;
    } else if (level === 2) {
      return `\x1b[1;36m${content}\x1b[0m`;
    }
    return `\x1b[1m${content}\x1b[0m`;
  });
}

/**
 * Format lists
 */
export function formatLists(text: string): string {
  return text
    .replace(/^\s*[-*+]\s+(.+)$/gm, '  • $1')
    .replace(/^\s*(\d+)\.\s+(.+)$/gm, '  $1. $2');
}

/**
 * Basic markdown formatting for terminal display
 */
export function formatMarkdown(markdown: string): string {
  let formatted = markdown;

  // Apply formatting in order
  formatted = formatHeaders(formatted);
  formatted = formatBold(formatted);
  formatted = formatItalic(formatted);
  formatted = formatInlineCode(formatted);
  formatted = formatLists(formatted);

  return formatted;
}

/**
 * Truncate text to fit within a specific width
 */
export function truncateText(text: string, maxWidth: number, suffix = '...'): string {
  if (text.length <= maxWidth) {
    return text;
  }
  return text.slice(0, maxWidth - suffix.length) + suffix;
}

/**
 * Word wrap text to fit within a specific width
 */
export function wordWrap(text: string, width: number): string {
  const words = text.split(' ');
  const lines: string[] = [];
  let currentLine = '';

  for (const word of words) {
    if (currentLine.length + word.length + 1 <= width) {
      currentLine += (currentLine ? ' ' : '') + word;
    } else {
      if (currentLine) {
        lines.push(currentLine);
      }
      currentLine = word;
    }
  }

  if (currentLine) {
    lines.push(currentLine);
  }

  return lines.join('\n');
}

/**
 * Get text width (accounting for ANSI escape codes)
 */
export function getTextWidth(text: string): number {
  // Remove ANSI escape codes
  const stripped = text.replace(/\x1b\[[0-9;]*m/g, '');
  return stripped.length;
}

/**
 * Pad text to a specific width
 */
export function padText(text: string, width: number, align: 'left' | 'center' | 'right' = 'left'): string {
  const textWidth = getTextWidth(text);
  const padding = Math.max(0, width - textWidth);

  if (align === 'center') {
    const leftPad = Math.floor(padding / 2);
    const rightPad = padding - leftPad;
    return ' '.repeat(leftPad) + text + ' '.repeat(rightPad);
  } else if (align === 'right') {
    return ' '.repeat(padding) + text;
  }

  return text + ' '.repeat(padding);
}

/**
 * Simple syntax highlighting for code
 */
export function highlightCode(code: string, language: string): string {
  // This is a very basic implementation
  // For production, consider using a proper syntax highlighter

  if (language === 'python') {
    return code
      .replace(/\b(def|class|import|from|return|if|else|elif|for|while|try|except|with|as)\b/g, `\x1b[35m$1\x1b[0m`)
      .replace(/(["'])(?:(?=(\\?))\2.)*?\1/g, `\x1b[32m$&\x1b[0m`)
      .replace(/\b(\d+)\b/g, `\x1b[33m$1\x1b[0m`)
      .replace(/#.*/g, `\x1b[90m$&\x1b[0m`);
  }

  if (language === 'javascript' || language === 'typescript') {
    return code
      .replace(/\b(const|let|var|function|class|import|export|return|if|else|for|while|try|catch|async|await)\b/g, `\x1b[35m$1\x1b[0m`)
      .replace(/(["'`])(?:(?=(\\?))\2.)*?\1/g, `\x1b[32m$&\x1b[0m`)
      .replace(/\b(\d+)\b/g, `\x1b[33m$1\x1b[0m`)
      .replace(/\/\/.*/g, `\x1b[90m$&\x1b[0m`)
      .replace(/\/\*[\s\S]*?\*\//g, `\x1b[90m$&\x1b[0m`);
  }

  return code;
}
