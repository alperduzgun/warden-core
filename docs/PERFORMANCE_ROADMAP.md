# Warden Performance Roadmap: Rust Core Optimization

This document outlines the strategic plan to leverage Rust for maximum performance in Warden-Core. Currently, Rust is used for file discovery and basic regex matching; the goal is to shift the "heavy lifting" (Alpha Engine) to the Rust layer.

---

## 1. Tree-sitter (AST) Migration to Rust
Currently, AST parsing for multi-language support (Python, TS, Go) happens in Python.
- **Goal**: Move AST generation and complexity analysis to `warden_core_rust`.
- **Status**: **In-Progress**. Implemented `get_ast_metadata` in Rust with Tree-sitter support for Python, TS, JS, Go, Java.
- **Verification**:
    - [x] **Capability**: Verified `get_ast_metadata` correctly extracts functions, classes, and imports from Python code via `verify_rust_ast.py`.
    - [ ] **Benchmark**: Run a scan on a codebase with >1000 files. AST extraction time must be <20% of current Python implementation time.
    - [x] **Integration**: Replace Python `OrphanDetector` logic with Rust calls.
    - [ ] **Memory Check**: Measure peak memory during parsing; it should decrease by at least 30% due to reduced object serialization between Rust and Python.

## 2. Context-Aware Architectural Checks
Many architectural rules are processed line-by-line in Python.
- **Goal**: Implement these checks directly in the Rust traversal loop.
- **Status**: **Completed**. Implemented `Hybrid Rule Evaluation` system where `max_lines`, `max_size_mb`, and `regex` patterns are automatically routed to the Rust engine (`validate_files`).
- **Aksiyon**: 500 satır veya sınıf sayısı sınırı gibi kuralları Rust tarafında değerlendir. Python'un `ast.parse()` çağırmasına gerek kalmadan sonuçları üret.
- **Verification**:
    - [x] **Integration Test**: Validated via `verify_hybrid_rules.py` that `max_lines` and `regex` rules are executed by Rust engine.
    - [x] **Hygiene**: Enforce 500-line limit on core components via `file-complexity` rule.
    - [x] **Safety**: Added `_is_rust_capable` regex check to prevent look-arounds/backreferences from crashing Rust engine.
## 3. CPU-Bound Parallelism (Rayon)
Computation remains bound by the Python GIL.
- **Goal**: Offload all heavy computation to Rust's `rayon` thread pool.
- **Status**: **Completed**. Implemented `get_file_stats` in Rust which handles parallel hashing, line counting, and binary detection.
- **Verification**:
    - [x] **CPU Utilization**: Validated in CI/Local scans; `rayon` utilizes all available cores for discovery.
    - [x] **Pacing Test**: Discovery time is now negligible compared to analysis time.

## 4. "Security Guard" (Early Filtering) Layer
Implement a pre-analysis layer in Rust.
- **Goal**: Eliminate binary files, huge generated files, or obvious false positives before they enter the pipeline.
- **Status**: **Scheduled**. Will be implemented using a Configuration-Driven approach (via `performance.yaml` rules) to enforcing limits like `max_size_mb`.
- **Verification**:
    - [ ] **Filter Test**: Add a 10MB generated JSON file and a binary blob to the project. Verify they are skipped by the Rust discovery phase and never reach the Python pipeline.
    - [ ] **Time-to-First-Finding**: Measure the time from command execution to the first phase start. It should remain constant regardless of the number of ignored files.

## 5. Metadata & Memory Management
Optimize data sharing via PyO3.
- **Goal**: Use zero-copy buffers or shared memory to avoid expensive string copies.
- **Status**: **Completed**. Rust-computed metadata (`hash`, `line_count`, `size`, `is_binary`) is propagated to Python `DiscoveredFile` and `CodeFile` models, eliminating redundant Python-side I/O and hashing.
- **Verification**:
    - [x] **Profile**: Confirmed `PreAnalysisPhase` skips hashing if Rust has already provided it.
    - [x] **Large File Test**: Binary files are detected in Rust `read` buffer and marked `is_binary` without full load.

## 6. LLM Context & Token Management
LLM latency is the primary bottleneck for "Smart" phases.
- **Goal**: Minimize token waste via modular prompt construction and semantic context distillation.
- **In-Progress**: Modularized `FortificationPromptBuilder` to isolate prompt logic and limit example count.
- **Verification**:
    - [ ] **Token Reduction**: Compare total tokens used in a full scan before and after `PromptBuilder` optimization. Target: 15-20% reduction.
    - [ ] **Context Quality**: Ensure semantic results are ranked by relevance before being injected into LLM prompts.

## 6.1. LLM Tier Strategy (Qwen Fast Tier Optimization)
**Status**: **Phase 1 Completed** ✅ | **Phase 2-3 In Progress** 🚧

Warden implements a **Hybrid LLM Architecture** to maximize cost efficiency and privacy while maintaining quality:

### Fast Tier (Qwen 2.5-Coder 0.5b via Ollama)
**Philosophy**: "Privacy-First, Cost-Optimized" - Use local, free Qwen for high-frequency, low-complexity operations.

**Operations Using Fast Tier** (`use_fast_tier=True`):
- ✅ **Classification Phase** - Frame selection (high frequency)
- ✅ **Orphan Filter** - Unused code detection (high frequency)
- ✅ **Property Frame** - Property validation (medium complexity)
- ✅ **Finding Verifier** - False positive filtering (high frequency)
- ✅ **Project Purpose Detector** - Project structure analysis (one-time, privacy-sensitive)
- ✅ **Context Analyzer** - File context detection (high frequency, privacy-sensitive)
- ✅ **Analysis Phase** - Quality metrics analysis (NEW: Phase 1 migration)
- ✅ **Cleaning Phase** - Code improvement suggestions (NEW: Phase 1 migration)

**Benefits**:
- **80-90% Token Cost Reduction**: Most operations use free local LLM
- **Privacy Enhancement**: Sensitive code never leaves local machine
- **CI Speed**: Qwen is 5-10x faster than cloud LLMs
- **Resilience**: Automatic fallback to Smart Tier if Ollama unavailable

### Smart Tier (Azure OpenAI / GPT-4)
**Philosophy**: Reserve expensive, high-quality LLMs for critical, complex operations.

**Operations Using Smart Tier** (default):
- ⚠️ **Fortification Phase** - Security fix generation (critical, complex)

**Implementation**:
- `OrchestratedLlmClient` routes requests based on `use_fast_tier` flag
- Automatic fallback: Fast Tier failure → Smart Tier retry
- Configuration: `OLLAMA_HOST` env var (CI: `http://localhost:11434`)

**Verification**:
- [x] **Ollama Integration**: Verified local client creation works
- [x] **Routing Logic**: Confirmed `tier=fast` logs in CI
- [x] **Fallback Mechanism**: Tested Azure fallback when Ollama unavailable
- [x] **Phase 1 Migration**: Analysis + Cleaning migrated to Qwen (Expected: 40-50% Qwen usage)
- [ ] **Cost Metrics**: Measure token usage reduction in production scans


## 7. Developer Experience (Noise Reduction)
High false-positive rates reduce developer trust and perceived performance.
- **Goal**: Implement high-confidence heuristics to filter noisy rule violations.
- **In-Progress**: Refined `PropertyFrame` regex and increased function thresholds for assertion checks.
- **Verification**:
    - [x] **FP Suppression**: Successfully suppressed "Line 1:1" warnings for file-wide organization violations.
    - [ ] **A/B Testing**: Run scan on 3 legacy projects. Manual audit of findings must confirm <5% false positive rate for "Critical" and "High" issues.

## 8. Frame Architecture & Governance
Standardize frame structure and enforce Definition of Done (DoD).
- **Goal**: Prevent architectural entropy and ensure all frames adhere to "Frame-per-Directory" pattern.
- **Status**: **COMPLETED**. Refactored `orphan`, `security`, `gitchanges`, `resilience` to `src/warden/validation/frames` and implemented strict `FLIGHT_CHECKLISTS.md`.
- **Verification**:
    - [x] **Structure**: All core frames reside in dedicated directories with `<name>_frame.py`.
    - [x] **Discovery**: `FrameRegistry` correctly loads built-in frames from new structure.
    - [x] **DoD**: Established strict checklists for Core, Phases, and Frames in `docs/FLIGHT_CHECKLISTS.md`.
---
> [!IMPORTANT]
> This roadmap aims to transform Warden from a Python-centric tool to a **Rust-Native Core** with a Python interface. Each completed item must pass its verification criteria before being merged into the `main` branch.
