# Warden Suppression Module

The Suppression module provides a robust system for handling false positives in Warden by allowing developers to suppress specific issues using inline comments, configuration files, or global rules.

## Features

- **Inline Comment Suppression**: Suppress issues directly in code using comments
- **Configuration-Based Suppression**: Define suppressions in `.warden/suppressions.yaml`
- **Global Rule Suppression**: Suppress rules across entire codebase
- **File Pattern Matching**: Suppress issues in specific file patterns (glob support)
- **Panel JSON Compatible**: All models serialize to camelCase for Panel integration
- **Multi-Language Support**: Python (`#`), JavaScript/TypeScript (`//`, `/* */`)

## Quick Start

### Basic Usage

```python
from warden.suppression import SuppressionMatcher

matcher = SuppressionMatcher()
code = '''
def foo():
    x = 1  # warden-ignore: magic-number
    return x
'''

is_suppressed = matcher.is_suppressed(line=3, rule="magic-number", code=code)
print(f"Suppressed: {is_suppressed}")  # True
```

### Inline Comment Patterns

```python
# Suppress all rules on this line
x = 1  # warden-ignore

# Suppress specific rule
x = 1  # warden-ignore: magic-number

# Suppress multiple rules
x = 1  # warden-ignore: magic-number, unused-var

# JavaScript/TypeScript
const x = 1;  // warden-ignore: magic-number

# Multi-line comment
const x = 1;  /* warden-ignore: magic-number */
```

## Configuration File

### Location

`.warden/suppressions.yaml`

### Example

```yaml
enabled: true

# Global rules (suppressed everywhere)
globalRules:
  - unused-import
  - magic-number

# Ignored files (all issues suppressed)
ignoredFiles:
  - test_*.py
  - migrations/*.py
  - generated/*.py

# Specific suppression entries
entries:
  - id: legacy-sql
    type: config
    rules:
      - sql-injection
    file: legacy/*.py
    reason: Legacy code scheduled for refactoring in Q2

  - id: generated-code
    type: config
    rules: []  # Empty = suppress all
    file: generated/*.py
    reason: Auto-generated code
```

### Loading Configuration

```python
from warden.suppression import load_suppression_config

# Load from default location (.warden/suppressions.yaml)
config = load_suppression_config(project_root="/path/to/project")

# Load from custom path
config = load_suppression_config(config_path="/path/to/config.yaml")
```

### Saving Configuration

```python
from warden.suppression import (
    SuppressionConfig,
    SuppressionEntry,
    SuppressionType,
    save_suppression_config,
)

entry = SuppressionEntry(
    id='test-1',
    type=SuppressionType.CONFIG,
    rules=['sql-injection'],
    file='legacy/*.py',
    reason='Legacy code',
)

config = SuppressionConfig(
    enabled=True,
    entries=[entry],
    global_rules=['unused-import'],
    ignored_files=['test_*.py'],
)

save_suppression_config(config, project_root="/path/to/project")
```

## API Reference

### SuppressionMatcher

Main class for checking suppressions.

```python
class SuppressionMatcher:
    def __init__(self, config: Optional[SuppressionConfig] = None):
        """Initialize with optional configuration."""
        pass

    def is_suppressed(
        self,
        line: int,
        rule: str,
        code: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> bool:
        """Check if issue should be suppressed."""
        pass

    def get_suppression_reason(
        self,
        line: int,
        rule: str,
        code: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> Optional[str]:
        """Get reason for suppression."""
        pass

    def add_inline_suppression(
        self,
        code: str,
        line: int,
        rules: Optional[List[str]] = None,
        comment_style: str = '#',
    ) -> str:
        """Add inline suppression to code."""
        pass

    def remove_inline_suppression(
        self,
        code: str,
        line: int,
    ) -> str:
        """Remove inline suppression from code."""
        pass
```

### SuppressionConfig

Configuration model.

```python
@dataclass
class SuppressionConfig(BaseDomainModel):
    enabled: bool = True
    entries: List[SuppressionEntry] = field(default_factory=list)
    global_rules: List[str] = field(default_factory=list)
    ignored_files: List[str] = field(default_factory=list)

    def is_file_ignored(self, file_path: str) -> bool:
        """Check if file is ignored."""
        pass

    def is_rule_globally_suppressed(self, rule: str) -> bool:
        """Check if rule is globally suppressed."""
        pass
```

### SuppressionEntry

Individual suppression entry.

```python
@dataclass
class SuppressionEntry(BaseDomainModel):
    id: str
    type: SuppressionType
    rules: List[str] = field(default_factory=list)
    file: Optional[str] = None
    line: Optional[int] = None
    reason: Optional[str] = None
    enabled: bool = True

    def matches_rule(self, rule: str) -> bool:
        """Check if suppression applies to rule."""
        pass

    def matches_location(
        self,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
    ) -> bool:
        """Check if suppression applies to location."""
        pass
```

### SuppressionType

Suppression type enum.

```python
class SuppressionType(Enum):
    INLINE = 0   # Inline comment
    CONFIG = 1   # Configuration file
    GLOBAL = 2   # Global suppression
```

## Panel JSON Integration

All models support Panel JSON serialization with camelCase:

```python
entry = SuppressionEntry(
    id='test-1',
    type=SuppressionType.CONFIG,
    rules=['sql-injection'],
    file='legacy/*.py',
    reason='Legacy code',
)

json_data = entry.to_json()
# {
#   "id": "test-1",
#   "type": 1,
#   "rules": ["sql-injection"],
#   "file": "legacy/*.py",
#   "line": null,
#   "reason": "Legacy code",
#   "enabled": true
# }
```

## Usage Examples

### Example 1: Inline Suppression

```python
from warden.suppression import SuppressionMatcher

matcher = SuppressionMatcher()

code = '''
def calculate_total(items):
    total = 0  # warden-ignore: magic-number
    for item in items:
        total += item.price
    return total
'''

# Check suppression
is_suppressed = matcher.is_suppressed(
    line=3,
    rule='magic-number',
    code=code
)
print(f"Suppressed: {is_suppressed}")  # True

# Get reason
reason = matcher.get_suppression_reason(
    line=3,
    rule='magic-number',
    code=code
)
print(f"Reason: {reason}")  # Suppressed by inline comment
```

### Example 2: Global Rules

```python
from warden.suppression import SuppressionConfig, SuppressionMatcher

config = SuppressionConfig(
    global_rules=['unused-import', 'magic-number']
)
matcher = SuppressionMatcher(config)

# These rules are suppressed everywhere
assert matcher.is_suppressed(line=1, rule='unused-import') is True
assert matcher.is_suppressed(line=100, rule='magic-number') is True
```

### Example 3: Configuration Entry

```python
from warden.suppression import (
    SuppressionConfig,
    SuppressionEntry,
    SuppressionType,
    SuppressionMatcher,
)

entry = SuppressionEntry(
    id='legacy-code',
    type=SuppressionType.CONFIG,
    rules=['sql-injection', 'xss'],
    file='legacy/*.py',
    reason='Legacy code scheduled for refactoring',
)

config = SuppressionConfig(entries=[entry])
matcher = SuppressionMatcher(config)

# Suppressed in legacy files
assert matcher.is_suppressed(
    line=1,
    rule='sql-injection',
    file_path='legacy/db.py'
) is True

# Not suppressed in other files
assert matcher.is_suppressed(
    line=1,
    rule='sql-injection',
    file_path='src/db.py'
) is False
```

### Example 4: Adding Inline Suppressions Programmatically

```python
from warden.suppression import SuppressionMatcher

matcher = SuppressionMatcher()

code = "x = 1"

# Add suppression for specific rules
modified = matcher.add_inline_suppression(
    code,
    line=1,
    rules=['magic-number', 'unused-var']
)
print(modified)  # x = 1  # warden-ignore: magic-number, unused-var

# Add suppression for all rules
modified = matcher.add_inline_suppression(code, line=1)
print(modified)  # x = 1  # warden-ignore
```

## File Structure

```
src/warden/suppression/
├── __init__.py           # Module exports
├── models.py             # Data models (252 lines)
├── matcher.py            # Suppression matching logic (355 lines)
└── config_loader.py      # YAML configuration loader (293 lines)
```

All files are under the 500-line limit as required by Warden coding standards.

## Testing

### Run Tests

```bash
# With pytest
pytest tests/suppression/ -v

# With coverage
pytest tests/suppression/ --cov=src/warden/suppression --cov-report=term-missing
```

### Test Coverage

- `tests/suppression/test_models.py` - Model functionality and JSON serialization
- `tests/suppression/test_matcher.py` - Suppression matching and inline comments
- `tests/suppression/test_config_loader.py` - Configuration loading and saving

All tests achieve >80% code coverage.

## Design Principles

1. **Type Safety**: Full type hints throughout
2. **Panel Compatibility**: All models support camelCase JSON serialization
3. **File Size Limits**: All files under 500 lines
4. **Comprehensive Testing**: >80% test coverage
5. **Clear Documentation**: Inline comments and docstrings
6. **Error Handling**: Graceful handling of malformed configs and edge cases

## Future Enhancements

- [ ] Regex pattern support for file matching
- [ ] Expiration dates for temporary suppressions
- [ ] Suppression statistics and reporting
- [ ] IDE integration for adding suppressions
- [ ] Bulk suppression management UI

## License

Part of the Warden Core project.
