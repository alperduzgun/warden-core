"""
YAML exporter for pipeline configuration.

Exports PipelineConfig models to YAML format.
Preserves node positions for visual builder compatibility.
"""

from typing import Dict, Any
from pathlib import Path
import yaml

from warden.config.domain.models import PipelineConfig


class YAMLExportError(Exception):
    """YAML export error."""
    pass


def export_to_dict(config: PipelineConfig, simple_format: bool = False) -> Dict[str, Any]:
    """
    Export PipelineConfig to dictionary.

    Args:
        config: Pipeline configuration
        simple_format: If True, export simple CLI-friendly format

    Returns:
        Dictionary ready for YAML serialization
    """
    if simple_format:
        return export_simple_format(config)
    else:
        return export_full_format(config)


def export_simple_format(config: PipelineConfig) -> Dict[str, Any]:
    """
    Export to simple CLI-friendly format.

    Only includes essential fields for quick CLI usage.
    """
    # Extract frame IDs from nodes
    frame_ids = []
    for node in config.nodes:
        if node.type == 'frame':
            frame_id = node.data.get('frameId')
            if frame_id:
                frame_ids.append(frame_id)

    # Build simple YAML
    data: Dict[str, Any] = {
        'version': config.version,
        'name': config.name,
        'frames': frame_ids,
        'settings': {
            'fail_fast': config.settings.fail_fast,
            'parallel': config.settings.parallel
        }
    }

    if config.settings.timeout:
        data['settings']['timeout'] = config.settings.timeout

    if config.project:
        data['project'] = {
            'id': config.project.id,
            'name': config.project.name
        }
        if config.project.path:
            data['project']['path'] = config.project.path
        if config.project.branch:
            data['project']['branch'] = config.project.branch

    return data


def export_full_format(config: PipelineConfig) -> Dict[str, Any]:
    """
    Export to full visual builder format.

    Includes all nodes, edges, positions, rules, etc.
    """
    data: Dict[str, Any] = {
        'version': config.version,
        'id': config.id,
        'name': config.name,
        'nodes': [],
        'edges': [],
        'settings': {
            'fail_fast': config.settings.fail_fast,
            'parallel': config.settings.parallel
        }
    }

    # Add project if present
    if config.project:
        data['project'] = {
            'id': config.project.id,
            'name': config.project.name
        }
        if config.project.path:
            data['project']['path'] = config.project.path
        if config.project.branch:
            data['project']['branch'] = config.project.branch
        if config.project.commit:
            data['project']['commit'] = config.project.commit

    # Add nodes with positions
    for node in config.nodes:
        node_dict: Dict[str, Any] = {
            'id': node.id,
            'type': node.type,
            'position': {
                'x': node.position.x,
                'y': node.position.y
            }
        }
        if node.data:
            node_dict['data'] = node.data
        data['nodes'].append(node_dict)

    # Add edges
    for edge in config.edges:
        edge_dict: Dict[str, Any] = {
            'id': edge.id,
            'source': edge.source,
            'target': edge.target
        }
        if edge.source_handle:
            edge_dict['source_handle'] = edge.source_handle
        if edge.target_handle:
            edge_dict['target_handle'] = edge.target_handle
        if edge.type != 'smoothstep':
            edge_dict['type'] = edge.type
        if not edge.animated:
            edge_dict['animated'] = False
        if edge.label:
            edge_dict['label'] = edge.label

        data['edges'].append(edge_dict)

    # Add global rules if present
    if config.global_rules:
        data['global_rules'] = []
        for rule in config.global_rules:
            rule_dict = {
                'id': rule.id,
                'name': rule.name,
                'category': rule.category,
                'severity': rule.severity,
                'is_blocker': rule.is_blocker,
                'description': rule.description,
                'type': rule.type,
                'conditions': rule.conditions
            }
            if rule.language:
                rule_dict['language'] = rule.language
            data['global_rules'].append(rule_dict)

    # Add timeout if set
    if config.settings.timeout:
        data['settings']['timeout'] = config.settings.timeout

    return data


def export_to_yaml(config: PipelineConfig, file_path: str,
                   simple_format: bool = False) -> None:
    """
    Export PipelineConfig to YAML file.

    Args:
        config: Pipeline configuration
        file_path: Output YAML file path
        simple_format: If True, export simple CLI-friendly format

    Raises:
        YAMLExportError: If export fails
    """
    # Validate path
    if not file_path:
        raise YAMLExportError("file_path cannot be empty")

    path = Path(file_path)

    # Prevent path traversal
    if ".." in file_path:
        raise YAMLExportError("Path traversal not allowed")

    # Create parent directory if needed
    path.parent.mkdir(parents=True, exist_ok=True)

    # Export to dict
    data = export_to_dict(config, simple_format=simple_format)

    # Write YAML
    try:
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                indent=2
            )
    except Exception as e:
        raise YAMLExportError(f"Failed to write YAML: {e}")


def export_to_yaml_string(config: PipelineConfig,
                          simple_format: bool = False) -> str:
    """
    Export PipelineConfig to YAML string.

    Args:
        config: Pipeline configuration
        simple_format: If True, export simple CLI-friendly format

    Returns:
        YAML string

    Raises:
        YAMLExportError: If export fails
    """
    data = export_to_dict(config, simple_format=simple_format)

    try:
        return yaml.dump(
            data,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            indent=2
        )
    except Exception as e:
        raise YAMLExportError(f"Failed to serialize YAML: {e}")
