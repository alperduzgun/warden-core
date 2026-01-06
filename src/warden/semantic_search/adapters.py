
from typing import List, Dict, Any, Optional, Protocol
from abc import ABC, abstractmethod
import structlog
from datetime import datetime

logger = structlog.get_logger()

class VectorStoreAdapter(Protocol):
    """Protocol for vector store adapters."""
    
    async def upsert(
        self, 
        ids: List[str], 
        embeddings: List[List[float]], 
        metadatas: List[Dict[str, Any]], 
        documents: List[str]
    ) -> bool:
        """Upsert vectors into the store."""
        ...

    async def query(
        self, 
        query_embeddings: List[List[float]], 
        n_results: int = 5, 
        where: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Query the store."""
        ...

    def delete_collection(self) -> bool:
        """Delete the collection."""
        ...
        
    def count(self) -> int:
        """Count items in collection."""
        ...

    def get_existing_file_hash(self, file_path: str) -> Optional[str]:
        """Get file hash from metadata."""
        ...

class ChromaDBAdapter(VectorStoreAdapter):
    """Adapter for ChromaDB (Local)."""
    
    def __init__(self, chroma_path: str, collection_name: str):
        try:
            import chromadb
            self.client = chromadb.PersistentClient(path=chroma_path)
            self.collection_name = collection_name
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )
        except ImportError:
            raise ImportError("chromadb not installed.")
        except Exception as e:
            logger.error("chroma_init_failed", error=str(e))
            raise

    async def upsert(self, ids, embeddings, metadatas, documents) -> bool:
        try:
            self.collection.upsert(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents
            )
            return True
        except Exception as e:
            logger.error("chroma_upsert_failed", error=str(e))
            return False

    async def query(self, query_embeddings, n_results=5, where=None) -> Dict[str, Any]:
        try:
            return self.collection.query(
                query_embeddings=query_embeddings,
                n_results=n_results,
                where=where
            )
        except Exception as e:
            logger.error("chroma_query_failed", error=str(e))
            return {}

    def delete_collection(self) -> bool:
        try:
            self.client.delete_collection(self.collection_name)
            return True
        except Exception as e:
            logger.error("chroma_delete_failed", error=str(e))
            return False

    def count(self) -> int:
        return self.collection.count()

    def get_existing_file_hash(self, file_path: str) -> Optional[str]:
        try:
            results = self.collection.get(
                where={"file_path": file_path},
                include=["metadatas"],
                limit=1
            )
            if results and results["metadatas"]:
                return results["metadatas"][0].get("file_hash")
        except Exception:
            pass
        return None

class QdrantAdapter(VectorStoreAdapter):
    """Adapter for Qdrant (Cloud/Remote)."""
    
    def __init__(self, url: str, api_key: str, collection_name: str, vector_size: int = 768):
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models
            self.client = QdrantClient(url=url, api_key=api_key)
            self.collection_name = collection_name
            
            # Ensure Collection Exists
            if not self.client.collection_exists(collection_name):
                 self.client.create_collection(
                     collection_name=collection_name,
                     vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE)
                 )
        except ImportError:
            raise ImportError("qdrant-client not installed. Run 'pip install warden-core[cloud]'")
        except Exception as e:
            logger.error("qdrant_init_failed", error=str(e))
            raise

    async def upsert(self, ids, embeddings, metadatas, documents) -> bool:
        try:
            from qdrant_client.http import models
            points = []
            for i, _id in enumerate(ids):
                # Qdrant payload is metadata + document content
                payload = metadatas[i].copy()
                payload["document"] = documents[i]
                
                points.append(models.PointStruct(
                    id=_id, # Qdrant prefers UUIDs or ints, ensure these are UUIDs upstream!
                    vector=embeddings[i],
                    payload=payload
                ))
            
            self.client.upsert(
                collection_name=self.collection_name,
                points=points
            )
            return True
        except Exception as e:
            logger.error("qdrant_upsert_failed", error=str(e))
            return False

    async def query(self, query_embeddings, n_results=5, where=None) -> Dict[str, Any]:
        """
        Maps Qdrant search result to Chroma-like structure for compatibility.
        """
        try:
            # Note: Qdrant searches 1 vector at a time typically via search().
            # If query_embeddings has multiple, we loop? Or use search_batch?
            # Assuming single query vector for now or batch logic.
            # Using client.search() for single vector.
            
            # TODO: Implement complex filtering (where clause translation)
            # For now passing basic search.
            
            search_result = self.client.query_points(
                collection_name=self.collection_name,
                query=query_embeddings[0],
                limit=n_results
            ).points
            
            # Map back to Chroma format: {'ids': [[]], 'metadatas': [[]], 'documents': [[]], 'distances': [[]]}
            ids = [[point.id for point in search_result]]
            metadatas = [[point.payload for point in search_result]] # NOTE: remove 'document' key if needed?
            documents = [[point.payload.get('document') for point in search_result]]
            distances = [[point.score for point in search_result]]
            
            return {
                "ids": ids,
                "metadatas": metadatas,
                "documents": documents,
                "distances": distances
            }
            
        except Exception as e:
            logger.error("qdrant_query_failed", error=str(e), client_attrs=str(dir(self.client)))
            return {}

    def delete_collection(self) -> bool:
        try:
            self.client.delete_collection(self.collection_name)
            return True
        except Exception as e:
            logger.error("qdrant_delete_failed", error=str(e))
            return False

    def count(self) -> int:
        return self.client.count(self.collection_name).count

    def get_existing_file_hash(self, file_path: str) -> Optional[str]:
        try:
            from qdrant_client.http import models
            # Filter by file_path
            scroll_result = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="file_path",
                            match=models.MatchValue(value=file_path)
                        )
                    ]
                ),
                limit=1,
                with_payload=True
            )
            points, _ = scroll_result
            if points:
                return points[0].payload.get("file_hash")
        except Exception:
            pass
        return None
