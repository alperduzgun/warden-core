# Repository Guidelines

## Project Structure & Module Organization
- `src/warden/`: Python source (CLI entry, frames, pipeline, LLM, etc.).
- `src/warden_rust/`: Rust extension (built via `setuptools-rust`).
- `tests/`: Pytest suite (`test_*.py`, markers for slow/integration/live).
- `examples/` and `docs/`: Usage samples and documentation.
- `.warden/`: Agent rules/config, reports, and ignore lists.

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

## Testing Guidelines
- Framework: Pytest. Tests live under `tests/`, named `test_*.py`.
- Markers: `slow`, `integration`, `live`, `security`, `acceptance`.
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

## Agent Workflow (Recommended)
- Plan → Execute → Verify. After each task or PR, run `warden scan --diff` and address findings before review.

