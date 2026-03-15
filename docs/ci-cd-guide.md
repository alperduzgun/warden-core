# CI/CD Integration Guide

Warden integrates into any CI/CD pipeline to automatically scan code for security
vulnerabilities, anti-patterns, and policy violations. This guide provides
copy-paste-ready examples for GitHub Actions, GitLab CI, and generic CI systems.

## Table of Contents

- [Quick Setup with the CLI Wizard](#quick-setup-with-the-cli-wizard)
- [Exit Codes](#exit-codes)
- [GitHub Actions](#github-actions)
  - [Using the Marketplace Action (Simplest)](#using-the-marketplace-action-simplest)
  - [Manual pip Install Workflow](#manual-pip-install-workflow)
  - [SARIF Upload to Security Tab](#sarif-upload-to-github-security-tab)
  - [PR Comment Integration](#pr-comment-integration)
  - [Example: Basic Scan on Every PR](#example-basic-scan-on-every-pr)
  - [Example: Deep Scan on Main Only](#example-deep-scan-on-main-only)
  - [Example: Incremental Scan with --diff](#example-incremental-scan-with---diff)
  - [Example: Nightly Full Scan with Baseline Update](#example-nightly-full-scan-with-baseline-update)
  - [Example: Release Security Audit](#example-release-security-audit)
- [GitLab CI](#gitlab-ci)
  - [Basic Template](#basic-template)
  - [SAST Integration](#sast-integration)
  - [Merge Request Only Scan](#merge-request-only-scan)
- [General CI](#general-ci)
  - [Environment Variables Reference](#environment-variables-reference)
  - [Caching .warden/ for Faster Runs](#caching-warden-for-faster-runs)
  - [CI Mode Behavior (--ci)](#ci-mode-behavior---ci)
  - [LLM-Free Scanning (--quick-start)](#llm-free-scanning---quick-start)
  - [Incremental Scanning (--diff)](#incremental-scanning---diff)
  - [Output Formats](#output-formats)
- [Best Practices](#best-practices)

---

## Quick Setup with the CLI Wizard

The fastest way to add Warden to an existing repository is the built-in CI
scaffolding command. It auto-detects your CI provider and writes the workflow
files for you:

```bash
# Auto-detect provider (GitHub or GitLab)
warden ci init

# Specify provider explicitly
warden ci init --provider github
warden ci init --provider gitlab --branch main

# Overwrite existing workflow files
warden ci init --force
```

After init, check workflow status at any time:

```bash
warden ci status
warden ci status --json
```

Keep workflows in sync when you update Warden or change LLM providers:

```bash
warden ci update          # Update from latest templates
warden ci update --dry-run  # Preview what would change
warden ci sync            # Re-sync LLM provider config only
```

---

## Exit Codes

Warden uses specific exit codes that your CI pipeline should handle:

| Code | Meaning | Recommended action |
|------|---------|-------------------|
| `0` | All checks passed | Proceed normally |
| `1` | Infrastructure error (Ollama down, model missing, etc.) | Warn but do not block merge |
| `2` | Policy violation detected | Block merge / fail the job |

The marketplace action maps exit code `2` to a job failure automatically.
For manual setups, implement the same logic:

```bash
set +e
warden scan . --ci --format sarif --output warden.sarif
EXIT_CODE=$?
set -e

if [ "${EXIT_CODE}" -eq 2 ]; then
  echo "Policy violations found. Review the SARIF report."
  exit 1
elif [ "${EXIT_CODE}" -ne 0 ]; then
  echo "WARNING: Warden infrastructure error (exit ${EXIT_CODE}). Scan skipped."
  # Do not fail the job for infrastructure issues
fi
```

---

## GitHub Actions

### Using the Marketplace Action (Simplest)

The official Warden GitHub Action handles installation, scanning, and SARIF upload
in a single step. Add it to any workflow:

```yaml
name: Warden Security Scan

on:
  pull_request:
    branches: [main]

jobs:
  warden:
    name: Security Scan
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write  # Required for SARIF upload

    steps:
      - uses: actions/checkout@v4

      - name: Run Warden Security Scan
        uses: warden-dev/warden-core@main
        with:
          scan-path: "."
          level: "standard"           # basic | standard | deep
          format: "sarif"
          output-file: "warden.sarif"
          upload-sarif: "true"        # Uploads to GitHub Security tab
```

**Available inputs:**

| Input | Default | Description |
|-------|---------|-------------|
| `scan-path` | `.` | Directory or file path to scan |
| `level` | `standard` | Analysis level: `basic`, `standard`, or `deep` |
| `format` | `sarif` | Output format: `sarif`, `json`, `text`, `markdown` |
| `output-file` | `warden.sarif` | Output file path |
| `quick-start` | `false` | LLM-free deterministic scan (no API keys needed) |
| `upload-sarif` | `true` | Upload SARIF to GitHub Security tab |
| `extra-args` | `` | Additional `warden scan` arguments |
| `python-version` | `3.11` | Python version for the action runner |

**Available outputs:**

| Output | Description |
|--------|-------------|
| `sarif-file` | Path to the generated SARIF file |
| `exit-code` | Scan exit code (see [Exit Codes](#exit-codes)) |

---

### Manual pip Install Workflow

When you need full control over the install process, or want to scan the repository
code itself rather than a published package:

```yaml
name: Warden Security Scan (Manual)

on:
  pull_request:
    branches: [main]

jobs:
  warden:
    name: Security Scan
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install Warden
        run: |
          pip install --upgrade pip
          pip install warden-core

      - name: Run Warden Scan
        env:
          WARDEN_LLM_PROVIDER: "anthropic"
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          mkdir -p .warden/reports
          warden scan . --ci --format sarif --output .warden/reports/warden.sarif

      - name: Upload SARIF to GitHub Security
        if: always()
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: .warden/reports/warden.sarif
          category: warden-security
        continue-on-error: true
```

---

### SARIF Upload to GitHub Security Tab

Warden produces industry-standard SARIF output that GitHub's code scanning feature
can ingest. Findings appear under **Security > Code scanning alerts** on the
repository page.

Requirements:
- The workflow job must have `security-events: write` permission.
- The SARIF file must exist before the upload step runs. Use `if: always()` to
  upload even when the scan exits with code 2.
- `continue-on-error: true` prevents a missing SARIF file from blocking the
  pipeline (e.g., when `--quick-start` produces no findings file).

```yaml
- name: Upload SARIF to GitHub Security
  if: always()
  uses: github/codeql-action/upload-sarif@v4
  with:
    sarif_file: warden.sarif
    category: warden-security
  continue-on-error: true
```

---

### PR Comment Integration

Post a Warden summary directly to the pull request as a comment so reviewers see
findings without leaving the PR view:

```yaml
name: Warden PR Review

on:
  pull_request:
    branches: [main]

jobs:
  warden:
    name: PR Security Review
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      security-events: write

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install Warden
        run: pip install warden-core

      - name: Run Warden Scan (Markdown output for PR comment)
        id: warden
        env:
          WARDEN_LLM_PROVIDER: ${{ vars.WARDEN_LLM_PROVIDER || 'ollama' }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          mkdir -p .warden/reports
          set +e
          warden scan . --ci --diff --format markdown --output .warden/reports/warden-pr.md
          echo "exit_code=$?" >> "$GITHUB_OUTPUT"
          set -e

          # Also generate SARIF for Security tab
          warden scan . --ci --diff --format sarif --output .warden/reports/warden.sarif || true

      - name: Post PR Comment
        if: always() && hashFiles('.warden/reports/warden-pr.md') != ''
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const report = fs.readFileSync('.warden/reports/warden-pr.md', 'utf8');
            const body = `## Warden Security Report\n\n${report}`;
            await github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
              body: body.slice(0, 65000),  // GitHub comment limit
            });

      - name: Upload SARIF
        if: always()
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: .warden/reports/warden.sarif
          category: warden-security
        continue-on-error: true

      - name: Fail on policy violations
        if: steps.warden.outputs.exit_code == '2'
        run: |
          echo "Warden found policy violations."
          exit 1
```

---

### Example: Basic Scan on Every PR

Lightweight, LLM-free scan that runs in under 60 seconds. Suitable as a required
status check on every pull request. Uses `--quick-start` so no API keys or Ollama
setup are needed.

```yaml
name: Warden Basic PR Check

on:
  pull_request:
    branches: [main, dev]

jobs:
  warden-basic:
    name: Warden Basic Check
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write

    steps:
      - uses: actions/checkout@v4

      - name: Warden Quick-Start Scan
        uses: warden-dev/warden-core@main
        with:
          scan-path: "."
          quick-start: "true"    # No LLM required — deterministic only
          format: "sarif"
          output-file: "warden.sarif"
          upload-sarif: "true"
```

---

### Example: Deep Scan on Main Only

Run a thorough AI-powered deep scan whenever code lands on the main branch.
This scan may take several minutes but provides maximum coverage.

```yaml
name: Warden Deep Scan (Main)

on:
  push:
    branches: [main]

jobs:
  warden-deep:
    name: Warden Deep Analysis
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install Warden
        run: pip install warden-core

      - name: Run Deep Scan
        env:
          WARDEN_LLM_PROVIDER: "anthropic"
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          mkdir -p .warden/reports
          warden scan src/ \
            --level deep \
            --ci \
            --format sarif \
            --output .warden/reports/warden.sarif

      - name: Upload SARIF
        if: always()
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: .warden/reports/warden.sarif
          category: warden-deep
        continue-on-error: true

      - name: Upload Artifacts
        if: always()
        uses: actions/upload-artifact@v6
        with:
          name: warden-deep-reports
          path: .warden/reports/
```

---

### Example: Incremental Scan with --diff

Scan only the files changed in the current PR relative to the base branch.
This significantly reduces scan time on large codebases by avoiding re-analysis
of unchanged files.

```yaml
name: Warden Incremental PR Scan

on:
  pull_request:
    branches: [main]

jobs:
  warden-incremental:
    name: Warden Incremental Scan
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write

    env:
      WARDEN_LLM_PROVIDER: "anthropic"
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history required for git diff

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install Warden
        run: pip install warden-core

      - name: Run Incremental Scan
        run: |
          mkdir -p .warden/reports

          # --diff detects changed files automatically against the base branch.
          # --base sets the comparison branch (default: main).
          # --ci enables read-only mode optimized for pipelines.
          warden scan \
            --diff \
            --base ${{ github.base_ref }} \
            --ci \
            --level standard \
            --format sarif \
            --output .warden/reports/warden.sarif

      - name: Upload SARIF
        if: always()
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: .warden/reports/warden.sarif
          category: warden-incremental
        continue-on-error: true
```

Alternatively, compute the changed file list manually and pass it as explicit
paths (this is how the official `warden-pr.yml` workflow works):

```yaml
      - name: Run Warden on Changed Files
        run: |
          mkdir -p .warden/reports
          CHANGED=$(git diff --name-only --diff-filter=d \
            "origin/${{ github.base_ref }}"...HEAD | grep "\.py$" || true)

          if [ -z "$CHANGED" ]; then
            echo "No Python files changed. Skipping scan."
            exit 0
          fi

          warden scan $CHANGED \
            --level standard \
            --ci \
            --format sarif \
            --output .warden/reports/warden.sarif
```

---

### Example: Nightly Full Scan with Baseline Update

Run a comprehensive scan on a schedule and commit the updated baseline back to the
repository. The baseline helps Warden track new findings vs. known issues over time.

```yaml
name: Warden Nightly Scan

on:
  schedule:
    - cron: "0 2 * * *"  # 02:00 UTC every night
  workflow_dispatch:

jobs:
  warden-nightly:
    name: Nightly Full Scan
    runs-on: ubuntu-latest
    permissions:
      contents: write  # Required to commit baseline updates
      security-events: write

    env:
      WARDEN_LLM_PROVIDER: "anthropic"
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install Warden
        run: pip install warden-core

      - name: Run Full Scan
        run: |
          mkdir -p .warden/reports
          warden scan src/ \
            --level standard \
            --format sarif \
            --output .warden/reports/warden-report.sarif

      - name: Check Technical Debt
        run: |
          echo "## Technical Debt Report" >> $GITHUB_STEP_SUMMARY
          warden baseline debt >> $GITHUB_STEP_SUMMARY 2>&1 || true

      - name: Commit Baseline Updates
        if: success()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .warden/baseline/ .warden/intelligence/ .warden/reports/
          git diff --cached --quiet || \
            git commit -m "chore(warden): update baseline and intelligence [skip ci]"
          git push

      - name: Upload SARIF
        if: always()
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: .warden/reports/warden-report.sarif
          category: warden-nightly
        continue-on-error: true
```

---

### Example: Release Security Audit

Block a release when security findings exist. Add this as a required workflow on
the release event:

```yaml
name: Warden Release Audit

on:
  release:
    types: [created]
  workflow_dispatch:

jobs:
  warden-release:
    name: Release Security Audit
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write

    env:
      WARDEN_LLM_PROVIDER: "anthropic"
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install Warden
        run: pip install warden-core

      - name: Run Release Audit
        run: |
          mkdir -p .warden/reports
          warden scan src/ \
            --level deep \
            --ci \
            --format sarif \
            --output .warden/reports/warden-release.sarif

      - name: Write Security Summary
        if: always()
        run: |
          echo "## Warden Security Summary" >> $GITHUB_STEP_SUMMARY
          if [ -f .warden/ai_status.md ]; then
            cat .warden/ai_status.md >> $GITHUB_STEP_SUMMARY
          fi

      - name: Upload SARIF
        if: always()
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: .warden/reports/warden-release.sarif
          category: warden-release
        continue-on-error: true
```

---

## GitLab CI

### Basic Template

Add this to your `.gitlab-ci.yml` to scan on every merge request and push to
protected branches:

```yaml
stages:
  - security

warden-scan:
  stage: security
  image: python:3.11-slim
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  variables:
    WARDEN_LLM_PROVIDER: "anthropic"
    # Store ANTHROPIC_API_KEY in GitLab CI/CD Settings > Variables (masked)
  before_script:
    - pip install --upgrade pip warden-core
  script:
    - mkdir -p .warden/reports
    - |
      set +e
      warden scan . \
        --ci \
        --format sarif \
        --output .warden/reports/warden.sarif
      EXIT_CODE=$?
      set -e

      if [ "${EXIT_CODE}" -eq 2 ]; then
        echo "Warden found policy violations."
        exit 1
      elif [ "${EXIT_CODE}" -ne 0 ]; then
        echo "WARNING: Warden infrastructure error (exit ${EXIT_CODE})."
      fi
  artifacts:
    when: always
    paths:
      - .warden/reports/
    expire_in: 30 days
  cache:
    key: warden-pip-${CI_COMMIT_REF_SLUG}
    paths:
      - .pip-cache/
  variables:
    PIP_CACHE_DIR: "$CI_PROJECT_DIR/.pip-cache"
```

### SAST Integration

GitLab's built-in SAST integration can import Warden's SARIF output. Configure
the `sast` stage to pick up the Warden report alongside other SAST tools:

```yaml
include:
  - template: Security/SAST.gitlab-ci.yml

stages:
  - test
  - security

warden-sast:
  stage: security
  image: python:3.11-slim
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  variables:
    WARDEN_LLM_PROVIDER: "anthropic"
  before_script:
    - pip install warden-core
  script:
    - mkdir -p gl-sast-reports
    - |
      warden scan . \
        --ci \
        --level standard \
        --format sarif \
        --output gl-sast-reports/warden.sarif || true
  artifacts:
    reports:
      sast: gl-sast-reports/warden.sarif
    paths:
      - gl-sast-reports/
    when: always
    expire_in: 7 days
```

### Merge Request Only Scan

Scan only changed files on merge requests using GitLab's built-in diff variables:

```yaml
warden-mr-scan:
  stage: security
  image: python:3.11-slim
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  variables:
    WARDEN_LLM_PROVIDER: "anthropic"
    GIT_DEPTH: 0  # Full clone for diff detection
  before_script:
    - pip install warden-core
    - git fetch origin $CI_MERGE_REQUEST_TARGET_BRANCH_NAME
  script:
    - mkdir -p .warden/reports
    - |
      CHANGED=$(git diff --name-only --diff-filter=d \
        "origin/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME}"...HEAD | grep "\.py$" || true)

      if [ -z "$CHANGED" ]; then
        echo "No Python files changed. Skipping scan."
        exit 0
      fi

      warden scan $CHANGED \
        --ci \
        --level standard \
        --format sarif \
        --output .warden/reports/warden.sarif
  artifacts:
    when: always
    paths:
      - .warden/reports/
    expire_in: 7 days
```

---

## General CI

### Environment Variables Reference

Warden's behavior is controlled through environment variables. Set these as CI
secrets or pipeline variables as appropriate.

**LLM provider selection:**

| Variable | Description | Example |
|----------|-------------|---------|
| `WARDEN_LLM_PROVIDER` | Primary LLM provider | `anthropic`, `openai`, `groq`, `gemini`, `deepseek`, `ollama` |
| `WARDEN_BLOCKED_PROVIDERS` | Comma-separated list of providers to block | `claude_code,codex` |
| `WARDEN_FAST_TIER_PRIORITY` | Override the fast-tier provider | `groq` |
| `WARDEN_SMART_TIER_PROVIDER` | Smart-tier provider for deep analysis | `groq` |
| `WARDEN_SMART_TIER_MODEL` | Model name for smart-tier | `qwen-qwq-32b` |

**API keys (store as CI secrets, never in code):**

| Variable | Provider |
|----------|---------|
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `OPENAI_API_KEY` | OpenAI |
| `GROQ_API_KEY` | Groq |
| `GEMINI_API_KEY` | Google Gemini |
| `DEEPSEEK_API_KEY` | DeepSeek |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI |

**Ollama (self-hosted):**

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `WARDEN_OLLAMA_CONCURRENCY` | `3` | Max parallel Ollama requests |

**Performance tuning:**

| Variable | Default | Description |
|----------|---------|-------------|
| `WARDEN_FILE_CONCURRENCY` | auto | Max files analyzed in parallel |
| `WARDEN_AST_WORKERS` | auto | AST parsing worker count |
| `WARDEN_FILE_TIMEOUT_MIN` | auto | Minimum per-file timeout (seconds) |
| `WARDEN_LIMIT_TPM` | `5000` | Token-per-minute rate limit |
| `WARDEN_LIMIT_RPM` | `10` | Requests-per-minute rate limit |
| `WARDEN_LIMIT_BURST` | `1` | Burst allowance for rate limiter |

**CI automation:**

| Variable | Description |
|----------|-------------|
| `WARDEN_NON_INTERACTIVE` | Set to `true` to suppress all interactive prompts |
| `WARDEN_INIT_PROVIDER` | Pre-select LLM provider for `warden init` |

---

### Caching .warden/ for Faster Runs

Warden stores its scan cache, baseline fingerprints, and intelligence graph under
`.warden/`. Caching this directory between runs avoids re-analyzing unchanged files.

**GitHub Actions:**

```yaml
- name: Cache Warden state
  uses: actions/cache@v5
  with:
    path: .warden/
    key: warden-state-${{ runner.os }}-${{ github.ref_name }}-${{ github.sha }}
    restore-keys: |
      warden-state-${{ runner.os }}-${{ github.ref_name }}-
      warden-state-${{ runner.os }}-
```

**GitLab CI:**

```yaml
cache:
  key: warden-state-${CI_COMMIT_REF_SLUG}
  paths:
    - .warden/cache/
    - .warden/baseline/
    - .warden/intelligence/
```

> Note: Do not cache `.warden/reports/` — report files should always be regenerated
> fresh on each run.

**Ollama model caching (GitHub Actions):**

Self-hosted Ollama models are large (~2 GB). Cache the binary and the model weights
separately so each is only downloaded once per runner OS:

```yaml
- name: Cache Ollama binary
  id: ollama-cache
  uses: actions/cache@v5
  with:
    path: /usr/local/bin/ollama
    key: ollama-binary-${{ runner.os }}-0.17.4

- name: Cache Ollama models
  uses: actions/cache@v5
  with:
    path: ~/.ollama
    key: ollama-models-${{ runner.os }}-qwen2.5-coder-3b
    restore-keys: |
      ollama-models-${{ runner.os }}-

- name: Install Ollama binary
  if: steps.ollama-cache.outputs.cache-hit != 'true'
  run: |
    curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=0.17.4 sh
    sudo systemctl stop ollama
    sudo systemctl disable ollama

- name: Start Ollama and warm up
  env:
    OLLAMA_MAX_LOADED_MODELS: "1"
    OLLAMA_FLASH_ATTENTION: "1"
    OLLAMA_CONTEXT_LENGTH: "4096"
  run: |
    lsof -ti :11434 | xargs --no-run-if-empty sudo kill -9 || true
    ollama serve &
    for i in {1..30}; do
      curl -s http://localhost:11434/api/tags > /dev/null && break || sleep 1
    done
    ollama list | grep -q "qwen2.5-coder:3b" || ollama pull qwen2.5-coder:3b
    # Warm up: pre-initialize KV cache to avoid cold-start on first analysis
    curl -s http://localhost:11434/api/generate \
      -d '{"model":"qwen2.5-coder:3b","prompt":"hi","options":{"num_predict":1},"keep_alive":-1}' \
      -o /dev/null
```

---

### CI Mode Behavior (--ci)

The `--ci` flag optimizes Warden for pipeline execution:

- **Read-only**: Warden does not modify any project files or configuration.
- **Auto-save JSON report**: A machine-readable report is written to
  `.warden/reports/warden-report.json` automatically, regardless of the `--format`
  flag. This allows downstream steps to parse results programmatically.
- **Non-interactive**: All prompts are suppressed. Combined with
  `WARDEN_NON_INTERACTIVE=true`, this ensures the scan never blocks waiting for
  user input.

```bash
warden scan src/ --ci --format sarif --output warden.sarif
```

---

### LLM-Free Scanning (--quick-start)

`--quick-start` runs deterministic-only analysis (regex, AST, taint tracking) with
no LLM backend required. This is ideal for:

- PR checks where sub-60-second feedback is important
- Repositories without access to an LLM API
- Catching obvious issues cheaply before a deeper nightly scan

```bash
warden scan . --quick-start --format sarif --output warden.sarif
```

When `--quick-start` is set, `--level` is ignored and the scan runs at `basic`
depth. You cannot combine `--quick-start` with `--level deep`.

---

### Incremental Scanning (--diff)

`--diff` restricts the scan to files changed relative to a base branch. Warden
uses `git diff` internally to compute the changed file list.

```bash
# Compare against main (default)
warden scan --diff --ci

# Compare against a specific base branch
warden scan --diff --base develop --ci

# Force a full scan even when --diff is set (for debugging)
warden scan --diff --force --ci
```

`--diff` requires a full git history clone. In GitHub Actions, add
`fetch-depth: 0` to your checkout step.

---

### Output Formats

| Format | Flag | Use case |
|--------|------|----------|
| SARIF | `--format sarif` | GitHub/GitLab Security tab, code scanning integration |
| JSON | `--format json` | Downstream parsing, custom dashboards |
| JUnit XML | `--format junit` | Test result integration (Jenkins, GitLab test reports) |
| Markdown | `--format markdown` | PR comments, GitHub step summaries |
| HTML | `--format html` | Human-readable reports saved as artifacts |
| Text | `--format text` | Terminal output, log files |
| Badge/Shield | `--format badge` | README shields |

Combine multiple outputs in a single scan using separate invocations with the
`--no-update-baseline` flag on subsequent runs to avoid double-updating state:

```bash
warden scan src/ --format sarif --output warden.sarif
warden scan src/ --format json  --output warden.json  --no-update-baseline
```

---

## Best Practices

### Use the Right Scan Level for Each Context

| Context | Recommended level | Rationale |
|---------|------------------|-----------|
| Every PR | `basic` / `--quick-start` | Fast feedback, catches obvious issues |
| Main branch push | `standard` | Good coverage without long waits |
| Nightly schedule | `standard` or `deep` | Thorough analysis with no time pressure |
| Pre-release audit | `deep` | Maximum coverage before shipping |

### Protect the Main Branch with Required Checks

Set the quick-start PR check as a required status check so it blocks merges when
policy violations are found. Keep the nightly deep scan as informational only —
failures there update the baseline rather than blocking development.

### Handle Exit Codes Correctly

Infrastructure errors (exit code `1`) should warn but not block merges. Only exit
code `2` (policy violation) should fail the job. Wrapping the scan command with
`set +e` / `set -e` and inspecting `$?` gives you full control:

```bash
set +e
warden scan . --ci --format sarif --output warden.sarif
EXIT_CODE=$?
set -e

case $EXIT_CODE in
  0) echo "Clean scan." ;;
  1) echo "WARNING: Infrastructure issue. Skipping gate." ;;
  2) echo "Policy violations found."; exit 1 ;;
  *) echo "Unknown exit code: $EXIT_CODE"; exit 1 ;;
esac
```

### Cache Warden Init Results

`warden init` writes configuration and baseline data to `.warden/`. Cache this
directory in CI so repeated runs skip the initialization overhead:

```yaml
- name: Cache Warden state
  uses: actions/cache@v5
  with:
    path: .warden/
    key: warden-${{ runner.os }}-${{ hashFiles('pyproject.toml', 'setup.py', 'requirements*.txt') }}
    restore-keys: warden-${{ runner.os }}-
```

### Store API Keys as Secrets

Never put API keys in workflow YAML files. Use your CI platform's secret store:

- **GitHub Actions**: Settings > Secrets and variables > Actions
- **GitLab CI**: Settings > CI/CD > Variables (mark as Masked)

Reference them via `${{ secrets.ANTHROPIC_API_KEY }}` (GitHub) or
`$ANTHROPIC_API_KEY` (GitLab).

### Use warden ci init for First-Time Setup

The `warden ci init` command generates provider-appropriate workflow files,
pre-configured with the correct LLM provider secrets hints, caching strategy,
and scan levels. Run it once locally and commit the generated files:

```bash
warden ci init --provider github
git add .github/workflows/warden-*.yml
git commit -m "ci: add Warden security scanning workflows"
```

Keep workflows up to date as Warden releases new template versions:

```bash
warden ci update --dry-run  # Preview changes
warden ci update            # Apply updates
```
