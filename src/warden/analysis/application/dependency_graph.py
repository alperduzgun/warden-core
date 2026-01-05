"""
Dependency Graph Service for Transitive Impact Analysis.

Builds and manages a Directed Acyclic Graph (DAG) of project file dependencies
to identify which files are impacted by changes in their dependencies.
"""

from pathlib import Path
from typing import Dict, List, Set, Optional
import structlog
import asyncio

from warden.analysis.domain.project_context import ProjectContext
from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.enums import CodeLanguage
from warden.analysis.application.resolvers.semantic_resolver import SemanticResolver

logger = structlog.get_logger()

class DependencyGraph:
    """
    Manages a graph where nodes are files and edges are 'depends-on' relationships.
    
    Allows finding all files that transitively depend on a set of changed files.
    """

    def __init__(self, project_root: Path, project_context: ProjectContext, provider_registry: ASTProviderRegistry):
        """
        Initialize the dependency graph.
        
        Args:
            project_root: Root directory of the project
            project_context: Metadata for resolution hints
            provider_registry: To get AST providers for dependency extraction
        """
        self.project_root = Path(project_root)
        self.resolver = SemanticResolver(project_root, project_context)
        self.provider_registry = provider_registry
        
        # graph[file_path] = {set of absolute paths it depends on}
        self._forward_graph: Dict[Path, Set[Path]] = {}
        # reverse_graph[file_path] = {set of absolute paths that depend on it}
        self._reverse_graph: Dict[Path, Set[Path]] = {}

    def add_dependency(self, source_file: Path, dependency_file: Path):
        """Add a dependency relationship: source_file -> dependency_file."""
        source_file = source_file.absolute()
        dependency_file = dependency_file.absolute()
        
        if source_file not in self._forward_graph:
            self._forward_graph[source_file] = set()
        self._forward_graph[source_file].add(dependency_file)
        
        if dependency_file not in self._reverse_graph:
            self._reverse_graph[dependency_file] = set()
        self._reverse_graph[dependency_file].add(source_file)

    async def scan_file_async(self, file_path: Path, language: CodeLanguage):
        """
        Scan a single file for dependencies and update the graph.
        
        Args:
            file_path: Path to the file to scan
            language: Language of the file
        """
        try:
            # 1. Get appropriate provider
            provider = self.provider_registry.get_provider(language)
            if not provider:
                return

            # 2. Extract raw dependencies
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            
            raw_deps = provider.extract_dependencies(content, language)
            
            # 3. Resolve and add to graph
            for dep_str in raw_deps:
                resolved_path = self.resolver.resolve(dep_str, file_path, language)
                if resolved_path:
                    self.add_dependency(file_path, resolved_path)
                    
        except Exception as e:
            logger.warning(
                "dependency_scan_failed",
                file=str(file_path),
                error=str(e)
            )

    def get_transitive_impact(self, changed_files: List[Path]) -> Set[Path]:
        """
        Find all files transitively impacted by the given changed files.
        
        Traverses the reverse graph starting from changed_files.
        """
        impacted = set()
        stack = [f.absolute() for f in changed_files]
        visited = set()
        
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            
            # If current is in reverse graph, it means other files depend on it
            dependents = self._reverse_graph.get(current, set())
            for dep in dependents:
                impacted.add(dep)
                stack.append(dep)
                
        # Exclude the original changed files from the 'impacted' set 
        # (they will be scanned anyway because they changed)
        origin_set = {f.absolute() for f in changed_files}
        return impacted - origin_set

    def clear(self):
        """Reset the graph."""
        self._forward_graph.clear()
        self._reverse_graph.clear()
