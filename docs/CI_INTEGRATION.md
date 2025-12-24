# Warden CI/CD Integration Guide

> **Complete guide for integrating Warden into your CI/CD pipelines**
>
> **Version:** 1.0.0
> **Last Updated:** 2025-12-24

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Platform-Specific Guides](#platform-specific-guides)
   - [GitHub Actions](#github-actions)
   - [GitLab CI](#gitlab-ci)
   - [Azure Pipelines](#azure-pipelines)
4. [Configuration Options](#configuration-options)
5. [Validation Frames](#validation-frames)
6. [Advanced Features](#advanced-features)
7. [Troubleshooting](#troubleshooting)
8. [Best Practices](#best-practices)

---

## Overview

### What is Warden CI/CD Integration?

Warden integrates into your CI/CD pipeline to automatically validate code quality, security, and resilience **before** it reaches production. Think of it as an automated security guard for your codebase.

### Benefits

- ✅ **Catch issues early** - Find security vulnerabilities and edge cases in PR reviews
- ✅ **Block bad code** - Prevent critical issues from reaching main/prod branches
- ✅ **Fast feedback** - Incremental analysis focuses on changed files only
- ✅ **Multi-platform** - Works with GitHub Actions, GitLab CI, Azure Pipelines
- ✅ **Inline annotations** - See issues directly in your code review UI

### How It Works

```
Developer → Push Code → CI Pipeline → Warden Analysis → Pass/Fail → Merge/Block
                            ↓
                    4 Validation Frames:
                    - Security (Blocker)
                    - Chaos Engineering
                    - Fuzz Testing
                    - Property Testing
```

---

## Quick Start

### Prerequisites

- Git repository
- Python 3.9+ installed in CI environment
- CI/CD platform (GitHub Actions, GitLab CI, or Azure Pipelines)

### 5-Minute Setup (GitHub Actions)

1. **Copy workflow file to your repository:**

```bash
mkdir -p .github/workflows
cp .github/workflows/warden.yml .github/workflows/
```

2. **Commit and push:**

```bash
git add .github/workflows/warden.yml
git commit -m "feat: Add Warden CI/CD analysis"
git push
```

3. **Create a PR and watch Warden analyze!**

That's it! Warden will now automatically run on every pull request.

---

## Platform-Specific Guides

### GitHub Actions

#### Basic Setup

**File:** `.github/workflows/warden.yml`

```yaml
name: Warden Analysis

on:
  pull_request:
    branches: [main, dev]
  push:
    branches: [main, dev]

jobs:
  warden:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install Warden
        run: pip install -e ".[dev]"

      - name: Run Warden Analysis
        run: |
          warden scan . \
            --frame security \
            --frame chaos \
            --frame fuzz \
            --frame property \
            --ci \
            --output warden-report.json

      - name: Upload Report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: warden-report
          path: warden-report.json
```

#### Advanced Setup with Annotations

See `.github/workflows/warden.yml` in this repository for the full example with:
- GitHub Security tab integration (SARIF)
- Inline code annotations
- PR comments
- Blocker issue detection
- Caching for faster runs

#### Permissions

Add to your workflow file:

```yaml
permissions:
  contents: read
  pull-requests: write
  security-events: write
  issues: write
```

---

### GitLab CI

#### Basic Setup

**File:** `.gitlab-ci.yml`

```yaml
variables:
  PYTHON_VERSION: "3.11"

stages:
  - analyze

warden:analysis:
  image: python:${PYTHON_VERSION}
  stage: analyze
  script:
    - pip install -e ".[dev]"
    - warden scan . \
        --frame security \
        --frame chaos \
        --frame fuzz \
        --frame property \
        --ci \
        --output warden-report.json

  artifacts:
    when: always
    paths:
      - warden-report.json
    expire_in: 30 days

  only:
    - merge_requests
    - main
    - dev
```

#### Advanced Setup with Code Quality Reports

See `.gitlab-ci.yml` in this repository for:
- GitLab Code Quality integration
- JUnit test reports
- Multi-stage pipeline (setup → analyze → report)
- Cache configuration
- Scheduled full scans

---

### Azure Pipelines

#### Basic Setup

**File:** `azure-pipelines.yml`

```yaml
trigger:
  branches:
    include:
      - main
      - dev

pool:
  vmImage: 'ubuntu-latest'

steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.11'

  - script: |
      pip install -e ".[dev]"
    displayName: 'Install Warden'

  - script: |
      warden scan . \
        --frame security \
        --frame chaos \
        --frame fuzz \
        --frame property \
        --ci \
        --output $(Build.ArtifactStagingDirectory)/warden-report.json
    displayName: 'Run Warden Analysis'

  - task: PublishBuildArtifacts@1
    condition: always()
    inputs:
      pathToPublish: '$(Build.ArtifactStagingDirectory)'
      artifactName: 'warden-analysis'
```

#### Advanced Setup

See `azure-pipelines.yml` in this repository for:
- Multi-stage pipeline
- ##vso[] logging commands
- Build tags for issue severity
- Test result publishing

---

## Configuration Options

### CLI Flags

| Flag | Description | Default |
|------|-------------|---------|
| `--frame <name>` | Enable validation frame (can be repeated) | All frames |
| `--ci` | Enable CI mode (platform detection, annotations) | False |
| `--output <path>` | Output report path | `warden-report.json` |
| `--format <type>` | Output format (json, sarif, junit) | json |
| `--fail-on-critical` | Exit with code 1 if critical issues found | True |
| `--fail-on-high` | Exit with code 1 if high severity issues found | False |
| `--incremental` | Analyze only changed files (git diff) | False |
| `--verbose` | Enable verbose logging | False |

### Example Configurations

**Strict Security (Block on ANY issues):**
```bash
warden scan . \
  --frame security \
  --fail-on-critical \
  --fail-on-high \
  --ci
```

**Fast PR Checks (Changed files only):**
```bash
warden scan . \
  --frame security \
  --frame fuzz \
  --incremental \
  --ci
```

**Full Weekly Scan (All frames):**
```bash
warden scan . \
  --frame security \
  --frame chaos \
  --frame fuzz \
  --frame property \
  --frame stress \
  --frame architectural \
  --ci \
  --output warden-full-report.json
```

---

## Validation Frames

### Available Frames

| Frame | Priority | Description | Blocker? |
|-------|----------|-------------|----------|
| **security** | Critical | SQL injection, XSS, secrets detection | ✅ Yes |
| **chaos** | High | Network failures, timeout handling | ❌ No |
| **fuzz** | High | Edge cases, null/empty/unicode inputs | ❌ No |
| **property** | Medium | Idempotency, invariant checks | ❌ No |
| **stress** | Low | Memory leaks, performance under load | ❌ No |
| **architectural** | Medium | File organization, naming consistency | ❌ No |

### Frame Selection Strategy

**For Pull Requests (Fast Feedback):**
```bash
--frame security --frame fuzz --frame property
```
Time: ~30 seconds for small PRs

**For Main Branch (Comprehensive):**
```bash
--frame security --frame chaos --frame fuzz --frame property
```
Time: ~2-3 minutes

**For Scheduled Scans (Full Coverage):**
```bash
# All 6 frames
--frame security --frame chaos --frame fuzz --frame property --frame stress --frame architectural
```
Time: ~10-15 minutes

---

## Advanced Features

### 1. Incremental Analysis

**Analyze only changed files** for faster CI runs.

```yaml
- name: Run Incremental Analysis
  run: |
    warden scan . \
      --frame security \
      --frame fuzz \
      --incremental \
      --ci
```

**How it works:**
- Detects git diff automatically (PR: base branch, Push: previous commit)
- Filters files to analyze
- Reduces analysis time by 70-90% for small PRs

**Environment variables detected:**
- GitHub: `GITHUB_BASE_REF`, `GITHUB_HEAD_REF`
- GitLab: `CI_MERGE_REQUEST_TARGET_BRANCH_NAME`
- Azure: `SYSTEM_PULLREQUEST_TARGETBRANCH`

### 2. SARIF Export (GitHub Security Tab)

**Enable security findings in GitHub Security tab:**

```yaml
- name: Generate SARIF Report
  run: |
    warden scan . --frame security --format sarif --output warden.sarif

- name: Upload to GitHub Security
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: warden.sarif
```

**Benefits:**
- Security findings in dedicated Security tab
- Integration with GitHub Advanced Security
- Historical security trend tracking

### 3. Matrix Builds

**Test across multiple Python versions and OS:**

See `.github/workflows/warden-full.yml` for complete example.

```yaml
strategy:
  matrix:
    os: [ubuntu-latest, macos-latest, windows-latest]
    python-version: ['3.9', '3.10', '3.11', '3.12']
```

**Use cases:**
- Weekly comprehensive scans
- Pre-release validation
- Cross-platform compatibility testing

### 4. Custom Rules

**Add project-specific validation rules:**

```yaml
# .warden/rules/custom-security.yml
rules:
  - id: no-hardcoded-urls
    name: No Hardcoded URLs
    severity: high
    pattern: 'https?://[a-zA-Z0-9.-]+'
    message: "Hardcoded URLs found. Use configuration."
```

**Enable in CI:**
```bash
warden scan . --frame security --custom-rules .warden/rules/
```

### 5. Caching

**Speed up CI runs with dependency caching:**

**GitHub Actions:**
```yaml
- uses: actions/cache@v4
  with:
    path: |
      ~/.cache/pip
      ~/.warden/cache
    key: ${{ runner.os }}-warden-${{ hashFiles('**/pyproject.toml') }}
```

**GitLab CI:**
```yaml
cache:
  key: "${CI_COMMIT_REF_SLUG}"
  paths:
    - .cache/pip
    - .cache/warden
```

**Azure Pipelines:**
```yaml
- task: Cache@2
  inputs:
    key: 'python | "$(Agent.OS)" | **/requirements*.txt'
    path: $(Pipeline.Workspace)/.cache/pip
```

### 6. Repository-Level Frame Caching

**Optimize pipeline execution with intelligent frame caching:**

Warden automatically caches repository-level validation frames (frames that analyze the entire codebase rather than individual files). This optimization prevents redundant execution when running multiple pipelines or re-analyzing the same codebase.

**How it works:**

- **Repository-level frames** (e.g., `SecurityFrame`, `ChaosEngineeringFrame`) analyze the entire codebase
- Results are cached in-memory using frame name as the key
- Subsequent pipeline executions reuse cached results (⚡ instant execution)
- File-level frames are always executed (no caching for file-specific analysis)

**Benefits:**

- ⚡ Near-instant execution for repository-level frames on subsequent runs
- 💾 Reduced LLM API calls and resource consumption
- 🚀 Faster CI/CD pipeline completion times

**Example:**

```python
# First pipeline execution
SecurityFrame: 45s (LLM analysis)
ChaosEngineeringFrame: 30s (LLM analysis)

# Second pipeline execution (same code)
SecurityFrame: 0.0s (cached ⚡)
ChaosEngineeringFrame: 0.0s (cached ⚡)
```

**Cache invalidation:**

- Cache is cleared when code changes are detected
- Cache is scoped per orchestrator instance (process lifetime)
- No persistent cache across CI runs (by design, for freshness)

**Configuration:**

No configuration needed - automatic optimization! The caching is transparent and happens automatically based on frame scope.

### 7. Context-Aware Validation

**NEW:** Warden validation frames now support enhanced context for smarter, more accurate validation.

#### Code Characteristics

Warden automatically detects code characteristics to optimize validation:

```python
from warden.validation.domain import CodeCharacteristics

characteristics = CodeCharacteristics(
    has_async_operations=True,          # Async/await patterns detected
    has_database_operations=True,       # SQL/ORM usage found
    has_user_input=True,                # User input acceptance
    has_authentication_logic=True,      # Auth patterns detected
    has_cryptographic_operations=False,
    complexity_score=7,                 # 1-10 scale
)
```

**Validation frames use characteristics to:**

- Skip irrelevant checks (e.g., no DB checks if no DB operations)
- Prioritize high-risk patterns (auth + user input = security focus)
- Adjust validation depth based on complexity score

#### Memory Context

**Future enhancement** - Validation frames will receive memory context from previous validations:

```python
from warden.validation.domain import ValidationMemoryContext, ProjectContext

context = ValidationMemoryContext(
    project_context=ProjectContext(
        name="PaymentAPI",
        domain="fintech",
        compliance_requirements=["PCI-DSS"],
        frameworks=["fastapi", "sqlalchemy"]
    ),
    learned_patterns=[
        "This project often has SQL injection issues in payment code",
        "API endpoints frequently lack rate limiting"
    ],
    relevant_memories=[...],  # Similar issues from past runs
)
```

**Benefits:**

- 🧠 Smarter validation based on project history
- 🎯 Targeted checks for known problem areas
- 📈 Continuous improvement over time

**Current Status:**

- ✅ Infrastructure implemented (models, interfaces)
- ⏳ Classifier integration (in progress)
- ⏳ Memory system integration (planned)

**Using in custom frames:**

```python
from warden.validation.domain import ValidationFrame, FrameResult

class MyCustomFrame(ValidationFrame):
    async def execute(
        self,
        code_file,
        characteristics=None,      # Optional: Code patterns
        memory_context=None,        # Optional: Historical context
    ) -> FrameResult:
        # Use characteristics to optimize
        if characteristics and not characteristics.has_database_operations:
            # Skip DB validation if no DB code detected
            return FrameResult(status="passed", ...)

        # Use memory context for smarter validation
        if memory_context and memory_context.is_available:
            # Check learned patterns
            for pattern in memory_context.learned_patterns:
                # Apply project-specific validation
                pass

        # Standard validation logic
        ...
```

---

## Troubleshooting

### Issue: Warden analysis failing on every PR

**Symptom:** All PRs fail with critical issues

**Solution 1:** Check if issues are valid
```bash
# Run locally
warden scan . --frame security --verbose
```

**Solution 2:** Adjust failure thresholds
```yaml
# Don't fail on high severity (only critical)
warden scan . --fail-on-critical --no-fail-on-high
```

### Issue: CI runs too slow

**Solutions:**

1. **Use incremental analysis:**
```bash
warden scan . --incremental
```

2. **Reduce frames for PRs:**
```bash
# Only security + fuzz for PRs
warden scan . --frame security --frame fuzz
```

3. **Enable caching** (see [Caching](#5-caching))

### Issue: GitHub annotations not showing

**Checklist:**
- ✅ Workflow has `pull-requests: write` permission
- ✅ Using `--ci` flag in warden scan command
- ✅ `GITHUB_ACTIONS=true` environment variable set (automatic)

**Debug:**
```yaml
- name: Debug CI Detection
  run: |
    python -c "
    from warden.pipeline.application.ci_orchestrator import CIPipelineOrchestrator
    orch = CIPipelineOrchestrator()
    print(orch.get_platform_info())
    "
```

### Issue: SARIF upload failing

**Common causes:**

1. **Missing permission:**
```yaml
permissions:
  security-events: write  # Required!
```

2. **Invalid SARIF format:**
```bash
# Validate SARIF file
cat warden.sarif | jq .
```

3. **File too large:**
```
SARIF files must be < 10MB
```

**Solution:** Filter to security frame only
```bash
warden scan . --frame security --format sarif
```

### Issue: Git diff not detected (incremental mode)

**Symptoms:** Incremental mode analyzes all files

**Debug:**
```bash
git fetch origin main
git diff --numstat origin/main HEAD
```

**Solutions:**

1. **Ensure full git history:**
```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0  # Full history
```

2. **Specify base branch explicitly:**
```bash
warden scan . --incremental --base-branch main
```

---

## Best Practices

### 1. Pipeline Design

**Recommended Structure:**

```
Pull Requests:
├── Fast validation (security + fuzz) → 30 sec
├── Inline annotations for developers
└── Block merge if critical issues

Main Branch Push:
├── Comprehensive validation (4 frames) → 2 min
├── SARIF upload to Security tab
└── Notify team if issues found

Weekly Schedule:
├── Full scan (all 6 frames) → 15 min
├── Matrix builds (multiple Python versions)
└── Detailed report generation
```

### 2. Failure Thresholds

**Recommended settings:**

| Branch | Fail on Critical | Fail on High | Fail on Medium |
|--------|------------------|--------------|----------------|
| PR → main | ✅ Yes | ✅ Yes | ❌ No |
| PR → dev | ✅ Yes | ❌ No | ❌ No |
| main push | ✅ Yes | ✅ Yes | ❌ No |
| Scheduled | ❌ No | ❌ No | ❌ No |

**Why?**
- **PRs to main:** Strictest (production quality)
- **PRs to dev:** Moderate (allow iteration)
- **Scheduled:** Informational (don't fail, just report)

### 3. Performance Optimization

**Tips for faster CI:**

1. **Use incremental analysis** for PRs (`--incremental`)
2. **Cache dependencies** (pip, warden cache)
3. **Parallel frame execution** (automatic in Warden)
4. **Reduce frames for PRs** (security + fuzz minimum)
5. **Full scans only on schedule** (weekly)

### 4. Security First

**Always-on frames:**

```bash
# NEVER skip security frame
warden scan . --frame security --fail-on-critical
```

**Critical issues = blockers:**
```yaml
# Exit code 1 if critical issues
--fail-on-critical
```

**SARIF export for visibility:**
```yaml
# Upload to GitHub Security tab
--format sarif
```

### 5. Developer Experience

**Make feedback visible:**

```yaml
# GitHub: Inline annotations
- uses: actions/github-script@v7  # PR comments

# GitLab: Code Quality reports
reports:
  codequality: code-quality-report.json

# Azure: ##vso[] annotations
--ci flag enables platform-specific output
```

**Provide actionable messages:**
```
❌ BLOCKER: 3 critical security issues found!
   → SQL injection in user_service.py:42
   → Fix: Use parameterized queries
```

---

## Example Configurations

### Minimal (Security Only)

```yaml
# .github/workflows/warden-minimal.yml
name: Security Check
on: [pull_request]
jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -e ".[dev]"
      - run: warden scan . --frame security --ci --fail-on-critical
```

### Balanced (Recommended)

```yaml
# .github/workflows/warden-balanced.yml
name: Warden Analysis
on:
  pull_request:
    branches: [main, dev]
  push:
    branches: [main]

jobs:
  warden:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - run: pip install -e ".[dev]"

      - name: Run Warden (Incremental)
        if: github.event_name == 'pull_request'
        run: |
          warden scan . \
            --frame security \
            --frame fuzz \
            --incremental \
            --ci

      - name: Run Warden (Full)
        if: github.event_name == 'push'
        run: |
          warden scan . \
            --frame security \
            --frame chaos \
            --frame fuzz \
            --frame property \
            --ci

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: warden-report
          path: warden-report.json
```

### Complete (Production)

See `.github/workflows/warden.yml` in this repository for:
- Multi-trigger (PR, push, schedule, manual)
- SARIF export
- PR comments
- GitHub annotations
- Artifact retention
- Blocker detection

---

## Next Steps

1. **Choose your platform** (GitHub Actions, GitLab CI, Azure Pipelines)
2. **Copy example configuration** from this repo
3. **Customize validation frames** for your needs
4. **Test on a PR** and adjust thresholds
5. **Enable scheduled full scans** (weekly recommended)

---

## Support

- **Documentation:** [/docs](../docs/)
- **Examples:** [/examples/ci](../examples/ci/)
- **Issues:** [GitHub Issues](https://github.com/ibrahimcaglar/warden-core/issues)

---

**Last Updated:** 2025-12-24
**Warden Version:** 1.0.0
