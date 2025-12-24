# Warden Java AST Provider

Java AST provider for Warden using JavaParser library.

## Overview

This package provides Java code parsing capabilities for Warden using the JavaParser library via JPype1 (Python-Java bridge). It implements Warden's AST provider interface to deliver native Java parsing with symbol resolution and semantic analysis.

## Features

- **Native Java Parsing**: Full Java syntax support (Java 8-21)
- **Symbol Resolution**: Resolve types, methods, and variables
- **Semantic Analysis**: Understand code semantics beyond syntax
- **Universal AST**: Converts JavaParser AST to Warden's universal format
- **Auto-Discovery**: Automatically registered via setuptools entry points

## Installation

### From PyPI (when published)

```bash
pip install warden-ast-java
```

### From Source

```bash
# Clone repository
git clone https://github.com/warden-team/warden-ast-java
cd warden-ast-java

# Install in development mode
pip install -e .

# Or install with dev dependencies
pip install -e ".[dev]"
```

## Usage

The provider automatically registers itself via setuptools entry points. No manual registration needed.

### Verification

```bash
# Check if provider is installed
warden providers list
# Should show: JavaParser (java)

# Test provider availability
warden providers test java
# Should show: ✅ Provider available for java
```

### Using in Code

```python
from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.enums import CodeLanguage

# Get provider for Java
registry = ASTProviderRegistry()
registry.discover_providers()

provider = registry.get_provider(CodeLanguage.JAVA)
print(f"Using: {provider.metadata.name}")
# Output: Using: JavaParser

# Parse Java code
java_code = """
public class HelloWorld {
    public static void main(String[] args) {
        System.out.println("Hello, World!");
    }
}
"""

result = await provider.parse(java_code, CodeLanguage.JAVA)

if result.is_success():
    print(f"AST nodes: {len(result.ast_root.children)}")
else:
    print(f"Errors: {result.errors}")
```

## Requirements

- Python 3.11+
- warden >= 0.1.0
- jpype1 >= 1.4.0
- JavaParser JAR (bundled)

## Development

### Setup Development Environment

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks (optional)
pre-commit install
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=warden_ast_java --cov-report=html

# Run specific test file
pytest tests/test_java_provider.py

# Run specific test
pytest tests/test_java_provider.py::TestJavaParserProvider::test_metadata_name
```

### Code Quality

```bash
# Format code
black src/ tests/

# Lint code
ruff check src/ tests/

# Type check
mypy src/
```

### Building Package

```bash
# Build distribution
python -m build

# Outputs:
# dist/warden-ast-java-0.1.0.tar.gz
# dist/warden_ast_java-0.1.0-py3-none-any.whl
```

## Architecture

### Provider Priority

This provider has `NATIVE` priority (highest), meaning it will be preferred over Tree-sitter and other generic parsers for Java code.

**Priority Order:**
1. `NATIVE` - JavaParserProvider (this package)
2. `SPECIALIZED` - Language-specific parsers
3. `TREE_SITTER` - Universal parser (fallback)
4. `COMMUNITY` - Community plugins
5. `FALLBACK` - Basic parsers

### Implementation Status

**Current Status:** Skeleton Implementation

- ✅ Provider interface implemented
- ✅ Entry points configured
- ✅ Unit tests written
- ⏳ JavaParser integration (pending)
- ⏳ AST conversion (pending)
- ⏳ Symbol resolution (pending)

### TODO List

1. **JVM Integration**
   - [ ] Start JVM with JavaParser JAR
   - [ ] Handle JVM lifecycle
   - [ ] Load JavaParser classes

2. **Parsing**
   - [ ] Parse Java source with JavaParser
   - [ ] Handle syntax errors
   - [ ] Extract parse tree

3. **AST Conversion**
   - [ ] Map JavaParser nodes to universal AST
   - [ ] Preserve location information
   - [ ] Convert Java-specific constructs

4. **Symbol Resolution**
   - [ ] Resolve types
   - [ ] Resolve method calls
   - [ ] Resolve variables

5. **Testing**
   - [ ] Integration tests with real Java code
   - [ ] Performance benchmarks
   - [ ] Error handling tests

## Entry Points

This package registers itself via setuptools entry points:

```toml
[project.entry-points."warden.ast_providers"]
java = "warden_ast_java.provider:JavaParserProvider"
```

Warden automatically discovers and loads this provider at runtime.

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

### Coding Standards

Follow [Warden Core Rules](https://github.com/warden-team/warden-core/blob/main/temp/warden_core_rules.md):

- Max 500 lines per file
- Type hints everywhere
- Docstrings (Google style)
- Structured logging
- Error handling
- Unit tests for all code

## License

MIT License - see LICENSE file for details.

## Links

- **Homepage**: https://github.com/warden-team/warden-ast-java
- **Warden Core**: https://github.com/warden-team/warden-core
- **Issues**: https://github.com/warden-team/warden-ast-java/issues
- **JavaParser**: https://javaparser.org/
- **JPype1**: https://jpype.readthedocs.io/

## Support

For issues and questions:

- **Bug Reports**: GitHub Issues
- **Discussions**: GitHub Discussions
- **Email**: team@warden.dev

## Changelog

### 0.1.0 (2025-12-21)

- Initial skeleton implementation
- Provider interface implemented
- Entry points configured
- Basic unit tests
- Development documentation
