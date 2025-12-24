# Warden CI/CD Examples

This directory contains example CI/CD configurations for different scenarios and platforms.

## Directory Structure

```
examples/ci/
├── github-actions/       # GitHub Actions workflows
├── gitlab-ci/           # GitLab CI pipelines
├── azure-pipelines/     # Azure Pipelines configs
└── custom-rules/        # Example custom validation rules
```

## Quick Start Examples

### Minimal Security Check (30 seconds)
For projects that need fast PR validation with minimal overhead.

**Use case:** Small teams, fast iteration, basic security

**Platform:** GitHub Actions → `github-actions/minimal.yml`

### Balanced Analysis (2-3 minutes)
Recommended for most projects. Good balance between speed and coverage.

**Use case:** Medium teams, production code, comprehensive validation

**Platforms:**
- GitHub Actions → `github-actions/balanced.yml`
- GitLab CI → `gitlab-ci/balanced.yml`
- Azure Pipelines → `azure-pipelines/balanced.yml`

### Full Matrix Build (15-30 minutes)
Complete validation across multiple Python versions and platforms.

**Use case:** Open source projects, pre-release validation, weekly comprehensive scans

**Platform:** GitHub Actions → `github-actions/matrix.yml`

### Enterprise Setup (Complete)
Production-grade setup with all features enabled.

**Use case:** Enterprise projects, compliance requirements, full observability

**Platforms:**
- GitHub Actions → `github-actions/enterprise.yml`
- GitLab CI → `gitlab-ci/enterprise.yml`
- Azure Pipelines → `azure-pipelines/enterprise.yml`

## Usage

1. **Choose your scenario** based on project needs
2. **Copy example file** to your repository
3. **Customize** validation frames and thresholds
4. **Test** on a PR
5. **Iterate** based on feedback

## Custom Rules

See `custom-rules/` directory for examples of project-specific validation rules.

## Support

Refer to the main [CI Integration Guide](../../docs/CI_INTEGRATION.md) for detailed documentation.
