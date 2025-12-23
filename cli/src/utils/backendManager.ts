/**
 * Backend Manager
 *
 * Automatically manages Warden backend IPC server lifecycle.
 * Detects if backend is running, starts if needed, and ensures socket availability.
 */

import { spawn, ChildProcess } from 'child_process';
import { existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const SOCKET_PATH = '/tmp/warden-ipc.sock';
const STARTUP_TIMEOUT_MS = 5000;

let backendProcess: ChildProcess | null = null;

/**
 * Get project root directory
 */
function getProjectRoot(): string {
  // CLI is in warden-core/cli, so go up one level
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  return join(__dirname, '..', '..', '..');
}

/**
 * Check if backend socket exists and is accessible
 */
function isBackendRunning(): boolean {
  try {
    return existsSync(SOCKET_PATH);
  } catch {
    return false;
  }
}

/**
 * Find backend server script
 */
function findBackendScript(): string | null {
  const projectRoot = getProjectRoot();

  // Option 1: start_ipc_server.py in root
  const startScript = join(projectRoot, 'start_ipc_server.py');
  if (existsSync(startScript)) {
    return startScript;
  }

  // Option 2: Python module (warden.cli_bridge.server)
  return null;
}

/**
 * Start backend IPC server
 */
async function startBackend(): Promise<boolean> {
  const projectRoot = getProjectRoot();
  const backendScript = findBackendScript();

  return new Promise((resolve) => {
    let args: string[];
    let cwd: string;

    if (backendScript) {
      // Use start_ipc_server.py
      args = [backendScript];
      cwd = projectRoot;
    } else {
      // Use Python module
      args = [
        '-m',
        'warden.cli_bridge.server',
        '--transport',
        'socket',
        '--socket-path',
        SOCKET_PATH,
      ];
      cwd = projectRoot;
    }

    // Spawn backend process
    backendProcess = spawn('python3', args, {
      cwd,
      detached: true,
      stdio: 'ignore', // Run silently in background
    });

    // Unref so it doesn't block CLI exit
    backendProcess.unref();

    // Wait for socket to appear
    const startTime = Date.now();
    const checkInterval = setInterval(() => {
      if (isBackendRunning()) {
        clearInterval(checkInterval);
        resolve(true);
      } else if (Date.now() - startTime > STARTUP_TIMEOUT_MS) {
        clearInterval(checkInterval);
        resolve(false);
      }
    }, 100);
  });
}

/**
 * Ensure backend is running, start if needed
 *
 * Returns true if backend is available, false otherwise
 */
export async function ensureBackend(): Promise<boolean> {
  // Check if already running
  if (isBackendRunning()) {
    return true;
  }

  // Try to start backend
  console.log('🔄 Starting Warden backend...');
  const started = await startBackend();

  if (started) {
    console.log('✅ Backend started successfully\n');
    return true;
  } else {
    console.log('⚠️  Backend could not be started automatically');
    console.log('   You can start it manually:');
    console.log('   cd ' + getProjectRoot());
    console.log('   python3 start_ipc_server.py\n');
    return false;
  }
}

/**
 * Cleanup backend on exit (optional - backend can run independently)
 */
export function cleanupBackend(): void {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
}
