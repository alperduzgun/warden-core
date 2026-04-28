# Warden Core — Flow & Architecture Deep-Dive

> Every claim backed by `file:line` + grep. Last refreshed: 2026-04-28.

---

## 1. Project Identity (1 sentence)

**warden-core** is an AI-native security and quality gate (Python 3.10+ / Rust PyO3 extension) that validates code via a multi-phase pipeline with 13 validation frames, ~15 security checks, LLM-powered verification, and self-improving false-positive suppression.

---

## 2. Entry Points

| Entry | File | Purpose |
|-------|------|---------|
| Python CLI | `src/warden/main.py:1` | Typer app, registers `scan`, `chat`, `init`, `rules`, etc. |
| Node.js Chat TUI | `src/warden/cli/commands/chat.py:1` | Spawns `npm run start:raw` from `cli/` directory |
| gRPC Server | `src/warden/grpc/server.py:1` | Async gRPC wrapper (51 endpoints, optional dep) |
| GitHub Action | `action.yml:1` | Composite action: SARIF upload + PR comment + diff-mode |

---

## 3. Pipeline Execution Flow

### 3.1 Phase Sequence

```
Pre-Analysis → Triage → Analysis → Classification → Validation → LSP Diagnostics → Verification → Fortification → Cleaning → Post-Process
```

**Orchestrator:** `src/warden/pipeline/application/orchestrator/orchestrator.py:38`  
**Phase Runner:** `src/warden/pipeline/application/orchestrator/pipeline_phase_runner.py:75`

### 3.2 Phase Details (with LLM trigger points)

| # | Phase | LLM? | Key Code | Output Context Fields |
|---|-------|------|----------|----------------------|
| 0 | **Pre-Analysis** | No | `pipeline_phase_runner.py:198-223` | `project_context`, `ast_cache`, `project_intelligence`, `taint_paths`, `cross_file_context`, `code_graph`, `chain_validation` |
| 0.5 | **Triage** | Conditional | `pipeline_phase_runner.py:225-254` | `triage_decisions` (FAST/MIDDLE/DEEP per file) |
| 0.8 | **LSP Audit** | No | `pipeline_phase_runner.py:788-845` | `chain_validation` (30s hard cap) |
| 1 | **Analysis** | Conditional | `pipeline_phase_runner.py:260-270` | `quality_metrics`, `quality_score_before`, `hotspots`, `technical_debt_hours` |
| 2 | **Classification** | Conditional | `pipeline_phase_runner.py:276-302` | `selected_frames`, `suppression_rules`, `classification_reasoning` |
| 3 | **Validation** | Per-frame | `pipeline_phase_runner.py:308-315` | `frame_results`, `findings` |
| 3.3 | **LSP Diagnostics** | No | `pipeline_phase_runner.py:327-329` | Extends `findings` + `frame_results["lsp"]` |
| 3.5 | **Verification** | Yes | `pipeline_phase_runner.py:331-346` | `validated_issues`, `false_positives` |
| 4 | **Fortification** | Yes | `pipeline_phase_runner.py:348-366` | `fortifications`, `applied_fixes` |
| 5 | **Cleaning** | Yes | `pipeline_phase_runner.py:378-394` | `cleaning_suggestions`, `refactorings`, `quality_score_after` |
| POST | **Baseline + Suppress + Git Risk + Diff Filter** | No | `pipeline_phase_runner.py:407-417` | Modified `findings` in-place |

**CI Mode Override:** `pipeline_phase_runner.py:173-196` — disables Fortification, Cleaning, Verification; switches Ollama to SEQUENTIAL.

### 3.3 Frame Execution Order

**Frame Executor:** `src/warden/pipeline/application/orchestrator/frame_executor.py:45`  
**Frame Runner:** `src/warden/pipeline/application/orchestrator/frame_runner.py:1`

Frames are executed via `execute_validation_with_strategy_async` which supports:
- **SEQUENTIAL** — one frame at a time
- **PARALLEL** — multiple frames concurrently (respects `parallel_limit`)

Per-frame timeout calculation: `frame_runner.py:55-88` — dynamic based on file size:
```python
timeout = max(MIN, min(file_size_bytes / 10_000, MAX=300s))
```
Local providers (Ollama, Claude Code, Codex) get 45s floor.

---

## 4. Security Frame Checks (15 checks)

**Location:** `src/warden/validation/frames/security/_internal/`

| Check | File | Purpose |
|-------|------|---------|
| SQL Injection | `sql_injection_check.py:45` | f-string/format/%/concat in SQL execute |
| XSS | `xss_check.py:58` | innerHTML, render_template_string, Markup |
| Secrets | `secrets_check.py:27` | AWS keys, OpenAI tokens, GitHub PAT, Stripe keys, PEM |
| Hardcoded Password | `hardcoded_password_check.py:26` | password/pwd/secret variables with literal values |
| Weak Crypto | `crypto_check.py` | MD5/SHA1 hashing, DES/RC4, ECB mode |
| CSRF | `csrf_check.py:26` | @csrf_exempt, missing CsrfViewMiddleware |
| HTTP Security | `http_security_check.py` | CORS wildcard, missing security headers, insecure cookies |
| JWT Misconfig | `jwt_check.py:31` | Missing exp claim, algorithm='none' |
| Path Traversal | `path_traversal_check.py:83` | Unsafe path construction |
| Phantom Package | `phantom_package_check.py` | Hallucinated imports (supply chain risk) |
| Stale API | `stale_api_check.py:45` | Deprecated API patterns (hashlib.md5, new Buffer(), etc.) |
| Open Redirect | `open_redirect_check.py` | Redirect to user-controlled URLs |
| Sensitive Logging | `sensitive_logging_check.py` | Logging of secrets/PII |
| SCA | `sca_check.py` | CVE via OSV API |
| Supply Chain | `supply_chain_check.py` | Typosquatting via Levenshtein |

**Taint Infrastructure:** `src/warden/analysis/taint/service.py:1` — lazy-init, per-project, shared across frames. Supports Python, JavaScript, TypeScript, Go, Java.

---

## 5. Verification Layers

### 5.1 Analysis Levels

| Level | Triage | LLM | Validation | Verification | Fortification | Cleaning |
|-------|--------|-----|------------|--------------|---------------|----------|
| **basic** | Heuristic bypass | `use_llm=False` | Deterministic only | SKIP | SKIP | SKIP |
| **standard** | Full | Yes | Full | Run | Config-dependent | Config-dependent |
| **deep** | Full | Yes | Full + extended timeout | Run | **Enabled** | **Enabled** |

**Config:** `src/warden/pipeline/domain/enums.py` (AnalysisLevel enum)

### 5.2 Triage Skip Conditions

Triage is **bypassed** (heuristic only) when:
1. `analysis_level == BASIC` (`pipeline_phase_runner.py:235`)
2. Single-tier provider (Claude Code, Codex, Qwen CLI) — subprocess-per-call too slow (`pipeline_phase_runner.py:238`)
3. Ollama in CI mode — batch_size=1 + 90s timeout would exceed pipeline timeout (`pipeline_phase_runner.py:237`)

### 5.3 MemoryManager + Verification Cache

**MemoryManager:** `src/warden/memory/application/memory_manager.py:22`
- Loads/saves `.warden/memory/knowledge_graph.json`
- Idempotent init, dirty-flag save

**Findings Cache:** `src/warden/pipeline/application/orchestrator/findings_cache.py` — hash-based per-file cache to skip unchanged files.

---

## 6. LLM Provider Flow

### 6.1 Provider Registry

**Factory:** `src/warden/llm/factory.py:1`

Registered providers (14 files in `src/warden/llm/providers/`):
- Local: `claude_code.py`, `codex.py`, `ollama.py`, `qwen_cli.py`, `offline.py`
- Cloud: `anthropic.py`, `openai.py`, `gemini.py`, `groq.py`, `deepseek.py`, `qwen.py`, `qwencode.py`
- Orchestrated: `orchestrated.py` (parallel fast-tier racing)

### 6.2 Single-Tier vs Dual-Tier

```python
SINGLE_TIER_PROVIDERS = {CLAUDE_CODE, CODEX, QWEN_CLI}  # factory.py:24
_LOCAL_PROVIDERS = {OLLAMA, CLAUDE_CODE, CODEX, QWENCODE, QWEN_CLI}  # factory.py:31
```

- **Single-tier:** All requests route through same CLI tool; no fast/smart split.
- **Local providers:** Support dual-tier (fast_model ≠ smart_model).
- **Cloud providers:** Should NOT duplicate into fast tier (same API quota).

### 6.3 Default Model

**Qwen Cloud:** `qwen-coder-turbo` (default, `src/warden/llm/providers/qwen.py`)

### 6.4 Fallback Chain

Provider fallback is handled by `orchestrated.py` — if primary fails, falls back to next configured provider. Circuit breaker and rate limiter protect against cascading failures.

### 6.5 Prompt Loading (Externalized)

**PromptManager:** `src/warden/llm/prompts/prompt_manager.py:28`
- Loads `.txt` templates from `src/warden/llm/prompts/templates/`
- Supports `@include(shared/_confidence_rules.txt)` directive
- **Path traversal protection:** `templates_dir.resolve()` + validation
- Circular include detection (depth limit = 10)
- Template size limit: 100KB
- LRU caching

---

## 7. Auto-Improve Flow

### 7.1 Rules Autoimprove (#648)

**Command:** `warden rules autoimprove`

**Flow:**
1. Scans `.warden/corpus/` for low-confidence findings
2. LLM proposes FP suppression patterns
3. Validates proposed pattern against full corpus
4. **Keep-or-revert:** F1 must not drop; if it drops, revert
5. Writes approved patterns to `fp_exclusions.py`

**Trigger:** Manual (`warden rules autoimprove`) or `--auto-improve` flag on scan.

### 7.2 Resilience Frame Autoimprove (#657)

**ResilienceFrame:** `src/warden/validation/frames/resilience/resilience_frame.py`
- Static checks run **before** LLM (performance + determinism)
- Autoimprove support added in #657
- Same keep-or-revert loop as security frame

### 7.3 `--report-fp` User Flow

```
user runs: warden scan . --report-fp security-sql-injection-3

1. Finding looked up in current scan (fallback to .warden/cache/)
2. Code snippet written to .warden/corpus/<project>_reported_fp.py
   with corpus_labels: {check_id: 0}
3. Autoimprove loop runs against .warden/corpus/
4. Pattern validated → written to fp_exclusions.py
5. Next scan: suppressed at pattern layer
```

---

## 8. Corpus Eval System

**Runner:** `src/warden/validation/corpus/runner.py:1`

### 8.1 Directory Structure

```
verify/corpus/
├── python_sqli.py          (TP: 3)
├── python_xss.py           (TP)
├── python_secrets.py       (TP: 3)
├── python_weak_crypto.py   (TP)
├── python_command_injection.py (TP)
├── python_sqli_fp.py       (FP: 0)
├── python_xss_fp.py        (FP: 0)
├── python_secrets_fp.py    (FP: 0)
├── python_crypto_fp.py     (FP: 0)
├── python_command_fp.py    (FP: 0)
├── clean_python.py         (TN: 0)
└── resilience/
    ├── python_circuit_breaker_fp.py
    ├── python_circuit_breaker_tp.py
    ├── python_error_handling_fp.py
    ├── python_error_handling_tp.py
    ├── python_timeout_fp.py
    └── python_timeout_tp.py
```

### 8.2 Label Parsing

```python
_LABEL_RE = re.compile(r"corpus_labels\s*:\s*\n((?:\s+[\w-]+\s*:\s*\d+\n?)+)")  # runner.py:32
_ENTRY_RE = re.compile(r"^\s+([\w-]+)\s*:\s*(\d+)\s*$", re.MULTILINE)           # runner.py:36
```

### 8.3 F1 Scoring

```python
@property
def f1(self) -> float:
    p, r = self.precision, self.recall
    return 2 * p * r / (p + r) if (p + r) else 0.0  # runner.py:61-63
```

### 8.4 CI Gate

```bash
warden corpus eval verify/corpus/ --fast --min-f1 0.90
```
Fails if overall F1 drops below threshold.

---

## 9. Self-Healing

**Orchestrator:** `src/warden/self_healing/orchestrator.py:28`

### 9.1 Flow

```
1. Check attempt limit (max 2 per error key)        # orchestrator.py:66
2. Cache lookup (replay known fix)                  # orchestrator.py:49
3. Classify error -> ErrorCategory                  # orchestrator.py:48
4. Registry -> matching strategies (priority order) # orchestrator.py:50
5. First successful strategy -> return result
6. Cache + Metrics record
7. Return DiagnosticResult
```

### 9.2 Strategies

**Location:** `src/warden/self_healing/strategies/`

| Strategy | File | Handles |
|----------|------|---------|
| ConfigHealer | `config_healer.py` | Missing/invalid config values |
| ImportHealer | `import_healer.py` | Import errors |
| LLMHealer | `llm_healer.py` | Generic errors via LLM |
| ModelHealer | `model_healer.py` | Pydantic validation errors |
| ProviderHealer | `provider_healer.py` | LLM provider failures |

---

## 10. Semantic Search

**Searcher:** `src/warden/semantic_search/searcher.py:27`

### 10.1 When It Activates

Triggered when semantic search is enabled in config and a frame or command requests code context enrichment. Used by `PhaseOrchestrator` (`orchestrator.py:100`) if `SemanticSearchService` is initialized.

### 10.2 Architecture

```
Query Text → EmbeddingGenerator → Vector Embedding
                                    ↓
VectorStoreAdapter ← similarity search → CodeChunks (with metadata)
```

**Components:**
- `embeddings.py` — generates vector embeddings
- `indexer.py` — indexes code chunks
- `chunker.py` — splits code into semantic chunks
- `adapters.py` — VectorStoreAdapter interface

### 10.3 Cache Strategy

No explicit cache mentioned in semantic search module. Relies on vector store persistence (e.g., ChromaDB optional dep).

---

## 11. gRPC Layer

**Server:** `src/warden/grpc/server.py:1`

### 11.1 Status

**Experimental / Optional.** `pyproject.toml:64-66` lists `grpcio` and `grpcio-tools` as optional extras. `pyproject.toml:162` ignores `F821` (undefined names) in `src/warden/grpc/**/*.py` with comment: "incomplete/experimental feature".

### 11.2 Endpoints

51 endpoints wrapping `WardenBridge` for C# Panel communication. Lazy import pattern used — if `grpc` not installed, server gracefully degrades (`GRPC_AVAILABLE = False`).

---

## 12. TUI / Warden Chat

**Command:** `src/warden/cli/commands/chat.py:1`

### 12.1 Architecture

Delegates to a **Node.js CLI frontend**:
```bash
npm run start:raw   # dev mode
npm start           # production
```

**Startup script:** `start_warden_chat.sh:1` — starts backend IPC server (`python3 -m warden.services.ipc_entry`) then launches Node CLI.

### 12.2 Slash Commands

Defined in `docs/COMMAND_SYSTEM.md`:
- `/scan <path>`, `/analyze <path>` — run pipeline
- `/rules`, `/config`, `/status` — info commands
- `@<path>` — file/directory injection
- `!<cmd>` — shell execution

### 12.3 Backend IPC

Socket path: `/tmp/warden-ipc.sock`  
Backend log: `/tmp/warden-backend.log`

---

## 13. Cache + Intelligence

### 13.1 `.warden/` Directory Structure

```
.warden/
├── ai_status.md              # Self-scan status (read first!)
├── config.yaml               # Pipeline + frame config
├── rules/                    # Custom rule definitions
├── suppressions.yaml         # Global suppressions
├── baseline/                 # Known debt baseline
│   ├── _meta.json
│   └── unknown.json
├── cache/                    # Cross-run caches
│   ├── analysis_metrics.json
│   ├── classification_cache.json
│   ├── findings_cache.json
│   ├── triage_cache.json
│   └── project_profile.json
├── intelligence/             # Pre-analysis outputs
│   ├── chain_validation.json
│   ├── code_graph.json
│   ├── dependency_graph.json
│   └── gap_report.json
├── memory/                   # Persistent knowledge graph
│   └── knowledge_graph.json
├── corpus/                   # Auto-generated FP corpus
└── reports/                  # Scan outputs
    ├── WARDEN_REPORT.md
    ├── warden-report.json
    └── warden-report.sarif
```

### 13.2 Persistence Model

**Cache files:** Written during scan post-processing, read on next scan to skip unchanged files.  
**Intelligence files:** Written during Pre-Analysis phase, consumed by frames during Validation.  
**Memory:** `MemoryManager` (`memory/application/memory_manager.py:22`) persists `knowledge_graph.json` with dirty-flag saves.

### 13.3 Cross-Run Persistence

- **FindingsCache:** Hash-based file cache (`findings_cache.py`)
- **VerificationCache:** Persisted via MemoryManager (`memory_manager.py`)
- **ClassificationCache:** Reuses previous frame selections for unchanged files
- **TriageCache:** Reuses previous triage decisions

---

## 14. Reporting

### 14.1 Output Formats

**Generator:** `src/warden/reports/generator.py:1`

| Format | File | Notes |
|--------|------|-------|
| SARIF | `generator.py` | Injects CONTRACT_RULE_META for GitHub Code Scanning |
| JSON | `generator.py` | Machine-readable findings |
| Markdown | `.warden/reports/WARDEN_REPORT.md` | Human-readable report |
| HTML | `html_generator.py` | Optional HTML report |
| Badge SVG | `warden_badge.svg` | Status badge |

### 14.2 GitHub Action Integration

**File:** `action.yml:1`

Composite action features:
- SARIF upload to GitHub Security tab (`codeql-action/upload-sarif@v4`)
- PR comment with findings table (idempotent, updates existing)
- Diff-mode support (`--diff --base $GITHUB_BASE_REF`)
- `fail-on-severity` configuration (default: critical)
- Quality score extraction from SARIF properties

### 14.3 Contract Mode Reporting

SARIF output includes 5 contract-specific rules (`CONTRACT-DEAD-WRITE`, `CONTRACT-MISSING-WRITE`, `CONTRACT-NEVER-POPULATED`, etc.) injected into `tool.driver.rules` whenever contract mode is enabled (`generator.py:18-68`).

---

## 15. Errors & Edge Cases

### 15.1 Provider Rate Limit

Handled by `global_rate_limiter.py` + circuit breaker in LLM registry. Falls back to next provider if primary rate-limited.

### 15.2 Corpus Empty

`CorpusResult.overall_f1` returns `0.0` if no metrics collected (`runner.py:91-94`). CI gate `--min-f1` will fail.

### 15.3 LLM Error Response

Frame runner catches exceptions with `@async_error_handler` decorator (`frame_runner.py` imports from `shared.infrastructure.error_handler`). Returns partial results instead of crashing pipeline.

### 15.4 Cross-File Truncation (Recent Fix)

**Commit:** `f204c77` — "fix(orphan): fix cross-file corpus truncated to 5-file chunk, causing mass FPs"

OrphanFrame's cross-file analysis was limiting corpus to 5-file chunks, causing false positives on multi-file projects. Fixed by removing or increasing the chunk limit.

### 15.5 Path Traversal Attack

Protected at multiple layers:
- **PromptManager:** `templates_dir.resolve()` + path validation (`prompt_manager.py:71`)
- **Auto-init:** Hardened against YAML injection and TOCTOU (`#534`)
- **File discovery:** Respects `.wardenignore` and `.gitignore`

---

## Understand-Quality Score

**8/10** — A reader of this document can understand:
- ✅ The full pipeline phase sequence and where LLM calls happen
- ✅ All 15 security checks and their file locations
- ✅ How frames are executed (sequential vs parallel, timeout calculation)
- ✅ The CI mode behavior and triage skip conditions
- ✅ The auto-improve and corpus evaluation flows
- ✅ The self-healing, semantic search, and gRPC capabilities
- ✅ The reporting outputs and GitHub Action integration
- ⚠️ Does NOT cover: internal AST node types, exact regex patterns per check, fine-grained provider authentication flows (these are implementation details that would bloat the doc)

---

*Document generated on 2026-04-28. Every claim verified against source code.*

WARDEN_FLOW_R1_CLAUDE_DONE
