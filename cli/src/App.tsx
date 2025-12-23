/**
 * Main Warden CLI Application Component
 *
 * Integrates all UI components into a cohesive chat interface.
 * Features:
 * - React hooks for state management (useState, useEffect, useContext)
 * - Layout with Header, ChatArea, InputBox
 * - Theme provider with Warden colors
 * - Command detection and handling
 * - Streaming message support
 *
 * Inspired by Qwen Code's architecture but adapted for Warden's needs.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Box, useApp, useInput } from 'ink';
import { resolve as resolvePath } from 'path';
import { Header } from './components/Header.js';
import { ChatArea } from './components/ChatArea.js';
import { InputBox } from './components/InputBox.js';
import { ScanProgress } from './components/ScanProgress.js';
import { useMessages } from './hooks/useMessages.js';
import { MessageType, SessionInfo, CommandType } from './types/index.js';
import { detectCommand } from './utils/commandDetector.js';
import { WardenClient } from './bridge/wardenClient.js';
import { routeCommand } from './handlers/index.js';
import type { CommandHandlerContext } from './handlers/types.js';
import { ProgressProvider, useProgress } from './contexts/ProgressContext.js';
import { keyMatchers, Command } from './config/keyBindings.js';
import { setupCleanupHandlers, registerCleanup } from './utils/cleanup.js';
import { appEvents, AppEvent, createScopedListener } from './utils/events.js';
import { ConsolePatcher } from './utils/ConsolePatcher.js';

/**
 * App props interface
 */
export interface AppProps {
  initialSessionInfo?: Partial<SessionInfo>;
  onCommand?: (command: string, args?: string) => void;
  onSubmit?: (message: string) => void;
  onExit?: () => void;
}

/**
 * Default session info
 */
const DEFAULT_SESSION_INFO: SessionInfo = {
  llmStatus: 'disconnected',
};

/**
 * App Content Component (with access to Progress context)
 */
const AppContent: React.FC<AppProps> = ({
  initialSessionInfo = {},
  onCommand,
  onSubmit,
  onExit,
}) => {
  const { exit } = useApp();
  const progressContext = useProgress();

  // State management
  const [inputValue, setInputValue] = useState('');
  const [sessionInfo, setSessionInfo] = useState<SessionInfo>({
    ...DEFAULT_SESSION_INFO,
    ...initialSessionInfo,
  });
  const [isProcessing, setIsProcessing] = useState(false);
  const [client, setClient] = useState<WardenClient | null>(null);
  const [sessionId] = useState<string>(() => `session-${Date.now()}`);
  const [lastScanPath, setLastScanPath] = useState<string | undefined>(undefined);

  // Configuration available via environment variables
  // Currently unused but kept for future features
  //const config: WardenConfig = {
  //  apiUrl: process.env.WARDEN_API_URL ?? 'http://localhost:8000',
  //  ...(process.env.WARDEN_API_KEY !== undefined && { apiKey: process.env.WARDEN_API_KEY }),
  //  timeout: parseInt(process.env.WARDEN_TIMEOUT ?? '30000', 10),
  //  maxRetries: parseInt(process.env.WARDEN_MAX_RETRIES ?? '3', 10),
  //};

  // Use custom messages hook
  const {
    messages,
    addMessage,
    clearMessages,
    startStreaming,
    updateStreaming,
    completeStreaming,
  } = useMessages();

  /**
   * Handle global keyboard shortcuts
   */
  useInput((_input, key) => {
    // Esc - Cancel running scan/analyze
    if (key.escape) {
      if (progressContext.progress.isActive) {
        progressContext.cancelScan();
        addMessage('⚠️  Scan cancelled by user', MessageType.SYSTEM);
      }
      return;
    }

    // Ctrl+K or Ctrl+L - Clear screen
    if (keyMatchers[Command.CLEAR_SCREEN](key)) {
      clearMessages();
      addMessage(
        '🧹 Screen cleared!\n\nType `/help` to see available commands.',
        MessageType.SYSTEM,
        { markdown: true }
      );
      return;
    }

    // Ctrl+U - Clear current input line
    if (keyMatchers[Command.CLEAR_LINE](key)) {
      setInputValue('');
      return;
    }

    // Ctrl+C - Clear input OR exit (if input is empty)
    if (keyMatchers[Command.CLEAR_INPUT](key)) {
      if (inputValue.trim().length === 0) {
        // Input is empty, exit application
        addMessage('👋 Goodbye!', MessageType.SYSTEM);
        if (onExit) {
          onExit();
        }
        setTimeout(() => exit(), 500);
      } else {
        // Input has text, clear it
        setInputValue('');
      }
      return;
    }

    // Ctrl+D - Exit application
    if (keyMatchers[Command.EXIT](key)) {
      addMessage('👋 Goodbye!', MessageType.SYSTEM);
      if (onExit) {
        onExit();
      }
      setTimeout(() => exit(), 500);
      return;
    }
  });

  /**
   * Handle slash commands using new command router
   */
  const handleSlashCommand = useCallback(
    async (command: string, args?: string) => {
      if (onCommand) {
        onCommand(command, args);
      }

      // Create handler context with progressContext
      const context: CommandHandlerContext = {
        client,
        addMessage: (msg: string, type: MessageType, markdown?: boolean) => {
          // Convert markdown flag to metadata format expected by useMessages
          const metadata = markdown ? { markdown: true } : undefined;
          addMessage(msg, type, metadata);
        },
        clearMessages,
        exit: () => {
          if (onExit) {
            onExit();
          }
          exit();
        },
        progressContext,
        projectRoot: process.cwd(),
        sessionId,
        ...(lastScanPath && { lastScanPath }),
      };

      // Update lastScanPath if this is a scan command
      if (command === 'scan' || command === 's') {
        // Extract path from args or use current directory
        const scanPath = args?.trim() || process.cwd();
        setLastScanPath(scanPath.startsWith('/') ? scanPath : resolvePath(scanPath));
      }

      // Route command to appropriate handler
      await routeCommand(command, args || '', context);
    },
    [addMessage, clearMessages, client, exit, onCommand, onExit, sessionId, progressContext, lastScanPath]
  );

  /**
   * Handle message submission with command detection
   */
  const handleMessageSubmit = useCallback(
    async (message: string) => {
      // Detect command type
      const detection = detectCommand(message);

      // Add user message
      addMessage(message, MessageType.USER);

      // Set processing state
      setIsProcessing(true);

      try {
        // Handle slash command
        if (detection.type === CommandType.SLASH && detection.command) {
          await handleSlashCommand(detection.command, detection.args);
        }
        // Handle regular message
        else {
          if (onSubmit) {
            onSubmit(message);
          }

          // Simulate AI response with streaming (for demo)
          // In production, this would be replaced with actual LLM API integration
          const responseId = startStreaming(MessageType.ASSISTANT);

          const responseText =
            'This is a simulated streaming response from Warden.\n\n' +
            'In production, this would connect to:\n' +
            '• LLM provider (OpenAI, Anthropic, etc.)\n' +
            '• Warden backend API\n' +
            '• Real-time security analysis\n\n' +
            'For now, try using commands like /help, /analyze, or /validate!';

          // Simulate streaming with gradual content updates
          for (let i = 0; i <= responseText.length; i += 10) {
            await new Promise((resolve) => setTimeout(resolve, 30));
            updateStreaming(responseId, responseText.slice(0, i));
          }
          completeStreaming(responseId);

          // Update session info to show connected status
          setSessionInfo((prev) => ({
            ...prev,
            llmStatus: 'connected',
          }));
        }
      } catch (error) {
        // Error handling (Kural 4.4) - Specific exception handling
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        addMessage(`Error: ${errorMessage}`, MessageType.ERROR);
        setSessionInfo((prev) => ({
          ...prev,
          llmStatus: 'error',
        }));
      } finally {
        setIsProcessing(false);
      }
    },
    [
      addMessage,
      handleSlashCommand,
      startStreaming,
      updateStreaming,
      completeStreaming,
      onSubmit,
    ]
  );

  /**
   * Handle input value change
   */
  const handleInputChange = useCallback((value: string) => {
    setInputValue(value);
  }, []);

  /**
   * Handle input submission
   */
  const handleInputSubmit = useCallback(
    async (value: string) => {
      // Clear input IMMEDIATELY (don't wait for async operations)
      // This ensures file picker/command list disappears right away
      setInputValue('');

      // Then submit message (async operation continues in background)
      await handleMessageSubmit(value);
    },
    [handleMessageSubmit]
  );

  /**
   * Setup cleanup handlers on mount (MUST run first)
   */
  useEffect(() => {
    // Setup automatic cleanup on process exit signals
    setupCleanupHandlers({
      handleExceptions: true,
      handleRejections: true,
      exitAfterCleanup: true,
    });
  }, []);

  /**
   * Initialize IPC client on mount
   */
  useEffect(() => {
    const initializeClient = async () => {
      const wardenClient = new WardenClient();

      try {
        // Try to connect to backend
        await wardenClient.connect();
        setClient(wardenClient);
        setSessionInfo((prev) => ({ ...prev, llmStatus: 'connected' }));

        // Emit IPC status event
        appEvents.emit(AppEvent.IPC_STATUS_CHANGED, { connected: true });

        addMessage(
          '✅ Connected to Warden backend\n\n' +
            'Type `/help` to see available commands or `/status` to check configuration.',
          MessageType.SYSTEM,
          { markdown: true }
        );
      } catch (error) {
        // Connection failed - continue without IPC
        setClient(null);
        setSessionInfo((prev) => ({ ...prev, llmStatus: 'disconnected' }));

        // Emit IPC status event
        appEvents.emit(AppEvent.IPC_STATUS_CHANGED, { connected: false });

        const errorMsg = error instanceof Error ? error.message : 'Unknown error';

        addMessage(
          '⚠️  **Backend connection failed**\n\n' +
            `Error: \`${errorMsg}\`\n\n` +
            'Some commands require the Python backend. To enable them:\n' +
            '1. Open a separate terminal\n' +
            '2. Navigate to project root\n' +
            '3. Run: `source .venv/bin/activate`\n' +
            '4. Run: `python3 start_ipc_server.py`\n\n' +
            '**You can still use:**\n' +
            '- `/help` - Show available commands\n' +
            '- `/clear` - Clear chat\n' +
            '- `/quit` - Exit CLI',
          MessageType.SYSTEM,
          { markdown: true }
        );
      }
    };

    // Initialize client
    initializeClient();

    // Cleanup on unmount (fallback - cleanup handlers will also handle this)
    return () => {
      if (client) {
        client.disconnect().catch(() => {
          // Ignore disconnect errors
        });
      }
    };
  }, [addMessage]);

  /**
   * Register IPC cleanup when client changes
   */
  useEffect(() => {
    if (client) {
      // Register cleanup for IPC client
      registerCleanup(async () => {
        console.log('[Cleanup] Disconnecting IPC client...');
        await client.disconnect();
      });
    }
  }, [client]);

  /**
   * Setup console patcher for capturing console output
   */
  useEffect(() => {
    const patcher = new ConsolePatcher({
      onNewMessage: (msg) => {
        // Format console message for UI
        const prefix = msg.count > 1 ? `[${msg.count}x] ` : '';
        const typePrefix = `[${msg.type.toUpperCase()}]`;
        const content = `${prefix}${typePrefix} ${msg.content}`;

        // Add to chat with appropriate type
        const messageType =
          msg.type === 'error' ? MessageType.ERROR :
          msg.type === 'warn' ? MessageType.SYSTEM :
          MessageType.SYSTEM;

        addMessage(content, messageType);
      },
      debugMode: false, // Set to true to see debug console messages
      aggregateDuplicates: true,
      aggregationWindow: 1000, // 1 second
    });

    // Patch console
    patcher.patch();

    // Register cleanup
    registerCleanup(() => {
      patcher.cleanup();
    });

    // Return cleanup for React unmount
    return () => {
      patcher.cleanup();
    };
  }, [addMessage]);

  /**
   * Setup global event listeners
   */
  useEffect(() => {
    // Listen for error events
    const errorCleanup = createScopedListener(AppEvent.LOG_ERROR, ({ message, stack }) => {
      console.error(`[ERROR] ${message}`);
      if (stack) {
        console.error(`Stack: ${stack}`);
      }
    });

    // Listen for clear screen events
    const clearCleanup = createScopedListener(AppEvent.CLEAR_SCREEN, () => {
      clearMessages();
      addMessage(
        '🧹 Screen cleared!\n\nType `/help` to see available commands.',
        MessageType.SYSTEM,
        { markdown: true }
      );
    });

    // Return cleanup function
    return () => {
      errorCleanup();
      clearCleanup();
    };
  }, [addMessage, clearMessages]);

  /**
   * Sync isProcessing with progress context
   * When scan/analyze is cancelled or completes, clear processing state
   */
  useEffect(() => {
    if (!progressContext.progress.isActive && isProcessing) {
      setIsProcessing(false);
    }
  }, [progressContext.progress.isActive, isProcessing]);

  /**
   * Show welcome message after client initialization
   */
  useEffect(() => {
    addMessage(
      '# Welcome to Warden CLI - AI Code Guardian! 🛡️\n\n' +
        'Type `/help` to see available commands.',
      MessageType.SYSTEM,
      { markdown: true }
    );
  }, []);

  return (
    <Box flexDirection="column" padding={1} height="100%">
      {/* Header with session info */}
      <Header sessionInfo={sessionInfo} version="0.1.0" />

      {/* Chat area with messages (scrollable, takes remaining space) */}
      <Box flexGrow={1} flexDirection="column" minHeight={0}>
        <ChatArea messages={messages} autoScroll />
      </Box>

      {/* Scan progress overlay (shows when scanning) - ABOVE input */}
      {progressContext.progress.isActive && (
        <Box marginBottom={1}>
          <ScanProgress />
        </Box>
      )}

      {/* Input box with command detection - ALWAYS at bottom */}
      <InputBox
        value={inputValue}
        onChange={handleInputChange}
        onSubmit={handleInputSubmit}
        isProcessing={isProcessing}
      />
    </Box>
  );
};

/**
 * Main App Component (wrapped with ProgressProvider)
 *
 * Provides progress context to all child components
 */
export const App: React.FC<AppProps> = (props) => {
  return (
    <ProgressProvider>
      <AppContent {...props} />
    </ProgressProvider>
  );
};

export default App;
