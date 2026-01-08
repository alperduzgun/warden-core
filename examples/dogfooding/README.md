# Warden Dogfooding Examples

Test files for verifying warden frame functionality.

## Files

| File | Frame | What it Tests |
|------|-------|---------------|
| `security_vulnerabilities.py` | security | SQL injection, command injection, hardcoded secrets |
| `vulnerable_code.py` | security | Additional security vulnerabilities |
| `orphan_test.py` | orphan | Unused imports, functions, classes, dead code |
| `chaos_test.py` | chaos | Missing timeout, retry, circuit breaker patterns |
| `property_test.py` | property | Input validation, edge cases, bounds checking |
| `architectural_test.py` | architectural | God classes, tight coupling, dependency issues |

## Quick Test Commands

```bash
# Test all frames
warden scan examples/dogfooding/python

# Test specific frame
warden scan examples/dogfooding/python --frames security
warden scan examples/dogfooding/python --frames orphan
warden scan examples/dogfooding/python --frames chaos
warden scan examples/dogfooding/python --frames property
warden scan examples/dogfooding/python --frames architectural
```
