"""
File Discovery Adapter

MCP adapter for file discovery and project analysis tools.
Maps to gRPC FileDiscoveryMixin functionality.
"""

from pathlib import Path
from typing import Any, Dict, List

from warden.mcp.infrastructure.adapters.base_adapter import BaseWardenAdapter
from warden.mcp.domain.models import MCPToolDefinition, MCPToolResult
from warden.mcp.domain.enums import ToolCategory


class DiscoveryAdapter(BaseWardenAdapter):
    """
    Adapter for file discovery tools.

    Tools:
        - warden_discover_files: Discover project files
        - warden_get_files_by_type: Filter by type
        - warden_detect_frameworks: Detect frameworks
        - warden_get_project_stats: Project statistics
    """

    SUPPORTED_TOOLS = frozenset({
        "warden_discover_files",
        "warden_get_files_by_type",
        "warden_detect_frameworks",
        "warden_get_project_stats",
    })
    TOOL_CATEGORY = ToolCategory.DISCOVERY

    # Language extension mapping
    LANGUAGE_EXTENSIONS = {
        "python": [".py", ".pyi", ".pyw"],
        "javascript": [".js", ".jsx", ".mjs"],
        "typescript": [".ts", ".tsx"],
        "java": [".java"],
        "csharp": [".cs"],
        "go": [".go"],
        "rust": [".rs"],
        "cpp": [".cpp", ".cc", ".cxx", ".c", ".h", ".hpp"],
        "ruby": [".rb"],
        "php": [".php"],
        "kotlin": [".kt", ".kts"],
        "swift": [".swift"],
        "scala": [".scala"],
    }

    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        """Get discovery tool definitions."""
        return [
            self._create_tool_definition(
                name="warden_discover_files",
                description="Discover all code files in a project",
                properties={
                    "path": {
                        "type": "string",
                        "description": "Path to scan (default: project root)",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum directory depth",
                        "default": 10,
                    },
                    "use_gitignore": {
                        "type": "boolean",
                        "description": "Respect .gitignore patterns",
                        "default": True,
                    },
                },
            ),
            self._create_tool_definition(
                name="warden_get_files_by_type",
                description="Get files filtered by programming language",
                properties={
                    "types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Language types (python, javascript, etc.)",
                    },
                },
                required=["types"],
            ),
            self._create_tool_definition(
                name="warden_detect_frameworks",
                description="Detect frameworks and dependencies in project",
                properties={
                    "path": {
                        "type": "string",
                        "description": "Path to analyze",
                    },
                },
            ),
            self._create_tool_definition(
                name="warden_get_project_stats",
                description="Get project statistics (file counts, line counts, etc.)",
                properties={},
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolResult:
        """Execute discovery tool."""
        handlers = {
            "warden_discover_files": self._discover_files,
            "warden_get_files_by_type": self._get_files_by_type,
            "warden_detect_frameworks": self._detect_frameworks,
            "warden_get_project_stats": self._get_project_stats,
        }

        handler = handlers.get(tool_name)
        if handler:
            return await handler(arguments)
        return MCPToolResult.error(f"Unknown tool: {tool_name}")

    async def _discover_files(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Discover project files."""
        path = Path(arguments.get("path", str(self.project_root)))
        max_depth = arguments.get("max_depth", 10)
        use_gitignore = arguments.get("use_gitignore", True)

        if not path.exists():
            return MCPToolResult.error(f"Path not found: {path}")

        try:
            files = []
            analyzable = []

            # Get gitignore patterns
            gitignore_patterns = set()
            if use_gitignore:
                gitignore_file = self.project_root / ".gitignore"
                if gitignore_file.exists():
                    for line in gitignore_file.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            gitignore_patterns.add(line)

            # Walk directory
            for item in path.rglob("*"):
                # Check depth
                rel_path = item.relative_to(path)
                if len(rel_path.parts) > max_depth:
                    continue

                # Skip ignored directories
                if any(p.startswith(".") or p == "__pycache__" or p == "node_modules"
                       for p in rel_path.parts):
                    continue

                if item.is_file():
                    file_info = {
                        "path": str(item),
                        "name": item.name,
                        "extension": item.suffix,
                        "size": item.stat().st_size,
                    }
                    files.append(file_info)

                    # Check if analyzable
                    for lang, exts in self.LANGUAGE_EXTENSIONS.items():
                        if item.suffix in exts:
                            file_info["language"] = lang
                            analyzable.append(file_info)
                            break

            return MCPToolResult.json_result({
                "success": True,
                "total_files": len(files),
                "analyzable_files": len(analyzable),
                "files": analyzable[:100],  # Limit to 100 files in response
            })
        except Exception as e:
            return MCPToolResult.error(f"Discovery failed: {e}")

    async def _get_files_by_type(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get files filtered by language type."""
        types = arguments.get("types", [])

        if not types:
            return MCPToolResult.error("Missing required parameter: types")

        # Get extensions for requested types
        extensions = set()
        for lang_type in types:
            exts = self.LANGUAGE_EXTENSIONS.get(lang_type.lower(), [])
            extensions.update(exts)

        if not extensions:
            return MCPToolResult.error(f"Unknown language types: {types}")

        try:
            files = []
            for item in self.project_root.rglob("*"):
                if item.is_file() and item.suffix in extensions:
                    # Skip common ignored directories
                    if any(p.startswith(".") or p == "__pycache__" or p == "node_modules"
                           for p in item.relative_to(self.project_root).parts):
                        continue
                    files.append({
                        "path": str(item),
                        "name": item.name,
                        "extension": item.suffix,
                        "size": item.stat().st_size,
                    })

            return MCPToolResult.json_result({
                "success": True,
                "total_files": len(files),
                "types": types,
                "files": files[:100],
            })
        except Exception as e:
            return MCPToolResult.error(f"File filtering failed: {e}")

    async def _detect_frameworks(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Detect frameworks in project."""
        path = Path(arguments.get("path", str(self.project_root)))

        frameworks = []

        # Python frameworks
        if (path / "requirements.txt").exists() or (path / "setup.py").exists() or (path / "pyproject.toml").exists():
            frameworks.append({"name": "Python", "type": "language"})

            # Check for specific frameworks
            for req_file in ["requirements.txt", "pyproject.toml"]:
                req_path = path / req_file
                if req_path.exists():
                    content = req_path.read_text().lower()
                    if "django" in content:
                        frameworks.append({"name": "Django", "type": "web_framework"})
                    if "flask" in content:
                        frameworks.append({"name": "Flask", "type": "web_framework"})
                    if "fastapi" in content:
                        frameworks.append({"name": "FastAPI", "type": "web_framework"})
                    if "pytest" in content:
                        frameworks.append({"name": "pytest", "type": "testing"})

        # Node.js
        if (path / "package.json").exists():
            frameworks.append({"name": "Node.js", "type": "language"})
            try:
                import json
                pkg = json.loads((path / "package.json").read_text())
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "react" in deps:
                    frameworks.append({"name": "React", "type": "frontend_framework"})
                if "vue" in deps:
                    frameworks.append({"name": "Vue", "type": "frontend_framework"})
                if "express" in deps:
                    frameworks.append({"name": "Express", "type": "web_framework"})
                if "jest" in deps:
                    frameworks.append({"name": "Jest", "type": "testing"})
            except Exception:
                pass

        # Rust
        if (path / "Cargo.toml").exists():
            frameworks.append({"name": "Rust", "type": "language"})

        # Go
        if (path / "go.mod").exists():
            frameworks.append({"name": "Go", "type": "language"})

        return MCPToolResult.json_result({
            "success": True,
            "frameworks": frameworks,
            "total_count": len(frameworks),
        })

    async def _get_project_stats(self, arguments: Dict[str, Any]) -> MCPToolResult:
        """Get project statistics."""
        stats = {
            "total_files": 0,
            "total_lines": 0,
            "total_size_bytes": 0,
            "files_by_language": {},
            "lines_by_language": {},
        }

        try:
            for item in self.project_root.rglob("*"):
                if not item.is_file():
                    continue

                # Skip ignored directories
                rel_parts = item.relative_to(self.project_root).parts
                if any(p.startswith(".") or p == "__pycache__" or p == "node_modules"
                       for p in rel_parts):
                    continue

                stats["total_files"] += 1
                stats["total_size_bytes"] += item.stat().st_size

                # Count by language
                for lang, exts in self.LANGUAGE_EXTENSIONS.items():
                    if item.suffix in exts:
                        stats["files_by_language"][lang] = stats["files_by_language"].get(lang, 0) + 1
                        try:
                            lines = len(item.read_text(encoding="utf-8", errors="ignore").splitlines())
                            stats["total_lines"] += lines
                            stats["lines_by_language"][lang] = stats["lines_by_language"].get(lang, 0) + lines
                        except Exception:
                            pass
                        break

            return MCPToolResult.json_result(stats)
        except Exception as e:
            return MCPToolResult.error(f"Failed to get stats: {e}")
