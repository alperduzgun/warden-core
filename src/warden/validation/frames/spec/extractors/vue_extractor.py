"""
Vue.js Contract Extractor.

Extracts API contracts from Vue.js applications by analyzing:
1. Axios calls (axios.get, axios.post, etc.)
2. Fetch API usage
3. Composables and API service files
4. TypeScript interfaces/types

Supported Patterns:
- Axios: axios.get<T>('/api/users'), this.$axios.post(...)
- Fetch: fetch('/api/users'), useFetch(...)
- Pinia stores with API calls
- Composables (useApi, useFetch patterns)

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
class VueExtractor(BaseContractExtractor):
    """
    Extracts API contracts from Vue.js projects.

    Scans for:
    - src/**/*.ts, src/**/*.vue
    - Composables, stores, services
    - Axios and fetch patterns
    """

    platform_type = PlatformType.VUE
    supported_languages = [CodeLanguage.TYPESCRIPT, CodeLanguage.JAVASCRIPT]
    file_patterns = [
        "src/**/*.ts",
        "src/**/*.vue",
        "src/**/api/**/*.ts",
        "src/**/services/**/*.ts",
        "src/**/composables/**/*.ts",
        "src/**/stores/**/*.ts",
        "src/**/types/**/*.ts",
        "src/**/models/**/*.ts",
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
        Extract contract from Vue.js project.

        Returns:
            Contract with operations and models
        """
        logger.info(
            "vue_extraction_started",
            project_root=str(self.project_root),
        )

        contract = Contract(
            name="vue-consumer",
            extracted_from=self.platform_type.value,
        )

        files = self._find_files()
        logger.info("vue_files_found", count=len(files))

        seen_operations: Set[str] = set()
        seen_models: Set[str] = set()

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")

                # For .vue files, extract script content
                if file_path.suffix == ".vue":
                    content = self._extract_script_content(content)

                # Extract axios/fetch operations
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
                    "vue_file_extraction_error",
                    file=str(file_path),
                    error=str(e),
                )

        logger.info(
            "vue_extraction_completed",
            operations=len(contract.operations),
            models=len(contract.models),
            enums=len(contract.enums),
        )

        return contract

    def _extract_script_content(self, vue_content: str) -> str:
        """Extract <script> content from .vue file."""
        # Match <script setup lang="ts"> or <script lang="ts">
        script_pattern = re.compile(
            r"<script[^>]*>(.+?)</script>",
            re.DOTALL | re.IGNORECASE,
        )
        match = script_pattern.search(vue_content)
        if match:
            return match.group(1)
        return ""

    def _extract_http_operations(
        self,
        content: str,
        file_path: Path,
    ) -> List[OperationDefinition]:
        """
        Extract operations from axios/fetch calls.

        Patterns:
            axios.get<User[]>('/api/users')
            axios.post('/api/users', userData)
            await $fetch<User>('/api/users')
            useFetch('/api/users')
        """
        operations: List[OperationDefinition] = []

        # Pattern for axios calls
        # axios.get<Type>('/path') or api.post('/path', data)
        axios_pattern = re.compile(
            r"(?:axios|api|\$axios|this\.\$axios|http)\s*\.\s*(get|post|put|patch|delete)\s*(?:<([^>]+)>)?\s*\(\s*[`'\"]([^`'\"]+)[`'\"]",
            re.IGNORECASE,
        )

        # Pattern for $fetch (Nuxt 3)
        fetch_pattern = re.compile(
            r"(?:\$fetch|useFetch|useLazyFetch)\s*(?:<([^>]+)>)?\s*\(\s*[`'\"]([^`'\"]+)[`'\"](?:[^)]*method\s*:\s*['\"](\w+)['\"])?",
            re.IGNORECASE,
        )

        # Pattern for native fetch
        native_fetch_pattern = re.compile(
            r"fetch\s*\(\s*[`'\"]([^`'\"]+)[`'\"](?:[^)]*method\s*:\s*['\"](\w+)['\"])?",
            re.IGNORECASE,
        )

        lines = content.split("\n")

        for i, line in enumerate(lines):
            # Check axios pattern
            axios_match = axios_pattern.search(line)
            if axios_match:
                http_method = axios_match.group(1).lower()
                response_type = axios_match.group(2)
                path = axios_match.group(3)

                method_name = self._find_enclosing_function(content, i)
                if not method_name:
                    method_name = self._path_to_operation_name(path, http_method)

                input_type = self._extract_request_body(line, http_method)

                operations.append(OperationDefinition(
                    name=method_name,
                    operation_type=self.HTTP_METHODS.get(http_method, OperationType.QUERY),
                    input_type=input_type,
                    output_type=self._clean_type(response_type) if response_type else None,
                    description=f"{http_method.upper()} {path}",
                    source_file=str(file_path),
                    source_line=i + 1,
                ))
                continue

            # Check $fetch pattern
            fetch_match = fetch_pattern.search(line)
            if fetch_match:
                response_type = fetch_match.group(1)
                path = fetch_match.group(2)
                http_method = (fetch_match.group(3) or "get").lower()

                method_name = self._find_enclosing_function(content, i)
                if not method_name:
                    method_name = self._path_to_operation_name(path, http_method)

                operations.append(OperationDefinition(
                    name=method_name,
                    operation_type=self.HTTP_METHODS.get(http_method, OperationType.QUERY),
                    input_type=None,
                    output_type=self._clean_type(response_type) if response_type else None,
                    description=f"{http_method.upper()} {path}",
                    source_file=str(file_path),
                    source_line=i + 1,
                ))
                continue

            # Check native fetch pattern
            native_match = native_fetch_pattern.search(line)
            if native_match:
                path = native_match.group(1)
                http_method = (native_match.group(2) or "get").lower()

                method_name = self._find_enclosing_function(content, i)
                if not method_name:
                    method_name = self._path_to_operation_name(path, http_method)

                operations.append(OperationDefinition(
                    name=method_name,
                    operation_type=self.HTTP_METHODS.get(http_method, OperationType.QUERY),
                    description=f"{http_method.upper()} {path}",
                    source_file=str(file_path),
                    source_line=i + 1,
                ))

        return operations

    def _find_enclosing_function(self, content: str, line_index: int) -> Optional[str]:
        """Find the function/method name that contains the given line."""
        lines = content.split("\n")

        # Search backwards for function definition
        for i in range(line_index, -1, -1):
            line = lines[i]
            # Match various function patterns
            patterns = [
                r"(?:export\s+)?(?:async\s+)?function\s+(\w+)",  # function name()
                r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(",  # const name = () =>
                r"(\w+)\s*(?::\s*[^=]+)?\s*=\s*(?:async\s*)?\(",  # name = () =>
                r"(?:async\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*[^{]+)?\s*\{",  # method name()
            ]
            for pattern in patterns:
                match = re.search(pattern, line)
                if match:
                    func_name = match.group(1)
                    # Skip common non-API functions
                    if func_name not in ["setup", "onMounted", "onUnmounted", "watch", "computed"]:
                        return func_name

        return None

    def _extract_request_body(self, line: str, method: str) -> Optional[str]:
        """Extract request body type from POST/PUT/PATCH."""
        if method not in ["post", "put", "patch"]:
            return None

        # Look for second argument: axios.post('/path', data)
        body_pattern = re.compile(r",\s*(\w+)\s*[,)]")
        match = body_pattern.search(line)
        if match:
            var_name = match.group(1)
            if var_name not in ["null", "undefined", "config", "options"]:
                return var_name[0].upper() + var_name[1:] if var_name[0].islower() else var_name

        return None

    def _extract_models(
        self,
        content: str,
        file_path: Path,
    ) -> List[ModelDefinition]:
        """Extract TypeScript interfaces and types."""
        models: List[ModelDefinition] = []

        # Pattern for interfaces
        interface_pattern = re.compile(
            r"(?:export\s+)?interface\s+(\w+)(?:\s+extends\s+[^{]+)?\s*\{([^}]+)\}",
            re.MULTILINE | re.DOTALL,
        )

        # Pattern for type aliases
        type_pattern = re.compile(
            r"(?:export\s+)?type\s+(\w+)\s*=\s*\{([^}]+)\}",
            re.MULTILINE | re.DOTALL,
        )

        for match in interface_pattern.finditer(content):
            model = self._parse_model_body(
                match.group(1),
                match.group(2),
                file_path,
                content[:match.start()].count("\n") + 1,
            )
            if model:
                models.append(model)

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
        # Skip Vue/common types
        skip_types = [
            "Ref", "ComputedRef", "Component", "Plugin",
            "RouteLocationNormalized", "Router",
        ]
        if name in skip_types:
            return None

        fields: List[FieldDefinition] = []

        # Pattern for field
        field_pattern = re.compile(r"(\w+)\s*(\?)?\s*:\s*([^;,\n]+)")

        for field_match in field_pattern.finditer(body):
            field_name = field_match.group(1)
            is_optional = field_match.group(2) == "?"
            field_type = field_match.group(3).strip()

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

        enum_pattern = re.compile(
            r"(?:export\s+)?enum\s+(\w+)\s*\{([^}]+)\}",
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
        path = re.sub(r"^\$\{[^}]+\}/?", "", path)
        path = re.sub(r"^/?(?:api/)?(?:v\d+/)?", "", path)

        parts = [p for p in path.split("/") if p and not p.startswith("{") and not p.startswith(":")]

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

        # Remove Ref wrapper
        ref_match = re.match(r"Ref<(.+)>", type_str)
        if ref_match:
            return self._clean_type(ref_match.group(1))

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
