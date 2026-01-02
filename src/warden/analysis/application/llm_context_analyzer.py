"""
LLM-Enhanced Context Analyzer for PRE-ANALYSIS Phase.

Uses LLM to improve context detection accuracy for ambiguous files.
Falls back to rule-based detection when LLM is unavailable.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import structlog

from warden.llm.factory import create_client
from warden.llm.config import LlmConfiguration, load_llm_config_async
from warden.llm.types import LlmRequest, LlmResponse
from warden.analysis.domain.file_context import FileContext
from warden.analysis.domain.project_context import ProjectContext, Framework, ProjectType

logger = structlog.get_logger()


@dataclass
class LlmContextDecision:
    """LLM decision for file/project context."""

    context: str  # FileContext or ProjectType value
    confidence: float  # 0.0 to 1.0
    reasoning: str  # Why this context was chosen
    secondary_contexts: List[str] = None  # Other possible contexts


class LlmContextAnalyzer:
    """
    LLM-powered context analyzer for improved accuracy.

    Enhances rule-based detection with LLM intelligence for:
    - Ambiguous files (confidence < threshold)
    - Complex project structures
    - Custom frameworks and patterns
    """

    def __init__(
        self,
        llm_config: Optional[LlmConfiguration] = None,
        confidence_threshold: float = 0.7,
        batch_size: int = 10,
        cache_enabled: bool = True,
    ):
        """
        Initialize LLM context analyzer.

        Args:
            llm_config: LLM configuration (uses default if None)
            confidence_threshold: Use LLM when confidence below this (default: 0.7)
            batch_size: Number of files to analyze per LLM call
            cache_enabled: Cache LLM responses for similar patterns
        """
        try:
            self.llm = create_client(llm_config) if llm_config else None
        except Exception as e:
            logger.warning(
                "llm_client_creation_failed",
                error=str(e),
                fallback="no_llm",
            )
            self.llm = None

        self.confidence_threshold = confidence_threshold
        self.batch_size = batch_size
        self.cache_enabled = cache_enabled
        self.cache: Dict[str, LlmContextDecision] = {}

        logger.info(
            "llm_context_analyzer_initialized",
            llm_enabled=self.llm is not None,
            confidence_threshold=confidence_threshold,
            batch_size=batch_size,
            cache_enabled=cache_enabled,
        )

    async def analyze_file_context(
        self,
        file_path: Path,
        initial_context: FileContext,
        initial_confidence: float,
        file_content: Optional[str] = None,
    ) -> Tuple[FileContext, float, str]:
        """
        Analyze file context with LLM enhancement.

        Args:
            file_path: Path to the file
            initial_context: Context from rule-based detection
            initial_confidence: Confidence from rule-based detection
            file_content: Optional file content (will read if not provided)

        Returns:
            (context, confidence, detection_method)
        """
        # Skip LLM if confidence is high enough
        if initial_confidence >= self.confidence_threshold:
            return initial_context, initial_confidence, "rule-based"

        # Skip if LLM not available
        if not self.llm:
            logger.debug(
                "llm_not_available_for_context",
                file=str(file_path),
                fallback_context=initial_context.value,
            )
            return initial_context, initial_confidence, "rule-based"

        # Check cache
        cache_key = self._get_cache_key(file_path)
        if self.cache_enabled and cache_key in self.cache:
            cached = self.cache[cache_key]
            return FileContext(cached.context), cached.confidence, "llm-cached"

        logger.info(
            "using_llm_for_ambiguous_file",
            file=str(file_path),
            initial_context=initial_context.value,
            initial_confidence=initial_confidence,
        )

        try:
            # Read file content if not provided
            if file_content is None:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    file_content = f.read()[:5000]  # Limit for LLM

            # Call LLM for analysis
            decision = await self._analyze_with_llm(
                file_path=file_path,
                file_content=file_content,
                initial_guess=initial_context,
            )

            # Cache result
            if self.cache_enabled:
                self.cache[cache_key] = decision

            # Convert to FileContext
            try:
                context = FileContext(decision.context)
            except ValueError:
                # Invalid context from LLM, fallback
                logger.warning(
                    "llm_returned_invalid_context",
                    context=decision.context,
                    fallback=initial_context.value,
                )
                context = initial_context

            return context, decision.confidence, "llm-enhanced"

        except Exception as e:
            logger.error(
                "llm_context_analysis_failed",
                error=str(e),
                fallback=initial_context.value,
            )
            return initial_context, initial_confidence, "rule-based-fallback"

    async def analyze_project_structure(
        self,
        project_root: Path,
        file_list: List[Path],
        config_files: Dict[str, str],
        initial_project_type: ProjectType,
        initial_framework: Framework,
        initial_confidence: float,
    ) -> Tuple[ProjectType, Framework, float]:
        """
        Analyze project structure with LLM enhancement.

        Args:
            project_root: Root directory of project
            file_list: List of files in project
            config_files: Detected configuration files
            initial_project_type: Initial detection
            initial_framework: Initial framework detection
            initial_confidence: Initial confidence

        Returns:
            (project_type, framework, confidence)
        """
        # Skip LLM if confidence is high enough
        if initial_confidence >= self.confidence_threshold:
            return initial_project_type, initial_framework, initial_confidence

        # Skip if LLM not available
        if not self.llm:
            return initial_project_type, initial_framework, initial_confidence

        logger.info(
            "using_llm_for_project_structure",
            project=str(project_root),
            initial_type=initial_project_type.value,
            initial_framework=initial_framework.value,
            initial_confidence=initial_confidence,
        )

        try:
            # Prepare project summary for LLM
            project_summary = self._create_project_summary(
                project_root, file_list, config_files
            )

            # Call LLM for analysis
            decision = await self._analyze_project_with_llm(
                project_summary=project_summary,
                initial_type=initial_project_type,
                initial_framework=initial_framework,
            )

            # Parse and validate results
            try:
                project_type = ProjectType(decision.context.split("|")[0])
                framework = Framework(decision.context.split("|")[1]) if "|" in decision.context else initial_framework
            except (ValueError, IndexError):
                logger.warning(
                    "llm_project_analysis_parse_error",
                    response=decision.context,
                )
                return initial_project_type, initial_framework, initial_confidence

            return project_type, framework, decision.confidence

        except Exception as e:
            logger.error(
                "llm_project_analysis_failed",
                error=str(e),
            )
            return initial_project_type, initial_framework, initial_confidence

    async def analyze_batch(
        self,
        files: List[Tuple[Path, FileContext, float]],
    ) -> List[Tuple[FileContext, float, str]]:
        """
        Analyze multiple files in a single LLM call for efficiency.

        Args:
            files: List of (file_path, initial_context, initial_confidence)

        Returns:
            List of (context, confidence, method) for each file
        """
        if not self.llm:
            return [(ctx, conf, "rule-based") for _, ctx, conf in files]

        # Filter files that need LLM analysis
        needs_llm = [
            (path, ctx, conf)
            for path, ctx, conf in files
            if conf < self.confidence_threshold
        ]

        if not needs_llm:
            return [(ctx, conf, "rule-based") for _, ctx, conf in files]

        logger.info(
            "batch_llm_context_analysis",
            total_files=len(files),
            needs_llm=len(needs_llm),
        )

        try:
            # Create batch prompt
            batch_prompt = self._create_batch_prompt(needs_llm)

            # Call LLM
            response = await self._call_llm_batch(batch_prompt)

            # Parse batch response
            decisions = self._parse_batch_response(response, len(needs_llm))

            # Merge results
            results = []
            llm_index = 0
            for path, ctx, conf in files:
                if conf >= self.confidence_threshold:
                    results.append((ctx, conf, "rule-based"))
                else:
                    if llm_index < len(decisions):
                        decision = decisions[llm_index]
                        try:
                            new_ctx = FileContext(decision.context)
                            results.append((new_ctx, decision.confidence, "llm-batch"))
                        except ValueError:
                            results.append((ctx, conf, "rule-based-fallback"))
                    else:
                        results.append((ctx, conf, "rule-based-fallback"))
                    llm_index += 1

            return results

        except Exception as e:
            logger.error(
                "batch_llm_analysis_failed",
                error=str(e),
            )
            return [(ctx, conf, "rule-based-fallback") for _, ctx, conf in files]

    async def _analyze_with_llm(
        self,
        file_path: Path,
        file_content: str,
        initial_guess: FileContext,
    ) -> LlmContextDecision:
        """Call LLM to analyze file context."""

        prompt = f"""Analyze this file and determine its context in the software project.

File: {file_path}
Initial detection: {initial_guess.value}

File content (first 5000 chars):
```
{file_content}
```

Possible contexts:
- production: Real production code
- test: Test files (unit tests, integration tests)
- example: Example or demo code
- framework: Framework or library internal code
- documentation: Documentation files
- configuration: Configuration files
- generated: Auto-generated code
- vendor: Third-party code
- migration: Database migrations
- fixture: Test fixtures or mock data
- script: Utility scripts
- unknown: Cannot determine

Analyze the file considering:
1. File path and naming conventions
2. Import statements and dependencies
3. Code patterns and structure
4. Comments and documentation
5. Decorators and annotations

Return JSON:
{{
  "context": "the_most_appropriate_context",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation",
  "secondary_contexts": ["other_possible_contexts"]
}}"""

        response = await self._call_llm(prompt)
        return self._parse_llm_response(response.content)

    async def _analyze_project_with_llm(
        self,
        project_summary: str,
        initial_type: ProjectType,
        initial_framework: Framework,
    ) -> LlmContextDecision:
        """Call LLM to analyze project structure."""

        prompt = f"""Analyze this project structure and determine its type and framework.

{project_summary}

Initial detection:
- Type: {initial_type.value}
- Framework: {initial_framework.value}

Possible project types:
- monorepo: Multiple projects in one repository
- library: Reusable library or package
- application: Standalone application
- cli: Command-line tool
- microservice: Single microservice
- api: API-only project
- frontend: Frontend application
- fullstack: Full-stack application

Possible frameworks:
- django, fastapi, flask (Python)
- react, vue, angular, svelte (JavaScript)
- express (Node.js)
- none: No framework
- custom: Custom framework

Analyze considering:
1. Directory structure
2. Configuration files
3. Dependencies
4. File naming patterns
5. Common framework indicators

Return JSON:
{{
  "context": "project_type|framework",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation"
}}"""

        response = await self._call_llm(prompt)
        return self._parse_llm_response(response.content)

    async def _call_llm(self, prompt: str) -> LlmResponse:
        """Call LLM with prompt."""
        request = LlmRequest(
            system_prompt="You are an expert code analyzer specializing in understanding project structure and file contexts. Provide accurate, concise analysis.",
            user_message=prompt,
            max_tokens=500,
            temperature=0.0,  # Deterministic
        )

        return await self.llm.send_async(request)

    async def _call_llm_batch(self, batch_prompt: str) -> LlmResponse:
        """Call LLM for batch analysis."""
        request = LlmRequest(
            system_prompt="You are an expert code analyzer. Analyze multiple files efficiently and accurately.",
            user_message=batch_prompt,
            max_tokens=2000,
            temperature=0.0,
        )

        return await self.llm.send_async(request)

    def _parse_llm_response(self, response: str) -> LlmContextDecision:
        """Parse LLM JSON response."""
        try:
            if not response or not response.strip():
                raise ValueError("Empty response from LLM")

            # Extract JSON from response
            json_str = self._extract_json(response)
            if not json_str:
                raise ValueError("No JSON found in response")

            data = json.loads(json_str)

            return LlmContextDecision(
                context=data.get("context", "unknown"),
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning", ""),
                secondary_contexts=data.get("secondary_contexts", []),
            )
        except Exception as e:
            # Downgrade to warning for resilience
            logger.warning(
                "llm_response_parse_failed_using_fallback",
                error=str(e),
                response_preview=response[:200] if response else "empty",
            )
            return LlmContextDecision(
                context="unknown",
                confidence=0.0,
                reasoning=f"Parse error: {str(e)}",
            )

    def _extract_json(self, text: str) -> str:
        """Extract JSON from LLM response."""
        text = text.strip()

        # Remove markdown code blocks
        if "```json" in text:
            start = text.find("{", text.find("```json"))
            end = text.rfind("}", 0, text.rfind("```") if "```" in text[start:] else len(text)) + 1
        else:
            start = text.find("{")
            end = text.rfind("}") + 1

        if start != -1 and end > start:
            return text[start:end]

        return ""  # Return empty string if no JSON found

    def _create_project_summary(
        self,
        project_root: Path,
        file_list: List[Path],
        config_files: Dict[str, str],
    ) -> str:
        """Create project summary for LLM analysis."""
        # Directory structure
        dirs = set()
        for file in file_list[:100]:  # Limit for performance
            dirs.add(str(file.parent.relative_to(project_root)))

        # File extensions
        extensions = {}
        for file in file_list:
            ext = file.suffix
            if ext:
                extensions[ext] = extensions.get(ext, 0) + 1

        summary = f"""Project: {project_root.name}

Configuration files:
{chr(10).join(f"- {name}: {type}" for name, type in list(config_files.items())[:20])}

Top directories:
{chr(10).join(f"- {d}" for d in sorted(dirs)[:20])}

File types (by extension):
{chr(10).join(f"- {ext}: {count} files" for ext, count in sorted(extensions.items(), key=lambda x: x[1], reverse=True)[:10])}

Total files: {len(file_list)}
"""
        return summary

    def _create_batch_prompt(
        self,
        files: List[Tuple[Path, FileContext, float]]
    ) -> str:
        """Create batch analysis prompt."""
        prompt = "Analyze these files and determine their contexts:\n\n"

        for i, (path, initial_ctx, conf) in enumerate(files):
            prompt += f"""File {i}:
- Path: {path}
- Initial guess: {initial_ctx.value} (confidence: {conf:.2f})

"""

        prompt += """Return JSON array with context for each file:
[
  {"context": "test", "confidence": 0.95, "reasoning": "Contains pytest imports"},
  {"context": "production", "confidence": 0.8, "reasoning": "Main application logic"},
  ...
]"""

        return prompt

    def _parse_batch_response(
        self,
        response: LlmResponse,
        expected_count: int,
    ) -> List[LlmContextDecision]:
        """Parse batch LLM response."""
        try:
            if not response.content or not response.content.strip():
                raise ValueError("Empty response from LLM batch")

            json_str = self._extract_json(response.content)
            if not json_str:
                raise ValueError("No JSON found in batch response")

            data = json.loads(json_str)

            if isinstance(data, list):
                decisions = []
                for item in data[:expected_count]:
                    decisions.append(LlmContextDecision(
                        context=item.get("context", "unknown"),
                        confidence=float(item.get("confidence", 0.5)),
                        reasoning=item.get("reasoning", ""),
                    ))

                # Pad with defaults if needed
                while len(decisions) < expected_count:
                    decisions.append(LlmContextDecision(
                        context="unknown",
                        confidence=0.0,
                        reasoning="Missing from LLM response",
                    ))

                return decisions

        except Exception as e:
            logger.warning(
                "batch_llm_parse_failed_using_fallback",
                error=str(e),
                response_preview=response.content[:200] if response.content else "empty",
            )

        # Return defaults on error
        return [
            LlmContextDecision(
                context="unknown",
                confidence=0.0,
                reasoning="Parse error",
            )
            for _ in range(expected_count)
        ]

    def _get_cache_key(self, file_path: Path) -> str:
        """Generate cache key for file."""
        # Use file extension and parent directory as key
        parent = file_path.parent.name
        ext = file_path.suffix
        name_pattern = "test" if "test" in file_path.name.lower() else "regular"
        return f"{parent}:{ext}:{name_pattern}"