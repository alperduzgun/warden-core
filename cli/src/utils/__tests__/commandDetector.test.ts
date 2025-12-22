/**
 * Unit tests for command detection utilities
 */

import { describe, it, expect } from '@jest/globals';
import {
  detectCommand,
  getAutocompleteSuggestions,
  isValidCommand,
  formatCommand,
  extractMentions,
  extractAlerts,
  parseComplexInput,
} from '../commandDetector.js';
import { CommandType } from '../../types/index.js';

describe('commandDetector', () => {
  describe('detectCommand', () => {
    it('should detect slash commands', () => {
      const result = detectCommand('/help');
      expect(result.type).toBe(CommandType.SLASH);
      expect(result.command).toBe('help');
      expect(result.args).toBeUndefined();
    });

    it('should detect slash commands with arguments', () => {
      const result = detectCommand('/analyze src/index.ts');
      expect(result.type).toBe(CommandType.SLASH);
      expect(result.command).toBe('analyze');
      expect(result.args).toBe('src/index.ts');
    });

    it('should detect mention commands', () => {
      const result = detectCommand('@file:src/App.tsx');
      expect(result.type).toBe(CommandType.MENTION);
      expect(result.command).toBe('file');
      expect(result.args).toBe('src/App.tsx');
    });

    it('should detect alert commands', () => {
      const result = detectCommand('!critical');
      expect(result.type).toBe(CommandType.ALERT);
      expect(result.command).toBe('critical');
    });

    it('should return NONE for regular text', () => {
      const result = detectCommand('This is regular text');
      expect(result.type).toBe(CommandType.NONE);
      expect(result.command).toBeUndefined();
    });

    it('should return NONE for empty input', () => {
      const result = detectCommand('');
      expect(result.type).toBe(CommandType.NONE);
    });

    it('should handle whitespace', () => {
      const result = detectCommand('   /help   ');
      expect(result.type).toBe(CommandType.SLASH);
      expect(result.command).toBe('help');
    });
  });

  describe('getAutocompleteSuggestions', () => {
    it('should return all slash commands for "/" input', () => {
      const suggestions = getAutocompleteSuggestions('/');
      expect(suggestions.length).toBeGreaterThan(0);
      expect(suggestions[0].type).toBe(CommandType.SLASH);
    });

    it('should filter suggestions by partial match', () => {
      const suggestions = getAutocompleteSuggestions('/ana');
      const analyzeCmd = suggestions.find((s) => s.command === '/analyze');
      expect(analyzeCmd).toBeDefined();
    });

    it('should return empty array for non-command input', () => {
      const suggestions = getAutocompleteSuggestions('regular text');
      expect(suggestions).toEqual([]);
    });

    it('should return mention suggestions for @ input', () => {
      const suggestions = getAutocompleteSuggestions('@');
      expect(suggestions.length).toBeGreaterThan(0);
      expect(suggestions[0].type).toBe(CommandType.MENTION);
    });
  });

  describe('isValidCommand', () => {
    it('should return true for valid slash command', () => {
      const detection = detectCommand('/help');
      expect(isValidCommand(detection)).toBe(true);
    });

    it('should return false for invalid slash command', () => {
      const detection = detectCommand('/invalidcommand');
      expect(isValidCommand(detection)).toBe(false);
    });

    it('should return false for NONE type', () => {
      const detection = detectCommand('regular text');
      expect(isValidCommand(detection)).toBe(false);
    });

    it('should return true for valid mention command', () => {
      const detection = detectCommand('@file:test.ts');
      expect(isValidCommand(detection)).toBe(true);
    });

    it('should return true for valid alert command', () => {
      const detection = detectCommand('!critical');
      expect(isValidCommand(detection)).toBe(true);
    });
  });

  describe('formatCommand', () => {
    it('should format slash command without args', () => {
      const detection = detectCommand('/help');
      expect(formatCommand(detection)).toBe('/help');
    });

    it('should format slash command with args', () => {
      const detection = detectCommand('/analyze src/App.tsx');
      expect(formatCommand(detection)).toBe('/analyze src/App.tsx');
    });

    it('should format mention command', () => {
      const detection = detectCommand('@file:test.ts');
      expect(formatCommand(detection)).toBe('@file:test.ts');
    });

    it('should return raw input for NONE type', () => {
      const detection = detectCommand('regular text');
      expect(formatCommand(detection)).toBe('regular text');
    });
  });

  describe('extractMentions', () => {
    it('should extract single mention', () => {
      const mentions = extractMentions('Check @file:src/App.tsx');
      expect(mentions).toContain('@file:src/App.tsx');
    });

    it('should extract multiple mentions', () => {
      const mentions = extractMentions('Compare @file:src/A.tsx and @file:src/B.tsx');
      expect(mentions.length).toBe(2);
    });

    it('should return empty array for no mentions', () => {
      const mentions = extractMentions('No mentions here');
      expect(mentions).toEqual([]);
    });

    it('should handle mention without args', () => {
      const mentions = extractMentions('Reference @config');
      expect(mentions).toContain('@config');
    });
  });

  describe('extractAlerts', () => {
    it('should extract single alert', () => {
      const alerts = extractAlerts('This is !critical');
      expect(alerts).toContain('!critical');
    });

    it('should extract multiple alerts', () => {
      const alerts = extractAlerts('Mark as !high and !critical');
      expect(alerts.length).toBe(2);
    });

    it('should return empty array for no alerts', () => {
      const alerts = extractAlerts('No alerts here');
      expect(alerts).toEqual([]);
    });
  });

  describe('parseComplexInput', () => {
    it('should parse input with slash command', () => {
      const result = parseComplexInput('/analyze src/App.tsx');
      expect(result.primaryCommand?.type).toBe(CommandType.SLASH);
      expect(result.primaryCommand?.command).toBe('analyze');
    });

    it('should parse input with mentions', () => {
      const result = parseComplexInput('Check @file:test.ts');
      expect(result.mentions.length).toBeGreaterThan(0);
    });

    it('should parse input with alerts', () => {
      const result = parseComplexInput('This is !critical');
      expect(result.alerts.length).toBeGreaterThan(0);
    });

    it('should extract plain text', () => {
      const result = parseComplexInput('/analyze @file:test.ts !high check this');
      expect(result.plainText.length).toBeGreaterThan(0);
    });

    it('should handle complex mixed input', () => {
      const result = parseComplexInput('/analyze @file:src/App.tsx !critical fix security issue');
      expect(result.primaryCommand?.type).toBe(CommandType.SLASH);
      expect(result.mentions.length).toBeGreaterThan(0);
      expect(result.alerts.length).toBeGreaterThan(0);
      expect(result.plainText).toContain('fix security issue');
    });
  });
});
