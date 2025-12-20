# Discovery Module Quick Reference

## Import

```python
from warden.discovery import FileDiscoverer, FileType, Framework
```

## Basic Usage

### Async Discovery (Recommended)

```python
import asyncio
from warden.discovery import FileDiscoverer

async def main():
    discoverer = FileDiscoverer(root_path="/path/to/project")
    result = await discoverer.discover_async()
    print(f"Found {result.stats.total_files} files")

asyncio.run(main())
```

### Sync Discovery

```python
from warden.discovery import FileDiscoverer

discoverer = FileDiscoverer(root_path="/path/to/project")
result = discoverer.discover_sync()
```

## Common Operations

### Get Analyzable Files Only

```python
# Async
files = await discoverer.get_analyzable_files_async()

# Sync
files = discoverer.get_analyzable_files()
```

### Filter by File Type

```python
from warden.discovery import FileType

result = discoverer.discover_sync()
python_files = result.get_files_by_type(FileType.PYTHON)
typescript_files = result.get_files_by_type(FileType.TYPESCRIPT)
```

### Check Framework

```python
from warden.discovery import Framework

result = discoverer.discover_sync()
if result.has_framework(Framework.REACT):
    print("React project detected")
```

## Configuration

```python
# With max depth
discoverer = FileDiscoverer(root_path=".", max_depth=5)

# Without gitignore filtering
discoverer = FileDiscoverer(root_path=".", use_gitignore=False)

# Combined
discoverer = FileDiscoverer(
    root_path="/path/to/project",
    max_depth=10,
    use_gitignore=True
)
```

## Panel JSON Export

```python
result = discoverer.discover_sync()
json_data = result.to_json()  # camelCase for Panel

# Access Panel JSON
print(json_data["projectPath"])
print(json_data["stats"]["totalFiles"])
print(json_data["frameworkDetection"]["primaryFramework"])
```

## Statistics

```python
result = discoverer.discover_sync()
stats = result.stats

print(f"Total files: {stats.total_files}")
print(f"Analyzable: {stats.analyzable_files}")
print(f"Percentage: {stats.analyzable_percentage:.2f}%")
print(f"Total size: {stats.total_size_bytes / 1024 / 1024:.2f} MB")
print(f"Duration: {stats.scan_duration_seconds:.3f}s")

# Files by type
for file_type, count in stats.files_by_type.items():
    print(f"{file_type}: {count}")
```

## File Types

### Analyzable Types

- `FileType.PYTHON` - Python files (.py, .pyw, .pyi)
- `FileType.JAVASCRIPT` - JavaScript (.js, .mjs, .cjs)
- `FileType.TYPESCRIPT` - TypeScript (.ts)
- `FileType.TSX` - TypeScript + JSX (.tsx)
- `FileType.JSX` - JavaScript + JSX (.jsx)
- `FileType.GO` - Go files (.go)
- `FileType.RUST` - Rust files (.rs)
- `FileType.JAVA` - Java files (.java)
- `FileType.KOTLIN` - Kotlin files (.kt, .kts)

### Non-Analyzable Types

- `FileType.MARKDOWN` - Documentation (.md, .rst)
- `FileType.JSON` - JSON files (.json)
- `FileType.YAML` - YAML files (.yaml, .yml)
- `FileType.HTML` - HTML files (.html)
- `FileType.CSS` - Stylesheets (.css, .scss)

## Frameworks

### Python Frameworks

- `Framework.DJANGO`
- `Framework.FLASK`
- `Framework.FASTAPI`
- `Framework.PYRAMID`
- `Framework.TORNADO`

### JavaScript/TypeScript Frameworks

- `Framework.REACT`
- `Framework.VUE`
- `Framework.ANGULAR`
- `Framework.NEXT`
- `Framework.NUXT`
- `Framework.SVELTE`
- `Framework.EXPRESS`
- `Framework.NEST`

## Convenience Functions

### Quick Discovery

```python
from warden.discovery import discover_project_files

result = await discover_project_files("/path/to/project")
```

### Gitignore Filter

```python
from warden.discovery import create_gitignore_filter
from pathlib import Path

filter = create_gitignore_filter(Path("/project"))
if filter.should_ignore(Path("/project/node_modules/lib.js")):
    print("File is ignored")
```

### Framework Detection

```python
from warden.discovery import detect_frameworks

result = await detect_frameworks(Path("/project"))
print(f"Primary: {result.primary_framework}")
print(f"All: {result.detected_frameworks}")
```

## Error Handling

```python
from pathlib import Path

try:
    discoverer = FileDiscoverer(root_path="/nonexistent")
    result = await discoverer.discover_async()
    # Gracefully handles missing directories
    if result.stats.total_files == 0:
        print("No files found")
except Exception as e:
    print(f"Error: {e}")
```

## Performance Tips

1. **Use async methods** for better UI responsiveness
2. **Set max_depth** to limit deep directory traversal
3. **Enable gitignore** to filter unnecessary files
4. **Get only analyzable files** to reduce processing

## Examples

See `examples/discovery_example.py` for complete examples.
