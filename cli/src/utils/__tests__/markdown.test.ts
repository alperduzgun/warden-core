/**
 * Unit tests for markdown utilities
 */

import { describe, it, expect } from '@jest/globals';
import {
  stripMarkdown,
  hasCodeBlocks,
  extractCodeBlocks,
  formatInlineCode,
  formatBold,
  formatItalic,
  formatHeaders,
  formatLists,
  truncateText,
  wordWrap,
  getTextWidth,
  padText,
  highlightCode,
} from '../markdown.js';

describe('markdown utilities', () => {
  describe('stripMarkdown', () => {
    it('should strip code blocks', () => {
      const input = '```javascript\nconst x = 1;\n```';
      const result = stripMarkdown(input);
      expect(result).not.toContain('```');
    });

    it('should strip inline code', () => {
      const input = 'Use `console.log()` to debug';
      const result = stripMarkdown(input);
      expect(result).toBe('Use console.log() to debug');
    });

    it('should strip bold', () => {
      const input = 'This is **bold** text';
      const result = stripMarkdown(input);
      expect(result).toBe('This is bold text');
    });

    it('should strip italic', () => {
      const input = 'This is *italic* text';
      const result = stripMarkdown(input);
      expect(result).toBe('This is italic text');
    });

    it('should strip headers', () => {
      const input = '## Heading 2';
      const result = stripMarkdown(input);
      expect(result).toBe('Heading 2');
    });

    it('should convert lists to bullets', () => {
      const input = '- Item 1\n- Item 2';
      const result = stripMarkdown(input);
      expect(result).toContain('• Item 1');
    });

    it('should strip links', () => {
      const input = '[Click here](https://example.com)';
      const result = stripMarkdown(input);
      expect(result).toBe('Click here');
    });
  });

  describe('hasCodeBlocks', () => {
    it('should detect code blocks', () => {
      const text = '```javascript\ncode\n```';
      expect(hasCodeBlocks(text)).toBe(true);
    });

    it('should return false for no code blocks', () => {
      const text = 'Regular text without code blocks';
      expect(hasCodeBlocks(text)).toBe(false);
    });
  });

  describe('extractCodeBlocks', () => {
    it('should extract code block with language', () => {
      const markdown = '```javascript\nconst x = 1;\n```';
      const blocks = extractCodeBlocks(markdown);
      expect(blocks.length).toBe(1);
      expect(blocks[0].language).toBe('javascript');
      expect(blocks[0].code).toBe('const x = 1;\n');
    });

    it('should extract code block without language', () => {
      const markdown = '```\nplain code\n```';
      const blocks = extractCodeBlocks(markdown);
      expect(blocks.length).toBe(1);
      expect(blocks[0].language).toBe('text');
    });

    it('should extract multiple code blocks', () => {
      const markdown = '```js\ncode1\n```\n\n```python\ncode2\n```';
      const blocks = extractCodeBlocks(markdown);
      expect(blocks.length).toBe(2);
    });

    it('should return empty array for no code blocks', () => {
      const markdown = 'No code here';
      const blocks = extractCodeBlocks(markdown);
      expect(blocks).toEqual([]);
    });
  });

  describe('formatInlineCode', () => {
    it('should format inline code with ANSI colors', () => {
      const text = 'Use `const` keyword';
      const result = formatInlineCode(text);
      expect(result).toContain('\x1b[36m');
      expect(result).toContain('\x1b[0m');
    });

    it('should handle multiple inline codes', () => {
      const text = 'Use `const` or `let` keyword';
      const result = formatInlineCode(text);
      expect(result.match(/\x1b\[36m/g)?.length).toBe(2);
    });
  });

  describe('formatBold', () => {
    it('should format bold text with ANSI codes', () => {
      const text = 'This is **bold**';
      const result = formatBold(text);
      expect(result).toContain('\x1b[1m');
      expect(result).toContain('\x1b[0m');
    });
  });

  describe('formatItalic', () => {
    it('should format italic text with ANSI codes', () => {
      const text = 'This is *italic*';
      const result = formatItalic(text);
      expect(result).toContain('\x1b[3m');
      expect(result).toContain('\x1b[0m');
    });
  });

  describe('truncateText', () => {
    it('should truncate long text', () => {
      const text = 'This is a very long text that should be truncated';
      const result = truncateText(text, 20);
      expect(result.length).toBeLessThanOrEqual(20);
      expect(result).toContain('...');
    });

    it('should not truncate short text', () => {
      const text = 'Short text';
      const result = truncateText(text, 20);
      expect(result).toBe(text);
    });

    it('should use custom suffix', () => {
      const text = 'Long text';
      const result = truncateText(text, 5, '>>');
      expect(result).toContain('>>');
    });
  });

  describe('wordWrap', () => {
    it('should wrap text at word boundaries', () => {
      const text = 'This is a long line that should wrap';
      const result = wordWrap(text, 20);
      expect(result.split('\n').length).toBeGreaterThan(1);
    });

    it('should handle single word longer than width', () => {
      const text = 'supercalifragilisticexpialidocious';
      const result = wordWrap(text, 10);
      expect(result).toBeDefined();
    });

    it('should preserve single line if within width', () => {
      const text = 'Short text';
      const result = wordWrap(text, 50);
      expect(result).toBe(text);
    });
  });

  describe('getTextWidth', () => {
    it('should get width of plain text', () => {
      const text = 'Hello';
      expect(getTextWidth(text)).toBe(5);
    });

    it('should ignore ANSI escape codes', () => {
      const text = '\x1b[31mHello\x1b[0m';
      expect(getTextWidth(text)).toBe(5);
    });

    it('should handle multiple ANSI codes', () => {
      const text = '\x1b[1m\x1b[31mBold Red\x1b[0m';
      expect(getTextWidth(text)).toBe(8);
    });
  });

  describe('padText', () => {
    it('should pad left by default', () => {
      const text = 'Hello';
      const result = padText(text, 10);
      expect(result.length).toBe(10);
      expect(result.startsWith('Hello')).toBe(true);
    });

    it('should pad right', () => {
      const text = 'Hello';
      const result = padText(text, 10, 'right');
      expect(result.length).toBe(10);
      expect(result.endsWith('Hello')).toBe(true);
    });

    it('should pad center', () => {
      const text = 'Hi';
      const result = padText(text, 10, 'center');
      expect(result.length).toBe(10);
      expect(result.includes('Hi')).toBe(true);
    });

    it('should handle text already at width', () => {
      const text = 'Hello';
      const result = padText(text, 5);
      expect(result).toBe(text);
    });
  });

  describe('highlightCode', () => {
    it('should highlight Python keywords', () => {
      const code = 'def hello():\n    return True';
      const result = highlightCode(code, 'python');
      expect(result).toContain('\x1b[35m'); // keyword color
    });

    it('should highlight JavaScript keywords', () => {
      const code = 'const x = 1;';
      const result = highlightCode(code, 'javascript');
      expect(result).toContain('\x1b[35m'); // keyword color
    });

    it('should highlight strings', () => {
      const code = 'const str = "hello";';
      const result = highlightCode(code, 'javascript');
      expect(result).toContain('\x1b[32m'); // string color
    });

    it('should return code as-is for unknown language', () => {
      const code = 'some code';
      const result = highlightCode(code, 'unknown');
      expect(result).toBe(code);
    });
  });
});
