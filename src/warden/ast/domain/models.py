"""
AST domain models.

Universal AST representation for cross-language code analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from warden.shared.domain.base_model import BaseDomainModel
from pydantic import Field
from warden.ast.domain.enums import (
    ASTNodeType,
    ParseStatus,
    CodeLanguage,
    ASTProviderPriority,
)


@dataclass
class SourceLocation:
    """
    Source code location information.

    Tracks position in source file for error reporting and navigation.
    """

    file_path: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "file_path": self.file_path,
            "start_line": self.start_line,
            "start_column": self.start_column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SourceLocation:
        """Create from dictionary."""
        return cls(
            file_path=data["file_path"],
            start_line=data["start_line"],
            start_column=data["start_column"],
            end_line=data["end_line"],
            end_column=data["end_column"],
        )


@dataclass
class ASTNode:
    """
    Universal AST node representation.

    Language-agnostic node structure that can represent AST from any language.
    Providers translate language-specific AST to this universal format.
    """

    node_type: ASTNodeType
    name: Optional[str] = None
    value: Optional[Any] = None
    location: Optional[SourceLocation] = None
    children: List[ASTNode] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    raw_node: Optional[Any] = None  # Original language-specific node (not serialized)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Note: raw_node is excluded from serialization.
        """
        result: Dict[str, Any] = {
            "node_type": self.node_type.value,
            "name": self.name,
            "value": self.value,
            "location": self.location.to_dict() if self.location else None,
            "children": [child.to_dict() for child in self.children],
            "attributes": self.attributes,
        }
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ASTNode:
        """Create from dictionary."""
        return cls(
            node_type=ASTNodeType(data["node_type"]),
            name=data.get("name"),
            value=data.get("value"),
            location=(
                SourceLocation.from_dict(data["location"]) if data.get("location") else None
            ),
            children=[cls.from_dict(child) for child in data.get("children", [])],
            attributes=data.get("attributes", {}),
        )

    def find_nodes(self, node_type: ASTNodeType) -> List[ASTNode]:
        """
        Find all nodes of a specific type (recursive).

        Args:
            node_type: Type of nodes to find

        Returns:
            List of matching nodes
        """
        results: List[ASTNode] = []

        if self.node_type == node_type:
            results.append(self)

        for child in self.children:
            results.extend(child.find_nodes(node_type))

        return results

    def find_by_name(self, name: str) -> List[ASTNode]:
        """
        Find all nodes with specific name (recursive).

        Args:
            name: Node name to search for

        Returns:
            List of matching nodes
        """
        results: List[ASTNode] = []

        if self.name == name:
            results.append(self)

        for child in self.children:
            results.extend(child.find_by_name(name))

        return results


@dataclass
class ParseError:
    """
    Parse error information.

    Captures errors encountered during parsing.
    """

    message: str
    location: Optional[SourceLocation] = None
    error_code: Optional[str] = None
    severity: str = "error"  # error, warning, info

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "message": self.message,
            "location": self.location.to_dict() if self.location else None,
            "error_code": self.error_code,
            "severity": self.severity,
        }


class ParseResult(BaseDomainModel):
    """
    Result of AST parsing operation.

    Contains parsed AST, errors, and metadata.
    """

    status: ParseStatus
    language: CodeLanguage
    provider_name: str
    ast_root: Optional[ASTNode] = None
    errors: List[ParseError] = Field(default_factory=list)
    warnings: List[ParseError] = Field(default_factory=list)
    parse_time_ms: float = 0.0
    file_path: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)

    def is_success(self) -> bool:
        """Check if parsing was successful."""
        return self.status == ParseStatus.SUCCESS

    def is_partial(self) -> bool:
        """Check if parsing was partial (has errors but AST available)."""
        return self.status == ParseStatus.PARTIAL

    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0


@dataclass
class ASTProviderMetadata:
    """
    Metadata about an AST provider.

    Used for provider registration and discovery.
    """

    name: str
    priority: ASTProviderPriority
    supported_languages: List[CodeLanguage]
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    requires_installation: bool = False  # True if needs extra dependencies
    installation_command: Optional[str] = None  # e.g., "pip install tree-sitter-python"

    def supports_language(self, language: CodeLanguage) -> bool:
        """Check if provider supports a language."""
        return language in self.supported_languages

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "priority": self.priority.value,
            "supported_languages": [lang.value for lang in self.supported_languages],
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "requires_installation": self.requires_installation,
            "installation_command": self.installation_command,
        }
