# Warden Pipeline & Frame Reference

> Complete documentation of every phase, frame, and module.
> This is the source of truth for verify suite's expected.yaml.

---

## Pipeline Phases (Execution Order)

| # | Phase | Enable Flag | Default | Skip When | LLM? | Input | Output (Context Fields) |
|---|-------|-------------|---------|-----------|------|-------|------------------------|
| 0 | **Pre-Analysis** | `enable_pre_analysis` | True | flag=False | No | `code_files` | `project_context`, `file_contexts`, `ast_cache`, `project_intelligence`, `taint_paths` |
| 0.5 | **Triage** | automatic | — | `analysis_level=BASIC` OR single-tier provider OR Ollama+CI | Conditional | `code_files` + AST cache | `triage_decisions` (per-file lane: FAST/MIDDLE/DEEP) |
| 0.8 | **LSP Audit** | `enable_lsp_audit` | True | LSP unavailable | No | `code_files` + code_graph | `chain_validation` (30s hard cap) |
| 1 | **Analysis** | `enable_analysis` | True | flag=False | Conditional | `code_files` + project context | `quality_metrics`, `quality_score_before`, `hotspots`, `quick_wins`, `technical_debt_hours` |
| 2 | **Classification** | **ALWAYS** | True | manual frame override via CLI | Conditional | `code_files` + metrics | `selected_frames`, `suppression_rules`, `classification_reasoning` |
| 3 | **Validation** | `enable_validation` | True | flag=False | Per-frame | `code_files` + `selected_frames` | `frame_results`, `findings` |
| 3.3 | **LSP Diagnostics** | automatic | — | LSP unavailable | No | `code_files` | extends `findings` + `frame_results["lsp"]` |
| 3.5 | **Verification** | `enable_issue_validation` | True | CI mode | Yes | `findings` | modifies `findings` in-place, sets `validated_issues`, `false_positives` |
| 4 | **Fortification** | `enable_fortification` | **False** | CI mode OR flag=False | Yes | `validated_issues` + `code_files` | `fortifications`, `applied_fixes`, `security_improvements` |
| 5 | **Cleaning** | `enable_cleaning` | **False** | CI mode OR flag=False | Yes | `code_files` + metrics | `cleaning_suggestions`, `refactorings`, `quality_score_after` |
| POST | **Baseline Filter** | automatic | — | never | No | `findings` | modifies `findings` in-place (suppresses known debt) |

### Analysis Level Impact

| Level | Triage | Classification LLM | Validation | Verification | Fortification | Cleaning |
|-------|--------|-------------------|------------|--------------|---------------|---------|
| **basic** | SKIP | Heuristic only | Deterministic checks only | SKIP | SKIP | SKIP |
| **standard** | Run | Heuristic + LLM | Full (det. + LLM) | Run | Config-dependent | Config-dependent |
| **deep** | Run | Heuristic + LLM | Full + extended timeout | Run | **Enabled** | **Enabled** |

### CI Mode Overrides

CI mode (`--ci`) auto-disables: Fortification, Cleaning, Verification (3 LLM-heavy phases).

---

## Validation Frames (13 Total)

### Core Frames (Exported via `__init__.py`)

| # | Frame ID | Class | Priority | Scope | Blocker | Deterministic? | LLM? | Mixin(s) | What It Detects |
|---|----------|-------|----------|-------|---------|---------------|------|----------|----------------|
| 1 | `security` | SecurityFrame | CRITICAL | FILE | Yes | Hybrid | Yes | TaintAware, BatchExecutable, CodeGraphAware | SQL injection, XSS, hardcoded secrets, CSRF, weak crypto, JWT misconfig, command injection, path traversal. 8 deterministic checks + taint analysis + LLM batch verification. |
| 2 | `antipattern` | AntiPatternFrame | HIGH | FILE | Yes | **Yes** | No | — | Empty catch blocks, god classes (500+ lines), debug output (print/console.log), TODO/FIXME markers, generic exception throwing. Universal AST (50+ languages). |
| 3 | `architecture` | ArchitectureFrame | HIGH | PROJECT | No | **Yes** (opt-in LLM) | Optional | CodeGraphAware | Broken imports, circular dependencies, orphan files, unreachable code, missing mixin implementations. Uses GapReport from code graph. |
| 4 | `orphan` | OrphanFrame | MEDIUM | FILE | No | **Yes** (opt-in LLM) | Optional | BatchExecutable, ProjectContextAware, LSPAware | Unused imports, uncalled functions, unused classes, unreachable code. Optional LLM filtering for accuracy. |
| 5 | `resilience` | ResilienceFrame | HIGH | FILE | No | No | **Yes** | TaintAware, ChunkingAware | Missing error handling, no timeout patterns, no circuit breaker, no retry logic, missing cleanup on failure. External dependency failure simulation. |
| 6 | `fuzz` | FuzzFrame | MEDIUM | FILE | No | No | **Yes** | TaintAware, ChunkingAware | Missing null/None checks, empty string validation gaps, boundary value handling, type validation gaps, special character handling. |
| 7 | `property` | PropertyFrame | HIGH | FILE | No | No | **Yes** | BatchExecutable | Missing precondition/postcondition checks, invariant violations, state machine errors, mathematical edge cases. |
| 8 | `gitchanges` | GitChangesFrame | MEDIUM | FILE | No | **Yes** | No | — | Changed lines in git diff. PR-focused: only analyzes new/modified code. All languages. |
| 9 | `spec` | SpecFrame | LOW | PROJECT | No | Partial | Optional | Cleanable, ProjectContextAware | API consumer vs provider contract mismatches. Multi-platform contract extraction. Monorepo support. |

### Contract Mode Frames (Not Exported, `contract_mode=True` Required)

| # | Frame ID | Class | Priority | Scope | Blocker | Deterministic? | LLM? | Mixin(s) | What It Detects |
|---|----------|-------|----------|-------|---------|---------------|------|----------|----------------|
| 10 | `async_race` | AsyncRaceFrame | MEDIUM | FILE | No | No | **Yes** | — | Shared mutable state accessed without locks in asyncio.gather/create_task. Python only. |
| 11 | `dead_data` | DeadDataFrame | LOW | FILE | No | **Yes** | No | DataFlowAware | DEAD_WRITE (written never read), MISSING_WRITE (read never written), NEVER_POPULATED. Uses DDG. |
| 12 | `protocol_breach` | ProtocolBreachFrame | MEDIUM | FILE | No | **Yes** | No | — | Frames with TaintAware/DataFlowAware mixins but injection missing in frame_runner. |
| 13 | `stale_sync` | StaleSyncFrame | MEDIUM | FILE | No | No | **Yes** | DataFlowAware | STALE_SYNC: logically coupled fields updated in some paths but not others. DDG co-write analysis + LLM verdict. |

### Mixin Reference

| Mixin | Setter | Injected By | Purpose |
|-------|--------|-------------|---------|
| TaintAware | `set_taint_paths(dict)` | Pre-Analysis (Phase 0) | Source-to-sink data flow paths |
| DataFlowAware | `set_data_dependency_graph(DDG)` | Pre-Analysis (contract_mode) | Data dependency graph |
| CodeGraphAware | `set_code_graph(graph, gap_report)` | Pre-Analysis (Phase 0.7) | Code structure + gap analysis |
| LSPAware | `set_lsp_context(ctx)` | LSP Audit (Phase 0.8) | Language server cross-file context |
| ProjectContextAware | `set_project_context(ctx)` | Pre-Analysis | Project-wide metadata |
| BatchExecutable | `execute_batch_async(files)` | Validation (Phase 3) | Multi-file batch processing |
| ChunkingAware | (config-based) | Validation (Phase 3) | Large file chunked processing |

---

## SecurityFrame Detail (8 Deterministic Checks)

| Check | Class | CWE | Severity | LLM? | What It Detects |
|-------|-------|-----|----------|------|----------------|
| SQL Injection | SQLInjectionCheck | CWE-89 | CRITICAL | No | f-string/format/%/concat in SQL execute |
| XSS | XSSCheck | CWE-79 | HIGH | No | innerHTML, render_template_string, Markup |
| Secrets | SecretsCheck | CWE-798 | CRITICAL | No | AWS keys, OpenAI tokens, GitHub PAT, Stripe keys, PEM |
| Hardcoded Password | HardcodedPasswordCheck | CWE-798 | CRITICAL | No | password/pwd/secret variables with literal values |
| HTTP Security | HTTPSecurityCheck | CWE-614 | HIGH | No | CORS wildcard, missing security headers, insecure cookies |
| CSRF | CSRFCheck | CWE-352 | HIGH | No | @csrf_exempt, missing CsrfViewMiddleware |
| Weak Crypto | WeakCryptoCheck | CWE-327/328 | HIGH | No | MD5/SHA1 hashing, DES/RC4, ECB mode |
| JWT Misconfig | JWTMisconfigCheck | CWE-613 | HIGH | No | Missing exp claim, algorithm='none' |

Plus: **SCA Check** (CVE via OSV API), **Supply Chain Check** (typosquatting via Levenshtein)

---

## Taint Analysis

### Supported Languages & Strategies

| Language | Strategy | Method | Passes | Interprocedural? |
|----------|----------|--------|--------|-----------------|
| Python | AST-based | `PythonTaintStrategy` | 5-pass fixed-point | Yes (single-file call graph) |
| JavaScript | Regex-based | `JsTaintStrategy` | 5-pass propagation | No |
| TypeScript | Regex-based | `JsTaintStrategy` | 5-pass propagation | No |
| Go | Regex-based | `GoTaintStrategy` | 5-pass propagation | No |
| Java | Regex-based | `JavaTaintStrategy` | 5-pass propagation | No |

### Sink Types

| Sink Type | CWE | Example Sinks |
|-----------|-----|---------------|
| SQL-value | CWE-89 | cursor.execute, db.query, sequelize.query, knex.raw |
| CMD-argument | CWE-78 | os.system, subprocess.run, exec, spawn |
| HTML-content | CWE-79 | innerHTML, render_template_string, Markup, document.write |
| CODE-execution | CWE-94 | eval, compile, Function, setTimeout |
| FILE-path | CWE-22 | open, pathlib.Path, fs.readFile |
| HTTP-request | CWE-918 | requests.get, urllib.urlopen, httpx, aiohttp |
| LOG-output | CWE-532 | logging.info, print, console.log |

### Confidence Hierarchy

| Source | Confidence | Description |
|--------|-----------|-------------|
| YAML model pack (flask.yaml, django.yaml) | 0.99 | Framework-specific catalog |
| Hardcoded constants (TAINT_SOURCES/SINKS) | 0.90 | Built-in patterns |
| Signal inference (signals.yaml heuristics) | 0.60-0.70 | Heuristic fallback |
| Propagated taint | 0.75 | From function call chain |
| Sanitized flow | ×0.3 penalty | Confidence multiplied |

### Threshold: `confidence >= 0.80` → HIGH severity + is_blocker

---

## Classification Module

### 3-Layer Pipeline

| Layer | Class | Condition | Cost | Duration |
|-------|-------|-----------|------|----------|
| 1. Cache | ClassificationCache | SHA256(files+frames+config) match | 0 tokens | <1ms |
| 2. Heuristic | HeuristicClassifier | Always runs | 0 tokens | 2-100ms |
| 3. LLM | LLMClassificationPhase | `confidence < SKIP_LLM_THRESHOLD (0.88)` | 500-6000 tokens | 8-12s |

Output is **union** of heuristic + LLM (LLM cannot reduce below heuristic floor).

### Heuristic Pattern Groups

| Group | Count | Triggers Frame | Example Patterns |
|-------|-------|---------------|-----------------|
| (always) | — | security | (unconditional) |
| RESILIENCE | 15 | resilience | requests, httpx, aiohttp, grpc, redis, celery, kafka, boto, sqlalchemy, flask, django, fastapi |
| FUZZ | 8 | fuzz | argparse, click, typer, json.loads, yaml.safe_load, xml.etree, pickle.loads |
| PROPERTY | 6 | property | @dataclass, @property, typing, pydantic, TypeVar, Protocol |
| ANTIPATTERN | 5 | antipattern | global, exec(), eval(), __class__, metaclass= |
| SECURITY_SENSITIVE | 13 | (caps confidence) | password, secret, token, api_key, auth, login, jwt, session, sql, subprocess |
| (multi-file) | — | architecture | file_count > 5 |
| (functions/classes) | — | orphan | `def ` or `class ` in combined content |

---

## Report Generation

| Format | Method | Working? | Notes |
|--------|--------|----------|-------|
| JSON | `generate_json_report()` | ✅ | Atomic write, path sanitization |
| SARIF 2.1.0 | `generate_sarif_report()` | ✅ | GitHub Code Scanning compatible, 5 contract rules |
| HTML | `generate_html_report()` | ✅ | Delegated to HtmlReportGenerator |
| PDF | `generate_pdf_report()` | ⚠️ | Requires WeasyPrint (fails in CI without system libs) |
| JUnit XML | `generate_junit_report()` | ✅ | Atomic write, TestCase/TestSuite structure |
| Markdown | `generate_markdown_report()` | ✅ | Human-readable, finding links |
| SVG Badge | `generate_svg_badge()` | ✅ | HMAC-SHA256 signed, gradient colors |
| Tech Debt | `TechDebtGenerator` | ✅ | `.warden/TECH_DEBT.md` |

---

## Cache Layers

| Cache | Key Format | TTL | Max Entries | Disk Location | Eviction |
|-------|-----------|-----|-------------|---------------|----------|
| Findings | `frame_id:file_path:SHA256(content)[:16]` | LRU | 10,000 | `.warden/cache/findings_cache.json` | Oldest 20% |
| Triage | `file_path:SHA256(content)[:16]` | LRU | 5,000 | `.warden/cache/triage_cache.json` | Oldest 20% |
| Classification | `SHA256(files+frames+config)` | 7 days | 500 | `.warden/cache/classification_cache.json` | FIFO oldest |
| AST (in-memory) | file_path | Session | 500 | — (memory only) | LRU |

---

## Post-Processing Pipeline

| Step | Module | Purpose | LLM? |
|------|--------|---------|------|
| 1. Deduplication | ResultAggregator | `(location, rule_type)` key, severity ranking | No |
| 2. Verification | FindingVerifierService | 3-stage: heuristic → cache → LLM batch (max 10/batch, 4K tokens) | Yes |
| 3. Baseline | FindingsPostProcessor | `rule_id:path` key match against `.warden/baseline.json` | No |
| 4. State Consistency | FindingsPostProcessor | Auto-correct frame status if all findings filtered | No |

---

## Fortification Module

| Component | Purpose | LLM? |
|-----------|---------|------|
| FortificationPhase | Orchestrates fix generation | Yes |
| LLMFortificationGenerator | Context-aware patch generation | Yes |
| ErrorHandlingFortifier | Try-catch improvements | Yes |
| InputValidationFortifier | Schema validation, sanitization | Yes |
| ResourceDisposalFortifier | File/connection cleanup | Yes |

**Policy:** Read-only tool. Never modifies source code directly. Generates suggestions only.
