/**
 * Backend Manager - Auto-start and manage Warden backend server
 */

import {spawn, ChildProcess} from 'child_process';
import {existsSync, readFileSync, writeFileSync, unlinkSync} from 'fs';
import {join} from 'path';
import {logger} from './logger.js';

// Find project root by looking for start_ipc_server.py
const findProjectRoot = (): string => {
  let currentDir = process.cwd();

  // Check current directory and parent directories
  for (let i = 0; i < 5; i++) {
    const scriptPath = join(currentDir, 'start_ipc_server.py');
    if (existsSync(scriptPath)) {
      return currentDir;
    }
    const parentDir = join(currentDir, '..');
    if (parentDir === currentDir) break; // Reached root
    currentDir = parentDir;
  }

  // Default to parent of cli directory
  return join(process.cwd(), '..');
};

const PROJECT_ROOT = findProjectRoot();
const PID_FILE = join(PROJECT_ROOT, '.warden', 'backend.pid');
const BACKEND_SCRIPT = join(PROJECT_ROOT, 'start_ipc_server.py');
const SOCKET_PATH = '/tmp/warden-ipc.sock';
const HEALTH_CHECK_INTERVAL = 5000; // 5 seconds
const STARTUP_TIMEOUT = 10000; // 10 seconds

export class BackendManager {
  private process: ChildProcess | null = null;
  private healthCheckTimer: NodeJS.Timeout | null = null;
  private isShuttingDown = false;

  /**
   * Start the backend server
   */
  async start(): Promise<boolean> {
    // Check if already running
    if (this.isRunning()) {
      logger.info('backend_already_running', {pid: this.getPID()});
      return true;
    }

    // Check if backend script exists
    if (!existsSync(BACKEND_SCRIPT)) {
      logger.error('backend_script_not_found', {
        script_path: BACKEND_SCRIPT,
        project_root: PROJECT_ROOT,
      });
      throw new Error(`Backend script not found: ${BACKEND_SCRIPT}`);
    }

    logger.info('backend_starting', {
      script: BACKEND_SCRIPT,
      project_root: PROJECT_ROOT,
    });

    // Ensure .warden directory exists
    const wardenDir = join(PROJECT_ROOT, '.warden');
    if (!existsSync(wardenDir)) {
      await import('fs/promises').then(fs => fs.mkdir(wardenDir, {recursive: true}));
    }

    // Start backend process
    this.process = spawn('python3', [BACKEND_SCRIPT], {
      detached: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      cwd: PROJECT_ROOT, // Run from project root, not cli directory
    });

    // Save PID
    if (this.process.pid) {
      writeFileSync(PID_FILE, this.process.pid.toString());
    }

    // Capture stdout/stderr for debugging
    if (this.process.stdout) {
      this.process.stdout.on('data', (data) => {
        logger.debug('backend_stdout', {output: data.toString().trim()});
      });
    }

    if (this.process.stderr) {
      this.process.stderr.on('data', (data) => {
        const output = data.toString().trim();
        // Only log errors, not info messages
        if (output.includes('ERROR') || output.includes('Error') || output.includes('Traceback')) {
          logger.error('backend_stderr', {output});
        } else {
          logger.debug('backend_stderr', {output});
        }
      });
    }

    // Handle process events
    this.process.on('error', (error) => {
      console.error('Backend process error:', error);
    });

    this.process.on('exit', (code) => {
      if (!this.isShuttingDown) {
        console.error(`Backend exited unexpectedly with code ${code}`);
        this.cleanup();
      }
    });

    // Wait for server to be ready
    const isReady = await this.waitForReady();

    if (!isReady) {
      logger.error('backend_startup_timeout', {
        timeout_ms: STARTUP_TIMEOUT,
        socket_path: SOCKET_PATH,
      });
      throw new Error(`Backend failed to start within ${STARTUP_TIMEOUT}ms`);
    }

    logger.info('backend_started_successfully', {
      pid: this.process?.pid,
      socket_path: SOCKET_PATH,
    });

    // Start health check
    this.startHealthCheck();

    return true;
  }

  /**
   * Stop the backend server
   */
  async stop(): Promise<void> {
    this.isShuttingDown = true;

    // Stop health check
    if (this.healthCheckTimer) {
      clearInterval(this.healthCheckTimer);
      this.healthCheckTimer = null;
    }

    // Kill process
    if (this.process) {
      this.process.kill();
      this.process = null;
    }

    // Cleanup
    this.cleanup();
  }

  /**
   * Check if backend is running
   */
  isRunning(): boolean {
    // Check PID file
    if (!existsSync(PID_FILE)) {
      return false;
    }

    try {
      const pid = parseInt(readFileSync(PID_FILE, 'utf-8'));

      // Check if process exists
      try {
        process.kill(pid, 0); // Signal 0 = check if process exists
        return true;
      } catch {
        // Process doesn't exist
        this.cleanup();
        return false;
      }
    } catch {
      return false;
    }
  }

  /**
   * Health check - ping backend
   */
  async healthCheck(): Promise<boolean> {
    try {
      // Check if socket exists
      if (!existsSync(SOCKET_PATH)) {
        logger.debug('health_check_socket_missing', {socket_path: SOCKET_PATH});
        return false;
      }

      // Try to connect (simple check)
      const {ipcClient} = await import('../lib/ipc-client.js');

      if (!ipcClient.isConnected()) {
        logger.debug('health_check_reconnecting', {});
        await ipcClient.connect();
      }

      const response = await ipcClient.send('ping', {});
      const isHealthy = response.success === true;

      if (!isHealthy) {
        logger.warning('health_check_unhealthy', {
          response_success: response.success,
          response_error: response.error,
        });
      }

      return isHealthy;
    } catch (error) {
      logger.debug('health_check_failed', {
        error: error instanceof Error ? error.message : 'Unknown',
      });
      return false;
    }
  }

  /**
   * Restart backend
   */
  async restart(): Promise<void> {
    await this.stop();
    await new Promise(resolve => setTimeout(resolve, 1000)); // Wait 1s
    await this.start();
  }

  /**
   * Get backend PID
   */
  getPID(): number | null {
    if (!existsSync(PID_FILE)) {
      return null;
    }

    try {
      return parseInt(readFileSync(PID_FILE, 'utf-8'));
    } catch {
      return null;
    }
  }

  /**
   * Wait for backend to be ready
   */
  private async waitForReady(): Promise<boolean> {
    const startTime = Date.now();

    while (Date.now() - startTime < STARTUP_TIMEOUT) {
      if (existsSync(SOCKET_PATH)) {
        // Socket exists, try to ping
        const healthy = await this.healthCheck();
        if (healthy) {
          return true;
        }
      }

      // Wait 500ms before retry
      await new Promise(resolve => setTimeout(resolve, 500));
    }

    return false;
  }

  /**
   * Start periodic health check
   */
  private startHealthCheck(): void {
    this.healthCheckTimer = setInterval(async () => {
      if (this.isShuttingDown) {
        return;
      }

      const healthy = await this.healthCheck();

      if (!healthy && !this.isShuttingDown) {
        console.error('Backend health check failed, restarting...');
        await this.restart();
      }
    }, HEALTH_CHECK_INTERVAL);
  }

  /**
   * Cleanup PID file and socket
   */
  private cleanup(): void {
    try {
      if (existsSync(PID_FILE)) {
        unlinkSync(PID_FILE);
      }
    } catch {
      // Ignore errors
    }

    try {
      if (existsSync(SOCKET_PATH)) {
        unlinkSync(SOCKET_PATH);
      }
    } catch {
      // Ignore errors
    }
  }
}

// Singleton instance
export const backendManager = new BackendManager();
