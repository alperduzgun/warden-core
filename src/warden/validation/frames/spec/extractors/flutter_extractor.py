"""
Flutter/Dart Contract Extractor.

Extracts API contracts from Flutter mobile applications by analyzing:
1. Retrofit-style annotated API classes (@GET, @POST, @PUT, @DELETE)
2. Dio HTTP client calls
3. http package calls
4. Data models (freezed, json_serializable, plain classes)

Supported Patterns:
- Retrofit annotations: @GET('/api/users'), @POST('/api/users')
- Dio calls: dio.get('/api/users'), dio.post('/api/users', data: ...)
- http calls: http.get(Uri.parse('...')), http.post(...)
- Model classes with fromJson/toJson

Author: Warden Team
Version: 1.0.0
"""

import re
from pathlib import Path
from typing import List, Optional, Set, Dict, Any

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
class FlutterExtractor(BaseContractExtractor):
    """
    Extracts API contracts from Flutter/Dart projects.

    Scans for:
    - lib/**/*.dart files
    - Retrofit-style API definitions
    - Dio/http HTTP calls
    - Data model classes
    """

    platform_type = PlatformType.FLUTTER
    supported_languages = [CodeLanguage.DART]
    file_patterns = [
        "lib/**/*.dart",
        "lib/**/*_api.dart",
        "lib/**/*_service.dart",
        "lib/**/*_client.dart",
        "lib/**/*_repository.dart",
        "lib/**/models/**/*.dart",
        "lib/**/entities/**/*.dart",
    ]

    # Retrofit HTTP method annotations
    RETROFIT_ANNOTATIONS = {
        "GET": OperationType.QUERY,
        "POST": OperationType.COMMAND,
        "PUT": OperationType.COMMAND,
        "PATCH": OperationType.COMMAND,
        "DELETE": OperationType.COMMAND,
    }

    # Dio/http method patterns
    HTTP_METHODS = {
        "get": OperationType.QUERY,
        "post": OperationType.COMMAND,
        "put": OperationType.COMMAND,
        "patch": OperationType.COMMAND,
        "delete": OperationType.COMMAND,
    }

    async def extract(self) -> Contract:
        """
        Extract contract from Flutter project.

        Returns:
            Contract with operations and models
        """
        logger.info(
            "flutter_extraction_started",
            project_root=str(self.project_root),
        )

        contract = Contract(
            name="flutter-consumer",
            extracted_from=self.platform_type.value,
        )

        files = self._find_files()
        logger.info("flutter_files_found", count=len(files))

        # Track extracted items to avoid duplicates
        seen_operations: Set[str] = set()
        seen_models: Set[str] = set()

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")

                # Extract Retrofit-style annotations
                retrofit_ops = self._extract_retrofit_operations(content, file_path)
                for op in retrofit_ops:
                    if op.name not in seen_operations:
                        contract.operations.append(op)
                        seen_operations.add(op.name)

                # Extract Dio/http calls
                http_ops = self._extract_http_operations(content, file_path)
                for op in http_ops:
                    if op.name not in seen_operations:
                        contract.operations.append(op)
                        seen_operations.add(op.name)

                # Extract data models
                models = self._extract_models(content, file_path)
                for model in models:
                    if model.name not in seen_models:
                        contract.models.append(model)
                        seen_models.add(model.name)

                # Extract enums
                enums = self._extract_enums(content, file_path)
                for enum in enums:
                    if enum.name not in seen_models:  # Use same set for uniqueness
                        contract.enums.append(enum)
                        seen_models.add(enum.name)

            except Exception as e:
                logger.warning(
                    "flutter_file_extraction_error",
                    file=str(file_path),
                    error=str(e),
                )

        logger.info(
            "flutter_extraction_completed",
            operations=len(contract.operations),
            models=len(contract.models),
            enums=len(contract.enums),
        )

        return contract

    def _extract_retrofit_operations(
        self,
        content: str,
        file_path: Path,
    ) -> List[OperationDefinition]:
        """
        Extract operations from Retrofit-style annotations.

        Patterns:
            @GET('/api/users')
            Future<List<User>> getUsers();

            @POST('/api/users')
            Future<User> createUser(@Body() CreateUserRequest request);
        """
        operations: List[OperationDefinition] = []

        # Pattern for Retrofit annotations
        # @GET('/path') or @GET("/path")
        annotation_pattern = re.compile(
            r"@(GET|POST|PUT|PATCH|DELETE)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
            re.IGNORECASE,
        )

        # Pattern for method following annotation
        # Future<ReturnType> methodName(params);
        method_pattern = re.compile(
            r"Future<([^>]+)>\s+(\w+)\s*\(([^)]*)\)\s*;",
            re.MULTILINE,
        )

        lines = content.split("\n")

        for i, line in enumerate(lines):
            # Check for Retrofit annotation
            ann_match = annotation_pattern.search(line)
            if ann_match:
                http_method = ann_match.group(1).upper()
                path = ann_match.group(2)

                # Look for method definition in next few lines
                search_range = "\n".join(lines[i : i + 5])
                method_match = method_pattern.search(search_range)

                if method_match:
                    return_type = method_match.group(1).strip()
                    method_name = method_match.group(2)
                    params = method_match.group(3).strip()

                    # Determine input type from @Body parameter
                    input_type = self._extract_body_param(params)

                    # Clean return type (remove List<>, handle generics)
                    output_type = self._clean_type(return_type)

                    operations.append(OperationDefinition(
                        name=method_name,
                        operation_type=self.RETROFIT_ANNOTATIONS.get(
                            http_method, OperationType.QUERY
                        ),
                        input_type=input_type,
                        output_type=output_type,
                        description=f"{http_method} {path}",
                        source_file=str(file_path),
                        source_line=i + 1,
                    ))

        return operations

    def _extract_http_operations(
        self,
        content: str,
        file_path: Path,
    ) -> List[OperationDefinition]:
        """
        Extract operations from Dio/http package calls.

        Patterns:
            dio.get('/api/users')
            dio.post('/api/users', data: userData)
            http.get(Uri.parse('$baseUrl/api/users'))
        """
        operations: List[OperationDefinition] = []

        # Pattern for dio calls
        # dio.get('/path'), dio.post('/path', data: ...)
        dio_pattern = re.compile(
            r"(?:dio|_dio|client|httpClient)\s*\.\s*(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]",
            re.IGNORECASE,
        )

        # Pattern for http package calls
        # http.get(Uri.parse('...'))
        http_pattern = re.compile(
            r"http\s*\.\s*(get|post|put|patch|delete)\s*\(\s*Uri\.parse\s*\(\s*['\"\$]([^'\"]+)",
            re.IGNORECASE,
        )

        lines = content.split("\n")

        for i, line in enumerate(lines):
            # Check for Dio calls
            dio_match = dio_pattern.search(line)
            if dio_match:
                method = dio_match.group(1).lower()
                path = dio_match.group(2)

                # Generate operation name from path
                op_name = self._path_to_operation_name(path, method)

                operations.append(OperationDefinition(
                    name=op_name,
                    operation_type=self.HTTP_METHODS.get(method, OperationType.QUERY),
                    description=f"{method.upper()} {path}",
                    source_file=str(file_path),
                    source_line=i + 1,
                ))

            # Check for http package calls
            http_match = http_pattern.search(line)
            if http_match:
                method = http_match.group(1).lower()
                path = http_match.group(2)

                # Clean path (remove baseUrl prefix, interpolation)
                path = re.sub(r"^\$\{?\w+\}?/?", "", path)

                op_name = self._path_to_operation_name(path, method)

                operations.append(OperationDefinition(
                    name=op_name,
                    operation_type=self.HTTP_METHODS.get(method, OperationType.QUERY),
                    description=f"{method.upper()} {path}",
                    source_file=str(file_path),
                    source_line=i + 1,
                ))

        return operations

    def _extract_models(
        self,
        content: str,
        file_path: Path,
    ) -> List[ModelDefinition]:
        """
        Extract data models from Dart classes.

        Patterns:
            class User { ... }
            @freezed class User with _$User { ... }
            @JsonSerializable() class User { ... }
        """
        models: List[ModelDefinition] = []

        # Pattern for class with fields
        # class ClassName { final Type field; ... }
        class_pattern = re.compile(
            r"(?:@\w+(?:\([^)]*\))?\s*)*class\s+(\w+)(?:\s+(?:with|extends|implements)\s+[^{]+)?\s*\{",
            re.MULTILINE,
        )

        # Pattern for class fields
        # final Type fieldName;
        # Type? fieldName;
        field_pattern = re.compile(
            r"(?:final\s+)?(\w+(?:<[^>]+>)?)\??\s+(\w+)\s*[;,]",
        )

        # Find all class definitions
        for class_match in class_pattern.finditer(content):
            class_name = class_match.group(1)

            # Skip internal/generated classes
            if class_name.startswith("_") or class_name.startswith("\$"):
                continue

            # Skip non-model classes (widgets, states, etc.)
            if any(suffix in class_name for suffix in [
                "Widget", "State", "Page", "Screen", "View",
                "Controller", "Bloc", "Cubit", "Provider",
            ]):
                continue

            # Find the class body
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

            # Extract fields
            fields: List[FieldDefinition] = []
            for field_match in field_pattern.finditer(class_body):
                field_type = field_match.group(1)
                field_name = field_match.group(2)

                # Skip common non-data fields
                if field_name in ["context", "key", "child", "children", "builder"]:
                    continue

                # Determine if optional
                is_optional = "?" in field_type or "?" in class_body[
                    field_match.start() : field_match.end()
                ]

                # Determine if array
                is_array = field_type.startswith("List<")

                # Clean type
                clean_type = self._clean_type(field_type)

                fields.append(FieldDefinition(
                    name=field_name,
                    type_name=clean_type,
                    is_optional=is_optional,
                    is_array=is_array,
                    source_file=str(file_path),
                ))

            # Only add if has fields (likely a data model)
            if fields:
                # Get line number
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
    ) -> List[EnumDefinition]:
        """
        Extract enums from Dart code.

        Pattern:
            enum Status { pending, active, completed }
        """
        enums: List[EnumDefinition] = []

        # Pattern for enum definition
        enum_pattern = re.compile(
            r"enum\s+(\w+)\s*\{([^}]+)\}",
            re.MULTILINE,
        )

        for enum_match in enum_pattern.finditer(content):
            enum_name = enum_match.group(1)
            enum_body = enum_match.group(2)

            # Extract enum values
            # Handle both simple (value,) and complex (value(1),) syntax
            values: List[str] = []
            value_pattern = re.compile(r"(\w+)(?:\([^)]*\))?\s*[,;]?")

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

    def _extract_body_param(self, params: str) -> Optional[str]:
        """Extract type from @Body() parameter."""
        # Pattern: @Body() TypeName paramName
        body_pattern = re.compile(r"@Body\(\)\s*(\w+)")
        match = body_pattern.search(params)
        if match:
            return match.group(1)
        return None

    def _clean_type(self, type_str: str) -> str:
        """Clean Dart type string to contract type."""
        # Remove List<> wrapper
        if type_str.startswith("List<") and type_str.endswith(">"):
            inner = type_str[5:-1]
            return self._clean_type(inner)

        # Remove nullable marker
        type_str = type_str.rstrip("?")

        # Map Dart types to contract primitives
        type_mapping = {
            "String": "string",
            "int": "int",
            "double": "float",
            "num": "float",
            "bool": "bool",
            "DateTime": "datetime",
            "Uint8List": "bytes",
            "dynamic": "any",
            "Object": "any",
            "void": "void",
        }

        return type_mapping.get(type_str, type_str)

    def _path_to_operation_name(self, path: str, method: str) -> str:
        """
        Convert API path to operation name.

        Examples:
            GET /api/users -> getUsers
            POST /api/users -> createUser
            GET /api/users/{id} -> getUserById
            DELETE /api/users/{id} -> deleteUser
        """
        # Remove leading slash and api prefix
        path = re.sub(r"^/?(?:api/)?(?:v\d+/)?", "", path)

        # Split path into parts
        parts = [p for p in path.split("/") if p and not p.startswith("{")]

        if not parts:
            return f"{method}Resource"

        # Get resource name (last non-param part)
        resource = parts[-1]

        # Convert to camelCase
        resource = re.sub(r"[-_](.)", lambda m: m.group(1).upper(), resource)

        # Singularize for single-item operations
        if resource.endswith("s") and method in ["get", "delete", "put", "patch"]:
            # Check if path has id parameter
            if "{" in path:
                resource = resource[:-1]  # Remove trailing 's'

        # Build operation name based on method
        method_prefix = {
            "get": "get",
            "post": "create",
            "put": "update",
            "patch": "update",
            "delete": "delete",
        }

        prefix = method_prefix.get(method, method)

        # Capitalize first letter of resource
        resource = resource[0].upper() + resource[1:] if resource else "Resource"

        # Add suffix for list operations
        if method == "get" and "{" not in path and not resource.endswith("s"):
            resource += "s"  # Pluralize for list

        return f"{prefix}{resource}"
