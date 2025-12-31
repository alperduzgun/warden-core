#!/usr/bin/env node

/**
 * Warden CLI Integration Tests
 *
 * These tests ensure all CLI commands work correctly before deployment.
 * Run with: node tests/integration/cli-integration.test.js
 */

import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { existsSync, mkdirSync, writeFileSync, rmSync } from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Test configuration
const CLI_PATH = join(__dirname, '..', '..', 'dist', 'cli.js');
const PROJECT_ROOT = join(__dirname, '..', '..', '..');
const TEST_DIR = join(__dirname, 'test-workspace');
const SOCKET_PATH = '/tmp/warden-ipc.sock';
const TIMEOUT = 60000; // 60 seconds for slow operations

// ANSI color codes
const colors = {
  reset: '\x1b[0m',
  bright: '\x1b[1m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m'
};

// Test results tracking
let totalTests = 0;
let passedTests = 0;
let failedTests = [];

/**
 * Print colored message
 */
function print(message, color = 'reset') {
  console.log(`${colors[color]}${message}${colors.reset}`);
}

/**
 * Print test header
 */
function testHeader(name) {
  print(`\n${'='.repeat(60)}`, 'cyan');
  print(`Testing: ${name}`, 'cyan');
  print(`${'='.repeat(60)}`, 'cyan');
}

/**
 * Run CLI command and capture output
 */
function runCommand(args, options = {}) {
  return new Promise((resolve) => {
    const startTime = Date.now();
    const timeout = options.timeout || TIMEOUT;

    const proc = spawn('node', [CLI_PATH, ...args], {
      cwd: options.cwd || PROJECT_ROOT,
      env: { ...process.env, NODE_ENV: 'test' },
      timeout: timeout
    });

    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', (data) => {
      stdout += data.toString();
      if (options.verbose) {
        process.stdout.write(data);
      }
    });

    proc.stderr.on('data', (data) => {
      stderr += data.toString();
      if (options.verbose) {
        process.stderr.write(data);
      }
    });

    proc.on('close', (code) => {
      const duration = Date.now() - startTime;
      resolve({
        code,
        stdout,
        stderr,
        duration,
        success: code === 0
      });
    });

    proc.on('error', (error) => {
      resolve({
        code: -1,
        stdout,
        stderr: error.message,
        duration: Date.now() - startTime,
        success: false
      });
    });

    // Kill process after timeout
    setTimeout(() => {
      proc.kill('SIGTERM');
    }, timeout);
  });
}

/**
 * Check if backend is running
 */
async function isBackendRunning() {
  return existsSync(SOCKET_PATH);
}

/**
 * Kill any existing backend processes
 */
async function killBackend() {
  const { exec } = await import('child_process');
  return new Promise((resolve) => {
    exec('pkill -f "python.*server.py" || true', () => {
      // Also remove socket file
      if (existsSync(SOCKET_PATH)) {
        try {
          rmSync(SOCKET_PATH);
        } catch (e) {
          // Ignore
        }
      }
      resolve();
    });
  });
}

/**
 * Create test files
 */
function createTestFiles() {
  // Create test directory
  if (!existsSync(TEST_DIR)) {
    mkdirSync(TEST_DIR, { recursive: true });
  }

  // Create a test Python file with issues
  const testFile = join(TEST_DIR, 'test_file.py');
  writeFileSync(testFile, `
# Test file with security issues
import os
import json

DATABASE_PASSWORD = "admin123"  # Security issue

def vulnerable_sql(user_id):
    query = f"SELECT * FROM users WHERE id = '{user_id}'"  # SQL injection
    return query

def unused_function():
    pass  # Orphan code

# Missing error handling
data = open('file.txt').read()
`);

  // Create a clean Python file
  const cleanFile = join(TEST_DIR, 'clean_file.py');
  writeFileSync(cleanFile, `
"""A clean Python file with no issues."""

def hello_world():
    """Print hello world."""
    print("Hello, World!")

if __name__ == "__main__":
    hello_world()
`);

  return { testFile, cleanFile };
}

/**
 * Test assertions
 */
function assert(condition, message) {
  totalTests++;
  if (condition) {
    passedTests++;
    print(`  ✓ ${message}`, 'green');
    return true;
  } else {
    failedTests.push(message);
    print(`  ✗ ${message}`, 'red');
    return false;
  }
}

/**
 * Test status command
 */
async function testStatus() {
  testHeader('STATUS COMMAND');

  const result = await runCommand(['status']);

  assert(result.success, 'Status command should exit with code 0');
  assert(result.stdout.includes('Warden Backend Connected'), 'Should show connection status');
  assert(result.stdout.includes('pong'), 'Should receive pong response');
  assert(result.duration < 45000, `Should complete within 45 seconds (took ${result.duration}ms)`);

  return result.success;
}

/**
 * Test scan command
 */
async function testScan() {
  testHeader('SCAN COMMAND');

  const { testFile } = createTestFiles();

  // Test single file scan
  print('\nScanning single file...', 'yellow');
  const fileScan = await runCommand(['scan', testFile]);

  assert(fileScan.success, 'Scan command should exit with code 0');
  assert(fileScan.stdout.includes('Scan Complete'), 'Should show scan completion');
  assert(fileScan.stdout.includes('Files scanned: 1'), 'Should scan 1 file');
  assert(fileScan.stdout.includes('Issues Found'), 'Should find issues');
  assert(fileScan.stdout.includes('DATABASE_PASSWORD'), 'Should detect hardcoded password');
  assert(fileScan.stdout.includes('SQL injection'), 'Should detect SQL injection');
  assert(fileScan.duration < 50000, `Should complete within 50 seconds (took ${fileScan.duration}ms)`);

  // Test directory scan
  print('\nScanning directory...', 'yellow');
  const dirScan = await runCommand(['scan', TEST_DIR]);

  assert(dirScan.success, 'Directory scan should exit with code 0');
  assert(dirScan.stdout.includes('Files scanned: 2'), 'Should scan 2 files');

  return fileScan.success && dirScan.success;
}

/**
 * Test analyze command
 */
async function testAnalyze() {
  testHeader('ANALYZE COMMAND');

  const { testFile } = createTestFiles();

  const result = await runCommand(['analyze', testFile], { timeout: 60000 });

  assert(result.success, 'Analyze command should exit with code 0');
  assert(result.stdout.includes('Analysis Complete'), 'Should complete analysis');
  assert(result.stdout.includes('Validation Pipeline'), 'Should show pipeline progress');
  assert(result.stdout.includes('Security Analysis'), 'Should run security frame');
  assert(result.stdout.includes('Findings Summary'), 'Should show findings summary');
  assert(result.duration < 60000, `Should complete within 60 seconds (took ${result.duration}ms)`);

  return result.success;
}

/**
 * Test relative paths
 */
async function testRelativePaths() {
  testHeader('RELATIVE PATH HANDLING');

  const { testFile } = createTestFiles();
  const relativePath = testFile.replace(PROJECT_ROOT + '/', '');

  // Test from project root
  print('\nTesting relative path from project root...', 'yellow');
  const result = await runCommand(['scan', relativePath]);

  assert(result.success, 'Should handle relative paths');
  assert(result.stdout.includes('Scan Complete'), 'Should complete scan with relative path');

  // Test with ../
  print('\nTesting parent directory path...', 'yellow');
  const parentPath = '../' + testFile.split('/').slice(-2).join('/');
  const parentResult = await runCommand(['scan', parentPath], {
    cwd: join(PROJECT_ROOT, 'cli')
  });

  assert(parentResult.success, 'Should handle parent directory paths');

  return result.success && parentResult.success;
}

/**
 * Test error handling
 */
async function testErrorHandling() {
  testHeader('ERROR HANDLING');

  // Test non-existent file
  print('\nTesting non-existent file...', 'yellow');
  const result = await runCommand(['scan', 'non-existent-file.py']);

  assert(!result.success, 'Should fail for non-existent file');
  assert(result.stdout.includes('Path does not exist') ||
         result.stderr.includes('Path does not exist'),
         'Should show clear error message');

  // Test invalid command
  print('\nTesting invalid command...', 'yellow');
  const invalid = await runCommand(['invalid-command']);

  assert(invalid.stdout.includes('chat') || invalid.stdout.includes('Chat'),
         'Should show help or default to chat');

  return true;
}

/**
 * Test backend auto-start
 */
async function testBackendAutoStart() {
  testHeader('BACKEND AUTO-START');

  // Kill backend first
  print('\nKilling any existing backend...', 'yellow');
  await killBackend();
  await new Promise(resolve => setTimeout(resolve, 1000));

  assert(!await isBackendRunning(), 'Backend should not be running initially');

  // Run status command which should auto-start backend
  print('\nRunning status command to trigger auto-start...', 'yellow');
  const result = await runCommand(['status']);

  assert(result.success, 'Status command should succeed');
  assert(result.stdout.includes('Starting Warden backend') ||
         result.stdout.includes('Warden Backend Connected'),
         'Should start backend automatically');

  // Verify backend is now running
  await new Promise(resolve => setTimeout(resolve, 2000));
  assert(await isBackendRunning(), 'Backend should be running after command');

  return result.success;
}

/**
 * Test concurrent commands
 */
async function testConcurrency() {
  testHeader('CONCURRENT COMMANDS');

  const { testFile, cleanFile } = createTestFiles();

  print('\nRunning multiple commands concurrently...', 'yellow');

  // Run multiple commands in parallel
  const [scan1, scan2, status] = await Promise.all([
    runCommand(['scan', testFile]),
    runCommand(['scan', cleanFile]),
    runCommand(['status'])
  ]);

  assert(scan1.success, 'First scan should succeed');
  assert(scan2.success, 'Second scan should succeed');
  assert(status.success, 'Status should succeed');
  assert(scan1.stdout.includes('Issues Found'), 'First scan should find issues');
  assert(scan2.stdout.includes('No issues found') ||
         scan2.stdout.includes('0 total'),
         'Second scan should find no issues');

  return scan1.success && scan2.success && status.success;
}

/**
 * Main test runner
 */
async function runTests() {
  print('\n╔════════════════════════════════════════════════════════════╗', 'bright');
  print('║           WARDEN CLI INTEGRATION TEST SUITE                ║', 'bright');
  print('╚════════════════════════════════════════════════════════════╝', 'bright');

  const startTime = Date.now();

  try {
    // Setup
    print('\n📦 Setting up test environment...', 'blue');
    await killBackend();

    // Run tests
    const tests = [
      testBackendAutoStart,
      testStatus,
      testScan,
      testAnalyze,
      testRelativePaths,
      testErrorHandling,
      testConcurrency
    ];

    for (const test of tests) {
      try {
        await test();
      } catch (error) {
        print(`\n❌ Test failed with error: ${error.message}`, 'red');
        failedTests.push(test.name);
      }
    }

  } finally {
    // Cleanup
    print('\n🧹 Cleaning up...', 'blue');

    // Remove test files
    if (existsSync(TEST_DIR)) {
      rmSync(TEST_DIR, { recursive: true, force: true });
    }

    // Kill backend
    await killBackend();

    // Summary
    const duration = ((Date.now() - startTime) / 1000).toFixed(2);

    print('\n╔════════════════════════════════════════════════════════════╗', 'bright');
    print('║                     TEST SUMMARY                           ║', 'bright');
    print('╚════════════════════════════════════════════════════════════╝', 'bright');

    print(`\n📊 Results:`, 'cyan');
    print(`   Total tests: ${totalTests}`, 'white');
    print(`   ✅ Passed: ${passedTests}`, 'green');
    print(`   ❌ Failed: ${failedTests.length}`, 'red');
    print(`   ⏱️  Duration: ${duration}s`, 'yellow');

    if (failedTests.length > 0) {
      print('\n❌ Failed tests:', 'red');
      failedTests.forEach(test => print(`   • ${test}`, 'red'));
      print('\n🚨 TESTS FAILED! CLI is not ready for deployment.', 'red');
      process.exit(1);
    } else {
      print('\n✨ ALL TESTS PASSED! CLI is ready for deployment. ✨', 'green');
      process.exit(0);
    }
  }
}

// Run tests
runTests().catch(error => {
  print(`\n💥 Fatal error: ${error.message}`, 'red');
  console.error(error.stack);
  process.exit(1);
});