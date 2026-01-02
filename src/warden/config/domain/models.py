"""
Pipeline configuration models for YAML and visual builder.

These models define pipeline structure:
- PipelineConfig: Complete pipeline definition
- PipelineNode: Visual builder nodes (start, end, frame, rule)
- PipelineEdge: Connections between nodes
- PipelineSettings: Execution settings

Panel JSON format: camelCase
Python internal format: snake_case
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Literal

from warden.shared.domain.base_model import BaseDomainModel


# Type aliases for Panel compatibility
PipelineNodeType = Literal['start', 'end', 'frame', 'globalRule', 'rule']
EdgeHandle = Literal['pre-execution', 'post-execution', 'output']
OnFailAction = Literal['stop', 'continue']


@dataclass
class Position(BaseDomainModel):
    """
    Node position in visual builder.

    Panel TypeScript equivalent:
    ```typescript
    interface Position {
      x: number
      y: number
    }
    ```
    """

    x: float
    y: float


@dataclass
class ProjectSummary(BaseDomainModel):
    """
    Project reference for pipeline.

    Panel TypeScript equivalent:
    ```typescript
    interface ProjectSummary {
      id: string
      name: string
      path?: string
      branch?: string
      commit?: string
    }
    ```
    """

    id: str
    name: str
    path: Optional[str] = None
    branch: Optional[str] = None
    commit: Optional[str] = None


@dataclass
class PipelineSettings(BaseDomainModel):
    """
    Pipeline execution settings.

    Panel TypeScript equivalent:
    ```typescript
    export interface PipelineSettings {
      failFast: boolean
      timeout?: number
      parallel?: boolean
      enableLlm?: boolean
      llmProvider?: string
    }
    ```
    """

    fail_fast: bool = True  # Stop on first error
    timeout: Optional[int] = None  # Execution timeout in seconds
    parallel: bool = False  # Run frames in parallel
    enable_llm: bool = True  # Enable LLM-enhanced analysis (C# pattern)
    llm_provider: str = "deepseek"  # LLM provider (deepseek, openai, anthropic, etc.)

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        return {
            'failFast': self.fail_fast,
            'timeout': self.timeout,
            'parallel': self.parallel,
            'enableLlm': self.enable_llm,
            'llmProvider': self.llm_provider
        }

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> 'PipelineSettings':
        """Parse Panel JSON to Python model."""
        return cls(
            fail_fast=data.get('failFast', True),
            timeout=data.get('timeout'),
            parallel=data.get('parallel', False),
            enable_llm=data.get('enableLlm', True),
            llm_provider=data.get('llmProvider', 'deepseek')
        )


@dataclass
class CustomRule(BaseDomainModel):
    """
    Custom validation rule.

    Panel TypeScript equivalent (simplified):
    ```typescript
    export interface CustomRule {
      id: string
      content: string
      severity: 'critical' | 'high' | 'medium' | 'low'
    }
    ```

    Full CustomRule definition in frame.py
    """

    id: str
    content: str
    severity: Literal['critical', 'high', 'medium', 'low']


@dataclass
class FrameNodeData(BaseDomainModel):
    """
    Frame node configuration data.

    Panel TypeScript equivalent:
    ```typescript
    export interface FrameNodeData {
      type: 'frame'
      frame: Frame
      preRules: CustomRule[]
      postRules: CustomRule[]
      onFail: 'stop' | 'continue'
      config?: Record<string, any>
    }
    ```
    """

    frame_id: str  # Reference to frame (e.g., "security", "chaos")
    type: Literal['frame'] = 'frame'
    pre_rules: List[CustomRule] = field(default_factory=list)  # Execute before frame
    post_rules: List[CustomRule] = field(default_factory=list)  # Execute after frame
    on_fail: OnFailAction = 'stop'
    config: Dict[str, Any] = field(default_factory=dict)  # Frame-specific config

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            'type': self.type,
            'frameId': self.frame_id,
            'preRules': [rule.to_json() for rule in self.pre_rules],
            'postRules': [rule.to_json() for rule in self.post_rules],
            'onFail': self.on_fail,
            'config': self.config
        }


@dataclass
class GlobalRuleNodeData(BaseDomainModel):
    """
    Global rule node data.

    Applied to all frames.
    """

    type: Literal['globalRule'] = 'globalRule'
    rule: CustomRule = field(default_factory=lambda: CustomRule(id='', content='', severity='medium'))


@dataclass
class StartNodeData(BaseDomainModel):
    """Start node data."""

    type: Literal['start'] = 'start'


@dataclass
class EndNodeData(BaseDomainModel):
    """End node data."""

    type: Literal['end'] = 'end'


@dataclass
class PipelineNode(BaseDomainModel):
    """
    Pipeline visual builder node.

    Panel TypeScript equivalent:
    ```typescript
    export interface PipelineNode {
      id: string
      type: PipelineNodeType
      position: { x: number; y: number }
      data: PipelineNodeData
    }
    ```
    """

    id: str
    type: PipelineNodeType
    position: Position
    data: Dict[str, Any]  # FrameNodeData | GlobalRuleNodeData | StartNodeData | EndNodeData

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            'id': self.id,
            'type': self.type,
            'position': self.position.to_json(),
            'data': self.data  # Already in correct format
        }


@dataclass
class EdgeStyle(BaseDomainModel):
    """
    Edge visual styling.

    Panel TypeScript equivalent:
    ```typescript
    interface EdgeStyle {
      stroke?: string
      strokeWidth?: number
    }
    ```
    """

    stroke: Optional[str] = None
    stroke_width: Optional[int] = None

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        result = {}
        if self.stroke:
            result['stroke'] = self.stroke
        if self.stroke_width is not None:
            result['strokeWidth'] = self.stroke_width
        return result


@dataclass
class PipelineEdge(BaseDomainModel):
    """
    Connection between pipeline nodes.

    Panel TypeScript equivalent:
    ```typescript
    export interface PipelineEdge {
      id: string
      source: string
      target: string
      sourceHandle?: string
      targetHandle?: 'pre-execution' | 'post-execution' | 'output'
      type?: string
      animated?: boolean
      style?: { stroke?: string; strokeWidth?: number }
      label?: string
    }
    ```
    """

    id: str
    source: str  # Source node ID
    target: str  # Target node ID
    source_handle: Optional[str] = None
    target_handle: Optional[EdgeHandle] = None
    type: str = 'smoothstep'  # Edge type (smoothstep, straight, step)
    animated: bool = True  # Dashed animation
    style: Optional[EdgeStyle] = None
    label: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        result: Dict[str, Any] = {
            'id': self.id,
            'source': self.source,
            'target': self.target,
            'type': self.type,
            'animated': self.animated
        }

        if self.source_handle:
            result['sourceHandle'] = self.source_handle
        if self.target_handle:
            result['targetHandle'] = self.target_handle
        if self.style:
            result['style'] = self.style.to_json()
        if self.label:
            result['label'] = self.label

        return result


@dataclass
class PipelineConfig(BaseDomainModel):
    """
    Complete pipeline configuration.

    Panel TypeScript equivalent:
    ```typescript
    export interface PipelineConfig {
      id: string
      name: string
      version: string
      project?: ProjectSummary
      nodes: PipelineNode[]
      edges: PipelineEdge[]
      globalRules: CustomRule[]
      settings: PipelineSettings
    }
    ```

    Can be serialized to YAML for CLI usage or JSON for Panel.
    """

    id: str
    name: str
    version: str = "1.0"
    project: Optional[ProjectSummary] = None
    nodes: List[PipelineNode] = field(default_factory=list)
    edges: List[PipelineEdge] = field(default_factory=list)
    global_rules: List[CustomRule] = field(default_factory=list)
    settings: PipelineSettings = field(default_factory=PipelineSettings)

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        result: Dict[str, Any] = {
            'id': self.id,
            'name': self.name,
            'version': self.version,
            'nodes': [node.to_json() for node in self.nodes],
            'edges': [edge.to_json() for edge in self.edges],
            'globalRules': [rule.to_json() for rule in self.global_rules],
            'settings': self.settings.to_json()
        }

        if self.project:
            result['project'] = self.project.to_json()

        return result

    def get_start_node(self) -> Optional[PipelineNode]:
        """Find the start node."""
        for node in self.nodes:
            if node.type == 'start':
                return node
        return None

    def get_end_node(self) -> Optional[PipelineNode]:
        """Find the end node."""
        for node in self.nodes:
            if node.type == 'end':
                return node
        return None

    def get_frame_nodes(self) -> List[PipelineNode]:
        """Get all frame nodes."""
        return [node for node in self.nodes if node.type == 'frame']

    def get_execution_order(self, respect_priority: bool = True) -> List[str]:
        """
        Get execution order of frames from start to end.

        Uses BFS to traverse the graph, then sorts by priority if requested.

        Args:
            respect_priority: If True, sort frames by priority (critical → low)

        Returns:
            List of frame node IDs in execution order
        """
        from collections import deque
        from warden.validation.domain.frame import get_frame_by_id, get_frames_by_priority

        start_node = self.get_start_node()
        if not start_node:
            return []

        # Build adjacency list
        graph: Dict[str, List[str]] = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            graph[edge.source].append(edge.target)

        # BFS traversal to find all reachable frames
        visited = set()
        queue = deque([start_node.id])
        frame_nodes = []

        while queue:
            node_id = queue.popleft()
            if node_id in visited:
                continue

            visited.add(node_id)

            # Collect frame nodes
            node = next((n for n in self.nodes if n.id == node_id), None)
            if node and node.type == 'frame':
                frame_nodes.append(node)

            # Add neighbors to queue
            for neighbor in graph.get(node_id, []):
                if neighbor not in visited:
                    queue.append(neighbor)

        # Sort by priority if requested
        if respect_priority:
            # Get frame definitions to access priority
            frames_with_priority = []
            for node in frame_nodes:
                frame_id = node.data.get('frameId')
                if frame_id:
                    frame_def = get_frame_by_id(frame_id)
                    if frame_def:
                        frames_with_priority.append((node, frame_def))

            # Sort by frame priority
            sorted_pairs = sorted(
                frames_with_priority,
                key=lambda pair: get_frames_by_priority([pair[1]])[0].priority
                if pair[1] else 'medium'
            )

            return [node.id for node, _ in sorted_pairs]
        else:
            return [node.id for node in frame_nodes]

    def get_execution_groups_for_parallel(self) -> List[List[str]]:
        """
        Get frame execution groups for parallel processing.

        Groups frames by priority. Each group runs sequentially,
        but frames within a group can run in parallel.

        Returns:
            List of groups, each containing frame node IDs
            Example: [[security], [chaos], [fuzz, property], [stress]]
        """
        from warden.validation.domain.frame import get_frame_by_id, get_execution_groups

        frame_nodes = self.get_frame_nodes()

        # Get frame definitions
        frames = []
        node_map = {}  # frame_id → node_id mapping
        for node in frame_nodes:
            frame_id = node.data.get('frameId')
            if frame_id:
                frame_def = get_frame_by_id(frame_id)
                if frame_def:
                    frames.append(frame_def)
                    node_map[frame_def.id] = node.id

        # Get priority groups
        groups = get_execution_groups(frames)

        # Convert to node IDs
        node_groups = []
        for group in groups:
            node_ids = [node_map[frame.id] for frame in group if frame.id in node_map]
            if node_ids:
                node_groups.append(node_ids)

        return node_groups
