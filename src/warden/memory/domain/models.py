"""
Memory Domain Models.

Defines the structure of knowledge stored in Warden's Persistent Memory.
"""

import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import Field

from warden.shared.domain.base_model import BaseDomainModel


@dataclass(frozen=True)
class Citation:
    """
    A source reference grounding a Fact in the codebase.

    Provides ``file:line`` provenance so that project knowledge can be
    traced back to the exact location in source code where it was derived.

    Attributes:
        file: Relative or absolute path to the source file.
        line: Optional 1-based line number within the file.
        text: Optional verbatim snippet or description of the cited content.
    """

    file: str
    line: int | None = None
    text: str = ""


class Fact(BaseDomainModel):
    """
    An atomic unit of knowledge in the system.

    Represents a relationship like: Subject (SecretManager) --Predicate (handles)--> Object (secrets)
    """

    category: str  # e.g., "service_abstraction", "rule", "architectural_pattern"
    subject: str  # e.g., "SecretManager"
    predicate: str  # e.g., "handles", "is_located_in", "bypassed_by"
    object: str  # e.g., "secret_management", "src/warden/secrets", "os.getenv"

    # Unique identifier
    id: str = Field(default_factory=lambda: str(uuid4()))

    # Metadata (provenance, confidence, etc.)
    source: str = "analysis"  # e.g., "analysis", "user", "llm"
    confidence: float = 1.0  # 0.0 to 1.0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    # Typed source references grounding this fact in the codebase
    citations: list[dict[str, Any]] = Field(default_factory=list)

    # Additional structured data
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Convert to JSON-compatible dict."""
        return self.model_dump(by_alias=True, mode="json")

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Fact":
        """Create from JSON dict."""
        return cls.model_validate(data)

    def get_citations(self) -> list[Citation]:
        """Return citations as typed Citation objects."""
        result = []
        for c in self.citations:
            if isinstance(c, dict):
                result.append(
                    Citation(
                        file=c.get("file", ""),
                        line=c.get("line"),
                        text=c.get("text", ""),
                    )
                )
        return result

    def add_citation(self, citation: Citation) -> "Fact":
        """Return a new Fact with the citation appended.

        Since citations is a list of dicts (for Pydantic JSON compatibility),
        the Citation dataclass is serialized before storage.
        """
        citation_dict: dict[str, Any] = {"file": citation.file}
        if citation.line is not None:
            citation_dict["line"] = citation.line
        if citation.text:
            citation_dict["text"] = citation.text

        new_citations = [*self.citations, citation_dict]
        return self.model_copy(update={"citations": new_citations})


class KnowledgeGraph(BaseDomainModel):
    """
    Collection of facts representing the system's knowledge.
    """

    facts: dict[str, Fact] = Field(default_factory=dict)  # id -> Fact
    version: str = "1.0.0"
    last_updated: float = Field(default_factory=time.time)

    def add_fact(self, fact: Fact) -> None:
        """Add or update a fact."""
        fact.updated_at = time.time()
        self.facts[fact.id] = fact
        self.last_updated = time.time()

    def get_facts_by_category(self, category: str) -> list[Fact]:
        """Get all facts in a category."""
        return [f for f in self.facts.values() if f.category == category]

    def get_facts_by_subject(self, subject: str) -> list[Fact]:
        """Get all facts about a subject."""
        return [f for f in self.facts.values() if f.subject == subject]

    def to_json(self) -> dict[str, Any]:
        """Convert to JSON-compatible dict."""
        # Custom to_json to match the manual implementation's "facts" as a list
        return {
            "version": self.version,
            "lastUpdated": self.last_updated,
            "facts": [f.to_json() for f in self.facts.values()],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "KnowledgeGraph":
        """Create from JSON dict."""
        # Handle the fact that "facts" in JSON is a list but in model it's a dict
        facts_list = data.get("facts", [])
        facts_dict = {}
        for f_data in facts_list:
            f = Fact.model_validate(f_data)
            facts_dict[f.id] = f

        return cls(
            version=data.get("version", "1.0.0"), last_updated=data.get("lastUpdated", time.time()), facts=facts_dict
        )
