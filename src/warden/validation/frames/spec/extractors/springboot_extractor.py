"""
Spring Boot Contract Extractor.

Extracts API contracts from Spring Boot projects (Java/Kotlin) by analyzing:
1. @RestController, @Controller classes
2. @RequestMapping, @GetMapping, @PostMapping, etc.
3. @RequestBody, @PathVariable, @RequestParam annotations
4. ResponseEntity<T>, Mono<T>, Flux<T> return types
5. DTO classes, records, data classes
6. Enums

Supported Patterns:
- Java: @GetMapping("/users"), @PostMapping, etc.
- Kotlin: @GetMapping("/users"), data class UserDto(...)
- Both: @RequestBody, @PathVariable, @RequestParam

Author: Warden Team
Version: 1.0.0
"""

import re
from pathlib import Path
from typing import List, Optional, Set, Dict

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
class SpringBootExtractor(BaseContractExtractor):
    """
    Extracts API contracts from Spring Boot projects.

    Supports both Java and Kotlin source files.
    Scans for:
    - *Controller.java/kt files
    - **/controller/**/*.java/kt
    - DTO/Model classes
    """

    platform_type = PlatformType.SPRING_BOOT
    supported_languages = [CodeLanguage.JAVA, CodeLanguage.KOTLIN]
    file_patterns = [
        "**/*Controller.java",
        "**/*Controller.kt",
        "**/controller/**/*.java",
        "**/controller/**/*.kt",
        "**/controllers/**/*.java",
        "**/controllers/**/*.kt",
        "**/api/**/*.java",
        "**/api/**/*.kt",
        "**/dto/**/*.java",
        "**/dto/**/*.kt",
        "**/model/**/*.java",
        "**/model/**/*.kt",
        "**/entity/**/*.java",
        "**/entity/**/*.kt",
    ]

    # HTTP mapping annotations
    HTTP_MAPPINGS = {
        "GetMapping": OperationType.QUERY,
        "PostMapping": OperationType.COMMAND,
        "PutMapping": OperationType.COMMAND,
        "PatchMapping": OperationType.COMMAND,
        "DeleteMapping": OperationType.COMMAND,
        "RequestMapping": OperationType.QUERY,  # Default, method determines actual
    }

    async def extract(self) -> Contract:
        """
        Extract contract from Spring Boot project.

        Returns:
            Contract with operations and models
        """
        logger.info(
            "springboot_extraction_started",
            project_root=str(self.project_root),
        )

        contract = Contract(
            name="springboot-provider",
            extracted_from=self.platform_type.value,
        )

        files = self._find_files()
        logger.info("springboot_files_found", count=len(files))

        seen_operations: Set[str] = set()
        seen_models: Set[str] = set()

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")
                is_kotlin = file_path.suffix == ".kt"

                # Check if it's a controller
                if self._is_controller(content):
                    # Extract controller-level request mapping
                    base_path = self._extract_base_path(content)

                    # Extract operations
                    operations = self._extract_operations(
                        content, file_path, base_path, is_kotlin
                    )
                    for op in operations:
                        if op.name not in seen_operations:
                            contract.operations.append(op)
                            seen_operations.add(op.name)

                # Extract models
                models = self._extract_models(content, file_path, is_kotlin)
                for model in models:
                    if model.name not in seen_models:
                        contract.models.append(model)
                        seen_models.add(model.name)

                # Extract enums
                enums = self._extract_enums(content, file_path, is_kotlin)
                for enum in enums:
                    if enum.name not in seen_models:
                        contract.enums.append(enum)
                        seen_models.add(enum.name)

            except Exception as e:
                logger.warning(
                    "springboot_file_extraction_error",
                    file=str(file_path),
                    error=str(e),
                )

        logger.info(
            "springboot_extraction_completed",
            operations=len(contract.operations),
            models=len(contract.models),
            enums=len(contract.enums),
        )

        return contract

    def _is_controller(self, content: str) -> bool:
        """Check if file contains a Spring controller."""
        return (
            "@RestController" in content
            or "@Controller" in content
            or "RestController" in content
        )

    def _extract_base_path(self, content: str) -> str:
        """Extract base path from class-level @RequestMapping."""
        # @RequestMapping("/api/users") or @RequestMapping(value = "/api/users")
        patterns = [
            r'@RequestMapping\s*\(\s*"([^"]+)"',
            r'@RequestMapping\s*\(\s*value\s*=\s*"([^"]+)"',
            r'@RequestMapping\s*\(\s*path\s*=\s*"([^"]+)"',
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1)

        return ""

    def _extract_operations(
        self,
        content: str,
        file_path: Path,
        base_path: str,
        is_kotlin: bool,
    ) -> List[OperationDefinition]:
        """
        Extract operations from Spring mapping annotations.

        Patterns (Java):
            @GetMapping("/users")
            public ResponseEntity<List<User>> getUsers() { ... }

            @PostMapping
            public User createUser(@RequestBody CreateUserRequest request) { ... }

        Patterns (Kotlin):
            @GetMapping("/users")
            fun getUsers(): ResponseEntity<List<User>> { ... }

            @PostMapping
            fun createUser(@RequestBody request: CreateUserRequest): User { ... }
        """
        operations: List[OperationDefinition] = []

        # Pattern for mapping annotations
        # @GetMapping, @GetMapping("/path"), @GetMapping(value = "/path")
        mapping_pattern = re.compile(
            r'@(Get|Post|Put|Patch|Delete|Request)Mapping(?:\s*\(\s*(?:value\s*=\s*)?(?:"([^"]*)")?)?[^)]*\)?',
            re.IGNORECASE,
        )

        # Pattern for Java method
        java_method_pattern = re.compile(
            r"public\s+(?:ResponseEntity<)?([^>(\s]+)(?:>)?\s+(\w+)\s*\(([^)]*)\)",
            re.MULTILINE,
        )

        # Pattern for Kotlin function
        kotlin_method_pattern = re.compile(
            r"fun\s+(\w+)\s*\(([^)]*)\)\s*:\s*(?:ResponseEntity<)?([^>{\s]+)(?:>)?",
            re.MULTILINE,
        )

        lines = content.split("\n")

        for i, line in enumerate(lines):
            mapping_match = mapping_pattern.search(line)
            if mapping_match:
                http_method = mapping_match.group(1)
                action_path = mapping_match.group(2) or ""

                # Search for method in next lines
                search_range = "\n".join(lines[i : i + 15])

                if is_kotlin:
                    method_match = kotlin_method_pattern.search(search_range)
                    if method_match:
                        method_name = method_match.group(1)
                        params = method_match.group(2)
                        return_type = method_match.group(3)
                else:
                    method_match = java_method_pattern.search(search_range)
                    if method_match:
                        return_type = method_match.group(1)
                        method_name = method_match.group(2)
                        params = method_match.group(3)

                if method_match:
                    # Build full path
                    full_path = self._build_path(base_path, action_path)

                    # Extract input type from @RequestBody
                    input_type = self._extract_request_body(params, is_kotlin)

                    # Clean return type
                    output_type = self._clean_type(return_type)

                    # Determine operation type
                    mapping_key = f"{http_method}Mapping"
                    op_type = self.HTTP_MAPPINGS.get(mapping_key, OperationType.QUERY)

                    operations.append(OperationDefinition(
                        name=method_name,
                        operation_type=op_type,
                        input_type=input_type,
                        output_type=output_type,
                        description=f"{http_method.upper()} {full_path}",
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
        return "/" + "/".join(parts) if parts else "/"

    def _extract_request_body(self, params: str, is_kotlin: bool) -> Optional[str]:
        """Extract type from @RequestBody parameter."""
        if is_kotlin:
            # @RequestBody request: CreateUserRequest
            pattern = re.compile(r"@RequestBody\s+\w+\s*:\s*(\w+)")
        else:
            # @RequestBody CreateUserRequest request
            pattern = re.compile(r"@RequestBody\s+(\w+)")

        match = pattern.search(params)
        if match:
            return match.group(1)

        # Look for DTO/Request type without explicit @RequestBody
        dto_pattern = re.compile(r"(\w+(?:Dto|Request|Command|Input))")
        match = dto_pattern.search(params)
        if match:
            return match.group(1)

        return None

    def _extract_models(
        self,
        content: str,
        file_path: Path,
        is_kotlin: bool,
    ) -> List[ModelDefinition]:
        """
        Extract models from Java classes or Kotlin data classes.

        Java:
            public class UserDto {
                private String name;
                private String email;
            }

        Kotlin:
            data class UserDto(
                val name: String,
                val email: String?
            )
        """
        models: List[ModelDefinition] = []

        if is_kotlin:
            models.extend(self._extract_kotlin_models(content, file_path))
        else:
            models.extend(self._extract_java_models(content, file_path))

        return models

    def _extract_java_models(
        self,
        content: str,
        file_path: Path,
    ) -> List[ModelDefinition]:
        """Extract models from Java classes."""
        models: List[ModelDefinition] = []

        # Pattern for Java class
        class_pattern = re.compile(
            r"public\s+(?:class|record)\s+(\w+)(?:\s+(?:extends|implements)[^{]*)?\s*[({]",
            re.MULTILINE,
        )

        # Pattern for private fields
        field_pattern = re.compile(
            r"private\s+(?:final\s+)?(\w+(?:<[^>]+>)?)\s+(\w+)\s*;",
        )

        # Pattern for record components
        record_pattern = re.compile(
            r"public\s+record\s+(\w+)\s*\(([^)]+)\)",
            re.MULTILINE,
        )

        # Handle records first
        for record_match in record_pattern.finditer(content):
            record_name = record_match.group(1)
            components = record_match.group(2)

            # Skip common non-model types
            if self._should_skip_class(record_name):
                continue

            fields: List[FieldDefinition] = []
            for component in components.split(","):
                component = component.strip()
                parts = component.split()
                if len(parts) >= 2:
                    comp_type = parts[0]
                    comp_name = parts[1]
                    fields.append(FieldDefinition(
                        name=comp_name,
                        type_name=self._clean_type(comp_type),
                        is_optional=False,
                        is_array="List<" in comp_type or "[]" in comp_type,
                        source_file=str(file_path),
                    ))

            if fields:
                line_num = content[:record_match.start()].count("\n") + 1
                models.append(ModelDefinition(
                    name=record_name,
                    fields=fields,
                    source_file=str(file_path),
                    source_line=line_num,
                ))

        # Handle regular classes
        for class_match in class_pattern.finditer(content):
            class_name = class_match.group(1)

            if self._should_skip_class(class_name):
                continue

            # Skip if already processed as record
            if any(m.name == class_name for m in models):
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
            for field_match in field_pattern.finditer(class_body):
                field_type = field_match.group(1)
                field_name = field_match.group(2)

                fields.append(FieldDefinition(
                    name=field_name,
                    type_name=self._clean_type(field_type),
                    is_optional=False,  # Java doesn't have nullable syntax
                    is_array="List<" in field_type or "[]" in field_type,
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

    def _extract_kotlin_models(
        self,
        content: str,
        file_path: Path,
    ) -> List[ModelDefinition]:
        """Extract models from Kotlin data classes."""
        models: List[ModelDefinition] = []

        # Pattern for Kotlin data class
        data_class_pattern = re.compile(
            r"data\s+class\s+(\w+)\s*\(([^)]+)\)",
            re.MULTILINE | re.DOTALL,
        )

        for class_match in data_class_pattern.finditer(content):
            class_name = class_match.group(1)
            params = class_match.group(2)

            if self._should_skip_class(class_name):
                continue

            fields: List[FieldDefinition] = []

            # Parse constructor parameters
            # val name: String, val email: String?
            param_pattern = re.compile(
                r"(?:val|var)\s+(\w+)\s*:\s*([^,)]+)",
            )

            for param_match in param_pattern.finditer(params):
                param_name = param_match.group(1)
                param_type = param_match.group(2).strip()

                is_optional = param_type.endswith("?") or "= null" in param_type
                is_array = param_type.startswith("List<")

                fields.append(FieldDefinition(
                    name=param_name,
                    type_name=self._clean_type(param_type.rstrip("?")),
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
            "Controller", "Service", "Repository", "Mapper",
            "Handler", "Interceptor", "Filter", "Advice",
            "Config", "Configuration", "Application", "Test",
            "Exception", "Error", "Builder", "Factory",
        ]
        return any(class_name.endswith(suffix) for suffix in skip_suffixes)

    def _extract_enums(
        self,
        content: str,
        file_path: Path,
        is_kotlin: bool,
    ) -> List[EnumDefinition]:
        """Extract enums from Java/Kotlin code."""
        enums: List[EnumDefinition] = []

        if is_kotlin:
            # Kotlin enum: enum class Status { ACTIVE, INACTIVE }
            enum_pattern = re.compile(
                r"enum\s+class\s+(\w+)(?:\s*\([^)]*\))?\s*\{([^}]+)\}",
                re.MULTILINE,
            )
        else:
            # Java enum: public enum Status { ACTIVE, INACTIVE }
            enum_pattern = re.compile(
                r"public\s+enum\s+(\w+)\s*\{([^}]+)\}",
                re.MULTILINE,
            )

        for enum_match in enum_pattern.finditer(content):
            enum_name = enum_match.group(1)
            enum_body = enum_match.group(2)

            # Extract values (before any semicolon for complex enums)
            values_part = enum_body.split(";")[0]

            values: List[str] = []
            value_pattern = re.compile(r"(\w+)(?:\s*\([^)]*\))?")

            for value_match in value_pattern.finditer(values_part):
                value = value_match.group(1)
                if value and not value.startswith("//") and value.isupper():
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
        """Clean Java/Kotlin type to contract type."""
        if not type_str:
            return "any"

        type_str = type_str.strip()

        # Remove Kotlin nullable marker
        type_str = type_str.rstrip("?")

        # Remove List<> wrapper
        list_match = re.match(r"List<(.+)>", type_str)
        if list_match:
            return self._clean_type(list_match.group(1))

        # Remove array notation
        type_str = type_str.rstrip("[]")

        # Remove ResponseEntity wrapper
        resp_match = re.match(r"ResponseEntity<(.+)>", type_str)
        if resp_match:
            return self._clean_type(resp_match.group(1))

        # Remove Mono/Flux (reactive)
        reactive_match = re.match(r"(?:Mono|Flux)<(.+)>", type_str)
        if reactive_match:
            return self._clean_type(reactive_match.group(1))

        # Remove Optional wrapper
        optional_match = re.match(r"Optional<(.+)>", type_str)
        if optional_match:
            return self._clean_type(optional_match.group(1))

        # Map Java/Kotlin types to contract primitives
        type_mapping = {
            "String": "string",
            "Integer": "int",
            "int": "int",
            "Long": "int",
            "long": "int",
            "Float": "float",
            "float": "float",
            "Double": "float",
            "double": "float",
            "BigDecimal": "decimal",
            "Boolean": "bool",
            "boolean": "bool",
            "LocalDateTime": "datetime",
            "ZonedDateTime": "datetime",
            "Instant": "datetime",
            "LocalDate": "date",
            "LocalTime": "time",
            "UUID": "string",
            "byte[]": "bytes",
            "ByteArray": "bytes",
            "Object": "any",
            "Any": "any",
            "void": "void",
            "Unit": "void",
        }

        return type_mapping.get(type_str, type_str)
