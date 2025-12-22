# Warden CLI - Installation Guide

Complete installation and setup guide for the Warden CLI.

## System Requirements

### Required

- **Node.js** >= 18.0.0
- **npm** >= 9.0.0 (comes with Node.js)
- **Git** (for cloning the repository)

### Recommended

- **Terminal** with Unicode support (for emojis and special characters)
- **VS Code** or similar IDE with TypeScript support
- **Modern terminal emulator** (iTerm2, Hyper, Windows Terminal, etc.)

### Check Your System

```bash
node --version   # Should show v18.0.0 or higher
npm --version    # Should show 9.0.0 or higher
```

## Installation Steps

### 1. Navigate to CLI Directory

```bash
cd /path/to/warden-core/cli
```

### 2. Install Dependencies

```bash
npm install
```

This installs:
- Ink 6.2.3 - React for CLI
- React 19.1.0 - UI framework
- TypeScript 5.3.3 - Type safety
- Axios - HTTP client
- Zod - Validation
- And all other dependencies

### 3. Configure Environment

Create your environment file:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# Required: Warden API endpoint
WARDEN_API_URL=http://localhost:8000

# Optional: API authentication
WARDEN_API_KEY=your-api-key-here

# Optional: Connection settings
WARDEN_TIMEOUT=30000
WARDEN_MAX_RETRIES=3

# Optional: Logging
WARDEN_LOG_LEVEL=info
```

### 4. Build the Project

```bash
npm run build
```

This compiles TypeScript to JavaScript in the `dist/` folder.

### 5. Verify Installation

Run the verification script:

```bash
./verify-setup.sh
```

This checks:
- Node.js version
- All required files
- Project structure
- Dependencies
- Configuration

## Running the CLI

### Development Mode

For development with hot reload:

```bash
npm run dev
```

Or use the helper script:

```bash
./dev.sh
```

### Production Mode

For production use:

```bash
npm start
```

Or directly:

```bash
node dist/index.js
```

## Global Installation

To use `warden-chat` command globally:

```bash
npm link
```

Then run from anywhere:

```bash
warden-chat
```

To unlink:

```bash
npm unlink
```

## Verification

After installation, verify everything works:

### 1. Type Check

```bash
npm run type-check
```

Should show no errors.

### 2. Lint Check

```bash
npm run lint
```

Should pass without errors.

### 3. Build Check

```bash
npm run build
```

Should create `dist/` folder with compiled files.

### 4. Run Check

```bash
npm start
```

Should display the Warden CLI interface.

## Directory Structure After Installation

```
cli/
├── node_modules/       # Dependencies (created by npm install)
├── dist/              # Compiled output (created by npm run build)
├── src/               # Source code
├── package.json       # Dependencies
├── tsconfig.json      # TypeScript config
├── .env              # Your environment (create from .env.example)
└── ...
```

## Troubleshooting

### Issue: npm install fails

**Solution:**
```bash
# Clear npm cache
npm cache clean --force

# Remove node_modules and lock file
rm -rf node_modules package-lock.json

# Reinstall
npm install
```

### Issue: TypeScript errors during build

**Solution:**
```bash
# Check for type errors
npm run type-check

# Clean and rebuild
npm run clean
npm run build
```

### Issue: Module not found errors

**Solution:**
```bash
# Ensure all dependencies are installed
npm install

# Check package.json for missing dependencies
```

### Issue: Permission errors on scripts

**Solution:**
```bash
# Make scripts executable
chmod +x dev.sh
chmod +x verify-setup.sh
```

### Issue: Node version too old

**Solution:**
```bash
# Install NVM (Node Version Manager)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash

# Install Node.js 18
nvm install 18
nvm use 18
```

### Issue: Port/API connection errors

**Solution:**
- Check that `WARDEN_API_URL` in `.env` is correct
- Ensure the Warden backend is running
- Verify network connectivity

### Issue: Build succeeds but runtime errors

**Solution:**
```bash
# Enable debug logging
WARDEN_LOG_LEVEL=debug npm start
```

## Platform-Specific Notes

### macOS

- Use Homebrew to install Node.js: `brew install node`
- Terminal.app works, but iTerm2 recommended
- Ensure Xcode Command Line Tools installed

### Linux

- Use package manager: `apt install nodejs npm` or `yum install nodejs npm`
- May need to add user to permissions groups
- Check firewall settings for API connection

### Windows

- Use Node.js installer from nodejs.org
- Use Windows Terminal or PowerShell
- May need to enable Developer Mode
- Use WSL2 for best experience

## Updating

### Update Dependencies

```bash
npm update
```

### Update to Latest Packages

```bash
npm install ink@latest
npm install react@latest
# ... etc
```

### Rebuild After Updates

```bash
npm run clean
npm run build
```

## Development Setup

For contributing to the CLI:

### 1. Install Dev Dependencies

```bash
npm install --save-dev
```

### 2. Setup ESLint

ESLint is already configured in `.eslintrc.json`.

### 3. Setup VS Code

Install recommended extensions:
- ESLint
- TypeScript and JavaScript Language Features
- Prettier (optional)

### 4. Run in Watch Mode

```bash
npm run dev
```

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WARDEN_API_URL` | No | `http://localhost:8000` | Warden backend API URL |
| `WARDEN_API_KEY` | No | - | API authentication key |
| `WARDEN_TIMEOUT` | No | `30000` | Request timeout (ms) |
| `WARDEN_MAX_RETRIES` | No | `3` | Max retry attempts |
| `WARDEN_LOG_LEVEL` | No | `info` | Log level (debug/info/warn/error) |

## Testing the Installation

### Quick Test

```bash
# Start the CLI
npm start

# You should see:
# 🛡️ Warden - AI Code Guardian v0.1.0
# ─────────────────────────────────────
# Type /help for available commands
```

### Test Commands

Try these commands:

```bash
/help      # Show help
/status    # Check status
/config    # View config
/exit      # Exit
```

### Test Chat

Type a message and press Enter:

```
Hello, Warden!
```

You should see a response (or placeholder if backend not connected).

## Next Steps

After successful installation:

1. Read [QUICKSTART.md](QUICKSTART.md) for usage guide
2. Review [README.md](README.md) for full documentation
3. Check [CONTRIBUTING.md](CONTRIBUTING.md) to contribute
4. Start using the CLI with your Warden backend

## Support

If you encounter issues:

1. Check this guide's troubleshooting section
2. Run `./verify-setup.sh` to diagnose issues
3. Enable debug logging: `WARDEN_LOG_LEVEL=debug npm start`
4. Check GitHub issues
5. Review documentation in `docs/`

## Uninstallation

To remove the CLI:

```bash
# Unlink if globally installed
npm unlink

# Remove node_modules and build artifacts
rm -rf node_modules dist

# Remove environment file (if desired)
rm .env
```

To completely remove from system:

```bash
cd ..
rm -rf cli/
```

---

**Installation Complete!** 🎉

You're ready to use Warden CLI. Run `npm start` to begin.
