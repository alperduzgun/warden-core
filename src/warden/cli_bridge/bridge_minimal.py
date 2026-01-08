"""
Minimal Warden Bridge - Standalone IPC Service for Testing

Provides a minimal bridge implementation with NO Warden dependencies.
Used for CLI testing and development without full Warden installation.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from pathlib import Path

from warden.cli_bridge.protocol import IPCError, ErrorCode


class MinimalWardenBridge:
    """
    Minimal bridge service with mocked responses for testing

    Implements the same interface as WardenBridge but with no dependencies.
    All methods return realistic mock data for CLI testing.
    """

    def __init__(self) -> None:
        """Initialize minimal bridge service"""
        self._mock_frames = [
            {
                "id": "security-001",
                "name": "SQL Injection Check",
                "description": "Detects potential SQL injection vulnerabilities",
                "priority": "HIGH",
                "is_blocker": True,
                "tags": ["security", "database"],
            },
            {
                "id": "quality-001",
                "name": "Code Complexity",
                "description": "Analyzes code complexity metrics",
                "priority": "MEDIUM",
                "is_blocker": False,
                "tags": ["quality", "metrics"],
            },
            {
                "id": "style-001",
                "name": "Naming Conventions",
                "description": "Checks naming conventions compliance",
                "priority": "LOW",
                "is_blocker": False,
                "tags": ["style", "conventions"],
            },
        ]

    async def execute_pipeline(self, file_path: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Mock pipeline execution

        Args:
            file_path: Path to file to validate
            config: Optional pipeline configuration

        Returns:
            Mock pipeline results

        Raises:
            IPCError: If file doesn't exist
        """
        # Validate file exists
        path = Path(file_path)
        if not path.exists():
            raise IPCError(
                code=ErrorCode.FILE_NOT_FOUND,
                message=f"File not found: {file_path}",
                data={"file_path": file_path},
            )

        # Return realistic mock results
        return {
            "pipeline_id": "mock-pipeline-001",
            "pipeline_name": "Minimal Validation Pipeline",
            "status": "completed",
            "duration": 1.234,
            "total_frames": 3,
            "frames_passed": 2,
            "frames_failed": 1,
            "frames_skipped": 0,
            "total_findings": 2,
            "critical_findings": 0,
            "high_findings": 1,
            "medium_findings": 1,
            "low_findings": 0,
            "frame_results": [
                {
                    "frame_id": "security-001",
                    "frame_name": "SQL Injection Check",
                    "status": "passed",
                    "duration": 0.456,
                    "issues_found": 0,
                    "is_blocker": True,
                    "findings": [],
                },
                {
                    "frame_id": "quality-001",
                    "frame_name": "Code Complexity",
                    "status": "failed",
                    "duration": 0.321,
                    "issues_found": 1,
                    "is_blocker": False,
                    "findings": [
                        {
                            "severity": "HIGH",
                            "message": "Function complexity exceeds threshold (15 > 10)",
                            "line": 42,
                            "column": 5,
                            "code": "complex_function",
                        }
                    ],
                },
                {
                    "frame_id": "style-001",
                    "frame_name": "Naming Conventions",
                    "status": "passed_with_warnings",
                    "duration": 0.457,
                    "issues_found": 1,
                    "is_blocker": False,
                    "findings": [
                        {
                            "severity": "MEDIUM",
                            "message": "Variable name should use snake_case",
                            "line": 23,
                            "column": 8,
                            "code": "myVariable",
                        }
                    ],
                },
            ],
            "metadata": {
                "file_path": str(path.absolute()),
                "language": self._detect_language(path),
                "file_size": path.stat().st_size if path.exists() else 0,
                "timestamp": datetime.utcnow().isoformat(),
                "mock_mode": True,
            },
        }

    async def get_config(self) -> Dict[str, Any]:
        """
        Get mock Warden configuration

        Returns:
            Mock configuration data
        """
        return {
            "version": "0.1.0",
            "llm_providers": [
                {
                    "name": "openai",
                    "model": "gpt-4",
                    "endpoint": "default",
                    "enabled": True,
                },
                {
                    "name": "anthropic",
                    "model": "claude-3-opus",
                    "endpoint": "default",
                    "enabled": True,
                },
            ],
            "default_provider": "openai",
            "frames": self._mock_frames,
            "total_frames": len(self._mock_frames),
            "mock_mode": True,
        }

    async def ping(self) -> Dict[str, str]:
        """
        Health check endpoint

        Returns:
            Pong response with timestamp
        """
        return {
            "status": "ok",
            "message": "pong",
            "timestamp": datetime.utcnow().isoformat(),
            "mode": "minimal",
        }

    async def get_available_frames(self) -> List[Dict[str, Any]]:
        """
        Get list of mock validation frames

        Returns:
            List of mock frame information
        """
        return self._mock_frames.copy()

    def _detect_language(self, path: Path) -> str:
        """
        Detect programming language from file extension

        Args:
            path: File path

        Returns:
            Language identifier
        """
        from warden.shared.utils.language_utils import get_language_from_path
        return get_language_from_path(path).value


# Convenience function for quick testing
async def create_minimal_bridge() -> MinimalWardenBridge:
    """
    Create a minimal bridge instance for testing

    Returns:
        MinimalWardenBridge instance
    """
    return MinimalWardenBridge()
