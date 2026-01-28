"""
Express.js Contract Extractor.

Extracts API contracts from Express.js applications by analyzing:
1. Route definitions (app.get, router.post, etc.)
2. Router instances
3. Middleware chains
4. Request/Response types (with TypeScript)

Supported Patterns:
- app.get('/users', handler)
- router.post('/users', validate, createUser)
- app.use('/api', apiRouter)

Author: Warden Team
Version: 1.0.0
"""

import re
from pathlib import Path
from typing import List, Optional, Set

from warden.validation.frames.spec.extractors.base import (
    BaseContractExtractor,
    ExtractorRegistry,
)
from warden.validation.frames.spec.models import (
    Contract,
    OperationDefinition,
    ModelDefinition,
    FieldDefinition,
    EnumDefinition,
    PlatformType,
    OperationType,
)
from warden.ast.domain.enums import CodeLanguage
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


@ExtractorRegistry.register
class ExpressExtractor(BaseContractExtractor):
    """
    Extracts API contracts from Express.js projects.

    Scans for:
    - src/**/*.ts, src/**/*.js
    - Routes, controllers, handlers
    - TypeScript interfaces for request/response
    """

    platform_type = PlatformType.EXPRESS
    supported_languages = [CodeLanguage.TYPESCRIPT, CodeLanguage.JAVASCRIPT]
    file_patterns = [
        "src/**/*.ts",
        "src/**/*.js",
        "routes/**/*.ts",
        "routes/**/*.js",
        "controllers/**/*.ts",
        "controllers/**/*.js",
        "api/**/*.ts",
        "api/**/*.js",
        "app.ts",
        "app.js",
        "index.ts",
        "index.js",
        "server.ts",
        "server.js",
    ]

    HTTP_METHODS = {
        "get": OperationType.QUERY,
        "post": OperationType.COMMAND,
        "put": OperationType.COMMAND,
        "patch": OperationType.COMMAND,
        "delete": OperationType.COMMAND,
    }

    async def extract(self) -> Contract:
        """Extract contract from Express.js project."""
        logger.info(
            "express_extraction_started",
            project_root=str(self.project_root),
        )

        contract = Contract(
            name="express-provider",
            extracted_from=self.platform_type.value,
        )

        files = self._find_files()
        logger.info("express_files_found", count=len(files))

        seen_operations: Set[str] = set()
        seen_models: Set[str] = set()

        # Track router prefixes
        router_prefixes: dict = {}

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")

                # Extract router mount points
                self._extract_router_mounts(content, router_prefixes)

                # Extract route operations
                operations = self._extract_operations(content, file_path, router_prefixes)
                for op in operations:
                    if op.name not in seen_operations:
                        contract.operations.append(op)
                        seen_operations.add(op.name)

                # Extract TypeScript interfaces
                models = self._extract_models(content, file_path)
                for model in models:
                    if model.name not in seen_models:
                        contract.models.append(model)
                        seen_models.add(model.name)

                # Extract enums
                enums = self._extract_enums(content, file_path)
                for enum in enums:
                    if enum.name not in seen_models:
                        contract.enums.append(enum)
                        seen_models.add(enum.name)

            except Exception as e:
                logger.warning(
                    "express_file_extraction_error",
                    file=str(file_path),
                    error=str(e),
                )

        logger.info(
            "express_extraction_completed",
            operations=len(contract.operations),
            models=len(contract.models),
            enums=len(contract.enums),
        )

        return contract

    def _extract_router_mounts(self, content: str, router_prefixes: dict) -> None:
        """Extract router mount points like app.use('/api', router)."""
        # app.use('/api/users', userRouter)
        mount_pattern = re.compile(
            r"(?:app|router)\s*\.\s*use\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\w+)",
        )
        for match in mount_pattern.finditer(content):
            prefix = match.group(1)
            router_name = match.group(2)
            router_prefixes[router_name] = prefix

    def _extract_operations(
        self,
        content: str,
        file_path: Path,
        router_prefixes: dict,
    ) -> List[OperationDefinition]:
        """Extract Express route operations."""
        operations: List[OperationDefinition] = []

        # Pattern for route definitions
        # app.get('/users', handler)
        # router.post('/users/:id', validate, updateUser)
        route_pattern = re.compile(
            r"(?:app|router|(\w+))\s*\.\s*(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"](?:[^)]*,\s*(?:async\s+)?(?:function\s*)?(\w+)|[^)]*,\s*(?:async\s+)?\([^)]*\)\s*(?:=>|:))",
            re.IGNORECASE,
        )

        # Pattern for inline handlers with typed request
        typed_handler_pattern = re.compile(
            r"\.\s*(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"][^)]*\(\s*req\s*:\s*Request<[^>]*,\s*[^>]*,\s*(\w+)>",
        )

        lines = content.split("\n")
        for i, line in enumerate(lines):
            # Check for route definition
            route_match = route_pattern.search(line)
            if route_match:
                router_var = route_match.group(1)
                method = route_match.group(2).lower()
                path = route_match.group(3)
                handler_name = route_match.group(4)

                # Apply router prefix if known
                if router_var and router_var in router_prefixes:
                    path = router_prefixes[router_var].rstrip("/") + "/" + path.lstrip("/")

                # Generate operation name
                if handler_name:
                    op_name = handler_name
                else:
                    op_name = self._path_to_operation_name(path, method)

                # Try to find request body type
                input_type = self._extract_body_type(content, i)

                operations.append(OperationDefinition(
                    name=op_name,
                    operation_type=self.HTTP_METHODS.get(method, OperationType.QUERY),
                    input_type=input_type,
                    description=f"{method.upper()} {path}",
                    source_file=str(file_path),
                    source_line=i + 1,
                ))

            # Check for typed request body
            typed_match = typed_handler_pattern.search(line)
            if typed_match and not route_match:
                method = typed_match.group(1).lower()
                path = typed_match.group(2)
                body_type = typed_match.group(3)

                operations.append(OperationDefinition(
                    name=self._path_to_operation_name(path, method),
                    operation_type=self.HTTP_METHODS.get(method, OperationType.QUERY),
                    input_type=body_type,
                    description=f"{method.upper()} {path}",
                    source_file=str(file_path),
                    source_line=i + 1,
                ))

        return operations

    def _extract_body_type(self, content: str, line_index: int) -> Optional[str]:
        """Try to extract request body type from handler."""
        lines = content.split("\n")
        search_range = "\n".join(lines[line_index:line_index + 10])

        # req.body as Type
        body_pattern = re.compile(r"req\.body\s+as\s+(\w+)")
        match = body_pattern.search(search_range)
        if match:
            return match.group(1)

        # const { ... }: Type = req.body
        destruct_pattern = re.compile(r":\s*(\w+(?:Dto|Request|Input|Body))\s*=\s*req\.body")
        match = destruct_pattern.search(search_range)
        if match:
            return match.group(1)

        return None

    def _extract_models(
        self,
        content: str,
        file_path: Path,
    ) -> List[ModelDefinition]:
        """Extract TypeScript interfaces and types."""
        models: List[ModelDefinition] = []

        interface_pattern = re.compile(
            r"(?:export\s+)?interface\s+(\w+)(?:\s+extends\s+[^{]+)?\s*\{([^}]+)\}",
            re.MULTILINE | re.DOTALL,
        )

        type_pattern = re.compile(
            r"(?:export\s+)?type\s+(\w+)\s*=\s*\{([^}]+)\}",
            re.MULTILINE | re.DOTALL,
        )

        for match in interface_pattern.finditer(content):
            model = self._parse_model_body(
                match.group(1), match.group(2), file_path,
                content[:match.start()].count("\n") + 1
            )
            if model:
                models.append(model)

        for match in type_pattern.finditer(content):
            model = self._parse_model_body(
                match.group(1), match.group(2), file_path,
                content[:match.start()].count("\n") + 1
            )
            if model:
                models.append(model)

        return models

    def _parse_model_body(
        self,
        name: str,
        body: str,
        file_path: Path,
        line_num: int,
    ) -> Optional[ModelDefinition]:
        """Parse interface/type body."""
        # Skip Express-specific types
        skip_types = ["Request", "Response", "NextFunction", "Router", "Application"]
        if name in skip_types:
            return None

        fields: List[FieldDefinition] = []
        field_pattern = re.compile(r"(\w+)\s*(\?)?\s*:\s*([^;,\n]+)")

        for match in field_pattern.finditer(body):
            field_name = match.group(1)
            is_optional = match.group(2) == "?"
            field_type = match.group(3).strip()

            fields.append(FieldDefinition(
                name=field_name,
                type_name=self._clean_type(field_type),
                is_optional=is_optional,
                is_array=field_type.endswith("[]") or "Array<" in field_type,
                source_file=str(file_path),
            ))

        if fields:
            return ModelDefinition(
                name=name,
                fields=fields,
                source_file=str(file_path),
                source_line=line_num,
            )
        return None

    def _extract_enums(self, content: str, file_path: Path) -> List[EnumDefinition]:
        """Extract TypeScript enums."""
        enums: List[EnumDefinition] = []
        enum_pattern = re.compile(r"(?:export\s+)?enum\s+(\w+)\s*\{([^}]+)\}", re.MULTILINE)

        for match in enum_pattern.finditer(content):
            values = [v.strip().split("=")[0].strip()
                     for v in match.group(2).split(",") if v.strip()]
            if values:
                enums.append(EnumDefinition(
                    name=match.group(1),
                    values=values,
                    source_file=str(file_path),
                    source_line=content[:match.start()].count("\n") + 1,
                ))
        return enums

    def _path_to_operation_name(self, path: str, method: str) -> str:
        """Convert API path to operation name."""
        path = re.sub(r"^/?(?:api/)?(?:v\d+/)?", "", path)
        parts = [p for p in path.split("/") if p and not p.startswith(":")]

        if not parts:
            return f"{method}Resource"

        resource = parts[-1]
        resource = re.sub(r"[-_](.)", lambda m: m.group(1).upper(), resource)
        prefix = {"get": "get", "post": "create", "put": "update", "patch": "update", "delete": "delete"}.get(method, method)

        return f"{prefix}{resource[0].upper()}{resource[1:]}" if resource else f"{prefix}Resource"

    def _clean_type(self, type_str: str) -> str:
        """Clean TypeScript type."""
        if not type_str:
            return "any"
        type_str = type_str.strip()

        if type_str.startswith("Promise<") and type_str.endswith(">"):
            return self._clean_type(type_str[8:-1])
        if type_str.endswith("[]"):
            return self._clean_type(type_str[:-2])

        type_str = re.sub(r"\s*\|\s*(?:null|undefined)", "", type_str)

        mapping = {"string": "string", "number": "float", "boolean": "bool", "Date": "datetime", "any": "any", "void": "void"}
        return mapping.get(type_str, type_str)
