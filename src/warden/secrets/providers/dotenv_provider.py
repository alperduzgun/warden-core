"""DotEnv file secret provider."""

from datetime import datetime
from pathlib import Path

import structlog

from ..domain.enums import SecretSource
from ..domain.models import SecretValue
from .base import ISecretProvider

logger = structlog.get_logger(__name__)


class DotEnvSecretProvider(ISecretProvider):
    """Reads secrets from .env file.

    Does NOT load into os.environ - reads directly from file.
    This allows isolation from the environment and explicit control.

    Features:
    - Parses .env file format
    - Handles quoted values
    - Searches parent directories
    - Supports comments

    Example:
        provider = DotEnvSecretProvider()
        result = await provider.get_secret("AZURE_OPENAI_API_KEY")
        if result.found:
            print(f"API Key from .env: {result.value}")
    """

    def __init__(
        self,
        env_path: Path | None = None,
        priority: int = 2,
        search_parents: bool = True,
    ):
        """Initialize the provider.

        Args:
            env_path: Explicit path to .env file. If None, searches current dir.
            priority: Provider priority (lower = tried first).
            search_parents: Whether to search parent directories for .env.
        """
        self._priority = priority
        self._search_parents = search_parents
        self._env_path = env_path
        self._values: dict[str, str] = {}
        self._loaded = False
        self._found_path: Path | None = None

    @property
    def source(self) -> SecretSource:
        """Return DOTENV as the source."""
        return SecretSource.DOTENV

    @property
    def priority(self) -> int:
        """Return the configured priority."""
        return self._priority

    def _find_env_file(self) -> Path | None:
        """Find .env file, searching parent directories if enabled.

        Returns:
            Path to .env file if found, None otherwise.
        """
        if self._env_path and self._env_path.exists():
            return self._env_path

        current = Path.cwd()
        for _ in range(5):  # Match existing pattern in load_llm_config
            env_file = current / ".env"
            if env_file.exists():
                return env_file
            if not self._search_parents:
                break
            parent = current.parent
            if parent == current:  # Reached root
                break
            current = parent
        return None

    def _load_env_file(self) -> None:
        """Parse .env file into dictionary.

        Format supported:
        - KEY=value
        - KEY="quoted value"
        - KEY='quoted value'
        - # comments
        - Empty lines
        """
        if self._loaded:
            return

        env_file = self._find_env_file()
        if not env_file:
            self._loaded = True
            return

        self._found_path = env_file

        try:
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        # Remove surrounding quotes
                        if (value.startswith('"') and value.endswith('"')) or (
                            value.startswith("'") and value.endswith("'")
                        ):
                            value = value[1:-1]
                        self._values[key] = value

            logger.debug(
                "dotenv_loaded",
                path=str(env_file),
                key_count=len(self._values),
            )
        except Exception as e:
            logger.warning(
                "dotenv_load_failed",
                path=str(env_file),
                error=str(e),
            )

        self._loaded = True

    async def get_secret(self, key: str) -> SecretValue:
        """Get a secret from .env file.

        Args:
            key: Secret key to look up.

        Returns:
            SecretValue with value if found, NOT_FOUND otherwise.
        """
        self._load_env_file()
        value = self._values.get(key)
        return SecretValue(
            key=key,
            value=value,
            source=SecretSource.DOTENV if value else SecretSource.NOT_FOUND,
            retrieved_at=datetime.now(),
        )

    async def is_available(self) -> bool:
        """Check if .env file exists.

        Returns:
            True if .env file was found.
        """
        return self._find_env_file() is not None

    def reload(self) -> None:
        """Force reload of .env file.

        Call this if .env file has been modified.
        """
        self._loaded = False
        self._values.clear()
        self._found_path = None
