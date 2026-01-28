"""
Angular Contract Extractor.

Extracts API contracts from Angular applications by analyzing:
1. HttpClient calls (this.http.get, this.http.post, etc.)
2. Service classes (@Injectable)
3. Interface/Type definitions for request/response
4. Environment API URLs

Supported Patterns:
- HttpClient methods: get<T>, post<T>, put<T>, patch<T>, delete<T>
- Service injection patterns
- Observable<T> return types
- Interface models

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
class AngularExtractor(BaseContractExtractor):
    """
    Extracts API contracts from Angular projects.

    Scans for:
    - **/services/**/*.ts
    - **/api/**/*.ts
    - **/models/**/*.ts
    - HttpClient usage patterns
    """

    platform_type = PlatformType.ANGULAR
    supported_languages = [CodeLanguage.TYPESCRIPT]
    file_patterns = [
        "src/**/*.service.ts",
        "src/**/services/**/*.ts",
        "src/**/api/**/*.ts",
        "src/**/models/**/*.ts",
        "src/**/interfaces/**/*.ts",
        "src/**/types/**/*.ts",
    ]

    # HTTP methods
    HTTP_METHODS = {
        "get": OperationType.QUERY,
        "post": OperationType.COMMAND,
        "put": OperationType.COMMAND,
        "patch": OperationType.COMMAND,
        "delete": OperationType.COMMAND,
    }

    async def extract(self) -> Contract:
        """
        Extract contract from Angular project.

        Returns:
            Contract with operations and models
        """
        logger.info(
            "angular_extraction_started",
            project_root=str(self.project_root),
        )

        contract = Contract(
            name="angular-consumer",
            extracted_from=self.platform_type.value,
        )

        files = self._find_files()
        logger.info("angular_files_found", count=len(files))

        seen_operations: Set[str] = set()
        seen_models: Set[str] = set()

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")

                # Extract HttpClient operations
                if "HttpClient" in content or "http." in content.lower():
                    operations = self._extract_http_operations(content, file_path)
                    for op in operations:
                        if op.name not in seen_operations:
                            contract.operations.append(op)
                            seen_operations.add(op.name)

                # Extract interfaces/types
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
                    "angular_file_extraction_error",
                    file=str(file_path),
                    error=str(e),
                )

        logger.info(
            "angular_extraction_completed",
            operations=len(contract.operations),
            models=len(contract.models),
            enums=len(contract.enums),
        )

        return contract

    def _extract_http_operations(
        self,
        content: str,
        file_path: Path,
    ) -> List[OperationDefinition]:
        """
        Extract operations from HttpClient calls.

        Patterns:
            this.http.get<User[]>('/api/users')
            this.http.post<User>(`${this.apiUrl}/users`, userData)
            return this.httpClient.get<Response>(`${environment.apiUrl}/items`);
        """
        operations: List[OperationDefinition] = []

        # Pattern for HttpClient calls
        # this.http.get<Type>('path') or this.http.get<Type>(`${baseUrl}/path`)
        http_pattern = re.compile(
            r"(?:this\.)?(?:http|httpClient)\s*\.\s*(get|post|put|patch|delete)\s*<([^>]+)>\s*\(\s*(?:[`'\"]([^`'\"]+)[`'\"]|`\$\{[^}]+\}([^`]+)`)",
            re.IGNORECASE,
        )

        # Pattern for method containing the http call
        re.compile(
            r"(?:async\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*Observable<[^>]+>)?\s*\{",
            re.MULTILINE,
        )

        lines = content.split("\n")

        for i, line in enumerate(lines):
            http_match = http_pattern.search(line)
            if http_match:
                http_method = http_match.group(1).lower()
                response_type = http_match.group(2)
                path = http_match.group(3) or http_match.group(4) or ""

                # Find enclosing method name
                method_name = self._find_enclosing_method(content, i)
                if not method_name:
                    method_name = self._path_to_operation_name(path, http_method)

                # Extract request body type for POST/PUT/PATCH
                input_type = None
                if http_method in ["post", "put", "patch"]:
                    input_type = self._extract_request_body_type(line, content, i)

                operations.append(OperationDefinition(
                    name=method_name,
                    operation_type=self.HTTP_METHODS.get(http_method, OperationType.QUERY),
                    input_type=input_type,
                    output_type=self._clean_type(response_type),
                    description=f"{http_method.upper()} {path}",
                    source_file=str(file_path),
                    source_line=i + 1,
                ))

        return operations

    def _find_enclosing_method(self, content: str, line_index: int) -> Optional[str]:
        """Find the method name that contains the given line."""
        lines = content.split("\n")

        # Search backwards for method definition
        for i in range(line_index, -1, -1):
            line = lines[i]
            # Match method definition patterns
            method_match = re.search(
                r"(?:public\s+|private\s+|protected\s+)?(?:async\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*Observable)?",
                line,
            )
            if method_match:
                method_name = method_match.group(1)
                # Skip constructor and lifecycle hooks
                if method_name not in ["constructor", "ngOnInit", "ngOnDestroy", "ngOnChanges"]:
                    return method_name

        return None

    def _extract_request_body_type(self, line: str, content: str, line_index: int) -> Optional[str]:
        """Extract request body type from POST/PUT/PATCH call."""
        # Look for second argument in http call
        # this.http.post<User>('/api/users', userData)
        # Pattern: , variableName) or , { ... })
        body_pattern = re.compile(r",\s*(\w+)\s*[,)]")
        match = body_pattern.search(line)
        if match:
            var_name = match.group(1)
            # Try to find variable type declaration
            type_pattern = re.compile(rf"{var_name}\s*:\s*(\w+)")
            type_match = type_pattern.search(content)
            if type_match:
                return type_match.group(1)
            # Use variable name as hint for type
            if var_name.endswith("Dto") or var_name.endswith("Request"):
                return var_name[0].upper() + var_name[1:]

        return None

    def _extract_models(
        self,
        content: str,
        file_path: Path,
    ) -> List[ModelDefinition]:
        """
        Extract interfaces and types from TypeScript.

        Patterns:
            export interface User {
                id: number;
                name: string;
            }

            export type CreateUserRequest = {
                name: string;
                email: string;
            }
        """
        models: List[ModelDefinition] = []

        # Pattern for interfaces
        interface_pattern = re.compile(
            r"export\s+interface\s+(\w+)(?:\s+extends\s+[^{]+)?\s*\{([^}]+)\}",
            re.MULTILINE | re.DOTALL,
        )

        # Pattern for type aliases
        type_pattern = re.compile(
            r"export\s+type\s+(\w+)\s*=\s*\{([^}]+)\}",
            re.MULTILINE | re.DOTALL,
        )

        # Process interfaces
        for match in interface_pattern.finditer(content):
            model = self._parse_model_body(
                match.group(1),
                match.group(2),
                file_path,
                content[:match.start()].count("\n") + 1,
            )
            if model:
                models.append(model)

        # Process type aliases
        for match in type_pattern.finditer(content):
            model = self._parse_model_body(
                match.group(1),
                match.group(2),
                file_path,
                content[:match.start()].count("\n") + 1,
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
        """Parse interface/type body to extract fields."""
        # Skip common non-model types
        if name in ["Observable", "HttpHeaders", "HttpParams", "HttpErrorResponse"]:
            return None

        fields: List[FieldDefinition] = []

        # Pattern for field: name: type; or name?: type;
        field_pattern = re.compile(
            r"(\w+)\s*(\?)?\s*:\s*([^;,\n]+)",
        )

        for field_match in field_pattern.finditer(body):
            field_name = field_match.group(1)
            is_optional = field_match.group(2) == "?"
            field_type = field_match.group(3).strip()

            # Determine if array
            is_array = field_type.endswith("[]") or field_type.startswith("Array<")

            fields.append(FieldDefinition(
                name=field_name,
                type_name=self._clean_type(field_type),
                is_optional=is_optional,
                is_array=is_array,
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

    def _extract_enums(
        self,
        content: str,
        file_path: Path,
    ) -> List[EnumDefinition]:
        """Extract TypeScript enums."""
        enums: List[EnumDefinition] = []

        # Pattern for enum
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

    def _path_to_operation_name(self, path: str, method: str) -> str:
        """Convert API path to operation name."""
        # Remove base URL patterns
        path = re.sub(r"^\$\{[^}]+\}/?", "", path)
        path = re.sub(r"^/?(?:api/)?(?:v\d+/)?", "", path)

        # Split and get resource
        parts = [p for p in path.split("/") if p and not p.startswith("{")]

        if not parts:
            return f"{method}Resource"

        resource = parts[-1]
        resource = re.sub(r"[-_](.)", lambda m: m.group(1).upper(), resource)

        method_prefix = {
            "get": "get",
            "post": "create",
            "put": "update",
            "patch": "update",
            "delete": "delete",
        }

        prefix = method_prefix.get(method, method)
        resource = resource[0].upper() + resource[1:] if resource else "Resource"

        return f"{prefix}{resource}"

    def _clean_type(self, type_str: str) -> str:
        """Clean TypeScript type to contract type."""
        if not type_str:
            return "any"

        type_str = type_str.strip()

        # Remove Observable wrapper
        obs_match = re.match(r"Observable<(.+)>", type_str)
        if obs_match:
            return self._clean_type(obs_match.group(1))

        # Remove Promise wrapper
        promise_match = re.match(r"Promise<(.+)>", type_str)
        if promise_match:
            return self._clean_type(promise_match.group(1))

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
        }

        return type_mapping.get(type_str, type_str)
