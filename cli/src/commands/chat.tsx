/**
 * Interactive Chat Mode
 * Qwen Code / Claude Code style terminal interface
 */

import React, { useState, useEffect } from 'react';
import { Box, Text } from 'ink';
import Gradient from 'ink-gradient';
import path from 'path';
import { ChatInterfaceEnhanced } from '../components/ChatInterfaceEnhanced.js';
import { FileBrowser } from '../components/FileBrowser.js';
import { Frames } from './frames.js';
import { Rules } from './rules.js';
import { Scan } from './scan.js';
import { ipcClient } from '../lib/ipc-client.js';
import { backendManager } from '../utils/backendManager.js';
import { sessionManager, type Session } from '../utils/sessionManager.js';
import { llmClient } from '../lib/llm-client.js';
import { configLoader, type WardenConfig } from '../utils/configLoader.js';
import { runPreFlightChecks } from '../lib/pre-flight.js';
import type { CommandResult } from '../lib/types.js';
import { logger } from '../utils/logger.js';

export function Chat() {
  const [backendConnected, setBackendConnected] = useState(false);
  const [showFileBrowser, setShowFileBrowser] = useState(false);
  const [showFrames, setShowFrames] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [showScan, setShowScan] = useState(false);
  const [scanPath, setScanPath] = useState<string>('');
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [isStarting, setIsStarting] = useState(true);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [config, setConfig] = useState<WardenConfig | null>(null);

  // Auto-start backend and initialize session on mount
  useEffect(() => {
    initializeApp();

    // Cleanup on unmount
    return () => {
      // Don't stop backend on unmount - let it run in background
    };
  }, []);

  const initializeApp = async () => {
    try {
      setIsStarting(true);
      setStartupError(null);

      // 1. Load config from .warden/config.yaml
      const wardenConfig = configLoader.load();
      setConfig(wardenConfig);

      // 2. Run pre-flight checks to ensure all backends are ready
      const preFlightResult = await runPreFlightChecks();
      if (!preFlightResult.passed) {
        const failedChecks = preFlightResult.checks
          .filter(c => !c.passed)
          .map(c => `${c.name}: ${c.error || 'Failed'}`)
          .join(', ');
        throw new Error(`Pre-flight checks failed: ${failedChecks}`);
      }

      // 3. Connect to backend (Socket for interactive mode)
      await checkConnection();

      // 4. Initialize or resume session
      const lastSession = sessionManager.getLastSession();
      if (lastSession && lastSession.projectPath === process.cwd()) {
        // Resume last session
        setSession(lastSession);
      } else {
        // Create new session
        const newSession = sessionManager.create(process.cwd());
        setSession(newSession);
      }

      setIsStarting(false);
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Unknown error';
      logger.error('app_startup_failed', {
        error: errorMsg,
        stack: error instanceof Error ? error.stack : undefined,
      });
      setStartupError(`Startup failed: ${errorMsg}. Check backend logs.`);
      setIsStarting(false);
    }
  };

  const checkConnection = async () => {
    try {
      await ipcClient.connect();
      setBackendConnected(true);
    } catch (error) {
      setBackendConnected(false);
      throw error;
    }
  };

  /**
   * Validate file path to prevent path traversal attacks
   * @param inputPath User-provided path
   * @returns Validated absolute path
   * @throws Error if path is invalid or outside project
   */
  const validatePath = (inputPath: string): string => {
    // Prevent path traversal attempts
    if (inputPath.includes('..')) {
      throw new Error('Path traversal (..) not allowed');
    }

    // Resolve to absolute path
    const absolutePath = path.resolve(inputPath);
    const projectRoot = process.cwd();

    // Ensure path is within project boundaries
    if (!absolutePath.startsWith(projectRoot)) {
      throw new Error('Path must be within project directory');
    }

    return absolutePath;
  };

  const handleCommand = async (command: string): Promise<CommandResult> => {
    const parts = command.split(' ');
    const cmd = parts[0];
    const args = parts.slice(1);

    switch (cmd) {
      case 'status':
        if (!ipcClient.isConnected()) {
          await ipcClient.connect();
        }
        // Get detailed backend config instead of just ping
        const statusResult = await ipcClient.send('get_config', {});
        return statusResult as CommandResult;

      case 'scan':
        if (args.length === 0) {
          throw new Error('Usage: /scan <path>');
        }
        // Validate path to prevent path traversal
        const validatedScanPath = validatePath(args[0] || '.');
        setScanPath(validatedScanPath);
        setShowScan(true);
        return { success: true } as CommandResult;

      case 'start':
      case 'analyze':
        if (args.length === 0) {
          throw new Error(`Usage: /${cmd} <file>`);
        }
        if (!ipcClient.isConnected()) {
          await ipcClient.connect();
        }
        // Validate path to prevent path traversal
        const validatedAnalyzePath = validatePath(args[0] || '');
        const analyzeResult = await ipcClient.send('analyze', { filePath: validatedAnalyzePath });
        return analyzeResult as CommandResult;

      case 'frames':
        setShowFrames(!showFrames);
        return { success: true };

      case 'rules':
        setShowRules(!showRules);
        return { success: true };

      case 'browse':
        setShowFileBrowser(!showFileBrowser);
        return { success: true };

      default:
        throw new Error(`Unknown command: ${cmd}`);
    }
  };

  const handleFileSelect = (filePath: string) => {
    setSelectedFile(filePath);
    setShowFileBrowser(false);
  };

  // Show startup screen
  if (isStarting) {
    return (
      <Box flexDirection="column" padding={1}>
        <Box marginBottom={1}>
          <Gradient name="rainbow">
            <Text bold>🛡️  WARDEN CODE ANALYSIS</Text>
          </Gradient>
        </Box>
        <Box flexDirection="column" paddingX={2}>
          <Text>🚀 Starting Warden...</Text>
          <Text dimColor>  • Running pre-flight checks</Text>
          <Text dimColor>  • Ensuring backend services are ready</Text>
          <Text dimColor>  • Connecting to IPC socket</Text>
          <Text dimColor>  • Initializing session</Text>
        </Box>
      </Box>
    );
  }

  // Show error screen
  if (startupError) {
    return (
      <Box flexDirection="column" padding={1}>
        <Box marginBottom={1}>
          <Gradient name="rainbow">
            <Text bold>🛡️  WARDEN CODE ANALYSIS</Text>
          </Gradient>
        </Box>
        <Box flexDirection="column" paddingX={2} borderStyle="single" borderColor="red">
          <Text color="red">❌ Startup Failed</Text>
          <Text>{startupError}</Text>
          <Text dimColor>
            Make sure Python backend is installed and warden.services.ipc_entry is running.
          </Text>
        </Box>
      </Box >
    );
  }

  if (showFileBrowser) {
    return (
      <Box flexDirection="column" padding={1}>
        <Box marginBottom={1}>
          <Gradient name="rainbow">
            <Text bold>🛡️  Warden File Browser</Text>
          </Gradient>
        </Box>
        <FileBrowser onSelect={handleFileSelect} />
      </Box>
    );
  }

  if (showFrames) {
    return <Frames onExit={() => setShowFrames(false)} />;
  }

  if (showRules) {
    return <Rules onExit={() => setShowRules(false)} />;
  }

  if (showScan) {
    return (
      <Box flexDirection="column">
        <Scan path={scanPath} />
        <Box marginTop={1}>
          <Text dimColor>Press Ctrl+C to return to chat</Text>
        </Box>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" padding={1} height="100%">
      {/* Header */}
      <Box marginBottom={1} flexDirection="column">
        <Gradient name="rainbow">
          <Text bold>🛡️  WARDEN CODE ANALYSIS</Text>
        </Gradient>
        {config && (
          <Text dimColor>
            {config.project.name} | {config.frames.length} frames | Session: {session?.id.slice(0, 8)}
          </Text>
        )}
        {!config && (
          <Text dimColor>Interactive Terminal Mode | Session: {session?.id.slice(0, 8)}</Text>
        )}
        {llmClient.isAvailable() && (
          <Text dimColor>LLM: {llmClient.getProvider()} ({llmClient.getModel()})</Text>
        )}
      </Box>

      {/* Main Chat Interface */}
      <ChatInterfaceEnhanced
        onCommand={handleCommand}
        backendConnected={backendConnected}
        session={session}
        config={config}
      />

      {/* Footer */}
      {selectedFile && (
        <Box borderStyle="single" borderColor="cyan" paddingX={1} marginTop={1}>
          <Text>Selected: <Text bold>{selectedFile}</Text></Text>
        </Box>
      )}
    </Box>
  );
}
