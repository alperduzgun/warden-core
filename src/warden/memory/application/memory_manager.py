"""
Memory Manager Application Service.

Manages the persistent knowledge graph (Warden Memory).
"""

import json
import aiofiles
from pathlib import Path
from typing import Optional, List, Dict, Any
import structlog

from warden.memory.domain.models import KnowledgeGraph, Fact
from datetime import datetime

logger = structlog.get_logger(__name__)


class MemoryManager:
    """
    Manages the persistent knowledge graph.
    
    Responsibilities:
    1. Load/Save Knowledge Graph from/to JSON
    2. Provide interface for adding/querying facts
    3. Manage memory persistence lifecycle
    """
    
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.memory_dir = self.project_root / ".warden" / "memory"
        self.memory_file = self.memory_dir / "knowledge_graph.json"
        
        self.knowledge_graph = KnowledgeGraph()
        self._is_loaded = False
        
    async def initialize_async(self) -> None:
        """Initialize memory system (ensure dirs exist, load existing)."""
        if not self.memory_dir.exists():
            try:
                self.memory_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error("memory_dir_creation_failed", error=str(e))
                return
                
        await self.load_async()
        
    async def load_async(self) -> None:
        """Load knowledge graph from disk."""
        if not self.memory_file.exists():
            logger.info("no_existing_memory_found", path=str(self.memory_file))
            return
            
        try:
            async with aiofiles.open(self.memory_file, mode='r') as f:
                content = await f.read()
                data = json.loads(content)
                self.knowledge_graph = KnowledgeGraph.from_json(data)
                self._is_loaded = True
                
            logger.info(
                "memory_loaded", 
                fact_count=len(self.knowledge_graph.facts),
                last_updated=self.knowledge_graph.last_updated
            )
        except Exception as e:
            logger.error("memory_load_failed", error=str(e))
            # Start with fresh graph on error
            self.knowledge_graph = KnowledgeGraph()
            
    async def save_async(self) -> None:
        """Save knowledge graph to disk."""
        if not self.memory_dir.exists():
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            
        try:
            data = self.knowledge_graph.to_json()
            # Ensure pretty print for human readability/debug
            content = json.dumps(data, indent=2)
            
            async with aiofiles.open(self.memory_file, mode='w') as f:
                await f.write(content)
                
            logger.info(
                "memory_saved", 
                fact_count=len(self.knowledge_graph.facts),
                path=str(self.memory_file)
            )
        except Exception as e:
            logger.error("memory_save_failed", error=str(e))

    def add_fact(self, fact: Fact) -> None:
        """Add a fact to memory."""
        self.knowledge_graph.add_fact(fact)
        
    def get_facts_by_category(self, category: str) -> List[Fact]:
        """Get facts by category."""
        return self.knowledge_graph.get_facts_by_category(category)

    def get_service_abstractions(self) -> List[Fact]:
        """Convenience method to get service abstraction facts."""
        return self.knowledge_graph.get_facts_by_category("service_abstraction")

    def store_service_abstraction(self, abstraction: Dict[str, Any]) -> None:
        """
        Store a detected service abstraction as a Fact.
        
        Args:
            abstraction: Dictionary from ServiceAbstraction.to_dict()
        """
        # Create a unique ID based on class name to enable updates
        fact_id = f"service:{abstraction['name']}"
        
        fact = Fact(
            id=fact_id,
            category="service_abstraction",
            subject=abstraction['name'],
            predicate="implements",
            object=abstraction['category'],
            source="ServiceAbstractionDetector",
            confidence=abstraction.get('confidence', 1.0),
            metadata=abstraction  # Store full abstraction data in metadata
        )
        
        self.add_fact(fact)

    def get_file_state(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Get stored state for a file (hash, findings, etc).
        
        Args:
            file_path: Absolute path to the file
            
        Returns:
            Dictionary with stored file state or None if not found
        """
        fact_id = f"filestate:{file_path}"
        fact = self.knowledge_graph.facts.get(fact_id)
        if fact:
            return fact.metadata
                
        return None

    def update_file_state(
        self, 
        file_path: str, 
        content_hash: str,
        findings_count: int = 0,
        context_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Update stored state for a file.
        
        Args:
            file_path: Absolute path to the file
            content_hash: SHA-256 hash of file content
            findings_count: Number of findings found in last scan
            context_data: Full context info (type, is_generated, weights, etc.)
        """
        fact_id = f"filestate:{file_path}"
        
        # In a dictionary-based system, assignment is update/overwrite
        metadata = {
            "file_path": file_path,
            "content_hash": content_hash,
            "findings_count": findings_count,
            "last_scan": datetime.now().isoformat()
        }

        if context_data:
            metadata["context_data"] = context_data
        
        fact = Fact(
            id=fact_id,
            category="file_state",
            subject=file_path,
            predicate="has_state",
            object=content_hash,
            source="MemoryManager",
            confidence=1.0,
            metadata=metadata
        )
        
        logger.debug("adding_file_state_fact", fact_id=fact_id)
        self.add_fact(fact)

    def get_project_purpose(self) -> Optional[Dict[str, str]]:
        """
        Get stored project purpose and architecture description.
        """
        fact_id = "project_purpose:global"
        fact = self.knowledge_graph.facts.get(fact_id)
        if fact:
            return {
                "purpose": fact.metadata.get("purpose", ""),
                "architecture_description": fact.metadata.get("architecture_description", "")
            }
        return None

    def update_project_purpose(
        self, 
        purpose: str, 
        architecture_description: str = ""
    ) -> None:
        """
        Update stored project purpose.
        """
        fact_id = "project_purpose:global"
        
        metadata = {
            "purpose": purpose,
            "architecture_description": architecture_description,
            "updated_at": datetime.now().isoformat()
        }
        
        fact = Fact(
            id=fact_id,
            category="project_purpose",
            subject=self.project_root.name,
            predicate="has_purpose",
            object=purpose[:100],  # Short summary as object
            source="ProjectPurposeDetector",
            confidence=1.0,
            metadata=metadata
        )
        
        self.add_fact(fact)

    def get_environment_hash(self) -> Optional[str]:
        """Get stored environment hash."""
        fact_id = "environment:global"
        fact = self.knowledge_graph.facts.get(fact_id)
        if fact:
            return fact.metadata.get("hash")
        return None

    def update_environment_hash(self, env_hash: str) -> None:
        """Update stored environment hash."""
        fact_id = "environment:global"
        
        metadata = {
            "hash": env_hash,
            "updated_at": datetime.now().isoformat()
        }
        
        fact = Fact(
            id=fact_id,
            category="environment_state",
            subject="warden_environment",
            predicate="has_hash",
            object=env_hash,
            source="PreAnalysisPhase",
            confidence=1.0,
            metadata=metadata
        )
        
        self.add_fact(fact)
