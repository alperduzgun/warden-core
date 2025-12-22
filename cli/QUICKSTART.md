# Warden CLI - Quick Start Guide

Get up and running with the Warden CLI in under 5 minutes.

## Prerequisites

- Node.js 18 or higher
- npm (comes with Node.js)

Check your versions:

```bash
node --version  # Should be v18.0.0 or higher
npm --version
```

## Installation

### 1. Install Dependencies

```bash
cd cli
npm install
```

This will install all required packages including:
- Ink (React for CLI)
- TypeScript
- Zod (validation)
- Axios (HTTP client)

### 2. Configure Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and set your Warden API URL:

```env
WARDEN_API_URL=http://localhost:8000
WARDEN_API_KEY=your-api-key-here  # Optional
```

### 3. Build the CLI

```bash
npm run build
```

This compiles TypeScript to JavaScript in the `dist/` folder.

## Running the CLI

### Development Mode (with hot reload)

```bash
npm run dev
```

Or use the helper script:

```bash
./dev.sh
```

### Production Mode

```bash
npm start
```

## First Steps

Once the CLI starts, you'll see:

```
WARDEN
AI-Powered DevSecOps Validation Platform
Status: Connected

Session: abc12345...

Type your message or use /help for commands
────────────────────────────────────────────────────────────────────────────────

> _
```

### Try These Commands

1. **Get help:**
   ```
   /help
   ```

2. **Check status:**
   ```
   /status
   ```

3. **View configuration:**
   ```
   /config
   ```

4. **Ask a question:**
   ```
   How do I validate my Docker configuration?
   ```

5. **Clear history:**
   ```
   /clear
   ```

6. **Exit:**
   ```
   /exit
   ```
   Or press `Ctrl+C`

## Common Issues

### Port Already in Use

If the API is not accessible:
- Check that the Warden backend is running
- Verify `WARDEN_API_URL` in `.env`

### Dependencies Not Found

```bash
rm -rf node_modules package-lock.json
npm install
```

### TypeScript Errors

```bash
npm run type-check
```

### Build Issues

```bash
npm run clean
npm run build
```

## Development Workflow

1. **Make changes** to files in `src/`
2. **Test in dev mode:**
   ```bash
   npm run dev
   ```
3. **Type check:**
   ```bash
   npm run type-check
   ```
4. **Lint code:**
   ```bash
   npm run lint
   ```
5. **Build for production:**
   ```bash
   npm run build
   ```

## Project Structure

```
cli/
├── src/
│   ├── index.tsx          # Entry point
│   ├── App.tsx            # Main component
│   ├── components/        # UI components
│   ├── api/              # API client
│   ├── config/           # Configuration
│   ├── utils/            # Utilities
│   └── types/            # TypeScript types
├── dist/                 # Built files (git-ignored)
├── package.json          # Dependencies
└── tsconfig.json         # TypeScript config
```

## Next Steps

- Read the [full README](README.md) for detailed documentation
- Explore the [API client](src/api/client.ts) implementation
- Check out the [component examples](src/components/)
- Learn about [custom commands](README.md#adding-new-commands)

## Tips

1. **Use TypeScript features** - IntelliSense works in VS Code
2. **Check logs** - Set `WARDEN_LOG_LEVEL=debug` for verbose output
3. **Hot reload** - Changes auto-reload in dev mode
4. **Test commands** - Try `/status` and `/config` first

## Getting Help

- Check [README.md](README.md) for full documentation
- Review TypeScript types in `src/types/warden.d.ts`
- Enable debug logging: `WARDEN_LOG_LEVEL=debug`

## Example Session

```
> Hello Warden!

Warden [12:34:56]
Hello! I'm Warden, your AI-powered DevSecOps assistant. How can I help you today?

> /status

System [12:35:01]
Connection Status: Connected
API URL: http://localhost:8000
Session ID: abc123def456
Messages: 3

> /exit

System [12:35:10]
Goodbye!
```

Happy validating!
