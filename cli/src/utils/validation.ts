/**
 * Validation Utilities
 *
 * Input validation and sanitization functions
 */

import { z } from 'zod';

/**
 * Validate environment configuration
 */
export const envSchema = z.object({
  WARDEN_API_URL: z.string().url().optional().default('http://localhost:8000'),
  WARDEN_API_KEY: z.string().optional(),
  WARDEN_TIMEOUT: z.string().regex(/^\d+$/).optional().default('30000'),
  WARDEN_MAX_RETRIES: z.string().regex(/^\d+$/).optional().default('3'),
  WARDEN_LOG_LEVEL: z
    .enum(['debug', 'info', 'warn', 'error'])
    .optional()
    .default('info'),
});

/**
 * Validate user input
 */
export const userInputSchema = z
  .string()
  .min(1, 'Input cannot be empty')
  .max(10000, 'Input too long (max 10000 characters)')
  .trim();

/**
 * Validate session ID
 */
export const sessionIdSchema = z
  .string()
  .min(1)
  .regex(/^[a-zA-Z0-9_-]+$/, 'Invalid session ID format');

/**
 * Sanitize user input to prevent injection attacks
 */
export const sanitizeInput = (input: string): string => {
  return input
    .replace(/[<>]/g, '') // Remove angle brackets
    .trim();
};

/**
 * Validate API URL
 */
export const isValidApiUrl = (url: string): boolean => {
  try {
    const parsed = new URL(url);
    return ['http:', 'https:'].includes(parsed.protocol);
  } catch {
    return false;
  }
};

/**
 * Validate command format
 */
export const isValidCommand = (input: string): boolean => {
  return /^\/[a-z]+$/i.test(input);
};

/**
 * Parse command and arguments
 */
export const parseCommand = (input: string): { command: string; args: string[] } => {
  const parts = input.trim().split(/\s+/);
  const command = parts[0] ?? '';
  const args = parts.slice(1);

  return { command, args };
};
