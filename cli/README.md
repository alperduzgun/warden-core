# Warden CLI

Interactive CLI interface for Warden - AI-Powered DevSecOps Validation Platform

## Overview

Warden CLI provides a beautiful, interactive terminal interface for communicating with the Warden AI platform. Built with [Ink](https://github.com/vadimdemedes/ink) and React, it offers a seamless chat-like experience for DevOps validation, security analysis, and infrastructure recommendations.

## Features

- **Interactive Chat Interface**: Real-time conversation with Warden AI
- **Beautiful UI**: Modern terminal interface with colors and gradients
- **Command System**: Powerful slash commands for quick actions
- **Session Management**: Persistent conversation history
- **Error Handling**: Graceful error handling and recovery
- **TypeScript**: Full type safety and IntelliSense support

## Installation

### Prerequisites

- Node.js >= 18.0.0
- npm, yarn, or pnpm

### Install Dependencies

```bash
npm install
```

### Build

```bash
npm run build
```

### Development

```bash
npm run dev
```

## Usage

### Start the CLI

```bash
npm start
```

Or directly with:

```bash
node dist/index.js
```

Or if installed globally:

```bash
warden-chat
```

### Commands

The CLI supports the following slash commands:

- `/help` - Show available commands
- `/clear` - Clear conversation history
- `/status` - Show connection status and session info
- `/config` - Display current configuration
- `/exit` or `/quit` - Exit the application

### Environment Variables

Configure the CLI using environment variables:

```bash
# Required
WARDEN_API_URL=http://localhost:8000

# Optional
WARDEN_API_KEY=your-api-key
WARDEN_TIMEOUT=30000
WARDEN_MAX_RETRIES=3
WARDEN_LOG_LEVEL=info
```

Create a `.env` file in the CLI directory:

```env
WARDEN_API_URL=http://localhost:8000
WARDEN_API_KEY=your-secret-key
```

## Development

### Project Structure

```
cli/
├── package.json          # Dependencies and scripts
├── tsconfig.json         # TypeScript configuration
├── .eslintrc.json       # ESLint rules
├── .gitignore           # Git ignore patterns
├── src/
│   ├── index.tsx        # Entry point
│   ├── App.tsx          # Main app component
│   ├── components/      # UI components
│   │   ├── Header.tsx   # Header with branding
│   │   ├── ChatArea.tsx # Message display
│   │   └── InputBox.tsx # User input handling
│   └── types/           # TypeScript types
│       └── warden.d.ts  # Type definitions
└── README.md
```

### Scripts

- `npm run dev` - Run in development mode with hot reload
- `npm run build` - Build for production
- `npm start` - Run built version
- `npm run type-check` - Type check without emitting
- `npm run lint` - Run ESLint
- `npm run clean` - Remove build artifacts

### Adding New Components

1. Create a new file in `src/components/`
2. Define props interface in `src/types/warden.d.ts`
3. Export the component
4. Import and use in `App.tsx`

Example:

```tsx
// src/components/MyComponent.tsx
import React from 'react';
import { Box, Text } from 'ink';
import type { MyComponentProps } from '../types/warden.js';

export const MyComponent: React.FC<MyComponentProps> = ({ prop1, prop2 }) => {
  return (
    <Box>
      <Text>{prop1}</Text>
    </Box>
  );
};
```

### Adding New Commands

Add command handlers in `App.tsx`:

```tsx
const handleCommand = useCallback(
  async (command: string): Promise<boolean> => {
    const cmd = command.toLowerCase();

    switch (cmd) {
      case '/mycommand':
        addMessage('system', 'My command executed!');
        return true;

      // ... other commands
    }
  },
  [addMessage]
);
```

## API Integration

### Implementing API Client

Create an API client to communicate with the Warden backend:

```tsx
// src/api/client.ts
import axios from 'axios';
import type { APIClient, WardenResponse } from '../types/warden.js';

export const createAPIClient = (config: WardenConfig): APIClient => {
  const client = axios.create({
    baseURL: config.apiUrl,
    timeout: config.timeout,
    headers: {
      'Content-Type': 'application/json',
      ...(config.apiKey && { Authorization: `Bearer ${config.apiKey}` }),
    },
  });

  return {
    chat: async (message, sessionId) => {
      const response = await client.post<WardenResponse>('/chat', {
        message,
        session_id: sessionId,
      });
      return response.data;
    },
    // ... other methods
  };
};
```

### Using the API Client

Update `App.tsx` to use the actual API:

```tsx
const handleSubmit = useCallback(
  async (input: string) => {
    addMessage('user', input);
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    try {
      const apiClient = createAPIClient(state.config);
      const response = await apiClient.chat(input, state.session.id);

      if (response.success && response.data) {
        addMessage('assistant', response.data.message);
      }
    } catch (error) {
      // Handle error
    }
  },
  [addMessage, state.config, state.session.id]
);
```

## Testing

### Unit Tests

```bash
npm test
```

### Type Checking

```bash
npm run type-check
```

### Linting

```bash
npm run lint
```

## Troubleshooting

### Common Issues

**Issue**: `Cannot find module 'ink'`
**Solution**: Run `npm install` to install dependencies

**Issue**: TypeScript errors
**Solution**: Run `npm run type-check` to see all type errors

**Issue**: CLI not starting
**Solution**: Check that `.env` file has correct `WARDEN_API_URL`

**Issue**: Build fails
**Solution**: Run `npm run clean` then `npm run build`

### Debug Mode

Enable debug logging:

```bash
WARDEN_LOG_LEVEL=debug npm start
```

## Production Deployment

### Build for Production

```bash
npm run build
```

### Run in Production

```bash
NODE_ENV=production node dist/index.js
```

### Install Globally

```bash
npm link
```

Then run anywhere:

```bash
warden-chat
```

## Architecture

### Component Hierarchy

```
App
├── Header (branding, status)
├── ChatArea (message history)
│   └── Message items
└── InputBox (user input)
```

### State Management

- **Local State**: React hooks (`useState`, `useCallback`)
- **Session State**: Managed in `AppState` interface
- **Message History**: Array of `ChatMessage` objects

### Type Safety

All components and functions are fully typed with TypeScript. Type definitions are in `src/types/warden.d.ts`.

## Contributing

### Code Style

- Use TypeScript strict mode
- Follow ESLint rules
- Use functional components
- Use React hooks
- Add JSDoc comments
- Handle all error cases

### Pull Requests

1. Create a feature branch
2. Make changes
3. Run tests and linting
4. Submit PR with description

## License

MIT

## Support

For issues and questions:
- GitHub Issues: [warden-core/issues](https://github.com/your-org/warden-core/issues)
- Documentation: [docs/](../docs/)

## Roadmap

- [ ] API client implementation
- [ ] Validation result visualization
- [ ] File upload support
- [ ] Configuration wizard
- [ ] History search
- [ ] Export conversations
- [ ] Plugin system
- [ ] Themes support

## Credits

Built with:
- [Ink](https://github.com/vadimdemedes/ink) - React for CLI
- [React](https://react.dev/) - UI framework
- [TypeScript](https://www.typescriptlang.org/) - Type safety
- [Chalk](https://github.com/chalk/chalk) - Terminal colors
- [Zod](https://github.com/colinhacks/zod) - Validation
