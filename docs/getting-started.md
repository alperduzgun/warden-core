# Getting Started with Warden

Warden is an AI-native security and quality gate that validates code before it enters your codebase. This guide gets you from zero to running your first scan in under five minutes.

---

## Installation

**Requirements:** Python 3.10+

```bash
pip install warden-core
```

### Optional Dependencies

Install extras based on your workflow:

```bash
# For fuzz testing support
pip install warden-core[fuzz]

# For property-based testing support
pip install warden-core[property]

# For all extras
pip install warden-core[all]
```

Verify the installation:

```bash
warden --version
```

---

## Quick Start (30 seconds)

```bash
pip install warden-core
cd your-project
warden init
warden scan --quick-start
```

`--quick-start` runs a deterministic scan with no LLM required — useful for getting an immediate baseline before configuring an AI provider.

---

## Initialization

Run `warden init` once per project to set up the configuration scaffolding:

```bash
warden init
```

This command:
1. Detects your project stack (Python, JS/TS, Go, Java, Dart, etc.)
2. Creates `.warden/config.yaml` with sensible defaults
3. Creates `.warden/AI_RULES.md` for AI agent context
4. Configures Claude Code hooks (`.claude/settings.json`) if present
5. Sets up MCP configuration for AI tool integration
6. Creates `.env` and `.env.example` for your API keys

### Init Flags

| Flag | Description |
|------|-------------|
| `--agent` / `--no-agent` | Configure AI agent files and MCP registration (default: on) |
| `--baseline` / `--no-baseline` | Create an initial baseline from current issues (default: on) |
| `--intel` / `--no-intel` | Generate project intelligence for CI optimization (default: on) |
| `--grammars` / `--no-grammars` | Install missing tree-sitter grammars (default: on) |
| `--ci` | Also generate a GitHub Actions workflow file |
| `--provider` | Set LLM provider non-interactively (for CI/headless use) |

**CI / headless environments:**

```bash
warden init --no-agent --skip-mcp --no-grammars --provider groq
```

---

## Configuration

After `warden init`, your project has a `.warden/config.yaml` file. The most important section is the LLM provider.

### LLM Setup

Warden supports local and cloud providers. Pick the one that matches your setup.

#### Option 1: Claude Code CLI (no API key needed)

If you have the Claude Code CLI installed and authenticated:

```bash
warden config llm use claude_code
warden config llm test
```

#### Option 2: Ollama (free, fully offline)

```bash
# Pull the recommended model
ollama pull qwen2.5-coder:7b

# Warden auto-detects Ollama when it is running
warden scan
```

#### Option 3: Codex CLI

```bash
warden config llm use codex
warden config llm test
```

#### Option 4: Cloud providers (API key required)

```bash
# Choose a provider
warden config llm use anthropic   # or: openai, groq, gemini, deepseek, azure

# Set the matching environment variable
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export GROQ_API_KEY=gsk_...
export GEMINI_API_KEY=...
```

Check what is currently active:

```bash
warden config llm status
```

### warden.yaml Basics

A minimal `.warden/config.yaml`:

```yaml
project:
  name: my-project
  language: python          # primary language

llm:
  auto_detect: true
  active_provider: ollama   # or: claude_code, anthropic, openai, groq

  providers:
    ollama:
      enabled: true
      endpoint: http://localhost:11434
      model: qwen2.5-coder:7b

settings:
  fail_fast: false          # stop pipeline on first critical finding
  use_llm: true             # enable AI-powered analysis

baseline:
  enabled: true
  path: .warden/baseline.json
```

For the full provider configuration reference see the [Configuration section in the README](../README.md#configuration).

---

## Analysis Levels

Warden offers three analysis levels that trade speed for depth:

| Level | What It Runs | Best For |
|-------|-------------|----------|
| `basic` | Regex rules, no LLM | Pre-commit hooks, fastest feedback |
| `standard` | AST analysis + LLM verification | Default — balanced speed and depth |
| `deep` | Full taint analysis + all frames + LLM | PR gates, nightly scans |

```bash
warden scan --level basic      # fastest
warden scan --level standard   # default
warden scan --level deep       # most thorough
```

For a detailed breakdown of what each level enables, see [docs/analysis-levels.md](./analysis-levels.md).

---

## CI/CD Integration

### Fastest path: GitHub Actions composite action

```yaml
# .github/workflows/warden.yml
name: Warden Security Scan

on:
  push:
    branches: [main, dev]
  pull_request:
    branches: [main, dev]

jobs:
  warden:
    runs-on: ubuntu-latest
    permissions:
      security-events: write

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: alperduzgun/warden-core@main
        with:
          level: standard
          format: sarif
          output-file: warden.sarif
          upload-sarif: "true"
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
```

Findings appear in the **Security > Code Scanning** tab as native alerts alongside CodeQL.

### Manual workflow (more control)

```yaml
- name: Run Warden Scan
  env:
    GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
    WARDEN_LLM_PROVIDER: groq
  run: |
    pip install warden-core
    warden scan . --level standard --format sarif --output warden.sarif

- name: Upload to GitHub Security
  uses: github/codeql-action/upload-sarif@v4
  if: always()
  with:
    sarif_file: warden.sarif
    category: warden-security
```

### Incremental scans on PRs

Only scan what changed — scans finish in seconds:

```bash
warden scan --diff                        # changed files vs main
warden scan --diff --base origin/develop  # changed files vs develop
```

For a full CI/CD setup guide including baseline autopilot and Ollama model caching, see [docs/ci_cd_integration.md](./ci_cd_integration.md).

---

## Common Commands

```bash
# Run a full scan on the current directory
warden scan

# Scan specific files or directories
warden scan src/ tests/

# Scan only changed files (fast, ideal for local dev)
warden scan --diff

# Deterministic scan, no LLM required
warden scan --quick-start

# Output as SARIF (for GitHub Security tab)
warden scan --format sarif --output warden.sarif

# Output as JSON
warden scan --format json --output report.json

# Apply auto-fixable issues
warden scan --auto-fix

# Preview auto-fixes without applying
warden scan --auto-fix --dry-run

# Show per-frame LLM cost breakdown
warden scan --cost-report

# Show per-phase timing
warden scan --benchmark

# Check LLM provider status
warden config llm status

# Test LLM provider connection
warden config llm test

# Switch LLM provider
warden config llm use ollama

# Check project health and configuration
warden doctor

# View current config
warden config list

# Get a specific config value
warden config get llm.active_provider

# Set a specific config value
warden config set settings.fail_fast true
```

---

## Troubleshooting

### "No LLM provider configured"

Run the quick-start scan to confirm Warden itself is working, then set up a provider:

```bash
warden scan --quick-start   # works without any LLM
warden config llm status    # see what is available
```

For zero-configuration analysis, install Ollama and pull the model:

```bash
ollama pull qwen2.5-coder:7b
warden scan
```

### "ANTHROPIC_API_KEY not set" (or similar)

Export the key for the provider you selected:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# Then verify
warden config llm test
```

### "Ollama is not running"

Start the Ollama service and confirm the model is present:

```bash
ollama serve
ollama list    # should show qwen2.5-coder:7b
warden scan
```

If Ollama is running on a non-default address, update `.warden/config.yaml`:

```yaml
llm:
  providers:
    ollama:
      endpoint: http://192.168.1.100:11434
```

### "warden init already ran, config exists"

Re-initialize without overwriting existing config:

```bash
warden init           # safe to re-run, skips existing files
warden init --force   # overwrites existing config
```

### Scan is too slow

Use incremental mode or reduce the analysis level:

```bash
warden scan --diff            # only changed files
warden scan --level basic     # no LLM, fastest
warden scan --quick-start     # deterministic only
```

Enable smart caching (on by default) — repeat scans of unchanged files complete in milliseconds.

### False positives

Suppress a specific finding inline:

```python
result = execute_query(query)  # warden-ignore: security-sql_injection
```

Or add a project-wide suppression rule in `.warden/rules/suppressions.yaml`:

```yaml
enabled: true
entries:
  - id: suppress-fp-streams
    rules:
      - stress-unclosed_file
    file: src/utils/stream.py
    reason: Standard streams managed by system
```

### "warden doctor" shows missing dependencies

Run the doctor command and follow its instructions:

```bash
warden doctor
```

It checks for required tools, LLM connectivity, grammar files, and configuration validity, then prints actionable remediation steps.

---

## Next Steps

- [CI/CD Integration Guide](./ci_cd_integration.md) — full pipeline setup with baseline autopilot
- [Custom Frames](./CUSTOM_FRAMES.md) — write your own validation rules
- [Rule Creation Guide](./RULE_CREATION_GUIDE.md) — extend Warden with project-specific rules
- [Command Reference](../README.md#command-reference) — full list of CLI flags
