"""
Tests for PipelineOrchestrator.

Validates sequential, parallel, and fail-fast execution strategies.
"""

import pytest
from warden.pipeline import (
    PipelineOrchestrator,
    PipelineConfig,
    ExecutionStrategy,
    PipelineStatus,
)
from warden.validation.frames import SecurityFrame, ResilienceFrame
from warden.validation.domain.frame import CodeFile


# --- Realistic code snippets (>300 chars AND >30 lines to pass triage heuristic) ---

_HARDCODED_PASSWORD = '''\
import os
import sys
import logging
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


class UserAuthService:
    """Handles user authentication and session management.

    This service manages user login, token generation, and session
    lifecycle operations for the application.
    """

    def __init__(self, db_connection):
        self.db = db_connection
        self.password = "admin123"
        self.session_timeout = 3600
        self.max_retries = 3

    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate a user against the database."""
        logger.info("Authenticating user: %s", username)
        user = self.db.find_user(username)
        if user and user.verify(password):
            logger.info("Authentication successful for: %s", username)
            return True
        logger.warning("Authentication failed for: %s", username)
        return False

    def create_session(self, user_id: str) -> Optional[str]:
        """Create a new session for the authenticated user."""
        session = self.db.create_session(user_id, timeout=self.session_timeout)
        if session:
            return session.token
        return None
'''

_OPENAI_KEY_LEAK = '''\
import os
import json
import logging
from typing import Any, Optional
from pathlib import Path


logger = logging.getLogger(__name__)

OPENAI_API_KEY = "sk-1234567890abcdefghijklmnopqrstuvwxyz123456789012"


class LLMClient:
    """Client for making LLM API calls.

    Provides methods for text completion, embedding generation,
    and model management operations.
    """

    def __init__(self, model: str = "gpt-4"):
        self.model = model
        self.api_key = OPENAI_API_KEY
        self.timeout = 60

    def complete(self, prompt: str) -> dict[str, Any]:
        """Send a completion request to the LLM API."""
        logger.info("Sending completion request to model: %s", self.model)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        return {"model": self.model, "prompt": prompt, "headers": headers}

    def get_embedding(self, text: str) -> Optional[list[float]]:
        """Generate text embeddings using the API."""
        logger.info("Generating embedding for text of length: %d", len(text))
        if not text.strip():
            return None
        return [0.0] * 1536

    def list_models(self) -> list[str]:
        """List available models from the API."""
        return ["gpt-4", "gpt-3.5-turbo", "text-embedding-ada-002"]
'''

_SQL_INJECTION = '''\
import sqlite3
import logging
from typing import Optional, Any
from pathlib import Path


logger = logging.getLogger(__name__)


class UserRepository:
    """Repository for user data access.

    Provides CRUD operations for user records in the SQLite database.
    Handles connection management and query execution.
    """

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.db_path = db_path
        logger.info("Connected to database: %s", db_path)

    def find_user(self, user_id: str) -> Optional[dict]:
        """Find a user by ID. WARNING: SQL injection vulnerability."""
        query = f"SELECT * FROM users WHERE id = {user_id}"
        cursor = self.conn.execute(query)
        row = cursor.fetchone()
        if row:
            return {"id": row[0], "name": row[1], "email": row[2]}
        return None

    def list_users(self, limit: int = 100) -> list[dict]:
        """List all users with optional limit."""
        cursor = self.conn.execute("SELECT * FROM users LIMIT ?", (limit,))
        return [{"id": r[0], "name": r[1]} for r in cursor.fetchall()]

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()
        logger.info("Database connection closed")
'''

_CLEAN_CODE = '''\
import math
import logging
from typing import Union


logger = logging.getLogger(__name__)

Number = Union[int, float]


class Calculator:
    """A simple calculator with basic arithmetic operations.

    Provides addition, multiplication, division, and square root
    functionality with proper error handling and input validation.
    """

    def add(self, a: Number, b: Number) -> Number:
        """Add two numbers together."""
        result = a + b
        logger.debug("add(%s, %s) = %s", a, b, result)
        return result

    def multiply(self, a: Number, b: Number) -> Number:
        """Multiply two numbers together."""
        result = a * b
        logger.debug("multiply(%s, %s) = %s", a, b, result)
        return result

    def divide(self, a: Number, b: Number) -> float:
        """Divide a by b, raising ValueError on zero division."""
        if b == 0:
            raise ValueError("Cannot divide by zero")
        result = a / b
        logger.debug("divide(%s, %s) = %s", a, b, result)
        return result

    def sqrt(self, n: Number) -> float:
        """Return the square root of a non-negative number."""
        if n < 0:
            raise ValueError("Cannot take square root of negative number")
        result = math.sqrt(n)
        logger.debug("sqrt(%s) = %s", n, result)
        return result
'''

_MULTI_ISSUE = '''\
import os
import requests
import logging
from typing import Optional, Any
from pathlib import Path


logger = logging.getLogger(__name__)


class ConfigManager:
    """Application configuration management.

    Manages application settings, remote configuration fetching,
    and database connection string construction.
    """

    password = "admin123"
    secret_key = "supersecret"

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.api_token = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        logger.info("ConfigManager initialized with path: %s", config_path)

    def fetch_remote_config(self, url: str) -> Optional[dict]:
        """Fetch configuration from a remote server."""
        query = f"SELECT * FROM configs WHERE name = {self.config_path}"
        response = requests.get(url)
        if response.ok:
            return response.json()
        logger.error("Failed to fetch config from: %s", url)
        return None

    def get_database_url(self) -> str:
        """Build database connection URL."""
        return f"postgresql://admin:{self.password}@localhost:5432/mydb"

    def save_config(self, data: dict[str, Any]) -> bool:
        """Save configuration data to a file."""
        try:
            Path(self.config_path).write_text(str(data))
            return True
        except OSError as exc:
            logger.error("Failed to save config: %s", exc)
            return False
'''

_API_KEY_SHORT = '''\
import os
import json
import logging
from pathlib import Path
from typing import Any, Optional


logger = logging.getLogger(__name__)


class ServiceConfig:
    """Service configuration with hardcoded API key.

    Manages API configuration, request headers, and
    configuration file loading for the service layer.
    """

    def __init__(self):
        self.api_key = "sk-123456789abcdefghijk"
        self.base_url = "https://api.example.com/v1"
        self.timeout = 30
        logger.info("ServiceConfig initialized")

    def get_headers(self) -> dict[str, str]:
        """Build request headers with authentication."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def load_config(self, path: str) -> dict[str, Any]:
        """Load configuration from a JSON file."""
        config_file = Path(path)
        if not config_file.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        return json.loads(config_file.read_text())

    def validate(self) -> bool:
        """Validate the configuration settings."""
        if not self.api_key:
            logger.error("API key is not set")
            return False
        if not self.base_url:
            logger.error("Base URL is not set")
            return False
        return True
'''

_REQUESTS_NO_TIMEOUT = '''\
import requests
import logging
from typing import Optional, Any
from pathlib import Path


logger = logging.getLogger(__name__)


class ExternalAPIClient:
    """Client for external API integration.

    Provides methods for fetching resources, posting data,
    and managing API sessions for external service communication.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = requests.Session()
        logger.info("ExternalAPIClient initialized with: %s", base_url)

    def get_resource(self, resource_id: str) -> Optional[dict]:
        """Fetch a resource from the external API."""
        url = f"{self.base_url}/resources/{resource_id}"
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        logger.warning("Resource not found: %s", resource_id)
        return None

    def post_data(self, endpoint: str, data: dict[str, Any]) -> dict:
        """Post data to the external API."""
        url = f"{self.base_url}/{endpoint}"
        response = self.session.post(url, json=data)
        response.raise_for_status()
        return response.json()

    def health_check(self) -> bool:
        """Check if the external API is available."""
        try:
            resp = requests.get(f"{self.base_url}/health")
            return resp.status_code == 200
        except requests.ConnectionError:
            logger.error("Health check failed for: %s", self.base_url)
            return False
'''


@pytest.mark.asyncio
async def test_orchestrator_sequential_execution():
    """Test sequential execution of frames."""
    frames = [SecurityFrame(), ResilienceFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="auth_service.py",
        content=_HARDCODED_PASSWORD,
        language="python",
    )

    result, _ = await orchestrator.execute_async([code_file], frames_to_execute=["security", "resilience"])

    # Both frames should execute
    assert result.total_frames == 2
    assert result.frames_passed + result.frames_failed == 2
    assert result.status == PipelineStatus.FAILED  # Security blocker failed


@pytest.mark.asyncio
async def test_orchestrator_parallel_execution():
    """Test parallel execution of frames."""
    frames = [SecurityFrame(), ResilienceFrame()]
    config = PipelineConfig(
        strategy=ExecutionStrategy.PARALLEL,
        parallel_limit=2,
        fail_fast=False,
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="llm_client.py",
        content=_OPENAI_KEY_LEAK,
        language="python",
    )

    result, _ = await orchestrator.execute_async([code_file], frames_to_execute=["security", "resilience"])

    # Both frames should execute in parallel
    assert result.total_frames == 2
    assert result.total_findings > 0


@pytest.mark.asyncio
async def test_orchestrator_fail_fast():
    """Test fail-fast execution stops on blocker failure."""
    frames = [SecurityFrame(), ResilienceFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.FAIL_FAST)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="user_repository.py",
        content=_SQL_INJECTION,
        language="python",
    )

    result, _ = await orchestrator.execute_async([code_file], frames_to_execute=["security", "resilience"])

    # Should stop after SecurityFrame fails (it's a blocker)
    assert result.status == PipelineStatus.FAILED
    assert result.frames_failed >= 1
    # ResilienceFrame may be skipped if SecurityFrame is blocker and failed
    assert result.frames_skipped >= 0


@pytest.mark.asyncio
async def test_orchestrator_passes_clean_code():
    """Test orchestrator passes clean code."""
    frames = [SecurityFrame(), ResilienceFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="calculator.py",
        content=_CLEAN_CODE,
        language="python",
    )

    result, _ = await orchestrator.execute_async([code_file], frames_to_execute=["security", "resilience"])

    # Should pass all frames (low-severity findings from resilience are acceptable)
    assert result.status == PipelineStatus.COMPLETED
    assert result.passed is True
    assert result.critical_findings == 0
    assert result.high_findings == 0


@pytest.mark.asyncio
async def test_orchestrator_frame_priority_sorting():
    """Test frames are sorted by priority."""
    # ResilienceFrame has priority HIGH, SecurityFrame has CRITICAL
    frames = [ResilienceFrame(), SecurityFrame()]  # Wrong order
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    # After initialization, frames should be sorted by priority (lower value = higher priority)
    assert orchestrator.frames[0].priority.value == 1  # CRITICAL (Security)
    assert orchestrator.frames[1].priority.value == 2  # HIGH (Chaos)


@pytest.mark.asyncio
async def test_orchestrator_multiple_files():
    """Test orchestrator handles multiple files."""
    frames = [SecurityFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_files = [
        CodeFile(path="auth_service.py", content=_HARDCODED_PASSWORD, language="python"),
        CodeFile(path="llm_client.py", content=_OPENAI_KEY_LEAK, language="python"),
        CodeFile(path="calculator.py", content=_CLEAN_CODE, language="python"),
    ]

    result, _ = await orchestrator.execute_async(code_files)

    # Should process all 3 files
    assert result.total_findings >= 2  # At least 2 issues from file1 and file2


@pytest.mark.asyncio
async def test_orchestrator_result_structure():
    """Test pipeline result has correct Panel JSON structure."""
    frames = [SecurityFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="auth_service.py",
        content=_HARDCODED_PASSWORD,
        language="python",
    )

    result, _ = await orchestrator.execute_async([code_file])

    # Test Panel JSON compatibility
    json_data = result.to_json()

    # Check camelCase fields
    assert "pipelineId" in json_data
    assert "pipelineName" in json_data
    assert "status" in json_data
    assert "duration" in json_data
    assert "totalFrames" in json_data
    assert "framesPassed" in json_data
    assert "framesFailed" in json_data
    assert "totalFindings" in json_data
    assert "frameResults" in json_data

    # Status should be integer
    assert isinstance(json_data["status"], int)


@pytest.mark.asyncio
async def test_orchestrator_severity_counts():
    """Test orchestrator correctly counts findings by severity."""
    frames = [SecurityFrame(), ResilienceFrame()]
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="app_manager.py",
        content=_MULTI_ISSUE,
        language="python",
    )

    result, _ = await orchestrator.execute_async([code_file], frames_to_execute=["security", "resilience"])

    # Should have findings across multiple severity levels
    assert result.total_findings > 0
    assert result.critical_findings > 0 or result.high_findings > 0


@pytest.mark.asyncio
async def test_orchestrator_metadata():
    """Test pipeline result includes execution metadata."""
    frames = [SecurityFrame()]
    config = PipelineConfig(
        strategy=ExecutionStrategy.SEQUENTIAL,
        fail_fast=True,
    )

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="service_client.py",
        content=_API_KEY_SHORT,
        language="python",
    )

    result, _ = await orchestrator.execute_async([code_file])

    # Check metadata
    assert "strategy" in result.metadata
    assert result.metadata["strategy"] == "sequential"
    assert "fail_fast" in result.metadata
    assert result.metadata["fail_fast"] is True
    assert "frame_executions" in result.metadata


@pytest.mark.asyncio
async def test_orchestrator_has_blockers_property():
    """Test has_blockers property works correctly."""
    frames = [SecurityFrame()]  # Blocker frame
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="auth_service.py",
        content=_HARDCODED_PASSWORD,
        language="python",
    )

    result, _ = await orchestrator.execute_async([code_file])

    # Should have blocker issues
    assert result.has_blockers is True


@pytest.mark.asyncio
async def test_orchestrator_no_blockers():
    """Test has_blockers is False when only warnings."""
    frames = [ResilienceFrame()]  # Non-blocker frame
    config = PipelineConfig(strategy=ExecutionStrategy.SEQUENTIAL, fail_fast=False)

    orchestrator = PipelineOrchestrator(frames=frames, config=config)

    code_file = CodeFile(
        path="external_api_client.py",
        content=_REQUESTS_NO_TIMEOUT,
        language="python",
    )

    result, _ = await orchestrator.execute_async([code_file])

    # Should not have blocker issues (ResilienceFrame is not a blocker)
    assert result.has_blockers is False
