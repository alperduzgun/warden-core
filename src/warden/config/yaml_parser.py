"""
YAML parser for pipeline configuration.

Loads YAML files and converts them to PipelineConfig models.
Supports both simple (CLI-friendly) and full (visual builder) formats.

Simple format:
```yaml
version: "1.0"
name: "Quick Security Scan"
files:
  - "src/**/*.py"
frames:
  - security
  - chaos
settings:
  fail_fast: true
```

Full format:
```yaml
version: "1.0"
name: "Complex Pipeline"
project:
  id: "proj-1"
  name: "My Project"
nodes:
  - id: "start"
    type: "start"
    position: {x: 100, y: 200}
edges:
  - id: "e1"
    source: "start"
    target: "frame-security"
```
"""

from typing import Dict, Any, List, Optional
from pathlib import Path
import yaml

from warden.config.domain.models import (
    PipelineConfig,
    PipelineNode,
    PipelineEdge,
    PipelineSettings,
    ProjectSummary,
    Position,
    CustomRule,
)
from warden.validation.domain.frame import get_frame_by_id, get_frames_by_priority


class YAMLParseError(Exception):
    """YAML parsing error."""
    pass


def load_yaml(file_path: str) -> Dict[str, Any]:
    """
    Load YAML file safely.

    Args:
        file_path: Path to YAML file

    Returns:
        Parsed YAML data

    Raises:
        YAMLParseError: If file cannot be loaded or parsed
    """
    # Validate path
    if not file_path:
        raise YAMLParseError("file_path cannot be empty")

    path = Path(file_path)

    # Prevent path traversal
    if ".." in file_path:
        raise YAMLParseError("Path traversal not allowed")

    # Check file exists
    if not path.exists():
        raise YAMLParseError(f"File not found: {file_path}")

    # Check file size (max 1MB)
    if path.stat().st_size > 1 * 1024 * 1024:
        raise YAMLParseError("YAML file too large (max 1MB)")

    # Load YAML
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise YAMLParseError("YAML root must be a dictionary")

        return data

    except yaml.YAMLError as e:
        raise YAMLParseError(f"Invalid YAML syntax: {e}")
    except Exception as e:
        raise YAMLParseError(f"Failed to load YAML: {e}")


def parse_simple_format(data: Dict[str, Any]) -> PipelineConfig:
    """
    Parse simple CLI-friendly YAML format.

    Simple format example:
    ```yaml
    version: "1.0"
    name: "Quick Scan"
    files:
      - "src/**/*.py"
    frames:
      - security
      - chaos
    settings:
      fail_fast: true
      parallel: true
    ```

    Generates a linear pipeline: start → frame1 → frame2 → ... → end
    """
    # Required fields
    if 'name' not in data:
        raise YAMLParseError("Missing required field: name")

    # Parse frames
    frame_ids = data.get('frames', [])
    if not frame_ids:
        raise YAMLParseError("At least one frame required")

    # Parse settings
    settings_data = data.get('settings', {})
    settings = PipelineSettings(
        fail_fast=settings_data.get('fail_fast', True),
        timeout=settings_data.get('timeout'),
        parallel=settings_data.get('parallel', False)
    )

    # Generate nodes
    nodes: List[PipelineNode] = []

    # Start node
    nodes.append(PipelineNode(
        id='start',
        type='start',
        position=Position(x=100, y=200),
        data={'type': 'start'}
    ))

    # Frame nodes
    x_offset = 300
    for i, frame_id in enumerate(frame_ids):
        frame = get_frame_by_id(frame_id)
        if not frame:
            raise YAMLParseError(f"Unknown frame: {frame_id}")

        nodes.append(PipelineNode(
            id=f'frame-{frame_id}',
            type='frame',
            position=Position(x=x_offset + (i * 200), y=200),
            data={
                'type': 'frame',
                'frameId': frame_id,
                'preRules': [],
                'postRules': [],
                'onFail': 'stop',
                'config': {}
            }
        ))

    # End node
    nodes.append(PipelineNode(
        id='end',
        type='end',
        position=Position(x=x_offset + (len(frame_ids) * 200), y=200),
        data={'type': 'end'}
    ))

    # Generate edges (linear)
    edges: List[PipelineEdge] = []
    for i in range(len(nodes) - 1):
        edges.append(PipelineEdge(
            id=f'e{i}',
            source=nodes[i].id,
            target=nodes[i + 1].id
        ))

    return PipelineConfig(
        id=data.get('id', 'pipeline-1'),
        name=data['name'],
        version=data.get('version', '1.0'),
        nodes=nodes,
        edges=edges,
        settings=settings
    )


def parse_full_format(data: Dict[str, Any]) -> PipelineConfig:
    """
    Parse full visual builder YAML format.

    Full format includes nodes, edges, positions, etc.
    """
    # Required fields
    required = ['id', 'name', 'nodes', 'edges']
    for field in required:
        if field not in data:
            raise YAMLParseError(f"Missing required field: {field}")

    # Parse project if present
    project = None
    if 'project' in data:
        proj_data = data['project']
        project = ProjectSummary(
            id=proj_data['id'],
            name=proj_data['name'],
            path=proj_data.get('path'),
            branch=proj_data.get('branch'),
            commit=proj_data.get('commit')
        )

    # Parse nodes
    nodes: List[PipelineNode] = []
    for node_data in data['nodes']:
        pos_data = node_data['position']
        nodes.append(PipelineNode(
            id=node_data['id'],
            type=node_data['type'],
            position=Position(x=pos_data['x'], y=pos_data['y']),
            data=node_data.get('data', {})
        ))

    # Parse edges
    edges: List[PipelineEdge] = []
    for edge_data in data['edges']:
        edges.append(PipelineEdge(
            id=edge_data['id'],
            source=edge_data['source'],
            target=edge_data['target'],
            source_handle=edge_data.get('sourceHandle'),
            target_handle=edge_data.get('targetHandle'),
            type=edge_data.get('type', 'smoothstep'),
            animated=edge_data.get('animated', True),
            label=edge_data.get('label')
        ))

    # Parse global rules
    global_rules: List[CustomRule] = []
    for rule_data in data.get('global_rules', []):
        global_rules.append(CustomRule(
            id=rule_data['id'],
            name=rule_data.get('name', ''),
            category=rule_data.get('category', 'security'),
            severity=rule_data.get('severity', 'medium'),
            is_blocker=rule_data.get('is_blocker', False),
            description=rule_data.get('description', ''),
            type=rule_data.get('type', 'security'),
            conditions=rule_data.get('conditions', {})
        ))

    # Parse settings
    settings_data = data.get('settings', {})
    settings = PipelineSettings(
        fail_fast=settings_data.get('fail_fast', True),
        timeout=settings_data.get('timeout'),
        parallel=settings_data.get('parallel', False)
    )

    return PipelineConfig(
        id=data['id'],
        name=data['name'],
        version=data.get('version', '1.0'),
        project=project,
        nodes=nodes,
        edges=edges,
        global_rules=global_rules,
        settings=settings
    )


def parse_yaml(file_path: str) -> PipelineConfig:
    """
    Parse YAML pipeline configuration.

    Automatically detects simple or full format.

    Args:
        file_path: Path to YAML file

    Returns:
        PipelineConfig model

    Raises:
        YAMLParseError: If parsing fails
    """
    data = load_yaml(file_path)

    # Detect format
    if 'nodes' in data and 'edges' in data:
        # Full format
        return parse_full_format(data)
    elif 'frames' in data:
        # Simple format
        return parse_simple_format(data)
    else:
        raise YAMLParseError(
            "Invalid format. Must have either 'frames' (simple) or 'nodes'+'edges' (full)"
        )


def parse_yaml_string(yaml_str: str) -> PipelineConfig:
    """
    Parse YAML string directly.

    Useful for testing and programmatic usage.

    Args:
        yaml_str: YAML content as string

    Returns:
        PipelineConfig model

    Raises:
        YAMLParseError: If parsing fails
    """
    try:
        data = yaml.safe_load(yaml_str)

        if not isinstance(data, dict):
            raise YAMLParseError("YAML root must be a dictionary")

        # Detect format
        if 'nodes' in data and 'edges' in data:
            return parse_full_format(data)
        elif 'frames' in data:
            return parse_simple_format(data)
        else:
            raise YAMLParseError(
                "Invalid format. Must have either 'frames' (simple) or 'nodes'+'edges' (full)"
            )

    except yaml.YAMLError as e:
        raise YAMLParseError(f"Invalid YAML syntax: {e}")
