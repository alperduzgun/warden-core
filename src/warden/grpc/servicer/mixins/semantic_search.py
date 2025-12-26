"""
Semantic Search Mixin

Endpoints: SearchCode, SearchSimilarCode, SearchByDescription, IndexProject,
           GetIndexStats, ClearIndex
"""

import time

try:
    from warden.grpc.generated import warden_pb2
except ImportError:
    warden_pb2 = None

from warden.grpc.converters import ProtoConverters

try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class SemanticSearchMixin:
    """Semantic search endpoints (6 endpoints)."""

    async def SearchCode(self, request, context) -> "warden_pb2.SearchResult":
        """Search code using semantic search."""
        logger.info("grpc_search_code", query=request.query)

        try:
            start_time = time.time()

            if hasattr(self.bridge, 'search_code'):
                result = await self.bridge.search_code(
                    query=request.query,
                    language=request.language or None,
                    limit=request.limit or 10
                )

                response = warden_pb2.SearchResult(
                    total_matches=result.get("total", 0),
                    search_time_ms=int((time.time() - start_time) * 1000)
                )

                for chunk in result.get("results", []):
                    response.results.append(ProtoConverters.convert_code_chunk(chunk))

                return response

            return warden_pb2.SearchResult(
                total_matches=0,
                search_time_ms=int((time.time() - start_time) * 1000)
            )

        except Exception as e:
            logger.error("grpc_search_code_error: %s", str(e))
            return warden_pb2.SearchResult()

    async def SearchSimilarCode(self, request, context) -> "warden_pb2.SearchResult":
        """Find similar code using embeddings."""
        logger.info("grpc_search_similar_code")

        try:
            start_time = time.time()

            if hasattr(self.bridge, 'search_similar_code'):
                result = await self.bridge.search_similar_code(
                    code=request.code,
                    language=request.language or None,
                    limit=request.limit or 10
                )

                response = warden_pb2.SearchResult(
                    total_matches=result.get("total", 0),
                    search_time_ms=int((time.time() - start_time) * 1000)
                )

                for chunk in result.get("results", []):
                    response.results.append(ProtoConverters.convert_code_chunk(chunk))

                return response

            return warden_pb2.SearchResult(
                search_time_ms=int((time.time() - start_time) * 1000)
            )

        except Exception as e:
            logger.error("grpc_search_similar_error: %s", str(e))
            return warden_pb2.SearchResult()

    async def SearchByDescription(self, request, context) -> "warden_pb2.SearchResult":
        """Search code by natural language description."""
        logger.info("grpc_search_by_description", query=request.query)

        return await self.SearchCode(request, context)

    async def IndexProject(self, request, context) -> "warden_pb2.IndexResponse":
        """Index project for semantic search."""
        logger.info("grpc_index_project", path=request.path)

        try:
            start_time = time.time()

            if hasattr(self.bridge, 'index_project'):
                result = await self.bridge.index_project(
                    path=request.path,
                    force_reindex=request.force_reindex,
                    languages=list(request.languages) if request.languages else None
                )

                return warden_pb2.IndexResponse(
                    success=True,
                    files_indexed=result.get("files_indexed", 0),
                    chunks_created=result.get("chunks_created", 0),
                    duration_ms=int((time.time() - start_time) * 1000)
                )

            return warden_pb2.IndexResponse(
                success=False,
                error_message="Semantic search indexing not available"
            )

        except Exception as e:
            logger.error("grpc_index_project_error: %s", str(e))
            return warden_pb2.IndexResponse(
                success=False,
                error_message=str(e)
            )

    async def GetIndexStats(self, request, context) -> "warden_pb2.IndexStats":
        """Get semantic search index statistics."""
        logger.info("grpc_get_index_stats")

        try:
            if hasattr(self.bridge, 'get_index_stats'):
                result = await self.bridge.get_index_stats()

                stats = warden_pb2.IndexStats(
                    total_files=result.get("total_files", 0),
                    total_chunks=result.get("total_chunks", 0),
                    last_indexed=result.get("last_indexed", ""),
                    index_size_bytes=result.get("index_size_bytes", 0)
                )
                stats.chunks_by_language.update(result.get("chunks_by_language", {}))
                stats.chunks_by_type.update(result.get("chunks_by_type", {}))

                return stats

            return warden_pb2.IndexStats()

        except Exception as e:
            logger.error("grpc_get_index_stats_error: %s", str(e))
            return warden_pb2.IndexStats()

    async def ClearIndex(self, request, context) -> "warden_pb2.IndexResponse":
        """Clear semantic search index."""
        logger.info("grpc_clear_index")

        try:
            if hasattr(self.bridge, 'clear_index'):
                await self.bridge.clear_index()
                return warden_pb2.IndexResponse(success=True)

            return warden_pb2.IndexResponse(
                success=False,
                error_message="Index clearing not available"
            )

        except Exception as e:
            logger.error("grpc_clear_index_error: %s", str(e))
            return warden_pb2.IndexResponse(
                success=False,
                error_message=str(e)
            )
