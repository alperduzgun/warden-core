"""
Memory Domain Models.

Defines the structure of knowledge stored in Warden's Persistent Memory.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from uuid import uuid4

from warden.shared.domain.base_model import BaseDomainModel


from datetime import datetime
from pydantic import Field
from typing import Dict, List, Optional, Any
from uuid import uuid4

from warden.shared.domain.base_model import BaseDomainModel


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
    id: str = Field(default_factory=lambda: str(uuid4()))
    
    # Metadata (provenance, confidence, etc.)
    source: str = "analysis"   # e.g., "analysis", "user", "llm"
    confidence: float = 1.0    # 0.0 to 1.0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    
    # Additional structured data
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        """Convert to JSON-compatible dict."""
        return self.model_dump(by_alias=True, mode='json')
    
    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> 'Fact':
        """Create from JSON dict."""
        return cls.model_validate(data)


class KnowledgeGraph(BaseDomainModel):
    """
    Collection of facts representing the system's knowledge.
    """
    
    facts: Dict[str, Fact] = Field(default_factory=dict)  # id -> Fact
    version: str = "1.0.0"
    last_updated: float = Field(default_factory=time.time)
    
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
        # Custom to_json to match the manual implementation's "facts" as a list
        return {
            "version": self.version,
            "lastUpdated": self.last_updated,
            "facts": [f.to_json() for f in self.facts.values()],
        }
    
    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> 'KnowledgeGraph':
        """Create from JSON dict."""
        # Handle the fact that "facts" in JSON is a list but in model it's a dict
        facts_list = data.get("facts", [])
        facts_dict = {}
        for f_data in facts_list:
            f = Fact.model_validate(f_data)
            facts_dict[f.id] = f
            
        return cls(
            version=data.get("version", "1.0.0"),
            last_updated=data.get("lastUpdated", time.time()),
            facts=facts_dict
        )
