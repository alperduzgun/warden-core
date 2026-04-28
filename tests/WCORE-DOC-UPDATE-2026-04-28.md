# WCORE Doc Update Report — 2026-04-28

## Summary

Updated `CLAUDE.md` and `AGENTS.md` with the consolidated project state from `tests/WCORE-CONSENSUS-2026-04-28.md` (both signatures: Claude + Kimi APPROVE).

---

## CLAUDE.md

| Metric | Value |
|--------|-------|
| Before | 69 lines |
| After | 213 lines |
| Diff | +161 insertions, -16 deletions |

### Added sections
- **Project Identity** — name, version, purpose, target user, license, status
- **Stack Snapshot** — Python 3.10+, Rust PyO3 extension, Typer, Rich/Textual, tree-sitter (7 languages), Pydantic v2, ruff (primary) + black/isort (dev deps), mypy/pyright, setuptools + optional setuptools-rust
- **Architecture (Short)** — pipeline phases (Pre-Analysis → Triage → LSP Audit → Analysis → Classification → Validation → LSP Diagnostics → Verification → Fortification → Cleaning → Baseline Filter), 13 frames, 15 security checks, analysis levels (basic/standard/deep), CI mode
- **Modules (`src/warden/`)** — complete module list including `self_healing/`, `semantic_search/`, `benchmark/`, `grpc/` (experimental), `mcp/`, `lsp/`, `rules/`, `fortification/`, etc.
- **Commands Snapshot** — `warden init`, `warden scan` (with `--diff`, `--ci`, `--quick-start`, `--auto-improve`, `--report-fp`), `warden corpus eval`, `warden rules autoimprove`, `warden chat`
- **Self-Scan Capability** — PASS status, 99.5% FP reduction note
- **Corpus System** — security + resilience corpus files listed, F1 scoring, CI gate
- **Conventions** — RUF001/RUF002 Turkish char suppression, Apache-2.0, Beta, Python 3.10+, 120-char lines, Conventional Commits
- **Active Line** — branch, tracking, working tree state, open PR #660, latest commit, selected open issues
- **References** — consensus SOT, PIPELINE_REFERENCE.md, CONTRACT_MODE plan docs, action.yml

### Preserved sections
- Security (Warden) status check protocol
- Corpus Evaluation System (commands, interpreting results, key design notes)

---

## AGENTS.md

| Metric | Value |
|--------|-------|
| Before | 42 lines |
| After | 101 lines |
| Diff | +69 insertions, -10 deletions |

### Added sections
- **Agent Capabilities** — self-healing, semantic search, multi-provider LLM routing, MCP server, interactive chat/TUI
- **Self-Improvement** — `--auto-improve`, `--report-fp`, `warden rules autoimprove`
- **Provider List** — 9 providers (Claude Code CLI, Codex CLI, Ollama, Anthropic, OpenAI, Gemini, Groq, DeepSeek, Qwen Cloud with `qwen-coder-turbo` default)
- **Branch Hygiene & PR Workflow** — dev/main branches, current active branch `feat/resilience-autoimprove-657`, open PR #660, conventional commits, post-task scan policy
- **Self-Scan Policy** — read `.warden/ai_status.md` first, FAIL protocol, v2.6.0 self-scan stats

### Updated sections
- **Project Structure & Module Organization** — expanded with all submodules (`self_healing/`, `semantic_search/`, `benchmark/`, `grpc/`, `action.yml`, `verify/corpus/`)
- **Coding Style & Naming Conventions** — added RUF001/RUF002 Turkish character suppression note
- **Testing Guidelines** — expanded markers list (`unit`, `integration`, `llm`, `slow`, `live`, `security`, `acceptance`)

### Preserved sections
- Build, Test, and Development Commands
- Commit & Pull Request Guidelines
- Security & Configuration Tips
- Agent Workflow (Recommended)

---

## Commit & Push

| Field | Value |
|-------|-------|
| **Commit SHA** | `bfb175b9090e64a7c51e657813a5256fe6b97d70` |
| **Message** | `docs: refresh CLAUDE.md + AGENTS.md with current project state (per consensus 2026-04-28)` |
| **Branch** | `feat/resilience-autoimprove-657` |
| **Push** | ✅ Success (`f204c77..bfb175b` pushed to `origin/feat/resilience-autoimprove-657`) |

---

*Report generated on 2026-04-28. No code changes made beyond documentation updates.*

WCORE_DOC_UPDATE_DONE
