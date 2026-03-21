# Changelog

All notable changes to warden-core are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [2.6.0] - 2026-03-21

### Highlights

- **99.5% false-positive reduction** on self-scan: 388 findings down to 2
- **Cross-file analysis** now production-ready with import graph, value propagation, and LLM context enrichment
- **98%+ detection rate** validated against 53 planted vulnerabilities across 4 real projects
- **6 new security patterns** covering prototype pollution, TLS misconfiguration, and IDOR

### Added

#### Security Detection
- Prototype pollution detection (CWE-915) — `__proto__`, `constructor.prototype` assignment patterns
- TLS certificate verification bypass (CWE-295) — `verify=False` in `requests`, `httpx`, `aiohttp`
- SSL `CERT_NONE` and `check_hostname=False` misconfiguration patterns
- IDOR LLM-guided detection with contextual prompt enrichment
- SSTI, `setattr` injection, and `yaml.unsafe_load` patterns
- Dunder taint-context awareness — taint sinks now distinguish `__setitem__` vs application code

#### Cross-File Analysis
- Import graph construction for module-level dependency tracking
- Value propagation across file boundaries for inter-module taint flows
- LLM context enrichment using cross-file call graph data

#### Pipeline & Tooling
- Deep scan timeout increased from 600s to 900s for large codebases
- Fuzz frame JSON parse recovery — scan continues on malformed LLM output
- LSP EOF noise reduction and spawn retry prevention
- `warden init` scaffold now generates rich `.warden/` with rules, suppressions, context, and frame configs

### Changed

#### False Positive Reduction (Frames)
- **Orphan frame**: added 48 framework decorator exemptions (FastAPI, Flask, Celery, Click, etc.), cross-file reference filter, AST visitor/dunder method exemption, and `self.method()` call capture
- **Fuzz frame**: removed high-noise regex patterns entirely; detection is now LLM-only for precision
- **Property frame**: rewrote division guard detection, added pathlib `/` operator exclusion, `while True` loop exclusion, test-file-only assertion filter, `ContextVar` FP filter, LLM noise filter, and LLM line hallucination validation

#### Taint Analysis
- `os.environ`, `os.getenv`, `process.env` reclassified as semi-trusted sources — severity capped at MEDIUM instead of HIGH

#### Analysis & Scoring
- Cross-frame semantic deduplication with vulnerability class normalization eliminates duplicate findings across overlapping frames
- Quality score calculated from pre-baseline findings for stability
- `totalFrames` in pipeline output now reflects executed frame count accurately

#### Baseline
- Overhauled fingerprint system — stable across line shifts, no false-resolved findings
- Unified module-based reading with `fail-on-severity` support

#### LLM Integration
- AST, LSP, and semantic data wired into LLM prompts for richer context
- LLM triage temperature fixed to `0.0` for deterministic results
- Deterministic findings exempted from LLM suppression
- Per-provider rate limits configurable via `config.yaml`
- 429 rate limit handling added for OpenAI and Anthropic providers
- Qwen Code CLI provider added

#### Configuration
- `analysis_level` setting supported in `config.yaml` and as environment variable
- `min_severity` and `classification_config` wired into `PipelineConfig`
- `llm.model` accepted as alias for `smart_model`

### Fixed

- LSP `c.location` `AttributeError` on partial diagnostic results
- LSP auto-install on first-run systems
- Fuzz array-bounds check restricted to numeric index access only (removes type annotation FPs)
- Division regex rewritten to assignment/return context only
- Property frame no longer reports "no assertions" on production files (test-only filter)
- `CheckFinding.suggestion` now routed correctly to `Finding.remediation`
- SARIF `executionSuccessful` reflects tool health, not LLM availability
- Pipeline finding deduplication after post-processor re-sync
- Double-counting of rule violations in `_collect_findings`
- `unknown` severity normalized to `low` in quality score calculation
- Diff mode `old_path` mapping for renamed files

---

## [2.5.0] - 2026-02-19

Initial public release on the 2.x series.

### Added
- Multi-frame validation pipeline (security, property, orphan, fuzz, taint)
- SARIF 2.1 output format
- Baseline management with fingerprint-stable suppression
- LLM-assisted triage with Anthropic, OpenAI, Ollama, and Azure providers
- GitHub Action integration with diff-mode support
- `warden init` for project scaffolding
- Rich TUI scan progress display
- gRPC server mode (experimental)

---

[2.6.0]: https://github.com/alperduzgun/warden-core/compare/v2.5.0...v2.6.0
[2.5.0]: https://github.com/alperduzgun/warden-core/releases/tag/v2.5.0
