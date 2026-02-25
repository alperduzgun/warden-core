# Warden Core - Release Notes

## v2.4.0 (2026-02-25) - Contract Mode: Data Flow Analysis

### 🎯 Major Features

**Contract Mode — `warden scan --contract-mode`**
- Opt-in data flow contract analysis detecting structural gaps in the pipeline
- `DeadDataFrame`: AST-based detection of DEAD_WRITE, MISSING_WRITE, and NEVER_POPULATED fields
- `DataDependencyGraph (DDG)`: Full write/read tracking across all Python source files
- `DataDependencyBuilder + DDGVisitor`: AST-powered DDG construction with FP filters
- `DataFlowAware` mixin: Standardized DDG injection protocol for frames

**Reporting Enhancements**
- Contract Mode terminal summary panel (5 gap types: DEAD_WRITE, MISSING_WRITE, STALE_SYNC, PROTOCOL_BREACH, ASYNC_RACE)
- SARIF enrichment: 5 contract rules with `fullDescription`, `help`, and `tags`
- `CONTRACT_RULE_META` registry in generator.py

**Security Bug Fixes**
- Restored `taint_context` parameter in `_aggregate_findings` (broken by TaintAware refactor)
- Fixed `html.escape()` scope leak: escaped values no longer written to MachineContext/findings storage

**Performance & CI**
- Generated file skip (reduces scan overhead on projects with build artifacts)
- Findings cache for unchanged files
- Per-file timeout to prevent single-file hang
- Fixed redis key pattern duplicate violation in CI (3 violations → 2)

### 🧪 Test Coverage
- **1372 tests passing** (Python 3.10, 3.11, 3.12)
- New: DDG unit tests + E2E contract violation fixtures (`dead_write_project`, `clean_project`)
- New: DeadDataFrame unit + integration tests
- New: SecurityFrame machine context tests restored

### 📊 Impact
- Zero regressions on full test suite
- Contract analysis is opt-in (`--contract-mode` flag) — no impact on existing scans
- Graceful degradation: DeadDataFrame skips if DDG not injected
- FP-safe: `PIPELINE_CTX_NAMES` whitelist prevents false positives on internal pipeline fields

### 🔧 Issues Closed
`#162` DDG domain model · `#163` DataDependencyBuilder + FP filters · `#164` DDG tests + fixtures ·
`#165` DataFlowAware mixin + service · `#166` Pipeline wiring + CLI flag · `#167` DeadDataFrame ·
`#168` DeadDataFrame tests + E2E fixtures · `#174` Contract terminal summary + SARIF enrichment ·
`#175` taint_context TypeError fix · `#176` html.escape scope fix

### ⬆️ Upgrading to v2.4.0
No breaking changes. New `--contract-mode` flag is strictly opt-in.
```bash
warden scan --contract-mode src/
```

---

## v2.1.0 (2026-02-17) - Observability & Production Hardening

### 🎯 Major Features

**Comprehensive Metrics & Observability**
- Context injection health monitoring with timing metrics
- Finding deduplication collision tracking and effectiveness metrics
- Fortification linking success rate monitoring
- **CRITICAL**: Truncated findings logging prevents silent data loss

### 🔧 Improvements

**Production Debugging Capabilities**
- Track project intelligence injection across frames
- Monitor prior findings injection and error rates
- Log severity distribution of dropped findings
- Validate fortification contract fields

**Pipeline Health Visibility**
- Average injection time tracking
- Deduplication rate calculation
- Link success rate monitoring
- Comprehensive error categorization

### 📊 Impact
- Zero regressions (36 tests passing)
- Production-ready observability infrastructure
- Prevents silent failures in high-volume scans
- Enables data-driven pipeline optimization

---

## v2.0.3 → v2.0.0 Series - Type Safety & Security Hardening

### 🛡️ Security Enhancements

**BATCH 1: Type Safety Foundation**
- Fixed CRITICAL empty location deduplication bug
- Normalized Finding type handling (object vs dict)
- Case-insensitive severity ranking
- Eliminated 78% of critical failure modes

**BATCH 2: Security Hardening**
- Prompt injection detection and HTML sanitization
- Token-aware truncation (prevents LLM context overflow)
- Project intelligence structure validation
- Input validation on findings list (prevent memory bombs)

### 🧪 Test Coverage
- 13 type safety tests
- 9 prompt injection tests
- 14 context-awareness tests
- **Total: 36 new tests, all passing**

### 🔧 Technical Improvements
- Token utilities integration (qwen 2048 limit support)
- MCP handler method fixes (22 tools restored)
- Smart caching for unchanged files
- Incremental scanning support

---

## v1.9.0 - Context-Aware Analysis

### 🎯 Features
- Project intelligence injection into frames
- Cross-frame finding awareness
- Semantic context from related files
- LLM-powered security verification

### 🔧 Improvements
- Enhanced prompt building with project context
- Entry points and critical sinks detection
- Authentication pattern recognition
- Prior findings context in prompts

---

## v1.8.x Series - Performance & Stability

### ⚡ Performance
- Smart caching for file processing
- Skip unchanged files in validation
- Incremental scanning for cleaning phase
- Optimized LLM processing

### 🔧 Improvements
- v1.8.3: Enhanced progress reporting
- v1.8.2: Cache file contexts for unchanged files
- v1.8.1: Environment hash validation
- v1.8.0: Dynamic versioning for releases

---

## v1.7.x Series - Frame Extensions

### 🎯 Features
- Frame extension system
- Demo and environment security frames
- Auto-discovery for custom frames
- Frame configuration merging

### 🔧 Improvements
- v1.7.3: Enhanced frame discovery
- v1.7.1: Frame consistency validation
- v1.7.0: Dynamic frame loading

---

## v1.6.x Series - CI/CD & Reporting

### 🎯 Features
- GitHub CLI integration
- SARIF status reporting
- JSON, SARIF, and JUnit reports
- Docker support

### 🔧 Improvements
- v1.6.2: Normalize paths for portability
- v1.6.1: Modular CLI commands
- v1.6.0: Incremental scanning, smart caching

---

## v1.5.0 - Repository Pattern & gRPC

### 🎯 Features
- Repository pattern for issue management
- gRPC server with reflection support
- Full pipeline execution with streaming
- Smart caching for unchanged files

### 🔧 Improvements
- Pydantic domain model migration
- LLM-based project detection
- Analysis cache versioning
- Orphan detector strategy pattern

---

## v1.4.x Series - IPC & Backend

### 🎯 Features
- v1.4.1: Modular phase executors
- v1.4.0: Interactive frame manager
- Backend pipeline architecture
- Azure Key Vault support

### 🔧 Improvements
- Real-time streaming progress
- Graceful shutdown system
- Pipeline UI visualization
- Auto-restart backend

---

## v1.3.x Series - Rules & Testing

### 🎯 Features
- Rules CLI commands
- Pipeline orchestrator rules
- Architectural consistency validation
- Fuzz testing and property validation

### 🔧 Improvements
- Smart filtering for false positives
- Comprehensive test coverage
- Semantic searcher tests
- Dashboard metrics tests

---

## v1.2.0 - LLM Integration

### 🎯 Features
- LLM support for code analysis
- Enhanced prompt building
- Cleanup and discovery modules
- Resource disposal fortifiers

---

## v1.1.0 - Frame Execution

### 🎯 Features
- Auto-register frames
- Pipeline config loading
- Visual hierarchy in TUI
- Progress indicators

---

## v1.0.x Series - Foundation

### 🎯 Features
- v1.0.2: Warden TUI with command palette
- v1.0.1: AST module testing, SQL injection detection
- v1.0.0: Initial setup with mem0 integration

### 🔧 Improvements
- Qdrant vector database
- Azure OpenAI embeddings
- JSON compatibility tests
- Code structure refactoring

---

## Migration Guides

### Upgrading to v2.1.0
No breaking changes. Enhanced observability is backward compatible.

### Upgrading to v2.0.x
- Findings now type-safe (Finding objects normalized to dicts)
- Empty location findings preserved (not deduplicated)
- Prompt injection protection enabled by default

### Upgrading to v1.6.0+
- New CLI structure (`warden scan` replaces old commands)
- SARIF report format standardized
- Smart caching enabled by default

---

## Statistics

- **Total Releases**: 26 versions
- **Latest Stable**: v2.1.0
- **Test Coverage**: 36+ tests for critical paths
- **Supported Python**: 3.10, 3.11, 3.12, 3.13
- **Architecture**: Async-first pipeline

---

Generated: 2026-02-17
