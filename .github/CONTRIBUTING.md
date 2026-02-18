Contributing to Warden Core
===========================

Thanks for your interest in contributing! Warden Core is the open-source engine.
Warden Cloud is a separate, commercial product that builds on top of the core.

Ground Rules
------------
- License: Contributions are accepted under Apache-2.0.
- Sign-off: Use Developer Certificate of Origin (DCO) for all commits.
  - Add a Signed-off-by line to each commit: `git commit -s -m "feat: ..."`
- Code of Conduct: We follow the Contributor Covenant. See CODE_OF_CONDUCT.md.
- Security: Do not file vulnerabilities publicly. See SECURITY.md.

Scope: Core vs Cloud
--------------------
- Core (OSS): CLI, pipeline engine, frames SDK, AST/LSP integrations, diff/baseline,
  local LLM providers, JSON/SARIF outputs, suppression & verification phases.
- Cloud (Commercial): Org/repo management, SSO/SAML, RBAC, centralized policy,
  hosted dashboards, audit logs, enterprise integrations.

Development Setup
-----------------
1. Python 3.10+ and Rust toolchain (for optional extensions).
2. Create env: `python -m venv .venv && source .venv/bin/activate`
3. Install: `pip install -e .[dev]`
4. Lint/format: `ruff check . && ruff format .`
5. Tests: `pytest -q` (or `pytest -m "not slow and not integration"`).
6. Run CLI: `warden scan` or `warden scan --diff`.

Commit & PR Guidelines
----------------------
- Conventional Commits (e.g., `feat(cli): ...`, `fix(pipeline): ...`).
- Small, focused PRs; include tests and docs where relevant.
- Keep 120-char lines, spaces for indent, double quotes.
- Update examples/docs if behavior changes.

Design & RFCs
-------------
- Non-trivial changes benefit from an RFC PR in `docs/rfcs/`.
- Include problem statement, alternatives, migration risks, rollout plan.

Release & Versioning
--------------------
- SemVer for public APIs. Breaking changes require a deprecation note and release notes.

Legal
-----
- By contributing, you agree that your contributions are licensed under Apache-2.0.
- Ensure you have the right to contribute code (your employer, third-party licenses, etc.).

