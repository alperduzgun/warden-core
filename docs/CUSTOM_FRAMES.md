# Warden Custom Frames - Developer Guide

**Create your own validation frames for any technology, framework, or security standard.**

## 📖 Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Frame Architecture](#frame-architecture)
- [Creating a Custom Frame](#creating-a-custom-frame)
- [Frame Metadata (frame.yaml)](#frame-metadata-frameyaml)
- [Implementing Validation Logic](#implementing-validation-logic)
- [Testing Your Frame](#testing-your-frame)
- [Distribution & Installation](#distribution--installation)
- [Best Practices](#best-practices)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

---

## Overview

Warden's custom frame system allows you to create validation frames for:

- **Technology-specific validations**: Redis, MongoDB, PostgreSQL, RabbitMQ
- **Cloud providers**: AWS, Azure, GCP compliance checks
- **Security standards**: OWASP Top 10, CWE Top 25, PCI DSS
- **Company-specific rules**: Internal security policies, coding standards
- **Framework best practices**: FastAPI, Flask, Django patterns

### Frame Types

1. **Built-in Frames** (Shipped with Warden)
   - Security, Chaos, Fuzz, Property, Stress, Architectural
   - Maintained by Warden team
   - Location: `warden.validation.frames`

2. **Community Frames** (Python-based)
   - Created by developers
   - Installed locally: `~/.warden/frames/`
   - Discovered automatically

3. **Marketplace Frames** (WASM - Future)
   - Multi-language support (Rust, Go, Python)
   - Sandboxed execution
   - Community distribution

---

## Quick Start

### 1. Create Frame Structure

```bash
# Create a new frame
warden frame create redis-security

# Output:
# ~/.warden/frames/redis-security/
# ├── frame.yaml          # Metadata
# ├── frame.py            # Implementation
# ├── checks/             # Optional sub-checks
# ├── tests/              # Required tests
# │   └── test_frame.py
# └── README.md
```

### 2. Implement Validation Logic

Edit `frame.py`:

```python
from warden.validation.domain.frame import (
    ValidationFrame, FrameResult, Finding, CodeFile
)
from warden.validation.domain.enums import (
    FrameCategory, FramePriority, FrameScope, FrameApplicability
)

class RedisSecurityFrame(ValidationFrame):
    """Redis security best practices validator."""

    name = "Redis Security Validator"
    description = "Validates Redis connection security"
    category = FrameCategory.GLOBAL
    priority = FramePriority.CRITICAL
    scope = FrameScope.FILE_LEVEL
    is_blocker = True

    async def execute(self, code_file: CodeFile) -> FrameResult:
        findings = []

        # Check for insecure Redis connections
        if "Password=" in code_file.content and "ssl=true" not in code_file.content:
            findings.append(Finding(
                id="redis-insecure-connection",
                severity="critical",
                message="Redis connection without SSL detected",
                location=f"{code_file.path}",
                detail="Always use SSL for Redis connections in production"
            ))

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="failed" if findings else "passed",
            duration=0.1,
            issues_found=len(findings),
            is_blocker=self.is_blocker,
            findings=findings
        )
```

### 3. Validate & Test

```bash
# Validate frame structure
warden frame validate ~/.warden/frames/redis-security

# Run tests
pytest ~/.warden/frames/redis-security/tests/

# Frame is now auto-discovered
warden frame list
```

### 4. Use in Pipeline

Custom frames are automatically integrated into Warden's validation pipeline:

```yaml
# .warden/config.yaml
frames:
  # Built-in frames
  - security
  - chaos

  # Custom frames (auto-discovered from ~/.warden/frames/)
  - redissecurity  # Use frame_id (snake_case), not kebab-case!
```

```bash
# Scan with custom frames
warden scan run . --verbose

# Output:
# Discovered 4 frames (built-in + custom)
# Available frames: security, chaos, architecturalconsistency, redissecurity
# ✓ Loaded: security
# ✓ Loaded: chaos
# ✓ Loaded: redissecurity
```

**Note:** Frame IDs are auto-converted to snake_case (e.g., `RedisSecurityFrame` → `redissecurity`). Use `warden frame list` to see exact frame IDs.

---

## Frame Architecture

### Directory Structure

```
~/.warden/frames/my-custom-frame/
├── frame.yaml              # Required: Metadata
├── frame.py                # Required: ValidationFrame implementation
├── checks/                 # Optional: Sub-checks
│   ├── __init__.py
│   ├── check_ssl.py
│   └── check_config.py
├── tests/                  # Required: Tests
│   ├── __init__.py
│   └── test_frame.py
└── README.md               # Recommended: Documentation
```

### Frame Lifecycle

1. **Discovery**: FrameRegistry scans `~/.warden/frames/`
2. **Metadata Load**: Parse `frame.yaml`
3. **Module Load**: Import `frame.py` dynamically
4. **Validation**: Verify ValidationFrame subclass exists
5. **Registration**: Add to registry with metadata
6. **Execution**: Run during validation pipeline

### Discovery Sources (Priority Order)

1. **Built-in frames**: `warden.validation.frames.*` (always available)
2. **Entry points**: PyPI packages via `warden.frames` entry point
3. **Local directory**: `~/.warden/frames/` (auto-discovered)
4. **Environment variable**: `WARDEN_FRAME_PATHS` (colon-separated paths)

**Example:**
```bash
# Multiple discovery sources
export WARDEN_FRAME_PATHS="/company/security-frames:/team/custom-frames"
warden frame list  # Shows all discovered frames
```

---

## Creating a Custom Frame

### Step 1: Generate Template

```bash
warden frame create my-validator \
  --priority high \
  --blocker \
  --category global \
  --author "Your Name"
```

**Options**:
- `--priority`: `critical | high | medium | low`
- `--blocker`: Frame fails validation if issues found
- `--category`: `global | language-specific | framework-specific`
- `--output`: Custom output directory

### Step 2: Configure Metadata

Edit `frame.yaml`:

```yaml
name: "My Custom Validator"
id: "my-validator"
version: "1.0.0"
author: "Your Name"
description: "Validates X according to Y standard"

category: "global"
priority: "high"
scope: "file_level"
is_blocker: true

applicability:
  - language: "python"
  - language: "typescript"
  - framework: "fastapi"

config_schema:
  check_ssl:
    type: "boolean"
    default: true
    description: "Check SSL requirement"

  allowed_hosts:
    type: "array"
    items: "string"
    default: ["localhost"]

tags:
  - "security"
  - "custom"
```

### Step 3: Implement ValidationFrame

```python
class MyValidatorFrame(ValidationFrame):
    """Custom validator implementation."""

    # Required metadata
    name = "My Custom Validator"
    description = "Validates X according to Y standard"
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    is_blocker = True

    # Optional metadata
    version = "1.0.0"
    author = "Your Name"
    applicability = [FrameApplicability.PYTHON]

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        # Initialize your checks

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """Execute validation on code file."""
        start_time = time.perf_counter()
        findings = []

        # TODO: Implement validation logic

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="passed" if not findings else "failed",
            duration=time.perf_counter() - start_time,
            issues_found=len(findings),
            is_blocker=self.is_blocker,
            findings=findings
        )
```

---

## Frame Metadata (frame.yaml)

### Required Fields

```yaml
name: "Frame Display Name"        # User-facing name
id: "frame-id"                     # Unique identifier (kebab-case)
version: "1.0.0"                   # Semantic versioning
author: "Author Name"              # Creator name
description: "What this validates" # Short description
```

### Optional Fields

```yaml
# Classification
category: "global"              # global | language-specific | framework-specific
priority: "medium"              # critical | high | medium | low
scope: "file_level"             # file_level | repository_level
is_blocker: false               # Block validation on failure

# Applicability filters
applicability:
  - language: "python"
  - language: "typescript"
  - framework: "fastapi"

# Warden version requirements
min_warden_version: "1.0.0"
max_warden_version: "2.0.0"

# Configuration schema
config_schema:
  my_setting:
    type: "boolean"
    default: true
    description: "Setting description"

# Tags for discoverability
tags:
  - "security"
  - "cloud"
  - "aws"
```

### Validation Rules

- **ID Format**: kebab-case (e.g., `redis-security`)
- **Version Format**: Semantic versioning (`1.0.0`)
- **Category**: Must be one of the enum values
- **Priority**: Must be one of the enum values
- **Applicability**: Must have `language` or `framework` field

---

## Implementing Validation Logic

### Basic Pattern

```python
async def execute(self, code_file: CodeFile) -> FrameResult:
    findings: List[Finding] = []

    # 1. Parse/analyze code
    content = code_file.content
    lines = content.split("\n")

    # 2. Run checks
    for i, line in enumerate(lines, 1):
        if self._is_violation(line):
            findings.append(Finding(
                id=f"{self.frame_id}-violation-{i}",
                severity="critical",
                message="Violation description",
                location=f"{code_file.path}:{i}",
                detail="How to fix",
                code=line
            ))

    # 3. Return result
    return FrameResult(
        frame_id=self.frame_id,
        frame_name=self.name,
        status="failed" if findings else "passed",
        duration=0.1,
        issues_found=len(findings),
        is_blocker=self.is_blocker,
        findings=findings
    )
```

### Using Configuration

```python
def __init__(self, config: Dict[str, Any] | None = None):
    super().__init__(config)

    # Access configuration
    self.check_ssl = self.config.get("check_ssl", True)
    self.allowed_hosts = self.config.get("allowed_hosts", [])

async def execute(self, code_file: CodeFile) -> FrameResult:
    if self.check_ssl:
        # Perform SSL check
        pass
```

### Pattern Matching

```python
import re

INSECURE_PATTERNS = [
    r"eval\s*\(",                    # eval() usage
    r"exec\s*\(",                    # exec() usage
    r"pickle\.loads\s*\([^)]*input", # pickle on user input
]

for pattern in INSECURE_PATTERNS:
    if re.search(pattern, code_file.content):
        findings.append(...)
```

### AST Analysis

```python
import ast

try:
    tree = ast.parse(code_file.content)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id == "eval":
                    findings.append(...)
except SyntaxError:
    # Handle syntax errors gracefully
    pass
```

---

## Testing Your Frame

### Test Structure

```python
# tests/test_frame.py
import pytest
from warden.validation.domain.frame import CodeFile
from frame import MyValidatorFrame


@pytest.mark.asyncio
async def test_frame_initialization():
    """Test frame can be initialized."""
    frame = MyValidatorFrame()
    assert frame.name == "My Custom Validator"
    assert frame.version == "1.0.0"


@pytest.mark.asyncio
async def test_frame_detects_violation():
    """Test frame detects known violations."""
    frame = MyValidatorFrame()

    code_file = CodeFile(
        path="test.py",
        content='eval(user_input)',  # Known violation
        language="python",
    )

    result = await frame.execute(code_file)

    assert result.status == "failed"
    assert len(result.findings) > 0
    assert result.findings[0].severity == "critical"


@pytest.mark.asyncio
async def test_frame_passes_valid_code():
    """Test frame passes on valid code."""
    frame = MyValidatorFrame()

    code_file = CodeFile(
        path="test.py",
        content="def safe_function(): return True",
        language="python",
    )

    result = await frame.execute(code_file)

    assert result.status == "passed"
    assert len(result.findings) == 0
```

### Running Tests

```bash
# Run all tests
pytest ~/.warden/frames/my-validator/tests/

# Run with coverage
pytest --cov=frame tests/

# Run specific test
pytest tests/test_frame.py::test_frame_detects_violation -v
```

---

## Distribution & Installation

### Local Installation (Recommended for Development)

```bash
# Copy to frames directory
cp -r my-validator ~/.warden/frames/

# Verify installation
warden frame list

# Add to project config
echo "  - myvalidator" >> .warden/config.yaml

# Test in pipeline
warden scan run . --verbose
```

**Frame ID Naming:**
- Class: `MyValidatorFrame` → Frame ID: `myvalidator` (snake_case)
- Always use `warden frame list` to verify exact frame ID
- Config uses frame ID, not class name or directory name

### Environment Variable

```bash
# Add to environment
export WARDEN_FRAME_PATHS="/path/to/custom-frames:/another/path"

# Frames in these paths will be auto-discovered
warden frame list
```

### PyPI Package (Entry Points)

```toml
# pyproject.toml
[tool.poetry.plugins."warden.frames"]
my_validator = "warden_frame_my_validator.frame:MyValidatorFrame"
```

```bash
# Install package
pip install warden-frame-my-validator

# Frame is auto-discovered
warden frame list
```

---

## Best Practices

### 1. Follow Single Responsibility

```python
# ✅ GOOD: One clear purpose
class RedisSecurityFrame(ValidationFrame):
    """Redis security validation."""
    pass

# ❌ BAD: Too many responsibilities
class AllSecurityChecksFrame(ValidationFrame):
    """SQL, Redis, MongoDB, AWS, Azure..."""
    pass
```

### 2. Provide Clear Messages

```python
# ✅ GOOD: Actionable message
Finding(
    severity="critical",
    message="Redis connection without SSL detected",
    detail="Add 'ssl=true' to connection string. Example: 'localhost:6379,ssl=true,password=...'"
)

# ❌ BAD: Vague message
Finding(
    severity="critical",
    message="Security issue found"
)
```

### 3. Handle Errors Gracefully

```python
async def execute(self, code_file: CodeFile) -> FrameResult:
    try:
        # Validation logic
        pass
    except SyntaxError as e:
        # Don't fail on syntax errors (file might be incomplete)
        logger.warning("syntax_error", error=str(e))
        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="warning",
            duration=0.0,
            issues_found=0,
            is_blocker=False,
            findings=[]
        )
```

### 4. Use Structured Logging

```python
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

async def execute(self, code_file: CodeFile) -> FrameResult:
    logger.info(
        "frame_execution_started",
        frame=self.name,
        file_path=code_file.path,
        file_size=code_file.size_bytes,
    )

    # ... validation logic ...

    logger.info(
        "frame_execution_completed",
        frame=self.name,
        status=result.status,
        findings_count=len(findings),
        duration=f"{duration:.2f}s",
    )
```

### 5. Write Comprehensive Tests

```python
# Test all code paths
def test_empty_file():
    pass

def test_syntax_error():
    pass

def test_multiple_violations():
    pass

def test_edge_cases():
    pass

def test_configuration_options():
    pass
```

---

## Examples

### Example 1: Redis Security Frame

```python
class RedisSecurityFrame(ValidationFrame):
    """Validates Redis connection security."""

    name = "Redis Security Validator"
    description = "Ensures Redis connections use SSL and proper authentication"
    category = FrameCategory.GLOBAL
    priority = FramePriority.CRITICAL
    is_blocker = True

    async def execute(self, code_file: CodeFile) -> FrameResult:
        findings = []

        # Check for Redis connection strings
        redis_pattern = r'redis://[^@]*@'

        if re.search(redis_pattern, code_file.content):
            # Found Redis connection

            # Check SSL
            if "ssl=true" not in code_file.content.lower():
                findings.append(Finding(
                    id="redis-no-ssl",
                    severity="critical",
                    message="Redis connection without SSL",
                    location=code_file.path,
                    detail="Add 'ssl=true' to connection string"
                ))

            # Check authentication
            if "password=" not in code_file.content.lower():
                findings.append(Finding(
                    id="redis-no-auth",
                    severity="high",
                    message="Redis connection without authentication",
                    location=code_file.path,
                    detail="Add password to connection string"
                ))

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="failed" if findings else "passed",
            duration=0.1,
            issues_found=len(findings),
            is_blocker=self.is_blocker,
            findings=findings
        )
```

### Example 2: OWASP Top 10 Frame

```python
class OWASPTop10Frame(ValidationFrame):
    """Validates against OWASP Top 10 vulnerabilities."""

    name = "OWASP Top 10 Validator"
    description = "Checks for OWASP Top 10 security vulnerabilities"
    category = FrameCategory.GLOBAL
    priority = FramePriority.CRITICAL
    is_blocker = True

    VULNERABILITY_PATTERNS = {
        "A01:2021-Broken Access Control": [
            r"@app\.route\([^)]*\)",  # Routes without auth check
        ],
        "A02:2021-Cryptographic Failures": [
            r"hashlib\.md5",  # Weak hashing
            r"hashlib\.sha1",
        ],
        "A03:2021-Injection": [
            r"execute\s*\([^)]*%s",  # SQL injection
            r"eval\s*\(",           # Code injection
        ],
    }

    async def execute(self, code_file: CodeFile) -> FrameResult:
        findings = []

        for vuln_name, patterns in self.VULNERABILITY_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, code_file.content):
                    findings.append(Finding(
                        id=f"owasp-{vuln_name.split(':')[0]}",
                        severity="critical",
                        message=f"OWASP {vuln_name} detected",
                        location=code_file.path,
                        detail=f"Pattern: {pattern}"
                    ))

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="failed" if findings else "passed",
            duration=0.1,
            issues_found=len(findings),
            is_blocker=self.is_blocker,
            findings=findings
        )
```

---

## Troubleshooting

### Frame Not Discovered

```bash
# Check frame directory
ls -la ~/.warden/frames/my-frame/

# Verify frame.yaml exists
cat ~/.warden/frames/my-frame/frame.yaml

# Check logs
python3 -m warden.cli.main frame list --verbose
```

### Validation Errors

```bash
# Validate frame structure
warden frame validate ~/.warden/frames/my-frame

# Check YAML syntax
python3 -c "import yaml; yaml.safe_load(open('~/.warden/frames/my-frame/frame.yaml'))"
```

### Import Errors

```python
# Make sure all dependencies are importable
# Add __init__.py to directories
touch ~/.warden/frames/my-frame/__init__.py
touch ~/.warden/frames/my-frame/checks/__init__.py
```

### Frame Not Executing

**Problem:** Frame discovered but not executing in pipeline.

**Solution 1: Check Frame ID in Config**
```bash
# Get exact frame ID
warden frame list

# Use correct ID in config (snake_case, not kebab-case!)
# .warden/config.yaml
frames:
  - myvalidator  # ✅ Correct (frame_id)
  # - my-validator  # ❌ Wrong (kebab-case not auto-converted)
```

**Solution 2: Check Verbose Output**
```bash
warden scan run . --verbose
# Look for: "Available frames: ..." and "✓ Loaded: ..."
```

**Solution 3: Check Applicability Filters**
```yaml
# frame.yaml - Remove or adjust applicability
applicability:
  - language: "python"  # Only runs on Python files
```

**Solution 4: Override in Config**
```yaml
# .warden/config.yaml
frames:
  myvalidator:
    enabled: true
    force_execute: true
```

---

## Pipeline Integration Details

### How Custom Frames are Loaded

Warden uses **dynamic frame discovery** instead of hardcoded imports:

```python
# scan.py / validate.py (automatic)
from warden.validation.infrastructure.frame_registry import get_registry

registry = get_registry()
frame_map = registry.get_all_frames_as_dict()
# Returns: {'security': SecurityFrame, 'redissecurity': RedisSecurityFrame, ...}

# Load from config
for frame_name in config['frames']:
    if frame_name in frame_map:
        frames.append(frame_map[frame_name]())
```

**Benefits:**
- ✅ No code changes needed to add custom frames
- ✅ Frames auto-discovered on every run
- ✅ Works with `warden scan`, `warden validate`, and all CLI commands
- ✅ Supports entry points, local directories, and environment paths

### Configuration Examples

**Basic Usage:**
```yaml
# .warden/config.yaml
frames:
  - security           # Built-in
  - redissecurity      # Custom (from ~/.warden/frames/redis-security/)
  - mongodbsecurity    # Custom
```

**Advanced Configuration:**
```yaml
frames:
  - security
  - redissecurity:
      check_ssl: true
      check_auth: true
      allowed_hosts: ["localhost", "staging.redis.com"]
```

**Multi-Source Discovery:**
```bash
# Environment variable for shared frames
export WARDEN_FRAME_PATHS="/company/security:/team/custom"

# PyPI package (entry point)
pip install warden-frame-company-security

# Local development
cp -r my-frame ~/.warden/frames/

# All discovered automatically!
warden frame list
```

---

## Additional Resources

- [Built-in Frames Source Code](../src/warden/validation/frames/)
- [Frame Development Examples](../examples/custom-frames/)
- [Panel Integration Guide](./PANEL_INTEGRATION.md)
- [Marketplace Documentation](./FRAME_MARKETPLACE.md) *(Coming Soon)*

---

## Quick Reference

### Common Commands
```bash
# Development
warden frame create my-validator --priority high --blocker
warden frame validate ~/.warden/frames/my-validator
pytest ~/.warden/frames/my-validator/tests/

# Discovery
warden frame list                    # List all frames
warden frame info myvalidator        # Show frame details

# Integration
warden scan run . --verbose          # Test in pipeline
warden validate run file.py          # Test on single file
```

### Frame ID Conversion
| Class Name | Frame ID (Use in Config) |
|------------|--------------------------|
| `RedisSecurityFrame` | `redissecurity` |
| `MyValidatorFrame` | `myvalidator` |
| `OWASPTop10Frame` | `owasp top10` |
| `AWS_S3_SecurityFrame` | `aws_s3_security` |

**Rule:** Class name → snake_case → remove "Frame" suffix = frame_id

---

**Last Updated**: 2025-12-22
**Warden Version**: 1.0.0
**Status**: Production Ready - Phase 1 (Python Custom Frames)
**Pipeline Integration**: ✅ Fully Operational
