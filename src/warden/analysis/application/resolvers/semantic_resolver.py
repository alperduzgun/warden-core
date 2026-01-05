"""
Semantic Resolver for Language-Agnostic Dependency Mapping.

Handles the mapping of raw import strings (e.g., "@/utils", "../core") 
to actual project file paths using heuristics, project context, and LLM fallback.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
import structlog
from warden.analysis.domain.project_context import ProjectContext
from warden.ast.domain.enums import CodeLanguage

logger = structlog.get_logger()

class SemanticResolver:
    """
    Resolves dependency strings to physical file paths.
    
    Uses a multi-layered approach:
    1. Heuristic (Relative/Common paths)
    2. Context-Aware (Alias resolution from ProjectContext)
    3. LLM-Assisted Fallback (For ambiguous/dynamic paths)
    """

    def __init__(self, project_root: Path, project_context: ProjectContext):
        """
        Initialize resolver.
        
        Args:
            project_root: Root directory of the project
            project_context: Metadata about the project (Phase 0)
        """
        self.project_root = Path(project_root)
        self.project_context = project_context
        self.skip_list = {
            "logging", "structlog", "typing", "json", "os", "sys", "pathlib", "asyncio",
            "warden.shared.logger", "warden.reports", "warden.cli"
        }

    def resolve(self, import_str: str, current_file: Path, language: CodeLanguage) -> Optional[Path]:
        """
        Resolve an import string to an absolute path.
        
        Args:
            import_str: Raw string from source code
            current_file: Absolute path of the file containing the import
            language: Programming language context
            
        Returns:
            Resolved absolute Path or None if not found/skipped
        """
        # 1. Skip infrastructure/stdlib (approximate)
        if self._should_skip(import_str):
            return None

        # 2. Try Heuristic Resolution (Relative paths)
        resolved = self._resolve_heuristic(import_str, current_file, language)
        if resolved:
            return resolved

        # 3. Try Context-Aware Resolution (Aliases)
        resolved = self._resolve_context(import_str, language)
        if resolved:
            return resolved

        # 4. Fallback (Future: LLM assisted resolution)
        # For now, we return None if not found
        return None

    def _should_skip(self, import_str: str) -> bool:
        """Check if import is in the global skip list."""
        # Simple match for common infra modules
        parts = import_str.split('.')
        base_module = parts[0]
        return base_module in self.skip_list or import_str in self.skip_list

    def _resolve_heuristic(self, import_str: str, current_file: Path, language: CodeLanguage) -> Optional[Path]:
        """Resolve common relative and absolute-within-project patterns."""
        # Relative paths: ./utils, ../core
        if import_str.startswith('.'):
            # Normalize to relative path on disk
            try:
                # Replace dots with slashes for Python (e.g., ..models -> ../../models)
                if language == CodeLanguage.PYTHON:
                    # In Python, 'from .. import x' means 2 levels up
                    # 'from . import x' means same dir
                    dot_count = 0
                    for char in import_str:
                        if char == '.': dot_count += 1
                        else: break
                    
                    if dot_count > 0:
                        parent = current_file.parent
                        for _ in range(dot_count - 1):
                            parent = parent.parent
                        
                        rel_path = import_str[dot_count:].replace('.', '/')
                        path = parent / rel_path
                    else:
                        path = current_file.parent / import_str.replace('.', '/')
                else:
                    path = current_file.parent / import_str
                
                return self._verify_path(path, language)
            except Exception:
                return None

        # Check for paths relative to project root (e.g., 'src/utils')
        root_path = self.project_root / import_str.replace('.', '/')
        resolved = self._verify_path(root_path, language)
        if resolved:
            return resolved
            
        # Try prepending 'src' (Common in Python/JS projects)
        src_path = self.project_root / "src" / import_str.replace('.', '/')
        return self._verify_path(src_path, language)

    def _resolve_context(self, import_str: str, language: CodeLanguage) -> Optional[Path]:
        """Resolve using project-specific aliases (e.g., TSC aliases)."""
        # 1. Check for known aliases in ProjectContext
        # Future: ProjectContext could store alias mappings detected in Phase 0
        # For now, we handle common ones like '@/...' -> 'src/...'
        if import_str.startswith('@/'):
            path = self.project_root / 'src' / import_str[2:]
            return self._verify_path(path, language)
            
        return None

    def _verify_path(self, path: Path, language: CodeLanguage) -> Optional[Path]:
        """Check if path exists with appropriate extension."""
        extensions = {
            CodeLanguage.PYTHON: [".py", "/__init__.py"],
            CodeLanguage.TYPESCRIPT: [".ts", ".tsx", ".d.ts", "/index.ts"],
            CodeLanguage.JAVASCRIPT: [".js", ".jsx", "/index.js"],
            CodeLanguage.GO: [".go"],
            CodeLanguage.JAVA: [".java"],
        }.get(language, [".py", ".ts", ".js", ".go", ".java"])

        # Try base path first (if it's a directory or already has extension)
        if path.is_file():
            return path.absolute()
        
        if path.is_dir():
             # Check for index files
             for ext in extensions:
                 if ext.startswith('/'):
                     idx_path = path / ext.lstrip('/')
                     if idx_path.exists():
                         return idx_path.absolute()

        # Try appending extensions
        for ext in extensions:
            if ext.startswith('/'): continue
            p = path.with_suffix(ext)
            if p.exists():
                return p.absolute()
        
        return None
