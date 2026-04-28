# Warden Core — Context Load (2026-04-28)

> Zero code, zero action. Read-only project recognition summary.

---

## 1. Project Identity

| Field | Value |
|-------|-------|
| **Name** | Warden Core (warden-core) |
| **Version** | 3.0.0 (pyproject.toml) / 2.6.0 (CHANGELOG latest) |
| **Purpose** | AI-native security & quality gate that validates LLM-generated code before it enters a codebase |
| **Tagline** | "AI writes the code. Warden guards the production." |
| **Target User** | Developers using AI coding assistants (Claude, GPT-4, etc.), DevOps/CI-CD pipelines |
| **License** | Apache-2.0 |
| **Status** | Beta |
| **Repository** | `git@github.com:alperduzgun/warden-core.git` |

---

## 2. Stack

| Layer | Technology |
|-------|------------|
| **Language** | Python 3.10+ (primary), Rust (extension via PyO3) |
| **CLI Framework** | Typer |
| **TUI** | Rich + Textual |
| **AST Parsing** | tree-sitter (Python, JS/TS, Go, Java, Kotlin, Dart) |
| **Data Validation** | Pydantic v2 |
| **HTTP** | httpx, requests |
| **LLM Integration** | openai SDK, custom providers (Anthropic, Gemini, Groq, DeepSeek, Qwen Cloud, Ollama, Claude Code CLI, Codex CLI) |
| **Testing** | pytest, pytest-asyncio, pytest-cov, pytest-timeout |
| **Lint/Format** | ruff (replaces black+isort) |
| **Type Checking** | mypy 1.10, pyright |
| **Build** | setuptools + setuptools-rust |
| **Rust Crate** | `warden_core_rust` (cdylib) — regex, sha2, rayon, ignore, memmap2 |

---

## 3. Architecture Summary

### Pipeline Phases (Execution Order)

```
Phase 0   PRE-ANALYSIS    → project_context, ast_cache, taint_paths
Phase 0.5 TRIAGE          → per-file lane: FAST / MIDDLE / DEEP
Phase 0.8 LSP AUDIT       → chain_validation (30s cap)
Phase 1   ANALYSIS        → quality_metrics, hotspots, technical_debt
Phase 2   CLASSIFICATION  → selected_frames, suppression_rules
Phase 3   VALIDATION      → frame_results, findings (13+ frames)
Phase 3.3 LSP DIAGNOSTICS → extends findings
Phase 3.5 VERIFICATION    → validated_issues, false_positives (LLM)
Phase 4   FORTIFICATION   → applied_fixes, security_improvements (LLM)
Phase 5   CLEANING        → refactorings, quality_score_after (LLM)
POST      BASELINE FILTER → suppress known debt
```

### Validation Frames (13 Total)

| Frame | ID | Priority | Deterministic | LLM | Scope | Notes |
|-------|----|----------|---------------|-----|-------|-------|
| Security | `security` | CRITICAL | Hybrid | Yes | FILE | 8 checks + taint analysis. SQLi, XSS, secrets, CSRF, weak crypto, JWT, command injection, path traversal |
| AntiPattern | `antipattern` | HIGH | Yes | No | FILE | Empty catches, god classes, debug output, TODO/FIXME markers |
| Architecture | `architecture` | HIGH | Yes | Optional | PROJECT | Broken imports, circular deps, orphan files |
| Orphan | `orphan` | MEDIUM | Yes | Optional | FILE | Unused imports, uncalled functions, unreachable code |
| Resilience | `resilience` | HIGH | No | Yes | FILE | Missing error handling, timeouts, circuit breakers, retry logic |
| Fuzz | `fuzz` | MEDIUM | No | Yes | FILE | Null checks, boundary values, type validation gaps |
| Property | `property` | HIGH | No | Yes | FILE | Preconditions, invariants, state machine errors |
| GitChanges | `gitchanges` | MEDIUM | Yes | No | FILE | Changed lines in git diff |
| Spec | `spec` | LOW | Partial | Optional | PROJECT | API consumer vs provider contract mismatch |
| AsyncRace | `async_race` | MEDIUM | No | Yes | FILE | Contract mode only. Shared mutable state in asyncio |
| DeadData | `dead_data` | LOW | Yes | No | FILE | Contract mode only. Dead writes, missing writes |
| ProtocolBreach | `protocol_breach` | MEDIUM | Yes | No | FILE | Contract mode only. Missing mixin injections |
| StaleSync | `stale_sync` | MEDIUM | No | Yes | FILE | Contract mode only. Logically coupled fields not co-updated |

### Key Services

- **Taint Analysis** — Shared Pre-Analysis service. Source-to-sink tracking. Python (AST), JS/TS/Go/Java (regex 3-pass). Consumed by SecurityFrame, FuzzFrame, ResilienceFrame.
- **Code Graph** — Import graph, gap report. Injected to CodeGraphAware frames.
- **LLM Router** — Provider registry with circuit breaker, rate limiting, parallel fast-tier execution.
- **Caching** — File-level hash cache, result cache, verification cache, classification cache, triage cache.
- **Corpus Evaluation** — FP/TP labeled test files under `verify/corpus/`. F1 scoring per check.

### Data Flow

1. User runs `warden scan <path>`
2. Pre-Analysis detects stack, builds AST cache, computes taint paths
3. Triage assigns per-file analysis depth (FAST → skip LLM, DEEP → full)
4. Classification selects relevant frames per file
5. Validation runs frames (deterministic first, LLM batch second)
6. Verification re-checks findings with LLM (unless CI mode)
7. Baseline filter suppresses known issues
8. Reports generated: Markdown, JSON, SARIF

---

## 4. Recent Activity (Last 30 Days)

### Burst Period: 2026-04-06 → 2026-04-08
~35 commits in 3 days. Heavy feature delivery + Copilot review cycles.

**Major Features Delivered:**
- **#648 / #657 — Autoimprove FP Reduction**
  - `--auto-improve` flag: auto FP corpus generation from low-confidence findings
  - `--report-fp` flag: instant false-positive suppression via finding ID
  - `warden rules autoimprove`: keep-or-revert loop for FP reduction
  - ResilienceFrame now supported by autoimprove (static checks run before LLM)
- **#649 — Externalized LLM Prompts**
  - LLM prompts moved to editable `.md` files (not hardcoded strings)
  - Prompt loader with path-traversal guard, package-data inclusion
- **#647 / #651 — Corpus Evaluation System**
  - Frame-agnostic corpus runner (`warden corpus eval`)
  - FP/TP labeled corpus files with F1 scoring
  - CI gate support (`--min-f1 0.90`)
- **#534 — Auto-Init**
  - `warden scan` auto-creates minimal `.warden/` on first run
  - Hardened against YAML injection, TOCTOU, path traversal
- **#595 — Verification Cache Persistence**
  - MemoryManager wired to persist verification cache across runs
- **Security Hardening (#638-642)**
  - Path confinement, atomic writes, idempotent init, regex validation
  - Confidence scoring for HardcodedPassword / WeakCrypto
  - XSS / PathTraversal context-aware checks

### Provider Additions
- Qwen (Alibaba Cloud DashScope) provider added
- Renamed QWEN → QWEN_CLOUD for clarity
- Default model: `qwen-coder-turbo`

### Quiet Period
- **Last 7 days:** Zero commits (2026-04-08 was the last activity day)

---

## 5. Active Line

| Field | Value |
|-------|-------|
| **Current Branch** | `feat/resilience-autoimprove-657` |
| **Tracking** | `origin/feat/resilience-autoimprove-657` |
| **Branch Status** | Up to date |
| **Working Tree** | Dirty — `.warden/` cache/intelligence files modified, `warden_badge.svg` modified, untracked `.qwen/` and `examples/demo-scan/` |
| **Open PR** | #660 — `fix(antipattern): regex fallback when AST yields no violations` (on this branch) |
| **Latest Commit** | `f204c77` — "fix(orphan): fix cross-file corpus truncated to 5-file chunk, causing mass FPs" |

**What this branch does:**
- Adds autoimprove support for ResilienceFrame (previously only SecurityFrame supported)
- Wires static checks to run **before** LLM in ResilienceFrame (performance + determinism)
- Fixes AST node type mismatch that caused 0 findings in pipeline scans
- Applies Copilot review fixes (singleton registry, pre-split lines, frame_id, regex fix)

---

## 6. Open Issues & PRs

### Open Issues (20 total, top relevant)

| # | Title | Labels | Priority |
|---|-------|--------|----------|
| 657 | feat(rules): autoimprove FP reduction support for resilience frame | enhancement | — |
| 650 | feat(config): security_research.md — human strategy file for autonomous scan improvement | enhancement | — |
| 628 | feat(resilience): LLM graceful degradation — context reduction on prompt-too-long | enhancement, P2 | P2 |
| 627 | feat(fortification): `warden fix --auto-pr` — auto-create GitHub PR from patches | enhancement, P2 | P2 |
| 626 | feat(init): auto-install git hooks during `warden init` | enhancement, P2 | P2 |
| 597 | feat(llm): multi-pass analysis with attacker/defender perspectives | enhancement, P2 | P2 |
| 596 | feat(llm): vulnerability pattern corpus from confirmed findings | enhancement, P2 | P2 |
| 593 | feat(llm): JSON schema enforcement on security analysis prompts | enhancement, P2 | P2 |
| 592 | feat(llm): structural pre-tags for deterministic LLM context | enhancement, P2 | P2 |
| 589 | feat(cross-file): inter-procedural taint propagation via function summaries | enhancement, P2 | P2 |
| 536 | chore(config): 12 PipelineConfig fields not configurable via config.yaml | enhancement, P2 | P2 |
| 506 | feat(action): publish Warden to GitHub Actions Marketplace | enhancement | **P1** |
| 522 | bug(diff): renamed file path mismatch causes findings to be dropped | bug, P2 | P2 |
| 507 | feat(cli): add warden heal command for auto-fix suggestions | enhancement, P2 | P2 |

### Open PRs (6 total)

| # | Title | Branch |
|---|-------|--------|
| 666 | chore(deps): bump mypy 1.20.0 → 1.20.2 | dependabot |
| 665 | chore(deps): bump pytest 8.2.2 → 9.0.3 | dependabot |
| 664 | chore(deps): sentence-transformers <4.0 → <6.0 | dependabot |
| 663 | chore(deps): rich <15.0 → <16.0 | dependabot |
| 661 | chore(ci): bump softprops/action-gh-release 2 → 3 | dependabot |
| 660 | fix(antipattern): regex fallback when AST yields no violations | `feat/resilience-autoimprove-657` |

---

## 7. Notes & Quirks

### Self-Scan Quality
- v2.6.0 achieved **99.5% false-positive reduction** on self-scan: 388 findings → 2 findings.
- Cross-file analysis is production-ready (import graph, value propagation, LLM context enrichment).
- **98%+ detection rate** validated against 53 planted vulnerabilities across 4 real projects.

### Warden Guards Itself
- `.warden/ai_status.md` currently shows **PASS** (0 critical, 0 total issues).
- If status becomes FAIL, agent must read SARIF/JSON reports and fix before proceeding.

### Corpus System
- Located at `verify/corpus/`.
- Files have `corpus_labels:` docstring blocks (e.g., `sql-injection: 3` for TP, `xss: 0` for FP).
- Run: `warden corpus eval verify/corpus/ --fast`
- Key rule: findings with `pattern_confidence < 0.75` are LLM-routed and **not counted** in corpus scoring.

### Configuration
- Project config lives in `.warden/` directory.
- `config.yaml`, `rules/`, `suppressions.yaml`, `baseline/`, `cache/`, `intelligence/`.
- Auto-init on first scan creates minimal `.warden/` scaffold.
- 12 `PipelineConfig` fields are **not yet configurable** via `config.yaml` (issue #536).

### CI Behavior
- `--ci` flag auto-disables: Fortification, Cleaning, Verification (3 LLM-heavy phases).
- `--diff` mode available for incremental PR scans.

### Analysis Levels
- `basic` — skip triage, heuristic classification only, deterministic validation, skip verification/fortification/cleaning.
- `standard` — full pipeline, fortification/cleaning config-dependent.
- `deep` — extended timeout, fortification & cleaning enabled.

### Language Tiers
- **Tier 1 (Full):** Python, JavaScript/TypeScript — AST + taint + security rules.
- **Tier 2 (Standard):** Go, Java — AST + regex taint.
- **Tier 3 (Basic):** Kotlin, Dart — AST only.
- **Tier 4 (Regex):** Swift, C/C++, Ruby, PHP — regex only.

### Rust Extension
- `src/warden_rust/` built via `setuptools-rust`.
- Not a standalone binary; compiled as Python extension module (`cdylib`).
- Used for performance-critical path: file walking, hashing, possibly AST ops.

### MCP & Chat
- MCP (Model Context Protocol) server support exists under `src/warden/mcp/`.
- Interactive chat/TUI available via `warden chat`.
- Slash-command system (`/scan`, `/analyze`, `/rules`, etc.) + `@file` injection + `!shell` execution.

### Development Workflow
- Conventional Commits enforced: `feat(scope):`, `fix(scope):`, `chore:`, `style:`.
- Required before PR: tests pass, `ruff check` clean, formatted code.
- Post-task: run `warden scan --diff` and address findings.

### Turkish Character Support
- Ruff ignores `RUF001`/`RUF002` (ambiguous unicode character in strings/docstrings) because project contains Turkish characters intentionally.

### Branch Hygiene
- Repository has **many** remote branches (~150+) and multiple worktrees.
- Active worktrees: `worktree-agent-a152d24f`, `worktree-agent-a241fb0e`, `worktree-agent-a408d5b6`, `worktree-agent-a5ca0338`, `worktree-agent-aa0ea417`, `worktree-agent-ad831e28`, `worktree-agent-aecd3213`, `worktree-agent-afcbd9d3`.
- Main dev branch: `dev`. Production: `main`.

---

*Context generated on 2026-04-28. No code changes made.*

WCORE_CONTEXT_CLAUDE_DONE
