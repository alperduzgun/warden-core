"""
AST Provider Loader.

Auto-discovers and loads AST providers from multiple sources:
1. Built-in providers (tree-sitter, Python native)
2. PyPI entry points (warden.ast_providers)
3. Local plugin directory (~/.warden/ast-providers/)
4. Environment variables (WARDEN_AST_PROVIDERS)
"""

import os
import sys
from pathlib import Path
from typing import List, Optional, Type
import importlib
import importlib.util
import structlog

from warden.ast.application.provider_interface import IASTProvider
from warden.ast.application.provider_registry import ASTProviderRegistry

logger = structlog.get_logger(__name__)


class ASTProviderLoader:
    """
    Auto-discovery and loading of AST providers.

    Discovery order:
        1. Built-in providers (always available)
        2. PyPI entry points (installed via pip)
        3. Local plugin directory (~/.warden/ast-providers/)
        4. Environment variable paths (WARDEN_AST_PROVIDERS)

    Example PyPI package (warden-ast-provider-kotlin):
        setup.py:
            entry_points={
                'warden.ast_providers': [
                    'kotlin = warden_ast_kotlin:KotlinASTProvider'
                ]
            }

    Example local plugin (~/.warden/ast-providers/my_provider.py):
        from warden.ast.application.provider_interface import IASTProvider

        class MyProvider(IASTProvider):
            ...
    """

    def __init__(self, registry: ASTProviderRegistry) -> None:
        """
        Initialize loader with registry.

        Args:
            registry: Provider registry to load providers into
        """
        self._registry = registry
        self._loaded_providers: List[str] = []

    async def load_all(self) -> None:
        """
        Load providers from all sources.

        Discovery order:
            1. Built-in providers
            2. PyPI entry points
            3. Local plugin directory
            4. Environment variables
        """
        logger.info("ast_provider_discovery_started")

        # 1. Built-in providers
        await self._load_builtin_providers()

        # 2. PyPI entry points
        await self._load_entry_point_providers()

        # 3. Local plugin directory
        await self._load_local_plugins()

        # 4. Environment variables
        await self._load_env_providers()

        logger.info(
            "ast_provider_discovery_completed",
            total_providers=len(self._registry),
            loaded_providers=self._loaded_providers,
        )

    async def _load_builtin_providers(self) -> None:
        """Load built-in providers (tree-sitter, Python native)."""
        logger.debug("loading_builtin_providers")

        builtin_providers = [
            ("warden.ast.providers.tree_sitter_provider", "TreeSitterProvider"),
            ("warden.ast.providers.python_ast_provider", "PythonASTProvider"),
        ]

        for module_name, class_name in builtin_providers:
            try:
                provider = await self._load_provider_from_module(module_name, class_name)
                if provider:
                    self._registry.register(provider)
                    self._loaded_providers.append(f"{module_name}.{class_name}")
                    logger.debug(
                        "builtin_provider_loaded",
                        provider_name=provider.metadata.name,
                    )
            except Exception as e:
                logger.warning(
                    "builtin_provider_load_failed",
                    module=module_name,
                    class_name=class_name,
                    error=str(e),
                )

    async def _load_entry_point_providers(self) -> None:
        """Load providers from PyPI entry points."""
        logger.debug("loading_entry_point_providers")

        try:
            # Python 3.10+ has importlib.metadata
            if sys.version_info >= (3, 10):
                from importlib.metadata import entry_points

                eps = entry_points()
                if hasattr(eps, "select"):
                    # Python 3.10+
                    warden_eps = eps.select(group="warden.ast_providers")
                else:
                    # Python 3.9
                    warden_eps = eps.get("warden.ast_providers", [])
            else:
                # Fallback for older Python versions
                logger.warning("entry_points_not_supported", python_version=sys.version)
                return

            for ep in warden_eps:
                try:
                    provider_class = ep.load()
                    provider = provider_class()

                    # Validate provider
                    if not isinstance(provider, IASTProvider):
                        logger.warning(
                            "invalid_entry_point_provider",
                            entry_point=ep.name,
                            reason="not IASTProvider instance",
                        )
                        continue

                    self._registry.register(provider)
                    self._loaded_providers.append(f"entry_point:{ep.name}")
                    logger.info(
                        "entry_point_provider_loaded",
                        provider_name=provider.metadata.name,
                        entry_point=ep.name,
                    )

                except Exception as e:
                    logger.warning(
                        "entry_point_provider_load_failed",
                        entry_point=ep.name,
                        error=str(e),
                    )

        except Exception as e:
            logger.warning("entry_point_discovery_failed", error=str(e))

    async def _load_local_plugins(self) -> None:
        """Load providers from local plugin directory."""
        logger.debug("loading_local_plugins")

        plugin_dir = Path.home() / ".warden" / "ast-providers"

        if not plugin_dir.exists():
            logger.debug("local_plugin_dir_not_found", path=str(plugin_dir))
            return

        # Find all .py files in plugin directory
        plugin_files = list(plugin_dir.glob("*.py"))

        for plugin_file in plugin_files:
            if plugin_file.name.startswith("_"):
                continue  # Skip __init__.py, _private.py, etc.

            try:
                await self._load_provider_from_file(plugin_file)
            except Exception as e:
                logger.warning(
                    "local_plugin_load_failed",
                    file=str(plugin_file),
                    error=str(e),
                )

    async def _load_env_providers(self) -> None:
        """Load providers from environment variable paths."""
        logger.debug("loading_env_providers")

        env_providers = os.environ.get("WARDEN_AST_PROVIDERS")
        if not env_providers:
            return

        # Format: "module1:Class1,module2:Class2" or "/path/to/file.py:Class"
        provider_specs = [spec.strip() for spec in env_providers.split(",")]

        for spec in provider_specs:
            if not spec:
                continue

            try:
                if ":" in spec:
                    module_or_path, class_name = spec.rsplit(":", 1)

                    # Check if it's a file path
                    if "/" in module_or_path or "\\" in module_or_path:
                        await self._load_provider_from_file(Path(module_or_path), class_name)
                    else:
                        # It's a module name
                        provider = await self._load_provider_from_module(
                            module_or_path, class_name
                        )
                        if provider:
                            self._registry.register(provider)
                            self._loaded_providers.append(f"env:{spec}")
                else:
                    logger.warning("invalid_env_provider_spec", spec=spec)

            except Exception as e:
                logger.warning(
                    "env_provider_load_failed",
                    spec=spec,
                    error=str(e),
                )

    async def _load_provider_from_module(
        self,
        module_name: str,
        class_name: str,
    ) -> Optional[IASTProvider]:
        """
        Load provider from Python module.

        Args:
            module_name: Full module name (e.g., 'warden.ast.providers.tree_sitter')
            class_name: Provider class name

        Returns:
            Provider instance or None if load failed
        """
        try:
            module = importlib.import_module(module_name)
            provider_class = getattr(module, class_name)
            provider = provider_class()

            if not isinstance(provider, IASTProvider):
                logger.warning(
                    "invalid_provider_class",
                    module=module_name,
                    class_name=class_name,
                )
                return None

            # Validate provider is ready
            is_valid = await provider.validate()
            if not is_valid:
                logger.warning(
                    "provider_validation_failed",
                    provider_name=provider.metadata.name,
                )
                return None

            return provider

        except ImportError as e:
            logger.debug(
                "provider_module_import_failed",
                module=module_name,
                error=str(e),
            )
            return None
        except Exception as e:
            logger.warning(
                "provider_load_failed",
                module=module_name,
                class_name=class_name,
                error=str(e),
            )
            return None

    async def _load_provider_from_file(
        self,
        file_path: Path,
        class_name: Optional[str] = None,
    ) -> None:
        """
        Load provider from Python file.

        Args:
            file_path: Path to Python file
            class_name: Optional class name (discovers if not provided)
        """
        if not file_path.exists():
            logger.warning("provider_file_not_found", path=str(file_path))
            return

        try:
            # Load module from file
            spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
            if spec is None or spec.loader is None:
                logger.warning("invalid_provider_file", path=str(file_path))
                return

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # If class name not provided, try to find IASTProvider implementations
            if class_name is None:
                for attr_name in dir(module):
                    if attr_name.startswith("_"):
                        continue

                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, IASTProvider) and attr is not IASTProvider:
                        class_name = attr_name
                        break

            if class_name is None:
                logger.warning(
                    "no_provider_class_found",
                    path=str(file_path),
                )
                return

            # Instantiate provider
            provider_class = getattr(module, class_name)
            provider = provider_class()

            if not isinstance(provider, IASTProvider):
                logger.warning(
                    "invalid_provider_from_file",
                    path=str(file_path),
                    class_name=class_name,
                )
                return

            # Validate provider
            is_valid = await provider.validate()
            if not is_valid:
                logger.warning(
                    "file_provider_validation_failed",
                    path=str(file_path),
                    provider_name=provider.metadata.name,
                )
                return

            self._registry.register(provider)
            self._loaded_providers.append(f"file:{file_path.stem}")
            logger.info(
                "file_provider_loaded",
                provider_name=provider.metadata.name,
                path=str(file_path),
            )

        except Exception as e:
            logger.warning(
                "file_provider_load_exception",
                path=str(file_path),
                error=str(e),
            )
