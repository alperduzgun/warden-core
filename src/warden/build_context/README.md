# Build Context Module

Automatically detects and extracts build configuration and dependencies from project files.

## Features

- **Auto-detection**: Automatically identifies build system (NPM, Yarn, PNPM, Poetry, Pip, etc.)
- **Multiple formats**: Supports package.json, pyproject.toml, requirements.txt
- **Panel compatible**: All models serialize to camelCase JSON for TypeScript integration
- **Type-safe**: Full type hints throughout
- **Async support**: Both sync and async APIs available

## Supported Build Systems

| Build System | Files | Priority |
|-------------|-------|----------|
| NPM | package.json + package-lock.json | 1 (highest) |
| Yarn | package.json + yarn.lock | 1 |
| PNPM | package.json + pnpm-lock.yaml | 1 |
| Poetry | pyproject.toml with [tool.poetry] | 2 |
| PIP | pyproject.toml or requirements.txt | 3 |

## Quick Start

### Basic Usage

```python
from warden.build_context import BuildContextProvider

# Create provider
provider = BuildContextProvider("/path/to/project")

# Get context (async)
context = await provider.get_context_async()

# Or synchronous
context = provider.get_context()

# Access information
print(f"Build system: {context.build_system.name}")
print(f"Project: {context.project_name} v{context.project_version}")
print(f"Dependencies: {len(context.dependencies)}")
```

### Convenience Functions

```python
from warden.build_context import get_build_context_sync

# One-liner for sync usage
context = get_build_context_sync("/path/to/project")
```

### Check Dependencies

```python
# Check if dependency exists
if context.has_dependency("fastapi"):
    print("FastAPI is installed!")

# Get dependency details
dep = context.get_dependency_by_name("fastapi")
print(f"Version: {dep.version}")
print(f"Extras: {dep.extras}")
```

### Check Scripts

```python
# Check if script exists
if context.has_script("test"):
    script = context.get_script_by_name("test")
    print(f"Test command: {script.command}")
```

### Filter Dependencies

```python
# Get all dependencies (production + dev)
all_deps = context.get_all_dependencies()

# Get only production dependencies
prod_deps = context.get_production_dependencies()
```

## Panel Integration

All models support Panel-compatible JSON serialization:

```python
# Convert to JSON for Panel
json_data = context.to_json()

# Output format (camelCase, enums as int):
# {
#   "buildSystem": 5,  // POETRY = 5
#   "projectName": "my-app",
#   "projectVersion": "1.0.0",
#   "projectDescription": "My application",
#   "pythonVersion": "^3.11",
#   "dependencies": [
#     {
#       "name": "fastapi",
#       "version": "^0.100.0",
#       "type": 0,  // PRODUCTION = 0
#       "isDirect": true,
#       "extras": []
#     }
#   ],
#   "devDependencies": [...],
#   "scripts": [...]
# }
```

## Models

### BuildSystem (Enum)

```python
class BuildSystem(Enum):
    UNKNOWN = 0
    NPM = 1
    YARN = 2
    PNPM = 3
    PIP = 4
    POETRY = 5
    PIPENV = 6
    CONDA = 7
    # ... and more
```

### DependencyType (Enum)

```python
class DependencyType(Enum):
    PRODUCTION = 0
    DEVELOPMENT = 1
    OPTIONAL = 2
    PEER = 3
```

### Dependency (Dataclass)

```python
@dataclass
class Dependency:
    name: str
    version: str
    type: DependencyType = DependencyType.PRODUCTION
    is_direct: bool = True
    extras: List[str] = field(default_factory=list)
```

### BuildScript (Dataclass)

```python
@dataclass
class BuildScript:
    name: str
    command: str
    description: Optional[str] = None
```

### BuildContext (Dataclass)

```python
@dataclass
class BuildContext:
    build_system: BuildSystem
    project_path: str
    project_name: Optional[str] = None
    project_version: Optional[str] = None
    project_description: Optional[str] = None
    config_file_path: Optional[str] = None
    dependencies: List[Dependency] = field(default_factory=list)
    dev_dependencies: List[Dependency] = field(default_factory=list)
    scripts: List[BuildScript] = field(default_factory=list)
    python_version: Optional[str] = None
    node_version: Optional[str] = None
    engines: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

## Parsers

### PackageJsonParser

Parses JavaScript/TypeScript projects:

```python
from warden.build_context.parsers import PackageJsonParser

parser = PackageJsonParser("/path/to/project")
if parser.can_parse():
    context = parser.parse()
```

Features:
- Detects NPM, Yarn, or PNPM based on lock files
- Parses dependencies, devDependencies, peerDependencies, optionalDependencies
- Extracts scripts and engines configuration
- Includes project metadata (author, license, keywords, etc.)

### PyprojectParser

Parses Python projects with pyproject.toml:

```python
from warden.build_context.parsers import PyprojectParser

parser = PyprojectParser("/path/to/project")
if parser.can_parse():
    context = parser.parse()
```

Features:
- Supports Poetry format ([tool.poetry])
- Supports PEP 621 format ([project])
- Handles dependency extras (e.g., "httpx[http2]")
- Extracts Python version requirements
- Includes project metadata

### RequirementsParser

Parses pip-based projects:

```python
from warden.build_context.parsers import RequirementsParser

parser = RequirementsParser("/path/to/project")
if parser.can_parse():
    context = parser.parse()
```

Features:
- Parses requirements.txt
- Supports requirements-dev.txt for dev dependencies
- Handles -r include directives (recursive)
- Handles -e editable installs
- Parses dependency extras and version constraints
- Supports environment markers

## Advanced Usage

### Custom Parser Order

The default priority is: package.json > pyproject.toml > requirements.txt

If you need custom behavior, use parsers directly:

```python
from warden.build_context.parsers import PyprojectParser

parser = PyprojectParser("/path/to/project")
if parser.can_parse():
    context = parser.parse()
```

### Build System Detection Only

```python
provider = BuildContextProvider("/path/to/project")

# Just detect, don't parse
build_system = provider.detect_build_system()
print(f"Detected: {build_system.name}")
```

### Check for Build Config

```python
provider = BuildContextProvider("/path/to/project")

# Check if any build config exists
if provider.has_build_config():
    print("Project has build configuration")

# List all config files
config_files = provider.get_config_files()
print(f"Found: {', '.join(config_files)}")
```

## Error Handling

All parsers handle errors gracefully:

- Invalid JSON/TOML: Returns None
- Missing files: Returns None
- Malformed data: Returns None
- Unknown project: Returns empty context with BuildSystem.UNKNOWN

```python
# Safe to use without error checking
context = provider.get_context()

# Will always return a BuildContext object
# Check build_system to see if detection succeeded
if context.build_system == BuildSystem.UNKNOWN:
    print("No build system detected")
```

## Testing

The module includes comprehensive tests:

```bash
pytest tests/build_context/test_models.py
pytest tests/build_context/test_context_provider.py
```

Test coverage includes:
- Model creation and JSON serialization
- All parser types (NPM, Poetry, Pip)
- Edge cases (missing files, malformed data)
- Real project testing
- Async functionality

## Compliance

This module follows Warden coding standards:

- All files under 500 lines
- Type hints on all functions and methods
- Panel JSON compatibility (camelCase)
- Inherits from BaseDomainModel
- Comprehensive docstrings
- No external dependencies beyond Warden's stack
