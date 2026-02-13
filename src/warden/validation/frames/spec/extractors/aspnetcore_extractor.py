"""
ASP.NET Core Contract Extractor.

Extracts API contracts from ASP.NET Core Web API projects by analyzing:
1. Controller classes with [ApiController] attribute
2. HTTP method attributes ([HttpGet], [HttpPost], etc.)
3. Route attributes ([Route], [HttpGet("path")])
4. DTO/Model classes
5. Request/Response types from action parameters and return types

Supported Patterns:
- [HttpGet], [HttpPost], [HttpPut], [HttpPatch], [HttpDelete]
- [Route("api/[controller]")]
- [FromBody], [FromQuery], [FromRoute] parameters
- ActionResult<T>, IActionResult return types
- Record types and classes with properties

Author: Warden Team
Version: 1.0.0
"""

import re
from pathlib import Path
from typing import List, Optional, Set

from warden.ast.domain.enums import CodeLanguage
from warden.shared.infrastructure.logging import get_logger
from warden.validation.frames.spec.extractors.base import (
    BaseContractExtractor,
    ExtractorRegistry,
)
from warden.validation.frames.spec.models import (
    Contract,
    EnumDefinition,
    FieldDefinition,
    ModelDefinition,
    OperationDefinition,
    OperationType,
    PlatformType,
)

logger = get_logger(__name__)


@ExtractorRegistry.register
class AspNetCoreExtractor(BaseContractExtractor):
    """
    Extracts API contracts from ASP.NET Core projects.

    Scans for:
    - Controllers/**/*.cs
    - Models/**/*.cs, DTOs/**/*.cs
    - [ApiController] decorated classes
    """

    platform_type = PlatformType.ASP_NET_CORE
    supported_languages = [CodeLanguage.CSHARP]
    file_patterns = [
        "**/*Controller.cs",
        "**/*Controllers/*.cs",
        "**/Controllers/**/*.cs",
        "**/Models/**/*.cs",
        "**/DTOs/**/*.cs",
        "**/Entities/**/*.cs",
        "**/ViewModels/**/*.cs",
    ]

    # HTTP method attributes
    HTTP_ATTRIBUTES = {
        "HttpGet": OperationType.QUERY,
        "HttpPost": OperationType.COMMAND,
        "HttpPut": OperationType.COMMAND,
        "HttpPatch": OperationType.COMMAND,
        "HttpDelete": OperationType.COMMAND,
    }

    async def extract(self) -> Contract:
        """
        Extract contract from ASP.NET Core project.

        Returns:
            Contract with operations and models
        """
        logger.info(
            "aspnetcore_extraction_started",
            project_root=str(self.project_root),
        )

        contract = Contract(
            name="aspnetcore-provider",
            extracted_from=self.platform_type.value,
        )

        files = self._find_files()
        logger.info("aspnetcore_files_found", count=len(files))

        seen_operations: set[str] = set()
        seen_models: set[str] = set()

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")

                # Check if it's a controller
                if self._is_controller(content):
                    # Extract controller route prefix
                    controller_route = self._extract_controller_route(content)
                    controller_name = self._extract_controller_name(content)

                    # Extract operations from controller actions
                    operations = self._extract_operations(
                        content, file_path, controller_route, controller_name
                    )
                    for op in operations:
                        if op.name not in seen_operations:
                            contract.operations.append(op)
                            seen_operations.add(op.name)

                # Extract models (from any .cs file)
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
                    "aspnetcore_file_extraction_error",
                    file=str(file_path),
                    error=str(e),
                )

        logger.info(
            "aspnetcore_extraction_completed",
            operations=len(contract.operations),
            models=len(contract.models),
            enums=len(contract.enums),
        )

        return contract

    def _is_controller(self, content: str) -> bool:
        """Check if file contains an API controller."""
        return (
            "[ApiController]" in content
            or ": ControllerBase" in content
            or ": Controller" in content
        )

    def _extract_controller_name(self, content: str) -> str:
        """Extract controller class name."""
        pattern = re.compile(
            r"class\s+(\w+)(?:Controller)?\s*:\s*(?:Controller|ControllerBase)"
        )
        match = pattern.search(content)
        if match:
            name = match.group(1)
            # Remove "Controller" suffix if present
            return name.replace("Controller", "")
        return "Unknown"

    def _extract_controller_route(self, content: str) -> str:
        """Extract route prefix from [Route] attribute."""
        # [Route("api/[controller]")] or [Route("api/users")]
        pattern = re.compile(r'\[Route\s*\(\s*"([^"]+)"\s*\)\]')
        match = pattern.search(content)
        if match:
            route = match.group(1)
            # Replace [controller] placeholder
            controller_name = self._extract_controller_name(content).lower()
            route = route.replace("[controller]", controller_name)
            return route
        return ""

    def _extract_operations(
        self,
        content: str,
        file_path: Path,
        controller_route: str,
        controller_name: str,
    ) -> list[OperationDefinition]:
        """
        Extract operations from controller actions.

        Patterns:
            [HttpGet]
            public async Task<ActionResult<User>> GetUser(int id)

            [HttpPost("create")]
            public async Task<IActionResult> CreateUser([FromBody] CreateUserDto dto)
        """
        operations: list[OperationDefinition] = []

        # Pattern for HTTP attributes with optional route
        # [HttpGet], [HttpGet("path")], [HttpGet("{id}")]
        http_pattern = re.compile(
            r'\[(Http(?:Get|Post|Put|Patch|Delete))(?:\s*\(\s*"([^"]*)")?\s*\)\]',
            re.IGNORECASE,
        )

        # Pattern for action method
        # public async Task<ActionResult<T>> MethodName(params)
        # public IActionResult MethodName(params)
        method_pattern = re.compile(
            r"public\s+(?:async\s+)?(?:Task<)?(?:ActionResult<([^>]+)>|IActionResult|ActionResult)(?:>)?\s+(\w+)\s*\(([^)]*)\)",
            re.MULTILINE,
        )

        lines = content.split("\n")

        for i, line in enumerate(lines):
            http_match = http_pattern.search(line)
            if http_match:
                http_method = http_match.group(1)
                action_route = http_match.group(2) or ""

                # Search for method in next lines
                search_range = "\n".join(lines[i : i + 10])
                method_match = method_pattern.search(search_range)

                if method_match:
                    return_type = method_match.group(1) or "void"
                    method_name = method_match.group(2)
                    params = method_match.group(3)

                    # Build full path
                    full_path = self._build_path(controller_route, action_route)

                    # Extract input type from [FromBody] parameter
                    input_type = self._extract_from_body_param(params)

                    # Clean return type
                    output_type = self._clean_type(return_type)

                    # Generate operation name
                    op_name = self._generate_operation_name(
                        method_name, http_method, controller_name
                    )

                    operations.append(OperationDefinition(
                        name=op_name,
                        operation_type=self.HTTP_ATTRIBUTES.get(
                            http_method, OperationType.QUERY
                        ),
                        input_type=input_type,
                        output_type=output_type,
                        description=f"{http_method.replace('Http', '')} {full_path}",
                        source_file=str(file_path),
                        source_line=i + 1,
                    ))

        return operations

    def _build_path(self, controller_route: str, action_route: str) -> str:
        """Build full API path from controller and action routes."""
        parts = []
        if controller_route:
            parts.append(controller_route.strip("/"))
        if action_route:
            parts.append(action_route.strip("/"))
        return "/" + "/".join(parts) if parts else "/"

    def _extract_from_body_param(self, params: str) -> str | None:
        """Extract type from [FromBody] parameter."""
        # [FromBody] TypeName paramName
        pattern = re.compile(r"\[FromBody\]\s*(\w+)")
        match = pattern.search(params)
        if match:
            return match.group(1)

        # If no [FromBody], look for complex type parameter (not primitive)
        # CreateUserDto dto, UpdateRequest request
        param_pattern = re.compile(r"(\w+(?:Dto|Request|Command|Input))\s+\w+")
        match = param_pattern.search(params)
        if match:
            return match.group(1)

        return None

    def _extract_models(
        self,
        content: str,
        file_path: Path,
    ) -> list[ModelDefinition]:
        """
        Extract models from C# classes and records.

        Patterns:
            public class UserDto { public string Name { get; set; } }
            public record CreateUserRequest(string Name, string Email);
        """
        models: list[ModelDefinition] = []

        # Pattern for class definition
        class_pattern = re.compile(
            r"public\s+(?:partial\s+)?(?:class|record)\s+(\w+)(?:\s*[:(][^{]*)?\s*\{",
            re.MULTILINE,
        )

        # Pattern for properties
        # public Type Name { get; set; }
        property_pattern = re.compile(
            r"public\s+(?:required\s+)?(\w+(?:<[^>]+>)?)\??\s+(\w+)\s*\{\s*get;",
        )

        # Pattern for record parameters
        # record Name(Type Prop1, Type Prop2)
        record_param_pattern = re.compile(
            r"record\s+\w+\s*\(([^)]+)\)",
        )

        for class_match in class_pattern.finditer(content):
            class_name = class_match.group(1)

            # Skip common non-model classes
            if any(suffix in class_name for suffix in [
                "Controller", "Service", "Repository", "Handler",
                "Middleware", "Filter", "Attribute", "Extension",
                "Builder", "Factory", "Provider", "Context",
            ]):
                continue

            # Find class body
            start = class_match.end()
            brace_count = 1
            end = start

            for j, char in enumerate(content[start:], start):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end = j
                        break

            class_body = content[start:end]

            fields: list[FieldDefinition] = []

            # Extract properties
            for prop_match in property_pattern.finditer(class_body):
                prop_type = prop_match.group(1)
                prop_name = prop_match.group(2)

                is_optional = "?" in content[
                    class_match.start() + prop_match.start():
                    class_match.start() + prop_match.end()
                ]
                is_array = prop_type.startswith("List<") or prop_type.endswith("[]")

                fields.append(FieldDefinition(
                    name=prop_name,
                    type_name=self._clean_type(prop_type),
                    is_optional=is_optional,
                    is_array=is_array,
                    source_file=str(file_path),
                ))

            # Check for record parameters
            record_match = record_param_pattern.search(
                content[class_match.start():class_match.end() + 100]
            )
            if record_match:
                params = record_match.group(1)
                for param in params.split(","):
                    param = param.strip()
                    parts = param.split()
                    if len(parts) >= 2:
                        param_type = parts[0]
                        param_name = parts[1]
                        fields.append(FieldDefinition(
                            name=param_name,
                            type_name=self._clean_type(param_type),
                            is_optional="?" in param_type,
                            is_array="List<" in param_type or "[]" in param_type,
                            source_file=str(file_path),
                        ))

            if fields:
                line_num = content[:class_match.start()].count("\n") + 1
                models.append(ModelDefinition(
                    name=class_name,
                    fields=fields,
                    source_file=str(file_path),
                    source_line=line_num,
                ))

        return models

    def _extract_enums(
        self,
        content: str,
        file_path: Path,
    ) -> list[EnumDefinition]:
        """Extract enums from C# code."""
        enums: list[EnumDefinition] = []

        # Pattern for enum
        # public enum Status { Active, Inactive }
        enum_pattern = re.compile(
            r"public\s+enum\s+(\w+)\s*\{([^}]+)\}",
            re.MULTILINE,
        )

        for enum_match in enum_pattern.finditer(content):
            enum_name = enum_match.group(1)
            enum_body = enum_match.group(2)

            # Extract values
            values: list[str] = []
            value_pattern = re.compile(r"(\w+)(?:\s*=\s*\d+)?")

            for value_match in value_pattern.finditer(enum_body):
                value = value_match.group(1).strip()
                if value and not value.startswith("//"):
                    values.append(value)

            if values:
                line_num = content[:enum_match.start()].count("\n") + 1
                enums.append(EnumDefinition(
                    name=enum_name,
                    values=values,
                    source_file=str(file_path),
                    source_line=line_num,
                ))

        return enums

    def _generate_operation_name(
        self,
        method_name: str,
        http_method: str,
        controller_name: str,
    ) -> str:
        """Generate operation name from method and controller."""
        # If method already has good name, use it
        if not method_name.startswith("Get") and not method_name.startswith("Create"):
            # Convert to camelCase
            name = method_name[0].lower() + method_name[1:]
            return name

        return method_name[0].lower() + method_name[1:]

    def _clean_type(self, type_str: str) -> str:
        """Clean C# type to contract type."""
        # Remove List<> wrapper
        if type_str.startswith("List<") and type_str.endswith(">"):
            inner = type_str[5:-1]
            return self._clean_type(inner)

        # Remove IEnumerable<>, ICollection<>
        for prefix in ["IEnumerable<", "ICollection<", "IList<"]:
            if type_str.startswith(prefix) and type_str.endswith(">"):
                inner = type_str[len(prefix):-1]
                return self._clean_type(inner)

        # Remove array notation
        type_str = type_str.rstrip("[]")

        # Remove nullable
        type_str = type_str.rstrip("?")

        # Map C# types to contract primitives
        type_mapping = {
            "string": "string",
            "String": "string",
            "int": "int",
            "Int32": "int",
            "long": "int",
            "Int64": "int",
            "float": "float",
            "Single": "float",
            "double": "float",
            "Double": "float",
            "decimal": "decimal",
            "Decimal": "decimal",
            "bool": "bool",
            "Boolean": "bool",
            "DateTime": "datetime",
            "DateTimeOffset": "datetime",
            "DateOnly": "date",
            "TimeOnly": "time",
            "Guid": "string",
            "byte[]": "bytes",
            "object": "any",
            "dynamic": "any",
            "void": "void",
        }

        return type_mapping.get(type_str, type_str)
