"""
Code analyzer - hybrid AST + LLM analysis.

Analyzes code files and extracts:
- Code metrics (lines, complexity, etc.)
- Issues (bugs, code smells, security vulnerabilities)
- Quality score (0-10)

This is a simplified version. Full implementation will include:
- Python AST parsing
- Multi-language support
- LLM-based analysis
- False positive filtering
"""
import ast
import time
import logging
from typing import Dict, Any, List
from pathlib import Path

from warden.core.analysis.prompt_builder import build_enriched_prompt

# Fallback logger (structlog not installed yet)
try:
    import structlog
    logger = structlog.get_logger()
except ImportError:
    from warden.shared.logger import get_logger
    logger = get_logger(__name__)


class CodeAnalyzer:
    """
    Code analyzer with AST and basic metrics.

    Current version: Simple AST-based analysis for Python.
    Future: LLM integration for deeper analysis.
    """

    def __init__(self, llm_factory=None, use_llm: bool = True):
        """Initialize code analyzer.

        Args:
            llm_factory: Optional LLM factory for enhanced analysis
            use_llm: Enable LLM-enhanced analysis (default: True)
        """
        self.logger = logger
        self.llm_factory = llm_factory
        self.use_llm = use_llm and llm_factory is not None

    async def analyze(
        self,
        file_path: str,
        file_content: str,
        language: str = "python",
    ) -> Dict[str, Any]:
        """
        Hybrid code analysis: AST (fast, exact) + LLM (semantic, context-aware).

        Follows C# pattern:
        - Phase 1: AST Analysis (deterministic metrics)
        - Phase 2: LLM Analysis (semantic insights) - ALWAYS runs if enabled
        - Phase 3: Merge Results

        Args:
            file_path: Path to file
            file_content: File content
            language: Programming language

        Returns:
            Analysis result with score, issues, and metrics
        """
        start_time = time.perf_counter()

        self.logger.info(
            "analysis_started",
            file_path=file_path,
            language=language,
            content_length=len(file_content),
            llm_enabled=self.use_llm,
        )

        try:
            # Phase 1: AST Analysis (fast, exact metrics)
            ast_result = None
            if language.lower() == "python":
                ast_result = await self._analyze_python(file_path, file_content)
            else:
                ast_result = await self._analyze_generic(file_path, file_content, language)

            # Phase 2: LLM Analysis (semantic insights) - C# pattern: ALWAYS run
            if self.use_llm:
                # Extract AST metrics to enrich prompt
                ast_metrics = ast_result.get("metrics") if ast_result else None

                result = await self.analyze_with_llm(
                    file_path,
                    file_content,
                    language,
                    ast_metrics=ast_metrics  # Enrich prompt with AST metrics
                )

                # Merge AST metrics if available
                if ast_result and "metrics" in ast_result:
                    result["metrics"] = ast_result["metrics"]
                    result["ast_analysis_success"] = True
            else:
                # Fallback: Use AST-only result
                result = ast_result

            duration_ms = (time.perf_counter() - start_time) * 1000

            self.logger.info(
                "analysis_completed",
                file_path=file_path,
                score=result.get("score", 0),
                issue_count=len(result.get("issues", [])),
                duration_ms=duration_ms,
                llm_used=self.use_llm,
            )

            result["durationMs"] = duration_ms
            return result

        except Exception as ex:
            duration_ms = (time.perf_counter() - start_time) * 1000

            self.logger.error(
                "analysis_failed",
                file_path=file_path,
                error=str(ex),
                error_type=type(ex).__name__,
                duration_ms=duration_ms,
            )

            return {
                "score": 5.0,
                "issues": [],
                "metrics": {},
                "error": str(ex),
                "durationMs": duration_ms,
            }

    async def _analyze_python(
        self, file_path: str, file_content: str
    ) -> Dict[str, Any]:
        """Analyze Python code using AST."""
        issues = []
        metrics = {}

        try:
            # Parse AST
            tree = ast.parse(file_content)

            # Extract metrics
            metrics = self._extract_python_metrics(tree, file_content)

            # Basic issue detection
            issues = self._detect_python_issues(tree, file_content)

            # Calculate score (simple heuristic)
            score = self._calculate_score(metrics, issues)

            return {
                "score": score,
                "issues": issues,
                "metrics": metrics,
                "language": "python",
            }

        except SyntaxError as e:
            return {
                "score": 0.0,
                "issues": [
                    {
                        "type": "syntax_error",
                        "message": f"Syntax error: {str(e)}",
                        "line": e.lineno if hasattr(e, 'lineno') else 0,
                    }
                ],
                "metrics": {},
                "language": "python",
            }

    async def _analyze_generic(
        self, file_path: str, file_content: str, language: str
    ) -> Dict[str, Any]:
        """Generic analysis for non-Python languages."""
        lines = file_content.split('\n')
        metrics = {
            "lines": len(lines),
            "nonBlankLines": len([l for l in lines if l.strip()]),
            "commentLines": len([l for l in lines if l.strip().startswith('#')]),
        }

        # Default score
        score = 7.0

        return {
            "score": score,
            "issues": [],
            "metrics": metrics,
            "language": language,
        }

    def _extract_python_metrics(self, tree: ast.AST, content: str) -> Dict[str, Any]:
        """Extract Python code metrics from AST."""
        lines = content.split('\n')

        # Count nodes
        function_count = sum(1 for _ in ast.walk(tree) if isinstance(_, ast.FunctionDef))
        class_count = sum(1 for _ in ast.walk(tree) if isinstance(_, ast.ClassDef))
        import_count = sum(
            1 for _ in ast.walk(tree) if isinstance(_, (ast.Import, ast.ImportFrom))
        )

        # Count async
        async_function_count = sum(
            1 for _ in ast.walk(tree) if isinstance(_, ast.AsyncFunctionDef)
        )

        # Count complexity indicators
        if_count = sum(1 for _ in ast.walk(tree) if isinstance(_, ast.If))
        loop_count = sum(
            1 for _ in ast.walk(tree) if isinstance(_, (ast.For, ast.While))
        )
        try_count = sum(1 for _ in ast.walk(tree) if isinstance(_, ast.Try))

        # Basic metrics
        metrics = {
            "lines": len(lines),
            "nonBlankLines": len([l for l in lines if l.strip()]),
            "commentLines": len([l for l in lines if l.strip().startswith('#')]),
            "functions": function_count,
            "classes": class_count,
            "imports": import_count,
            "asyncFunctions": async_function_count,
            "conditionals": if_count,
            "loops": loop_count,
            "errorHandling": try_count,
        }

        return metrics

    def _detect_python_issues(
        self, tree: ast.AST, content: str
    ) -> List[Dict[str, Any]]:
        """Detect basic Python issues."""
        issues = []

        # Check for bare except
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    issues.append({
                        "type": "bare_except",
                        "message": "Bare except clause - catches all exceptions",
                        "line": node.lineno,
                        "severity": "medium",
                    })

        # Check for print statements (code smell in production)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == 'print':
                    issues.append({
                        "type": "print_statement",
                        "message": "print() statement found - use logging instead",
                        "line": node.lineno,
                        "severity": "low",
                    })

        # Check for TODO comments
        for idx, line in enumerate(content.split('\n'), 1):
            if 'TODO' in line or 'FIXME' in line:
                issues.append({
                    "type": "todo_comment",
                    "message": "TODO/FIXME comment found",
                    "line": idx,
                    "severity": "low",
                })

        return issues

    def _calculate_score(
        self, metrics: Dict[str, Any], issues: List[Dict[str, Any]]
    ) -> float:
        """
        Calculate quality score (0-10).

        Simple heuristic:
        - Start with 8.0
        - Deduct for issues
        - Bonus for good practices
        """
        score = 8.0

        # Deduct for issues
        for issue in issues:
            severity = issue.get("severity", "low")
            if severity == "critical":
                score -= 2.0
            elif severity == "high":
                score -= 1.0
            elif severity == "medium":
                score -= 0.5
            elif severity == "low":
                score -= 0.2

        # Bonus for error handling
        if metrics.get("errorHandling", 0) > 0:
            score += 0.5

        # Bonus for docstrings (future: detect with AST)
        # For now, skip

        # Clamp to 0-10
        score = max(0.0, min(10.0, score))

        return round(score, 1)

    async def analyze_with_llm(
        self,
        file_path: str,
        file_content: str,
        language: str = "python",
        ast_metrics: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Enhanced analysis using LLM with enriched prompts (C# pattern).

        Enriches prompt with AST metrics for better analysis:
        - File header (path, language)
        - AST metrics (LOC, complexity, functions, classes)
        - Source code
        - Analysis instructions

        Args:
            file_path: Path to file
            file_content: File content
            language: Programming language
            ast_metrics: Optional AST metrics to enrich prompt

        Returns:
            Analysis result with LLM insights
        """
        if not self.llm_factory:
            self.logger.warning("llm_factory_not_configured", file_path=file_path)
            # Return basic AST analysis
            if language.lower() == "python":
                return await self._analyze_python(file_path, file_content)
            else:
                return await self._analyze_generic(file_path, file_content, language)

        start_time = time.perf_counter()

        try:
            # Import LLM types
            from warden.llm import (
                LlmRequest,
                AnalysisResult,
                ANALYSIS_SYSTEM_PROMPT
            )

            # Get LLM client with fallback
            client = await self.llm_factory.create_client_with_fallback()

            # Build enriched prompt with AST metrics (C# pattern)
            user_message = build_enriched_prompt(
                file_path,
                file_content,
                language,
                ast_metrics
            )

            # Create LLM request
            request = LlmRequest(
                system_prompt=ANALYSIS_SYSTEM_PROMPT,
                user_message=user_message,
                temperature=0.3,
                max_tokens=4000,
                timeout_seconds=60
            )

            # Send to LLM
            response = await client.send_async(request)

            if not response.success:
                self.logger.warning(
                    "llm_analysis_failed",
                    file_path=file_path,
                    error=response.error_message,
                    provider=response.provider.value if response.provider else None
                )
                # Fallback to AST analysis
                return await self.analyze(file_path, file_content, language)

            # Parse LLM response
            import json
            llm_data = json.loads(response.content)
            result = AnalysisResult.from_dict(llm_data)

            duration_ms = (time.perf_counter() - start_time) * 1000

            self.logger.info(
                "llm_analysis_completed",
                file_path=file_path,
                score=result.score,
                confidence=result.confidence,
                issue_count=len(result.issues),
                provider=response.provider.value if response.provider else None,
                duration_ms=duration_ms
            )

            # Convert to standard format
            return {
                "score": result.score,
                "confidence": result.confidence,
                "summary": result.summary,
                "issues": [issue.to_dict() for issue in result.issues],
                "provider": response.provider.value if response.provider else None,
                "durationMs": duration_ms,
                "tokensUsed": response.total_tokens
            }

        except Exception as ex:
            self.logger.error(
                "llm_analysis_error",
                file_path=file_path,
                error=str(ex),
                error_type=type(ex).__name__
            )
            # Fallback to AST analysis
            if language.lower() == "python":
                return await self._analyze_python(file_path, file_content)
            else:
                return await self._analyze_generic(file_path, file_content, language)
