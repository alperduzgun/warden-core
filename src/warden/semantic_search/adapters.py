from typing import Any, Dict, List, Optional, Protocol

import structlog

logger = structlog.get_logger()


class VectorStoreAdapter(Protocol):
    """Protocol for vector store adapters."""

    async def upsert(
        self, ids: list[str], embeddings: list[list[float]], metadatas: list[dict[str, Any]], documents: list[str]
    ) -> bool:
        """Upsert vectors into the store."""
        ...

    async def query(
        self, query_embeddings: list[list[float]], n_results: int = 5, where: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Query the store."""
        ...

    def delete_collection(self) -> bool:
        """Delete the collection."""
        ...

    def count(self) -> int:
        """Count items in collection."""
        ...

    def get_existing_file_hash(self, file_path: str) -> str | None:
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
                name=collection_name, metadata={"hnsw:space": "cosine"}
            )
        except ImportError:
            raise ImportError("chromadb not installed.")
        except Exception as e:
            logger.error("chroma_init_failed", error=str(e))
            raise

    async def upsert(self, ids, embeddings, metadatas, documents) -> bool:
        try:
            self.collection.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)
            return True
        except Exception as e:
            logger.error("chroma_upsert_failed", error=str(e))
            return False

    async def query(self, query_embeddings, n_results=5, where=None) -> dict[str, Any]:
        try:
            return self.collection.query(query_embeddings=query_embeddings, n_results=n_results, where=where)
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

    def get_existing_file_hash(self, file_path: str) -> str | None:
        try:
            results = self.collection.get(where={"file_path": file_path}, include=["metadatas"], limit=1)
            if results and results["metadatas"]:
                return results["metadatas"][0].get("file_hash")
        except (ValueError, TypeError, RuntimeError):  # Vector store operation
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
                    vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
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

                points.append(
                    models.PointStruct(
                        id=_id,  # Qdrant prefers UUIDs or ints, ensure these are UUIDs upstream!
                        vector=embeddings[i],
                        payload=payload,
                    )
                )

            self.client.upsert(collection_name=self.collection_name, points=points)
            return True
        except Exception as e:
            logger.error("qdrant_upsert_failed", error=str(e))
            return False

    def _translate_where_to_filter(self, where: dict[str, Any] | None):
        """
        Translate ChromaDB-style where dict to Qdrant Filter.

        Args:
            where: ChromaDB-style filter dict

        Returns:
            Qdrant Filter object or None

        Examples:
            {"language": "python"} -> FieldCondition(key="language", match="python")
            {"language": {"$in": ["python", "js"]}} -> FieldCondition with MatchAny
            {"$and": [{"language": "python"}, {"chunk_type": "function"}]} -> Filter with multiple must conditions
        """
        if not where:
            return None

        try:
            from qdrant_client.http import models

            conditions = []

            # Handle $and operator
            if "$and" in where:
                for sub_filter in where["$and"]:
                    for key, value in sub_filter.items():
                        conditions.extend(self._build_conditions(key, value, models))
            else:
                # Handle direct key-value pairs
                for key, value in where.items():
                    conditions.extend(self._build_conditions(key, value, models))

            if not conditions:
                return None

            return models.Filter(must=conditions)

        except Exception as e:
            logger.warning(
                "filter_translation_failed", error=str(e), error_type=type(e).__name__, where=str(where)[:200]
            )
            return None

    def _build_conditions(self, key: str, value: Any, models):
        """
        Build Qdrant field conditions from key-value pairs.

        Args:
            key: Metadata key
            value: Filter value (can be simple value or dict with operators)
            models: Qdrant models module

        Returns:
            List of FieldCondition objects
        """
        conditions = []

        if isinstance(value, dict):
            # Handle operators: {"$eq": val}, {"$ne": val}, {"$in": [vals]}
            for op, val in value.items():
                if op == "$eq":
                    conditions.append(models.FieldCondition(key=key, match=models.MatchValue(value=val)))
                elif op == "$ne":
                    # Qdrant uses must_not for negation
                    conditions.append(models.FieldCondition(key=key, match=models.MatchExcept(**{"except": [val]})))
                elif op == "$in":
                    conditions.append(models.FieldCondition(key=key, match=models.MatchAny(any=val)))
                else:
                    logger.warning("unsupported_filter_operator", operator=op, key=key)
        else:
            # Simple equality: {"language": "python"}
            conditions.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))

        return conditions

    async def query(self, query_embeddings, n_results=5, where=None) -> dict[str, Any]:
        """
        Maps Qdrant search result to Chroma-like structure for compatibility.
        """
        try:
            # Translate where clause to Qdrant filter
            query_filter = self._translate_where_to_filter(where)

            logger.debug(
                "qdrant_search",
                collection=self.collection_name,
                n_results=n_results,
                has_filter=query_filter is not None,
                where=str(where)[:200] if where else None,
            )

            # Query with filter
            search_result = self.client.query_points(
                collection_name=self.collection_name,
                query=query_embeddings[0],
                query_filter=query_filter,
                limit=n_results,
            ).points

            # Map back to Chroma format: {'ids': [[]], 'metadatas': [[]], 'documents': [[]], 'distances': [[]]}
            ids = [[point.id for point in search_result]]
            metadatas = [[point.payload for point in search_result]]  # NOTE: remove 'document' key if needed?
            documents = [[point.payload.get("document") for point in search_result]]
            distances = [[point.score for point in search_result]]

            return {"ids": ids, "metadatas": metadatas, "documents": documents, "distances": distances}

        except Exception as e:
            # If filter translation or query fails, try fallback without filter
            logger.warning(
                "qdrant_query_with_filter_failed_attempting_fallback",
                error=str(e),
                error_type=type(e).__name__,
                has_filter=where is not None,
            )

            # Fallback: try query without filter
            try:
                if where is not None:
                    search_result = self.client.query_points(
                        collection_name=self.collection_name, query=query_embeddings[0], limit=n_results
                    ).points

                    ids = [[point.id for point in search_result]]
                    metadatas = [[point.payload for point in search_result]]
                    documents = [[point.payload.get("document") for point in search_result]]
                    distances = [[point.score for point in search_result]]

                    logger.info("qdrant_fallback_query_succeeded", results_count=len(search_result))

                    return {"ids": ids, "metadatas": metadatas, "documents": documents, "distances": distances}
            except Exception as fallback_error:
                logger.error(
                    "qdrant_fallback_query_also_failed",
                    error=str(fallback_error),
                    error_type=type(fallback_error).__name__,
                )

            # Complete failure
            logger.error("qdrant_query_failed", error=str(e))
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

    def get_existing_file_hash(self, file_path: str) -> str | None:
        try:
            from qdrant_client.http import models

            # Filter by file_path
            scroll_result = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[models.FieldCondition(key="file_path", match=models.MatchValue(value=file_path))]
                ),
                limit=1,
                with_payload=True,
            )
            points, _ = scroll_result
            if points:
                return points[0].payload.get("file_hash")
        except (ValueError, TypeError, RuntimeError):  # Vector store operation
            pass
        return None
