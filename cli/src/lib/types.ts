/**
 * Warden CLI Types
 * Type definitions for the Warden CLI
 */

export interface ScanResult {
  success: boolean;
  filesScanned: number;
  issues: Issue[];
  duration: number;
  summary: {
    critical: number;
    high: number;
    medium: number;
    low: number;
  };
}

export interface Issue {
  id: string;
  filePath: string;
  line: number;
  column: number;
  severity: Severity;
  message: string;
  rule: string;
  frame: string;
}

export type Severity = 'critical' | 'high' | 'medium' | 'low';

export interface ValidationResult {
  success: boolean;
  frame: string;
  issues: Issue[];
}

export interface StatusResponse {
  connected: boolean;
  version: string;
  sessionId: string;
  projectPath: string;
  framesAvailable: string[];
}

export interface IPCResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
}

/**
 * Command result types
 */
export type CommandData = ScanResult | ValidationResult | ConfigResult;

export interface CommandResult {
  success: boolean;
  data?: CommandData;
  error?: string;
}

export interface ConfigResult {
  version: string;
  project_path: string;
  session_id: string;
  frames_available: string[];
}

/**
 * LLM message types
 */
export interface LLMMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

/**
 * File picker types
 */
export interface FileItem {
  label: string;
  value: string;
  isDirectory: boolean;
}

/**
 * Frame configuration types
 */
export interface FrameConfig {
  enabled: boolean;
  options: Record<string, string | number | boolean>;
}

/**
 * Validation Frame metadata
 */
export interface Frame {
  id: string;
  name: string;
  description: string;
  priority: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  is_blocker: boolean;
  tags?: string[];
}
