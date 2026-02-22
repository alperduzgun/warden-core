Title
-----
Use Conventional Commits (e.g., `feat(cli): add diff baseline flag`).

Summary
-------
Briefly describe the change, motivation, and context.

Changes
-------
- What was added/removed/changed?
- Any migrations or config updates?

Testing
-------
- Commands run (unit/integration):
  - `pytest -q` (or focused markers)
  - `ruff check . && ruff format --check .`
  - `warden scan --diff` and attach relevant output
- Screenshots/logs (if applicable)

Backward Compatibility
----------------------
- Breaking changes? Deprecations? Migration notes?

Security & Risk
---------------
- Security considerations (secrets, SSRF, sandboxing, LLM routing)?
- Performance implications (p95 diff scan, memory)?

Docs
----
- Updated README/docs/examples if behavior changed.

Checklist
---------
- [ ] Conventional Commit title
- [ ] Tests added/updated (or not applicable)
- [ ] `ruff check` clean; formatted
- [ ] `pytest` passing locally
- [ ] `warden scan --diff` passes (attach summary if relevant)
- [ ] Docs/examples updated (if needed)
- [ ] Does not disclose secrets; follows SECURITY.md

Linked Issues
-------------
Closes #XXXX

