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
        import os
        from warden.semantic_search.adapters import ChromaDBAdapter, QdrantAdapter
        
        ss_config = self.config
        
        # 1. Embedding Generator
        # Distinguish between Vector Store Provider and Embedding Provider
        # Config 'provider' might refer to vector store (e.g., qdrant)
        emb_provider = ss_config.get("embedding_provider")
        if not emb_provider:
            primary_provider = ss_config.get("provider", "openai")
            if primary_provider in ["qdrant", "pinecone"]:
                emb_provider = "openai" # Default to OpenAI for Cloud DBs unless specified
            else:
                emb_provider = primary_provider

        # For now, we'll just check common env vars if missing
        api_key = ss_config.get("api_key")
        if not api_key:
             # Try to get from global env if not explicitly provided in ss_config
             api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY", "")

        self.embedding_gen = EmbeddingGenerator(
            provider=emb_provider,
            model_name=ss_config.get("model", "text-embedding-3-small"),
            api_key=os.path.expandvars(str(api_key)),
            azure_endpoint=os.path.expandvars(ss_config.get("azure_endpoint", os.environ.get("AZURE_OPENAI_ENDPOINT", ""))),
            azure_deployment=os.path.expandvars(ss_config.get("azure_deployment", os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", ""))),
            device=ss_config.get("device", "cpu"),
        )
        
        # 2. Vector Store Adapter
        provider = ss_config.get("provider", "local")
        database = ss_config.get("database", "chromadb")
        collection_name = ss_config.get("collection_name", "warden_codebase")
        
        adapter = None
        
        if provider == "qdrant" or database == "qdrant":
            url = os.path.expandvars(ss_config.get("url", ""))
            
            # Key priority:
            # 1. qdrant_api_key (specific)
            # 2. api_key (generic, potentially shared with provider but risky)
            # 3. QDRANT_API_KEY env var
            
            config_qdrant_key = ss_config.get("qdrant_api_key")
            if not config_qdrant_key:
                # If specific key not set, try generic key IF provider is NOT the embedding provider 
                # (to avoid using Azure key for Qdrant)
                # But here we simply fallback to generic 'api_key' if provided.
                config_qdrant_key = ss_config.get("api_key")

            api_key = os.path.expandvars(config_qdrant_key or "")
            
            # Fallback to env vars if config expansion failed or was empty
            if not url: url = os.environ.get("QDRANT_URL", "http://localhost:6333")
            if not api_key: api_key = os.environ.get("QDRANT_API_KEY", "")
            
            # Determine vector size from embedding generator
            vector_size = self.embedding_gen.dimensions if self.embedding_gen else 1536
            
            adapter = QdrantAdapter(
                url=url,
                api_key=api_key,
                collection_name=collection_name,
                vector_size=vector_size
            )
        else:
            # Default to Chroma
            chroma_path = ss_config.get("chroma_path", ".warden/embeddings")
            adapter = ChromaDBAdapter(
                chroma_path=chroma_path,
                collection_name=collection_name
            )
        
        # 3. Indexer
        self.indexer = CodeIndexer(
            adapter=adapter,
            embedding_generator=self.embedding_gen,
            project_root=Path(self.config.get("project_root", os.getcwd()))
        )
        
        # 4. Searcher
        self.searcher = SemanticSearcher(
            adapter=adapter,
            embedding_generator=self.embedding_gen,
        )
        
        # 5. Context Retriever
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
        """Index project files in parallel."""
        if not self.is_available():
            return
            
        from warden.shared.utils.language_utils import get_language_from_path
        
        languages = {}
        str_paths = []

        for p in file_paths:
            lang = get_language_from_path(p)
            languages[str(p)] = lang.value
            str_paths.append(str(p))
            
        # Control concurrency at both file and chunk level
        # Control concurrency at both file and chunk level
        # Use configurable concurrency if provided
        max_concurrency = self.config.get("max_indexing_concurrency", 2)
        return await self.indexer.index_files(str_paths, languages, max_concurrency=max_concurrency)
