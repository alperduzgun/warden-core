# Environment Security Validator

**Author:** Warden Security Team
**Version:** 1.0.0
**Priority:** CRITICAL (Blocker)

## Purpose

This custom validation frame detects environment variable security issues and best practices violations in your codebase.

## What It Checks

### 1. Hardcoded Credentials ❌
Detects hardcoded:
- API Keys
- Secrets
- Tokens
- Passwords
- Private Keys
- AWS/Azure/Google Cloud credentials

**Example (BAD):**
```python
API_KEY = "sk-1234567890abcdef"  # ❌ Hardcoded!
aws_access_key = "AKIAIOSFODNN7EXAMPLE"  # ❌ Exposed!
```

**Example (GOOD):**
```python
import os

API_KEY = os.getenv('API_KEY')
if not API_KEY:
    raise ValueError('API_KEY environment variable is required')
```

### 2. Missing Validation ⚠️
Ensures sensitive environment variables are validated before use.

**Example (BAD):**
```python
SECRET_KEY = os.getenv('SECRET_KEY')  # ❌ No validation!
# What if SECRET_KEY is None?
```

**Example (GOOD):**
```python
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError('SECRET_KEY is required')
```

### 3. Insecure Defaults 🔒
Detects sensitive variables with default values.

**Example (BAD):**
```python
API_KEY = os.getenv('API_KEY', 'default-key-123')  # ❌ Insecure default!
```

**Example (GOOD):**
```python
# Sensitive vars should have NO defaults
API_KEY = os.getenv('API_KEY')
if not API_KEY:
    raise ValueError('API_KEY must be explicitly set')

# OR: Only safe defaults for non-sensitive configs
DEBUG = os.getenv('DEBUG', 'false')  # ✅ OK for non-sensitive
```

## Configuration

All config is **auto-generated** from `frame.yaml`!

### Default Config:
```yaml
enabled: true
check_hardcoded_credentials: true
check_missing_env_validation: true
check_insecure_defaults: true
sensitive_patterns:
  - API_KEY
  - SECRET
  - TOKEN
  - PASSWORD
  - PRIVATE_KEY
  - AWS_
  - AZURE_
  - GOOGLE_
severity_level: critical
```

### Override in `.warden/config.yaml`:
```yaml
frames_config:
  env-security:
    # Only override what you need
    check_missing_env_validation: false  # Disable validation check
    severity_level: high                  # Lower severity
    sensitive_patterns:                   # Add custom patterns
      - CUSTOM_SECRET
      - MY_TOKEN
```

## Usage

### 1. Automatic Discovery
The frame is automatically discovered from `~/.warden/frames/env-security/`

### 2. Enable in Config
Add to `.warden/config.yaml`:
```yaml
frames:
  - security
  - chaos
  - env-security  # Add this line
```

### 3. Run Warden
```bash
warden scan .
```

## Example Output

```
🔍 Environment Security Validator

❌ FAILED (3 issues found)

1. Hardcoded API Key detected
   Location: config.py:12
   Severity: critical
   Code: API_KEY = "sk-1234567890"

   Fix:
     import os
     api_key = os.getenv('API_KEY')
     if not api_key:
         raise ValueError('API_KEY not configured')

2. Sensitive environment variable 'SECRET_KEY' not validated
   Location: app.py:45
   Severity: high

3. Insecure default value for sensitive variable 'PASSWORD'
   Location: database.py:23
   Severity: high
```

## Files

```
~/.warden/frames/env-security/
├── frame.yaml       # Metadata + Config Schema (auto-generates config)
├── frame.py         # ValidationFrame implementation
└── README.md        # This file
```

## Testing

```python
import asyncio
from warden.validation.infrastructure.frame_registry import get_registry
from warden.validation.domain.frame import CodeFile

# Get frame
registry = get_registry()
registry.discover_all()

frame_class = registry.get("envsecurity")
frame = frame_class()

# Test code
test_code = '''
API_KEY = "sk-hardcoded-secret"
password = os.getenv('PASSWORD', 'default123')
'''

code_file = CodeFile(path="test.py", content=test_code, language="python")

# Run validation
result = asyncio.run(frame.execute(code_file))
print(f"Status: {result.status}")
print(f"Findings: {result.issues_found}")
```

## Benefits

✅ **Auto-Config:** No manual config needed - auto-generated from frame.yaml
✅ **Customizable:** Override only what you need in .warden/config.yaml
✅ **Production-Ready:** Detects real security issues
✅ **Best Practices:** Enforces environment variable security patterns
✅ **CI/CD Ready:** Blocker status prevents insecure code from deploying

## Author

Warden Security Team
Created: 2025-12-26
License: Internal Use
