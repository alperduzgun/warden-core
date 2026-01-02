/**
 * Backend Manager
 * Automatically manages Python backend lifecycle
 */

import { spawn, ChildProcess } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';
import { logger } from '../utils/logger.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SOCKET_PATH = '/tmp/warden-ipc.sock';
const BACKEND_SCRIPT = 'src/warden/cli_bridge/server.py';
const PROJECT_ROOT = path.resolve(__dirname, '..', '..', '..'); // Go up 3 levels from dist/lib to project root
const MAX_RETRIES = 3;
const STARTUP_TIMEOUT = 20000; // 20 seconds for slower systems
const HEALTH_CHECK_INTERVAL = 500; // 500ms for faster response

export class BackendManager {
  private process: ChildProcess | null = null;
  private isStarting = false;
  private startPromise: Promise<void> | null = null;

  /**
   * Ensure backend is running
   * This is idempotent - safe to call multiple times
   */
  async ensureRunning(): Promise<void> {
    // If already starting, wait for that to complete
    if (this.startPromise) {
      return this.startPromise;
    }

    // Check if backend is already running
    if (await this.isBackendRunning()) {
      logger.debug('backend_already_running');
      return;
    }

    // Start backend
    this.startPromise = this.startBackend();
    try {
      await this.startPromise;
    } finally {
      this.startPromise = null;
    }
  }

  /**
   * Check if backend is running by testing socket
   */
  private async isBackendRunning(): Promise<boolean> {
    try {
      // Check if socket file exists
      if (!fs.existsSync(SOCKET_PATH)) {
        return false;
      }

      // Try to connect to socket
      const net = await import('net');
      return new Promise((resolve) => {
        const client = net.createConnection(SOCKET_PATH);

        client.on('connect', () => {
          client.end();
          resolve(true);
        });

        client.on('error', () => {
          resolve(false);
        });

        // Timeout after 1 second
        setTimeout(() => {
          client.destroy();
          resolve(false);
        }, 1000);
      });
    } catch (error) {
      logger.debug('backend_check_error', { error: String(error) });
      return false;
    }
  }

  /**
   * Start the Python backend process
   */
  private async startBackend(): Promise<void> {
    if (this.isStarting) {
      throw new Error('Backend is already starting');
    }

    this.isStarting = true;
    logger.info('starting_backend', { script: BACKEND_SCRIPT, cwd: PROJECT_ROOT });

    try {
      // Clean up old socket if exists
      if (fs.existsSync(SOCKET_PATH)) {
        try {
          fs.unlinkSync(SOCKET_PATH);
        } catch (e) {
          // Ignore errors
        }
      }

      // Find Python executable
      const pythonCmd = await this.findPython();

      // Spawn backend process
      this.process = spawn(pythonCmd, [BACKEND_SCRIPT, '--transport', 'socket'], {
        cwd: PROJECT_ROOT,
        detached: false,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: {
          ...process.env,
          PYTHONPATH: `${PROJECT_ROOT}:${path.join(PROJECT_ROOT, 'src')}`,
          PYTHONUNBUFFERED: '1',
        },
      });

      // Handle process output
      if (this.process.stdout) {
        this.process.stdout.on('data', (data) => {
          const output = data.toString();
          // Only log important messages
          if (output.includes('error') || output.includes('warning')) {
            logger.debug('backend_output', { message: output.trim() });
          }
        });
      }

      if (this.process.stderr) {
        this.process.stderr.on('data', (data) => {
          logger.error('backend_error', { message: data.toString().trim() });
        });
      }

      // Handle process exit
      this.process.on('exit', (code) => {
        logger.info('backend_exited', { code });
        this.process = null;
      });

      this.process.on('error', (error) => {
        logger.error('backend_process_error', { error: String(error) });
        this.process = null;
      });

      // Wait for backend to be ready
      await this.waitForBackend();

      logger.info('backend_started_successfully');
    } finally {
      this.isStarting = false;
    }
  }

  /**
   * Wait for backend to be ready
   */
  private async waitForBackend(): Promise<void> {
    const startTime = Date.now();

    while (Date.now() - startTime < STARTUP_TIMEOUT) {
      if (await this.isBackendRunning()) {
        // Give it a bit more time to fully initialize
        await new Promise(resolve => setTimeout(resolve, 500));
        return;
      }

      // Check if process died
      if (this.process && this.process.exitCode !== null) {
        const exitCode = this.process.exitCode;
        let errorMsg = `Backend process exited with code ${exitCode}`;

        // Provide more specific error messages based on exit code
        if (exitCode === 1) {
          errorMsg = 'Backend failed to start - likely due to missing Python dependencies';
        } else if (exitCode === 127) {
          errorMsg = 'Python command not found in PATH';
        }

        throw new Error(errorMsg);
      }

      await new Promise(resolve => setTimeout(resolve, HEALTH_CHECK_INTERVAL));
    }

    throw new Error('Backend startup timeout - the service is taking too long to respond');
  }

  /**
   * Find Python executable
   */
  private async findPython(): Promise<string> {
    const candidates = ['python3', 'python', 'python3.11', 'python3.10', 'python3.9'];

    for (const cmd of candidates) {
      try {
        const { execSync } = await import('child_process');
        execSync(`${cmd} --version`, { stdio: 'ignore' });
        return cmd;
      } catch {
        // Try next
      }
    }

    throw new Error('Python not found. Please install Python 3.9 or later.');
  }

  /**
   * Stop the backend process
   */
  async stop(): Promise<void> {
    if (!this.process) {
      return;
    }

    logger.info('stopping_backend');

    return new Promise((resolve) => {
      if (!this.process) {
        resolve();
        return;
      }

      // Set a timeout for graceful shutdown
      const killTimeout = setTimeout(() => {
        if (this.process) {
          this.process.kill('SIGKILL');
        }
      }, 5000);

      this.process.on('exit', () => {
        clearTimeout(killTimeout);
        this.process = null;
        resolve();
      });

      // Try graceful shutdown first
      this.process.kill('SIGTERM');
    });
  }

  /**
   * Restart the backend
   */
  async restart(): Promise<void> {
    await this.stop();
    await this.ensureRunning();
  }
}

// Singleton instance
export const backendManager = new BackendManager();

// Cleanup on exit
process.on('exit', () => {
  if (backendManager['process']) {
    backendManager['process'].kill('SIGTERM');
  }
});

process.on('SIGINT', async () => {
  await backendManager.stop();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  await backendManager.stop();
  process.exit(0);
});