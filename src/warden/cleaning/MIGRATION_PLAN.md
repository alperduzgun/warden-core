# CleaningPhase Tree-Sitter Migration Plan

## Current State

All CleaningPhase analyzers use Python AST (`ast.parse()`), limiting them to Python-only analysis:

- ❌ ComplexityAnalyzer - Python AST
- ❌ NamingAnalyzer - Python AST
- ❌ DuplicationAnalyzer - Python AST
- ❌ MagicNumberAnalyzer - Python AST
- ❌ TestabilityAnalyzer - Python AST
- ❌ MaintainabilityAnalyzer - Python AST
- ❌ DocumentationAnalyzer - Python AST

## Infrastructure Ready

✅ **Pre-Analysis Phase** already detects and shares `code_file.language`
✅ **Tree-sitter Provider** supports 40+ languages
✅ **BaseCleaningAnalyzer** has `supported_languages` property
✅ **Orchestrator** filters analyzers by language compatibility

## Migration Strategy

### Phase 1: Create Universal Base (1 week)

```python
# src/warden/cleaning/application/analyzers/base_universal_analyzer.py

from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.enums import ASTNodeType, CodeLanguage

class BaseUniversalAnalyzer(BaseCleaningAnalyzer):
    """Base for multi-language analyzers using tree-sitter."""

    def __init__(self):
        self._registry = ASTProviderRegistry()

    @property
    def supported_languages(self) -> set:
        """Universal analyzer - supports all languages."""
        return set()  # Empty = all languages

    async def get_ast(self, code_file: CodeFile):
        """Get universal AST via tree-sitter."""
        language = CodeLanguage(code_file.language.lower())
        provider = self._registry.get_provider(language)
        result = await provider.parse(code_file.content, language)
        return result.ast_root
```

### Phase 2: Migrate Analyzers (2 weeks)

**Priority Order:**
1. **ComplexityAnalyzer** (highest value, easiest to migrate)
2. **NamingAnalyzer** (moderate complexity)
3. **DuplicationAnalyzer** (AST-based diff)
4. **MagicNumberAnalyzer** (literal detection)

**Example Migration (Complexity):**

```python
class ComplexityAnalyzer(BaseUniversalAnalyzer):
    @property
    def supported_languages(self) -> set:
        return set()  # All languages

    async def analyze_async(self, code_file: CodeFile, ...):
        # Get universal AST
        ast_root = await self.get_ast(code_file)

        # Find functions (language-agnostic)
        functions = self._find_nodes_by_type(ast_root, ASTNodeType.FUNCTION)

        # Analyze complexity (same logic, different AST)
        for func in functions:
            lines = self._count_lines(func)
            if lines > MAX_FUNCTION_LINES:
                issues.append(...)
```

### Phase 3: Hybrid Mode (1 week)

Keep Python AST for Python (performance) + tree-sitter for others:

```python
@property
def supported_languages(self) -> set:
    return set()  # Universal

async def analyze_async(self, code_file: CodeFile, ...):
    if code_file.language == "python":
        # Fast path: Use native AST
        tree = ast.parse(code_file.content)
        return await self._analyze_python_ast(tree)
    else:
        # Universal path: Use tree-sitter
        ast_root = await self.get_ast(code_file)
        return await self._analyze_universal_ast(ast_root)
```

### Phase 4: Test & Validate (1 week)

- Unit tests for each language (Swift, Kotlin, Go, Rust, TypeScript)
- Integration tests with real codebases
- Performance benchmarks (Python AST vs tree-sitter)

## Testing Strategy

```python
# tests/cleaning/analyzers/test_universal_complexity.py

@pytest.mark.parametrize("language,code,expected_issues", [
    ("python", "def long_func():\n" + "    pass\n" * 60, 1),
    ("swift", "func longFunc() {\n" + "    return\n" * 60 + "}", 1),
    ("kotlin", "fun longFunc() {\n" + "    return\n" * 60 + "}", 1),
])
async def test_complexity_multi_language(language, code, expected_issues):
    analyzer = ComplexityAnalyzer()
    code_file = CodeFile(path=f"test.{language}", content=code, language=language)
    result = await analyzer.analyze_async(code_file)
    assert len(result.suggestions) == expected_issues
```

## Current Workaround (Implemented)

✅ Orchestrator now skips non-Python files gracefully:

```python
# Determine file language for compatibility check
file_language = code_file.language.lower() if code_file.language else "unknown"

# Run each analyzer
for analyzer in self._analyzers:
    # Check language compatibility
    supported_langs = analyzer.supported_languages
    if supported_langs and file_language not in supported_langs:
        logger.debug("skipping_analyzer_unsupported_language", ...)
        skipped_analyzers.append(analyzer.name)
        continue
```

**Logs Example:**
```
2026-02-06 00:09:54 [debug] skipping_analyzer_unsupported_language
    analyzer='Complexity Analyzer'
    file_language='swift'
    supported=['python']
```

## Success Metrics

- ✅ No more syntax errors on non-Python files
- ✅ CleaningPhase works on Swift/Kotlin/Go/Rust/TypeScript
- ✅ Performance within 2x of Python AST (acceptable for universal support)
- ✅ Same quality of issues detected across languages

## Timeline

- **Week 1-2:** Phase 1 (Universal Base)
- **Week 3-5:** Phase 2 (Migrate analyzers)
- **Week 6:** Phase 3 (Hybrid mode)
- **Week 7:** Phase 4 (Test & validate)

**Total:** 7 weeks to full multi-language CleaningPhase
