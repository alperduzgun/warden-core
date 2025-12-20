```markdown
# Two-Level Pluggable System: Frames + Checks

> **Both Frames AND Checks are pluggable, extensible, and modular!**

**Last Updated:** 2025-12-20

---

## 🎯 Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│  LEVEL 1: FRAMES (Strategy/Category) - PLUGGABLE            │
├──────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Security     │  │ Chaos        │  │ MyCustom     │       │
│  │ Frame        │  │ Frame        │  │ Frame        │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                  │                  │               │
│         ▼                  ▼                  ▼               │
│  ┌─────────────────────────────────────────────────┐         │
│  │  LEVEL 2: CHECKS (Specific Rules) - PLUGGABLE  │         │
│  ├─────────────────────────────────────────────────┤         │
│  │                                                  │         │
│  │  SecurityFrame Checks:                          │         │
│  │  ├─ SQLInjectionCheck (built-in)               │         │
│  │  ├─ XSSCheck (built-in)                        │         │
│  │  ├─ SecretsCheck (built-in)                    │         │
│  │  ├─ HardcodedPasswordCheck (built-in)          │         │
│  │  ├─ MyCompanyAPIKeyCheck (community!)          │         │
│  │  └─ CustomSecretPatternCheck (community!)      │         │
│  │                                                  │         │
│  │  ChaosFrame Checks:                             │         │
│  │  ├─ NetworkFailureCheck (built-in)             │         │
│  │  ├─ TimeoutCheck (built-in)                    │         │
│  │  ├─ CircuitBreakerCheck (built-in)             │         │
│  │  └─ MyCompanyRetryPolicyCheck (community!)     │         │
│  │                                                  │         │
│  │  MyCustomFrame Checks:                          │         │
│  │  └─ CustomCheck1, CustomCheck2... (yours!)     │         │
│  │                                                  │         │
│  └─────────────────────────────────────────────────┘         │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

---

## 🔍 Why Two Levels?

### Problem with Single-Level System

```python
# ❌ Monolithic Frame (hard to extend)
class SecurityFrame:
    def execute(self):
        self.check_sql_injection()      # Built-in
        self.check_xss()                # Built-in
        self.check_secrets()            # Built-in
        # How does community add custom checks? 🤔
```

### Solution: Two-Level Pluggable System

```python
# ✅ Frame + Pluggable Checks
class SecurityFrame:
    def __init__(self):
        self.checks = CheckRegistry()

        # Built-in checks
        self.checks.register(SQLInjectionCheck())
        self.checks.register(XSSCheck())
        self.checks.register(SecretsCheck())

        # Community checks (auto-discovered!)
        self.checks.discover_and_register()

    async def execute(self, code_file):
        results = []
        for check in self.checks.get_enabled():
            result = await check.execute(code_file)
            results.append(result)
        return results
```

**Benefits:**
1. **Granular Control**: Enable/disable specific checks
2. **Community Extension**: Add custom checks without forking frame
3. **Reusability**: Share checks across frames
4. **Configuration**: Each check has its own config

---

## 📦 Package Structure

### Community Frame Package (with built-in checks)

```
warden-frame-mycompany/
├── pyproject.toml
├── src/
│   └── warden_frame_mycompany/
│       ├── frame.py          # MyCompanyFrame
│       └── checks/            # Built-in checks for this frame
│           ├── api_key_check.py
│           └── import_check.py
```

### Community Check Package (extends existing frame)

```
warden-check-mycompany-api/
├── pyproject.toml
├── src/
│   └── warden_check_mycompany_api/
│       └── check.py          # MyCompanyAPIKeyCheck (for SecurityFrame)
```

---

## 🔌 Plugin Discovery

### Level 1: Frame Discovery

```toml
# pyproject.toml for Frame
[tool.poetry.plugins."warden.frames"]
mycompany = "warden_frame_mycompany.frame:MyCompanyFrame"
```

### Level 2: Check Discovery (per Frame)

```toml
# pyproject.toml for Check (SecurityFrame)
[tool.poetry.plugins."warden.checks.security"]
mycompany_api_key = "warden_check_mycompany_api.check:MyCompanyAPIKeyCheck"

# pyproject.toml for Check (ChaosFrame)
[tool.poetry.plugins."warden.checks.chaos"]
mycompany_retry = "warden_check_mycompany_api.check:MyCompanyRetryCheck"
```

**Entry Point Format:**
- Frames: `warden.frames`
- Checks: `warden.checks.{frame_id}`
  - `warden.checks.security` - For SecurityFrame
  - `warden.checks.chaos` - For ChaosFrame
  - `warden.checks.mycompany` - For MyCompanyFrame

---

## 📁 Directory-Based Discovery

### Level 1: Frames

```
~/.warden/plugins/
└── mycompany-frame/
    ├── plugin.yaml
    └── frame.py
```

### Level 2: Checks

```
~/.warden/checks/
├── security/                     # Checks for SecurityFrame
│   ├── mycompany-api-key/
│   │   ├── check.yaml
│   │   └── check.py
│   └── custom-secret-pattern/
│       ├── check.yaml
│       └── check.py
│
├── chaos/                        # Checks for ChaosFrame
│   └── mycompany-retry/
│       ├── check.yaml
│       └── check.py
│
└── mycompany/                    # Checks for MyCompanyFrame
    └── custom-check/
        ├── check.yaml
        └── check.py
```

---

## 🎨 Example: Community Check

### 1. Create Check Class

```python
# warden_check_mycompany_api/check.py

from warden.validation.domain.check import (
    ValidationCheck,
    CheckResult,
    CheckFinding,
    CheckSeverity,
)
import re


class MyCompanyAPIKeyCheck(ValidationCheck):
    """
    Detects MyCompany-specific API keys in code.

    This check extends SecurityFrame with company-specific patterns.
    """

    # Required metadata
    id = "mycompany-api-key"
    name = "MyCompany API Key Detection"
    description = "Detects hardcoded MyCompany API keys"
    severity = CheckSeverity.CRITICAL
    version = "1.0.0"
    author = "MyCompany Security Team"
    enabled_by_default = True

    def __init__(self, config: dict | None = None):
        super().__init__(config)

        # Load custom patterns from config
        self.patterns = self.config.get(
            "patterns",
            [
                r"MY_COMPANY_API_[A-Z0-9]{32}",
                r"INTERNAL_SERVICE_KEY_[A-Z0-9]{32}",
            ],
        )

    async def execute(self, code_file) -> CheckResult:
        """Execute API key detection."""
        findings = []

        for pattern_str in self.patterns:
            pattern = re.compile(pattern_str)

            for line_num, line in enumerate(code_file.content.split("\n"), start=1):
                if pattern.search(line):
                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=self.severity,
                            message=f"Hardcoded MyCompany API key detected",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=line.strip(),
                            suggestion=(
                                "Move API key to environment variable or Azure Key Vault. "
                                "Use: api_key = os.getenv('MY_COMPANY_API_KEY')"
                            ),
                            documentation_url="https://docs.mycompany.com/security/api-keys",
                        )
                    )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
        )
```

### 2. Package Configuration

```toml
# pyproject.toml

[tool.poetry]
name = "warden-check-mycompany-api"
version = "1.0.0"
description = "MyCompany API key detection for Warden SecurityFrame"

[tool.poetry.dependencies]
python = "^3.11"
warden-core = "^0.1.0"

# Register check for SecurityFrame
[tool.poetry.plugins."warden.checks.security"]
mycompany_api_key = "warden_check_mycompany_api.check:MyCompanyAPIKeyCheck"
```

### 3. Installation

```bash
# Publish to PyPI
poetry publish

# Install (user)
pip install warden-check-mycompany-api

# Check is auto-discovered and added to SecurityFrame!
warden scan ./src
```

---

## ⚙️ Configuration

### Frame-Level Configuration

```yaml
# .warden/config.yaml

plugins:
  enabled:
    - security
    - chaos
    - mycompany

  frame_config:
    security:
      # Enable/disable specific checks
      checks:
        sql-injection:
          enabled: true
        xss:
          enabled: true
        secrets:
          enabled: true
        mycompany-api-key:          # Community check!
          enabled: true
          patterns:
            - "MY_COMPANY_API_[A-Z0-9]{32}"
            - "CUSTOM_PATTERN_.*"
```

### Programmatic Configuration

```python
# Configure SecurityFrame with custom checks
from warden.validation.frames import SecurityFrame
from warden_check_mycompany_api.check import MyCompanyAPIKeyCheck

security_frame = SecurityFrame(config={
    "checks": {
        "mycompany-api-key": {
            "enabled": True,
            "patterns": ["CUSTOM_.*"]
        }
    }
})

# Or register check directly
security_frame.register_check(MyCompanyAPIKeyCheck())
```

---

## 🔄 Execution Flow

```
User: warden scan my_file.py
    ↓
FrameExecutor
    ↓
SecurityFrame.execute(code_file)
    ↓
    ├─ Built-in Checks:
    │   ├─ SQLInjectionCheck.execute() → CheckResult
    │   ├─ XSSCheck.execute() → CheckResult
    │   ├─ SecretsCheck.execute() → CheckResult
    │   └─ HardcodedPasswordCheck.execute() → CheckResult
    │
    └─ Community Checks:
        ├─ MyCompanyAPIKeyCheck.execute() → CheckResult
        └─ CustomSecretPatternCheck.execute() → CheckResult
    ↓
Aggregate all CheckResults
    ↓
Return FrameResult (with all findings)
```

---

## 📊 Benefits Comparison

| Feature | Single-Level | Two-Level |
|---------|--------------|-----------|
| **Frame Extensibility** | ✅ Yes (new frames) | ✅ Yes (new frames) |
| **Check Extensibility** | ❌ No (modify frame) | ✅ Yes (add checks) |
| **Granular Control** | ❌ No (all or nothing) | ✅ Yes (per-check) |
| **Community Contribution** | ⚠️ Limited (frames only) | ✅ Full (frames + checks) |
| **Reusability** | ⚠️ Frame-level | ✅ Check-level |
| **Configuration** | ⚠️ Frame-level | ✅ Check-level |

---

## 🎯 Use Cases

### Use Case 1: Add Custom Check to Built-in Frame

**Scenario:** Company wants to add API key detection to SecurityFrame

```python
# Don't fork Warden! Just create a check package:
class MyCompanyAPIKeyCheck(ValidationCheck):
    # ... custom logic ...

# Publish to PyPI
poetry publish

# Users install
pip install warden-check-mycompany-api

# Check runs automatically with SecurityFrame!
```

### Use Case 2: Create Custom Frame with Custom Checks

**Scenario:** Company wants a full custom validation strategy

```python
# Create frame
class MyCompanyStandardsFrame(ValidationFrame):
    def __init__(self):
        super().__init__()
        self.checks.register(NamingConventionCheck())
        self.checks.register(DocumentationCheck())

# Publish
poetry publish

# Users install
pip install warden-frame-mycompany-standards
```

### Use Case 3: Share Checks Across Frames

**Scenario:** A check is useful for multiple frames

```python
# TimeoutCheck can be used by:
# - ChaosFrame (resilience testing)
# - PerformanceFrame (performance testing)

# Register in multiple frames:
chaos_frame.register_check(TimeoutCheck())
performance_frame.register_check(TimeoutCheck())
```

---

## 🚀 Migration Path

### Phase 1: Built-in Frames + Built-in Checks ✅
```
SecurityFrame
  ├─ SQLInjectionCheck (built-in)
  ├─ XSSCheck (built-in)
  └─ SecretsCheck (built-in)
```

### Phase 2: Community Frames ✅
```
pip install warden-frame-mycompany
```

### Phase 3: Community Checks (NEW!) ✅
```
pip install warden-check-mycompany-api

# Extends SecurityFrame without forking!
```

---

## 📝 Summary

**Two-Level Pluggable System:**

1. **Level 1: Frames** (Strategy/Category)
   - Security, Chaos, Fuzz, Property, Stress, Custom
   - Pluggable via PyPI, directory, entry points

2. **Level 2: Checks** (Specific Rules)
   - SQLInjection, XSS, Timeout, APIKey, Custom
   - Pluggable via PyPI, directory, entry points
   - Can extend built-in frames OR custom frames

**Benefits:**
- ✅ **Granular Control**: Enable/disable per-check
- ✅ **Community Extension**: Add checks without forking
- ✅ **Reusability**: Share checks across frames
- ✅ **Flexibility**: Mix built-in + community frames + community checks

**Next:** Implement built-in frames with check support!
```
