/**
 * Warden API Client
 *
 * HTTP client for communicating with the Warden backend
 */

import axios, { type AxiosInstance, type AxiosError } from 'axios';
import { logger } from '../utils/logger.js';
import type {
  APIClient,
  WardenConfig,
  WardenResponse,
  ChatSession,
  ValidationResult,
} from '../types/warden.js';

/**
 * Create configured axios instance
 */
const createAxiosInstance = (config: WardenConfig): AxiosInstance => {
  const instance = axios.create({
    baseURL: config.apiUrl,
    ...(config.timeout !== undefined && { timeout: config.timeout }),
    headers: {
      'Content-Type': 'application/json',
      ...(config.apiKey && { Authorization: `Bearer ${config.apiKey}` }),
    },
  });

  // Request interceptor
  instance.interceptors.request.use(
    (config) => {
      logger.debug('API Request', {
        method: config.method,
        url: config.url,
      });
      return config;
    },
    (error: Error) => {
      logger.error('Request error', error);
      return Promise.reject(error);
    }
  );

  // Response interceptor
  instance.interceptors.response.use(
    (response) => {
      logger.debug('API Response', {
        status: response.status,
        url: response.config.url,
      });
      return response;
    },
    (error: AxiosError) => {
      logger.error('Response error', error);
      return Promise.reject(error);
    }
  );

  return instance;
};

/**
 * Create API client instance
 */
export const createAPIClient = (config: WardenConfig): APIClient => {
  const client = createAxiosInstance(config);

  return {
    /**
     * Send a chat message
     */
    chat: async (message: string, sessionId: string): Promise<WardenResponse> => {
      try {
        const response = await client.post<WardenResponse>('/api/v1/chat', {
          message,
          session_id: sessionId,
        });

        return response.data;
      } catch (error) {
        logger.error('Chat request failed', error);
        throw new Error(
          error instanceof Error ? error.message : 'Failed to send message'
        );
      }
    },

    /**
     * Run validation
     */
    validate: async (config: Record<string, unknown>): Promise<ValidationResult[]> => {
      try {
        const response = await client.post<{ validations: ValidationResult[] }>(
          '/api/v1/validate',
          config
        );

        return response.data.validations;
      } catch (error) {
        logger.error('Validation request failed', error);
        throw new Error(
          error instanceof Error ? error.message : 'Failed to run validation'
        );
      }
    },

    /**
     * Get session by ID
     */
    getSession: async (sessionId: string): Promise<ChatSession> => {
      try {
        const response = await client.get<ChatSession>(
          `/api/v1/sessions/${sessionId}`
        );

        return response.data;
      } catch (error) {
        logger.error('Get session failed', error);
        throw new Error(
          error instanceof Error ? error.message : 'Failed to get session'
        );
      }
    },

    /**
     * Create new session
     */
    createSession: async (): Promise<ChatSession> => {
      try {
        const response = await client.post<ChatSession>('/api/v1/sessions');

        return response.data;
      } catch (error) {
        logger.error('Create session failed', error);
        throw new Error(
          error instanceof Error ? error.message : 'Failed to create session'
        );
      }
    },
  };
};

/**
 * Test API connection
 */
export const testConnection = async (config: WardenConfig): Promise<boolean> => {
  try {
    const client = createAxiosInstance(config);
    await client.get('/health');
    logger.info('API connection successful');
    return true;
  } catch (error) {
    logger.error('API connection failed', error);
    return false;
  }
};
