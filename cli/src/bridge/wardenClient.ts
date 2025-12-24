/**
 * Warden IPC Client - TypeScript wrapper for JSON-RPC communication
 *
 * Provides type-safe access to Warden's Python backend via IPC.
 */

import { spawn, ChildProcess } from 'child_process';
import { EventEmitter } from 'events';
import readline from 'readline';
import { Socket } from 'net';

// ============================================================================
// Types
// ============================================================================

export interface IPCRequest {
  jsonrpc: '2.0';
  method: string;
  params?: Record<string, any> | any[];
  id: string | number;
}

export interface IPCResponse<T = any> {
  jsonrpc: '2.0';
  result?: T;
  error?: IPCError;
  id: string | number;
}

export interface IPCError {
  code: number;
  message: string;
  data?: Record<string, any>;
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
  metadata: Record<string, any>;
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
  file?: string;  // Added file field for file path
}

export interface WardenConfig {
  version: string;
  llm_providers: LLMProvider[];
  default_provider: string;
  frames: FrameInfo[];
  total_frames: number;
}

export interface LLMProvider {
  name: string;
  model: string;
  endpoint: string;
  enabled: boolean;
}

export interface FrameInfo {
  id: string;
  name: string;
  description: string;
  priority: string;
  is_blocker: boolean;
  tags?: string[];
}

export interface ProviderInfo {
  name: string;
  languages: string[];
  priority: string;
  version: string;
  source: string;
}

export interface ProviderTestResult {
  available: boolean;
  providerName?: string;
  priority?: string;
  version?: string;
  validated?: boolean;
  language?: string;
  error?: string;
  supportedLanguages?: string[];
}

// ============================================================================
// Client Configuration
// ============================================================================

export interface WardenClientConfig {
  transport?: 'stdio' | 'socket';
  socketPath?: string;
  pythonPath?: string;
  timeoutMs?: number;
}

// ============================================================================
// Warden Client
// ============================================================================

export class WardenClient extends EventEmitter {
  private process: ChildProcess | null = null;
  private socket: Socket | null = null;
  private config: Required<WardenClientConfig>;
  private requestId = 0;
  private pendingRequests = new Map<number, {
    resolve: (value: any) => void;
    reject: (error: Error) => void;
  }>();

  constructor(config: WardenClientConfig = {}) {
    super();
    this.config = {
      transport: config.transport || 'socket',  // Default to socket (not stdio)
      socketPath: config.socketPath || '/tmp/warden-ipc.sock',
      pythonPath: config.pythonPath || 'python3',
      timeoutMs: config.timeoutMs || 30000,
    };
  }

  /**
   * Start the IPC connection to Warden backend
   */
  async connect(): Promise<void> {
    if (this.config.transport === 'socket') {
      await this.connectSocket();
    } else {
      await this.connectStdio();
    }

    // Verify connection with ping
    await this.ping();
  }

  /**
   * Connect via Unix socket (persistent connection to existing server)
   */
  private async connectSocket(): Promise<void> {
    if (this.socket && !this.socket.destroyed) {
      throw new Error('Already connected');
    }

    return new Promise((resolve, reject) => {
      this.socket = new Socket();

      // Set up response handling (line-delimited JSON)
      const rl = readline.createInterface({
        input: this.socket,
        crlfDelay: Infinity,
      });

      rl.on('line', (line) => {
        try {
          const response: IPCResponse = JSON.parse(line);
          this.handleResponse(response);
        } catch (error) {
          // Ignore non-JSON lines (e.g., server logs)
          if (line.trim().startsWith('{')) {
            this.emit('error', new Error(`Invalid JSON response: ${line}`));
          }
        }
      });

      // Handle socket events
      this.socket.on('connect', () => {
        resolve();
      });

      this.socket.on('error', (error) => {
        this.emit('error', error);
        reject(error);
      });

      this.socket.on('close', () => {
        this.emit('close');
        this.cleanup();
      });

      // Connect to Unix socket
      this.socket.connect(this.config.socketPath);
    });
  }

  /**
   * Connect via STDIO (spawn new Python process - legacy mode)
   */
  private async connectStdio(): Promise<void> {
    if (this.process) {
      throw new Error('Already connected');
    }

    // Spawn Python IPC server
    const args = [
      '-m',
      'warden.cli_bridge.server',
      '--transport',
      'stdio',
    ];

    this.process = spawn(this.config.pythonPath, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    // Set up response handling
    const rl = readline.createInterface({
      input: this.process.stdout!,
      crlfDelay: Infinity,
    });

    rl.on('line', (line) => {
      try {
        const response: IPCResponse = JSON.parse(line);
        this.handleResponse(response);
      } catch (error) {
        // Ignore non-JSON lines (e.g., server logs)
        if (line.trim().startsWith('{')) {
          this.emit('error', new Error(`Invalid JSON response: ${line}`));
        }
      }
    });

    // Handle errors
    this.process.stderr?.on('data', (data) => {
      this.emit('stderr', data.toString());
    });

    this.process.on('error', (error) => {
      this.emit('error', error);
    });

    this.process.on('exit', (code) => {
      this.emit('exit', code);
      this.cleanup();
    });
  }

  /**
   * Close the IPC connection
   */
  async disconnect(): Promise<void> {
    if (this.socket) {
      this.socket.destroy();
      this.cleanup();
    }
    if (this.process) {
      this.process.kill();
      this.cleanup();
    }
  }

  /**
   * Send a JSON-RPC request
   */
  private async request<T = any>(method: string, params?: any): Promise<T> {
    // Check connection
    const isSocketConnected = this.socket && !this.socket.destroyed;
    const isProcessConnected = this.process && !this.process.killed && this.process.stdin;

    if (!isSocketConnected && !isProcessConnected) {
      throw new Error('Not connected');
    }

    const id = ++this.requestId;
    const request: IPCRequest = {
      jsonrpc: '2.0',
      method,
      params,
      id,
    };

    return new Promise((resolve, reject) => {
      // Set up timeout
      const timeout = setTimeout(() => {
        this.pendingRequests.delete(id);
        reject(new Error(`Request timeout: ${method}`));
      }, this.config.timeoutMs);

      // Store pending request
      this.pendingRequests.set(id, {
        resolve: (value) => {
          clearTimeout(timeout);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timeout);
          reject(error);
        },
      });

      // Send request (socket or stdio)
      const message = JSON.stringify(request) + '\n';

      if (isSocketConnected) {
        this.socket!.write(message);
      } else if (isProcessConnected) {
        this.process!.stdin!.write(message);
      }
    });
  }

  /**
   * Handle JSON-RPC response
   */
  private handleResponse(response: IPCResponse): void {
    const pending = this.pendingRequests.get(response.id as number);
    if (!pending) {
      this.emit('error', new Error(`Unexpected response ID: ${response.id}`));
      return;
    }

    this.pendingRequests.delete(response.id as number);

    if (response.error) {
      const error = new Error(response.error.message);
      (error as any).code = response.error.code;
      (error as any).data = response.error.data;
      pending.reject(error);
    } else {
      pending.resolve(response.result);
    }
  }

  /**
   * Cleanup resources
   */
  private cleanup(): void {
    this.process = null;
    this.socket = null;
    this.pendingRequests.clear();
  }

  // ============================================================================
  // API Methods
  // ============================================================================

  /**
   * Health check
   */
  async ping(): Promise<{ status: string; message: string; timestamp: string }> {
    return this.request('ping');
  }

  /**
   * Execute validation pipeline on a file
   */
  async executePipeline(
    filePath: string,
    config?: Record<string, any>
  ): Promise<PipelineResult> {
    return this.request('execute_pipeline', { file_path: filePath, config });
  }

  /**
   * Execute validation pipeline with real-time streaming progress
   *
   * Yields progress events as they happen:
   * - { type: 'progress', event: 'pipeline_started', data: {...} }
   * - { type: 'progress', event: 'frame_started', data: { frame_name, ... } }
   * - { type: 'progress', event: 'frame_completed', data: { frame_name, issues_found, duration, ... } }
   * - { type: 'result', data: PipelineResult }
   *
   * @param filePath - Path to file to validate
   * @param config - Optional pipeline configuration
   * @yields Progress events and final result
   */
  async *executePipelineStream(
    filePath: string,
    config?: Record<string, any>
  ): AsyncGenerator<any> {
    // Check connection
    const isSocketConnected = this.socket && !this.socket.destroyed;
    const isProcessConnected = this.process && !this.process.killed && this.process.stdin;

    if (!isSocketConnected && !isProcessConnected) {
      throw new Error('Not connected');
    }

    const id = ++this.requestId;
    const request: IPCRequest = {
      jsonrpc: '2.0',
      method: 'execute_pipeline_stream',
      params: { file_path: filePath, config },
      id,
    };

    // Send request
    const message = JSON.stringify(request) + '\n';

    if (isSocketConnected) {
      this.socket!.write(message);
    } else if (isProcessConnected) {
      this.process!.stdin!.write(message);
    }

    // Read streaming responses (line-delimited JSON)
    // Each line is a separate JSON-RPC response with an event
    const eventQueue: any[] = [];
    let streamDone = false;
    let streamError: Error | null = null;

    // Set up temporary handler for this request
    const originalHandler = this.handleResponse.bind(this);

    // Override response handler temporarily for streaming
    const streamHandler = (response: IPCResponse) => {
      if (response.id === id) {
        if (response.error) {
          streamError = new Error(response.error.message);
          streamDone = true;
        } else if (response.result) {
          // Each response contains one event
          const event = response.result;
          eventQueue.push(event);

          // If this is the final result, mark stream as done
          if (event.type === 'result') {
            streamDone = true;
          }
        }
      } else {
        // Not our request, handle normally
        originalHandler(response);
      }
    };

    // Temporarily replace handler (hacky but works)
    this.handleResponse = streamHandler as any;

    try {
      // Yield events as they arrive
      while (!streamDone) {
        // Wait for next event
        while (eventQueue.length === 0 && !streamDone && !streamError) {
          await new Promise(resolve => setTimeout(resolve, 10));
        }

        // Check for errors
        if (streamError) {
          throw streamError;
        }

        // Yield all queued events
        while (eventQueue.length > 0) {
          const event = eventQueue.shift();
          yield event;

          // Stop if this was the final result
          if (event && event.type === 'result') {
            return;
          }
        }
      }
    } finally {
      // Restore original handler
      this.handleResponse = originalHandler as any;
    }
  }

  /**
   * Get Warden configuration
   */
  async getConfig(): Promise<WardenConfig> {
    return this.request('get_config');
  }

  /**
   * Get available validation frames
   */
  async getAvailableFrames(): Promise<FrameInfo[]> {
    return this.request('get_available_frames');
  }

  /**
   * Get available AST providers
   */
  async getAvailableProviders(): Promise<ProviderInfo[]> {
    return this.request('get_available_providers');
  }

  /**
   * Test if a language provider is available
   */
  async testProvider(language: string): Promise<ProviderTestResult> {
    return this.request('test_provider', { language });
  }

  /**
   * Analyze code with LLM
   *
   * Note: Currently returns all chunks at once. True streaming support coming soon.
   */
  async analyzeWithLLM(
    prompt: string,
    provider?: string
  ): Promise<AsyncIterator<string>> {
    const result = await this.request<{ chunks: string[]; streaming: boolean }>(
      'analyze_with_llm',
      { prompt, provider, stream: false }
    );

    // Convert to async iterator
    async function* generator() {
      for (const chunk of result.chunks) {
        yield chunk;
      }
    }

    return generator();
  }
}

export default WardenClient;
