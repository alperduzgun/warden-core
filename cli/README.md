# Warden CLI

Modern, interactive CLI for Warden Code Analysis with AI-powered features.

## 🚀 Quick Start

### Development
```bash
cd cli
npm install
npm run dev     # Run with auto .env loading
```

### Production Build
```bash
npm run build
npm start       # Run with auto .env loading
```

## 🔧 Environment Configuration

The CLI reads environment variables from multiple sources (in order of priority):

1. **System environment variables** (GitHub Actions, Azure DevOps, Docker, etc.)
2. **`.env` file** in project root (for local development)
3. **`.warden/config.yaml`** (references environment variables)

### Local Development Setup

Create `.env` file in project root:

```bash
# .env (in warden-core/)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-01
```

The CLI automatically loads `.env` when you run:
- `npm run dev`
- `npm run start`

### CI/CD Setup

**GitHub Actions:**
```yaml
env:
  AZURE_OPENAI_API_KEY: ${{ secrets.AZURE_OPENAI_API_KEY }}
  AZURE_OPENAI_ENDPOINT: ${{ secrets.AZURE_OPENAI_ENDPOINT }}
```

**Azure DevOps:**
```yaml
variables:
  - name: AZURE_OPENAI_API_KEY
    value: $(AZURE_OPENAI_SECRET)
```

**Docker:**
```dockerfile
ENV AZURE_OPENAI_API_KEY=your-key
ENV AZURE_OPENAI_ENDPOINT=your-endpoint
```

## 🎨 Sprint 1 Features

### ✅ Advanced Input System
- **History Navigation:** ↑↓ keys to browse command history
- **Command Deduplication:** No duplicate commands in history
- **Input hints:** Visual shortcuts guide

### ✅ Enhanced Status Line
```
┌────────────────────────────────────────────────────────┐
│ ✓ Backend | Session: abc123de | 5 msgs | 4.2K/200K (2%) │
└────────────────────────────────────────────────────────┘
/: commands | @: files | ↑↓: history | Ctrl+P: palette
```

**Shows:**
- Backend connection status
- Session ID (truncated)
- Message count
- Token usage with percentage
- LLM model/provider
- Thinking indicator (💭)

### ✅ Streaming Messages
- Real-time LLM response streaming
- Blinking cursor animation (█)
- Progress indicators for long operations

### ✅ Session Management
- Automatic session save/load
- Token tracking across sessions
- History persistence

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `/` | Open command palette |
| `@` | Open file picker |
| `↑` `↓` | Navigate command history |
| `Ctrl+P` | Command palette |
| `Ctrl+L` | Clear messages |
| `Ctrl+C` | Exit |
| `Esc` | Close palette/picker |

## 📦 Available Commands

```bash
/help              # Show help
/scan <path>       # Scan directory
/analyze <file>    # Analyze file
/status            # Backend status
/clear             # Clear chat history
/exit              # Exit CLI
```

## 🧪 Testing LLM Features

1. **Ensure `.env` is configured** (see above)
2. **Run CLI:**
   ```bash
   npm start
   ```
3. **Check LLM status** - You should see:
   ```
   ✓ LLM available (azure) - Natural language supported!
   ```
4. **Test streaming:**
   ```
   > Merhaba, kodumu analiz edebilir misin?
   ```
   You'll see the blinking cursor (█) as the response streams in.

## 🏗️ Project Structure

```
cli/
├── src/
│   ├── components/
│   │   ├── AdvancedInput.tsx       # Enhanced input with hints
│   │   ├── StatusLine.tsx          # Enhanced status bar
│   │   ├── StreamingMessage.tsx    # Streaming text display
│   │   ├── ProgressBar.tsx         # Progress indicators
│   │   └── ChatInterfaceEnhanced.tsx
│   ├── hooks/
│   │   ├── useInputHistory.ts      # Command history
│   │   └── useKillRing.ts          # Kill/yank (unused in Sprint 1)
│   ├── utils/
│   │   └── sessionManager.ts       # Session save/load
│   └── cli.tsx                     # Entry point
└── package.json
```

## 📝 Implementation Notes

- **Environment Loading:** Uses `dotenv/config` preload via `-r` flag
- **ES Modules:** TypeScript compiles to ES modules (`"type": "module"`)
- **No `__dirname`:** Uses `-r dotenv/config` instead of manual path resolution
- **Clean Separation:** CLI doesn't hardcode .env paths - works in any environment

## 🔜 Next: Sprint 2

- Theme system (5 themes)
- Syntax highlighting for code blocks
- Enhanced spinner with rotating tips

## 📚 References

- Implementation details: `temp/sprint1-implementation-summary.md`
- Roadmap: `temp/ui-ux-improvement-roadmap.md`
- Rules: `temp/warden_core_rules.md`
