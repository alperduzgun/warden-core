"""
Modular Contract Extractor - Reads pre-generated modular contracts.

This extractor reads contracts from `.warden/contracts/modules/*.yaml`
and merges them into a single Contract object. This enables:
- Modular contract management (split by domain/service)
- AI-driven noise filtering via .wardenignore
- Project-agnostic contract loading
"""

from pathlib import Path
from typing import Any, List, Optional

import yaml

from warden.shared.infrastructure.logging import get_logger
from warden.validation.frames.spec.extractors.base import (
    BaseContractExtractor,
    ExtractorResilienceConfig,
)
from warden.validation.frames.spec.models import (
    Contract,
    ModelDefinition,
    OperationDefinition,
    OperationType,
    PlatformRole,
    PlatformType,
)

logger = get_logger(__name__)


class ModularContractExtractor(BaseContractExtractor):
    """
    Extractor for pre-generated modular contracts.

    Reads YAML files from `.warden/contracts/modules/` and merges them
    into a single Contract object. Respects .wardenignore patterns.
    """

    platform_type = PlatformType.UNIVERSAL
    supported_languages = []  # Not language-specific
    file_patterns = []  # Not file-based scanning

    def __init__(
        self,
        project_root: Path,
        role: PlatformRole,
        resilience_config: ExtractorResilienceConfig | None = None,
    ):
        super().__init__(project_root, role, resilience_config)
        self.modules_dir = project_root / ".warden" / "contracts" / "modules"

    async def extract(self) -> Contract:
        """
        Extract contract by reading and merging modular YAML files.

        Returns:
            Merged Contract with all operations and models
        """
        if not self.modules_dir.exists():
            logger.warning(
                "modules_directory_not_found",
                path=str(self.modules_dir),
                message="No modular contracts found, returning empty contract",
            )
            return Contract(
                name=f"{self.role.value}_contract",
                extracted_from="modular",
            )

        # Collect all YAML files
        yaml_files = sorted(self.modules_dir.glob("*.yaml"))

        if not yaml_files:
            logger.warning(
                "no_module_files_found",
                path=str(self.modules_dir),
            )
            return Contract(
                name=f"{self.role.value}_contract",
                extracted_from="modular",
            )

        logger.info(
            "loading_modular_contracts",
            modules_dir=str(self.modules_dir),
            file_count=len(yaml_files),
        )

        # Merge all modules
        all_operations: list[OperationDefinition] = []
        all_models: list[ModelDefinition] = []

        for yaml_file in yaml_files:
            try:
                module_contract = self._load_module(yaml_file)
                if module_contract:
                    all_operations.extend(module_contract.get("contracts", []))
                    # Models are not typically in modular format, but support if present
                    all_models.extend(module_contract.get("models", []))

            except Exception as e:
                logger.error(
                    "module_load_failed",
                    file=yaml_file.name,
                    error=str(e),
                )
                self._stats["files_failed"] += 1
                continue

        # Convert raw dicts to OperationDefinition objects
        operations = []
        for op_dict in all_operations:
            try:
                operations.append(self._dict_to_operation(op_dict))
            except Exception as e:
                logger.warning(
                    "operation_parse_failed",
                    operation=op_dict.get("endpoint", "unknown"),
                    error=str(e),
                )

        logger.info(
            "modular_contract_loaded",
            total_operations=len(operations),
            total_models=len(all_models),
            modules_processed=self._stats["files_processed"],
            modules_failed=self._stats["files_failed"],
        )

        return Contract(
            name=f"{self.role.value}_contract",
            extracted_from="modular",
            operations=operations,
            models=all_models,
        )

    def _load_module(self, yaml_file: Path) -> dict | None:
        """Load a single module YAML file."""
        try:
            with open(yaml_file) as f:
                content = yaml.safe_load(f)

            self._stats["files_processed"] += 1
            logger.debug(
                "module_loaded",
                file=yaml_file.name,
                operations=len(content.get("contracts", [])),
            )
            return content

        except Exception as e:
            logger.error(
                "module_read_failed",
                file=yaml_file.name,
                error=str(e),
            )
            raise

    def _dict_to_operation(self, op_dict: dict) -> OperationDefinition:
        """Convert a dict to OperationDefinition."""
        endpoint_str = op_dict.get("endpoint", "")
        http_method = self._extract_http_method(endpoint_str)

        # Extract operation name from endpoint
        # "POST /auth/login" -> "login" or "auth_login"
        path = endpoint_str.replace(http_method, "").strip()
        operation_name = path.replace("/", "_").strip("_") or "unknown_operation"

        return OperationDefinition(
            name=operation_name,
            operation_type=OperationType.COMMAND
            if http_method in ["POST", "PUT", "DELETE", "PATCH"]
            else OperationType.QUERY,
            source_file=op_dict.get("source_file"),
            source_line=op_dict.get("line_number"),
            metadata={
                "endpoint": path,
                "http_method": http_method,
                "request_fields": op_dict.get("request", []),
                "response_fields": op_dict.get("response", []),
            },
        )

    def _extract_http_method(self, endpoint: str) -> str:
        """Extract HTTP method from endpoint string."""
        methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
        for method in methods:
            if endpoint.upper().startswith(method):
                return method
        return "GET"  # Default
