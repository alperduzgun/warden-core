"""
Memory Manager Application Service.

Manages the persistent knowledge graph (Warden Memory).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles
import structlog

from warden.memory.domain.models import Fact, KnowledgeGraph

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
            async with aiofiles.open(self.memory_file) as f:
                content = await f.read()
                data = json.loads(content)
                self.knowledge_graph = KnowledgeGraph.from_json(data)
                self._is_loaded = True

            logger.debug(
                "memory_loaded",
                fact_count=len(self.knowledge_graph.facts),
                last_updated=self.knowledge_graph.last_updated,
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

            async with aiofiles.open(self.memory_file, mode="w") as f:
                await f.write(content)

            logger.debug("memory_saved", fact_count=len(self.knowledge_graph.facts), path=str(self.memory_file))
        except Exception as e:
            logger.error("memory_save_failed", error=str(e))

    def add_fact(self, fact: Fact) -> None:
        """Add a fact to memory."""
        self.knowledge_graph.add_fact(fact)

    def get_facts_by_category(self, category: str) -> list[Fact]:
        """Get facts by category."""
        return self.knowledge_graph.get_facts_by_category(category)

    def get_service_abstractions(self) -> list[Fact]:
        """Convenience method to get service abstraction facts."""
        return self.knowledge_graph.get_facts_by_category("service_abstraction")

    def store_service_abstraction(self, abstraction: dict[str, Any]) -> None:
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
            subject=abstraction["name"],
            predicate="implements",
            object=abstraction["category"],
            source="ServiceAbstractionDetector",
            confidence=abstraction.get("confidence", 1.0),
            metadata=abstraction,  # Store full abstraction data in metadata
        )

        self.add_fact(fact)

    def get_file_state(self, file_path: str) -> dict[str, Any] | None:
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
        self, file_path: str, content_hash: str, findings_count: int = 0, context_data: dict[str, Any] | None = None
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
            "last_scan": datetime.now().isoformat(),
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
            metadata=metadata,
        )

        logger.debug("adding_file_state_fact", fact_id=fact_id)
        self.add_fact(fact)

    def get_llm_cache(self, key: str) -> Any | None:
        """
        Get cached LLM response from memory.

        Args:
            key: Cache key (usually hash of prompt/context)

        Returns:
            Cached response data or None
        """
        fact_id = f"llmcache:{key}"
        fact = self.knowledge_graph.facts.get(fact_id)
        if fact:
            # Check TTL if stored in metadata
            # For LLM cache, we might want longer persistence than file state
            return fact.metadata.get("response")
        return None

    def set_llm_cache(self, key: str, value: Any) -> None:
        """
        Store LLM response in memory.

        Args:
            key: Unique cache key
            value: Data to cache
        """
        fact_id = f"llmcache:{key}"

        fact = Fact(
            id=fact_id,
            category="llm_cache",
            subject=key[:50],  # Use prefix as subject
            predicate="cached_response",
            object="json_data",
            source="LLMPhaseBase",
            confidence=1.0,
            metadata={"key": key, "response": value, "cached_at": datetime.now().isoformat()},
        )

        self.add_fact(fact)

    def get_project_purpose(self) -> dict[str, str] | None:
        """
        Get stored project purpose and architecture description.
        """
        fact_id = "project_purpose:global"
        fact = self.knowledge_graph.facts.get(fact_id)
        if fact:
            return {
                "purpose": fact.metadata.get("purpose", ""),
                "architecture_description": fact.metadata.get("architecture_description", ""),
            }
        return None

    def update_project_purpose(self, purpose: str, architecture_description: str = "") -> None:
        """
        Update stored project purpose.
        """
        fact_id = "project_purpose:global"

        metadata = {
            "purpose": purpose,
            "architecture_description": architecture_description,
            "updated_at": datetime.now().isoformat(),
        }

        fact = Fact(
            id=fact_id,
            category="project_purpose",
            subject=self.project_root.name,
            predicate="has_purpose",
            object=purpose[:100],  # Short summary as object
            source="ProjectPurposeDetector",
            confidence=1.0,
            metadata=metadata,
        )

        self.add_fact(fact)

    def get_environment_hash(self) -> str | None:
        """Get stored environment hash."""
        fact_id = "environment:global"
        fact = self.knowledge_graph.facts.get(fact_id)
        if fact:
            return fact.metadata.get("hash")
        return None

    def update_environment_hash(self, env_hash: str) -> None:
        """Update stored environment hash."""
        fact_id = "environment:global"

        metadata = {"hash": env_hash, "updated_at": datetime.now().isoformat()}

        fact = Fact(
            id=fact_id,
            category="environment_state",
            subject="warden_environment",
            predicate="has_hash",
            object=env_hash,
            source="PreAnalysisPhase",
            confidence=1.0,
            metadata=metadata,
        )

        self.add_fact(fact)

    def get_module_map(self) -> dict[str, Any] | None:
        """
        Get stored module map with risk classifications.

        Returns:
            Dictionary mapping module names to ModuleInfo-like dicts,
            or None if not stored.
        """
        fact_id = "intelligence:module_map"
        fact = self.knowledge_graph.facts.get(fact_id)
        if fact:
            return fact.metadata.get("modules", {})
        return None

    def update_module_map(self, module_map: dict[str, Any]) -> None:
        """
        Store module map with risk classifications.

        Args:
            module_map: Dictionary mapping module names to ModuleInfo dicts.
                        Each ModuleInfo should have: name, path, risk_level,
                        security_focus, description.
        """
        fact_id = "intelligence:module_map"

        # Convert ModuleInfo objects to dicts if needed
        serialized_map = {}
        for name, info in module_map.items():
            if hasattr(info, "to_json"):
                serialized_map[name] = info.to_json()
            elif isinstance(info, dict):
                serialized_map[name] = info
            else:
                logger.warning("invalid_module_info", name=name, type=type(info).__name__)

        metadata = {
            "modules": serialized_map,
            "module_count": len(serialized_map),
            "updated_at": datetime.now().isoformat(),
        }

        fact = Fact(
            id=fact_id,
            category="project_intelligence",
            subject="module_map",
            predicate="contains",
            object=f"{len(serialized_map)} modules",
            source="ProjectPurposeDetector",
            confidence=1.0,
            metadata=metadata,
        )

        self.add_fact(fact)
        logger.debug("module_map_stored", module_count=len(serialized_map))

    def get_security_posture(self) -> str | None:
        """
        Get stored security posture for the project.

        Returns:
            Security posture string (paranoid, strict, standard, relaxed)
            or None if not stored.
        """
        fact_id = "intelligence:security_posture"
        fact = self.knowledge_graph.facts.get(fact_id)
        if fact:
            return fact.metadata.get("posture")
        return None

    def update_security_posture(self, posture: str) -> None:
        """
        Store security posture classification.

        Args:
            posture: Security posture value (paranoid, strict, standard, relaxed).
        """
        fact_id = "intelligence:security_posture"

        metadata = {"posture": posture, "updated_at": datetime.now().isoformat()}

        fact = Fact(
            id=fact_id,
            category="project_intelligence",
            subject="security_posture",
            predicate="is",
            object=posture,
            source="ProjectPurposeDetector",
            confidence=1.0,
            metadata=metadata,
        )

        self.add_fact(fact)
        logger.debug("security_posture_stored", posture=posture)
