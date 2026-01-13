"""
Go Contract Extractor (Gin/Echo/Fiber).

Extracts API contracts from Go HTTP applications by analyzing:
1. Gin handlers (gin.Context)
2. Echo handlers (echo.Context)
3. Fiber handlers (fiber.Ctx)
4. net/http handlers
5. Struct definitions for request/response

Supported Patterns:
- r.GET("/users", getUsers)
- e.POST("/users", createUser)
- app.Get("/users", handler)

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
    PlatformRole,
    OperationType,
)
from warden.ast.domain.enums import CodeLanguage
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


@ExtractorRegistry.register
class GoExtractor(BaseContractExtractor):
    """
    Extracts API contracts from Go projects using Gin, Echo, or Fiber.

    Scans for:
    - **/*.go files
    - Route definitions
    - Struct definitions
    """

    platform_type = PlatformType.GIN  # Primary, also handles Echo/Fiber
    supported_languages = [CodeLanguage.GO]
    file_patterns = [
        "**/*.go",
        "cmd/**/*.go",
        "internal/**/*.go",
        "pkg/**/*.go",
        "api/**/*.go",
        "handlers/**/*.go",
        "controllers/**/*.go",
        "routes/**/*.go",
        "models/**/*.go",
    ]

    HTTP_METHODS = {
        "get": OperationType.QUERY,
        "post": OperationType.COMMAND,
        "put": OperationType.COMMAND,
        "patch": OperationType.COMMAND,
        "delete": OperationType.COMMAND,
    }

    async def extract(self) -> Contract:
        """Extract contract from Go project."""
        logger.info(
            "go_extraction_started",
            project_root=str(self.project_root),
        )

        contract = Contract(
            name="go-provider",
            extracted_from=self.platform_type.value,
        )

        files = self._find_files()
        logger.info("go_files_found", count=len(files))

        seen_operations: Set[str] = set()
        seen_models: Set[str] = set()

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")

                # Extract route operations
                operations = self._extract_operations(content, file_path)
                for op in operations:
                    if op.name not in seen_operations:
                        contract.operations.append(op)
                        seen_operations.add(op.name)

                # Extract struct definitions
                models = self._extract_models(content, file_path)
                for model in models:
                    if model.name not in seen_models:
                        contract.models.append(model)
                        seen_models.add(model.name)

                # Extract const enums
                enums = self._extract_enums(content, file_path)
                for enum in enums:
                    if enum.name not in seen_models:
                        contract.enums.append(enum)
                        seen_models.add(enum.name)

            except Exception as e:
                logger.warning(
                    "go_file_extraction_error",
                    file=str(file_path),
                    error=str(e),
                )

        logger.info(
            "go_extraction_completed",
            operations=len(contract.operations),
            models=len(contract.models),
            enums=len(contract.enums),
        )

        return contract

    def _extract_operations(
        self,
        content: str,
        file_path: Path,
    ) -> List[OperationDefinition]:
        """Extract route operations from Gin/Echo/Fiber."""
        operations: List[OperationDefinition] = []

        # Gin: r.GET("/path", handler)
        # Echo: e.GET("/path", handler)
        # Fiber: app.Get("/path", handler)
        route_pattern = re.compile(
            r"(?:\w+)\s*\.\s*(GET|POST|PUT|PATCH|DELETE|Get|Post|Put|Patch|Delete)\s*\(\s*[\"'`]([^\"'`]+)[\"'`]\s*,\s*(\w+)",
            re.IGNORECASE,
        )

        # Group routes: v1 := r.Group("/api/v1")
        group_pattern = re.compile(
            r"(\w+)\s*:?=\s*\w+\.Group\s*\(\s*[\"'`]([^\"'`]+)[\"'`]",
        )

        # Track group prefixes
        group_prefixes: dict = {}
        for match in group_pattern.finditer(content):
            group_var = match.group(1)
            prefix = match.group(2)
            group_prefixes[group_var] = prefix

        lines = content.split("\n")
        for i, line in enumerate(lines):
            route_match = route_pattern.search(line)
            if route_match:
                method = route_match.group(1).lower()
                path = route_match.group(2)
                handler_name = route_match.group(3)

                # Check if this is a group route
                for group_var, prefix in group_prefixes.items():
                    if group_var + "." in line:
                        path = prefix.rstrip("/") + "/" + path.lstrip("/")
                        break

                operations.append(OperationDefinition(
                    name=handler_name,
                    operation_type=self.HTTP_METHODS.get(method, OperationType.QUERY),
                    description=f"{method.upper()} {path}",
                    source_file=str(file_path),
                    source_line=i + 1,
                ))

        # Also find handler functions to extract input/output types
        self._enhance_operations_with_types(content, operations)

        return operations

    def _enhance_operations_with_types(
        self,
        content: str,
        operations: List[OperationDefinition],
    ) -> None:
        """Enhance operations with input/output types from handler functions."""
        for op in operations:
            handler_name = op.name

            # Find handler function
            # func handlerName(c *gin.Context) { ... }
            handler_pattern = re.compile(
                rf"func\s+{handler_name}\s*\([^)]*\)\s*\{{([\s\S]*?)\n\}}",
                re.MULTILINE,
            )

            match = handler_pattern.search(content)
            if match:
                handler_body = match.group(1)

                # Find ShouldBindJSON or Bind calls
                # c.ShouldBindJSON(&req)
                bind_pattern = re.compile(r"(?:ShouldBindJSON|Bind|BindJSON)\s*\(\s*&(\w+)")
                bind_match = bind_pattern.search(handler_body)
                if bind_match:
                    var_name = bind_match.group(1)
                    # Find variable type
                    var_type_pattern = re.compile(rf"var\s+{var_name}\s+(\w+)")
                    type_match = var_type_pattern.search(handler_body)
                    if type_match:
                        op.input_type = type_match.group(1)

                # Find JSON response type
                # c.JSON(200, response)
                json_pattern = re.compile(r"\.JSON\s*\([^,]+,\s*(\w+)")
                json_match = json_pattern.search(handler_body)
                if json_match:
                    var_name = json_match.group(1)
                    # Try to find type
                    var_type_pattern = re.compile(rf"(\w+)\s*:?=.*{var_name}")
                    # This is simplified - actual type inference would be more complex

    def _extract_models(
        self,
        content: str,
        file_path: Path,
    ) -> List[ModelDefinition]:
        """Extract Go struct definitions."""
        models: List[ModelDefinition] = []

        # type StructName struct { ... }
        struct_pattern = re.compile(
            r"type\s+(\w+)\s+struct\s*\{([^}]+)\}",
            re.MULTILINE | re.DOTALL,
        )

        for match in struct_pattern.finditer(content):
            struct_name = match.group(1)
            struct_body = match.group(2)

            # Skip non-model structs
            if self._should_skip_struct(struct_name):
                continue

            fields = self._parse_struct_fields(struct_body, file_path)

            if fields:
                models.append(ModelDefinition(
                    name=struct_name,
                    fields=fields,
                    source_file=str(file_path),
                    source_line=content[:match.start()].count("\n") + 1,
                ))

        return models

    def _parse_struct_fields(
        self,
        struct_body: str,
        file_path: Path,
    ) -> List[FieldDefinition]:
        """Parse Go struct fields."""
        fields: List[FieldDefinition] = []

        # FieldName FieldType `json:"field_name"`
        field_pattern = re.compile(
            r"(\w+)\s+([\w\[\]\*\.]+)\s*(?:`[^`]*json:\"([^\"]+)\")?",
        )

        for match in field_pattern.finditer(struct_body):
            field_name = match.group(1)
            field_type = match.group(2)
            json_name = match.group(3)

            # Skip embedded types
            if field_name[0].islower():
                continue

            # Use json tag name if available
            display_name = json_name.split(",")[0] if json_name else field_name

            # Check if optional (pointer type)
            is_optional = field_type.startswith("*")
            is_array = field_type.startswith("[]")

            fields.append(FieldDefinition(
                name=display_name,
                type_name=self._clean_type(field_type),
                is_optional=is_optional,
                is_array=is_array,
                source_file=str(file_path),
            ))

        return fields

    def _should_skip_struct(self, name: str) -> bool:
        """Check if struct should be skipped."""
        skip_suffixes = [
            "Handler", "Controller", "Service", "Repository",
            "Config", "Server", "Router", "Middleware",
        ]
        return any(name.endswith(s) for s in skip_suffixes)

    def _extract_enums(
        self,
        content: str,
        file_path: Path,
    ) -> List[EnumDefinition]:
        """Extract Go const enums (iota pattern)."""
        enums: List[EnumDefinition] = []

        # type Status int
        # const (
        #     StatusActive Status = iota
        #     StatusInactive
        # )
        type_pattern = re.compile(r"type\s+(\w+)\s+(?:int|string)")
        const_block_pattern = re.compile(
            r"const\s*\(\s*([\s\S]*?)\s*\)",
            re.MULTILINE,
        )

        # Find type definitions
        type_names = {m.group(1) for m in type_pattern.finditer(content)}

        # Find const blocks
        for block_match in const_block_pattern.finditer(content):
            block_content = block_match.group(1)

            # Check if this block defines values for any of our types
            for type_name in type_names:
                if type_name in block_content:
                    # Extract values
                    value_pattern = re.compile(rf"(\w+)\s+{type_name}")
                    values = [m.group(1) for m in value_pattern.finditer(block_content)]

                    if values:
                        enums.append(EnumDefinition(
                            name=type_name,
                            values=values,
                            source_file=str(file_path),
                            source_line=content[:block_match.start()].count("\n") + 1,
                        ))

        return enums

    def _clean_type(self, type_str: str) -> str:
        """Clean Go type to contract type."""
        if not type_str:
            return "any"

        # Remove pointer
        type_str = type_str.lstrip("*")

        # Remove slice prefix
        if type_str.startswith("[]"):
            return self._clean_type(type_str[2:])

        # Map Go types
        mapping = {
            "string": "string",
            "int": "int",
            "int32": "int",
            "int64": "int",
            "uint": "int",
            "uint32": "int",
            "uint64": "int",
            "float32": "float",
            "float64": "float",
            "bool": "bool",
            "time.Time": "datetime",
            "[]byte": "bytes",
            "interface{}": "any",
            "any": "any",
        }

        return mapping.get(type_str, type_str)
