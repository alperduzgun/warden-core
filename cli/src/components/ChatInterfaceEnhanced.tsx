/**
 * Enhanced Chat Interface
 * With slash command autocomplete and @ file picker
 */

import React, {useState, useEffect} from 'react';
import {Box, Text, useInput, useApp} from 'ink';
import SelectInput from 'ink-select-input';
import TextInput from 'ink-text-input';
import {nanoid} from 'nanoid';
import type {Issue, ScanResult, ValidationResult, CommandData, ConfigResult} from '../lib/types.js';
import {IssueList} from './IssueList.js';
import {scanDirectory, filterFiles, type FileItem} from '../utils/fileScanner.js';
import {sessionManager, type Session, type SessionMessage} from '../utils/sessionManager.js';
import {llmClient} from '../lib/llm-client.js';
import type {WardenConfig} from '../utils/configLoader.js';
import {AdvancedInput} from './AdvancedInput.js';
import {StreamingMessage} from './StreamingMessage.js';
import {StatusLine, type StatusInfo} from './StatusLine.js';

interface Message {
  id: string;
  type: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  issues?: Issue[];
}

interface ChatInterfaceEnhancedProps {
  onCommand: (command: string) => Promise<any>;
  backendConnected: boolean;
  session: Session | null;
  config: WardenConfig | null;
}

const AVAILABLE_COMMANDS = [
  {label: '/help - Show help', value: '/help'},
  {label: '/scan <path> - Scan directory', value: '/scan '},
  {label: '/analyze <file> - Analyze file', value: '/analyze '},
  {label: '/frames - Show validation frames', value: '/frames'},
  {label: '/status - Backend status', value: '/status'},
  {label: '/browse - File browser', value: '/browse'},
  {label: '/clear - Clear history', value: '/clear'},
  {label: '/exit - Exit', value: '/exit'},
];

/**
 * Format command response for display
 */
function formatCommandResponse(cmdName: string, data: CommandData): string {
  switch (cmdName) {
    case 'scan': {
      const scanData = data as any; // Backend returns {total_files, files, message, path}
      const totalFiles = scanData.total_files || scanData.filesScanned || 0;
      const files = scanData.files || [];
      const summary = scanData.summary || {critical: 0, high: 0, medium: 0, low: 0};

      return `Scan Complete!
Path: ${scanData.path || 'unknown'}
Files found: ${totalFiles}
${files.length > 0 ? `\nSample files:\n${files.slice(0, 5).map((f: string) => `  • ${f}`).join('\n')}` : ''}

Issues found: ${scanData.issues?.length || 0}
  🔴 Critical: ${summary.critical}
  🟠 High: ${summary.high}
  🟡 Medium: ${summary.medium}
  ⚪ Low: ${summary.low}`;
    }

    case 'analyze': {
      const analyzeData = data as ValidationResult;
      return `Analysis Complete!
Frame: ${analyzeData.frame || 'unknown'}
Issues found: ${analyzeData.issues?.length || 0}`;
    }

    case 'status': {
      const config = data as ConfigResult;
      return `✓ Backend Status
Version: ${config.version || 'unknown'}
Project: ${config.project_path || 'not set'}
Session: ${config.session_id || 'n/a'}

Available Frames: ${config.frames_available?.length || 0}
${config.frames_available?.map((f) => `  • ${f}`).join('\n') || '  (none)'}`;
    }

    default:
      return `✓ Command executed
Result: ${JSON.stringify(data, null, 2)}`;
  }
}

export function ChatInterfaceEnhanced({onCommand, backendConnected, session, config}: ChatInterfaceEnhancedProps) {
  const {exit} = useApp();

  // Initialize messages from session or defaults
  const [messages, setMessages] = useState<Message[]>(() => {
    if (session && session.messages.length > 0) {
      // Resume from session
      return session.messages.map(msg => ({
        ...msg,
        timestamp: new Date(msg.timestamp),
      }));
    }

    // Default welcome messages
    return [
      {
        id: nanoid(),
        type: 'system',
        content: '🛡️  Warden - Type / for commands or @ to browse files',
        timestamp: new Date(),
      },
      {
        id: nanoid(),
        type: 'system',
        content: backendConnected
          ? '✓ Backend connected. Ready!'
          : '⚠ Backend disconnected.',
        timestamp: new Date(),
      },
      ...(llmClient.isAvailable()
        ? [{
            id: nanoid(),
            type: 'system' as const,
            content: `✓ LLM available (${llmClient.getProvider()}) - Natural language supported!`,
            timestamp: new Date(),
          }]
        : []),
    ];
  });

  const [input, setInput] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [showCommandPalette, setShowCommandPalette] = useState(false);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [allFiles, setAllFiles] = useState<FileItem[]>([]);
  const [filteredFiles, setFilteredFiles] = useState<Array<{label: string; value: string}>>([]);
  const [fileSearchQuery, setFileSearchQuery] = useState('');
  const [commandHistory, setCommandHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);

  // Load all files once on mount
  useEffect(() => {
    const files = scanDirectory(process.cwd(), {
      maxDepth: 5,
      ignorePatterns: ['.git', 'node_modules', '__pycache__', '.venv', 'dist', 'build'],
    });
    setAllFiles(files);
  }, []);

  // Detect slash command trigger and @ file picker
  useEffect(() => {
    if (input === '/') {
      setShowCommandPalette(true);
    } else if (input.length > 1 && !input.includes(' ')) {
      setShowCommandPalette(false);
    }

    // Detect @ file picker
    if (input.endsWith('@')) {
      setShowFilePicker(true);
      setFileSearchQuery('');
      setFilteredFiles(allFiles.slice(0, 50).map(f => ({label: f.label, value: f.value})));
    } else if (input.match(/@(.+)$/)) {
      // User is typing after @
      const match = input.match(/@(.+)$/);
      const query = match?.[1] || '';
      setFileSearchQuery(query);
      const filtered = filterFiles(allFiles, query);
      setFilteredFiles(filtered.slice(0, 50).map(f => ({label: f.label, value: f.value})));
      setShowFilePicker(true);
    } else if (!input.includes('@')) {
      setShowFilePicker(false);
    }
  }, [input, allFiles]);

  const handleCommandSelect = (item: {label: string; value: string}) => {
    setInput(item.value);
    setShowCommandPalette(false);
  };

  const handleFileSelect = (item: {label: string; value: string}) => {
    // Replace @query with @filepath
    const newInput = input.replace(/@[^\s]*$/, `@${item.value} `);
    setInput(newInput);
    setShowFilePicker(false);
  };

  const handleSubmit = async (value: string) => {
    if (!value.trim() || isProcessing) return;

    // Strip @ prefix from file paths (file picker adds @filepath, we only want filepath)
    const cleanedValue = value.replace(/@(\/[^\s]+)/g, '$1');

    // Add to history (avoid duplicates)
    if (cleanedValue.trim() && !commandHistory.includes(cleanedValue)) {
      setCommandHistory(prev => [...prev, cleanedValue]);
    }
    setHistoryIndex(-1);

    const userMessage: Message = {
      id: nanoid(),
      type: 'user',
      content: cleanedValue,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setShowCommandPalette(false);
    setShowFilePicker(false);

    // Save user message to session
    if (session) {
      sessionManager.addMessage(session, {
        ...userMessage,
        timestamp: userMessage.timestamp.getTime(),
      });
    }

    // Handle commands (use cleanedValue, not original value!)
    if (cleanedValue.startsWith('/')) {
      const command = cleanedValue.slice(1).trim();

      if (command === 'exit' || command === 'quit') {
        exit();
        return;
      }

      if (command === 'clear') {
        setMessages([]);
        return;
      }

      if (command === 'help') {
        const helpMsg: Message = {
          id: nanoid(),
          type: 'system',
          content: `Commands:
  /help       - This help
  /scan <path> - Scan directory
  /analyze <file> - Analyze file
  /frames     - Show validation frames
  /status     - Backend status
  /browse     - File browser
  /clear      - Clear chat
  /exit       - Exit

  Features:
  • Type / to see commands
  • Type @ to browse files
  • Ctrl+P - Command palette
  • Ctrl+L - Clear
  • Ctrl+C - Exit`,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, helpMsg]);
        return;
      }

      // Execute via IPC
      setIsProcessing(true);
      try {
        const result = await onCommand(command);

        // Handle different command results
        const cmdName = command.split(' ')[0] || 'unknown';
        let responseMsg: Message;

        if (result && result.data) {
          responseMsg = {
            id: nanoid(),
            type: 'assistant',
            content: formatCommandResponse(cmdName, result.data),
            timestamp: new Date(),
            issues: result.data.issues || [],
          };
        } else if (result && result.success) {
          responseMsg = {
            id: nanoid(),
            type: 'assistant',
            content: `✓ Executed: /${command}`,
            timestamp: new Date(),
          };
        } else {
          responseMsg = {
            id: nanoid(),
            type: 'system',
            content: result?.error || `Error executing: /${command}`,
            timestamp: new Date(),
          };
        }

        setMessages((prev) => [...prev, responseMsg]);
      } catch (error) {
        setMessages((prev) => [...prev, {
          id: nanoid(),
          type: 'system',
          content: `Error: ${error instanceof Error ? error.message : 'Unknown'}`,
          timestamp: new Date(),
        }]);
      } finally {
        setIsProcessing(false);
      }
    } else {
      // Natural language - use LLM if available
      if (llmClient.isAvailable()) {
        setIsProcessing(true);
        try {
          // Convert messages to session format for LLM history
          const history: SessionMessage[] = messages.map(msg => ({
            id: msg.id,
            type: msg.type,
            content: msg.content,
            timestamp: msg.timestamp.getTime(),
            ...(msg.issues ? {issues: msg.issues} : {}),
          }));

          const response = await llmClient.chat(value, history);

          const assistantMsg: Message = {
            id: nanoid(),
            type: 'assistant',
            content: response.content,
            timestamp: new Date(),
          };

          setMessages((prev) => [...prev, assistantMsg]);

          // Save to session
          if (session) {
            sessionManager.addMessage(session, {
              ...assistantMsg,
              timestamp: assistantMsg.timestamp.getTime(),
            });

            // Update token usage
            if (response.tokensUsed) {
              const currentTokens = sessionManager.getTokens(session);
              sessionManager.updateTokens(session, currentTokens.used + response.tokensUsed, currentTokens.limit);
            }
          }
        } catch (error) {
          setMessages((prev) => [...prev, {
            id: nanoid(),
            type: 'system',
            content: `LLM Error: ${error instanceof Error ? error.message : 'Unknown'}`,
            timestamp: new Date(),
          }]);
        } finally {
          setIsProcessing(false);
        }
      } else {
        // LLM not available
        setMessages((prev) => [...prev, {
          id: nanoid(),
          type: 'assistant',
          content: `💡 Try: /scan . or /help for available commands\n\nℹ️  LLM not configured. Set AZURE_OPENAI_API_KEY or ANTHROPIC_API_KEY for natural language support.`,
          timestamp: new Date(),
        }]);
      }
    }
  };

  // Keyboard shortcuts - works in all modes
  useInput((input, key) => {
    // Esc - close palettes/pickers
    if (key.escape) {
      if (showCommandPalette || showFilePicker) {
        setShowCommandPalette(false);
        setShowFilePicker(false);
        setInput(''); // Clear input too
        return;
      }
    }

    // Don't process other shortcuts when palettes are open
    if (showCommandPalette || showFilePicker) {
      return;
    }

    // Up Arrow - Navigate history (previous)
    if (key.upArrow && commandHistory.length > 0) {
      const newIndex = historyIndex + 1;
      if (newIndex < commandHistory.length) {
        setHistoryIndex(newIndex);
        setInput(commandHistory[commandHistory.length - 1 - newIndex] || '');
      }
      return;
    }

    // Down Arrow - Navigate history (next)
    if (key.downArrow && historyIndex >= 0) {
      const newIndex = historyIndex - 1;
      setHistoryIndex(newIndex);
      if (newIndex >= 0) {
        setInput(commandHistory[commandHistory.length - 1 - newIndex] || '');
      } else {
        setInput('');
      }
      return;
    }

    // Ctrl+C - Exit
    if (key.ctrl && input === 'c') {
      exit();
    }

    // Ctrl+L - Clear messages
    if (key.ctrl && input === 'l') {
      setMessages([]);
    }

    // Ctrl+P - Command palette
    if (key.ctrl && input === 'p') {
      setShowCommandPalette(true);
    }
  });

  const visibleMessages = messages.slice(-8);

  // Show command palette
  if (showCommandPalette) {
    return (
      <Box flexDirection="column" height="100%">
        <Box borderStyle="double" borderColor="cyan" paddingX={1} marginBottom={1}>
          <Text bold>⚡ Command Palette (Esc to close)</Text>
        </Box>
        <SelectInput items={AVAILABLE_COMMANDS} onSelect={handleCommandSelect} />
      </Box>
    );
  }

  // Show file picker
  if (showFilePicker && filteredFiles.length > 0) {
    return (
      <Box flexDirection="column" height="100%">
        <Box borderStyle="double" borderColor="cyan" paddingX={1} marginBottom={1}>
          <Text bold>📂 Select File {fileSearchQuery && `(filtering: "${fileSearchQuery}")`}</Text>
        </Box>
        <Box marginBottom={1} paddingX={1}>
          <Text dimColor>
            Showing {filteredFiles.length} files | Type to filter | ↑↓: Navigate | Enter: Select | Esc: Close
          </Text>
        </Box>
        <SelectInput items={filteredFiles} onSelect={handleFileSelect} limit={15} />
      </Box>
    );
  }

  return (
    <Box flexDirection="column" height="100%">
      {/* Messages */}
      <Box flexDirection="column" marginBottom={1} paddingX={1}>
        {visibleMessages.map((msg) => (
          <Box key={msg.id} marginBottom={1} flexDirection="column">
            <Box>
              <Text dimColor>{msg.timestamp.toLocaleTimeString()} </Text>
              <Text bold color={msg.type === 'user' ? 'cyan' : msg.type === 'assistant' ? 'green' : 'gray'}>
                {msg.type === 'user' ? '>' : msg.type === 'assistant' ? '🤖' : 'ℹ️ '}
              </Text>
              {msg.type === 'assistant' ? (
                <StreamingMessage
                  content={msg.content}
                  isStreaming={isProcessing && msg.id === messages[messages.length - 1]?.id}
                  showCursor={true}
                />
              ) : (
                <Text> {msg.content}</Text>
              )}
            </Box>
            {/* Show issues if present */}
            {msg.issues && msg.issues.length > 0 && (
              <Box marginLeft={2}>
                <IssueList issues={msg.issues} maxDisplay={5} />
              </Box>
            )}
          </Box>
        ))}
      </Box>

      {/* Enhanced Status Line */}
      <StatusLine
        status={{
          backend: backendConnected ? 'connected' : 'disconnected',
          messages: messages.length,
          thinking: isProcessing,
          ...(session ? {session: session.id.slice(0, 8)} : {}),
          ...(session ? {tokens: sessionManager.getTokens(session)} : {}),
          ...(llmClient.getProvider() ? {model: llmClient.getProvider()!} : {}),
        }}
        shortcuts="/: commands | @: files | Ctrl+R: history | Ctrl+P: palette | Ctrl+C: exit"
      />

      {/* Advanced Input */}
      <Box paddingX={1} paddingY={1}>
        <Text bold color="cyan">&gt; </Text>
        <AdvancedInput
          value={input}
          onChange={setInput}
          onSubmit={handleSubmit}
          placeholder={isProcessing ? 'Processing...' : 'Type / or @ or ask...'}
          isDisabled={isProcessing}
        />
      </Box>
    </Box>
  );
}
