/**
 * Configuration Management
 *
 * Loads and validates application configuration
 */

import { envSchema } from '../utils/validation.js';
import { logger } from '../utils/logger.js';
import type { WardenConfig } from '../types/warden.js';

/**
 * Load configuration from environment variables
 */
export const loadConfig = (): WardenConfig => {
  try {
    const env = envSchema.parse(process.env);

    const config: WardenConfig = {
      apiUrl: env.WARDEN_API_URL,
      ...(env.WARDEN_API_KEY !== undefined && { apiKey: env.WARDEN_API_KEY }),
      timeout: parseInt(env.WARDEN_TIMEOUT, 10),
      maxRetries: parseInt(env.WARDEN_MAX_RETRIES, 10),
    };

    logger.debug('Configuration loaded', config);

    return config;
  } catch (error) {
    logger.error('Failed to load configuration', error);
    throw new Error('Invalid configuration. Check your environment variables.');
  }
};

/**
 * Validate configuration
 */
export const validateConfig = (config: WardenConfig): boolean => {
  if (!config.apiUrl) {
    logger.error('API URL is required');
    return false;
  }

  if (config.timeout && config.timeout < 1000) {
    logger.warn('Timeout is very low, may cause issues');
  }

  if (config.maxRetries && config.maxRetries > 10) {
    logger.warn('Max retries is very high');
  }

  return true;
};

/**
 * Get default configuration
 */
export const getDefaultConfig = (): WardenConfig => {
  return {
    apiUrl: 'http://localhost:8000',
    timeout: 30000,
    maxRetries: 3,
  };
};
