# Warden Discovery Module

The Discovery module provides file discovery, classification, and framework detection capabilities for the Warden code analysis platform.

## Features

- **File Discovery**: Recursively scan project directories with configurable depth
- **File Classification**: Automatically detect file types by extension (Python, JavaScript, TypeScript, etc.)
- **Gitignore Support**: Respect .gitignore patterns to filter irrelevant files
- **Framework Detection**: Identify frameworks used in the project (Django, Flask, React, etc.)
- **Panel JSON Compatibility**: All models serialize to camelCase JSON for Panel integration
- **Async Support**: Full async/await support for non-blocking operations

## Installation

The Discovery module is part of the Warden core package:

```python
from warden.discovery import FileDiscoverer
```

## Quick Start

### Basic Discovery

```python
import asyncio
from warden.discovery import FileDiscoverer

async def discover_files():
    discoverer = FileDiscoverer(root_path="/path/to/project")
    result = await discoverer.discover_async()

    print(f"Found {result.stats.total_files} files")
    print(f"Analyzable: {result.stats.analyzable_files}")
    print(f"Primary framework: {result.framework_detection.primary_framework}")

asyncio.run(discover_files())
```

### Synchronous Usage

```python
from warden.discovery import FileDiscoverer

discoverer = FileDiscoverer(root_path="/path/to/project")
result = discoverer.discover_sync()

print(f"Total files: {result.stats.total_files}")
```

### Get Analyzable Files Only

```python
from warden.discovery import FileDiscoverer

discoverer = FileDiscoverer(root_path="/path/to/project")
analyzable_files = discoverer.get_analyzable_files()

for file_path in analyzable_files:
    print(file_path)
```

### Filter by File Type

```python
from warden.discovery import FileDiscoverer, FileType

discoverer = FileDiscoverer(root_path="/path/to/project")
result = discoverer.discover_sync()

python_files = result.get_files_by_type(FileType.PYTHON)
print(f"Found {len(python_files)} Python files")
```

## Architecture

### Components

1. **models.py** (280 lines)
   - `FileType` enum: Supported file types
   - `Framework` enum: Detected frameworks
   - `DiscoveredFile`: Individual file metadata
   - `FrameworkDetectionResult`: Framework detection results
   - `DiscoveryStats`: Statistics about discovery
   - `DiscoveryResult`: Complete discovery result

2. **classifier.py** (241 lines)
   - `FileClassifier`: File type detection by extension
   - Extension mapping for 20+ file types
   - Binary file detection (images, videos, archives)
   - Analyzability checking

3. **gitignore_filter.py** (266 lines)
   - `GitignoreFilter`: Pattern matching for .gitignore
   - Default ignore patterns (node_modules, .git, etc.)
   - Pattern to regex conversion
   - Recursive directory filtering

4. **framework_detector.py** (255 lines)
   - `FrameworkDetector`: Framework detection logic
   - Python framework detection (Django, Flask, FastAPI)
   - JavaScript framework detection (React, Vue, Next.js)
   - Confidence scoring

5. **discoverer.py** (309 lines)
   - `FileDiscoverer`: Main orchestrator
   - Directory walking with depth control
   - File classification and filtering
   - Statistics calculation

## File Types

### Analyzable File Types

The following file types can be analyzed by Warden:

- **Python**: `.py`, `.pyw`, `.pyi`
- **JavaScript**: `.js`, `.mjs`, `.cjs`
- **TypeScript**: `.ts`, `.tsx`, `.jsx`
- **Go**: `.go`
- **Rust**: `.rs`
- **Java**: `.java`
- **Kotlin**: `.kt`, `.kts`

### Supported but Non-Analyzable

- **Web**: `.html`, `.css`, `.scss`
- **Data**: `.json`, `.yaml`, `.yml`
- **Documentation**: `.md`, `.rst`
- **Shell**: `.sh`, `.bash`, `.zsh`
- **SQL**: `.sql`

## Framework Detection

### Python Frameworks

- Django
- Flask
- FastAPI
- Pyramid
- Tornado

### JavaScript/TypeScript Frameworks

- React
- Vue
- Angular
- Next.js
- Nuxt
- Svelte
- Express
- NestJS

### Detection Methods

1. **Dependency Files**: Analyze `package.json`, `requirements.txt`, `pyproject.toml`
2. **Import Statements**: Scan source files for framework imports
3. **Confidence Scoring**: Calculate confidence based on detection method

## Panel JSON Compatibility

All models support Panel integration with camelCase JSON:

```python
from warden.discovery import FileDiscoverer

discoverer = FileDiscoverer(root_path="/path/to/project")
result = discoverer.discover_sync()

# Convert to Panel-compatible JSON
json_data = result.to_json()

# camelCase keys for Panel
print(json_data["projectPath"])
print(json_data["stats"]["totalFiles"])
print(json_data["frameworkDetection"]["primaryFramework"])
```

## Configuration Options

### FileDiscoverer Parameters

- `root_path`: Project root directory (required)
- `max_depth`: Maximum directory depth to scan (optional)
- `use_gitignore`: Respect .gitignore patterns (default: True)

### Examples

```python
# Limit directory depth
discoverer = FileDiscoverer(root_path=".", max_depth=3)

# Disable gitignore filtering
discoverer = FileDiscoverer(root_path=".", use_gitignore=False)

# Combined options
discoverer = FileDiscoverer(
    root_path="/path/to/project",
    max_depth=5,
    use_gitignore=True
)
```

## Statistics

The `DiscoveryStats` model provides:

- `total_files`: Total files discovered
- `analyzable_files`: Files that can be analyzed
- `ignored_files`: Files filtered by .gitignore
- `files_by_type`: Count by file type
- `total_size_bytes`: Total size in bytes
- `scan_duration_seconds`: Time taken to scan
- `analyzable_percentage`: Percentage of analyzable files

## Testing

Comprehensive test suite with 80%+ coverage:

```bash
pytest tests/discovery/test_discoverer.py -v
```

Test coverage includes:
- File classification for all supported types
- Gitignore pattern matching
- Framework detection for Python and JavaScript
- JSON serialization/deserialization
- Edge cases and error handling

## Performance

- **Fast Scanning**: Processes ~300 files in <100ms
- **Async Support**: Non-blocking for UI integration
- **Memory Efficient**: Streaming file processing
- **Smart Filtering**: Early rejection of ignored paths

## Examples

See `examples/discovery_example.py` for complete usage examples:

```bash
python examples/discovery_example.py
```

Examples include:
- Basic discovery
- Filtering by type
- Getting analyzable files
- JSON serialization
- Custom discovery options

## Code Quality

All files adhere to Warden coding standards:

- **Line Limit**: All files under 500 lines
- **Type Hints**: Complete type annotations
- **Documentation**: Comprehensive docstrings
- **Testing**: 80%+ test coverage
- **Panel JSON**: camelCase serialization

## API Reference

### Main Classes

- `FileDiscoverer`: Main discovery orchestrator
- `FileClassifier`: File type detection
- `GitignoreFilter`: Gitignore pattern matching
- `FrameworkDetector`: Framework detection

### Models

- `DiscoveryResult`: Complete discovery result
- `DiscoveredFile`: Individual file metadata
- `FrameworkDetectionResult`: Framework detection results
- `DiscoveryStats`: Discovery statistics

### Enums

- `FileType`: Supported file types
- `Framework`: Detected frameworks

## License

Part of the Warden project.
