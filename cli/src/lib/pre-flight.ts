/**
 * Pre-flight checks for CLI startup
 * Ensures all required services are running before commands execute
 */

import {backendManager} from './backend-manager.js';
import {logger} from '../utils/logger.js';
import type {PreFlightCheckResult} from './types.js';

export interface PreFlightCheck {
  name: string;
  description: string;
  required: boolean;
  check: () => Promise<boolean>;
  fix?: () => Promise<void>;
}

/**
 * HTTP Backend health check
 */
async function checkHTTPBackend(): Promise<boolean> {
  try {
    const response = await fetch('http://localhost:6173/health', {
      method: 'GET',
      signal: AbortSignal.timeout(2000),
    });

    if (response.ok) {
      const data = await response.json();
      return data.status === 'healthy';
    }
    return false;
  } catch {
    return false;
  }
}

/**
 * Start HTTP Backend
 */
async function startHTTPBackend(): Promise<void> {
  const {spawn} = await import('child_process');
  const path = await import('path');
  const {fileURLToPath} = await import('url');

  const __filename = fileURLToPath(import.meta.url);
  const __dirname = path.dirname(__filename);
  const projectRoot = path.resolve(__dirname, '..', '..', '..');

  logger.info('starting_http_backend');

  // Kill any existing HTTP server process
  try {
    const {execSync} = await import('child_process');
    execSync('pkill -f "http_server.py"', {stdio: 'ignore'});
    await new Promise(resolve => setTimeout(resolve, 1000));
  } catch {
    // Ignore errors
  }

  // Start new HTTP server
  const httpProcess = spawn('python3', [
    '-m',
    'warden.cli_bridge.http_server'
  ], {
    cwd: projectRoot,
    detached: false,
    stdio: 'inherit', // Changed from 'ignore' to 'inherit' for debugging
    env: {
      ...process.env,
      PYTHONPATH: projectRoot,
      PYTHONUNBUFFERED: '1',
    },
  });

  // Store PID for cleanup
  if (httpProcess.pid) {
    process.env.WARDEN_HTTP_PID = String(httpProcess.pid);
  }

  // Wait for server to be ready
  const maxRetries = 20;
  for (let i = 0; i < maxRetries; i++) {
    await new Promise(resolve => setTimeout(resolve, 500));
    if (await checkHTTPBackend()) {
      logger.info('http_backend_started');
      return;
    }
  }

  throw new Error('Failed to start HTTP backend');
}

/**
 * Define all pre-flight checks
 */
export const preFlightChecks: PreFlightCheck[] = [
  {
    name: 'Socket Backend',
    description: 'IPC socket backend for interactive mode',
    required: false, // Only required for interactive mode
    check: async () => {
      return backendManager['isBackendRunning']
        ? await backendManager['isBackendRunning']()
        : false;
    },
    fix: async () => {
      await backendManager.ensureRunning();
    },
  },
  {
    name: 'HTTP Backend',
    description: 'HTTP backend for scan operations',
    required: true, // Always required for scan
    check: checkHTTPBackend,
    fix: startHTTPBackend,
  },
];

/**
 * Run pre-flight checks
 */
export async function runPreFlightChecks(
  command?: string
): Promise<PreFlightCheckResult> {
  const results: PreFlightCheckResult = {
    passed: true,
    checks: [],
  };

  // Determine which checks to run based on command
  const checksToRun = command === 'scan'
    ? preFlightChecks.filter(c => c.name === 'HTTP Backend')
    : preFlightChecks.filter(c => c.name === 'Socket Backend');

  for (const check of checksToRun) {
    const checkResult = {
      name: check.name,
      description: check.description,
      passed: false,
      error: null as string | null,
    };

    try {
      // Run check
      checkResult.passed = await check.check();

      // If check failed and has a fix, try to fix it
      if (!checkResult.passed && check.fix) {
        logger.info('pre_flight_fixing', {check: check.name});
        await check.fix();

        // Re-check after fix
        checkResult.passed = await check.check();
      }

      // If still failed and required, mark overall as failed
      if (!checkResult.passed && check.required) {
        results.passed = false;
        checkResult.error = `${check.name} check failed`;
      }
    } catch (error) {
      checkResult.passed = false;
      checkResult.error = error instanceof Error ? error.message : String(error);

      if (check.required) {
        results.passed = false;
      }
    }

    results.checks.push(checkResult);
  }

  return results;
}

/**
 * Cleanup function for process exit
 */
export function cleanupServices(): void {
  // Kill HTTP backend if we started it
  if (process.env.WARDEN_HTTP_PID) {
    try {
      process.kill(parseInt(process.env.WARDEN_HTTP_PID), 'SIGTERM');
    } catch {
      // Ignore errors
    }
  }
}

// Register cleanup handlers
process.on('exit', cleanupServices);
process.on('SIGINT', cleanupServices);
process.on('SIGTERM', cleanupServices);