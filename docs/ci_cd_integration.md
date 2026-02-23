# CI/CD Integration Guide

Warden is designed to be a "Drop-in Security" solution for your CI/CD pipelines. This guide explains how to integrate verify your code automatically.

## 🚀 Quick Setup (Recommended)

The easiest way to set up CI/CD is using the CLI wizard:

```bash
warden init --ci
```

This command will:
1. Detect your project structure and primary branch.
2. Ask for your preferences (e.g., enable PR checks).
3. Automatically generate a `.github/workflows/warden-ci.yml` file.

## 🛠️ Manual Configuration

If you prefer to configure it manually or need advanced triggers, you can use the examples below.

### Production-Ready Environment (GitHub Actions)

This configuration mirrors the official Warden Core CI workflow. It includes:
*   **AI Model Caching:** Caches `~/.ollama` to prevent re-downloading large models (~5min savings).
*   **Offline-First Intelligence:** Uses local Qwen models for code understanding.
*   **Smart Scan Strategy:**
    *   **Baseline Scan:** Runs a full `deep` scan if no baseline exists (e.g., first run or manual trigger).
    *   **Incremental Scan:** Scans *only changed files* on PRs/pushes for maximum speed (<2min).

```yaml
name: Warden CI

on:
  push:
    branches: [ main, dev ]
  pull_request:
    branches: [ main, dev ]
  workflow_dispatch:

jobs:
  warden-scan:
    name: Self-Scan
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0 # Required for incremental git diff analysis

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install Warden
        run: |
          pip install --upgrade pip
          pip install -e .

      # 🧠 Cache AI Models (Crucial for Speed / Offline-First)
      - name: Cache AI Models
        uses: actions/cache@v4
        with:
          path: ~/.ollama
          key: ollama-models-${{ runner.os }}-${{ hashFiles('.warden/config.yaml') }}
          restore-keys: |
            ollama-models-${{ runner.os }}-

      # 🤖 Setup Local LLM (Ollama)
      - name: Setup Ollama
        run: |
          curl -fsSL https://ollama.com/install.sh | sh
          sudo systemctl stop ollama # Stop system service to run as runner user
          ollama serve &
          sleep 5 # Wait for server
          ollama pull qwen2.5-coder:3b # Pull or load from cache

      - name: Cache Baseline Report
        uses: actions/cache@v4
        with:
          path: .warden/baseline.sarif
          key: warden-baseline-${{ github.ref_name }}

      - name: Run Warden Scan
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }} # Optional (for Deep Tier)
          OLLAMA_HOST: http://localhost:11434
        run: |
          # Logic: If baseline exists, scan only changes. Else, deep scan all.
          if [[ -f ".warden/baseline.sarif" ]]; then
            echo "✅ Baseline found - Running INCREMENTAL SCAN"
            # Get changed files
            FILES=$(git diff --name-only --diff-filter=d origin/main...HEAD | grep "\.py$" || true)
            warden scan $FILES --level standard --format sarif --output warden.sarif
          else
            echo "🔍 No baseline - Running FULL DEEP SCAN"
            warden scan . --level deep --format sarif --output warden.sarif
            cp warden.sarif .warden/baseline.sarif # Save new baseline
          fi

      - name: Archive Results
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: warden-scan-results
          path: warden.sarif
```

### Excluding Files (.wardenignore)
To prevent "Integrity Check Failures" (e.g., scanning binary files or languages without installed parsers), creates a `.wardenignore` file:

```text
# .wardenignore
node_modules/
venv/
**/*.rs      # Exclude Rust if grammar not installed
Formula/     # Exclude brew formulas
```

