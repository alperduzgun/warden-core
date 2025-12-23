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
   * Handle Ctrl+C for graceful exit
   */
  useInput((input, key) => {
    if (key.ctrl && input === 'c') {
      addMessage('Goodbye!', MessageType.SYSTEM);
      if (onExit) {
        onExit();
      }
      setTimeout(() => exit(), 500);
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
      };

      // Route command to appropriate handler
      await routeCommand(command, args || '', context);
    },
    [addMessage, clearMessages, client, exit, onCommand, onExit, sessionId, progressContext]
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
        addMessage(
          `Error: ${error instanceof Error ? error.message : 'Unknown error'}`,
          MessageType.ERROR
        );
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
    (value: string) => {
      handleMessageSubmit(value);
      setInputValue('');
    },
    [handleMessageSubmit]
  );

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

    // Cleanup on unmount
    return () => {
      if (client) {
        client.disconnect().catch(() => {
          // Ignore disconnect errors
        });
      }
    };
  }, [addMessage]);

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
