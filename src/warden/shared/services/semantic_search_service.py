"""
Central Semantic Search Service for Warden.

Provides a unified interface for semantic search operations including:
- Code indexing
- Semantic similarity search
- Context retrieval
- Configuration management
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
import structlog
from pathlib import Path

from warden.semantic_search.embeddings import EmbeddingGenerator
from warden.semantic_search.indexer import CodeIndexer
from warden.semantic_search.searcher import SemanticSearcher
from warden.semantic_search.context_retriever import ContextRetriever
from warden.semantic_search.models import RetrievalContext, SearchResult, IndexStats

logger = structlog.get_logger()

class SemanticSearchService:
    """
    Singleton service for semantic search operations.
    
    Handles lazy initialization and graceful degradation if
    semantic search is disabled or unavailable.
    """
    
    _instance: Optional[SemanticSearchService] = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(SemanticSearchService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: Dict[str, Any] | None = None):
        """
        Initialize the service with configuration.
        """
        if self._initialized:
            return
            
        self.config = config or {}
        self.enabled = self.config.get("enabled", False)
        
        self.embedding_gen: Optional[EmbeddingGenerator] = None
        self.indexer: Optional[CodeIndexer] = None
        self.searcher: Optional[SemanticSearcher] = None
        self.context_retriever: Optional[ContextRetriever] = None
        
        if self.enabled:
            try:
                self._initialize_components()
            except Exception as e:
                logger.error("semantic_search_init_failed", error=str(e))
                self.enabled = False
        
        self._initialized = True
        logger.info("semantic_search_service_ready", enabled=self.enabled)

    def _initialize_components(self):
        """Initialize underlying semantic search components."""
        ss_config = self.config
        
        # 1. Embedding Generator
        self.embedding_gen = EmbeddingGenerator(
            provider=ss_config.get("provider", "openai"),
            model_name=ss_config.get("model", "text-embedding-3-small"),
            api_key=ss_config.get("api_key"),
            azure_endpoint=ss_config.get("azure_endpoint"),
            azure_deployment=ss_config.get("azure_deployment"),
        )
        
        # 2. Indexer
        self.indexer = CodeIndexer(
            chroma_path=ss_config.get("chroma_path", ".warden/embeddings"),
            collection_name=ss_config.get("collection_name", "warden_codebase"),
            embedding_generator=self.embedding_gen,
        )
        
        # 3. Searcher
        self.searcher = SemanticSearcher(
            chroma_path=ss_config.get("chroma_path", ".warden/embeddings"),
            collection_name=ss_config.get("collection_name", "warden_codebase"),
            embedding_generator=self.embedding_gen,
        )
        
        # 4. Context Retriever
        self.context_retriever = ContextRetriever(
            searcher=self.searcher,
            max_tokens=ss_config.get("max_context_tokens", 4000),
        )

    def is_available(self) -> bool:
        """Check if semantic search is enabled and initialized."""
        return self.enabled and self.searcher is not None

    async def search(self, query: str, language: Optional[str] = None, limit: int = 5) -> List[SearchResult]:
        """Perform semantic search."""
        if not self.is_available():
            return []
        
        return await self.searcher.search_by_description(
            description=query,
            language=language,
            limit=limit
        )

    async def get_context(self, query: str, language: Optional[str] = None) -> Optional[RetrievalContext]:
        """Retrieve relevant code context for LLM."""
        if not self.is_available():
            return None
            
        return await self.context_retriever.retrieve_context(
            query=query,
            language=language
        )

    async def index_project(self, project_path: Path, file_paths: List[Path]):
        """Index project files."""
        if not self.is_available():
            return
            
        # Map paths to their content languages (simplified)
        languages = {}
        str_paths = []
        for p in file_paths:
            lang = "python" if p.suffix == ".py" else "unknown"
            languages[str(p)] = lang
            str_paths.append(str(p))
            
        return await self.indexer.index_files(str_paths, languages)
