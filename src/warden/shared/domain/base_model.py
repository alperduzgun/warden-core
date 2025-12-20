"""
Base domain model with Panel JSON compatibility.

Provides automatic camelCase ↔ snake_case conversion for Panel integration.
All domain models should inherit from BaseDomainModel.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, asdict, fields
from datetime import datetime
from typing import Any, Dict, TypeVar, Type
from enum import Enum

T = TypeVar("T", bound="BaseDomainModel")


def to_camel_case(snake_str: str) -> str:
    """
    Convert snake_case to camelCase.

    Examples:
        >>> to_camel_case("file_path")
        'filePath'
        >>> to_camel_case("code_snippet")
        'codeSnippet'
    """
    components = snake_str.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def to_snake_case(camel_str: str) -> str:
    """
    Convert camelCase to snake_case.

    Examples:
        >>> to_snake_case("filePath")
        'file_path'
        >>> to_snake_case("codeSnippet")
        'code_snippet'
    """
    result = [camel_str[0].lower()]
    for char in camel_str[1:]:
        if char.isupper():
            result.extend(["_", char.lower()])
        else:
            result.append(char)
    return "".join(result)


@dataclass
class BaseDomainModel:
    """
    Base class for all domain models.

    Provides Panel JSON compatibility:
    - to_json() serializes to camelCase for Panel
    - from_json() deserializes from camelCase Panel JSON
    - Enum values are serialized as integers
    - Dates are serialized as ISO 8601 strings
    """

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON (camelCase).

        Returns:
            Dictionary with camelCase keys, Enum values as ints, dates as ISO strings
        """
        result: Dict[str, Any] = {}

        for field in fields(self):
            value = getattr(self, field.name)

            # Convert field name to camelCase
            json_key = to_camel_case(field.name)

            # Handle None
            if value is None:
                result[json_key] = None
                continue

            # Handle Enum - convert to int value
            if isinstance(value, Enum):
                result[json_key] = value.value

            # Handle datetime - convert to ISO 8601 string
            elif isinstance(value, datetime):
                result[json_key] = value.isoformat()

            # Handle list
            elif isinstance(value, list):
                result[json_key] = [
                    item.to_json() if isinstance(item, BaseDomainModel) else item
                    for item in value
                ]

            # Handle dict
            elif isinstance(value, dict):
                result[json_key] = {
                    k: v.to_json() if isinstance(v, BaseDomainModel) else v
                    for k, v in value.items()
                }

            # Handle nested domain model
            elif isinstance(value, BaseDomainModel):
                result[json_key] = value.to_json()

            # Primitive types
            else:
                result[json_key] = value

        return result

    @classmethod
    def from_json(cls: Type[T], data: Dict[str, Any]) -> T:
        """
        Deserialize from Panel JSON (camelCase) to Python model (snake_case).

        Args:
            data: Dictionary with camelCase keys from Panel

        Returns:
            Instance of the domain model with snake_case fields

        Raises:
            ValueError: If required fields are missing or invalid
        """
        kwargs: Dict[str, Any] = {}

        for field in fields(cls):
            # Convert snake_case field name to camelCase for lookup
            json_key = to_camel_case(field.name)

            # Get value from JSON data
            if json_key not in data:
                # Check if field has default value
                if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING:  # type: ignore[attr-defined]
                    continue
                raise ValueError(f"Missing required field: {json_key}")

            value = data[json_key]

            # Handle None
            if value is None:
                kwargs[field.name] = None
                continue

            # Handle Enum
            if hasattr(field.type, "__bases__") and Enum in field.type.__bases__:
                kwargs[field.name] = field.type(value)

            # Handle datetime
            elif field.type is datetime or (
                hasattr(field.type, "__origin__") and field.type.__origin__ is datetime
            ):
                if isinstance(value, str):
                    kwargs[field.name] = datetime.fromisoformat(value)
                else:
                    kwargs[field.name] = value

            # Handle list (nested models)
            elif hasattr(field.type, "__origin__") and field.type.__origin__ is list:
                kwargs[field.name] = value  # Simplified - override in subclass if needed

            # Primitive types
            else:
                kwargs[field.name] = value

        return cls(**kwargs)

    def __str__(self) -> str:
        """String representation for logging."""
        field_strs = [f"{field.name}={getattr(self, field.name)!r}" for field in fields(self)]
        return f"{self.__class__.__name__}({', '.join(field_strs)})"

    def __repr__(self) -> str:
        """Detailed representation for debugging."""
        return self.__str__()
