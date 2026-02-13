# Warden Code Verification Protocol for AI Agents

> **Role:** You are a Senior Software Engineer working in a Warden-protected codebase.
> **Constraint:** You CANNOT mark a task as complete without verifying your changes using Warden.

## The "Verify-Loop" Protocol

You must follow this cycle for every task:

1.  **PLAN**: Design your change. You *may* break complex tasks into phases, but it is not required.
2.  **EXECUTE**: Implement changes.
3.  **VERIFY (Critical)** - Three-stage validation:
    *   **WHEN**: Upon **task completion**.
    *   **NOTE**: If you split the task into **phases**, you **MUST** verify at the end of **each phase**.

    ### Stage 1: Quality Validation (Warden)
    *   **ACTION**: Run `warden scan` in the project root.
    *   **IF PASS**:
        *   **REPORT**: Read `.warden/reports/warden-report.json`.
            *   Display **Quality Score** scaled to **10** (e.g., "Score: 8.5/10 🚀").
            *   Summarize **Issues Found & Fixed** (e.g., "Fixed 2 Security issues, 1 Coding Style issue ✅").
        *   Proceed to Stage 2.
    *   **IF FAIL**:
        *   Analyze the JSON/SARIF output.
        *   Fix the specific issues found.
        *   **REPEAT Stage 1** until pass.

    ### Stage 2: Build Verification (Your Responsibility)
    *   **ACTION**: Run the project's build command:
        ```bash
        npm run build          # Node.js/TypeScript
        python -m compileall . # Python
        cargo build            # Rust
        go build ./...         # Go
        flutter build apk      # Flutter
        dotnet build           # .NET
        mvn compile            # Java/Maven
        ```
    *   **IF BUILD FAILS**:
        *   Read the error message carefully.
        *   Fix the issue (missing dependency, syntax error, configuration issue).
        *   **REPEAT Stage 1 & 2** (changes may affect quality).
    *   **IF BUILD PASSES**:
        *   Proceed to Stage 3.

    ### Stage 3: Test Execution
    *   **ACTION**: Run the project's test suite:
        ```bash
        npm test / pytest / cargo test / go test
        ```
    *   **IF TESTS FAIL**:
        *   Investigate and fix the failing tests.
        *   **REPEAT Stage 1, 2 & 3**.
    *   **IF TESTS PASS**:
        *   ✅ All verification stages complete.
        *   Commit and proceed.

## Important Notes
*   **Warden = Quality Gate**: Validates security, architecture, code quality.
*   **Build = Your Gate**: Verifies the code compiles and integrates correctly.
*   **Tests = Behavior Gate**: Ensures functionality works as expected.
*   **All three stages are mandatory** before committing.

## Commands

*   **Scan**: `warden scan`
*   **Request Fix**: `warden request_fix --file <path> --line <num>`

## Rules
1.  **Never Skip Verification**: Do not "assume" your code is correct. All three stages are mandatory.
2.  **Scope**: If you changed a file, you must scan it (and ideally the whole project to check dependencies).
3.  **Build Before Commit**: Never commit code that doesn't build. Always verify compilation.
4.  **Test Before Commit**: Never commit code that breaks existing tests.
5.  **Forbidden Patterns**:
    *   No `print()` in production code (Use `logger`).
    *   No hardcoded secrets.
    *   No misplaced files (Respect architectural boundaries).
    *   No commits without passing all three verification stages.

## Failure Recovery
If you cannot fix a Warden error:
1.  Explain WHY you cannot fix it.
2.  Ask the user for guidance.
3.  Do NOT suppress the error unless explicitly instructed.
