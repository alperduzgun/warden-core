/**
 * Config Loader - Load .warden/config.yaml
 */

import {existsSync, readFileSync} from 'fs';
import {join} from 'path';
import yaml from 'yaml';

import type {FrameConfig} from '../lib/types.js';

export interface WardenConfig {
  project: {
    name: string;
    description: string;
    language: string;
    sdk_version: string;
    framework?: string;
    project_type?: string;
  };
  llm?: {
    provider: string;
    model: string;
    azure?: {
      endpoint: string;
      api_key: string;
      deployment_name?: string;
      api_version?: string;
    };
    fallback?: {
      provider: string;
      api_key: string;
    };
    timeout?: number;
    max_retries?: number;
  };
  frames: string[];
  frames_config?: Record<string, any>;
  ci?: {
    enabled: boolean;
    fail_on_blocker: boolean;
    output: Array<{format: string; path: string}>;
  };
  advanced?: {
    max_workers: number;
    frame_timeout: number;
    debug: boolean;
  };
}

export class ConfigLoader {
  private config: WardenConfig | null = null;
  private configPath: string;

  constructor(projectRoot: string = process.cwd()) {
    this.configPath = join(projectRoot, '.warden', 'config.yaml');
  }

  /**
   * Load config from .warden/config.yaml
   */
  load(): WardenConfig | null {
    if (this.config) {
      return this.config;
    }

    if (!existsSync(this.configPath)) {
      return null;
    }

    try {
      const content = readFileSync(this.configPath, 'utf-8');
      const rawConfig = yaml.parse(content);

      // Resolve environment variables in config
      this.config = this.resolveEnvVars(rawConfig);
      return this.config;
    } catch (error) {
      console.error('Failed to load config:', error);
      return null;
    }
  }

  /**
   * Get config (load if not loaded)
   */
  getConfig(): WardenConfig | null {
    return this.config || this.load();
  }

  /**
   * Get LLM config from .warden/config.yaml
   */
  getLLMConfig(): WardenConfig['llm'] | null {
    const config = this.getConfig();
    return config?.llm || null;
  }

  /**
   * Get available frames from config
   */
  getFrames(): string[] {
    const config = this.getConfig();
    return config?.frames || [];
  }

  /**
   * Get frame config
   */
  getFrameConfig(frameName: string): FrameConfig | null {
    const config = this.getConfig();
    return config?.frames_config?.[frameName] || null;
  }

  /**
   * Resolve environment variables in config
   */
  private resolveEnvVars<T>(obj: T): T {
    if (typeof obj === 'string') {
      // Replace ${VAR} with process.env.VAR
      const resolved = obj.replace(/\$\{([^}]+)\}/g, (_match: string, varName: string) => {
        return process.env[varName] || _match;
      });
      return resolved as T;
    }

    if (Array.isArray(obj)) {
      return obj.map(item => this.resolveEnvVars(item)) as T;
    }

    if (obj && typeof obj === 'object') {
      const resolved: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
        resolved[key] = this.resolveEnvVars(value);
      }
      return resolved as T;
    }

    return obj;
  }

  /**
   * Check if config exists
   */
  exists(): boolean {
    return existsSync(this.configPath);
  }

  /**
   * Get config path
   */
  getConfigPath(): string {
    return this.configPath;
  }
}

// Singleton instance
export const configLoader = new ConfigLoader();
