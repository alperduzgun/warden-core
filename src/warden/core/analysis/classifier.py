"""
Code classifier - frame recommendation system.

Analyzes code characteristics and recommends validation frames:
- hasAsync: Async/await patterns → recommend chaos frame
- hasUserInput: User input handling → recommend security, fuzz frames
- hasExternalCalls: API calls → recommend chaos frame
- hasDatabase: Database operations → recommend security frame
- hasFileIO: File operations → recommend security frame

This is a simplified version. Full implementation will include:
- LLM-based classification
- Machine learning model
- Language-specific patterns
"""
import ast
import time
import logging
from typing import Dict, Any, List

# Fallback logger (structlog not installed yet)
try:
    import structlog
    logger = structlog.get_logger()
except ImportError:
    from warden.shared.logger import get_logger
    logger = get_logger(__name__)


class CodeClassifier:
    """
    Code classifier with pattern-based frame recommendation.

    Current version: AST-based pattern detection for Python.
    Future: LLM integration for intelligent classification.
    """

    def __init__(self):
        """Initialize code classifier."""
        self.logger = logger

    async def classify(
        self,
        file_path: str,
        file_content: str,
        language: str = "python",
    ) -> Dict[str, Any]:
        """
        Classify code and recommend validation frames.

        Args:
            file_path: Path to file
            file_content: File content
            language: Programming language

        Returns:
            Classification result with characteristics and frame recommendations
        """
        start_time = time.perf_counter()

        self.logger.info(
            "classification_started",
            file_path=file_path,
            language=language,
        )

        try:
            # Classify based on language
            if language.lower() == "python":
                result = await self._classify_python(file_path, file_content)
            else:
                result = await self._classify_generic(file_path, file_content, language)

            duration_ms = (time.perf_counter() - start_time) * 1000

            self.logger.info(
                "classification_completed",
                file_path=file_path,
                recommended_frames=result["recommendedFrames"],
                duration_ms=duration_ms,
            )

            result["durationMs"] = duration_ms
            return result

        except Exception as ex:
            duration_ms = (time.perf_counter() - start_time) * 1000

            self.logger.error(
                "classification_failed",
                file_path=file_path,
                error=str(ex),
                error_type=type(ex).__name__,
                duration_ms=duration_ms,
            )

            # Default: recommend all frames
            return {
                "characteristics": {
                    "hasAsync": False,
                    "hasUserInput": False,
                    "hasExternalCalls": False,
                    "hasDatabase": False,
                    "hasFileIO": False,
                },
                "recommendedFrames": ["security", "fuzz", "property"],
                "error": str(ex),
                "durationMs": duration_ms,
            }

    async def _classify_python(
        self, file_path: str, file_content: str
    ) -> Dict[str, Any]:
        """Classify Python code using AST."""
        try:
            tree = ast.parse(file_content)

            # Detect characteristics
            characteristics = {
                "hasAsync": self._has_async(tree),
                "hasUserInput": self._has_user_input(tree, file_content),
                "hasExternalCalls": self._has_external_calls(tree),
                "hasDatabase": self._has_database(tree, file_content),
                "hasFileIO": self._has_file_io(tree),
                "hasNetworking": self._has_networking(tree, file_content),
                "hasCrypto": self._has_crypto(file_content),
            }

            # Recommend frames based on characteristics
            recommended_frames = self._recommend_frames(characteristics)

            return {
                "characteristics": characteristics,
                "recommendedFrames": recommended_frames,
                "language": "python",
            }

        except SyntaxError:
            # Syntax error: recommend security frame only
            return {
                "characteristics": {
                    "hasAsync": False,
                    "hasUserInput": False,
                    "hasExternalCalls": False,
                },
                "recommendedFrames": ["security"],
                "language": "python",
            }

    async def _classify_generic(
        self, file_path: str, file_content: str, language: str
    ) -> Dict[str, Any]:
        """Generic classification for non-Python languages."""
        # Simple keyword-based detection
        content_lower = file_content.lower()

        characteristics = {
            "hasAsync": "async" in content_lower or "await" in content_lower,
            "hasUserInput": "input" in content_lower or "request" in content_lower,
            "hasExternalCalls": "http" in content_lower or "api" in content_lower,
            "hasDatabase": "sql" in content_lower or "database" in content_lower,
            "hasFileIO": "file" in content_lower or "read" in content_lower,
        }

        recommended_frames = self._recommend_frames(characteristics)

        return {
            "characteristics": characteristics,
            "recommendedFrames": recommended_frames,
            "language": language,
        }

    def _has_async(self, tree: ast.AST) -> bool:
        """Check if code uses async/await."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.Await)):
                return True
        return False

    def _has_user_input(self, tree: ast.AST, content: str) -> bool:
        """Check if code handles user input."""
        # Check for input() calls
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == 'input':
                    return True

        # Check for common web frameworks
        keywords = ['request', 'form', 'query', 'body', 'params']
        content_lower = content.lower()
        return any(kw in content_lower for kw in keywords)

    def _has_external_calls(self, tree: ast.AST) -> bool:
        """Check if code makes external API calls."""
        http_libs = ['requests', 'httpx', 'urllib', 'aiohttp']

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(lib in alias.name for lib in http_libs):
                        return True
            elif isinstance(node, ast.ImportFrom):
                if node.module and any(lib in node.module for lib in http_libs):
                    return True

        return False

    def _has_database(self, tree: ast.AST, content: str) -> bool:
        """Check if code uses database operations."""
        db_libs = ['sqlalchemy', 'psycopg', 'pymongo', 'redis', 'mysql']

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(lib in alias.name.lower() for lib in db_libs):
                        return True
            elif isinstance(node, ast.ImportFrom):
                if node.module and any(lib in node.module.lower() for lib in db_libs):
                    return True

        # Check for SQL keywords
        sql_keywords = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE TABLE']
        content_upper = content.upper()
        return any(kw in content_upper for kw in sql_keywords)

    def _has_file_io(self, tree: ast.AST) -> bool:
        """Check if code performs file I/O."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == 'open':
                    return True
            elif isinstance(node, ast.With):
                # Check for 'with open(...)' pattern
                if any(
                    isinstance(item.context_expr, ast.Call)
                    and isinstance(item.context_expr.func, ast.Name)
                    and item.context_expr.func.id == 'open'
                    for item in node.items
                ):
                    return True

        return False

    def _has_networking(self, tree: ast.AST, content: str) -> bool:
        """Check if code uses networking."""
        net_libs = ['socket', 'asyncio', 'trio']

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(lib in alias.name for lib in net_libs):
                        return True

        return 'socket' in content.lower()

    def _has_crypto(self, content: str) -> bool:
        """Check if code uses cryptography."""
        crypto_keywords = ['hashlib', 'secrets', 'cryptography', 'pycrypto']
        content_lower = content.lower()
        return any(kw in content_lower for kw in crypto_keywords)

    def _recommend_frames(self, characteristics: Dict[str, bool]) -> List[str]:
        """
        Recommend validation frames based on characteristics.

        Priority-based recommendations:
        - Security: ALWAYS recommended (critical)
        - Chaos: If hasAsync or hasExternalCalls or hasNetworking
        - Fuzz: If hasUserInput
        - Property: ALWAYS recommended (idempotency checks)
        - Stress: If hasAsync or hasDatabase
        - Architectural: ALWAYS recommended (design patterns)
        """
        frames = []

        # Security (critical, always)
        frames.append("security")

        # Chaos (resilience)
        if (
            characteristics.get("hasAsync")
            or characteristics.get("hasExternalCalls")
            or characteristics.get("hasNetworking")
        ):
            frames.append("chaos")

        # Fuzz (edge cases)
        if characteristics.get("hasUserInput"):
            frames.append("fuzz")

        # Property (idempotency)
        frames.append("property")

        # Architectural (design patterns)
        frames.append("architectural")

        # Stress (performance)
        if characteristics.get("hasAsync") or characteristics.get("hasDatabase"):
            frames.append("stress")

        return frames
