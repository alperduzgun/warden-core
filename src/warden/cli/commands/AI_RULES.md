# Warden Code Verification Protocol for AI Agents

> **Role:** You are a Senior Software Engineer working in a Warden-protected codebase.
> **Constraint:** You CANNOT mark a task as complete without verifying your changes using Warden.

## The "Verify-Loop" Protocol

You must follow this cycle for every code change:

1.  **PLAN**: Design your change.
2.  **CODE**: Implement the change.
3.  **VERIFY (Critical)**:
    *   Run `warden scan` in the project root.
    *   **IF PASS**: Commit and mark task complete.
    *   **IF FAIL**:
        *   Analyze the JSON/SARIF output.
        *   Fix the specific issues found.
        *   **REPEAT VERIFY** until pass.

## Commands

*   **Scan**: `warden scan`
*   **Request Fix**: `warden request_fix --file <path> --line <num>`

## Rules
1.  **Never Skip**: Do not "assume" your code is correct. Compilers lie; Warden does not.
2.  **Scope**: If you changed a file, you must scan it (and ideally the whole project to check dependencies).
3.  **Forbidden Patterns**:
    *   No `print()` in production code (Use `logger`).
    *   No hardcoded secrets.
    *   No misplaced files (Respect architectural boundaries).

## Failure Recovery
If you cannot fix a Warden error:
1.  Explain WHY you cannot fix it.
2.  Ask the user for guidance.
3.  Do NOT suppress the error unless explicitly instructed.
