# Changelog

All notable changes to Warden will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- GitHub Actions composite action for marketplace integration
- `--quick-start` flag for LLM-free deterministic scanning
- Markdown output format for scan reports (`--output markdown`)
- Detection source field on findings distinguishing LLM vs deterministic attribution
- Live integration smoke assertions in CI after `warden scan`
- Remediation data in Rust engine findings

### Fixed
- Top-level CLI error handler with user-friendly messages (#451)
- SARIF output now uses relative paths with `uriBaseId` to prevent directory leaks (#480)
- Per-call timeout enforced in `complete_async` to prevent hanging LLM calls (#479)
- Dead OpenRouter provider enum and all references removed (#478)
- Severity enum crash and missing `get_frame_by_id` imports restored
- YAML parser orphan except block causing `SyntaxError`
- CI mode auto-saves JSON report for smoke check
- Cache now preserves `remediation`, `machine_context`, and `exploit_evidence`
- `--no-baseline` and `--no-intel` flags respected in non-interactive `init`
- Process group killed on script timeout to prevent zombie processes
- Metrics collection errors logged as warnings instead of silently swallowed

### Changed
- `init_command` decomposed from 708 lines into 6 focused step functions
- `TaintAnalyzer` split from 1526 lines into 4 language-specific strategy modules
- `scan.py` split from 1813 lines into 3 focused modules
- LLM duration calculation and error response DRY-ed across 8 providers
- `LlmConfiguration` gains typed `tpm_limit`/`rpm_limit` fields
- 9 verified dead functions removed from codebase
- 70 weak return-code test assertions replaced with `_assert_no_crash`

---

## [2.5.0] - 2026-02-25

### Added
- Contract Mode Complete: 6 gap types for data-flow analysis (closes #173)

---

## [2.4.0] - 2026-02-25

### Added
- Contract Mode: Data Flow Analysis engine (closes #169)

### Changed
- Bumped `grpcio-tools` upper bound to `<1.79.0`
- Bumped `aiofiles` upper bound to `<26.0.0`
- Bumped `rich` upper bound to `<15.0.0`
- Updated GitHub Actions: `checkout`, `setup-node`, `upload-artifact` to v6; `cache` to v5

---

## [2.3.0] - 2026-02-23

### Fixed
- SARIF: removed invalid `name` from notification descriptor
- Token estimate assertion widened for CI environments without `tiktoken`
- CI template packaging, scan timeout, and provider leaks resolved
- Lint and test failures blocking CI pipeline
- LLM config: skip `config.yaml` model overrides when provider is env-var-overridden
- Groq client now ignores non-Groq model names

---

## [2.2.3] - 2026-02-22

### Fixed
- LLM smart model sync with provider override in CI
- Groq error logs now include HTTP response body
- Groq default model updated to `llama-3.3-70b-versatile`
- Baseline cache fallback added for tag-based CI pushes
- CLI error logging, fortification unlinking, and duplicate finding IDs resolved
- Ruff 0.15.0 pinned in CI; all lint errors resolved

### Added
- Self-healing capabilities: strategies, orchestrator, and classifier integrated into pipeline and LLM services
- Framework-aware false-positive reduction and opt-in LLM verification
- Audit context CLI, LSP, and MCP tools (stages 4–8)
- Audit context dependency and code graph (stages 1–3)
- Taint analysis service with expanded security framework models for multiple languages
- Codex CLI as a local LLM provider
- `WARDEN_LLM_PROVIDER` env var for CI/local config separation
- Refreshed CLI scan UX with ASCII art logo and detailed progress updates

### Changed
- Pipeline executor error handling enhanced

---

## [2.2.0] - 2026-02-18

### Added
- Language detection now respects `.gitignore`/`.wardeignore` filter
- MCP adapter tool execution timeout and handler dispatch fixed
- `WARDEN_LLM_PROVIDER` environment variable for provider configuration
- Comprehensive license information and badge in README

### Fixed
- MCP `tools/list` blocking and `notifications/initialized` handling
- Frame `execute_async` signature incompatibilities resolved
- All ruff linter errors across codebase
- CI workflow failures resolved

---

## [2.1.0] - 2026-02-17

### Added
- Comprehensive metrics tracking for production debugging (observability)
- Token-aware truncation for context safety in LLM calls

### Fixed
- P0 type safety and security hardening
- MCP handler method names corrected with `_async` suffix

---

## [2.0.3] - 2026-02-16

### Fixed
- ANSI stripping in CI for init and scan help output tests
- Baseline assertions relaxed; Ollama-dependent tests skipped in CI
- CI uses standard frame level to avoid custom frame loading
- `init` non-interactive mode in cloud provider fallback
- AST cache type guard in pipeline
- `HardcodedPasswordCheck` false positives resolved; suppression format standardised
- Framework enum conversion between discovery and project context
- `FrameworkDetector` usage and async handling corrected
- Missing `FileNotFoundError` handling in file analyzers

### Added
- Finding suppressions and security baselines support
- Comprehensive test coverage for `HardcodedPasswordCheck`

---

## [2.0.0] - 2026-02-06

### Added
- Universal AST via tree-sitter migration for 50+ language support
- `AntiPatternFrame` for detecting code anti-patterns across 15+ languages
- SpecFrame Gen 3 Universal Contract Extractor with parallelisation and methodology-based prompting
- LSP pipeline integration
- Rust AST provider
- AST caching and pre-parsing optimisations across validation frames
- Pipeline chaining, ProjectIntelligence, cross-repo drift E2E, exploit evidence
- MachineContext, per-frame metrics, taint analysis, prompt templates, auto-fix
- End-to-end acceptance test suite with fixture project
- Pre-flight check system for E2E tests
- Finding suppression and config schema validation
- Chaos Hardening Infrastructure: `ParallelExecutor`, `SafeScanner`, `FrameCleanup`
- Interactive setup system core modules
- LLM global rate limiting with API key verification and prompt injection protection
- Privacy-aware logging
- Signed SVG badge support
- Claude Code as a local LLM provider
- Parallel execution for fast-tier providers in `OrchestratedLlmClient`
- `warden config` command for LLM provider management

### Fixed
- Chaos engineering principles applied to production error handling
- 6 production readiness issues resolved (#29–#34)
- HardcodedPasswordCheck false positives and self-scan findings
- Critical SpecFrame bugs: thread safety, path resolution, async/sync mismatch
- Prompt injection protection and gap analysis timeout in SpecFrame
- Bare-catch detection accuracy improved

### Changed
- `TimeoutError` renamed to `OperationTimeoutError` to avoid stdlib shadowing
- Orchestrator refactored: phase runner, post-processor, result builder extracted
- `_run_scan_async` decomposed into 5 focused helpers
- `configure_agent_tools` split into focused functions
- AntiPatternFrame detectors split from god class into modular structure

---

## [1.9.0] and earlier

For changes prior to v2.0.0 please refer to the git history:

```
git log --oneline v1.9.0
```

[Unreleased]: https://github.com/alperduzgun/warden-core/compare/v2.5.0...HEAD
[2.5.0]: https://github.com/alperduzgun/warden-core/compare/v2.4.0...v2.5.0
[2.4.0]: https://github.com/alperduzgun/warden-core/compare/v2.3.0...v2.4.0
[2.3.0]: https://github.com/alperduzgun/warden-core/compare/v2.2.3...v2.3.0
[2.2.3]: https://github.com/alperduzgun/warden-core/compare/v2.2.0...v2.2.3
[2.2.0]: https://github.com/alperduzgun/warden-core/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/alperduzgun/warden-core/compare/v2.0.3...v2.1.0
[2.0.3]: https://github.com/alperduzgun/warden-core/compare/v2.0.0...v2.0.3
[2.0.0]: https://github.com/alperduzgun/warden-core/compare/v1.9.0...v2.0.0
