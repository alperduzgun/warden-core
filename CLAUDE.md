# Project Instructions

Last refreshed: 2026-04-28 (per WCORE-CONSENSUS)

> **AI Session Notes (gitignored — `.notes/`):**
> Detailed runtime flow + architecture analysis, per dual-AI clash consensus 2026-04-28:
> - **Quick reference (~5 min read):** `.notes/WARDEN-FLOW.md` — pipeline phases, frame list, providers, CLI, smart features
> - **Full consensus (660 lines):** `.notes/WARDEN-FLOW-FULL.md` — every claim grep-verified, R2-corrected
>
> These docs capture the runtime flow so future AI sessions don't re-derive it. They are personal notes, NOT in git. If the codebase changes substantially, regenerate via dual clash workflow.

---

## Project Identity

**warden-core** (v3.0.0 in pyproject.toml / v2.6.0 latest CHANGELOG) is an AI-native security and quality gate that validates code — especially LLM-generated code — before it enters a codebase. Target users: individual developers using AI coding assistants and CI/CD pipelines. License: Apache-2.0. Status: Beta.

---

## Stack Snapshot

| Layer | Technology |
|-------|------------|
| Primary language | Python 3.10+ |
| Rust extension | `warden_core_rust` (PyO3 cdylib) — `src/warden_rust/Cargo.toml` |
| CLI framework | Typer |
| TUI | Rich + Textual |
| AST parsing | tree-sitter (Python, JS/TS, Go, Java, Kotlin, Dart) |
| Validation | Pydantic v2 |
| HTTP | httpx, requests |
| LLM integration | openai SDK + custom providers (see Provider List in AGENTS.md) |
| Testing | pytest, pytest-asyncio, pytest-cov, pytest-timeout |
| Lint/format | ruff (primary); black 24.4.2 + isort 5.13.2 still in dev deps |
| Type checks | mypy==1.10.0 (Dependabot PR #666 proposes 1.20.2), pyright |
| Build | setuptools (build-system); setuptools-rust in `setup.py` as optional extension |

---

## Architecture (Short)

Pipeline phases (in order):

```
Pre-Analysis  → Triage (FAST/MIDDLE/DEEP per file) → LSP Audit
Analysis      → Classification → Validation (13 frames)
LSP Diagnostics → Verification (LLM) → Fortification → Cleaning
Baseline Filter (POST)
```

**Validation frames (13):** `security`, `antipattern`, `architecture`, `orphan`, `resilience`, `fuzz`, `property`, `gitchanges`, `spec`, `async_race`, `dead_data`, `protocol_breach`, `stale_sync`. The last four are **Contract Mode only** (`contract_mode=True`).

**SecurityFrame checks:** 15 `*_check.py` files in `src/warden/validation/frames/security/_internal/` — including SQLi, XSS, secrets, hardcoded password, crypto, CSRF, HTTP security, JWT, path traversal, phantom package, stale API, open redirect, sensitive logging, SCA, supply chain — plus taint analysis infrastructure.

**Analysis levels:** `basic` (LLM off, deterministic only), `standard` (full pipeline), `deep` (extended timeout, fortification + cleaning forced on).

**CI mode:** `--ci` disables Fortification, Cleaning, and Verification.

---

## Modules (`src/warden/`)

```
cli/              — Typer CLI entry points
pipeline/         — Phase orchestration and domain models
validation/       — 13 frames + corpus eval + FP exclusions
  frames/         — antipattern, architecture, async_race, dead_data,
                    fuzz, gitchanges, orphan, property, protocol_breach,
                    resilience, security, spec, stale_sync
llm/              — 10+ providers + circuit breaker + prompts
ast/              — tree-sitter registry + language enum
classification/   — heuristic + LLM classification
suppression/      — baseline fingerprint + suppression
memory/           — MemoryManager (scan memory)
self_healing/     — self-repair orchestrator for runtime errors
semantic_search/  — vector similarity search (embeddings, indexer)
benchmark/        — phase duration and LLM call attribution tracking
grpc/             — experimental gRPC server (optional dep)
mcp/              — MCP server integration
lsp/              — Language Server Protocol connection
rules/            — warden rules command set + autoimprove
fortification/    — warden fix — automated patch generation
reports/          — SARIF, JSON, Markdown, HTML output
config/           — PipelineConfig, .warden.yml parse
secrets/          — secret detection infrastructure
shared/           — cross-cutting utilities
```

---

## Commands Snapshot

```bash
# Init project scaffolding
warden init

# Scan (core command)
warden scan .                          # standard scan
warden scan . --diff                   # changed files only
warden scan . --ci                     # CI mode (no LLM-heavy phases)
warden scan . --quick-start            # deterministic only, no LLM
warden scan . --auto-improve           # auto FP corpus generation after scan
warden scan . --report-fp <finding-id> # instant false-positive suppression

# Corpus evaluation
warden corpus eval verify/corpus/ --fast
warden corpus eval verify/corpus/ --fast --min-f1 0.90

# Rules management
warden rules autoimprove               # keep-or-revert FP reduction loop

# Interactive chat/TUI
warden chat
```

---

## Security (Warden)

This project is protected by Warden (AI Code Guardian).
- **Status Check:** Read `.warden/ai_status.md` first.
- **Fail Protocol:** If status is FAIL, read `warden-report.sarif/json` for details. Do not proceed until fixed.
- **Action:** Run `warden scan` to verify fixes.

### Self-Scan Capability

Warden scans itself. Current status: `.warden/ai_status.md` shows **PASS** (0 critical, 0 total issues). v2.6.0 achieved **99.5% false-positive reduction** on self-scan (388 findings → 2).

---

## Corpus Evaluation System

When scan quality is suspect (too many false positives, real findings being missed, or after changing a check/FP exclusion/LLM prompt), use the corpus system to measure impact.

### When to use
- After modifying a check in `src/warden/validation/frames/security/_internal/`
- After adding/changing FP exclusion patterns in `src/warden/validation/domain/fp_exclusions.py`
- After changing LLM prompts or confidence thresholds
- When a user reports a false positive or missed finding

### Commands
```bash
# Full evaluation — all checks, security frame (default)
warden corpus eval verify/corpus/ --fast

# Single check
warden corpus eval verify/corpus/ --check sql-injection --fast

# Other frames
warden corpus eval verify/corpus/ --frame orphan --fast
warden corpus eval verify/corpus/ --frame antipattern --fast

# CI gate (fails if F1 drops below threshold)
warden corpus eval verify/corpus/ --fast --min-f1 0.90
```

### Corpus files — `verify/corpus/`
Each file has a `corpus_labels:` block in its docstring:
```python
"""
corpus_labels:
  sql-injection: 3   # scanner must find exactly 3 (TP file)
  xss: 0             # scanner must find 0 (FP file)
"""
```

**Security corpus:** `python_sqli.py`, `python_xss.py`, `python_secrets.py`, `python_weak_crypto.py`, `python_command_injection.py`, `python_sqli_fp.py`, `python_xss_fp.py`, `python_secrets_fp.py`, `python_crypto_fp.py`, `python_command_fp.py`, `clean_python.py`.

**Resilience corpus:** `python_circuit_breaker_fp.py`, `python_circuit_breaker_tp.py`, `python_error_handling_fp.py`, `python_error_handling_tp.py`, `python_timeout_fp.py`, `python_timeout_tp.py`.

### Interpreting results
- **FP > 0** on a `*_fp.py` file → check is flagging safe patterns, add FP exclusion
- **FN > 0** on a `*_tp.py` / labeled file → check is missing real findings, review patterns
- **F1 < 1.00** → investigate which file caused it with `--check <id>`

### Key design notes
- `taint-analysis` is the check_id for command injection (no standalone command-injection check)
- `weak-crypto` only flags MD5/SHA1 **in password context** — checksums/ETags are intentionally excluded
- Findings with `pattern_confidence < 0.75` are LLM-routed and not counted in corpus scoring
- Finding ID format: `"{frame_id}-{check_id}-{n}"` — corpus uses substring match

---

## Conventions

- **Ruff:** `RUF001` and `RUF002` are intentionally ignored in `pyproject.toml:144-145` for Turkish character support.
- **License:** Apache-2.0.
- **Status:** Beta.
- **Python:** 3.10+, 120-character lines, spaces for indent, double quotes.
- **Commits:** Conventional Commits (`feat(scope):`, `fix(scope):`, `chore:`, `style:`).

---

## Active Line

| Field | Value |
|-------|-------|
| **Branch** | `feat/resilience-autoimprove-657` |
| **Tracking** | `origin/feat/resilience-autoimprove-657` (up to date) |
| **Working tree** | Dirty — `.warden/` cache/intelligence files + `warden_badge.svg` modified |
| **Open PR** | #660 — `fix(antipattern): regex fallback when AST yields no violations` |
| **Latest commit** | `f204c77` — fix cross-file corpus truncated to 5-file chunk, causing mass FPs |
| **Open issues (selected)** | #657 (resilience autoimprove), #506 P1 (GitHub Actions Marketplace publish), #522 (diff rename path mismatch) |

---

## References

- Consensus source of truth: `tests/WCORE-CONSENSUS-2026-04-28.md`
- Full pipeline & frame reference: `docs/PIPELINE_REFERENCE.md`
- Contract mode plan: `CONTRACT_MODE_PLAN.md` (45KB) + `CONTRACT_MODE_ROADMAP.md` (18KB)
- GitHub Action definition: `action.yml`
