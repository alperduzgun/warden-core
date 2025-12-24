# Warden AST Provider Plugin System

> **Purpose:** Modular AST provider system - Users install only the language providers they need
> **Created:** 2025-12-21
> **Status:** Implementation Guide & Research Report

---

## 🎯 EXECUTIVE SUMMARY

**Problem:** Users don't need all language AST providers. Installing all dependencies (JavaParser, Roslyn, etc.) creates dependency hell.

**Solution:** Plugin-based architecture where users install only needed providers via CLI.

```bash
# Minimal installation
pip install warden  # Only Python provider (built-in)

# Add Java support
warden providers install java

# Add C# support
warden providers install csharp

# List installed
warden providers list
```

---

## 🏗️ ARCHITECTURE OVERVIEW

### Distribution Strategy: Core + Separate PyPI Packages

```
warden (core)
├── Built-in: PythonASTProvider (zero dependency)
├── Optional: TreeSitterProvider (pip install warden[tree-sitter])
└── Plugin System (setuptools entry points)

warden-ast-java (separate package)
├── JavaParserProvider
└── Auto-registers via entry points

warden-ast-csharp (separate package)
├── RoslynProvider
└── Auto-registers via entry points

warden-ast-typescript (separate package)
├── TypeScriptProvider
└── Auto-registers via entry points
```

### Auto-Discovery Mechanism

Warden uses **setuptools entry points** for plugin discovery:

```python
# warden-ast-java/pyproject.toml
[project.entry-points."warden.ast_providers"]
java = "warden_ast_java.provider:JavaParserProvider"
```

```python
# Warden automatically discovers and loads it
from importlib.metadata import entry_points

eps = entry_points(group='warden.ast_providers')
for ep in eps:
    provider_class = ep.load()
    provider = provider_class()
    # Provider registered!
```

---

## 📦 PACKAGE STRUCTURE

### Core Package: `warden`

**File: `pyproject.toml`**

```toml
[project]
name = "warden"
version = "0.1.0"
dependencies = [
    "click>=8.0",
    "pydantic>=2.0",
    "structlog>=23.0",
]

[project.optional-dependencies]
tree-sitter = [
    "tree-sitter>=0.20.0",
    "tree-sitter-languages>=1.8.0",
]

[project.entry-points."warden.ast_providers"]
python = "warden.ast.providers.python_ast_provider:PythonASTProvider"
```

### Extension Package: `warden-ast-java`

**Directory Structure:**

```
extensions/warden-ast-java/
├── pyproject.toml
├── README.md
├── tests/
│   └── test_java_provider.py
└── src/
    └── warden_ast_java/
        ├── __init__.py
        └── provider.py
```

**File: `pyproject.toml`**

```toml
[project]
name = "warden-ast-java"
version = "0.1.0"
description = "Java AST provider for Warden"
dependencies = [
    "warden>=0.1.0",
    "jpype1>=1.4.0",
]

[project.entry-points."warden.ast_providers"]
java = "warden_ast_java.provider:JavaParserProvider"

[project.urls]
Homepage = "https://github.com/your-org/warden-ast-java"
Repository = "https://github.com/your-org/warden-ast-java"
```

**File: `src/warden_ast_java/provider.py`**

```python
"""Java AST provider using JavaParser."""
from typing import Optional
from warden.ast.application.provider_interface import IASTProvider
from warden.ast.domain.enums import CodeLanguage, ProviderPriority
from warden.ast.domain.models import (
    ASTProviderMetadata,
    ParseResult,
    ParseStatus,
    ParseError,
)


class JavaParserProvider(IASTProvider):
    """
    Java AST provider using JavaParser library.

    Provides symbol resolution and semantic analysis for Java code.
    """

    def __init__(self):
        """Initialize JavaParser provider."""
        self._jvm_started = False

    @property
    def metadata(self) -> ASTProviderMetadata:
        """Provider metadata."""
        return ASTProviderMetadata(
            name="JavaParser",
            version="1.0.0",
            supported_languages=[CodeLanguage.JAVA],
            priority=ProviderPriority.NATIVE,
            description="Java AST provider with symbol resolution",
            requires_setup=True,
        )

    def supports_language(self, language: CodeLanguage) -> bool:
        """Check if language is supported."""
        return language == CodeLanguage.JAVA

    async def parse(
        self,
        source_code: str,
        language: CodeLanguage,
        file_path: Optional[str] = None
    ) -> ParseResult:
        """
        Parse Java source code to AST.

        Args:
            source_code: Java source code
            language: Must be CodeLanguage.JAVA
            file_path: Optional file path for error reporting

        Returns:
            ParseResult with universal AST
        """
        if not self.supports_language(language):
            return ParseResult(
                status=ParseStatus.FAILED,
                errors=[ParseError(
                    message=f"JavaParser does not support {language.value}"
                )]
            )

        try:
            # TODO: Implement JavaParser integration
            # 1. Start JVM if needed
            # 2. Parse with JavaParser
            # 3. Convert to universal AST
            # 4. Return ParseResult

            return ParseResult(
                status=ParseStatus.FAILED,
                errors=[ParseError(
                    message="JavaParser provider not fully implemented yet"
                )]
            )
        except Exception as e:
            return ParseResult(
                status=ParseStatus.FAILED,
                errors=[ParseError(message=str(e))]
            )

    async def validate(self) -> bool:
        """Validate provider setup."""
        try:
            import jpype
            return True
        except ImportError:
            return False
```

**File: `src/warden_ast_java/__init__.py`**

```python
"""Warden Java AST provider."""
from warden_ast_java.provider import JavaParserProvider

__all__ = ["JavaParserProvider"]
__version__ = "0.1.0"
```

**File: `README.md`**

```markdown
# Warden Java AST Provider

Java AST provider for Warden using JavaParser.

## Installation

```bash
pip install warden-ast-java
```

The provider auto-registers via setuptools entry points.

## Verification

```bash
warden providers list
# Should show: JavaParser (java)

warden providers test java
# Should show: ✅ Provider available for java
```

## Development

```bash
# Install in development mode
pip install -e .

# Run tests
pytest tests/
```

## License

MIT
```

---

## 🔧 CLI COMMANDS

### `warden providers` Command Group

**File: `src/warden/cli/providers.py`** (NEW)

```python
"""CLI commands for managing AST providers."""
import click
from typing import List, Optional
import subprocess
import sys


@click.group()
def providers():
    """Manage AST providers."""
    pass


@providers.command()
def list():
    """List installed AST providers."""
    from importlib.metadata import entry_points
    from warden.ast.domain.models import ASTProviderMetadata

    click.echo("📦 Installed AST Providers:\n")

    try:
        eps = entry_points(group='warden.ast_providers')
    except Exception as e:
        click.echo(f"❌ Failed to load providers: {e}")
        return

    for ep in eps:
        try:
            provider_class = ep.load()
            provider = provider_class()
            metadata = provider.metadata

            click.echo(f"  ✅ {metadata.name}")
            click.echo(f"     Languages: {', '.join(l.value for l in metadata.supported_languages)}")
            click.echo(f"     Priority: {metadata.priority.name}")
            click.echo(f"     Version: {metadata.version}")

            # Get package name
            package = "built-in"
            if hasattr(ep, 'dist') and ep.dist:
                package = ep.dist.name
            click.echo(f"     Package: {package}")
            click.echo()
        except Exception as e:
            click.echo(f"  ❌ {ep.name} (failed to load: {e})")
            click.echo()


@providers.command()
@click.argument('provider')
def install(provider: str):
    """Install an AST provider from PyPI."""
    # Map short names to package names
    package_map = {
        'java': 'warden-ast-java',
        'csharp': 'warden-ast-csharp',
        'typescript': 'warden-ast-typescript',
        'kotlin': 'warden-ast-kotlin',
        'go': 'warden-ast-go',
        'rust': 'warden-ast-rust',
    }

    package = package_map.get(provider, f'warden-ast-{provider}')

    click.echo(f"📦 Installing {package}...\n")

    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', package],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        click.echo(f"✅ Successfully installed {package}")
        click.echo("\nRun 'warden providers list' to see installed providers.")
    else:
        click.echo(f"❌ Failed to install {package}")
        click.echo(result.stderr)
        sys.exit(1)


@providers.command()
@click.argument('provider')
def remove(provider: str):
    """Remove an AST provider."""
    package_map = {
        'java': 'warden-ast-java',
        'csharp': 'warden-ast-csharp',
        'typescript': 'warden-ast-typescript',
        'kotlin': 'warden-ast-kotlin',
        'go': 'warden-ast-go',
        'rust': 'warden-ast-rust',
    }

    package = package_map.get(provider, f'warden-ast-{provider}')

    click.echo(f"🗑️  Removing {package}...\n")

    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'uninstall', '-y', package],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        click.echo(f"✅ Successfully removed {package}")
    else:
        click.echo(f"❌ Failed to remove {package}")
        click.echo(result.stderr)
        sys.exit(1)


@providers.command()
@click.argument('language')
def test(language: str):
    """Test if a language provider is available."""
    from warden.ast.domain.enums import CodeLanguage
    from warden.ast.application.provider_registry import ASTProviderRegistry

    try:
        lang = CodeLanguage(language)
    except ValueError:
        click.echo(f"❌ Unknown language: {language}")
        click.echo(f"\nSupported languages:")
        for l in CodeLanguage:
            if l != CodeLanguage.UNKNOWN:
                click.echo(f"  - {l.value}")
        sys.exit(1)

    registry = ASTProviderRegistry()
    registry.discover_providers()

    provider = registry.get_provider(lang)

    if provider:
        click.echo(f"✅ Provider available for {language}")
        click.echo(f"   Provider: {provider.metadata.name}")
        click.echo(f"   Priority: {provider.metadata.priority.name}")
    else:
        click.echo(f"❌ No provider available for {language}")
        click.echo(f"\n💡 Install one with: warden providers install {language}")
        sys.exit(1)
```

### Register CLI Commands

**File: `src/warden/cli/__init__.py`** (UPDATE)

```python
"""Warden CLI."""
import click
from warden.cli.providers import providers


@click.group()
def cli():
    """Warden - AI-powered code validation."""
    pass


# Register command groups
cli.add_command(providers)

# ... other commands ...
```

---

## 👤 USER WORKFLOWS

### Scenario 1: Java Developer

```bash
# Install Warden (minimal - Python only)
pip install warden

# Check what's installed
warden providers list
# Output:
# 📦 Installed AST Providers:
#   ✅ Python AST
#      Languages: python
#      Priority: NATIVE
#      Version: 1.0.0
#      Package: built-in

# Install Java provider
warden providers install java
# Output:
# 📦 Installing warden-ast-java...
# ✅ Successfully installed warden-ast-java

# Verify
warden providers list
# Output:
#   ✅ Python AST (built-in)
#   ✅ JavaParser
#      Languages: java
#      Priority: NATIVE
#      Package: warden-ast-java

# Test
warden providers test java
# Output:
# ✅ Provider available for java
#    Provider: JavaParser
#    Priority: NATIVE

# Use it!
warden validate src/main/java/
# → Automatically uses JavaParserProvider
```

### Scenario 2: Multi-Language Project

```bash
# Install core + tree-sitter (basic support for all languages)
pip install warden[tree-sitter]

# Add native providers for critical languages
warden providers install java
warden providers install csharp

# List all
warden providers list
# Output:
#   ✅ Python AST (built-in)
#   ✅ Tree-sitter (40+ languages)
#   ✅ JavaParser (java)
#   ✅ Roslyn (csharp)

# Validate entire project
warden validate . --recursive
# → Auto-selects best provider per file
#   - Java files: JavaParser
#   - C# files: Roslyn
#   - TypeScript: Tree-sitter
```

### Scenario 3: CI/CD Pipeline

```dockerfile
# Dockerfile
FROM python:3.11-slim

# Install Warden + specific providers
RUN pip install warden[tree-sitter] && \
    warden providers install java && \
    warden providers install csharp

# Validate code in CI
COPY . /app
WORKDIR /app
RUN warden validate .
```

---

## 🛠️ PLUGIN DEVELOPMENT GUIDE

### Creating a New Provider

#### Step 1: Package Structure

```bash
mkdir -p warden-ast-mylang/src/warden_ast_mylang
cd warden-ast-mylang
```

#### Step 2: `pyproject.toml`

```toml
[project]
name = "warden-ast-mylang"
version = "0.1.0"
description = "MyLang AST provider for Warden"
dependencies = [
    "warden>=0.1.0",
    "mylang-parser>=1.0.0",
]

[project.entry-points."warden.ast_providers"]
mylang = "warden_ast_mylang.provider:MyLangProvider"
```

#### Step 3: Implement Provider

```python
# src/warden_ast_mylang/provider.py
from warden.ast.application.provider_interface import IASTProvider
from warden.ast.domain.enums import CodeLanguage, ProviderPriority
from warden.ast.domain.models import ASTProviderMetadata, ParseResult


class MyLangProvider(IASTProvider):
    """MyLang AST provider."""

    @property
    def metadata(self) -> ASTProviderMetadata:
        return ASTProviderMetadata(
            name="MyLang Parser",
            version="1.0.0",
            supported_languages=[CodeLanguage.MYLANG],
            priority=ProviderPriority.NATIVE,
            description="MyLang AST provider with semantic analysis",
        )

    def supports_language(self, language: CodeLanguage) -> bool:
        return language == CodeLanguage.MYLANG

    async def parse(self, source_code: str, language: CodeLanguage) -> ParseResult:
        # 1. Parse with mylang-parser
        # 2. Convert to universal AST
        # 3. Return ParseResult
        pass

    async def validate(self) -> bool:
        # Check if dependencies available
        try:
            import mylang_parser
            return True
        except ImportError:
            return False
```

#### Step 4: Publish

```bash
python -m build
twine upload dist/*
```

#### Step 5: Users Install

```bash
warden providers install mylang
# or
pip install warden-ast-mylang
```

---

## 📊 PRIORITY SYSTEM

When multiple providers support the same language, Warden selects by priority:

```python
class ProviderPriority(IntEnum):
    NATIVE = 1        # Language-specific parser (JavaParser, Roslyn)
    SPECIALIZED = 2   # TypeScript compiler API, esprima
    TREE_SITTER = 3   # Universal fallback
    COMMUNITY = 4     # User-contributed plugins
    FALLBACK = 5      # Regex-based parsers
```

**Example:**

```
Language: Java
Installed Providers:
  - JavaParser (NATIVE = 1)
  - Tree-sitter (TREE_SITTER = 3)

Selected: JavaParser (lower priority value = higher priority)
```

---

## 🧪 TESTING

### Unit Tests

```python
# tests/test_java_provider.py
import pytest
from warden_ast_java.provider import JavaParserProvider
from warden.ast.domain.enums import CodeLanguage


@pytest.fixture
def provider():
    return JavaParserProvider()


def test_metadata(provider):
    metadata = provider.metadata
    assert metadata.name == "JavaParser"
    assert CodeLanguage.JAVA in metadata.supported_languages


def test_supports_java(provider):
    assert provider.supports_language(CodeLanguage.JAVA)
    assert not provider.supports_language(CodeLanguage.PYTHON)


@pytest.mark.asyncio
async def test_parse_simple_class(provider):
    source = """
    public class HelloWorld {
        public static void main(String[] args) {
            System.out.println("Hello");
        }
    }
    """

    result = await provider.parse(source, CodeLanguage.JAVA)
    assert result.is_success()
    assert result.ast_root is not None
```

### Integration Tests

```python
# tests/integration/test_provider_discovery.py
from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.enums import CodeLanguage


def test_java_provider_discovered():
    """Test that warden-ast-java is discovered."""
    registry = ASTProviderRegistry()
    registry.discover_providers()

    provider = registry.get_provider(CodeLanguage.JAVA)
    assert provider is not None
    assert provider.metadata.name == "JavaParser"
```

---

## 🚀 IMPLEMENTATION ROADMAP

### Phase 1: Core Plugin System (1 week) - CURRENT

✅ **Tasks:**
1. Create MD documentation (this file)
2. Implement CLI commands (providers list/install/remove/test)
3. Create first external provider skeleton (warden-ast-java)
4. Write plugin development guide

### Phase 2: Tree-sitter Implementation (1-2 weeks)

✅ **Tasks:**
1. Finish tree-sitter provider implementation
2. Test with 14 languages
3. Basic AST conversion for all languages

### Phase 3: Native Providers (2-3 weeks)

✅ **Tasks:**
1. Complete JavaParser provider (Java)
2. Implement Roslyn provider (C#)
3. Optional: TypeScript compiler API provider

### Phase 4: Community & Marketplace (Optional)

✅ **Tasks:**
1. Provider search command (PyPI search)
2. Provider templates/cookiecutter
3. Community contribution guide

---

## 📝 CODING STANDARDS (from warden_core_rules.md)

### File Organization

- ✅ Max 500 lines per file
- ✅ Single responsibility per module
- ✅ Type hints everywhere
- ✅ Docstrings (Google style)

### Provider Implementation Checklist

```python
# ✅ DO
class MyProvider(IASTProvider):
    """Clear docstring with purpose."""

    @property
    def metadata(self) -> ASTProviderMetadata:
        """Metadata with type hint."""
        return ASTProviderMetadata(...)

    async def parse(...) -> ParseResult:
        """Async parse method."""
        pass

# ❌ DON'T
class MyProvider:  # Missing IASTProvider
    def metadata(self):  # Not a property, no type hint
        return {...}  # Dict instead of ASTProviderMetadata

    def parse(...):  # Not async
        pass
```

### Error Handling

```python
# ✅ GOOD
async def parse(self, source_code: str, language: CodeLanguage) -> ParseResult:
    try:
        # Parse logic
        ast_root = self._parse_internal(source_code)
        return ParseResult(
            status=ParseStatus.SUCCESS,
            ast_root=ast_root
        )
    except SyntaxError as e:
        return ParseResult(
            status=ParseStatus.FAILED,
            errors=[ParseError(
                message=f"Syntax error: {e}",
                line=e.lineno,
                column=e.offset
            )]
        )
    except Exception as e:
        logger.error("parse_failed", error=str(e))
        return ParseResult(
            status=ParseStatus.FAILED,
            errors=[ParseError(message=str(e))]
        )
```

---

## 🎯 SUCCESS CRITERIA

- [x] MD documentation complete
- [ ] CLI commands implemented
- [ ] warden-ast-java skeleton created
- [ ] Plugin development guide written
- [ ] Entry points tested (install/discover works)
- [ ] All code follows warden_core_rules.md

---

## 📚 REFERENCES

- **Session Start Guide:** `temp/session-start.md`
- **Coding Standards:** `temp/warden_core_rules.md`
- **AST Architecture:** `temp/ast-architecture.md`
- **Provider Loader:** `src/warden/ast/application/provider_loader.py`
- **Provider Interface:** `src/warden/ast/application/provider_interface.py`

---

**Last Updated:** 2025-12-21
**Status:** ✅ Documentation Complete - Ready for Implementation
**Next Steps:**
1. Implement CLI commands (frontend-developer agent)
2. Create warden-ast-java skeleton (backend-architect agent)
3. Write plugin development guide (senior-code-reviewer agent)
