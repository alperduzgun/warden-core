# Contributing to Warden CLI

Thank you for your interest in contributing to Warden CLI! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Node.js >= 18.0.0
- npm >= 9.0.0
- Git
- A code editor (VS Code recommended)

### Initial Setup

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd warden-core/cli
   ```

2. **Install dependencies:**
   ```bash
   npm install
   ```

3. **Copy environment file:**
   ```bash
   cp .env.example .env
   ```

4. **Build the project:**
   ```bash
   npm run build
   ```

5. **Run in development mode:**
   ```bash
   npm run dev
   ```

## Code Standards

### TypeScript

- Use TypeScript strict mode
- Define types in `src/types/warden.d.ts`
- Avoid `any` types - use `unknown` or proper types
- Use functional components with React hooks

### Code Style

- **Formatting:** Follows ESLint rules
- **Naming:**
  - Components: PascalCase (e.g., `ChatArea`)
  - Functions: camelCase (e.g., `handleSubmit`)
  - Constants: UPPER_SNAKE_CASE (e.g., `API_TIMEOUT`)
  - Types: PascalCase (e.g., `ChatMessage`)

### File Organization

```
src/
├── components/       # React components
├── api/             # API client
├── config/          # Configuration
├── utils/           # Utility functions
└── types/           # TypeScript types
```

### Comments

- Use JSDoc for public functions
- Add inline comments for complex logic
- Keep comments concise and meaningful

Example:

```typescript
/**
 * Send a chat message to the Warden API
 *
 * @param message - The message content
 * @param sessionId - The current session ID
 * @returns API response with assistant's reply
 */
async chat(message: string, sessionId: string): Promise<WardenResponse>
```

## Making Changes

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
```

Branch naming:
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation
- `refactor/` - Code refactoring
- `test/` - Test additions

### 2. Make Your Changes

- Write clean, readable code
- Follow existing patterns
- Add/update types as needed
- Keep commits atomic and focused

### 3. Test Your Changes

```bash
# Type check
npm run type-check

# Lint
npm run lint

# Build
npm run build

# Run
npm start
```

### 4. Commit Your Changes

Use conventional commit messages:

```
type(scope): description

[optional body]

[optional footer]
```

Types:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation
- `style:` - Code style (formatting)
- `refactor:` - Code refactoring
- `test:` - Tests
- `chore:` - Maintenance

Examples:

```bash
git commit -m "feat(chat): add message history export"
git commit -m "fix(api): handle timeout errors gracefully"
git commit -m "docs(readme): update installation instructions"
```

### 5. Push and Create PR

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub.

## Pull Request Guidelines

### PR Title

Use the same format as commits:

```
feat(chat): add message history export
```

### PR Description

Include:

1. **What** - What does this PR do?
2. **Why** - Why is this change needed?
3. **How** - How does it work?
4. **Testing** - How was it tested?

Example:

```markdown
## What

Adds ability to export chat history to JSON file.

## Why

Users need to save conversations for later reference.

## How

- Added `/export` command
- Implemented JSON serialization
- Added file write functionality

## Testing

- Tested with multiple message types
- Verified JSON format
- Tested error handling for write failures
```

### PR Checklist

- [ ] Code follows style guidelines
- [ ] TypeScript types are correct
- [ ] All type checks pass
- [ ] Linting passes
- [ ] Build succeeds
- [ ] Manually tested changes
- [ ] Documentation updated
- [ ] Commit messages follow convention

## Adding New Features

### New Component

1. Create file in `src/components/`
2. Define props interface in `src/types/warden.d.ts`
3. Implement component
4. Export from `src/components/index.ts`
5. Add to appropriate parent component

Example:

```typescript
// src/types/warden.d.ts
export interface StatusBarProps {
  connected: boolean;
  messageCount: number;
}

// src/components/StatusBar.tsx
import React from 'react';
import { Box, Text } from 'ink';
import type { StatusBarProps } from '../types/warden.js';

export const StatusBar: React.FC<StatusBarProps> = ({ connected, messageCount }) => {
  return (
    <Box>
      <Text>Status: {connected ? 'Connected' : 'Disconnected'}</Text>
      <Text> | Messages: {messageCount}</Text>
    </Box>
  );
};

// src/components/index.ts
export { StatusBar } from './StatusBar.js';
```

### New Command

Add to `App.tsx` in `handleCommand`:

```typescript
case '/export':
  const filename = `warden-${Date.now()}.json`;
  const data = JSON.stringify(state.session.messages, null, 2);
  // Save to file...
  addMessage('system', `Exported to ${filename}`);
  return true;
```

### New API Endpoint

Add to `src/api/client.ts`:

```typescript
export: async (sessionId: string): Promise<ChatSession> => {
  try {
    const response = await client.get<ChatSession>(
      `/api/v1/sessions/${sessionId}/export`
    );
    return response.data;
  } catch (error) {
    logger.error('Export failed', error);
    throw new Error('Failed to export session');
  }
}
```

## Testing

### Manual Testing

1. Build the project:
   ```bash
   npm run build
   ```

2. Run the CLI:
   ```bash
   npm start
   ```

3. Test all affected features
4. Test error cases
5. Test edge cases

### Type Checking

```bash
npm run type-check
```

Fix all type errors before submitting PR.

### Linting

```bash
npm run lint
```

Auto-fix issues:

```bash
npm run lint -- --fix
```

## Common Tasks

### Add a Dependency

```bash
npm install package-name
```

For dev dependencies:

```bash
npm install --save-dev package-name
```

Update `package.json` with correct version.

### Update Types

Edit `src/types/warden.d.ts`:

```typescript
export interface NewType {
  field: string;
  optional?: number;
}
```

### Add Utility Function

Create in `src/utils/`:

```typescript
// src/utils/helpers.ts
export const formatDate = (date: Date): string => {
  return date.toISOString().split('T')[0] ?? '';
};
```

Export from `src/utils/index.ts`:

```typescript
export { formatDate } from './helpers.js';
```

## Debugging

### Enable Debug Logging

```bash
WARDEN_LOG_LEVEL=debug npm run dev
```

### Add Debug Statements

```typescript
import { logger } from '../utils/logger.js';

logger.debug('Variable value', { value });
logger.info('Operation completed');
logger.error('Operation failed', error);
```

### TypeScript Issues

Check types:

```bash
npm run type-check
```

## Documentation

### Update README

When adding features, update:
- Feature list
- Usage examples
- Configuration options
- Command list

### Add JSDoc Comments

For public APIs:

```typescript
/**
 * Description of what this does
 *
 * @param param1 - Description
 * @param param2 - Description
 * @returns Description
 * @throws {Error} When something fails
 */
```

### Update CHANGELOG

Add entry for your changes.

## Getting Help

- Check existing code for patterns
- Read TypeScript errors carefully
- Check the Ink documentation
- Ask questions in PR comments

## Code Review

All PRs require review before merging.

### Review Checklist

- [ ] Code is clear and readable
- [ ] Types are correct
- [ ] No console.log statements
- [ ] Error handling is proper
- [ ] Follows existing patterns
- [ ] Documentation is updated

## Release Process

1. Update version in `package.json`
2. Update CHANGELOG.md
3. Create git tag
4. Build and test
5. Publish to npm (if applicable)

## Questions?

Open an issue or reach out to the team.

Thank you for contributing!
