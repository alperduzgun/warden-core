/**
 * Type definitions for Warden CLI Ink UI
 */

/**
 * Message types in the chat interface
 */
export enum MessageType {
  USER = 'user',
  ASSISTANT = 'assistant',
  SYSTEM = 'system',
  ERROR = 'error',
  SUCCESS = 'success',
  WARNING = 'warning',
}

/**
 * Streaming state for real-time message updates
 */
export enum StreamingState {
  IDLE = 'idle',
  STREAMING = 'streaming',
  COMPLETE = 'complete',
  ERROR = 'error',
}

/**
 * Command types that can be detected in user input
 */
export enum CommandType {
  SLASH = 'slash', // /command
  MENTION = 'mention', // @mention
  ALERT = 'alert', // !alert
  NONE = 'none',
}

/**
 * Single message in the chat
 */
export interface Message {
  id: string;
  type: MessageType;
  content: string;
  timestamp: Date;
  isStreaming?: boolean;
  metadata?: Record<string, unknown>;
}

/**
 * Session information displayed in the header
 */
export interface SessionInfo {
  projectPath?: string;
  configFile?: string;
  llmProvider?: string;
  llmModel?: string;
  llmStatus: 'connected' | 'disconnected' | 'error';
  validationMode?: string;
}

/**
 * Command detection result
 */
export interface CommandDetection {
  type: CommandType;
  command?: string;
  args?: string;
  raw: string;
}

/**
 * Theme colors for Warden UI
 */
export interface ThemeColors {
  primary: string;
  secondary: string;
  accent: string;
  success: string;
  warning: string;
  error: string;
  info: string;
  background: string;
  foreground: string;
  muted: string;
  border: string;
}

/**
 * Gradient colors for title
 */
export type GradientColors = [string, string, ...string[]];

/**
 * Application state
 */
export interface AppState {
  messages: Message[];
  sessionInfo: SessionInfo;
  streamingState: StreamingState;
  currentInput: string;
  isProcessing: boolean;
  commandDetection?: CommandDetection;
}

/**
 * Props for the main App component
 */
export interface AppProps {
  initialSessionInfo?: Partial<SessionInfo>;
  onCommand?: (command: string, args?: string) => void;
  onSubmit?: (message: string) => void;
  onExit?: () => void;
}

/**
 * Props for Header component
 */
export interface HeaderProps {
  sessionInfo: SessionInfo;
  version?: string;
}

/**
 * Props for ChatArea component
 */
export interface ChatAreaProps {
  messages: Message[];
  maxHeight?: number;
  autoScroll?: boolean;
}

/**
 * Props for InputBox component
 */
export interface InputBoxProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  placeholder?: string;
  isProcessing?: boolean;
  commandDetection?: CommandDetection;
}

/**
 * Props for StreamingMessage component
 */
export interface StreamingMessageProps {
  content: string;
  type: MessageType;
  isComplete?: boolean;
}

/**
 * Autocomplete suggestion
 */
export interface AutocompleteSuggestion {
  type: CommandType;
  command: string;
  description: string;
  syntax?: string;
}

/**
 * Available slash commands
 */
export const SLASH_COMMANDS: AutocompleteSuggestion[] = [
  {
    type: CommandType.SLASH,
    command: '/analyze',
    description: 'Analyze code for security issues',
    syntax: '/analyze [path]',
  },
  {
    type: CommandType.SLASH,
    command: '/validate',
    description: 'Validate code against rules',
    syntax: '/validate [path]',
  },
  {
    type: CommandType.SLASH,
    command: '/fix',
    description: 'Apply automated fixes',
    syntax: '/fix [issue-id]',
  },
  {
    type: CommandType.SLASH,
    command: '/config',
    description: 'Show or edit configuration',
    syntax: '/config [show|edit]',
  },
  {
    type: CommandType.SLASH,
    command: '/help',
    description: 'Show help information',
    syntax: '/help [command]',
  },
  {
    type: CommandType.SLASH,
    command: '/clear',
    description: 'Clear chat history',
    syntax: '/clear',
  },
  {
    type: CommandType.SLASH,
    command: '/exit',
    description: 'Exit Warden CLI',
    syntax: '/exit',
  },
];

/**
 * Available @ mentions
 */
export const MENTION_COMMANDS: AutocompleteSuggestion[] = [
  {
    type: CommandType.MENTION,
    command: '@file',
    description: 'Reference a file',
    syntax: '@file:path/to/file',
  },
  {
    type: CommandType.MENTION,
    command: '@rule',
    description: 'Reference a validation rule',
    syntax: '@rule:rule-name',
  },
  {
    type: CommandType.MENTION,
    command: '@config',
    description: 'Reference configuration',
    syntax: '@config',
  },
];

/**
 * Available ! alerts
 */
export const ALERT_COMMANDS: AutocompleteSuggestion[] = [
  {
    type: CommandType.ALERT,
    command: '!critical',
    description: 'Mark as critical issue',
    syntax: '!critical',
  },
  {
    type: CommandType.ALERT,
    command: '!high',
    description: 'Mark as high priority',
    syntax: '!high',
  },
  {
    type: CommandType.ALERT,
    command: '!medium',
    description: 'Mark as medium priority',
    syntax: '!medium',
  },
  {
    type: CommandType.ALERT,
    command: '!low',
    description: 'Mark as low priority',
    syntax: '!low',
  },
];
