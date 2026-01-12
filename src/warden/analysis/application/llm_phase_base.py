"""
Base LLM Phase Infrastructure.

Common LLM functionality for all pipeline phases.
Provides caching, fallback, and batch processing capabilities.
"""

import asyncio
import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from warden.llm.factory import create_client
from warden.llm.rate_limiter import RateLimiter, RateLimitConfig
import tiktoken
from warden.shared.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from warden.pipeline.domain.pipeline_context import PipelineContext

logger = get_logger(__name__)


@dataclass
class LLMPhaseConfig:
    """Configuration for LLM-enhanced phase."""

    enabled: bool = False
    model: str = "gpt-4o"
    confidence_threshold: float = 0.7
    batch_size: int = 10
    cache_enabled: bool = True
    max_retries: int = 3
    timeout: int = 120  # Increased from 30s to 120s for LLM API calls
    fallback_to_rules: bool = True
    temperature: float = 0.3  # Lower for more deterministic outputs
    max_tokens: int = 800  # Reduced to stay within context limits
    tpm_limit: int = 1000  # Default Free Tier
    rpm_limit: int = 6     # Default Free Tier


@dataclass
class LLMCache:
    """Simple in-memory cache for LLM responses."""

    cache: Dict[str, Tuple[Any, float]] = field(default_factory=dict)
    ttl: int = 3600  # 1 hour default TTL

    def get(self, key: str) -> Optional[Any]:
        """Get cached response if not expired."""
        if key in self.cache:
            response, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return response
            else:
                del self.cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """Cache response with timestamp."""
        self.cache[key] = (value, time.time())

    def clear_expired(self) -> None:
        """Remove expired entries."""
        current_time = time.time()
        expired = [
            k for k, (_, t) in self.cache.items() if current_time - t >= self.ttl
        ]
        for key in expired:
            del self.cache[key]


class LLMPhaseBase(ABC):
    """
    Base class for LLM-enhanced pipeline phases.

    Provides common functionality:
    - LLM client management
    - Caching mechanism
    - Batch processing
    - Fallback to rule-based
    - Prompt templates
    """

    def __init__(
        self,
        config: Optional[LLMPhaseConfig] = None,
        llm_service: Optional[Any] = None,
        project_root: Optional[Path] = None,
        use_gitignore: bool = True,
        rate_limiter: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize LLM phase base.

        Args:
            config: Phase-specific LLM configuration
            llm_service: Pre-configured LLM service/client
            project_root: Root directory of the project
            use_gitignore: Whether to use .gitignore patterns
            rate_limiter: Optional shared RateLimiter
        """
        self.config = config or LLMPhaseConfig(enabled=False)
        self.llm = llm_service
        self.project_root = project_root
        self.use_gitignore = use_gitignore
        self.memory_manager = kwargs.get('memory_manager')
        self.cache = LLMCache() if self.config.cache_enabled else None

        
        # Initialize Rate Limiter
        # Use injected rate limiter if provided (preferred for shared limits)
        if rate_limiter:
            self.rate_limiter = rate_limiter
        else:
            # Fallback to local rate limiter (per-phase limits)
            self.rate_limiter = RateLimiter(RateLimitConfig(
                tpm=self.config.tpm_limit, 
                rpm=self.config.rpm_limit
            ))
        # Initializing tokenizer (cl100k_base is used by gpt-4, gpt-3.5)
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.tokenizer = None

        # Enable LLM if service is provided
        if llm_service:
            self.config.enabled = True
            logger.info(
                "llm_phase_initialized",
                phase=self.phase_name,
                model=self.config.model,
                cache=self.config.cache_enabled,
                has_llm=True,
            )
        elif self.config.enabled:
            logger.warning(
                "llm_enabled_but_no_service",
                phase=self.phase_name,
                fallback="rule-based",
            )

    @property
    @abstractmethod
    def phase_name(self) -> str:
        """Get phase name for logging."""
        pass

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Get phase-specific system prompt."""
        pass

    @abstractmethod
    def format_user_prompt(self, context: Dict[str, Any]) -> str:
        """Format user prompt with context."""
        pass

    @abstractmethod
    def parse_llm_response(self, response: str) -> Any:
        """Parse LLM response to phase-specific format."""
        pass

    async def analyze_with_llm_async(
        self,
        context: Dict[str, Any],
        use_cache: bool = True,
        pipeline_context: Optional['PipelineContext'] = None,
    ) -> Optional[Any]:
        """
        Analyze with LLM support.

        Args:
            context: Analysis context
            use_cache: Whether to use cache
            pipeline_context: Shared pipeline context for phase communication

        Returns:
            Parsed LLM response or None if failed
        """
        if not self.config.enabled or not self.llm:
            return None

        # Enrich context with pipeline history if available
        if pipeline_context:
            context["pipeline_context"] = pipeline_context.get_llm_context_prompt(self.phase_name)
            context["previous_phases"] = pipeline_context.get_context_for_phase(self.phase_name)

        # Generate cache key
        cache_key = None
        if use_cache and self.cache:
            cache_key = self._generate_cache_key(context)
            cached = self.cache.get(cache_key)
            if cached:
                return cached

        # Check persistent cache (MemoryManager)
        if use_cache and self.memory_manager:
            cache_key = cache_key or self._generate_cache_key(context)
            persistent_cached = self.memory_manager.get_llm_cache(cache_key)
            if persistent_cached:
                logger.debug(
                    "llm_persistent_cache_hit",
                    phase=self.phase_name,
                    key=cache_key[:8],
                )
                # Syced back to in-memory cache for faster next access
                if self.cache:
                    self.cache.set(cache_key, persistent_cached)
                return persistent_cached

        try:
            # Prepare prompts with pipeline context
            system_prompt = self.get_system_prompt()
            if pipeline_context:
                system_prompt = f"{system_prompt}\n\nPIPELINE CONTEXT:\n{pipeline_context.get_llm_context_prompt(self.phase_name)}"

            user_prompt = self.format_user_prompt(context)

            logger.info(
                "llm_analysis_starting",
                phase=self.phase_name,
                context_size=len(str(context)),
                has_pipeline_context=pipeline_context is not None,
                timeout=self.config.timeout,
                max_retries=self.config.max_retries,
            )

            # Call LLM with retry logic
            llm_start_time = time.time()
            response = await self._call_llm_with_retry_async(system_prompt, user_prompt)
            llm_duration = time.time() - llm_start_time

            logger.info(
                "llm_call_completed",
                phase=self.phase_name,
                duration=llm_duration,
                success=response is not None,
            )

            # Record interaction in pipeline context
            if response and pipeline_context:
                pipeline_context.add_llm_interaction(
                    phase=self.phase_name,
                    prompt=user_prompt,
                    response=response.content,
                    confidence=0.85,  # Todo: use response confidence if available
                    usage={
                        "prompt_tokens": response.prompt_tokens,
                        "completion_tokens": response.completion_tokens,
                        "total_tokens": response.total_tokens
                    }
                )

            if response and response.success:
                # Parse response content
                result = self.parse_llm_response(response.content)

                # Cache result (cache the parsed result, not the raw response)
                if cache_key:
                    if self.cache:
                        self.cache.set(cache_key, result)
                    if self.memory_manager:
                        self.memory_manager.set_llm_cache(cache_key, result)
                        # Mark for saving later (or save now if needed)
                        # In the pipeline, orchestrator saves memory at the end

                logger.info(
                    "llm_analysis_complete",
                    phase=self.phase_name,
                    response_length=len(response.content),
                    tokens=response.total_tokens
                )

                return result

        except Exception as e:
            logger.error(
                "llm_analysis_failed",
                phase=self.phase_name,
                error=str(e),
                fallback=self.config.fallback_to_rules,
            )

            if not self.config.fallback_to_rules:
                raise

        return None

    async def analyze_batch_with_llm_async(
        self,
        items: List[Dict[str, Any]],
        use_cache: bool = True,
    ) -> List[Optional[Any]]:
        """
        Analyze multiple items in batches.

        Args:
            items: List of items to analyze
            use_cache: Whether to use cache

        Returns:
            List of results (None for failed items)
        """
        results = []

        # Process in batches
        for i in range(0, len(items), self.config.batch_size):
            batch = items[i : i + self.config.batch_size]

            # Process batch concurrently
            batch_tasks = [
                self.analyze_with_llm_async(item, use_cache) for item in batch
            ]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

            # Handle results
            for result in batch_results:
                if isinstance(result, Exception):
                    logger.warning(
                        "batch_item_failed",
                        phase=self.phase_name,
                        error=str(result),
                    )
                    results.append(None)
                else:
                    results.append(result)

        return results

    async def _call_llm_with_retry_async(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Optional[Any]:  # Returns LlmResponse
        """
        Call LLM with retry logic and PROACTIVE RATE LIMITING.

        Args:
            system_prompt: System prompt
            user_prompt: User prompt

        Returns:
            LLM response or None if all retries failed
        """
        # 1. Estimate Token Cost
        estimated_tokens = 100 # Safety buffer 
        if self.tokenizer:
            try:
                # Count input tokens
                input_text = system_prompt + user_prompt
                estimated_tokens += len(self.tokenizer.encode(input_text))
                # Add estimation for max output tokens (default 800 in config)
                estimated_tokens += self.config.max_tokens
            except Exception:
                pass
        
        # 2. Acquire Rate Limit (Waits here if needed)
        # This prevents 429s by not sending the request until we have budget
        await self.rate_limiter.acquire_async(estimated_tokens)

        for attempt in range(self.config.max_retries):
            try:
                # Call LLM with timeout
                response = await asyncio.wait_for(
                    self.llm.complete_async(
                        prompt=user_prompt,
                        system_prompt=system_prompt
                    ),
                    timeout=self.config.timeout,
                )

                return response

            except asyncio.TimeoutError:
                logger.warning(
                    "llm_timeout",
                    phase=self.phase_name,
                    attempt=attempt + 1,
                    max_attempts=self.config.max_retries,
                )
            except Exception as e:
                logger.warning(
                    "llm_call_failed",
                    phase=self.phase_name,
                    attempt=attempt + 1,
                    error=str(e),
                )

            # Exponential backoff
            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(2 ** attempt)

        return None

    def _generate_cache_key(self, context: Dict[str, Any]) -> str:
        """
        Generate cache key from context.

        Args:
            context: Analysis context

        Returns:
            Hash-based cache key
        """
        # Sort keys for consistent hashing
        sorted_context = json.dumps(context, sort_keys=True)
        hash_obj = hashlib.sha256(sorted_context.encode())
        return f"{self.phase_name}:{hash_obj.hexdigest()}"

    def should_use_llm(self, confidence: float) -> bool:
        """
        Determine if LLM should be used based on confidence.

        Args:
            confidence: Current confidence level (0-1)

        Returns:
            True if LLM should be used
        """
        return (
            self.config.enabled
            and self.llm is not None
            and confidence < self.config.confidence_threshold
        )

    async def enhance_with_llm_async(
        self,
        initial_result: Any,
        confidence: float,
        context: Dict[str, Any],
    ) -> Tuple[Any, float]:
        """
        Enhance initial result with LLM if needed.

        Args:
            initial_result: Initial rule-based result
            confidence: Initial confidence
            context: Additional context

        Returns:
            Enhanced result and new confidence
        """
        if not self.should_use_llm(confidence):
            return initial_result, confidence

        # Add initial result to context
        enhanced_context = {
            **context,
            "initial_result": initial_result,
            "initial_confidence": confidence,
        }

        # Get LLM enhancement
        llm_result = await self.analyze_with_llm_async(enhanced_context)

        if llm_result:
            logger.info(
                "llm_enhancement_applied",
                phase=self.phase_name,
                initial_confidence=confidence,
                enhanced=True,
            )
            # Assume LLM increases confidence
            return llm_result, min(0.95, confidence + 0.3)

        return initial_result, confidence


class PromptTemplates:
    """Common prompt templates for pipeline phases."""

    QUALITY_ANALYSIS = """You are an expert code quality analyzer.
Analyze the provided code and assign quality scores (0-10) for each metric.
Consider the file context (production/test/example) when scoring.
Be strict but fair, considering industry best practices."""

    FRAME_SELECTION = """You are a security validation expert.
Based on the project context and code characteristics, recommend which validation frames should run.
Consider false positive prevention and context-aware analysis."""

    ISSUE_VALIDATION = """You are a security researcher validating potential vulnerabilities.
Determine if the reported issue is a true positive or false positive.
Consider the file context and project type in your assessment."""

    FIX_GENERATION = """You are a senior developer providing security fixes.
Generate production-ready code to fix the identified vulnerability.
Ensure the fix is framework-appropriate and follows best practices."""

    CODE_IMPROVEMENT = """You are a code quality expert suggesting improvements.
Provide specific, actionable suggestions to improve code quality.
Focus on maintainability, readability, and performance."""

    @staticmethod
    def format_with_context(template: str, **kwargs) -> str:
        """Format template with context variables."""
        formatted = template
        for key, value in kwargs.items():
            formatted += f"\n\n{key.upper()}:\n{value}"
        return formatted