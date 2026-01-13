"""
YAML validator with graph algorithms.

Validates pipeline configuration using:
- BFS (Breadth-First Search): Path finding from start to end
- DFS (Depth-First Search): Circular dependency detection

Validation checks:
1. Start node exists
2. End node exists
3. All frame nodes have valid frame IDs
4. No circular dependencies (DFS)
5. Path exists from start to end (BFS)
6. No orphaned nodes/edges
"""

from typing import List, Dict, Set, Optional
from collections import deque

from warden.config.domain.models import PipelineConfig, PipelineNode
from warden.validation.domain.frame import get_frame_by_id


class ValidationError(Exception):
    """Pipeline validation error."""
    pass


class ValidationResult:
    """Validation result with errors and warnings."""

    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def add_error(self, message: str) -> None:
        """Add validation error."""
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        """Add validation warning."""
        self.warnings.append(message)

    @property
    def is_valid(self) -> bool:
        """Check if validation passed (no errors)."""
        return len(self.errors) == 0

    def __str__(self) -> str:
        """String representation."""
        lines = []
        if self.errors:
            lines.append("Errors:")
            for error in self.errors:
                lines.append(f"  - {error}")
        if self.warnings:
            lines.append("Warnings:")
            for warning in self.warnings:
                lines.append(f"  - {warning}")
        return "\n".join(lines) if lines else "Valid"


def validate_basic_structure(config: PipelineConfig,
                             result: ValidationResult) -> None:
    """Validate basic pipeline structure."""
    # Check start node exists
    start_node = config.get_start_node()
    if not start_node:
        result.add_error("Missing start node")

    # Check end node exists
    end_node = config.get_end_node()
    if not end_node:
        result.add_error("Missing end node")

    # Check at least one frame
    frame_nodes = config.get_frame_nodes()
    if not frame_nodes:
        result.add_warning("No frame nodes defined")

    # Validate frame IDs
    for node in frame_nodes:
        frame_id = node.data.get('frameId')
        if not frame_id:
            result.add_error(f"Frame node {node.id} missing frameId")
        elif not get_frame_by_id(frame_id):
            result.add_error(f"Unknown frame ID: {frame_id} in node {node.id}")


def has_circular_dependency(config: PipelineConfig) -> bool:
    """
    Detect circular dependencies using DFS.

    Returns True if circular dependency detected.
    """
    # Build adjacency list
    graph: Dict[str, List[str]] = {node.id: [] for node in config.nodes}
    for edge in config.edges:
        graph[edge.source].append(edge.target)

    # DFS with recursion stack
    visited: Set[str] = set()
    rec_stack: Set[str] = set()

    def dfs(node_id: str) -> bool:
        """DFS helper - returns True if cycle detected."""
        visited.add(node_id)
        rec_stack.add(node_id)

        # Visit neighbors
        for neighbor in graph.get(node_id, []):
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                # Back edge found - cycle detected
                return True

        rec_stack.remove(node_id)
        return False

    # Run DFS from all nodes
    for node in config.nodes:
        if node.id not in visited:
            if dfs(node.id):
                return True

    return False


def has_path_start_to_end(config: PipelineConfig) -> bool:
    """
    Check if path exists from start to end using BFS.

    Returns True if path exists.
    """
    start_node = config.get_start_node()
    end_node = config.get_end_node()

    if not start_node or not end_node:
        return False

    # Build adjacency list
    graph: Dict[str, List[str]] = {node.id: [] for node in config.nodes}
    for edge in config.edges:
        graph[edge.source].append(edge.target)

    # BFS from start
    visited: Set[str] = set()
    queue: deque = deque([start_node.id])

    while queue:
        node_id = queue.popleft()

        if node_id == end_node.id:
            return True

        if node_id in visited:
            continue

        visited.add(node_id)

        # Add neighbors
        for neighbor in graph.get(node_id, []):
            if neighbor not in visited:
                queue.append(neighbor)

    return False


def find_orphaned_nodes(config: PipelineConfig) -> List[str]:
    """
    Find nodes not connected to start or end.

    Returns list of orphaned node IDs.
    """
    # Build adjacency list (bidirectional for this check)
    graph: Dict[str, Set[str]] = {node.id: set() for node in config.nodes}
    for edge in config.edges:
        graph[edge.source].add(edge.target)
        graph[edge.target].add(edge.source)

    # Find all connected nodes via BFS from start
    start_node = config.get_start_node()
    if not start_node:
        return []

    visited: Set[str] = set()
    queue: deque = deque([start_node.id])

    while queue:
        node_id = queue.popleft()

        if node_id in visited:
            continue

        visited.add(node_id)

        for neighbor in graph.get(node_id, []):
            if neighbor not in visited:
                queue.append(neighbor)

    # Find orphaned nodes
    orphaned = []
    for node in config.nodes:
        if node.id not in visited:
            orphaned.append(node.id)

    return orphaned


def find_orphaned_edges(config: PipelineConfig) -> List[str]:
    """
    Find edges referencing non-existent nodes.

    Returns list of orphaned edge IDs.
    """
    node_ids = {node.id for node in config.nodes}
    orphaned = []

    for edge in config.edges:
        if edge.source not in node_ids or edge.target not in node_ids:
            orphaned.append(edge.id)

    return orphaned


def validate_graph(config: PipelineConfig, result: ValidationResult) -> None:
    """Validate pipeline graph using BFS and DFS algorithms."""
    # Check for circular dependencies (DFS)
    if has_circular_dependency(config):
        result.add_error("Circular dependency detected in pipeline graph")

    # Check path from start to end (BFS)
    if not has_path_start_to_end(config):
        result.add_error("No path from start to end node")

    # Check for orphaned nodes
    orphaned_nodes = find_orphaned_nodes(config)
    if orphaned_nodes:
        result.add_warning(f"Orphaned nodes: {', '.join(orphaned_nodes)}")

    # Check for orphaned edges
    orphaned_edges = find_orphaned_edges(config)
    if orphaned_edges:
        result.add_error(f"Orphaned edges: {', '.join(orphaned_edges)}")


def validate_settings(config: PipelineConfig, result: ValidationResult) -> None:
    """Validate pipeline settings."""
    # Check timeout
    if config.settings.timeout is not None:
        if config.settings.timeout <= 0:
            result.add_error("Timeout must be positive")
        if config.settings.timeout > 3600:  # 1 hour
            result.add_warning("Timeout is very large (>1 hour)")


def validate(config: PipelineConfig) -> ValidationResult:
    """
    Validate pipeline configuration.

    Runs all validation checks:
    1. Basic structure (start, end, frames)
    2. Graph algorithms (BFS, DFS)
    3. Settings validation

    Args:
        config: Pipeline configuration

    Returns:
        ValidationResult with errors and warnings
    """
    result = ValidationResult()

    # Run validation checks
    validate_basic_structure(config, result)
    validate_graph(config, result)
    validate_settings(config, result)

    return result


def validate_and_raise(config: PipelineConfig) -> None:
    """
    Validate pipeline configuration and raise on error.

    Args:
        config: Pipeline configuration

    Raises:
        ValidationError: If validation fails
    """
    result = validate(config)

    if not result.is_valid:
        raise ValidationError(str(result))
