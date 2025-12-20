# Warden Pluggable Frame System - Community Validation Frames

> **Vision:** Enable the community to create and share custom validation frames/checks without modifying Warden Core.

**Architecture:** Modular Frame System + Plugin Discovery Mechanism
**Status:** Design Document - Ready for Implementation
**Last Updated:** 2025-12-20

---

## 🎯 What is this?

This is a **Pluggable Validation Frame System** consisting of two layers:

1. **Frame System (Core)**: Modular validation architecture where each frame is an independent validation strategy
2. **Plugin Mechanism (Distribution)**: Discovery system that allows community to add custom frames

**Think of it as:**
- **Frames** = Validation strategies (Security, Chaos, Fuzz, YOUR_CUSTOM_FRAME)
- **Pluggable** = Community can add new frames without modifying Warden
- **Modular** = Each frame is independent, composable, reusable

---

## 🎯 Goals

1. **Extensibility**: Community can create custom frames without forking Warden
2. **Portability**: Frames are standalone packages (PyPI, Git, local)
3. **Discoverability**: Auto-discovery mechanism for installed frames
4. **Safety**: Sandboxing and validation before execution
5. **Marketplace**: Future community marketplace for sharing frames

---

## 🏗️ Plugin Architecture

### Plugin Types

```
1. Built-in Frames (Core)
   - Security, Chaos, Fuzz, Property, Stress, Architectural
   - Shipped with Warden Core
   - Always available

2. Official Frames (Warden Team)
   - warden-frame-dockerfile
   - warden-frame-kubernetes
   - warden-frame-terraform
   - Maintained by Warden team
   - Published on PyPI

3. Community Frames (User-created)
   - warden-frame-company-standards
   - warden-frame-myorg-security
   - warden-frame-custom-ai-review
   - Published by community on PyPI or Git
   - Can be private or public
```

---

## 📦 Plugin Package Structure

### Minimal Community Frame Package

```
warden-frame-mycompany-security/
├── pyproject.toml                    # Poetry/setuptools config
├── README.md                         # Documentation
├── plugin.yaml                       # Plugin manifest (metadata)
├── src/
│   └── warden_frame_mycompany_security/
│       ├── __init__.py
│       ├── frame.py                  # Frame implementation
│       └── config.py                 # Frame configuration
└── tests/
    └── test_frame.py
```

### Example: pyproject.toml

```toml
[tool.poetry]
name = "warden-frame-mycompany-security"
version = "1.0.0"
description = "Custom security checks for MyCompany coding standards"
authors = ["Your Name <you@mycompany.com>"]

[tool.poetry.dependencies]
python = "^3.11"
warden-core = "^0.1.0"  # Declares dependency on Warden Core

# Plugin entry point (auto-discovery)
[tool.poetry.plugins."warden.frames"]
mycompany_security = "warden_frame_mycompany_security.frame:MyCompanySecurityFrame"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

### Example: plugin.yaml (Metadata)

```yaml
name: MyCompany Security Frame
id: mycompany-security
version: 1.0.0
author: Your Name
author_email: you@mycompany.com
description: Custom security checks for MyCompany coding standards
category: security
priority: high

# Warden Core compatibility
compatibility:
  min_version: 0.1.0
  max_version: 1.0.0

# Plugin configuration schema
config_schema:
  type: object
  properties:
    api_key_patterns:
      type: array
      items:
        type: string
      default: ["MY_COMPANY_.*"]

    forbidden_imports:
      type: array
      items:
        type: string
      default: ["requests", "urllib"]  # Force use of httpx

# Languages/frameworks this frame applies to
applicability:
  - python
  - javascript
  - typescript

# Tags for discovery
tags:
  - security
  - api-keys
  - company-standards

# Documentation
documentation_url: https://github.com/mycompany/warden-frame-mycompany-security
issues_url: https://github.com/mycompany/warden-frame-mycompany-security/issues
```

### Example: frame.py (Implementation)

```python
"""
MyCompany Security Frame - Custom security validation.

This frame checks for MyCompany-specific security requirements.
"""

from typing import Dict, Any
from warden.validation.domain.frame import ValidationFrame, FrameResult
from warden.validation.domain.enums import FrameCategory, FramePriority
from warden.shared.domain.models import CodeFile


class MyCompanySecurityFrame(ValidationFrame):
    """
    Custom security checks for MyCompany coding standards.

    Checks:
    - Company-specific API key patterns
    - Forbidden imports (enforce httpx over requests)
    - Internal service authentication requirements
    """

    # Metadata
    name = "MyCompany Security Frame"
    description = "Custom security checks for MyCompany coding standards"
    category = FrameCategory.SECURITY
    priority = FramePriority.HIGH
    is_blocker = True
    version = "1.0.0"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize frame with custom configuration.

        Args:
            config: Frame configuration from plugin.yaml or user settings
        """
        super().__init__()
        self.config = config or {}
        self.api_key_patterns = self.config.get("api_key_patterns", ["MY_COMPANY_.*"])
        self.forbidden_imports = self.config.get("forbidden_imports", ["requests", "urllib"])

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """
        Execute MyCompany security checks.

        Args:
            code_file: Code file to validate

        Returns:
            Validation result with findings
        """
        findings = []

        # Check 1: Detect company API keys in code
        for pattern in self.api_key_patterns:
            if pattern in code_file.content:
                findings.append({
                    "severity": "critical",
                    "message": f"Hardcoded API key detected: {pattern}",
                    "line": self._find_line_number(code_file.content, pattern),
                    "suggestion": "Move API keys to environment variables or Azure Key Vault"
                })

        # Check 2: Forbidden imports (enforce httpx)
        for forbidden in self.forbidden_imports:
            import_statement = f"import {forbidden}"
            if import_statement in code_file.content:
                findings.append({
                    "severity": "high",
                    "message": f"Forbidden import detected: {forbidden}",
                    "line": self._find_line_number(code_file.content, import_statement),
                    "suggestion": f"Use httpx instead of {forbidden} (company standard)"
                })

        # Check 3: Internal service authentication (company-specific)
        if "internal.mycompany.com" in code_file.content:
            if "X-MyCompany-Auth" not in code_file.content:
                findings.append({
                    "severity": "medium",
                    "message": "Internal service call missing authentication header",
                    "suggestion": "Add X-MyCompany-Auth header for internal API calls"
                })

        return FrameResult(
            frame_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={
                "total_checks": 3,
                "config": self.config
            }
        )

    def _find_line_number(self, content: str, pattern: str) -> int:
        """Find line number of pattern in content."""
        for i, line in enumerate(content.split("\n"), start=1):
            if pattern in line:
                return i
        return 0
```

---

## 🔍 Plugin Discovery Mechanisms

### 1. Entry Points (Preferred - PyPI packages)

```python
# Warden Core discovers plugins via setuptools/poetry entry points
import pkg_resources

def discover_frames_via_entry_points() -> List[Type[ValidationFrame]]:
    """Discover frames via Python entry points."""
    frames = []

    for entry_point in pkg_resources.iter_entry_points("warden.frames"):
        try:
            frame_class = entry_point.load()
            frames.append(frame_class)
        except Exception as e:
            logger.warning(f"Failed to load frame {entry_point.name}: {e}")

    return frames
```

**User installs:**
```bash
pip install warden-frame-mycompany-security
# Frame is automatically discovered!
```

### 2. Directory-based Discovery (Local plugins)

```python
# User places plugin in ~/.warden/plugins/
~/.warden/plugins/
├── mycompany-security/
│   ├── plugin.yaml
│   └── frame.py
└── custom-ai-review/
    ├── plugin.yaml
    └── frame.py

def discover_frames_from_directory(plugin_dir: Path) -> List[Type[ValidationFrame]]:
    """Discover frames from local plugin directory."""
    frames = []

    for plugin_path in plugin_dir.glob("*/plugin.yaml"):
        plugin_dir = plugin_path.parent

        # Load plugin metadata
        with open(plugin_path) as f:
            metadata = yaml.safe_load(f)

        # Import frame module
        frame_module = import_plugin_module(plugin_dir / "frame.py")
        frame_class = getattr(frame_module, metadata["class_name"])

        frames.append(frame_class)

    return frames
```

**User creates:**
```bash
mkdir -p ~/.warden/plugins/mycompany-security
# Add plugin.yaml and frame.py
```

### 3. Environment Variable (Custom paths)

```bash
# User can specify additional plugin paths
export WARDEN_PLUGIN_PATHS="/opt/company-plugins:/home/user/custom-frames"
```

---

## 🛡️ Plugin Safety & Validation

### Pre-execution Validation

```python
class PluginValidator:
    """Validate plugins before execution."""

    def validate_plugin(self, frame_class: Type[ValidationFrame]) -> bool:
        """
        Validate plugin meets safety requirements.

        Checks:
        - Implements required interface
        - Compatible with Warden Core version
        - Has valid metadata
        - No malicious imports (optional)
        """
        # Check interface
        if not issubclass(frame_class, ValidationFrame):
            raise PluginValidationError("Frame must inherit from ValidationFrame")

        # Check required attributes
        required_attrs = ["name", "description", "category", "priority"]
        for attr in required_attrs:
            if not hasattr(frame_class, attr):
                raise PluginValidationError(f"Missing required attribute: {attr}")

        # Check version compatibility
        if hasattr(frame_class, "min_warden_version"):
            if WARDEN_VERSION < frame_class.min_warden_version:
                raise PluginValidationError("Incompatible Warden version")

        return True
```

### Execution Sandboxing

```python
import asyncio

async def execute_frame_with_timeout(
    frame: ValidationFrame,
    code_file: CodeFile,
    timeout: int = 30
) -> FrameResult:
    """
    Execute frame with timeout and resource limits.

    Args:
        frame: Validation frame to execute
        code_file: Code file to validate
        timeout: Execution timeout in seconds

    Returns:
        Frame result

    Raises:
        TimeoutError: If frame exceeds timeout
    """
    try:
        result = await asyncio.wait_for(
            frame.execute(code_file),
            timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        logger.error(f"Frame {frame.name} exceeded timeout of {timeout}s")
        raise
```

---

## 📋 Plugin Configuration

### User Configuration (.warden/config.yaml)

```yaml
# Project-level plugin configuration
plugins:
  # Enable/disable specific frames
  enabled:
    - security
    - chaos
    - mycompany-security  # Community plugin

  disabled:
    - stress  # Disable stress testing

  # Frame-specific configuration
  frame_config:
    mycompany-security:
      api_key_patterns:
        - "MY_COMPANY_API_.*"
        - "INTERNAL_SERVICE_KEY_.*"
      forbidden_imports:
        - "requests"
        - "urllib"
        - "subprocess"  # Company disallows subprocess

    security:
      max_severity: critical
      fail_on_critical: true
```

### Runtime Configuration (API)

```python
# Programmatic configuration
from warden.validation import FrameExecutor

executor = FrameExecutor(
    enabled_frames=["security", "mycompany-security"],
    frame_config={
        "mycompany-security": {
            "api_key_patterns": ["MY_COMPANY_.*"]
        }
    }
)

result = await executor.execute_all(code_file)
```

---

## 🏪 Plugin Marketplace (Future)

### Marketplace Features

```yaml
# plugins.warden.dev registry

Featured Plugins:
  - warden-frame-dockerfile
    Author: Warden Team
    Downloads: 10K
    Rating: 4.8/5
    Category: Infrastructure

  - warden-frame-sql-injection
    Author: security-community
    Downloads: 5K
    Rating: 4.9/5
    Category: Security

  - warden-frame-performance
    Author: perf-team
    Downloads: 2K
    Rating: 4.5/5
    Category: Performance
```

### Discovery & Installation

```bash
# Search marketplace
warden plugin search security

# Install from marketplace
warden plugin install warden-frame-dockerfile

# Install from Git
warden plugin install git+https://github.com/mycompany/warden-frame-custom

# Install from local directory
warden plugin install ./my-custom-frame

# List installed plugins
warden plugin list

# Update plugins
warden plugin update warden-frame-dockerfile
```

---

## 🔐 Security Best Practices

### For Plugin Developers

1. **Minimal Dependencies**: Avoid heavy dependencies
2. **No Network Calls**: Unless explicitly documented and user-approved
3. **No File System Writes**: Read-only by default
4. **Error Handling**: Graceful failure, never crash Warden
5. **Performance**: Execute within 30s timeout
6. **Documentation**: Clear README with examples

### For Plugin Users

1. **Review Source Code**: Always review community plugins before installation
2. **Use Virtual Environments**: Isolate plugin dependencies
3. **Pin Versions**: Specify exact versions in requirements
4. **Monitor Logs**: Check for suspicious activity
5. **Report Issues**: Report malicious plugins to Warden team

---

## 📊 Plugin Metadata Schema

```yaml
# Complete plugin.yaml schema
name: String (required)
id: String (required, unique, kebab-case)
version: String (required, semver)
author: String (required)
author_email: String (optional)
description: String (required)
category: Enum (security|performance|quality|custom)
priority: Enum (critical|high|medium|low)
is_blocker: Boolean (default: false)

compatibility:
  min_version: String (semver)
  max_version: String (semver)

config_schema:
  type: object
  properties: {...}

applicability:
  languages: [String]
  frameworks: [String]

tags: [String]

documentation_url: String (optional)
repository_url: String (optional)
issues_url: String (optional)
license: String (default: MIT)

# For marketplace submission
marketplace:
  featured: Boolean
  verified: Boolean
  downloads: Integer
  rating: Float
```

---

## 🚀 Implementation Phases

### Phase 1: Core Plugin System (Week 1)
- ✅ ValidationFrame base class
- ✅ Entry point discovery
- ✅ Plugin validation
- ✅ Timeout/sandboxing

### Phase 2: Local Plugins (Week 2)
- ✅ Directory-based discovery (~/.warden/plugins)
- ✅ plugin.yaml manifest
- ✅ Frame configuration
- ✅ Documentation

### Phase 3: Distribution (Week 3)
- ✅ PyPI publishing guide
- ✅ Example community frames
- ✅ CLI commands (install, list, update)

### Phase 4: Marketplace (Month 2)
- 🔮 Plugin registry API
- 🔮 Web UI for discovery
- 🔮 Rating/review system
- 🔮 Plugin verification

---

## 📝 Example Use Cases

### Company-Specific Standards

```python
# warden-frame-acme-standards
class AcmeStandardsFrame(ValidationFrame):
    """Enforce ACME Corp coding standards."""

    - No print() statements (use logging)
    - All functions must have type hints
    - All classes must have docstrings
    - API keys must use Azure Key Vault
    - Database queries must use parameterized queries
```

### Language-Specific Checks

```python
# warden-frame-python-async
class PythonAsyncFrame(ValidationFrame):
    """Python async/await best practices."""

    - Detect blocking I/O in async functions
    - Ensure proper async context managers
    - Check for missing 'await' keywords
    - Validate asyncio event loop usage
```

### Framework-Specific Checks

```python
# warden-frame-fastapi
class FastAPIFrame(ValidationFrame):
    """FastAPI best practices."""

    - Dependency injection usage
    - Proper response models
    - Error handling (HTTPException)
    - Pydantic model validation
```

---

**Status:** Design complete - Ready for plugin system implementation
**Next:** Implement ValidationFrame base class with plugin support
