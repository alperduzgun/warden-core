# Repository Guidelines

Last refreshed: 2026-04-28 (per WCORE-CONSENSUS)

---

## Project Structure & Module Organization

- `src/warden/`: Python source (CLI entry, frames, pipeline, LLM, etc.).
  - Key submodules: `cli/`, `pipeline/`, `validation/` (13 frames), `llm/` (10+ providers),
    `ast/`, `classification/`, `suppression/`, `memory/`, `self_healing/`, `semantic_search/`,
    `benchmark/`, `grpc/` (experimental), `mcp/`, `lsp/`, `rules/`, `fortification/`,
    `reports/`, `config/`, `secrets/`, `shared/`.
- `src/warden_rust/`: Rust extension (built via `setuptools-rust` in `setup.py`).
- `tests/`: Pytest suite (`test_*.py`, markers for slow/integration/live).
- `examples/` and `docs/`: Usage samples and documentation.
- `.warden/`: Agent rules/config, reports, and ignore lists.
- `action.yml`: GitHub Action composite definition (SARIF upload, PR comment, diff-mode).
- `verify/corpus/`: FP/TP labeled test files for frame-agnostic evaluation.

## Build, Test, and Development Commands

- Create env: `python -m venv .venv && source .venv/bin/activate`
- Install dev: `pip install -e .[dev]` (or `bash scripts/install_dev.sh`)
- Run CLI: `warden scan` (or `warden scan --diff` for changed files)
- Tests: `pytest -q` (e.g., `pytest -m "not slow"`, `pytest -k name`)
- Lint/format: `ruff check .` and `ruff format .` (or `ruff check --fix .`)
- Type checks (optional): `mypy src` and `pyright`

## Coding Style & Naming Conventions

- Python 3.10+, 120-char lines, spaces for indent, double quotes.
- Modules/functions: `snake_case`; classes: `PascalCase`; constants: `UPPER_SNAKE`.
- Sorting/import style handled by Ruff (isort rules). Keep public APIs typed.
- Ruff intentionally ignores `RUF001`/`RUF002` for Turkish character support (`pyproject.toml:144-145`).

## Testing Guidelines

- Framework: Pytest. Tests live under `tests/`, named `test_*.py`.
- Markers: `unit`, `integration`, `llm`, `slow`, `live`, `security`, `acceptance`.
- Typical runs: `pytest -m "not slow and not integration"` for fast cycles.
- Add focused unit tests alongside changes; prefer pure functions and fixtures.

## Commit & Pull Request Guidelines

- Conventional Commits: `feat(scope): ...`, `fix(scope): ...`, `chore: ...`, `style: ...`.
  - Examples: `feat(llm): add provider flag`, `fix(mcp): resolve timeout`.
- PRs: clear description, link issues, include CLI output (e.g., `warden scan --diff`) and rationale.
- Required: tests pass, `ruff check` clean, formatted code, update docs/examples if affected.

## Security & Configuration Tips

- Do not commit secrets. Use `.env` and mirror keys in `.env.example`.
- Warden config lives in `.warden/` (rules, suppressions, baseline). Keep changes reviewable.
- For CI/local split, prefer envs (e.g., `WARDEN_LLM_PROVIDER`, `OPENAI_API_KEY`).

## Agent Capabilities

Warden exposes several agent-oriented capabilities:

- **Self-Healing** (`src/warden/self_healing/`): runtime error classification and automated repair strategies (config, import, model, provider, LLM healers).
- **Semantic Search** (`src/warden/semantic_search/`): vector similarity search over indexed code via embeddings and adapters.
- **Multi-Provider LLM Routing** (`src/warden/llm/`): 10+ providers with circuit breaker, rate limiting, and parallel fast-tier execution.
- **MCP Server** (`src/warden/mcp/`): Model Context Protocol integration for external agent consumption.
- **Interactive Chat/TUI** (`warden chat`): slash-command system (`/scan`, `/analyze`, `/rules`) with `@file` injection and `!shell` execution.

## Self-Improvement

- `--auto-improve` flag: after scan, auto-generates FP corpus from low-confidence findings and runs the autoimprove loop.
- `--report-fp <finding-id>`: instant false-positive suppression via corpus write + pattern update.
- `warden rules autoimprove`: keep-or-revert loop that proposes FP suppression patterns and validates them against the full corpus (F1 must not drop).

## Provider List

Supported LLM providers (local + cloud):

| Provider | Type | Default Model (if any) |
|----------|------|------------------------|
| Claude Code CLI | Local | — |
| Codex CLI | Local | — |
| Ollama | Local | — |
| Anthropic API | Cloud | — |
| OpenAI API | Cloud | — |
| Google Gemini | Cloud | — |
| Groq | Cloud | — |
| DeepSeek | Cloud | — |
| Qwen Cloud (Alibaba DashScope) | Cloud | `qwen-coder-turbo` |

## Branch Hygiene & PR Workflow

- Main dev branch: `dev`. Production: `main`.
- Current active branch: `feat/resilience-autoimprove-657` (tracking `origin/feat/resilience-autoimprove-657`).
- Open PR on this branch: #660 — `fix(antipattern): regex fallback when AST yields no violations`.
- Conventional Commits enforced.
- Post-task: run `warden scan --diff` and address findings before review.

## Self-Scan Policy

- Every agent session should read `.warden/ai_status.md` first. If FAIL, read SARIF/JSON reports and fix before proceeding.
- v2.6.0 self-scan: 99.5% FP reduction (388 findings → 2).

## Agent Workflow (Recommended)

- Plan → Execute → Verify. After each task or PR, run `warden scan --diff` and address findings before review.
- If you modify `src/warden/validation/frames/security/_internal/`, run `warden corpus eval verify/corpus/ --fast` to verify no regression.
