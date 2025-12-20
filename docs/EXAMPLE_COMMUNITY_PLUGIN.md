## Example Community Plugin - Template

Bu örnek, community developers için tam fonksiyonel bir Warden validation frame plugin'i gösterir.

### Proje Yapısı

```
warden-frame-mycompany-security/
├── README.md
├── LICENSE
├── pyproject.toml
├── plugin.yaml
├── .gitignore
├── src/
│   └── warden_frame_mycompany_security/
│       ├── __init__.py
│       ├── frame.py
│       └── config.py
└── tests/
    ├── __init__.py
    └── test_frame.py
```

### 1. pyproject.toml

```toml
[tool.poetry]
name = "warden-frame-mycompany-security"
version = "1.0.0"
description = "Custom security checks for MyCompany coding standards"
authors = ["Your Name <you@mycompany.com>"]
readme = "README.md"
homepage = "https://github.com/mycompany/warden-frame-mycompany-security"
repository = "https://github.com/mycompany/warden-frame-mycompany-security"
documentation = "https://github.com/mycompany/warden-frame-mycompany-security#readme"
keywords = ["warden", "security", "validation", "code-quality"]
license = "MIT"

[tool.poetry.dependencies]
python = "^3.11"
warden-core = "^0.1.0"

[tool.poetry.group.dev.dependencies]
pytest = "^7.4.4"
pytest-asyncio = "^0.23.3"
black = "^24.1.1"
ruff = "^0.1.14"

# Entry point for plugin discovery
[tool.poetry.plugins."warden.frames"]
mycompany_security = "warden_frame_mycompany_security.frame:MyCompanySecurityFrame"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"

[tool.black]
line-length = 100

[tool.ruff]
line-length = 100
select = ["E", "W", "F", "I"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

### 2. plugin.yaml

```yaml
name: MyCompany Security Frame
id: mycompany-security
version: 1.0.0
author: Your Name
author_email: you@mycompany.com
description: Custom security checks for MyCompany coding standards (API keys, forbidden imports, auth headers)
category: security
priority: high
is_blocker: true

# Warden Core compatibility
compatibility:
  min_version: 0.1.0
  max_version: 1.0.0

# Configuration schema (JSON Schema)
config_schema:
  type: object
  properties:
    api_key_patterns:
      type: array
      description: Regex patterns for company API keys
      items:
        type: string
      default: ["MY_COMPANY_API_.*", "INTERNAL_SERVICE_KEY_.*"]

    forbidden_imports:
      type: array
      description: Forbidden Python imports (enforce alternatives)
      items:
        type: string
      default: ["requests", "urllib"]

    require_auth_header:
      type: boolean
      description: Require X-MyCompany-Auth header for internal API calls
      default: true

# Languages this frame applies to
applicability:
  languages:
    - python
    - javascript
    - typescript

# Tags for marketplace
tags:
  - security
  - api-keys
  - company-standards
  - authentication

# Links
documentation_url: https://github.com/mycompany/warden-frame-mycompany-security#readme
repository_url: https://github.com/mycompany/warden-frame-mycompany-security
issues_url: https://github.com/mycompany/warden-frame-mycompany-security/issues
license: MIT
```

### 3. src/warden_frame_mycompany_security/frame.py

```python
"""
MyCompany Security Frame - Custom security validation.

Checks:
1. Company-specific API key patterns
2. Forbidden imports (enforce httpx over requests)
3. Internal service authentication (X-MyCompany-Auth header)
"""

import re
from typing import Dict, Any, List
from warden.validation.domain.frame import (
    ValidationFrame,
    FrameResult,
    Finding,
    FrameCategory,
    FramePriority,
    FrameApplicability,
    CodeFile,
)


class MyCompanySecurityFrame(ValidationFrame):
    """
    Custom security checks for MyCompany coding standards.

    This frame enforces company-specific security policies:
    - API key detection (prevent hardcoded secrets)
    - Import restrictions (enforce approved libraries)
    - Authentication headers for internal services
    """

    # Required metadata
    name = "MyCompany Security Frame"
    description = "Custom security checks for MyCompany coding standards"
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    is_blocker = True  # Block PR if critical issues found
    version = "1.0.0"
    author = "MyCompany Security Team"

    # Applicability
    applicability = [
        FrameApplicability.PYTHON,
        FrameApplicability.TYPESCRIPT,
        FrameApplicability.JAVASCRIPT,
    ]

    # Warden compatibility
    min_warden_version = "0.1.0"
    max_warden_version = "1.0.0"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """Initialize frame with configuration."""
        super().__init__(config)

        # Load configuration (with defaults)
        self.api_key_patterns = self.config.get(
            "api_key_patterns", ["MY_COMPANY_API_.*", "INTERNAL_SERVICE_KEY_.*"]
        )
        self.forbidden_imports = self.config.get(
            "forbidden_imports", ["requests", "urllib"]
        )
        self.require_auth_header = self.config.get("require_auth_header", True)

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """
        Execute MyCompany security checks.

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with findings
        """
        findings: List[Finding] = []

        # Check 1: Hardcoded API keys
        findings.extend(self._check_api_keys(code_file))

        # Check 2: Forbidden imports
        findings.extend(self._check_forbidden_imports(code_file))

        # Check 3: Internal service authentication
        if self.require_auth_header:
            findings.extend(self._check_internal_auth(code_file))

        # Determine status
        critical_count = sum(1 for f in findings if f.severity == "critical")
        high_count = sum(1 for f in findings if f.severity == "high")

        if critical_count > 0:
            status = "failed"
        elif high_count > 0:
            status = "warning"
        else:
            status = "passed"

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=0.0,  # Will be set by executor
            issues_found=len(findings),
            is_blocker=self.is_blocker and status == "failed",
            findings=findings,
            metadata={
                "checks_performed": ["api_keys", "forbidden_imports", "internal_auth"],
                "config": self.config,
            },
        )

    def _check_api_keys(self, code_file: CodeFile) -> List[Finding]:
        """Check for hardcoded API keys."""
        findings: List[Finding] = []

        for pattern in self.api_key_patterns:
            regex = re.compile(pattern)
            for line_num, line in enumerate(code_file.content.split("\n"), start=1):
                if regex.search(line):
                    findings.append(
                        Finding(
                            id=f"api-key-{line_num}",
                            severity="critical",
                            message=f"Hardcoded API key detected: {pattern}",
                            location=f"{code_file.path}:{line_num}",
                            detail=(
                                "Company policy: API keys MUST NOT be hardcoded. "
                                "Use environment variables or Azure Key Vault."
                            ),
                            code=line.strip(),
                        )
                    )

        return findings

    def _check_forbidden_imports(self, code_file: CodeFile) -> List[Finding]:
        """Check for forbidden imports."""
        findings: List[Finding] = []

        for forbidden in self.forbidden_imports:
            import_patterns = [
                f"import {forbidden}",
                f"from {forbidden} import",
            ]

            for pattern in import_patterns:
                for line_num, line in enumerate(code_file.content.split("\n"), start=1):
                    if pattern in line:
                        findings.append(
                            Finding(
                                id=f"forbidden-import-{line_num}",
                                severity="high",
                                message=f"Forbidden import: {forbidden}",
                                location=f"{code_file.path}:{line_num}",
                                detail=(
                                    f"Company policy: Use 'httpx' instead of '{forbidden}'. "
                                    "httpx is the approved HTTP client (async support, better error handling)."
                                ),
                                code=line.strip(),
                            )
                        )

        return findings

    def _check_internal_auth(self, code_file: CodeFile) -> List[Finding]:
        """Check for missing authentication headers on internal API calls."""
        findings: List[Finding] = []

        # Detect internal service calls
        internal_domain = "internal.mycompany.com"

        if internal_domain in code_file.content:
            # Check if X-MyCompany-Auth header is present
            if "X-MyCompany-Auth" not in code_file.content:
                # Find line with internal domain
                for line_num, line in enumerate(code_file.content.split("\n"), start=1):
                    if internal_domain in line:
                        findings.append(
                            Finding(
                                id=f"missing-auth-{line_num}",
                                severity="medium",
                                message="Internal service call missing authentication header",
                                location=f"{code_file.path}:{line_num}",
                                detail=(
                                    "Company policy: All calls to internal.mycompany.com "
                                    "MUST include 'X-MyCompany-Auth' header for authentication."
                                ),
                                code=line.strip(),
                            )
                        )
                        break  # Only report once per file

        return findings
```

### 4. tests/test_frame.py

```python
"""Tests for MyCompany Security Frame."""

import pytest
from warden_frame_mycompany_security.frame import MyCompanySecurityFrame
from warden.validation.domain.frame import CodeFile


@pytest.mark.asyncio
async def test_detects_hardcoded_api_key():
    """Test detection of hardcoded API keys."""
    code = '''
import os

# BAD: Hardcoded API key
MY_COMPANY_API_KEY = "sk-abc123-secret-key"

def get_api_key():
    return MY_COMPANY_API_KEY
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = MyCompanySecurityFrame()
    result = await frame.execute(code_file)

    # Should detect API key
    assert result.status == "failed"
    assert result.issues_found == 1
    assert result.findings[0].severity == "critical"
    assert "API key" in result.findings[0].message


@pytest.mark.asyncio
async def test_detects_forbidden_import():
    """Test detection of forbidden imports."""
    code = '''
import requests  # FORBIDDEN!

def fetch_data(url):
    return requests.get(url)
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = MyCompanySecurityFrame()
    result = await frame.execute(code_file)

    # Should detect forbidden import
    assert result.status == "warning"
    assert result.issues_found == 1
    assert result.findings[0].severity == "high"
    assert "Forbidden import" in result.findings[0].message


@pytest.mark.asyncio
async def test_passes_clean_code():
    """Test that clean code passes all checks."""
    code = '''
import httpx  # APPROVED!
import os

async def fetch_data(url):
    api_key = os.getenv("MY_COMPANY_API_KEY")  # GOOD: From env
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = MyCompanySecurityFrame()
    result = await frame.execute(code_file)

    # Should pass
    assert result.status == "passed"
    assert result.issues_found == 0


@pytest.mark.asyncio
async def test_custom_configuration():
    """Test frame with custom configuration."""
    config = {
        "api_key_patterns": ["CUSTOM_API_.*"],
        "forbidden_imports": ["urllib3"],
    }

    code = '''
import urllib3  # Custom forbidden
CUSTOM_API_KEY = "test"  # Custom pattern
'''

    code_file = CodeFile(
        path="test.py",
        content=code,
        language="python",
    )

    frame = MyCompanySecurityFrame(config=config)
    result = await frame.execute(code_file)

    # Should detect both custom rules
    assert result.issues_found == 2
```

### 5. README.md

```markdown
# Warden Frame - MyCompany Security

Custom security validation frame for MyCompany coding standards.

## Installation

```bash
pip install warden-frame-mycompany-security
```

The frame is automatically discovered by Warden via entry points.

## What it checks

1. **Hardcoded API Keys**: Detects company API key patterns
2. **Forbidden Imports**: Enforces approved libraries (httpx over requests)
3. **Internal Auth**: Ensures internal API calls include auth headers

## Configuration

In your `.warden/config.yaml`:

```yaml
plugins:
  frame_config:
    mycompany-security:
      api_key_patterns:
        - "MY_COMPANY_API_.*"
        - "INTERNAL_SERVICE_KEY_.*"
      forbidden_imports:
        - "requests"
        - "urllib"
      require_auth_header: true
```

## Development

```bash
# Install dependencies
poetry install

# Run tests
pytest

# Format code
black src/ tests/

# Lint
ruff check src/ tests/
```

## License

MIT
```

### Publishing to PyPI

```bash
# Build package
poetry build

# Publish to PyPI
poetry publish

# Or publish to private PyPI
poetry publish --repository mycompany-pypi
```

### Usage

```bash
# Install from PyPI
pip install warden-frame-mycompany-security

# Warden automatically discovers it
warden scan ./src

# Frame runs alongside built-in frames!
```

Bu template, community developers'ın kendi frame'lerini oluşturması için tam bir başlangıç noktası sağlar!
