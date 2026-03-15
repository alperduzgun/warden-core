# Analysis Levels

Warden offers three analysis levels that control whether LLM-powered checks run alongside the always-on deterministic engine. Choosing the right level lets you balance speed, coverage, and infrastructure requirements for each context (CI gate, local review, or deep audit).

```
warden scan --level basic      # Deterministic only, no LLM needed
warden scan --level standard   # Deterministic + LLM verification
warden scan --level deep       # Full analysis with deep LLM reasoning
warden scan --quick-start      # Alias for basic, ideal for CI
```

---

## The Boundary: Deterministic vs LLM

Every Warden scan starts with deterministic analysis — checks that produce the same result on the same input, every time, with no external service dependency. LLM-enhanced checks layer on top of that foundation and are only activated at `standard` or `deep`.

| What runs | basic | standard | deep |
|---|:---:|:---:|:---:|
| Regex pattern matching (secrets, SQL injection, XSS) | yes | yes | yes |
| Tree-sitter AST structural analysis | yes | yes | yes |
| Interprocedural taint tracking (source-to-sink) | yes | yes | yes |
| Dependency vulnerability scanning (SCA) | yes | yes | yes |
| Orphan/dead-code detection (AST-based) | yes | yes | yes |
| Architecture gap analysis (dependency graph) | yes | yes | yes |
| Data-flow contract analysis (`--contract-mode`) | yes | yes | yes |
| LLM classification (frame selection) | no | yes | yes |
| LLM finding verification (false-positive reduction) | no | yes | yes |
| LLM triage (risk prioritisation per file) | no | yes | yes |
| LLM orphan filter (context-aware filtering) | no | yes | yes |
| LLM architecture verification | no | yes | yes |
| Fortification phase (auto-fix generation) | no | yes | yes |
| Deep semantic reasoning (extended LLM prompts) | no | no | yes |

---

## Level: basic

**LLM required:** no
**Ollama / API key required:** no

At `basic`, Warden sets `use_llm = False` and disables the fortification, cleaning, and issue-validation phases. Only checks that can run entirely offline execute.

Checks that run:

- **Regex patterns** — hardcoded secrets, SQL injection patterns, XSS sinks, insecure function calls across all languages.
- **AST analysis** — Tree-sitter structural parsing detects dangerous call patterns, SQL query construction, unvalidated input sources.
- **Taint tracking** — interprocedural source-to-sink tracing (full for Python/JS, regex-based for Go/Java).
- **Dependency scanning (SCA)** — advisory database lookup for known CVEs in declared dependencies.
- **Orphan detection** — AST-based unused-code detection without LLM filter.
- **Architecture gaps** — dependency and code graph analysis for broken imports, circular references, unreachable modules.
- **Data-flow contracts** — deterministic dead-write and missing-write detection (`--contract-mode`).

False-positive rate is higher at `basic` because LLM context-checking is absent. Expect more findings that require manual triage.

---

## Level: standard (default)

**LLM required:** yes (Ollama, Claude, OpenAI, Groq, or any configured provider)
**Ollama / API key required:** depends on configured provider

`standard` runs everything from `basic` and adds LLM-powered phases:

- **Classification** — LLM selects which validation frames are relevant for the detected tech stack and file risk profile.
- **Triage** — LLM assigns risk priority (P0–P3) per file; CI mode uses pre-computed intelligence to skip LLM for low-risk (P3) files.
- **Issue validation** — confidence-based false-positive detection reviews each finding against its code context before surfacing it.
- **LLM orphan filter** — context-aware review of AST-detected orphan candidates, reducing false positives from ~65% to under 10%.
- **Architecture verification** — LLM confirms FP-prone gap types (orphan modules, unreachable nodes, missing mixins).
- **Fortification** — LLM generates targeted fixes for confirmed findings.

This is the recommended level for day-to-day development and PR-scoped CI pipelines. Token usage is optimised via result-level caching (95% reduction in redundant LLM calls on unchanged files).

---

## Level: deep

**LLM required:** yes
**Ollama / API key required:** depends on configured provider

`deep` adds extended semantic reasoning on top of `standard`. It is intended for scheduled full-codebase audits, pre-release gates, or initial baseline creation — not for per-commit CI runs.

Differences from `standard`:

- Longer, higher-context LLM prompts that reason across file boundaries.
- Semantic search indexing used for cross-file vulnerability correlation.
- No time-budget optimisations — full analysis of every file regardless of change status.

Typical use from the CI integration guide:

```bash
# First run or manual baseline creation
warden scan . --level deep --format sarif --output warden.sarif
```

---

## Quick-Start Mode

`--quick-start` is an explicit alias for `--level basic` that also prints a user-facing banner confirming no LLM is required. It is designed for first-time users or CI environments where an LLM provider is not configured.

```bash
warden scan --quick-start          # Same as --level basic
warden scan --disable-ai           # Also maps to --level basic
```

If `--quick-start` is combined with an explicit `--level standard` or `--level deep`, `--quick-start` wins and a warning is printed.

---

## Choosing a Level

| Scenario | Recommended level |
|---|---|
| CI gate on every commit (no LLM in CI) | `--quick-start` or `--level basic` |
| CI gate on every PR (LLM available) | `--level standard` |
| Scheduled full-repo audit | `--level deep` |
| Pre-release security review | `--level deep` |
| Local development (fast feedback) | `--level basic` or `--level standard` |
| First scan / baseline creation | `--level deep` |

For CI pipelines where an LLM is available, a common pattern is:

```bash
# PR check — scan only changed files
warden scan --diff --level standard --format sarif --output warden.sarif

# Nightly full audit
warden scan . --level deep --format sarif --output warden.sarif
```

When no provider is configured, fall back to `basic` to keep CI green without blocking the pipeline:

```bash
warden scan --quick-start --format sarif --output warden.sarif
```

---

## Configuring a Provider

To use `standard` or `deep`, configure an LLM provider:

```bash
warden config llm use groq        # or: anthropic, openai, gemini, deepseek, azure
warden config llm status          # verify the active provider
warden config llm test            # send a test request
```

For local-only setups (no API key):

```bash
# Pull and start a local model via Ollama
ollama pull qwen2.5-coder:7b
warden scan --level standard
```

---

## Detection Source Attribution

Every finding in the scan result is tagged with its detection source so you can tell at a glance whether it was caught deterministically or by an LLM:

- `regex` / `ast` / `taint` / `sca` — deterministic sources; always present regardless of level.
- `llm_classification` / `llm_verification` / `llm_triage` — LLM sources; only present at `standard` or `deep`.
- Findings without a source tag (`unattributed`) come from frames that predate the attribution system.

The scan summary reports `deterministicFindingCount` and `llmFindingCount` for each run.
