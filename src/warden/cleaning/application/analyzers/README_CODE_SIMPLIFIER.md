# Code Simplifier Analyzer

## Overview

The **Code Simplifier Analyzer** is a cleaning analyzer that focuses on code elegance, clarity, and modernization. It goes beyond complexity metrics to suggest specific refactoring patterns that improve code readability and maintainability.

## Features

### 1. Guard Clause Detection
Identifies deeply nested conditional logic that could be flattened using guard clauses (early returns).

**Example:**
```python
# Before (Deep Nesting)
def process(user):
    if user is not None:
        if user.is_active:
            if user.verified:
                return do_something(user)
    return None

# After (Guard Clauses)
def process(user):
    if user is None:
        return None
    if not user.is_active:
        return None
    if not user.verified:
        return None
    return do_something(user)
```

### 2. Redundant Else Detection
Finds else blocks that follow early returns, which add unnecessary nesting.

**Example:**
```python
# Before
if condition:
    return value
else:
    do_something()

# After
if condition:
    return value
do_something()
```

### 3. Complex Boolean Simplification
Detects complex boolean expressions with multiple operators that should be extracted to named functions.

**Example:**
```python
# Before
if user.age > 18 and user.verified and not user.banned and resource.public:
    grant_access()

# After
def can_access(user, resource):
    return user.age > 18 and user.verified and not user.banned and resource.public

if can_access(user, resource):
    grant_access()
```

### 4. Python Modernization

#### F-String Suggestions
Detects old-style string formatting and suggests modern f-strings.

**Example:**
```python
# Before
message = "Hello %s" % name
message = "Hello {}, you are {}".format(name, age)

# After
message = f"Hello {name}"
message = f"Hello {name}, you are {age}"
```

#### List Comprehension Suggestions
Identifies manual list building loops that could use comprehensions.

**Example:**
```python
# Before
result = []
for item in items:
    result.append(item.value)

# After
result = [item.value for item in items]
```

## Integration

### Default Orchestrator
The Code Simplifier is included by default in the `CleaningOrchestrator`:

```python
from warden.cleaning.application.orchestrator import CleaningOrchestrator

orchestrator = CleaningOrchestrator()
result = await orchestrator.analyze_async(code_file)
```

### Standalone Usage
Can be used independently:

```python
from warden.cleaning.application.analyzers import CodeSimplifierAnalyzer
from warden.validation.domain.frame import CodeFile

analyzer = CodeSimplifierAnalyzer()
code_file = CodeFile(path="example.py", content=code, language="python")
result = await analyzer.analyze_async(code_file)

print(f"Found {result.issues_found} simplification opportunities")
print(f"Cleanup score: {result.cleanup_score}")
for suggestion in result.suggestions:
    print(f"- {suggestion.suggestion}")
    print(f"  Rationale: {suggestion.rationale}")
```

## Configuration

### Priority
The analyzer runs with **HIGH** priority (after CRITICAL naming checks, before MEDIUM magic number checks).

### Supported Languages
Universal support via tree-sitter AST (empty set = all languages):
- Python (with additional modernization checks)
- JavaScript/TypeScript
- Go, Rust, Java, Swift, Kotlin
- And all other tree-sitter supported languages

### Thresholds
```python
MAX_NESTING_FOR_GUARD_CLAUSE = 2  # Suggest guard clauses if nesting > 2
MAX_BOOLEAN_CONDITIONS = 3         # Suggest extraction if > 3 operators
```

## Metrics

The analyzer provides detailed metrics in the result:

```python
result.metrics = {
    "guard_clause_opportunities": 2,
    "redundant_else": 1,
    "complex_boolean": 1,
    "modernization": 3
}
```

## Testing

Comprehensive test suite in `tests/cleaning/application/analyzers/test_code_simplifier.py`:

- 18 unit tests covering all features
- Edge case handling
- Multi-language support
- Integration tests with orchestrator

Run tests:
```bash
python3 -m pytest tests/cleaning/application/analyzers/test_code_simplifier.py -v
```

## Architecture

### Inheritance
Extends `BaseCleaningAnalyzer` which provides:
- Universal AST parsing (Python native + tree-sitter)
- Helper methods for complexity calculation
- Standard interface for all analyzers

### Issue Types
Uses standard cleaning issue types:
- `COMPLEX_METHOD` - For nesting and boolean complexity
- `DESIGN_SMELL` - For redundant else, old formatting

### Severity Levels
- **HIGH**: Deep nesting (impacts readability significantly)
- **MEDIUM**: Complex booleans, guard clause opportunities
- **LOW**: Redundant else blocks
- **INFO**: Modernization suggestions (.format to f-strings)

## Future Enhancements

1. **Variable Usage Analysis**: Detect variables assigned but used only once
2. **Walrus Operator Suggestions**: For Python 3.8+
3. **Match Statement Suggestions**: For Python 3.10+ (replace if-elif chains)
4. **Language-Specific Patterns**:
   - JavaScript: Arrow functions, template literals
   - TypeScript: Type inference opportunities
   - Go: Early returns, error handling patterns
5. **Cognitive Complexity**: Beyond cyclomatic complexity

## Related Analyzers

- **ComplexityAnalyzer**: Focuses on metrics (lines, parameters, cyclomatic complexity)
- **Code Simplifier**: Focuses on patterns and refactoring opportunities
- **NamingAnalyzer**: Focuses on identifier naming
- **DuplicationAnalyzer**: Focuses on code duplication

Together they provide comprehensive code quality analysis.
