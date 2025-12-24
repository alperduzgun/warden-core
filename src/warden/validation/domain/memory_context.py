"""
Validation memory context.

Memory context passed to validation frames for context-aware validation.
Contains project information and relevant historical memories.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class MemoryEntry:
    """
    Individual memory entry from previous validation sessions.

    Represents learned patterns, similar issues, or context from past executions.
    """

    content: str
    timestamp: str
    relevance_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectContext:
    """
    Current project context information.

    Contains tech stack, project description, and configuration details
    that help validation frames understand the project's domain.
    """

    # Project identification
    name: str = ""
    description: str = ""

    # Technology stack
    primary_language: str = ""
    frameworks: List[str] = field(default_factory=list)
    libraries: List[str] = field(default_factory=list)

    # Project characteristics
    is_web_application: bool = False
    is_api_service: bool = False
    is_library: bool = False
    is_cli_tool: bool = False

    # Domain-specific information
    domain: str = ""  # e.g., "fintech", "healthcare", "e-commerce"
    compliance_requirements: List[str] = field(default_factory=list)  # e.g., ["PCI-DSS", "HIPAA"]

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "primary_language": self.primary_language,
            "frameworks": self.frameworks,
            "libraries": self.libraries,
            "is_web_application": self.is_web_application,
            "is_api_service": self.is_api_service,
            "is_library": self.is_library,
            "is_cli_tool": self.is_cli_tool,
            "domain": self.domain,
            "compliance_requirements": self.compliance_requirements,
            "metadata": self.metadata,
        }


@dataclass
class ValidationMemoryContext:
    """
    Memory context passed to validation frames for context-aware validation.

    This context provides:
    - Current project information (tech stack, domain, etc.)
    - Relevant memories from previous sessions (semantic search results)
    - Similar validation results from past executions
    - Learned patterns that can improve validation accuracy

    Example usage:
    ```python
    context = ValidationMemoryContext(
        project_context=ProjectContext(
            name="PaymentAPI",
            domain="fintech",
            compliance_requirements=["PCI-DSS"]
        ),
        learned_patterns=[
            "This project often has SQL injection issues in payment code"
        ]
    )
    ```
    """

    # Current project context (tech stack, description, etc.)
    project_context: Optional[ProjectContext] = None

    # Relevant memories from previous sessions (semantic search results)
    # Retrieved based on current file/frame context
    relevant_memories: List[MemoryEntry] = field(default_factory=list)

    # Similar validation results from past executions
    # Filtered by validation frame name
    similar_validations: List[MemoryEntry] = field(default_factory=list)

    # Learned patterns from previous validations
    # E.g., "This project often has SQL injection issues in payment code"
    learned_patterns: List[str] = field(default_factory=list)

    @property
    def is_available(self) -> bool:
        """
        Whether memory context is available.

        Returns:
            False if memory system disabled or no context available, True otherwise
        """
        return (
            self.project_context is not None or
            len(self.relevant_memories) > 0 or
            len(self.similar_validations) > 0 or
            len(self.learned_patterns) > 0
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "project_context": self.project_context.to_dict() if self.project_context else None,
            "relevant_memories": [
                {
                    "content": m.content,
                    "timestamp": m.timestamp,
                    "relevance_score": m.relevance_score,
                    "metadata": m.metadata,
                }
                for m in self.relevant_memories
            ],
            "similar_validations": [
                {
                    "content": m.content,
                    "timestamp": m.timestamp,
                    "relevance_score": m.relevance_score,
                    "metadata": m.metadata,
                }
                for m in self.similar_validations
            ],
            "learned_patterns": self.learned_patterns,
            "is_available": self.is_available,
        }

    @classmethod
    def empty(cls) -> "ValidationMemoryContext":
        """
        Create empty context (used when memory is disabled or unavailable).

        Returns:
            Empty ValidationMemoryContext with no data
        """
        return cls()

    @classmethod
    def from_project(cls, project_context: ProjectContext) -> "ValidationMemoryContext":
        """
        Create context with only project information.

        Args:
            project_context: Project context information

        Returns:
            ValidationMemoryContext with project info only
        """
        return cls(project_context=project_context)
