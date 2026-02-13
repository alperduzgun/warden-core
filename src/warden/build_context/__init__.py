"""
Build context extraction for Warden projects.

Automatically detects and extracts build configuration and dependencies
from various project types (NPM, Python, etc.).

Usage:
```python
from warden.build_context import BuildContextProvider

provider = BuildContextProvider("/path/to/project")
context = await provider.get_context_async()

print(f"Build system: {context.build_system}")
print(f"Project: {context.project_name} v{context.project_version}")
print(f"Dependencies: {len(context.dependencies)}")

# Check for specific dependency
if context.has_dependency("fastapi"):
    print("FastAPI is installed!")
```

Synchronous usage:
```python
from warden.build_context import get_build_context_sync

context = get_build_context_sync("/path/to/project")
```
"""

from warden.build_context.context_provider import (
    BuildContextProvider,
    get_build_context_async,
    get_build_context_sync,
)
from warden.build_context.models import (
    BuildContext,
    BuildScript,
    BuildSystem,
    Dependency,
    DependencyType,
    create_empty_context,
)

__all__ = [
    "BuildContext",
    "BuildSystem",
    "Dependency",
    "DependencyType",
    "BuildScript",
    "BuildContextProvider",
    "get_build_context_async",
    "get_build_context_sync",
    "create_empty_context",
]
