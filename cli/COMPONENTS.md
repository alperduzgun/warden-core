# Warden CLI - Component Documentation

Comprehensive guide to the Ink UI components for Warden CLI.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Core Components](#core-components)
- [Custom Hooks](#custom-hooks)
- [Utilities](#utilities)
- [Theme System](#theme-system)
- [Type System](#type-system)
- [Testing](#testing)
- [Best Practices](#best-practices)

## Overview

The Warden CLI uses production-ready React components built with [Ink](https://github.com/vadimdemedes/ink). The implementation is inspired by [Qwen Code](https://github.com/QwenLM/Qwen2.5-Code) but adapted for Warden's security-focused mission.

### Key Features

- React hooks for state management
- TypeScript for type safety
- Command detection and autocomplete
- Real-time streaming messages
- Markdown rendering
- Comprehensive test coverage

## Architecture

```
cli/src/
├── App.tsx                 # Main application component
├── index.tsx              # Entry point
├── theme.ts               # Theme configuration
├── components/            # UI components
│   ├── Header.tsx         # Title and session info
│   ├── ChatArea.tsx       # Scrollable message list
│   ├── InputBox.tsx       # Command-aware input
│   ├── StreamingMessage.tsx # Real-time message updates
│   └── index.ts           # Component exports
├── hooks/                 # Custom React hooks
│   ├── useMessages.ts     # Message state management
│   └── useInput.ts        # Input state management
├── utils/                 # Utility functions
│   ├── commandDetector.ts # Command parsing
│   └── markdown.ts        # Markdown formatting
└── types/                 # TypeScript definitions
    └── index.ts           # Type exports
```

## Core Components

### App.tsx - Main Application

The root component that orchestrates the entire UI.

#### Features
- React hooks (useState, useEffect, useCallback, useInput)
- Layout with Header, ChatArea, InputBox
- Theme provider with Warden colors
- Command detection and handling
- Streaming message support
- Keyboard shortcuts (Ctrl+C to exit)

#### Props
```typescript
interface AppProps {
  initialSessionInfo?: Partial<SessionInfo>;
  onCommand?: (command: string, args?: string) => void;
  onSubmit?: (message: string) => void;
  onExit?: () => void;
}
```

#### Usage
```typescript
import { App } from './App';

<App
  initialSessionInfo={{
    projectPath: '/path/to/project',
    llmProvider: 'OpenAI',
    llmStatus: 'connected'
  }}
  onCommand={(command, args) => console.log('Command:', command, args)}
  onSubmit={(message) => console.log('Message:', message)}
  onExit={() => console.log('Exiting')}
/>
```

#### State Management
```typescript
// Input state
const [inputValue, setInputValue] = useState('');

// Session info
const [sessionInfo, setSessionInfo] = useState<SessionInfo>({...});

// Processing state
const [isProcessing, setIsProcessing] = useState(false);

// Messages (from hook)
const { messages, addMessage, startStreaming, ... } = useMessages();
```

---

### Header.tsx - Title and Session Info

Displays the Warden branding with gradient styling and session information.

#### Features
- Shield emoji (🛡️) with gradient title
- Version display
- Project path display
- Configuration file indicator
- LLM status with colored indicator
- Validation mode display
- Responsive layout

#### Props
```typescript
interface HeaderProps {
  sessionInfo: SessionInfo;
  version?: string; // Default: '0.1.0'
}

interface SessionInfo {
  projectPath?: string;
  configFile?: string;
  llmProvider?: string;
  llmModel?: string;
  llmStatus: 'connected' | 'disconnected' | 'error';
  validationMode?: string;
}
```

#### Usage
```typescript
<Header
  sessionInfo={{
    projectPath: '/path/to/project',
    configFile: '.warden.yml',
    llmProvider: 'OpenAI',
    llmModel: 'gpt-4',
    llmStatus: 'connected',
    validationMode: 'strict'
  }}
  version="0.1.0"
/>
```

#### Status Colors
- **Connected**: Green (●)
- **Disconnected**: Gray (○)
- **Error**: Red (✗)

---

### ChatArea.tsx - Scrollable Messages

Displays conversation history with support for multiple message types.

#### Features
- Multiple message types (user, assistant, system, error, success, warning)
- Markdown rendering
- Auto-scroll to bottom
- Streaming message support
- Timestamp display
- Message metadata support
- Empty state with tips

#### Props
```typescript
interface ChatAreaProps {
  messages: Message[];
  maxHeight?: number;
  autoScroll?: boolean; // Default: true
}

interface Message {
  id: string;
  type: MessageType;
  content: string;
  timestamp: Date;
  isStreaming?: boolean;
  metadata?: Record<string, unknown>;
}
```

#### Usage
```typescript
<ChatArea
  messages={[
    {
      id: '1',
      type: MessageType.USER,
      content: 'Hello',
      timestamp: new Date()
    },
    {
      id: '2',
      type: MessageType.ASSISTANT,
      content: 'Hi there!',
      timestamp: new Date()
    }
  ]}
  maxHeight={20}
  autoScroll={true}
/>
```

#### Message Type Colors
- **user**: Cyan
- **assistant**: White
- **system**: Yellow
- **error**: Red
- **success**: Green
- **warning**: Yellow

---

### InputBox.tsx - Command-Aware Input

Enhanced text input with command detection and autocomplete hints.

#### Features
- Command detection (/, @, !)
- Autocomplete suggestions (up to 3)
- Visual feedback for command types
- Processing state indicator
- Invalid command warnings
- Customizable placeholder
- Help text at bottom

#### Props
```typescript
interface InputBoxProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  placeholder?: string;
  isProcessing?: boolean;
}
```

#### Usage
```typescript
const [input, setInput] = useState('');

<InputBox
  value={input}
  onChange={setInput}
  onSubmit={(value) => {
    console.log('Submitted:', value);
    setInput('');
  }}
  placeholder="Type your message..."
  isProcessing={false}
/>
```

#### Supported Commands

**Slash Commands (/):**
- `/help` - Show available commands
- `/analyze [path]` - Analyze code
- `/validate [path]` - Validate code
- `/fix [issue-id]` - Apply fixes
- `/config [show|edit]` - Configuration
- `/clear` - Clear history
- `/exit` - Exit CLI

**Mentions (@):**
- `@file:path/to/file` - Reference file
- `@rule:rule-name` - Reference rule
- `@config` - Reference config

**Alerts (!):**
- `!critical` - Critical priority
- `!high` - High priority
- `!medium` - Medium priority
- `!low` - Low priority

#### Command Colors
- **Slash**: Cyan (⚡)
- **Mention**: Magenta (@)
- **Alert**: Red (!)
- **None**: White (›)

---

### StreamingMessage.tsx - Real-Time Updates

Displays messages that update in real-time as content streams in.

#### Features
- Gradual content accumulation
- Animated cursor during streaming
- Markdown rendering
- Completion detection
- Message type styling

#### Props
```typescript
interface StreamingMessageProps {
  content: string;
  type: MessageType;
  isComplete?: boolean; // Default: false
}
```

#### Usage
```typescript
const [content, setContent] = useState('');
const [isComplete, setIsComplete] = useState(false);

// Simulate streaming
useEffect(() => {
  const text = 'This is a streaming response...';
  let i = 0;
  const interval = setInterval(() => {
    if (i <= text.length) {
      setContent(text.slice(0, i));
      i += 5;
    } else {
      setIsComplete(true);
      clearInterval(interval);
    }
  }, 50);
  return () => clearInterval(interval);
}, []);

<StreamingMessage
  content={content}
  type={MessageType.ASSISTANT}
  isComplete={isComplete}
/>
```

#### Cursor Animation
- Visible: ▊
- Hidden: (space)
- Blink rate: 500ms

---

## Custom Hooks

### useMessages

Manages chat message state with streaming support.

#### Return Value
```typescript
interface UseMessagesReturn {
  messages: Message[];
  addMessage: (content: string, type: MessageType, metadata?: Record<string, unknown>) => Message;
  updateMessage: (id: string, content: string) => void;
  deleteMessage: (id: string) => void;
  clearMessages: () => void;
  startStreaming: (type: MessageType) => string;
  updateStreaming: (id: string, content: string) => void;
  completeStreaming: (id: string) => void;
  streamingState: StreamingState;
}
```

#### Usage
```typescript
const {
  messages,
  addMessage,
  startStreaming,
  updateStreaming,
  completeStreaming
} = useMessages();

// Add a regular message
addMessage('Hello!', MessageType.USER);

// Start streaming
const streamId = startStreaming(MessageType.ASSISTANT);

// Update streaming content
updateStreaming(streamId, 'Partial response...');

// Complete streaming
completeStreaming(streamId);
```

---

### useInput

Manages input state with command detection.

#### Return Value
```typescript
interface UseInputReturn {
  value: string;
  setValue: (value: string) => void;
  commandDetection: CommandDetection;
  suggestions: AutocompleteSuggestion[];
  handleSubmit: () => void;
  clear: () => void;
}
```

#### Usage
```typescript
const {
  value,
  setValue,
  commandDetection,
  suggestions,
  handleSubmit
} = useInput((value, detection) => {
  console.log('Submitted:', value);
  console.log('Command:', detection);
});

// Input is automatically tracked
// Command detection updates on change
// Suggestions update automatically
```

---

## Utilities

### commandDetector.ts

#### Functions

**detectCommand(input: string): CommandDetection**
```typescript
const detection = detectCommand('/analyze src/App.tsx');
// { type: 'slash', command: 'analyze', args: 'src/App.tsx', raw: '...' }
```

**getAutocompleteSuggestions(input: string)**
```typescript
const suggestions = getAutocompleteSuggestions('/ana');
// [{ type: 'slash', command: '/analyze', description: '...', syntax: '...' }]
```

**isValidCommand(detection: CommandDetection): boolean**
```typescript
const detection = detectCommand('/help');
isValidCommand(detection); // true

const invalid = detectCommand('/unknown');
isValidCommand(invalid); // false
```

**formatCommand(detection: CommandDetection): string**
```typescript
const detection = detectCommand('/analyze src/');
formatCommand(detection); // '/analyze src/'
```

**extractMentions(text: string): string[]**
```typescript
extractMentions('Check @file:src/App.tsx and @config');
// ['@file:src/App.tsx', '@config']
```

**extractAlerts(text: string): string[]**
```typescript
extractAlerts('This is !critical and !high priority');
// ['!critical', '!high']
```

**parseComplexInput(input: string)**
```typescript
parseComplexInput('/analyze @file:test.ts !critical fix this');
// {
//   primaryCommand: { type: 'slash', command: 'analyze', ... },
//   mentions: ['@file:test.ts'],
//   alerts: ['!critical'],
//   plainText: 'fix this'
// }
```

---

### markdown.ts

#### Functions

**stripMarkdown(markdown: string): string**
```typescript
stripMarkdown('**Bold** and `code`');
// 'Bold and code'
```

**formatMarkdown(markdown: string): string**
```typescript
formatMarkdown('**Bold** and *italic*');
// Returns ANSI-formatted string
```

**extractCodeBlocks(markdown: string)**
```typescript
extractCodeBlocks('```js\nconst x = 1;\n```');
// [{ language: 'js', code: 'const x = 1;\n', startIndex: 0, endIndex: 20 }]
```

**highlightCode(code: string, language: string): string**
```typescript
highlightCode('const x = 1;', 'javascript');
// Returns ANSI-formatted code with syntax highlighting
```

**truncateText(text: string, maxWidth: number, suffix?: string): string**
```typescript
truncateText('Very long text', 10);
// 'Very lo...'
```

**wordWrap(text: string, width: number): string**
```typescript
wordWrap('This is a long line', 10);
// 'This is a\nlong line'
```

**getTextWidth(text: string): number**
```typescript
getTextWidth('\x1b[31mHello\x1b[0m');
// 5 (ignores ANSI codes)
```

**padText(text: string, width: number, align?: 'left' | 'center' | 'right'): string**
```typescript
padText('Hello', 10, 'center');
// '  Hello   '
```

---

## Theme System

### Colors

```typescript
const WARDEN_COLORS = {
  // Primary brand colors
  shield: '#4A90E2',      // Blue - protection
  guardian: '#7B68EE',    // Purple - vigilance
  secure: '#2ECC71',      // Green - safe
  warning: '#F39C12',     // Orange - warnings
  critical: '#E74C3C',    // Red - critical

  // UI colors
  background: '#1E1E1E',
  foreground: '#E0E0E0',
  muted: '#6C757D',
  border: '#444444',

  // Syntax highlighting
  keyword: '#569CD6',
  string: '#CE9178',
  number: '#B5CEA8',
  comment: '#6A9955',
  function: '#DCDCAA',
  variable: '#9CDCFE',
};
```

### Gradients

```typescript
const titleGradient: GradientColors = [
  '#4A90E2', // Shield blue
  '#7B68EE', // Guardian purple
];
```

### Usage

```typescript
import { WARDEN_COLORS, titleGradient } from './theme';

<Text color={WARDEN_COLORS.shield}>Protected</Text>
<Gradient colors={titleGradient}>Title</Gradient>
```

---

## Type System

### Enums

```typescript
enum MessageType {
  USER = 'user',
  ASSISTANT = 'assistant',
  SYSTEM = 'system',
  ERROR = 'error',
  SUCCESS = 'success',
  WARNING = 'warning'
}

enum StreamingState {
  IDLE = 'idle',
  STREAMING = 'streaming',
  COMPLETE = 'complete',
  ERROR = 'error'
}

enum CommandType {
  SLASH = 'slash',
  MENTION = 'mention',
  ALERT = 'alert',
  NONE = 'none'
}
```

### Interfaces

```typescript
interface Message {
  id: string;
  type: MessageType;
  content: string;
  timestamp: Date;
  isStreaming?: boolean;
  metadata?: Record<string, unknown>;
}

interface SessionInfo {
  projectPath?: string;
  configFile?: string;
  llmProvider?: string;
  llmModel?: string;
  llmStatus: 'connected' | 'disconnected' | 'error';
  validationMode?: string;
}

interface CommandDetection {
  type: CommandType;
  command?: string;
  args?: string;
  raw: string;
}

interface AutocompleteSuggestion {
  type: CommandType;
  command: string;
  description: string;
  syntax?: string;
}
```

---

## Testing

### Test Files

```
utils/__tests__/
├── commandDetector.test.ts  # Command detection tests
└── markdown.test.ts         # Markdown utility tests

hooks/__tests__/
└── useMessages.test.ts      # Message hook tests
```

### Running Tests

```bash
# Run all tests
npm test

# Run with coverage
npm test -- --coverage

# Run specific test file
npm test -- commandDetector.test.ts

# Watch mode
npm test -- --watch
```

### Test Coverage Goals

- Utilities: ≥ 90%
- Hooks: ≥ 85%
- Components: ≥ 80%
- Overall: ≥ 80%

### Example Test

```typescript
import { detectCommand } from '../commandDetector';
import { CommandType } from '../../types';

describe('detectCommand', () => {
  it('should detect slash commands', () => {
    const result = detectCommand('/help');
    expect(result.type).toBe(CommandType.SLASH);
    expect(result.command).toBe('help');
  });

  it('should detect commands with arguments', () => {
    const result = detectCommand('/analyze src/App.tsx');
    expect(result.command).toBe('analyze');
    expect(result.args).toBe('src/App.tsx');
  });
});
```

---

## Best Practices

### Component Design

1. **Single Responsibility**: Each component should have one clear purpose
2. **Composability**: Build small, reusable components
3. **Props Interface**: Always define TypeScript interfaces for props
4. **Default Props**: Provide sensible defaults
5. **Documentation**: Add JSDoc comments

### State Management

1. **Local First**: Keep state as local as possible
2. **Custom Hooks**: Extract complex state logic into hooks
3. **useCallback**: Memoize event handlers
4. **useEffect Cleanup**: Always return cleanup functions
5. **Dependencies**: List all dependencies in useEffect/useCallback

### Performance

1. **Memoization**: Use useMemo for expensive computations
2. **Stable References**: Use useCallback for stable function references
3. **Avoid Re-renders**: Don't create new objects/arrays in render
4. **Profile**: Use React DevTools Profiler
5. **Lazy Loading**: Load components on demand when needed

### Error Handling

1. **Input Validation**: Validate all inputs
2. **Error Messages**: Provide clear, actionable error messages
3. **Type Safety**: Leverage TypeScript for compile-time safety
4. **Edge Cases**: Handle null, undefined, empty arrays
5. **Try-Catch**: Wrap async operations in try-catch

### Accessibility

1. **Screen Readers**: Support screen reader users
2. **Keyboard Nav**: Ensure keyboard navigation works
3. **Semantic Components**: Use semantic Ink components
4. **Terminal Width**: Test with different terminal widths
5. **Color Blindness**: Don't rely solely on color

---

## Patterns from Qwen Code

This implementation adapts these patterns from Qwen Code:

1. **Layout Structure**: Header → Content → Input pattern
2. **Streaming Messages**: Real-time content updates with cursor
3. **Command Detection**: Auto-completion and visual feedback
4. **Theme System**: Centralized color management
5. **Hook Architecture**: Custom hooks for state logic

## Differences from Qwen Code

1. **Security Focus**: Colors emphasize protection/security
2. **Command Types**: Added @mentions and !alerts
3. **Session Info**: Different metadata
4. **Simplified**: No IDE integration
5. **Validation-Centric**: Commands for security validation

---

## Contributing

When adding new components:

1. Follow existing patterns
2. Add comprehensive tests (≥80% coverage)
3. Document all props and functions
4. Update this documentation
5. TypeScript strict mode must pass
6. Test in different terminal environments

---

**Built with:**
- [Ink](https://github.com/vadimdemedes/ink) - React for CLI
- [React](https://react.dev) - Component framework
- [TypeScript](https://www.typescriptlang.org) - Type safety

**Inspired by:**
- [Qwen Code](https://github.com/QwenLM/Qwen2.5-Code) - AI coding assistant
