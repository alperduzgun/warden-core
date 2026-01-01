"""
Memory Domain Models.

Defines the structure of knowledge stored in Warden's Persistent Memory.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from uuid import uuid4

from warden.shared.domain.base_model import BaseDomainModel


@dataclass
class Fact(BaseDomainModel):
    """
    An atomic unit of knowledge in the system.
    
    Represents a relationship like: Subject (SecretManager) --Predicate (handles)--> Object (secrets)
    """
    
    category: str  # e.g., "service_abstraction", "rule", "architectural_pattern"
    subject: str   # e.g., "SecretManager"
    predicate: str # e.g., "handles", "is_located_in", "bypassed_by"
    object: str    # e.g., "secret_management", "src/warden/secrets", "os.getenv"
    
    # Unique identifier
    id: str = field(default_factory=lambda: str(uuid4()))
    
    # Metadata (provenance, confidence, etc.)
    source: str = "analysis"   # e.g., "analysis", "user", "llm"
    confidence: float = 1.0    # 0.0 to 1.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    # Additional structured data
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        """Convert to JSON-compatible dict."""
        return {
            "id": self.id,
            "category": self.category,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "source": self.source,
            "confidence": self.confidence,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> 'Fact':
        """Create from JSON dict."""
        return cls(
            id=data.get("id", str(uuid4())),
            category=data["category"],
            subject=data["subject"],
            predicate=data["predicate"],
            object=data["object"],
            source=data.get("source", "analysis"),
            confidence=data.get("confidence", 1.0),
            created_at=data.get("createdAt", time.time()),
            updated_at=data.get("updatedAt", time.time()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class KnowledgeGraph(BaseDomainModel):
    """
    Collection of facts representing the system's knowledge.
    """
    
    facts: Dict[str, Fact] = field(default_factory=dict)  # id -> Fact
    version: str = "1.0.0"
    last_updated: float = field(default_factory=time.time)
    
    def add_fact(self, fact: Fact) -> None:
        """Add or update a fact."""
        fact.updated_at = time.time()
        self.facts[fact.id] = fact
        self.last_updated = time.time()
        
    def get_facts_by_category(self, category: str) -> List[Fact]:
        """Get all facts in a category."""
        return [f for f in self.facts.values() if f.category == category]
        
    def get_facts_by_subject(self, subject: str) -> List[Fact]:
        """Get all facts about a subject."""
        return [f for f in self.facts.values() if f.subject == subject]

    def to_json(self) -> Dict[str, Any]:
        """Convert to JSON-compatible dict."""
        return {
            "version": self.version,
            "lastUpdated": self.last_updated,
            "facts": [f.to_json() for f in self.facts.values()],
        }
    
    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> 'KnowledgeGraph':
        """Create from JSON dict."""
        graph = cls(
            version=data.get("version", "1.0.0"),
            last_updated=data.get("lastUpdated", time.time()),
        )
        
        for fact_data in data.get("facts", []):
            fact = Fact.from_json(fact_data)
            graph.facts[fact.id] = fact
            
        return graph
