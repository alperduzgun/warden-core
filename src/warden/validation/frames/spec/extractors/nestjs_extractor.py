"""
NestJS Contract Extractor.

Extracts API contracts from NestJS applications by analyzing:
1. @Controller() decorated classes
2. HTTP method decorators (@Get, @Post, @Put, @Patch, @Delete)
3. @Body(), @Param(), @Query() parameter decorators
4. DTO classes with class-validator decorators
5. Return types and response decorators

Supported Patterns:
- @Controller('users'), @Get(':id'), @Post()
- @Body() createUserDto: CreateUserDto
- @Param('id') id: string
- class CreateUserDto { @IsString() name: string; }

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
class NestJSExtractor(BaseContractExtractor):
    """
    Extracts API contracts from NestJS projects.

    Scans for:
    - **/*.controller.ts
    - **/*.dto.ts
    - **/*.entity.ts
    """

    platform_type = PlatformType.NESTJS
    supported_languages = [CodeLanguage.TYPESCRIPT]
    file_patterns = [
        "src/**/*.controller.ts",
        "src/**/*.dto.ts",
        "src/**/*.entity.ts",
        "src/**/*.model.ts",
        "src/**/controllers/**/*.ts",
        "src/**/dto/**/*.ts",
        "src/**/entities/**/*.ts",
    ]

    # HTTP method decorators
    HTTP_DECORATORS = {
        "Get": OperationType.QUERY,
        "Post": OperationType.COMMAND,
        "Put": OperationType.COMMAND,
        "Patch": OperationType.COMMAND,
        "Delete": OperationType.COMMAND,
    }

    async def extract(self) -> Contract:
        """
        Extract contract from NestJS project.

        Returns:
            Contract with operations and models
        """
        logger.info(
            "nestjs_extraction_started",
            project_root=str(self.project_root),
        )

        contract = Contract(
            name="nestjs-provider",
            extracted_from=self.platform_type.value,
        )

        files = self._find_files()
        logger.info("nestjs_files_found", count=len(files))

        seen_operations: Set[str] = set()
        seen_models: Set[str] = set()

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")

                # Check if it's a controller
                if self._is_controller(content):
                    # Extract controller base path
                    base_path = self._extract_controller_path(content)

                    # Extract operations
                    operations = self._extract_operations(content, file_path, base_path)
                    for op in operations:
                        if op.name not in seen_operations:
                            contract.operations.append(op)
                            seen_operations.add(op.name)

                # Extract DTOs/entities
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
                    "nestjs_file_extraction_error",
                    file=str(file_path),
                    error=str(e),
                )

        logger.info(
            "nestjs_extraction_completed",
            operations=len(contract.operations),
            models=len(contract.models),
            enums=len(contract.enums),
        )

        return contract

    def _is_controller(self, content: str) -> bool:
        """Check if file contains a NestJS controller."""
        return "@Controller" in content

    def _extract_controller_path(self, content: str) -> str:
        """Extract base path from @Controller decorator."""
        # @Controller('users') or @Controller("users")
        pattern = re.compile(r"@Controller\s*\(\s*['\"]([^'\"]*)['\"]")
        match = pattern.search(content)
        if match:
            return match.group(1)
        return ""

    def _extract_operations(
        self,
        content: str,
        file_path: Path,
        base_path: str,
    ) -> List[OperationDefinition]:
        """
        Extract operations from NestJS controller methods.

        Patterns:
            @Get()
            async findAll(): Promise<User[]> { ... }

            @Post()
            async create(@Body() createUserDto: CreateUserDto): Promise<User> { ... }

            @Get(':id')
            async findOne(@Param('id') id: string): Promise<User> { ... }
        """
        operations: List[OperationDefinition] = []

        # Pattern for HTTP method decorators
        # @Get(), @Get(':id'), @Post('create')
        http_decorator_pattern = re.compile(
            r"@(Get|Post|Put|Patch|Delete)\s*\(\s*(?:['\"]([^'\"]*)['\"])?\s*\)",
            re.IGNORECASE,
        )

        # Pattern for method definition
        # async methodName(@Body() dto: Type): Promise<ReturnType>
        method_pattern = re.compile(
            r"(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*(?::\s*Promise<([^>]+)>|:\s*(\w+))?\s*\{",
            re.MULTILINE,
        )

        lines = content.split("\n")

        for i, line in enumerate(lines):
            decorator_match = http_decorator_pattern.search(line)
            if decorator_match:
                http_method = decorator_match.group(1)
                action_path = decorator_match.group(2) or ""

                # Search for method in next lines
                search_range = "\n".join(lines[i + 1 : i + 15])
                method_match = method_pattern.search(search_range)

                if method_match:
                    method_name = method_match.group(1)
                    params = method_match.group(2)
                    return_type = method_match.group(3) or method_match.group(4)

                    # Build full path
                    full_path = self._build_path(base_path, action_path)

                    # Extract input type from @Body() parameter
                    input_type = self._extract_body_param(params)

                    # Clean return type
                    output_type = self._clean_type(return_type) if return_type else None

                    operations.append(OperationDefinition(
                        name=method_name,
                        operation_type=self.HTTP_DECORATORS.get(
                            http_method, OperationType.QUERY
                        ),
                        input_type=input_type,
                        output_type=output_type,
                        description=f"{http_method.upper()} /{full_path}",
                        source_file=str(file_path),
                        source_line=i + 1,
                    ))

        return operations

    def _build_path(self, base_path: str, action_path: str) -> str:
        """Build full API path."""
        parts = []
        if base_path:
            parts.append(base_path.strip("/"))
        if action_path:
            parts.append(action_path.strip("/"))
        return "/".join(parts)

    def _extract_body_param(self, params: str) -> Optional[str]:
        """Extract type from @Body() parameter."""
        # @Body() dto: CreateUserDto
        # @Body() createUserDto: CreateUserDto
        pattern = re.compile(r"@Body\s*\([^)]*\)\s*\w+\s*:\s*(\w+)")
        match = pattern.search(params)
        if match:
            return match.group(1)

        # Look for DTO type without @Body (less common but valid)
        dto_pattern = re.compile(r"(\w+(?:Dto|Request|Input|Command))")
        match = dto_pattern.search(params)
        if match:
            return match.group(1)

        return None

    def _extract_models(
        self,
        content: str,
        file_path: Path,
    ) -> List[ModelDefinition]:
        """
        Extract DTOs and entities from NestJS.

        Patterns:
            export class CreateUserDto {
                @IsString()
                name: string;

                @IsEmail()
                email: string;
            }

            export class User {
                id: number;
                name: string;
            }
        """
        models: List[ModelDefinition] = []

        # Pattern for class definition
        class_pattern = re.compile(
            r"export\s+class\s+(\w+)(?:\s+extends\s+\w+)?\s*\{",
            re.MULTILINE,
        )

        # Pattern for class properties
        # @IsString() name: string;
        # name: string;
        # readonly id: number;
        property_pattern = re.compile(
            r"(?:@\w+\([^)]*\)\s*)*(?:readonly\s+)?(\w+)\s*(\?)?\s*:\s*([^;=\n]+)",
        )

        for class_match in class_pattern.finditer(content):
            class_name = class_match.group(1)

            # Skip common non-model classes
            if self._should_skip_class(class_name):
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

            fields: List[FieldDefinition] = []

            for prop_match in property_pattern.finditer(class_body):
                prop_name = prop_match.group(1)
                is_optional = prop_match.group(2) == "?"
                prop_type = prop_match.group(3).strip()

                # Skip methods and constructor
                if prop_name in ["constructor"] or "(" in prop_type:
                    continue

                # Skip decorators captured as property names
                if prop_name.startswith("@"):
                    continue

                is_array = prop_type.endswith("[]") or prop_type.startswith("Array<")

                fields.append(FieldDefinition(
                    name=prop_name,
                    type_name=self._clean_type(prop_type),
                    is_optional=is_optional,
                    is_array=is_array,
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

    def _should_skip_class(self, class_name: str) -> bool:
        """Check if class should be skipped (not a model)."""
        skip_suffixes = [
            "Controller", "Service", "Module", "Guard",
            "Interceptor", "Filter", "Pipe", "Middleware",
            "Gateway", "Resolver", "Factory", "Provider",
            "Strategy", "Subscriber", "Listener",
        ]
        return any(class_name.endswith(suffix) for suffix in skip_suffixes)

    def _extract_enums(
        self,
        content: str,
        file_path: Path,
    ) -> List[EnumDefinition]:
        """Extract TypeScript enums."""
        enums: List[EnumDefinition] = []

        enum_pattern = re.compile(
            r"export\s+enum\s+(\w+)\s*\{([^}]+)\}",
            re.MULTILINE,
        )

        for enum_match in enum_pattern.finditer(content):
            enum_name = enum_match.group(1)
            enum_body = enum_match.group(2)

            values: List[str] = []
            value_pattern = re.compile(r"(\w+)\s*(?:=\s*[^,]+)?")

            for value_match in value_pattern.finditer(enum_body):
                value = value_match.group(1)
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

    def _clean_type(self, type_str: str) -> str:
        """Clean TypeScript type to contract type."""
        if not type_str:
            return "any"

        type_str = type_str.strip()

        # Remove Promise wrapper
        promise_match = re.match(r"Promise<(.+)>", type_str)
        if promise_match:
            return self._clean_type(promise_match.group(1))

        # Remove Observable wrapper
        obs_match = re.match(r"Observable<(.+)>", type_str)
        if obs_match:
            return self._clean_type(obs_match.group(1))

        # Remove Array<T> wrapper
        array_match = re.match(r"Array<(.+)>", type_str)
        if array_match:
            return self._clean_type(array_match.group(1))

        # Remove [] suffix
        if type_str.endswith("[]"):
            return self._clean_type(type_str[:-2])

        # Remove null/undefined unions
        type_str = re.sub(r"\s*\|\s*(?:null|undefined)", "", type_str)

        # Map TypeScript types
        type_mapping = {
            "string": "string",
            "number": "float",
            "boolean": "bool",
            "Date": "datetime",
            "any": "any",
            "void": "void",
            "never": "void",
            "unknown": "any",
            "object": "object",
            "Buffer": "bytes",
        }

        return type_mapping.get(type_str, type_str)
