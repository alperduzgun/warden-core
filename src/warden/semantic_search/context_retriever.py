"""
Context retrieval for LLM analysis.

Retrieves relevant code context for AI-powered analysis.
"""

from __future__ import annotations

from typing import List, Optional

import structlog

from warden.semantic_search.models import (
    CodeChunk,
    RetrievalContext,
    SearchQuery,
)
from warden.semantic_search.searcher import SemanticSearcher

logger = structlog.get_logger()


class ContextRetriever:
    """
    Retrieve relevant code context for LLM analysis.

    Optimizes context for LLM token windows.
    """

    def __init__(
        self,
        searcher: SemanticSearcher,
        max_tokens: int = 4000,
        chars_per_token: int = 4,  # Approximate for estimation
    ):
        """
        Initialize context retriever.

        Args:
            searcher: Semantic searcher instance
            max_tokens: Maximum tokens for LLM context window
            chars_per_token: Average characters per token (for estimation)
        """
        self.searcher = searcher
        self.max_tokens = max_tokens
        self.chars_per_token = chars_per_token
        self.max_chars = max_tokens * chars_per_token

        logger.info(
            "context_retriever_initialized",
            max_tokens=max_tokens,
            max_chars=self.max_chars,
        )

    async def retrieve_context(
        self,
        query: str,
        language: Optional[str] = None,
        max_chunks: int = 10,
    ) -> RetrievalContext:
        """
        Retrieve relevant code context for a query.

        Args:
            query: Natural language or code query
            language: Filter by programming language
            max_chunks: Maximum chunks to retrieve

        Returns:
            Retrieval context optimized for LLM
        """
        logger.info(
            "retrieving_context",
            query=query[:100],
            language=language,
            max_chunks=max_chunks,
        )

        # Build search query
        search_query = SearchQuery(
            query_text=query,
            limit=max_chunks * 2,  # Retrieve more, filter later
            min_score=0.5,
            language_filters=[language] if language else [],
        )

        # Execute search
        response = await self.searcher.search(search_query)

        # Select chunks within token budget
        selected_chunks, scores = self._select_chunks_within_budget(
            response.results, max_chunks
        )

        # Calculate stats
        total_chars = sum(chunk.char_count for chunk in selected_chunks)
        estimated_tokens = total_chars // self.chars_per_token

        context = RetrievalContext(
            query_text=query,
            relevant_chunks=selected_chunks,
            total_tokens=estimated_tokens,
            total_characters=total_chars,
            search_scores=scores,
            metadata={
                "language": language,
                "max_chunks": max_chunks,
                "retrieved_chunks": len(selected_chunks),
            },
        )

        logger.info(
            "context_retrieved",
            chunks=len(selected_chunks),
            estimated_tokens=estimated_tokens,
            total_chars=total_chars,
            average_score=context.average_score,
        )

        return context

    def _select_chunks_within_budget(
        self, results: list, max_chunks: int
    ) -> tuple[List[CodeChunk], List[float]]:
        """
        Select chunks that fit within token budget.

        Prioritizes higher-scoring chunks.

        Args:
            results: Search results
            max_chunks: Maximum chunks to select

        Returns:
            Tuple of (selected_chunks, scores)
        """
        selected_chunks = []
        scores = []
        current_chars = 0

        for result in results:
            chunk = result.chunk
            chunk_chars = chunk.char_count

            # Check if adding this chunk exceeds budget
            if current_chars + chunk_chars > self.max_chars:
                logger.debug(
                    "chunk_exceeds_budget",
                    current_chars=current_chars,
                    chunk_chars=chunk_chars,
                    max_chars=self.max_chars,
                )
                break

            # Check max chunks limit
            if len(selected_chunks) >= max_chunks:
                logger.debug(
                    "max_chunks_reached",
                    max_chunks=max_chunks,
                )
                break

            selected_chunks.append(chunk)
            scores.append(result.score)
            current_chars += chunk_chars

        return selected_chunks, scores

    async def retrieve_multi_query_context(
        self,
        queries: List[str],
        language: Optional[str] = None,
        chunks_per_query: int = 5,
    ) -> RetrievalContext:
        """
        Retrieve context for multiple queries.

        Useful for complex analysis requiring multiple perspectives.

        Args:
            queries: List of queries
            language: Filter by programming language
            chunks_per_query: Max chunks per query

        Returns:
            Combined retrieval context
        """
        logger.info(
            "retrieving_multi_query_context",
            num_queries=len(queries),
            chunks_per_query=chunks_per_query,
        )

        all_chunks = []
        all_scores = []
        seen_chunk_ids = set()

        for query in queries:
            context = await self.retrieve_context(
                query=query,
                language=language,
                max_chunks=chunks_per_query,
            )

            # Deduplicate chunks
            for i, chunk in enumerate(context.relevant_chunks):
                if chunk.id not in seen_chunk_ids:
                    all_chunks.append(chunk)
                    all_scores.append(context.search_scores[i])
                    seen_chunk_ids.add(chunk.id)

        # Recheck budget
        final_chunks, final_scores = self._select_chunks_within_budget(
            [
                type("Result", (), {"chunk": chunk, "score": score})
                for chunk, score in zip(all_chunks, all_scores)
            ],
            max_chunks=len(all_chunks),
        )

        total_chars = sum(chunk.char_count for chunk in final_chunks)
        estimated_tokens = total_chars // self.chars_per_token

        combined_query = " | ".join(queries)

        return RetrievalContext(
            query_text=combined_query,
            relevant_chunks=final_chunks,
            total_tokens=estimated_tokens,
            total_characters=total_chars,
            search_scores=final_scores,
            metadata={
                "num_queries": len(queries),
                "unique_chunks": len(final_chunks),
            },
        )

    async def retrieve_file_context(
        self,
        file_path: str,
        max_chunks: int = 10,
    ) -> RetrievalContext:
        """
        Retrieve all chunks from a specific file.

        Args:
            file_path: Path to file
            max_chunks: Maximum chunks to retrieve

        Returns:
            File context
        """
        # Search with file filter
        search_query = SearchQuery(
            query_text=f"file:{file_path}",
            limit=max_chunks,
            min_score=0.0,  # Get all chunks from file
            file_filters=[file_path],
        )

        response = await self.searcher.search(search_query)

        chunks = [result.chunk for result in response.results]
        scores = [result.score for result in response.results]

        total_chars = sum(chunk.char_count for chunk in chunks)
        estimated_tokens = total_chars // self.chars_per_token

        return RetrievalContext(
            query_text=f"File: {file_path}",
            relevant_chunks=chunks,
            total_tokens=estimated_tokens,
            total_characters=total_chars,
            search_scores=scores,
            metadata={
                "file_path": file_path,
            },
        )

    def format_context_for_llm(self, context: RetrievalContext) -> str:
        """
        Format retrieval context for LLM prompt.

        Args:
            context: Retrieval context

        Returns:
            Formatted context string
        """
        parts = [
            f"# Relevant Code Context for: {context.query_text}",
            f"",
            f"Total chunks: {context.chunk_count}",
            f"Estimated tokens: {context.total_tokens}",
            f"Average relevance: {context.average_score:.2f}",
            f"",
        ]

        for i, (chunk, score) in enumerate(
            zip(context.relevant_chunks, context.search_scores), start=1
        ):
            parts.extend(
                [
                    f"## Chunk {i}/{context.chunk_count} (Score: {score:.2f})",
                    f"**File:** `{chunk.relative_path}`",
                    f"**Type:** {chunk.chunk_type.value}",
                    f"**Lines:** {chunk.start_line}-{chunk.end_line}",
                    f"**Language:** {chunk.language}",
                    f"",
                    "```" + chunk.language,
                    chunk.content,
                    "```",
                    f"",
                ]
            )

        return "\n".join(parts)


class ContextOptimizer:
    """
    Optimize context for specific LLM use cases.

    Provides strategies for context selection and formatting.
    """

    @staticmethod
    def deduplicate_chunks(chunks: List[CodeChunk]) -> List[CodeChunk]:
        """
        Remove duplicate chunks based on content hash.

        Args:
            chunks: List of chunks

        Returns:
            Deduplicated list
        """
        seen_ids = set()
        unique_chunks = []

        for chunk in chunks:
            if chunk.id not in seen_ids:
                unique_chunks.append(chunk)
                seen_ids.add(chunk.id)

        logger.debug(
            "chunks_deduplicated",
            original=len(chunks),
            unique=len(unique_chunks),
        )

        return unique_chunks

    @staticmethod
    def sort_by_relevance(
        chunks: List[CodeChunk], scores: List[float]
    ) -> tuple[List[CodeChunk], List[float]]:
        """
        Sort chunks by relevance score (descending).

        Args:
            chunks: List of chunks
            scores: Corresponding scores

        Returns:
            Sorted (chunks, scores)
        """
        pairs = list(zip(chunks, scores))
        pairs.sort(key=lambda x: x[1], reverse=True)

        sorted_chunks = [pair[0] for pair in pairs]
        sorted_scores = [pair[1] for pair in pairs]

        return sorted_chunks, sorted_scores

    @staticmethod
    def filter_by_score(
        chunks: List[CodeChunk], scores: List[float], min_score: float
    ) -> tuple[List[CodeChunk], List[float]]:
        """
        Filter chunks by minimum score.

        Args:
            chunks: List of chunks
            scores: Corresponding scores
            min_score: Minimum score threshold

        Returns:
            Filtered (chunks, scores)
        """
        filtered_pairs = [
            (chunk, score)
            for chunk, score in zip(chunks, scores)
            if score >= min_score
        ]

        if not filtered_pairs:
            return [], []

        filtered_chunks = [pair[0] for pair in filtered_pairs]
        filtered_scores = [pair[1] for pair in filtered_pairs]

        logger.debug(
            "chunks_filtered_by_score",
            original=len(chunks),
            filtered=len(filtered_chunks),
            min_score=min_score,
        )

        return filtered_chunks, filtered_scores
