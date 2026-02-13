"""
FastAPI Contract Extractor.

Extracts API contracts from FastAPI Python projects by analyzing:
1. Route decorators (@app.get, @router.post, etc.)
2. Pydantic models (BaseModel subclasses)
3. Type hints on endpoint parameters and return types
4. Path/Query/Body parameter annotations

Supported Patterns:
- @app.get("/users"), @router.post("/users")
- async def endpoint(param: Type) -> ResponseType
- class UserModel(BaseModel): name: str
- Path(...), Query(...), Body(...) annotations

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
class FastAPIExtractor(BaseContractExtractor):
    """
    Extracts API contracts from FastAPI projects.

    Scans for:
    - main.py, app.py, api/**/*.py
    - Routes with @app.get, @router.post, etc.
    - Pydantic models
    """

    platform_type = PlatformType.FASTAPI
    supported_languages = [CodeLanguage.PYTHON]
    file_patterns = [
        "main.py",
        "app.py",
        "api.py",
        "**/api/**/*.py",
        "**/routers/**/*.py",
        "**/routes/**/*.py",
        "**/endpoints/**/*.py",
        "**/models/**/*.py",
        "**/schemas/**/*.py",
    ]

    # HTTP method decorators
    HTTP_DECORATORS = {
        "get": OperationType.QUERY,
        "post": OperationType.COMMAND,
        "put": OperationType.COMMAND,
        "patch": OperationType.COMMAND,
        "delete": OperationType.COMMAND,
    }

    async def extract(self) -> Contract:
        """
        Extract contract from FastAPI project.

        Returns:
            Contract with operations and models
        """
        logger.info(
            "fastapi_extraction_started",
            project_root=str(self.project_root),
        )

        contract = Contract(
            name="fastapi-provider",
            extracted_from=self.platform_type.value,
        )

        files = self._find_files()
        logger.info("fastapi_files_found", count=len(files))

        seen_operations: set[str] = set()
        seen_models: set[str] = set()

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")

                # Extract route operations
                operations = self._extract_operations(content, file_path)
                for op in operations:
                    if op.name not in seen_operations:
                        contract.operations.append(op)
                        seen_operations.add(op.name)

                # Extract Pydantic models
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
                    "fastapi_file_extraction_error",
                    file=str(file_path),
                    error=str(e),
                )

        logger.info(
            "fastapi_extraction_completed",
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
        """
        Extract operations from FastAPI route decorators.

        Patterns:
            @app.get("/users")
            async def get_users() -> List[User]:

            @router.post("/users", response_model=User)
            async def create_user(user: UserCreate) -> User:
        """
        operations: list[OperationDefinition] = []

        # Pattern for route decorators
        # @app.get("/path"), @router.post("/path", ...)
        decorator_pattern = re.compile(
            r"@(\w+)\.(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"](?:[^)]*response_model\s*=\s*(\w+))?[^)]*\)",
            re.IGNORECASE,
        )

        # Pattern for function definition
        # async def func_name(params) -> ReturnType:
        # def func_name(params) -> ReturnType:
        function_pattern = re.compile(
            r"(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)(?:\s*->\s*([^:]+))?\s*:",
            re.MULTILINE,
        )

        lines = content.split("\n")

        for i, line in enumerate(lines):
            dec_match = decorator_pattern.search(line)
            if dec_match:
                dec_match.group(1)  # app, router, etc.
                http_method = dec_match.group(2).lower()
                path = dec_match.group(3)
                response_model = dec_match.group(4)

                # Search for function in next lines
                search_range = "\n".join(lines[i + 1 : i + 10])
                func_match = function_pattern.search(search_range)

                if func_match:
                    func_name = func_match.group(1)
                    params = func_match.group(2)
                    return_type = func_match.group(3)

                    # Use response_model if specified, else return type
                    output_type = response_model or self._clean_type(return_type.strip() if return_type else "None")

                    # Extract input type from Body parameter
                    input_type = self._extract_body_param(params)

                    operations.append(
                        OperationDefinition(
                            name=func_name,
                            operation_type=self.HTTP_DECORATORS.get(http_method, OperationType.QUERY),
                            input_type=input_type,
                            output_type=output_type,
                            description=f"{http_method.upper()} {path}",
                            source_file=str(file_path),
                            source_line=i + 1,
                        )
                    )

        return operations

    def _extract_body_param(self, params: str) -> str | None:
        """Extract type from Body parameter or Pydantic model parameter."""
        # Pattern: param: TypeName or param: TypeName = Body(...)
        # Look for non-primitive types that are likely request bodies

        # Split parameters
        param_list = self._split_params(params)

        for param in param_list:
            # Skip common non-body params
            if any(
                skip in param.lower()
                for skip in [
                    "request:",
                    "response:",
                    "db:",
                    "session:",
                    "current_user",
                    "background",
                    "= depends",
                    "= query",
                    "= path",
                    "= header",
                    "= cookie",
                ]
            ):
                continue

            # Look for Body(...) annotation
            if "= body(" in param.lower():
                # param_name: Type = Body(...)
                type_match = re.search(r":\s*(\w+)", param)
                if type_match:
                    return type_match.group(1)

            # Look for Pydantic model type (capitalized, not primitive)
            type_match = re.search(r":\s*([A-Z]\w*(?:Create|Update|Request|Input)?)", param)
            if type_match:
                type_name = type_match.group(1)
                # Skip common non-body types
                if type_name not in ["Request", "Response", "HTTPException", "Depends"]:
                    return type_name

        return None

    def _split_params(self, params: str) -> list[str]:
        """Split function parameters handling nested brackets."""
        result = []
        current = ""
        bracket_count = 0

        for char in params:
            if char in "([{":
                bracket_count += 1
                current += char
            elif char in ")]}":
                bracket_count -= 1
                current += char
            elif char == "," and bracket_count == 0:
                if current.strip():
                    result.append(current.strip())
                current = ""
            else:
                current += char

        if current.strip():
            result.append(current.strip())

        return result

    def _extract_models(
        self,
        content: str,
        file_path: Path,
    ) -> list[ModelDefinition]:
        """
        Extract Pydantic models from Python code.

        Patterns:
            class UserModel(BaseModel):
                name: str
                email: Optional[str] = None
        """
        models: list[ModelDefinition] = []

        # Pattern for Pydantic model class
        class_pattern = re.compile(
            r"class\s+(\w+)\s*\(\s*(?:BaseModel|BaseSettings|BaseConfig)[^)]*\)\s*:",
            re.MULTILINE,
        )

        # Pattern for field definition
        # name: str
        # name: Optional[str] = None
        # name: str = Field(...)
        field_pattern = re.compile(
            r"^\s+(\w+)\s*:\s*([^=\n]+)(?:\s*=\s*[^,\n]+)?",
            re.MULTILINE,
        )

        for class_match in class_pattern.finditer(content):
            class_name = class_match.group(1)

            # Find class body (next class or end of indentation)
            start = class_match.end()

            # Find end of class (next class definition or end of file)
            next_class = re.search(r"\nclass\s+\w+", content[start:])
            if next_class:
                end = start + next_class.start()
            else:
                end = len(content)

            class_body = content[start:end]

            fields: list[FieldDefinition] = []

            for field_match in field_pattern.finditer(class_body):
                field_name = field_match.group(1)
                field_type = field_match.group(2).strip()

                # Skip private fields and methods
                if field_name.startswith("_") or field_name in ["model_config", "Config"]:
                    continue

                # Skip class variables (all caps)
                if field_name.isupper():
                    continue

                # Determine if optional
                is_optional = (
                    "Optional[" in field_type
                    or "| None" in field_type
                    or "None |" in field_type
                    or "= None" in class_body[field_match.start() : field_match.end() + 20]
                )

                # Determine if array
                is_array = field_type.startswith("List[") or field_type.startswith("list[") or "List[" in field_type

                # Clean type
                clean_type = self._clean_type(field_type)

                fields.append(
                    FieldDefinition(
                        name=field_name,
                        type_name=clean_type,
                        is_optional=is_optional,
                        is_array=is_array,
                        source_file=str(file_path),
                    )
                )

            if fields:
                line_num = content[: class_match.start()].count("\n") + 1
                models.append(
                    ModelDefinition(
                        name=class_name,
                        fields=fields,
                        source_file=str(file_path),
                        source_line=line_num,
                    )
                )

        return models

    def _extract_enums(
        self,
        content: str,
        file_path: Path,
    ) -> list[EnumDefinition]:
        """Extract enums from Python code."""
        enums: list[EnumDefinition] = []

        # Pattern for Enum class
        # class Status(str, Enum): or class Status(Enum):
        enum_pattern = re.compile(
            r"class\s+(\w+)\s*\([^)]*Enum[^)]*\)\s*:",
            re.MULTILINE,
        )

        # Pattern for enum values
        # VALUE = "value" or VALUE = 1
        value_pattern = re.compile(
            r"^\s+(\w+)\s*=\s*['\"]?(\w+)['\"]?",
            re.MULTILINE,
        )

        for enum_match in enum_pattern.finditer(content):
            enum_name = enum_match.group(1)

            # Find enum body
            start = enum_match.end()
            next_class = re.search(r"\nclass\s+\w+", content[start:])
            if next_class:
                end = start + next_class.start()
            else:
                end = len(content)

            enum_body = content[start:end]

            values: list[str] = []
            for value_match in value_pattern.finditer(enum_body):
                value_name = value_match.group(1)
                # Skip private and dunder
                if not value_name.startswith("_"):
                    values.append(value_name)

            if values:
                line_num = content[: enum_match.start()].count("\n") + 1
                enums.append(
                    EnumDefinition(
                        name=enum_name,
                        values=values,
                        source_file=str(file_path),
                        source_line=line_num,
                    )
                )

        return enums

    def _clean_type(self, type_str: str) -> str:
        """Clean Python type hint to contract type."""
        if not type_str:
            return "any"

        # Remove whitespace
        type_str = type_str.strip()

        # Handle Optional[T] -> T
        optional_match = re.match(r"Optional\[(.+)\]", type_str)
        if optional_match:
            return self._clean_type(optional_match.group(1))

        # Handle Union[T, None] -> T
        union_match = re.match(r"Union\[(.+),\s*None\]", type_str)
        if union_match:
            return self._clean_type(union_match.group(1))

        # Handle T | None -> T
        if " | None" in type_str:
            type_str = type_str.replace(" | None", "")
        if "None | " in type_str:
            type_str = type_str.replace("None | ", "")

        # Handle List[T] -> T
        list_match = re.match(r"[Ll]ist\[(.+)\]", type_str)
        if list_match:
            return self._clean_type(list_match.group(1))

        # Map Python types to contract primitives
        type_mapping = {
            "str": "string",
            "int": "int",
            "float": "float",
            "bool": "bool",
            "bytes": "bytes",
            "datetime": "datetime",
            "date": "date",
            "time": "time",
            "Decimal": "decimal",
            "UUID": "string",
            "Any": "any",
            "None": "void",
            "dict": "object",
            "Dict": "object",
        }

        return type_mapping.get(type_str, type_str)
