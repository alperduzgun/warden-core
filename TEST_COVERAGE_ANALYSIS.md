# Warden-Core Test Coverage Analysis

**Date:** 2026-02-16
**Scope:** Full structural and qualitative analysis of test coverage across all modules

---

## Executive Summary

Warden-core has **278 source files** across 20 modules, with **~126 test files** containing approximately **504 test functions**. The overall structural test coverage is **~16.5%** by file count, with significant gaps in critical, user-facing modules. Seven modules (44 source files) have **zero test coverage**, and several high-complexity modules have less than 15% file-level coverage.

Coverage measurement (`pytest-cov`) is not currently in the project dependencies. Adding it is recommended as a first step.

---

## Module-by-Module Coverage Summary

| Module | Source Files | Test Files | Tests | File Coverage | Priority |
|--------|:-----------:|:----------:|:-----:|:------------:|:--------:|
| **cli** | 18 | 0 | 0 | 0% | CRITICAL |
| **config** | 8 | 0 | 0 | 0% | CRITICAL |
| **reports** | 3 | 0 | 0 | 0% | HIGH |
| **secrets** | 8 | 0 | 0 | 0% | HIGH |
| **classification** | 3 | 0 | 0 | 0% | HIGH |
| **memory** | 2 | 0 | 0 | 0% | HIGH |
| **issues** | 2 | 0 | 0 | 0% | MEDIUM |
| **grpc** | 22 | 1 | 13 | 4.5% | CRITICAL |
| **fortification** | 12 | 1 | 16 | 8.3% | HIGH |
| **shared** | 31 | 3 | 12 | 9.7% | CRITICAL |
| **analysis** | 37 | 4 | 46 | 10.8% | HIGH |
| **mcp** | 36 | 4 | 13 | 11.1% | HIGH |
| **cleaning** | 15 | 2 | 23 | 13.3% | HIGH |
| **semantic_search** | 7 | 1 | 13 | 14.3% | MEDIUM |
| **lsp** | 5 | 1 | 11 | 20.0% | MEDIUM |
| **ast** | 8 | 2 | 32 | 25.0% | LOW |
| **pipeline** | 30 | 10 | 117 | 33.3% | LOW |
| **llm** | 22 | 8 | 62 | 36.4% | LOW |
| **rules** | 6 | 6 | 65 | 100% | -- |
| **suppression** | 3 | 3 | 81 | 100% | -- |

---

## Priority 1: Completely Untested Modules (0% Coverage)

### 1. CLI Module (18 files, 0 tests)

The entire CLI layer has no unit tests. This is the primary user-facing surface of the application.

**Key untested files:**
- `src/warden/cli/commands/scan.py` -- The core scanning command; includes LLM-powered failure summary generation, result rendering, and exit code logic
- `src/warden/cli/commands/init.py` / `init_helpers.py` -- Project initialization wizard; generates config files
- `src/warden/cli/commands/install.py` -- Git hook installation
- `src/warden/cli/commands/doctor.py` -- Environment diagnostics
- `src/warden/cli/commands/ci.py` -- CI/CD mode execution
- `src/warden/cli/commands/baseline.py` -- Baseline management
- `src/warden/cli/commands/config.py` -- Configuration management
- `src/warden/cli/commands/helpers/baseline_manager.py` -- Baseline comparison logic
- `src/warden/cli/commands/helpers/git_helper.py` -- Git operations
- `src/warden/cli/utils.py` -- CLI utility functions

**Recommended tests:**
- Use Typer's `CliRunner` to test each command's happy path and error conditions
- Test argument parsing and validation
- Test output formatting with mocked pipeline results
- Test exit code logic (especially `scan.py` which drives CI pass/fail)
- Test `git_helper.py` with mocked git subprocess calls

### 2. Config Module (8 files, 0 tests)

Configuration parsing and validation is a critical correctness concern. Bugs here affect every scan.

**Key untested files:**
- `src/warden/config/yaml_parser.py` -- Parses both simple and full (visual builder) YAML formats into `PipelineConfig`
- `src/warden/config/yaml_validator.py` -- Schema validation for config files
- `src/warden/config/project_config.py` -- Project-level configuration resolution
- `src/warden/config/config_generator.py` -- Auto-generates config from project analysis
- `src/warden/config/project_detector.py` -- Detects project type (Python, JS, Go, etc.)
- `src/warden/config/domain/models.py` -- Core config data models (`PipelineConfig`, `PipelineNode`, etc.)

**Recommended tests:**
- Test YAML parsing with valid simple-format and full-format configs
- Test parsing failures: malformed YAML, missing required fields, invalid types
- Test `project_detector.py` against different project structures
- Test `config_generator.py` produces valid configs for various detected project types
- Test `yaml_validator.py` rejects invalid schemas and accepts valid ones
- Test config model serialization/deserialization round-trips

### 3. Reports Module (3 files, 0 tests)

Report generation includes file locking, SARIF output, HTML generation, and concurrent write protection.

**Key untested files:**
- `src/warden/reports/generator.py` -- SARIF/JSON report generation with file locking and stale lock detection
- `src/warden/reports/html_generator.py` -- HTML report rendering
- `src/warden/reports/status_reporter.py` -- Status reporting

**Recommended tests:**
- Test SARIF report generation against SARIF schema
- Test file locking (`file_lock` context manager): concurrent access, stale lock cleanup, timeout behavior
- Test HTML report structure and content
- Test report generation with empty results, single finding, many findings

### 4. Secrets Module (8 files, 0 tests)

Secret management and provider integrations are security-sensitive code.

**Key untested files:**
- `src/warden/secrets/application/secret_manager.py` -- Secret resolution and caching
- `src/warden/secrets/application/template_resolver.py` -- Template variable resolution
- `src/warden/secrets/providers/env_provider.py` -- Environment variable secrets
- `src/warden/secrets/providers/dotenv_provider.py` -- .env file secrets
- `src/warden/secrets/providers/azure_keyvault_provider.py` -- Azure Key Vault integration

**Recommended tests:**
- Test each provider independently with mocked backends
- Test secret resolution order and fallback logic in `secret_manager.py`
- Test template resolution with missing variables, nested templates
- Test that secrets are properly masked in logs/output (security-critical)

### 5. Classification Module (3 files, 0 tests)

**Key untested files:**
- `src/warden/classification/application/classification_phase.py`
- `src/warden/classification/application/llm_classification_phase.py`
- `src/warden/classification/application/classification_prompts.py`

### 6. Memory Module (2 files, 0 tests)

**Key untested files:**
- `src/warden/memory/application/memory_manager.py`
- `src/warden/memory/domain/models.py`

---

## Priority 2: Severely Under-Tested Modules (<15% Coverage)

### 7. gRPC Module (22 files, 1 test file, 4.5% coverage)

Only `test_grpc_tls.py` exists (13 tests focused on TLS configuration). The entire gRPC server, all servicer mixins, converters, and repositories are untested.

**Critical untested files:**
- `src/warden/grpc/server.py` -- gRPC server lifecycle
- `src/warden/grpc/servicer/base.py` -- Base servicer implementation
- `src/warden/grpc/converters.py` -- Proto/domain model conversion
- `src/warden/grpc/infrastructure/` -- All repository implementations (history, issue, suppression, baseline)
- All servicer mixins in `src/warden/grpc/servicer/mixins/`

**Recommended tests:**
- Test converters with round-trip proto<->domain conversion
- Test repository implementations with temp file fixtures
- Test server startup/shutdown lifecycle
- Test servicer request handling with mocked dependencies

### 8. Shared Utilities (31 files, 3 test files, 9.7% coverage)

The resilience patterns (circuit breaker, retry, bulkhead, timeout) are completely untested despite being used across the codebase.

**Critical untested files:**
- `src/warden/shared/infrastructure/resilience/circuit_breaker.py` -- CircuitBreaker with CLOSED/OPEN/HALF_OPEN states
- `src/warden/shared/infrastructure/resilience/retry.py` -- Retry with backoff
- `src/warden/shared/infrastructure/resilience/bulkhead.py` -- Concurrency limiting
- `src/warden/shared/infrastructure/resilience/timeout.py` -- Timeout wrapper
- `src/warden/shared/infrastructure/resilience/combined.py` -- Combined resilience patterns
- `src/warden/shared/infrastructure/pii_masker.py` -- PII masking (security-critical)
- `src/warden/shared/infrastructure/ignore_matcher.py` -- Gitignore-style matching
- `src/warden/shared/infrastructure/error_handler.py` -- Global error handling

**Recommended tests:**
- Test circuit breaker state transitions: CLOSED -> OPEN on failures, OPEN -> HALF_OPEN on timeout, HALF_OPEN -> CLOSED on success
- Test retry with exponential backoff, max retries, excluded exceptions
- Test bulkhead concurrency limits
- Test PII masking for emails, IPs, API keys, etc.
- Test ignore matcher against gitignore patterns

### 9. Fortification Module (12 files, 1 test file, 8.3% coverage)

Only `test_auto_fixer.py` exists. The orchestrator, all fortifier implementations, and the phase runner are untested.

**Critical untested files:**
- `src/warden/fortification/application/fortification_phase.py` -- Phase runner
- `src/warden/fortification/application/orchestrator.py` -- Fortification orchestration
- `src/warden/fortification/application/fortifiers/error_handling.py`
- `src/warden/fortification/application/fortifiers/input_validation.py`
- `src/warden/fortification/application/fortifiers/logging.py`
- `src/warden/fortification/application/fortifiers/resource_disposal.py`
- `src/warden/fortification/infrastructure/git_checkpoint.py`

### 10. MCP Module (36 files, 4 test files, 11.1% coverage)

Only 13 test functions cover 36 source files. The server, service layer, tool executor, resource provider, and most adapters have no tests.

**Critical untested files:**
- `src/warden/mcp/server.py` -- MCP server implementation
- `src/warden/mcp/application/mcp_service.py` -- Service orchestration
- `src/warden/mcp/application/tool_executor.py` -- Tool execution
- `src/warden/mcp/application/resource_provider.py` -- Resource management
- `src/warden/mcp/application/session_manager.py` -- Session handling
- `src/warden/mcp/infrastructure/warden_adapter.py` -- Core Warden integration
- All adapters in `src/warden/mcp/infrastructure/adapters/`

### 11. Cleaning Module (15 files, 2 test files, 13.3% coverage)

Only the code simplifier and orchestrator integration are tested. Eight cleaning analyzers have no tests.

**Untested analyzers:**
- `complexity_analyzer.py`, `documentation_analyzer.py`, `duplication_analyzer.py`
- `magic_number_analyzer.py`, `maintainability_analyzer.py`, `naming_analyzer.py`
- `testability_analyzer.py`, `lsp_diagnostics_analyzer.py`

### 12. Analysis Module (37 files, 4 test files, 10.8% coverage)

**Critical untested files:**
- `src/warden/analysis/application/analysis_phase.py` -- Main analysis phase runner
- `src/warden/analysis/application/discovery/discoverer.py` -- File discovery
- `src/warden/analysis/application/llm_analysis_phase.py` -- LLM-powered analysis
- `src/warden/analysis/services/linter_service.py` -- Linter integration
- `src/warden/analysis/application/dependency_graph.py` -- Dependency analysis
- `src/warden/analysis/application/metrics_aggregator.py` -- Metrics collection

---

## Priority 3: Quality Issues in Existing Tests

### Weak Assertions in Validation Frame Tests

Several frame tests use overly permissive assertions:

```python
# Weak -- passes regardless of what the frame finds
assert result.status in ['passed', 'failed']
assert len(result.findings) >= 0
```

These should be strengthened to validate specific findings, severities, and messages.

### LLM Factory Tests Missing Provider Coverage

`tests/llm/test_factory.py` has only 4 tests covering Anthropic and DeepSeek. Missing tests for: Groq, Claude Code, Ollama, OpenAI, Gemini providers. No async tests despite LLM calls being async.

### MCP Tests Have Very Low Test Density

4 test files with only 13 tests total (3.2 tests per file) for a module with 36 source files. Error scenarios, protocol edge cases, and integration flows are not covered.

### Missing Error Scenario Fixtures

`tests/conftest.py` provides 6 basic fixtures but lacks:
- Error-inducing fixtures (corrupted input, timeout-simulating LLM, rate-limited services)
- Varied configuration fixtures (minimal, strict, permissive pipeline configs)
- Large-scale project fixtures for performance boundary testing

---

## Infrastructure Gaps

### 1. No Coverage Measurement in CI

`pytest-cov` is not in the project dependencies. The CI pipeline (`ci.yml`, `test.yml`) runs tests but does not collect or report coverage. There is a commented-out note: "Coverage disabled -- pytest-cov not in dependencies."

**Recommendation:** Add `pytest-cov` to dev dependencies and configure a coverage threshold gate in CI.

### 2. Tests Only Run on Version Tags

In `ci.yml`, the test job only runs on `v*` tags, not on every push or PR. Linting runs on all PRs, but tests do not.

**Recommendation:** Run at least a core test subset on every PR to catch regressions before merge.

### 3. Several Test Categories Excluded from CI

- `tests/chaos/` -- Property-based testing (requires Hypothesis)
- `tests/integration/` -- External service tests
- `tests/e2e/test_acceptance.py` -- Subprocess acceptance tests
- `tests/unit/grpc_testing/` -- Marked as incomplete

While some exclusions are reasonable, the chaos and property-based tests would provide high value if integrated.

---

## Recommended Action Plan

### Phase 1: Foundation (Highest Impact)

1. **Add `pytest-cov` to dev dependencies** and enable coverage reporting in CI
2. **Add CLI command tests** using `CliRunner` -- focus on `scan`, `init`, `doctor`, `install`
3. **Add config module tests** -- YAML parsing, validation, project detection
4. **Add shared resilience pattern tests** -- circuit breaker, retry, bulkhead

### Phase 2: Security-Critical Paths

5. **Add secrets module tests** -- provider resolution, secret masking
6. **Add report generation tests** -- SARIF output, file locking, HTML generation
7. **Strengthen validation frame assertions** -- replace `>= 0` with specific finding expectations
8. **Add PII masker tests** -- verify sensitive data is properly redacted

### Phase 3: Integration Layer

9. **Add gRPC converter and repository tests** -- proto conversion round-trips
10. **Add MCP service and adapter tests** -- tool execution, resource provision
11. **Add cleaning analyzer tests** -- each of the 8 untested analyzers
12. **Add analysis phase tests** -- discovery, dependency graph, LLM analysis

### Phase 4: Quality Improvements

13. **Expand LLM factory tests** for all providers with async coverage
14. **Add error scenario fixtures** to `conftest.py`
15. **Enable tests on every PR** (not just version tags) in CI
16. **Integrate Hypothesis** for property-based testing in the main CI run

---

## Modules with Strong Coverage (Models to Follow)

- **suppression** (100%, 81 tests): Comprehensive matcher testing with 36 tests covering edge cases
- **rules** (100%, 65 tests): Thorough error handling coverage including timeouts, missing files, permissions
- **pipeline** (33%, 117 tests): Good async orchestration testing with multiple execution strategies

These modules demonstrate the testing patterns that should be applied across the codebase.
