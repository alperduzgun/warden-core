"""
React/React Native Contract Extractor.

Extracts API contracts from React and React Native applications by analyzing:
1. fetch() calls
2. axios calls
3. React Query (useQuery, useMutation)
4. SWR hooks
5. Custom API hooks
6. TypeScript interfaces/types

Supported Patterns:
- fetch('/api/users', { method: 'POST' })
- axios.get<User[]>('/api/users')
- useQuery(['users'], () => fetchUsers())
- useMutation(createUser)

Author: Warden Team
Version: 1.0.0
"""

import re
from pathlib import Path

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
class ReactExtractor(BaseContractExtractor):
    """
    Extracts API contracts from React/React Native projects.

    Scans for:
    - src/**/*.ts, src/**/*.tsx
    - API calls, hooks, services
    - TypeScript interfaces
    """

    platform_type = PlatformType.REACT
    supported_languages = [CodeLanguage.TYPESCRIPT, CodeLanguage.TSX]
    file_patterns = [
        "src/**/*.ts",
        "src/**/*.tsx",
        "src/**/api/**/*.ts",
        "src/**/services/**/*.ts",
        "src/**/hooks/**/*.ts",
        "src/**/queries/**/*.ts",
        "src/**/types/**/*.ts",
        "app/**/*.ts",
        "app/**/*.tsx",
    ]

    HTTP_METHODS = {
        "get": OperationType.QUERY,
        "post": OperationType.COMMAND,
        "put": OperationType.COMMAND,
        "patch": OperationType.COMMAND,
        "delete": OperationType.COMMAND,
    }

    async def extract(self) -> Contract:
        """Extract contract from React project."""
        logger.info(
            "react_extraction_started",
            project_root=str(self.project_root),
        )

        contract = Contract(
            name="react-consumer",
            extracted_from=self.platform_type.value,
        )

        files = self._find_files()
        logger.info("react_files_found", count=len(files))

        seen_operations: set[str] = set()
        seen_models: set[str] = set()

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")

                # Extract API operations
                operations = self._extract_operations(content, file_path)
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
                    "react_file_extraction_error",
                    file=str(file_path),
                    error=str(e),
                )

        logger.info(
            "react_extraction_completed",
            operations=len(contract.operations),
            models=len(contract.models),
            enums=len(contract.enums),
        )

        return contract

    def _extract_operations(
        self,
        content: str,
        file_path: Path,
    ) -> list[OperationDefinition]:
        """Extract API operations from various patterns."""
        operations: list[OperationDefinition] = []

        # 1. Axios calls
        operations.extend(self._extract_axios_calls(content, file_path))

        # 2. Fetch calls
        operations.extend(self._extract_fetch_calls(content, file_path))

        # 3. React Query hooks
        operations.extend(self._extract_react_query(content, file_path))

        return operations

    def _extract_axios_calls(
        self,
        content: str,
        file_path: Path,
    ) -> list[OperationDefinition]:
        """Extract axios API calls."""
        operations: list[OperationDefinition] = []

        # axios.get<Type>('/path') or api.post('/path', data)
        axios_pattern = re.compile(
            r"(?:axios|api|client|http)\s*\.\s*(get|post|put|patch|delete)\s*(?:<([^>]+)>)?\s*\(\s*[`'\"]([^`'\"]+)[`'\"]",
            re.IGNORECASE,
        )

        lines = content.split("\n")
        for i, line in enumerate(lines):
            match = axios_pattern.search(line)
            if match:
                method = match.group(1).lower()
                response_type = match.group(2)
                path = match.group(3)

                func_name = self._find_enclosing_function(content, i)
                if not func_name:
                    func_name = self._path_to_operation_name(path, method)

                operations.append(
                    OperationDefinition(
                        name=func_name,
                        operation_type=self.HTTP_METHODS.get(method, OperationType.QUERY),
                        output_type=self._clean_type(response_type) if response_type else None,
                        description=f"{method.upper()} {path}",
                        source_file=str(file_path),
                        source_line=i + 1,
                    )
                )

        return operations

    def _extract_fetch_calls(
        self,
        content: str,
        file_path: Path,
    ) -> list[OperationDefinition]:
        """Extract fetch API calls."""
        operations: list[OperationDefinition] = []

        # fetch('/path', { method: 'POST' })
        fetch_pattern = re.compile(
            r"fetch\s*\(\s*[`'\"]([^`'\"]+)[`'\"](?:[^)]*method\s*:\s*['\"](\w+)['\"])?",
            re.IGNORECASE,
        )

        lines = content.split("\n")
        for i, line in enumerate(lines):
            match = fetch_pattern.search(line)
            if match:
                path = match.group(1)
                method = (match.group(2) or "get").lower()

                func_name = self._find_enclosing_function(content, i)
                if not func_name:
                    func_name = self._path_to_operation_name(path, method)

                operations.append(
                    OperationDefinition(
                        name=func_name,
                        operation_type=self.HTTP_METHODS.get(method, OperationType.QUERY),
                        description=f"{method.upper()} {path}",
                        source_file=str(file_path),
                        source_line=i + 1,
                    )
                )

        return operations

    def _extract_react_query(
        self,
        content: str,
        file_path: Path,
    ) -> list[OperationDefinition]:
        """Extract React Query / TanStack Query hooks."""
        operations: list[OperationDefinition] = []

        # useQuery<Type>(['key'], fetchFn)
        # useQuery({ queryKey: ['key'], queryFn: fetchFn })
        query_pattern = re.compile(
            r"use(?:Query|InfiniteQuery)\s*(?:<([^>]+)>)?\s*\(\s*(?:\[\s*['\"]([^'\"]+)['\"]|{\s*queryKey\s*:\s*\[\s*['\"]([^'\"]+)['\"])",
            re.IGNORECASE,
        )

        # useMutation<Type>
        mutation_pattern = re.compile(
            r"useMutation\s*(?:<([^>]+)>)?\s*\(",
            re.IGNORECASE,
        )

        lines = content.split("\n")
        for i, line in enumerate(lines):
            # Check useQuery
            query_match = query_pattern.search(line)
            if query_match:
                response_type = query_match.group(1)
                query_key = query_match.group(2) or query_match.group(3)

                func_name = self._find_enclosing_function(content, i)
                if not func_name and query_key:
                    func_name = f"get{query_key[0].upper()}{query_key[1:]}"

                if func_name:
                    operations.append(
                        OperationDefinition(
                            name=func_name,
                            operation_type=OperationType.QUERY,
                            output_type=self._clean_type(response_type) if response_type else None,
                            description=f"Query: {query_key}",
                            source_file=str(file_path),
                            source_line=i + 1,
                        )
                    )

            # Check useMutation
            mutation_match = mutation_pattern.search(line)
            if mutation_match:
                response_type = mutation_match.group(1)
                func_name = self._find_enclosing_function(content, i)

                if func_name:
                    operations.append(
                        OperationDefinition(
                            name=func_name,
                            operation_type=OperationType.COMMAND,
                            output_type=self._clean_type(response_type) if response_type else None,
                            description="Mutation",
                            source_file=str(file_path),
                            source_line=i + 1,
                        )
                    )

        return operations

    def _find_enclosing_function(self, content: str, line_index: int) -> str | None:
        """Find enclosing function name."""
        lines = content.split("\n")

        for i in range(line_index, -1, -1):
            line = lines[i]
            patterns = [
                r"(?:export\s+)?(?:async\s+)?function\s+(\w+)",
                r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(",
                r"(\w+)\s*[=:]\s*(?:async\s*)?\([^)]*\)\s*(?:=>|:)",
            ]
            for pattern in patterns:
                match = re.search(pattern, line)
                if match:
                    name = match.group(1)
                    if name not in ["useEffect", "useCallback", "useMemo", "useState"]:
                        return name
        return None

    def _extract_models(
        self,
        content: str,
        file_path: Path,
    ) -> list[ModelDefinition]:
        """Extract TypeScript interfaces and types."""
        models: list[ModelDefinition] = []

        # Interface pattern
        interface_pattern = re.compile(
            r"(?:export\s+)?interface\s+(\w+)(?:\s+extends\s+[^{]+)?\s*\{([^}]+)\}",
            re.MULTILINE | re.DOTALL,
        )

        # Type pattern
        type_pattern = re.compile(
            r"(?:export\s+)?type\s+(\w+)\s*=\s*\{([^}]+)\}",
            re.MULTILINE | re.DOTALL,
        )

        for match in interface_pattern.finditer(content):
            model = self._parse_model_body(
                match.group(1), match.group(2), file_path, content[: match.start()].count("\n") + 1
            )
            if model:
                models.append(model)

        for match in type_pattern.finditer(content):
            model = self._parse_model_body(
                match.group(1), match.group(2), file_path, content[: match.start()].count("\n") + 1
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
    ) -> ModelDefinition | None:
        """Parse interface/type body."""
        # Skip React-specific types
        skip_types = ["Props", "State", "Context", "FC", "Component"]
        if any(name.endswith(s) for s in skip_types):
            return None

        fields: list[FieldDefinition] = []
        field_pattern = re.compile(r"(\w+)\s*(\?)?\s*:\s*([^;,\n]+)")

        for match in field_pattern.finditer(body):
            field_name = match.group(1)
            is_optional = match.group(2) == "?"
            field_type = match.group(3).strip()

            fields.append(
                FieldDefinition(
                    name=field_name,
                    type_name=self._clean_type(field_type),
                    is_optional=is_optional,
                    is_array=field_type.endswith("[]") or "Array<" in field_type,
                    source_file=str(file_path),
                )
            )

        if fields:
            return ModelDefinition(
                name=name,
                fields=fields,
                source_file=str(file_path),
                source_line=line_num,
            )
        return None

    def _extract_enums(self, content: str, file_path: Path) -> list[EnumDefinition]:
        """Extract TypeScript enums."""
        enums: list[EnumDefinition] = []
        enum_pattern = re.compile(r"(?:export\s+)?enum\s+(\w+)\s*\{([^}]+)\}", re.MULTILINE)

        for match in enum_pattern.finditer(content):
            values = [v.strip().split("=")[0].strip() for v in match.group(2).split(",") if v.strip()]
            if values:
                enums.append(
                    EnumDefinition(
                        name=match.group(1),
                        values=values,
                        source_file=str(file_path),
                        source_line=content[: match.start()].count("\n") + 1,
                    )
                )
        return enums

    def _path_to_operation_name(self, path: str, method: str) -> str:
        """Convert API path to operation name."""
        path = re.sub(r"^\$\{[^}]+\}/?", "", path)
        path = re.sub(r"^/?(?:api/)?(?:v\d+/)?", "", path)
        parts = [p for p in path.split("/") if p and not p.startswith(":") and not p.startswith("{")]

        if not parts:
            return f"{method}Resource"

        resource = parts[-1]
        resource = re.sub(r"[-_](.)", lambda m: m.group(1).upper(), resource)
        prefix = {"get": "get", "post": "create", "put": "update", "patch": "update", "delete": "delete"}.get(
            method, method
        )

        return f"{prefix}{resource[0].upper()}{resource[1:]}" if resource else f"{prefix}Resource"

    def _clean_type(self, type_str: str) -> str:
        """Clean TypeScript type."""
        if not type_str:
            return "any"
        type_str = type_str.strip()

        # Unwrap common wrappers
        for wrapper in ["Promise<", "AxiosResponse<", "Array<"]:
            if type_str.startswith(wrapper) and type_str.endswith(">"):
                return self._clean_type(type_str[len(wrapper) : -1])

        if type_str.endswith("[]"):
            return self._clean_type(type_str[:-2])

        type_str = re.sub(r"\s*\|\s*(?:null|undefined)", "", type_str)

        mapping = {
            "string": "string",
            "number": "float",
            "boolean": "bool",
            "Date": "datetime",
            "any": "any",
            "void": "void",
        }
        return mapping.get(type_str, type_str)
