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
  enabled?: boolean;
  tags?: string[];
}

/**
 * Pipeline execution event types
 */
export type PipelineEventType =
  | 'pipeline_started'
  | 'pipeline_completed'
  | 'pipeline_failed'
  | 'phase_started'
  | 'phase_completed'
  | 'frame_started'
  | 'frame_completed'
  | 'result';

export interface PipelineEvent {
  type: 'progress' | 'result';
  event?: PipelineEventType;
  data: {
    phase?: string;
    frame?: string;
    status?: string;
    duration?: number;
    message?: string;
    [key: string]: unknown;
  };
}

export interface PipelineStreamResponse {
  events: AsyncIterableIterator<PipelineEvent>;
}

export interface LLMAnalysis {
  llm_enabled: boolean;
  llm_provider: string;
  phases_with_llm: string[];
  llm_quality_score?: number;
  llm_confidence?: number;
  llm_reasoning?: string;
}

export interface PipelineResult {
  pipeline_id: string;
  pipeline_name: string;
  status: string;
  duration: number;
  total_frames: number;
  frames_passed: number;
  frames_failed: number;
  frames_skipped: number;
  total_findings: number;
  critical_findings: number;
  high_findings: number;
  medium_findings: number;
  low_findings: number;
  frame_results: FrameResult[];
  context_summary?: {
    phases_completed: string[];
    errors: string[];
    [key: string]: unknown;
  };
  metadata?: Record<string, unknown>;
  llm_analysis?: LLMAnalysis;
}

export interface FrameResult {
  frame_id: string;
  frame_name: string;
  status: string;
  duration: number;
  issues_found: number;
  is_blocker: boolean;
  findings: Finding[];
}

export interface Finding {
  severity: string;
  message: string;
  line?: number;
  column?: number;
  code?: string;
  file?: string;
}

/**
 * Pre-flight check result types
 */
export interface PreFlightCheckResult {
  passed: boolean;
  checks: Array<{
    name: string;
    description: string;
    passed: boolean;
    error: string | null;
  }>;
}
