# Warden Custom Frames - Developer Guide

**Create your own validation frames for any technology, framework, or security standard.**

## 🆕 What's New (v1.1.0 - December 2025)

### 🎉 Major Infrastructure Upgrades

1. **Config Auto-Generation** ✨
   - Define `config_schema` in `frame.yaml`
   - Warden automatically generates default config
   - No manual configuration needed!
   - Example: 8 config fields auto-created

2. **Project-Specific Frames** ✨
   - New location: `.warden/frames/` (project-local)
   - Version-controlled custom frames
   - Team-specific validation rules
   - Coexists with global frames

3. **CLI Integration** ✨
   - Custom frames visible in Warden CLI UI
   - Real-time status updates
   - Backend auto-discovery
   - Frame metadata display

**Quick Example:**
```yaml
# frame.yaml - Define schema
config_schema:
  check_ssl:
    type: "boolean"
    default: true

# .warden/config.yaml - Auto-generated!
frames_config:
  my-frame:
    enabled: true
    check_ssl: true  # ← Auto-generated from schema!
```

**See:** [FRAME_INFRASTRUCTURE_UPDATE.md](./FRAME_INFRASTRUCTURE_UPDATE.md) for full details.

---

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

2. **Custom Frames** (Python-based)
   - Created by developers or teams
   - **Global location**: `~/.warden/frames/` (all projects)
   - **Project location**: `.warden/frames/` (current project only) ✨ NEW!
   - Discovered automatically
   - Config auto-generated from `frame.yaml` ✨ NEW!

3. **Marketplace Frames** (WASM - Future)
   - Multi-language support (Rust, Go, Python)
   - Sandboxed execution
   - Community distribution

### Frame Locations ✨

Warden discovers frames from **TWO locations** (in priority order):

```
# 1. Global frames (all projects)
~/.warden/frames/
├── redis-security/
├── company-standards/
└── shared-utilities/

# 2. Project-specific frames (current project only)
<project>/.warden/frames/
├── team-custom-frame/
├── project-specific-validation/
└── temporary-dev-frame/
```

**When to use which:**

| Location | Use Case | Benefits |
|----------|----------|----------|
| **Global** (`~/.warden/frames/`) | Company-wide standards, reusable validations | Available in all projects |
| **Project** (`.warden/frames/`) | Team-specific rules, project requirements | Version controlled, isolated |

**Discovery order:**
1. Built-in frames (always available)
2. Entry points (PyPI packages)
3. Global frames (`~/.warden/frames/`)
4. Project frames (`.warden/frames/`) ← Highest priority for overrides

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

## Config Auto-Generation ✨ NEW!

### Overview

Warden automatically generates default configuration from your `frame.yaml` schema. No need to manually write config for every frame!

**How it works:**
1. Define `config_schema` in `frame.yaml`
2. Warden reads schema and extracts `default` values
3. Auto-generates config in `.warden/config.yaml`
4. You only override what you need!

### Basic Example

**frame.yaml:**
```yaml
config_schema:
  check_ssl:
    type: "boolean"
    default: true
    description: "Validate SSL usage"

  max_connections:
    type: "integer"
    default: 100
    description: "Maximum allowed connections"
```

**Auto-Generated Config:**
```yaml
# .warden/config.yaml
frames_config:
  my-frame:
    enabled: true
    check_ssl: true          # ← Auto-generated from schema!
    max_connections: 100     # ← Auto-generated from schema!
```

### Advanced Example (8 Config Fields)

**frame.yaml:**
```yaml
config_schema:
  enabled:
    type: "boolean"
    default: true

  check_hardcoded_credentials:
    type: "boolean"
    default: true

  check_missing_validation:
    type: "boolean"
    default: true

  check_insecure_defaults:
    type: "boolean"
    default: true

  sensitive_patterns:
    type: "array"
    default: ["API_KEY", "SECRET", "TOKEN", "PASSWORD"]

  allowed_values:
    type: "array"
    default: ["localhost", "127.0.0.1"]

  severity_level:
    type: "string"
    default: "critical"

  fail_on_missing:
    type: "boolean"
    default: false
```

**Auto-Generated Config (8 fields!):**
```yaml
frames_config:
  env-security:
    enabled: true
    check_hardcoded_credentials: true
    check_missing_validation: true
    check_insecure_defaults: true
    sensitive_patterns: ["API_KEY", "SECRET", "TOKEN", "PASSWORD"]
    allowed_values: ["localhost", "127.0.0.1"]
    severity_level: "critical"
    fail_on_missing: false
```

### Overriding Defaults

**Only override what you need:**
```yaml
# .warden/config.yaml
frames_config:
  env-security:
    enabled: true
    # Override only 2 out of 8 fields:
    severity_level: "high"              # Changed from "critical"
    sensitive_patterns: ["API_KEY"]     # Reduced from 4 to 1
    # Other 6 fields use auto-generated defaults!
```

### Supported Types

| Type | Example Default | Description |
|------|----------------|-------------|
| `boolean` | `true` / `false` | Enable/disable features |
| `string` | `"value"` | Text values |
| `integer` | `100` | Numeric values |
| `array` | `["a", "b"]` | Lists |
| `object` | `{key: value}` | Nested structures |

### Benefits

✅ **Zero Manual Config** - Defaults auto-generated
✅ **Type Safety** - Schema validates config
✅ **Documentation** - Schema describes each field
✅ **DRY Principle** - Single source of truth (frame.yaml)
✅ **Easy Overrides** - Only change what you need

**See also:** [FRAME_INFRASTRUCTURE_UPDATE.md](./FRAME_INFRASTRUCTURE_UPDATE.md) for implementation details.

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

## CLI Integration ✨ NEW!

### Overview

Custom frames are now fully integrated into the Warden CLI! They appear alongside built-in frames in the UI, with real-time status updates.

### How It Works

1. **Backend Discovery**
   - Backend scans `.warden/frames/` and `~/.warden/frames/` on startup
   - Loads frame metadata from `frame.yaml`
   - Registers frames in FrameRegistry
   - Merges config (defaults + overrides)

2. **CLI Display**
   - Frames appear in "Installed Frames" list
   - Shows frame name, priority, blocker status
   - Real-time status updates
   - Config management UI

### CLI UI Example

```
🛡️  WARDEN CODE ANALYSIS

Installed frames (7/7 enabled)

🔍 Search frames...

╭───────────────────────────────────────────────────────────────────────────╮
│                                                                           │
│  ▶  Security Analysis · Built-in · CRITICAL · ⚠ BLOCKER                   │
│                                                                           │
│  Detects SQL injection, XSS, secrets, and other security vulnerabilities  │
│                                                                           │
│                                                                           │
│  ✓ Chaos Engineering · Built-in · HIGH                                    │
│                                                                           │
│  Validates resilience against network failures and timeouts              │
│                                                                           │
│                                                                           │
│  ✓ Environment Security Validator · Custom · CRITICAL · ⚠ BLOCKER  ✨     │
│                                                                           │
│  Detects environment variable security issues and best practices         │
│                                                                           │
│                                                                           │
│  ✓ Demo Security Validator · Custom · HIGH  ✨                            │
│                                                                           │
│  Demo custom frame with auto-generated config                            │
│                                                                           │
╰───────────────────────────────────────────────────────────────────────────╯
```

### Backend Integration

**Frame Discovery Process:**

```
1. Backend starts (start_ipc_server.py)
   ↓
2. FrameRegistry.discover_all()
   ↓
3. Scans locations:
   - Built-in frames
   - Global: ~/.warden/frames/
   - Project: .warden/frames/  ✨
   ↓
4. Loads metadata (frame.yaml)
   ↓
5. Generates default config  ✨
   ↓
6. Merges with .warden/config.yaml
   ↓
7. Registers in CLI bridge
   ↓
8. Available in UI!
```

### Viewing Frames in CLI

```bash
# Start CLI
warden

# Navigate to Frames section
# → Press Tab to cycle through sections
# → Arrow keys to navigate frames
# → Enter to view details

# Backend logs show discovery:
[info] local_frame_loaded frame=EnvironmentSecurityFrame source=project
[info] local_frame_loaded frame=DemoSecurityFrame source=project
[info] 🎯 Loaded 7 validation frames
```

### Troubleshooting

**Frame Not Appearing in CLI:**

```bash
# 1. Check backend is running
ps aux | grep start_ipc_server.py

# 2. Check frame was discovered
tail -f .warden/backend.log | grep "frame_loaded"

# 3. Restart backend
pkill -9 -f start_ipc_server.py
rm -f .warden/backend.pid
warden  # Auto-restarts backend

# 4. Check frame ID matches config
python3 << 'EOF'
from warden.validation.infrastructure.frame_registry import FrameRegistry
registry = FrameRegistry()
frames = registry.discover_all()
for fid in registry.registered_frames:
    print(f"Frame ID: {fid}")
EOF
```

**Config Not Taking Effect:**

```yaml
# Ensure frame ID matches (use snake_case)
frames:
  - env-security  # ✅ Correct (from frame.yaml)

frames_config:
  env-security:   # ✅ Same ID
    enabled: true
```

### Real-Time Updates

The CLI updates frame status in real-time:

| Status | UI Display | Description |
|--------|------------|-------------|
| **Enabled** | `✓ Frame Name` | Frame is active and will execute |
| **Disabled** | `○ Frame Name [DISABLED]` | Frame is inactive |
| **Error** | `✗ Frame Name [ERROR]` | Frame failed to load |
| **Custom** | `Frame Name · Custom ✨` | Custom frame (non-built-in) |
| **Blocker** | `Frame Name · ⚠ BLOCKER` | Will block validation if fails |

### Frame Metadata Display

Click on a frame in CLI to see:

```
╭─── Environment Security Validator ───────────────────────────────────────╮
│                                                                           │
│  Type: Custom · Project-Specific                                         │
│  Priority: CRITICAL                                                       │
│  Blocker: Yes                                                             │
│  Version: 1.0.0                                                           │
│  Author: Warden Security Team                                             │
│                                                                           │
│  Description:                                                             │
│  Detects environment variable security issues and best practices         │
│  violations in your codebase.                                             │
│                                                                           │
│  Configuration (8 fields):                                                │
│  ✓ check_hardcoded_credentials: true                                     │
│  ✓ check_missing_env_validation: true                                    │
│  ✓ check_insecure_defaults: true                                         │
│  ✓ sensitive_patterns: ["API_KEY", "SECRET", ...]                        │
│  ✓ severity_level: critical                                              │
│  ... (3 more)                                                             │
│                                                                           │
│  Location: .warden/frames/env-security/                                  │
│                                                                           │
│  [E]dit Config | [V]iew Source | [T]est Frame | [D]isable               │
╰───────────────────────────────────────────────────────────────────────────╯
```

**See also:** [FRAME_INFRASTRUCTURE_UPDATE.md](./FRAME_INFRASTRUCTURE_UPDATE.md) for backend integration details.

---

## Additional Resources

- [Built-in Frames Source Code](../src/warden/validation/frames/)
- [Frame Development Examples](../examples/custom-frames/)
- [Frame Infrastructure Update](./FRAME_INFRASTRUCTURE_UPDATE.md) ✨ **NEW!**
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

**Last Updated**: 2025-12-26
**Warden Version**: 1.1.0
**Status**: Production Ready - Phase 2 (Config Auto-Generation + CLI Integration)
**Pipeline Integration**: ✅ Fully Operational
**New Features**: ✨ Config Auto-Generation | Project-Specific Frames | CLI Integration
