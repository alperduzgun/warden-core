# Warden C# AST Provider

**C# Abstract Syntax Tree (AST) provider for Warden using tree-sitter-c-sharp.**

## Overview

This extension provides C# parsing capabilities for [Warden](https://github.com/warden-team/warden-core), enabling comprehensive static analysis of C# codebases.

### Features

- ✅ **C# 1-10 Syntax Support**: Modern C# features including records, patterns, async/await
- ✅ **Pure Python**: No .NET runtime required
- ✅ **Fast Parsing**: Powered by tree-sitter's C implementation
- ✅ **Universal AST**: Converts C# to Warden's language-agnostic AST format
- ✅ **Comprehensive Extraction**: Classes, methods, properties, attributes, namespaces, using directives

### Supported C# Features

- **Declarations**: Classes, structs, interfaces, enums, records
- **Members**: Methods, properties, fields, constructors
- **Modifiers**: public, private, protected, internal, static, async, virtual, override, partial
- **Attributes**: C# annotation syntax (`[Serializable]`, `[HttpGet]`, etc.)
- **Namespaces**: Namespace declarations and using directives
- **Properties**: Auto-properties with getter/setter detection
- **Modern Features**: Records, async/await, LINQ expressions

## Installation

```bash
pip install warden-ast-csharp
```

### Dependencies

- `tree-sitter>=0.21.0`
- `tree-sitter-c-sharp>=0.21.0`
- `structlog>=23.0`

## Usage

Once installed, the C# AST provider is automatically discovered by Warden via entry points.

### Standalone Usage

```python
import asyncio
from warden_ast_csharp.provider import CSharpParserProvider
from warden.ast.domain.enums import CodeLanguage

async def main():
    provider = CSharpParserProvider()

    # Validate dependencies
    is_valid = await provider.validate()
    if not is_valid:
        print("Provider dependencies not available")
        return

    # Parse C# code
    code = """
    using System;

    namespace MyApp
    {
        public class User
        {
            public string Name { get; set; }

            public async Task<bool> ValidateAsync()
            {
                return await Task.FromResult(true);
            }
        }
    }
    """

    result = await provider.parse(code, CodeLanguage.CSHARP)

    if result.status == ParseStatus.SUCCESS:
        print(f"Parsed successfully! Nodes: {count_nodes(result.ast_root)}")
    else:
        print(f"Parsing failed: {result.errors}")

if __name__ == "__main__":
    asyncio.run(main())
```

### With Warden

```python
# Warden automatically discovers and uses the C# provider
from warden.validation.domain.frame import CodeFile
from warden.pipeline.application.orchestrator import PipelineOrchestrator

code_file = CodeFile(
    path="UserService.cs",
    content=csharp_code,
    language="csharp",
    framework="aspnet",
    size_bytes=len(csharp_code)
)

orchestrator = PipelineOrchestrator(frames=frames)
result = await orchestrator.execute([code_file])
```

## Architecture

### Provider Priority

The C# provider uses `NATIVE` priority, making it the preferred parser for C# files.

### AST Node Mapping

C# tree-sitter nodes are mapped to Warden's universal AST types:

| C# Node | Universal AST Type |
|---------|-------------------|
| `class_declaration` | `CLASS` |
| `method_declaration` | `FUNCTION` |
| `property_declaration` | `PROPERTY` |
| `field_declaration` | `FIELD` |
| `using_directive` | `IMPORT` |
| `namespace_declaration` | `MODULE` |
| `attribute` | `ANNOTATION` |
| `record_declaration` | `CLASS` |

### Extracted Attributes

The provider extracts C#-specific attributes:

```python
{
    "modifiers": ["public", "static", "async"],
    "has_getter": True,
    "has_setter": True,
    "attributes": ["[Serializable]", "[HttpGet(\"/api/users\")]"],
    "async": True,
    "partial": True,
    "namespace": "System.Collections.Generic"
}
```

## Limitations

### Syntax-Only Parsing

This provider performs **syntax-level parsing** without semantic analysis:

- ✅ **Supported**: Structure, declarations, statements, expressions
- ❌ **Not Supported**: Type resolution, symbol resolution, inheritance chains

For semantic analysis, consider future `warden-ast-csharp-roslyn` provider.

### C# Version Support

- **Fully Supported**: C# 1-10
- **Partially Supported**: C# 11-12 (depends on tree-sitter-c-sharp updates)

Check [tree-sitter-c-sharp releases](https://github.com/tree-sitter/tree-sitter-c-sharp/releases) for latest C# version support.

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/warden-team/warden-ast-csharp.git
cd warden-ast-csharp

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest tests/ -v
```

### Code Quality

```bash
# Format code
black src/ tests/

# Lint
ruff check src/ tests/

# Type checking
mypy src/
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Related Projects

- [Warden Core](https://github.com/warden-team/warden-core) - Main validation framework
- [warden-ast-java](https://github.com/warden-team/warden-ast-java) - Java AST provider
- [tree-sitter-c-sharp](https://github.com/tree-sitter/tree-sitter-c-sharp) - Underlying parser

## Support

- **Issues**: [GitHub Issues](https://github.com/warden-team/warden-ast-csharp/issues)
- **Documentation**: [Warden Docs](https://warden.dev/docs)
- **Discussions**: [GitHub Discussions](https://github.com/warden-team/warden-core/discussions)
