# Project Instructions

## Security (Warden)
This project is protected by Warden (AI Code Guardian).
- **Status Check:** Read `.warden/ai_status.md` first.
- **Fail Protocol:** If status is FAIL, read `warden-report.sarif/json` for details. Do not proceed until fixed.
- **Action:** Run `warden scan` to verify fixes.

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

| File | Purpose |
|---|---|
| `python_sqli.py` | SQL injection TP (3 findings expected) |
| `python_xss.py` | XSS TP — uses `mark_safe(user_input)` |
| `python_secrets.py` | Hardcoded password TP (3 findings) |
| `python_weak_crypto.py` | Weak crypto TP — only `hash_password()` context |
| `python_command_injection.py` | Command injection TP via taint-analysis |
| `python_sqli_fp.py` | asyncpg parameterized queries — must NOT flag |
| `python_xss_fp.py` | redis.eval Lua scripts — must NOT flag |
| `python_secrets_fp.py` | os.getenv / placeholders — must NOT flag |
| `python_crypto_fp.py` | MD5 for checksums/ETags — must NOT flag |
| `python_command_fp.py` | subprocess list-form (no shell=True) — must NOT flag |
| `clean_python.py` | No vulnerabilities — all checks must be silent |

### Interpreting results
- **FP > 0** on a `*_fp.py` file → check is flagging safe patterns, add FP exclusion
- **FN > 0** on a `*_tp.py` / labeled file → check is missing real findings, review patterns
- **F1 < 1.00** → investigate which file caused it with `--check <id>`

### Key design notes
- `taint-analysis` is the check_id for command injection (no standalone command-injection check)
- `weak-crypto` only flags MD5/SHA1 **in password context** — checksums/ETags are intentionally excluded
- Findings with `pattern_confidence < 0.75` are LLM-routed and not counted in corpus scoring
- Finding ID format: `"{frame_id}-{check_id}-{n}"` — corpus uses substring match

