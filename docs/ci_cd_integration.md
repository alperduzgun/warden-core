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

### Standard Workflow (Push & PR)
This is the default recommended configuration. It scans on every push to main branches and every Pull Request.

```yaml
name: Warden Security Scan

on:
  push:
    branches: [ "main", "develop" ]
  pull_request:
    branches: [ "main", "develop" ]

jobs:
  security-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install Warden
        run: pip install warden-core

      - name: Run Scan
        run: warden scan . --format sarif --output warden-report.sarif
      
      # Upload results to GitHub Security Tab
      - name: Upload SARIF
        uses: github/codeql-action/upload-sarif@v2
        if: always()
        with:
          sarif_file: warden-report.sarif
```

### Advanced Trigger Examples

#### 1. Scan Only on Pull Requests (No Push)
Useful to save CI minutes if you trust that main is protected.

```yaml
on:
  pull_request:
    branches: [ "main" ]
```

#### 2. Scheduled Nightly Scans
Useful for checking new vulnerabilities in dependencies even if code hasn't changed.

```yaml
on:
  schedule:
    - cron: '0 0 * * *' # Every night at midnight
```

#### 3. Ignore Documentation Changes
Don't trigger scan if only markdown files are changed.

```yaml
on:
  push:
    paths-ignore:
      - '**.md'
      - 'docs/**'
```

## 📊 Reporting Formats

Warden supports multiple report formats for different CI systems:

| Format | CLI Flag | Best For |
|--------|----------|----------|
| **SARIF** | `--format sarif` | GitHub Security, Azure DevOps, GitLab |
| **JUnit** | `--format junit` | Jenkins, CircleCI, Bamboo (Fail/Pass tracking) |
| **JSON** | `--format json` | Custom parsing & scripts |
| **HTML** | `--format html` | Human-readable artifacts |

### Azure DevOps Example (JUnit)
```bash
warden scan . --format junit --output test-results.xml
```

### GitLab CI Example (SARIF)
```yaml
warden-scan:
  script:
    - warden scan . --format sarif --output warden.sarif
  artifacts:
    reports:
      sast: warden.sarif
```
